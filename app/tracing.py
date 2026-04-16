import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from traceloop.sdk import Traceloop
from traceloop.sdk.instruments import Instruments

from app.config import settings

_initialized = False
_logger_provider: LoggerProvider | None = None


def configure_tracer() -> None:
    """Configure OTEL traces, logs, and metrics — all exported to groundcover-sensor via gRPC 4317."""
    global _initialized, _logger_provider
    if _initialized:
        return

    os.environ.setdefault("OTEL_SERVICE_NAME", settings.service_name)

    # ── Shared resource attributes ────────────────────────────────────
    resource_attrs: dict[str, str] = {
        "service.name": settings.service_name,
        "service.version": settings.service_version,
    }

    k8s_mappings = {
        "K8S_POD_NAME": "k8s.pod.name",
        "K8S_POD_UID": "k8s.pod.uid",
        "K8S_NAMESPACE": "k8s.namespace.name",
        "K8S_NODE_NAME": "k8s.node.name",
        "K8S_CONTAINER_NAME": "k8s.container.name",
    }
    for env_var, attr_key in k8s_mappings.items():
        val = os.getenv(env_var)
        if val:
            resource_attrs[attr_key] = val

    resource = Resource.create(resource_attrs)

    # ── OTEL Logs SDK — trace-correlated logging via gRPC ─────────────
    log_exporter = OTLPLogExporter(
        endpoint=settings.otlp_endpoint,
        insecure=settings.otlp_insecure,
    )
    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(log_exporter)
    )
    otel_handler = LoggingHandler(logger_provider=_logger_provider)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )
    logging.getLogger().addHandler(otel_handler)

    # ── OTEL Metrics SDK — custom metrics via gRPC ────────────────────
    metric_exporter = OTLPMetricExporter(
        endpoint=settings.otlp_endpoint,
        insecure=settings.otlp_insecure,
    )
    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    # ── OTLP Trace exporter → groundcover-sensor (gRPC, port 4317) ───
    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        insecure=settings.otlp_insecure,
    )
    processor = BatchSpanProcessor(exporter)

    # ── Traceloop / OpenLLMetry init ─────────────────────────────────
    Traceloop.init(
        app_name=settings.service_name,
        exporter=exporter,
        processor=processor,
        telemetry_enabled=False,
        instruments={
            Instruments.BEDROCK,
            Instruments.URLLIB3,
        },
        resource_attributes=resource_attrs,
    )
    _initialized = True


def get_tracer():
    if not _initialized:
        configure_tracer()
    return trace.get_tracer(settings.service_name)


def get_meter():
    if not _initialized:
        configure_tracer()
    return metrics.get_meter(settings.service_name)
