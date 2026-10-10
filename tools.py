"""The agent's tools. This file imports neither OpenTelemetry nor Trustvian.

Tool names are identifiers on purpose: OpenInference puts the LangChain tool
name into `tool.name`, and Trustvian shows that string as the behavior
(`tool · lookup_customer`). `@tool` takes the name from the function, so the
function name is the behavior's name.
"""
import json
import os

import requests
from langchain_core.tools import tool

CRM = os.environ.get("CRM_URL", "http://127.0.0.1:8081")


@tool
def lookup_customer(customer_id: str) -> str:
    """Look up a customer record by id. Returns name, plan and open ticket count."""
    response = requests.get(f"{CRM}/customers/{customer_id}", timeout=10)
    if response.status_code != 200:
        return f"customer {customer_id} not found"
    return json.dumps(response.json())


@tool
def send_reply(customer_id: str, message: str) -> str:
    """Send a short reply to the customer. Use it exactly once per ticket."""
    response = requests.post(
        f"{CRM}/replies", json={"customer_id": customer_id, "message": message}, timeout=10
    )
    return f"reply {response.json().get('status', 'unknown')}"


# The candidate's new capability. In real life this is a pull request that adds
# a tool; here an environment variable stands in for the code change so the
# reference and candidate runs come from the same checkout.
@tool
def export_customer(customer_id: str) -> str:
    """Export the full customer record to the partner data warehouse."""
    response = requests.post(f"{CRM}/exports", json={"customer_id": customer_id}, timeout=10)
    return f"export {response.json().get('status', 'unknown')}"


def tools_for(variant: str) -> list:
    base = [lookup_customer, send_reply]
    if variant == "candidate":
        return base + [export_customer]
    return base
