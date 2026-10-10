"""Instrumentation harness: stands in for the tracing a framework would ship.

Everything here reads the environment `trustvian dev` hands the child:
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT   where spans go (dev's Collector)
  OTEL_RESOURCE_ATTRIBUTES             deployment.environment.name=local
  OTEL_SERVICE_NAME                    the agent identity (from --agent)
  OTEL_SEMCONV_STABILITY_OPT_IN=http   new HTTP attribute names
  OTEL_BSP_SCHEDULE_DELAY              short batch flush

graph.py and tools.py never import any of this. The harness turns on
LangChain (graph, node, model and tool spans: LangGraph runs on LangChain's
callbacks, so one instrumentor sees all of them) and requests (the HTTP
beneath each tool), then runs graph.py unchanged.

What reaches a span is decided by the OPENINFERENCE_HIDE_* variables the
instrumentor reads when it is turned on; see the README.

Usage:  trustvian dev --instrumentation existing --agent support-graph -- python run.py
"""
import atexit
import os
import runpy
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from openinference.instrumentation.langchain import LangChainInstrumentor


def instrument(provider: TracerProvider) -> None:
    """The instrumentors, on `provider`. The tests call this with an in-memory exporter."""
    LangChainInstrumentor().instrument(tracer_provider=provider)
    RequestsInstrumentor().instrument(tracer_provider=provider)


def main() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint:
        sys.exit(
            "run.py: no OTLP endpoint in the environment — run this under "
            "`trustvian dev --instrumentation existing -- python run.py`"
        )
    print(f"run.py: exporter → {endpoint}", flush=True)

    # Resource.create() reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES;
    # OTLPSpanExporter() reads the endpoint and protocol variables; the batch
    # processor reads OTEL_BSP_SCHEDULE_DELAY. Nothing is hard-coded here.
    provider = TracerProvider(resource=Resource.create())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    atexit.register(provider.shutdown)  # flush before the process exits

    instrument(provider)

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    runpy.run_path(os.path.join(here, "graph.py"), run_name="__main__")


if __name__ == "__main__":
    main()
