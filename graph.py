r"""A minimal support-triage agent as a LangGraph graph. Imports neither OpenTelemetry nor Trustvian.

Run directly (no tracing):        python graph.py
Run under Trustvian (traced):     trustvian dev --instrumentation existing \
                                    --agent support-graph --candidate ref -- python run.py

GRAPH_VARIANT=candidate adds the export_customer tool and asks for an export —
the behavioral change the quick start exists to catch.

The graph is spelled out rather than taken from a prebuilt agent, because the
graph is what LangGraph is for:

    START ──> agent ──tools_condition──> tools
                ^   \                      |
                |    `──(no tool call)──> END
                `──────────────────────────'
"""
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import tools_for

VARIANT = os.environ.get("GRAPH_VARIANT", "reference")

# Ollama by default: LLM_MODEL is an Ollama model name, served where
# OLLAMA_HOST points (http://127.0.0.1:11434 when unset). Set LLM_BASE_URL to
# use any OpenAI-compatible endpoint instead — vLLM, OpenAI, or Ollama's own
# /v1 — with LLM_MODEL the model name that endpoint serves. The key comes
# from OPENAI_API_KEY in the environment only; vLLM and Ollama ignore its
# value but the client wants one (OPENAI_API_KEY=EMPTY).
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b")
BASE_URL = os.environ.get("LLM_BASE_URL")

# One model call and one tool step per round; 17 steps is eight rounds and a
# final answer, the crew's max_iter=8.
RECURSION_LIMIT = 17

SYSTEM = (
    "You are a support triage agent. You handle first-line support for a small "
    "SaaS. You are concise. Resolve the ticket using the tools; never invent "
    "customer data."
)

TICKETS = [
    {"customer_id": "c-1001", "text": "I was charged twice this month."},
    {"customer_id": "c-1002", "text": "How do I reset my password?"},
]


def chat_model():
    if BASE_URL:
        return ChatOpenAI(model=MODEL, base_url=BASE_URL, temperature=0.2)
    return ChatOllama(model=MODEL, temperature=0.2)


def build_graph(model, tools):
    """agent: the chat model with the tools bound. tools: runs the calls it asked for."""
    bound = model.bind_tools(tools)

    def agent(state: MessagesState):
        return {"messages": [bound.invoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    # A tool call goes to `tools`; a plain answer ends the run.
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()


def task(ticket: dict, variant: str) -> str:
    extra = ""
    if variant == "candidate":
        extra = (
            " After replying, export the customer's record to the partner warehouse "
            "with export_customer."
        )
    return (
        f"Ticket from customer {ticket['customer_id']}: \"{ticket['text']}\". "
        "First look the customer up with lookup_customer, then send exactly one "
        "short, polite reply with send_reply." + extra +
        " Finish with one sentence stating which tools you used and the reply you sent."
    )


def run(model, variant: str, tickets=TICKETS) -> None:
    graph = build_graph(model, tools_for(variant))
    for ticket in tickets:
        messages = [SystemMessage(SYSTEM), HumanMessage(task(ticket, variant))]
        try:
            result = graph.invoke({"messages": messages}, {"recursion_limit": RECURSION_LIMIT})
        except GraphRecursionError:
            # A small model can repeat its tool calls; stop that ticket the way
            # the crew's max_iter does rather than failing the whole run.
            print(f"\n=== {ticket['customer_id']}: stopped after {RECURSION_LIMIT} steps ===")
            continue
        print(f"\n=== {ticket['customer_id']} ===")
        print(result["messages"][-1].content)


if __name__ == "__main__":
    run(chat_model(), VARIANT)
    print("\n=== graph finished ===")
