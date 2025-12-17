import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from traceloop.sdk import Traceloop
from traceloop.sdk.instruments import Instruments

from app.config import settings

_initialized = False


def configure_tracer() -> None:
    """
    Configure OpenLLMetry (Traceloop) to export OTLP traces directly to groundcover-sensor.

    We explicitly provide an OTLP exporter+processor so Traceloop doesn't require a Traceloop SaaS API key.
    OpenLLMetry repo: https://github.com/traceloop/openllmetry
    """
    global _initialized
    if _initialized:
        return

    os.environ.setdefault("OTEL_SERVICE_NAME", settings.service_name)

    exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=settings.otlp_insecure)
    processor = BatchSpanProcessor(exporter)

    Traceloop.init(
        app_name=settings.service_name,
        exporter=exporter,
        processor=processor,
        telemetry_enabled=False,
        # Enable Bedrock instrumentation (and leave the rest alone).
        instruments={Instruments.BEDROCK},
        resource_attributes={"service.name": settings.service_name},
    )
    _initialized = True


def get_tracer():
    if not _initialized:
        configure_tracer()
    return trace.get_tracer(settings.service_name)

