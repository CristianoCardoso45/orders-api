import sys

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def setup_tracing(service_name: str = "order-service", enabled: bool = False) -> None:
    if not enabled:
        return
    """
    Configures OpenTelemetry tracing with Console Exporter.

    Tracing is disabled by default (enabled=False). Set OTEL_ENABLED=true
    in the environment to activate it. In production, swap ConsoleSpanExporter
    for an OTLP exporter without changing any other code.

    Args:
        service_name: Service name used to identify spans.
        enabled: If False, tracing is skipped entirely.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    trace.set_tracer_provider(provider)
