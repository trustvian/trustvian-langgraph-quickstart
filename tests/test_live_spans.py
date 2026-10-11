"""Live mode's graph, per role, under run.py's instrumentation with a scripted model.

The same checks as test_spans.py, for the tickets live.py's workers handle: a
TOOL span per tool call, an LLM span per model call, export_customer only on a
drift ticket, and no ticket text, reply text or tool argument in any span.
"""
import pytest

import graph
import mock_services
import roles
from test_spans import REDACTED, ScriptedChatModel, call, of_kind, tool_names
from langchain_core.messages import AIMessage

CUSTOMER = "c-1003"
TICKET = "SENTINEL-LIVE-TICKET-81f3: the invoice for March is missing"
REPLY = "SENTINEL-LIVE-REPLY-2be7: here is how to fix it"
INVOICE = "SENTINEL-LIVE-INVOICE-90aa"
PLAN = "SENTINEL-LIVE-PLAN-77c1"
ANSWER = "SENTINEL-LIVE-ANSWER-d41e: done"
PLANTED = (TICKET, REPLY, INVOICE, PLAN, ANSWER)

# What the scripted model asks for after lookup_customer, per role.
ROLE_CALLS = {
    "support": [("send_reply", {"customer_id": CUSTOMER, "message": REPLY})],
    "billing": [("lookup_invoice", {"customer_id": CUSTOMER}),
                ("issue_refund", {"customer_id": CUSTOMER, "invoice_id": INVOICE})],
    "accounts": [("change_plan", {"customer_id": CUSTOMER, "plan": PLAN})],
}


def live_ticket(monkeypatch, role: str, drift: bool) -> dict:
    """A ticket of `role` whose text is the sentinel; ticket 20 drifts at the default."""
    monkeypatch.setitem(roles.ROLES[role], "tickets", [(CUSTOMER, TICKET)])
    import random
    return roles.ticket(role, 20 if drift else 1, random.Random(0), drift_every=20)


def script(role: str, drift: bool) -> ScriptedChatModel:
    responses = [call("lookup_customer", "1", customer_id=CUSTOMER)]
    for i, (name, args) in enumerate(ROLE_CALLS[role], start=2):
        responses.append(call(name, str(i), **args))
    if drift:
        responses.append(call("export_customer", "9", customer_id=CUSTOMER))
    responses.append(AIMessage(ANSWER))
    return ScriptedChatModel(responses=responses)


def run_ticket(monkeypatch, role: str, drift: bool = False) -> int:
    ticket = live_ticket(monkeypatch, role, drift)
    model = script(role, drift)
    graph.live_handler(model)(ticket)
    return len(model.responses)


@pytest.mark.parametrize("role", ["support", "billing", "accounts"])
def test_each_role_emits_its_tools_and_model_calls(spans, monkeypatch, role):
    model_calls = run_ticket(monkeypatch, role)
    finished = spans()
    assert tool_names(finished) == ["lookup_customer"] + [name for name, _ in ROLE_CALLS[role]]
    assert len(of_kind(finished, "LLM")) == model_calls


def test_a_drift_ticket_adds_export_customer_to_billing(spans, monkeypatch):
    run_ticket(monkeypatch, "billing", drift=True)
    assert tool_names(spans())[-1] == "export_customer"


def test_a_normal_billing_ticket_cannot_export(spans, monkeypatch):
    ticket = live_ticket(monkeypatch, "billing", drift=False)
    assert "export_customer" not in ticket["tools"]
    assert "export_customer" not in ticket["task"]


def test_a_failed_crm_call_is_a_tool_span_not_a_crash(spans, monkeypatch):
    monkeypatch.setattr(mock_services, "ERROR_RATE", 1.0)
    run_ticket(monkeypatch, "billing")
    finished = spans()
    assert tool_names(finished) == ["lookup_customer", "lookup_invoice", "issue_refund"]
    # Old or new HTTP attribute name, depending on OTEL_SEMCONV_STABILITY_OPT_IN.
    statuses = [s.attributes.get("http.response.status_code") or s.attributes.get("http.status_code")
                for s in finished if s.attributes.get("http.method") or s.attributes.get("http.request.method")]
    assert sorted(set(statuses)) == [429, 503]


@pytest.mark.parametrize("role", ["support", "billing", "accounts"])
def test_no_content_reaches_a_span_in_live_mode(spans, monkeypatch, role):
    run_ticket(monkeypatch, role, drift=role == "billing")
    finished = spans()
    assert finished
    for span in finished:
        for key, value in span.attributes.items():
            assert not key.startswith(("llm.input_messages", "llm.output_messages",
                                       "llm.prompts", "tool.parameters")), key
            if key in ("input.value", "output.value"):
                assert value == REDACTED, (span.name, key)
            text = str(value)
            for planted in PLANTED:
                assert planted not in text, (span.name, key)
            # As in test_spans.py: the customer id reaches only the URL of the
            # GET the tool itself makes (/customers/<id>, /invoices/<id>).
            if CUSTOMER in text:
                assert key in ("http.url", "url.full"), (span.name, key)
        assert all(p not in span.name for p in PLANTED + (CUSTOMER,))
        for event in span.events:
            for value in event.attributes.values():
                assert all(p not in str(value) for p in PLANTED)
