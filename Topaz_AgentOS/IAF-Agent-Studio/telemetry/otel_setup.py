"""OpenTelemetry SDK wiring — configured only through the standard OTEL_* variables.

Enable with TELEMETRY_EXPORTERS=local,otel. Everything else uses the variables every
vendor's documentation already describes, so a customer can follow their vendor's
guide unchanged:

  OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://otel-collector:4318
  OTEL_EXPORTER_OTLP_HEADERS    e.g. Authorization=Basic%20...   (vendor auth)
  OTEL_SERVICE_NAME             default: iaf-agent-studio
  OTEL_RESOURCE_ATTRIBUTES      e.g. deployment.environment.name=prod
  OTEL_TRACES_SAMPLER           e.g. parentbased_traceidratio (+ OTEL_TRACES_SAMPLER_ARG)
  OTEL_METRICS_EXPORTER         otlp (default) | none
  OTEL_LOGS_EXPORTER            none (default) | otlp  — application logs over OTLP
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT   false (default) | true

Exporting happens on the SDK's background threads (batch processors with bounded
queues), so a slow or unreachable collector can never slow a request.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

# Lets the trace bridge keep AgentOS trace IDs as OTel trace IDs (same ID in our UI and
# in the vendor's), and choose span IDs so parent/child links can be built after the fact.
_FORCED_TRACE_ID: ContextVar[int] = ContextVar("agentos_otel_trace_id", default=0)
_FORCED_SPAN_ID: ContextVar[int] = ContextVar("agentos_otel_span_id", default=0)

AUDIT_LOGGER_NAME = "agentos.audit"

_STATE: dict[str, Any] = {
    "configured": False,
    "tracer_provider": None,
    "meter_provider": None,
    "logger_provider": None,
    "instrumented_app": False,
    "log_handler": None,
    "error": "",
}


def otel_selected(exporters: str) -> bool:
    """True when the TELEMETRY_EXPORTERS list asks for OpenTelemetry."""
    selected = {item.strip().lower() for item in (exporters or "").split(",") if item.strip()}
    # "otlp"/"otlp_json" were the names of the old non-standard adapter; keep them as aliases.
    return bool(selected & {"otel", "otlp", "otlp_json"})


def capture_content_enabled() -> bool:
    return os.getenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false").strip().lower() == "true"


def _apply_legacy_settings(legacy_endpoint: str, legacy_service_name: str) -> None:
    """Map the old TELEMETRY_OTLP_* settings onto the standard variables (standard wins)."""
    if legacy_endpoint and not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        base = legacy_endpoint.rstrip("/")
        for suffix in ("/v1/traces", "/v1/metrics", "/v1/logs"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = base
    if legacy_service_name and not os.getenv("OTEL_SERVICE_NAME"):
        os.environ["OTEL_SERVICE_NAME"] = legacy_service_name


class _NotOurTelemetry(logging.Filter):
    """Keep the exporter's own logs out of the log pipeline (no feedback loop)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(("opentelemetry", "urllib3", "requests"))


def make_id_generator():
    """Random ids, except when the trace bridge pins one (to keep AgentOS ids in OTel)."""
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    class _AgentOSIdGenerator(RandomIdGenerator):
        def generate_trace_id(self) -> int:
            return _FORCED_TRACE_ID.get() or super().generate_trace_id()

        def generate_span_id(self) -> int:
            return _FORCED_SPAN_ID.get() or super().generate_span_id()

    return _AgentOSIdGenerator()


def configure_otel(
    *,
    legacy_endpoint: str = "",
    legacy_service_name: str = "",
    service_version: str = "",
    tenant_id: str = "",
    export_audit: str = "off",
) -> bool:
    """Install the global tracer/meter/(logger) providers. Idempotent; never raises."""
    if _STATE["configured"]:
        return True
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        _STATE["error"] = f"OpenTelemetry SDK not installed: {exc}"
        logger.warning("Telemetry: %s — OTel export disabled (pip install -r requirements.txt)", _STATE["error"])
        return False

    try:
        _apply_legacy_settings(legacy_endpoint, legacy_service_name)
        os.environ.setdefault("OTEL_SERVICE_NAME", "iaf-agent-studio")
        attrs: dict[str, str] = {}
        if service_version:
            attrs["service.version"] = service_version
        if tenant_id:
            attrs["agentos.tenant"] = tenant_id
        # Resource.create also merges OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES.
        resource = Resource.create(attrs)

        # Sampler comes from OTEL_TRACES_SAMPLER when set (SDK default: parentbased_always_on).
        tracer_provider = TracerProvider(resource=resource, id_generator=make_id_generator())
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)
        _STATE["tracer_provider"] = tracer_provider

        if os.getenv("OTEL_METRICS_EXPORTER", "otlp").strip().lower() != "none":
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
            )
            metrics.set_meter_provider(meter_provider)
            _STATE["meter_provider"] = meter_provider

        app_logs = os.getenv("OTEL_LOGS_EXPORTER", "none").strip().lower() == "otlp"
        audit_logs = (export_audit or "off").strip().lower() in ("denials", "all")
        if app_logs or audit_logs:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider
            try:  # the SDK's handler is deprecated in favour of the instrumentation package's
                from opentelemetry.instrumentation.logging.handler import LoggingHandler
            except ImportError:
                from opentelemetry.sdk._logs import LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

            logger_provider = LoggerProvider(resource=resource)
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
            set_logger_provider(logger_provider)
            _STATE["logger_provider"] = logger_provider
            handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
            handler.addFilter(_NotOurTelemetry())
            _STATE["log_handler"] = handler
            if app_logs:
                logging.getLogger().addHandler(handler)
            if audit_logs:
                logging.getLogger(AUDIT_LOGGER_NAME).addHandler(handler)

        _STATE["configured"] = True
        # Flush and detach before interpreter teardown: otherwise a late log record (e.g. a
        # connection pool's __del__ warning) reaches the OTel handler mid-shutdown.
        import atexit
        atexit.register(shutdown_otel)
        logger.info(
            "Telemetry: OpenTelemetry export ON — service=%s endpoint=%s metrics=%s logs=%s audit=%s",
            os.getenv("OTEL_SERVICE_NAME"),
            os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "(SDK default http://localhost:4318)",
            bool(_STATE["meter_provider"]), app_logs, export_audit,
        )
        return True
    except Exception as exc:  # telemetry must never stop the server from starting
        _STATE["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Telemetry: OpenTelemetry setup failed (export disabled): %s", _STATE["error"])
        return False


def instrument_app(app) -> None:
    """Standard HTTP server spans for API requests + traceparent on outgoing httpx calls."""
    if not _STATE["configured"] or _STATE["instrumented_app"]:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        FastAPIInstrumentor.instrument_app(
            app, excluded_urls="health/live,health,metrics,static/.*",
        )
        HTTPXClientInstrumentor().instrument()
        # Adds otelTraceID/otelSpanID to every LogRecord (used by our log formatters).
        LoggingInstrumentor().instrument(set_logging_format=False)
        _STATE["instrumented_app"] = True
    except Exception as exc:
        logger.warning("Telemetry: HTTP instrumentation failed (traces still exported): %s", exc)


def shutdown_otel() -> None:
    """Flush pending telemetry at shutdown (bounded by the SDK's export timeouts). Idempotent."""
    handler = _STATE.get("log_handler")
    if handler is not None:
        for name in ("", AUDIT_LOGGER_NAME):
            logging.getLogger(name).removeHandler(handler)
        _STATE["log_handler"] = None
    for key in ("tracer_provider", "meter_provider", "logger_provider"):
        provider = _STATE.get(key)
        if provider is None:
            continue
        try:
            provider.shutdown()
        except Exception as exc:
            logger.debug("Telemetry: %s shutdown failed: %s", key, exc)
        _STATE[key] = None


def otel_diagnostics() -> dict[str, Any]:
    """Safe status for capability snapshots — never includes headers or credentials."""
    return {
        "configured": _STATE["configured"],
        "endpoint_configured": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")),
        "service_name": os.getenv("OTEL_SERVICE_NAME", ""),
        "metrics": bool(_STATE["meter_provider"]),
        "logs": bool(_STATE["logger_provider"]),
        "http_instrumented": _STATE["instrumented_app"],
        "capture_content": capture_content_enabled(),
        "error": _STATE["error"],
    }
