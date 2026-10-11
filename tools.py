"""The agent's tools. This file imports neither OpenTelemetry nor Trustvian.

Tool names are identifiers on purpose: OpenInference puts the LangChain tool
name into `tool.name`, and Trustvian shows that string as the behavior
(`tool · lookup_customer`). `@tool` takes the name from the function, so the
function name is the behavior's name.

A tool never raises: an error from the CRM (live mode's occasional 503 or
429) comes back to the model as a short failure string.
"""
import json
import os

import requests
from langchain_core.tools import tool

CRM = os.environ.get("CRM_URL", "http://127.0.0.1:8081")

# Every call as (tool name, succeeded), for live mode's line per ticket.
CALLS = []


def _crm(method: str, path: str, **kwargs):
    """(status, body) from the CRM; status 0 when it could not be reached."""
    try:
        response = requests.request(method, f"{CRM}{path}", timeout=10, **kwargs)
    except requests.RequestException:
        return 0, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {}


def _result(name: str, ok: bool, text: str) -> str:
    CALLS.append((name, ok))
    return text


def _failed(name: str, status: int) -> str:
    reason = "the CRM is unreachable" if status == 0 else f"the CRM answered {status}"
    return _result(name, False, f"{name} failed: {reason}; try again later")


@tool
def lookup_customer(customer_id: str) -> str:
    """Look up a customer record by id. Returns name, plan and open ticket count."""
    status, body = _crm("GET", f"/customers/{customer_id}")
    if status == 200:
        return _result("lookup_customer", True, json.dumps(body))
    if status == 404:
        return _result("lookup_customer", True, f"customer {customer_id} not found")
    return _failed("lookup_customer", status)


@tool
def send_reply(customer_id: str, message: str) -> str:
    """Send a short reply to the customer. Use it exactly once per ticket."""
    status, body = _crm("POST", "/replies", json={"customer_id": customer_id, "message": message})
    if status in (200, 201):
        return _result("send_reply", True, f"reply {body.get('status', 'unknown')}")
    return _failed("send_reply", status)


# The candidate's new capability. In real life this is a pull request that adds
# a tool; here an environment variable stands in for the code change so the
# reference and candidate runs come from the same checkout.
@tool
def export_customer(customer_id: str) -> str:
    """Export the full customer record to the partner data warehouse."""
    status, body = _crm("POST", "/exports", json={"customer_id": customer_id})
    if status in (200, 201):
        return _result("export_customer", True, f"export {body.get('status', 'unknown')}")
    return _failed("export_customer", status)


# Live mode's billing and accounts tools.
@tool
def lookup_invoice(customer_id: str) -> str:
    """List a customer's invoices: id, month, amount and status."""
    status, body = _crm("GET", f"/invoices/{customer_id}")
    if status == 200:
        return _result("lookup_invoice", True, json.dumps(body["invoices"]))
    if status == 404:
        return _result("lookup_invoice", True, f"customer {customer_id} not found")
    return _failed("lookup_invoice", status)


@tool
def issue_refund(customer_id: str, invoice_id: str) -> str:
    """Refund one invoice of a customer."""
    status, body = _crm("POST", "/refunds", json={"customer_id": customer_id, "invoice_id": invoice_id})
    if status in (200, 201):
        return _result("issue_refund", True, f"refund {body.get('status', 'unknown')}")
    return _failed("issue_refund", status)


@tool
def change_plan(customer_id: str, plan: str) -> str:
    """Change a customer's subscription plan to free, pro or team."""
    status, body = _crm("POST", "/plans", json={"customer_id": customer_id, "plan": plan})
    if status in (200, 201):
        return _result("change_plan", True, f"plan {body.get('status', 'unknown')}")
    if status == 400:
        return _result("change_plan", True, "plan must be one of free, pro, team")
    return _failed("change_plan", status)


TOOLS = {
    t.name: t
    for t in (lookup_customer, send_reply, export_customer, lookup_invoice, issue_refund, change_plan)
}


def tools_for(variant: str) -> list:
    base = [lookup_customer, send_reply]
    if variant == "candidate":
        return base + [export_customer]
    return base


def tools_named(names: list) -> list:
    """Live mode: the tools a role's ticket binds, by name (roles.py)."""
    return [TOOLS[name] for name in names]
