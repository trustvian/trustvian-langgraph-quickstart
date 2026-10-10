"""What graph.py emits under run.py: one TOOL span per tool call, one LLM span per
model call, and no content.

The model is scripted, so each test knows exactly which tools were called and
how many times the model answered.
"""
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

import graph
from conftest import shipped_settings

SPAN_KIND = "openinference.span.kind"
REDACTED = "__REDACTED__"  # what OpenInference writes in place of a hidden value

# Planted where content lives: the ticket the user wrote, the reply the model
# composes as a tool argument, and the model's final answer.
TICKET = "SENTINEL-TICKET-4e1b9c: my invoice shows a charge twice"
REPLY = "SENTINEL-REPLY-7d20aa: sorry about that, a refund is on its way"
ANSWER = "SENTINEL-ANSWER-c35f02: used lookup_customer and send_reply"
CUSTOMER = "c-1001"
CUSTOMER_NAME = "Alice Carter"  # in lookup_customer's output, from the CRM


class ScriptedChatModel(FakeMessagesListChatModel):
    """Answers with the next scripted AIMessage. Binding tools changes nothing:
    the script already says which tools are called."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_model_name"] = "scripted-model"
        return params


def call(name: str, call_id: str, **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


def script(variant: str) -> ScriptedChatModel:
    responses = [
        call("lookup_customer", "1", customer_id=CUSTOMER),
        call("send_reply", "2", customer_id=CUSTOMER, message=REPLY),
    ]
    if variant == "candidate":
        responses.append(call("export_customer", "3", customer_id=CUSTOMER))
    responses.append(AIMessage(ANSWER))
    return ScriptedChatModel(responses=responses)


def run_graph(variant: str) -> int:
    """Runs one ticket; returns how many times the model is called."""
    model = script(variant)
    graph.run(model, variant, tickets=[{"customer_id": CUSTOMER, "text": TICKET}])
    return len(model.responses)


def of_kind(spans, kind: str) -> list:
    return [s for s in spans if s.attributes.get(SPAN_KIND) == kind]


def tool_names(spans) -> list:
    return [s.attributes.get("tool.name") for s in of_kind(spans, "TOOL")]


def test_reference_emits_a_tool_span_per_tool_and_an_llm_span_per_model_call(spans):
    model_calls = run_graph("reference")
    finished = spans()

    assert tool_names(finished) == ["lookup_customer", "send_reply"]
    llm = of_kind(finished, "LLM")
    assert len(llm) == model_calls == 3
    assert {s.attributes.get("llm.model_name") for s in llm} == {"scripted-model"}


def test_candidate_adds_an_export_customer_tool_span(spans):
    run_graph("candidate")
    candidate = tool_names(spans())
    assert candidate == ["lookup_customer", "send_reply", "export_customer"]


def test_reference_emits_no_export_customer_span(spans):
    run_graph("reference")
    assert "export_customer" not in tool_names(spans())


def test_no_content_reaches_a_span(spans):
    run_graph("candidate")
    finished = spans()
    assert finished

    for span in finished:
        for key, value in span.attributes.items():
            # Messages are dropped outright; input.value / output.value are
            # kept as a key whose value is OpenInference's fixed marker.
            assert not key.startswith(("llm.input_messages", "llm.output_messages")), key
            assert not key.startswith(("llm.prompts", "tool.parameters")), key
            if key in ("input.value", "output.value"):
                assert value == REDACTED, (span.name, key)

            text = str(value)
            for planted in (TICKET, REPLY, ANSWER, CUSTOMER_NAME):
                assert planted not in text, (span.name, key)
            # The customer id is a tool argument. It reaches exactly one place:
            # the URL of the HTTP request the tool itself makes.
            if CUSTOMER in text:
                assert key in ("http.url", "url.full"), (span.name, key)

        assert all(planted not in span.name for planted in (TICKET, REPLY, ANSWER, CUSTOMER))
        for event in span.events:
            for value in event.attributes.values():
                assert all(p not in str(value) for p in (TICKET, REPLY, ANSWER, CUSTOMER_NAME))


def test_the_shipped_configuration_hides_content_and_disables_the_framework_tracer():
    settings = shipped_settings()
    assert settings == {
        "LANGSMITH_TRACING": "false",
        "OPENINFERENCE_HIDE_INPUTS": "true",
        "OPENINFERENCE_HIDE_OUTPUTS": "true",
        "OPENINFERENCE_HIDE_INPUT_MESSAGES": "true",
        "OPENINFERENCE_HIDE_OUTPUT_MESSAGES": "true",
    }
