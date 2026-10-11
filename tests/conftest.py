"""Runs graph.py under run.py's instrumentation, with a scripted model and spans kept in memory.

No model server, no Trustvian, no network beyond loopback: the fake CRM runs
in a thread on a free port, and the chat model is a script of AIMessages
whose tool_calls the graph executes for real.
"""
import os
import re
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The settings that keep content out of spans, taken from the agent service in
# compose.yaml — the configuration the stack ships — rather than restated
# here, so a test run and a Compose run cannot drift apart. The instrumentor
# reads them once, when it is turned on, so they are set before anything else.
CONTENT_SETTINGS = ("LANGSMITH_TRACING", "OPENINFERENCE_HIDE_")


def shipped_settings() -> dict:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    environment = compose["services"]["agent"]["environment"]
    settings = {}
    for key, value in environment.items():
        if key.startswith(CONTENT_SETTINGS):
            # ${NAME:-default} → default: what Compose uses without a .env.
            match = re.fullmatch(r"\$\{\w+:-(.*)\}", str(value))
            settings[key] = match.group(1) if match else str(value)
    return settings


os.environ.update(shipped_settings())
os.environ.pop("LANGCHAIN_TRACING_V2", None)

# No injected CRM errors: each test decides which calls fail (test_live_*).
os.environ["CRM_ERROR_RATE"] = "0"
import mock_services  # noqa: E402

_crm = HTTPServer(("127.0.0.1", 0), mock_services.Handler)
threading.Thread(target=_crm.serve_forever, daemon=True).start()
# tools.py reads CRM_URL when it is imported, so this precedes that import.
os.environ["CRM_URL"] = f"http://127.0.0.1:{_crm.server_address[1]}"

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

import run  # noqa: E402

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
run.instrument(_provider)  # the harness's own setup, with an in-memory exporter


@pytest.fixture
def spans():
    """The finished spans of whatever the test ran."""
    _exporter.clear()
    yield _exporter.get_finished_spans
    _exporter.clear()
