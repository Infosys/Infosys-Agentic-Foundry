# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import logging
import os
import atexit
import json
import contextvars
from functools import wraps
import threading
import uuid
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv


load_dotenv()

# Constant server name (can be overridden by env var)
SERVER_NAME = os.getenv("SERVER_NAME", "localhost")

# --- Environment Configuration ---
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


def format_error(e: Exception) -> str:
    """Format exception based on environment.
    
    In development: returns repr(e) for detailed debugging info.
    In production: returns str(e) for cleaner logs.
    """
    if ENVIRONMENT == "development":
        return repr(e)
    return str(e)


def is_development() -> bool:
    """Check if current environment is development."""
    return ENVIRONMENT == "development"


# --- Global Configuration Flags ---
ENABLE_LOGGING = os.getenv("ENABLE_LOGGING", "True").lower() == "true"
# TELEMETRY_BACKEND: "elasticsearch" (default) or "azure"
TELEMETRY_BACKEND = os.getenv("TELEMETRY_BACKEND", "elasticsearch").lower()

# Conditional imports based on backend
AZURE_MONITOR_AVAILABLE = False  # Default to False

_base_logger = logging.getLogger("agentic_workflow_logger")

if TELEMETRY_BACKEND == "elasticsearch":
    from opentelemetry import trace, _logs
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    USE_OTEL_LOGGING = os.getenv("USE_OTEL_LOGGING", "True").lower() == "true"

elif TELEMETRY_BACKEND == "azure":
    # Azure Monitor OpenTelemetry SDK
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry._logs import LogRecord as OTelLogRecord, SeverityNumber
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.trace import TraceFlags
        from opentelemetry import _logs
        AZURE_MONITOR_AVAILABLE = True
    except ImportError as e:
        _base_logger.warning(f"[WARNING] azure-monitor-opentelemetry not installed or import error: {e}. "
              "Install with: pip install azure-monitor-opentelemetry")
    USE_OTEL_LOGGING = True

else:
    # Unknown backend - still import base opentelemetry for type hints
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    USE_OTEL_LOGGING = False
    _base_logger.warning(f"[WARNING] Unknown TELEMETRY_BACKEND: {TELEMETRY_BACKEND}. Telemetry disabled.")

# --- 1. OpenTelemetryManager Class ---
class OpenTelemetryManager:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(OpenTelemetryManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._otel_logger_provider = None
        self._otel_tracer_provider = None
        self._tracer = None
        self._azure_handler = None
        self._initialized = True

    def setup_tracing(self, service_name: str = "agentic-workflow-service"):
        """
        Initializes the OpenTelemetry tracing workflow. Should be called once.
        """
        if self._otel_tracer_provider:
            logger.debug("OpenTelemetry Tracing already initialized.")
            return self._otel_tracer_provider

        logger.info(f"[OTel:Tracing] INIT START | service={service_name}, backend={TELEMETRY_BACKEND}, server={SERVER_NAME}")
        resource = Resource(attributes={SERVICE_NAME: service_name, "host.name": SERVER_NAME, "service.instance.id": SERVER_NAME})

        if TELEMETRY_BACKEND == "elasticsearch":
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            
            self._otel_tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(self._otel_tracer_provider)
            otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
            logger.info(f"[OTel:Tracing] Connecting to OTLP trace endpoint: {otlp_endpoint or 'NOT SET'}")
            if not otlp_endpoint:
                logger.warning("[OTel:Tracing] WARNING: OTEL_EXPORTER_OTLP_TRACES_ENDPOINT not configured - traces will not be exported")
            exporter_args = {"endpoint": otlp_endpoint}
            headers_str = os.getenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
            if headers_str:
                try:
                    exporter_args["headers"] = dict(item.split("=", 1) for item in headers_str.split(","))
                    logger.info(f"[OTel:Tracing] Custom headers configured: {list(exporter_args['headers'].keys())}")
                except ValueError:
                    logger.error("[OTel:Tracing] FAILED: Invalid format for OTEL_EXPORTER_OTLP_TRACES_HEADERS. Expected: key1=value1,key2=value2")
            try:
                logger.info(f"[OTel:Tracing] Creating OTLPSpanExporter (HTTP/protobuf) -> {otlp_endpoint}")
                span_exporter = OTLPSpanExporter(**exporter_args)
                self._otel_tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
                logger.info(f"[OTel:Tracing] SUCCESS: BatchSpanProcessor attached")
            except Exception as e:
                logger.error(f"[OTel:Tracing] FAILED: Could not initialize OTLP span exporter: {e}", exc_info=True)
                logger.error(f"[OTel:Tracing] TROUBLESHOOT: Is the endpoint {otlp_endpoint} reachable? Is the port open?")
                
        elif TELEMETRY_BACKEND == "azure":
            logger.info("[OTel:Tracing] Azure backend: Tracing will be configured with Azure Monitor in setup_logging().")

        self._tracer = trace.get_tracer(__name__)
        logger.info(f"[OTel:Tracing] INIT COMPLETE | backend={TELEMETRY_BACKEND}, tracer_ready={self._tracer is not None}")
        return self._otel_tracer_provider

    def setup_logging(self, service_name: str = "agentic-workflow-service", use_http: bool = True):
        """
        Initializes the OpenTelemetry logging workflow. Should be called once.
        """
        if self._otel_logger_provider:
            logger.debug("OpenTelemetry Logging already initialized.")
            return self._otel_logger_provider

        logger.info(f"[OTel:Logging] INIT START | service={service_name}, backend={TELEMETRY_BACKEND}, protocol={'HTTP' if use_http else 'gRPC'}")
        resource = Resource(attributes={SERVICE_NAME: service_name, "host.name": SERVER_NAME, "service.instance.id": SERVER_NAME})

        if TELEMETRY_BACKEND == "elasticsearch":
            from opentelemetry import _logs
            from opentelemetry.sdk._logs import LoggerProvider
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP
            
            ExporterClass = OTLPLogExporterHTTP
            default_endpoint = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP")
            env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP"
            protocol = "HTTP"

            if not use_http:
                try:
                    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as OTLPLogExporterGRPC
                    ExporterClass = OTLPLogExporterGRPC
                    default_endpoint = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC")
                    env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC"
                    protocol = "gRPC"
                    logger.info(f"[OTel:Logging] gRPC exporter loaded successfully")
                except ImportError as ie:
                    logger.error(f"[OTel:Logging] FAILED: gRPC Exporter import failed: {ie}. Falling back to HTTP.", exc_info=True)

            otlp_endpoint = os.getenv(env_var_name, default_endpoint)
            logger.info(f"[OTel:Logging] Target endpoint: {otlp_endpoint or 'NOT SET'} (protocol={protocol}, env_var={env_var_name})")
            if not otlp_endpoint:
                logger.error(f"[OTel:Logging] FAILED: {env_var_name} not configured - logs will not be exported to collector")
                return None
            exporter_args = {"endpoint": otlp_endpoint}

            headers_str = os.getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS")
            if headers_str:
                try:
                    exporter_args["headers"] = dict(item.split("=", 1) for item in headers_str.split(","))
                    logger.info(f"[OTel:Logging] Custom headers configured: {list(exporter_args['headers'].keys())}")
                except ValueError:
                    logger.error("[OTel:Logging] FAILED: Invalid format for OTEL_EXPORTER_OTLP_LOGS_HEADERS. Expected: key1=value1,key2=value2")

            try:
                logger.info(f"[OTel:Logging] Creating {ExporterClass.__name__} -> {otlp_endpoint}")
                log_exporter = ExporterClass(**exporter_args)
                self._otel_logger_provider = LoggerProvider(resource=resource)
                _logs.set_logger_provider(self._otel_logger_provider)
                self._otel_logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
                logger.info(f"[OTel:Logging] INIT COMPLETE | Elasticsearch log pipeline ready ({protocol} -> {otlp_endpoint})")
            except Exception as e:
                logger.error(f"[OTel:Logging] FAILED: Could not initialize OTLP log exporter ({protocol}): {e}", exc_info=True)
                logger.error(f"[OTel:Logging] TROUBLESHOOT: Verify endpoint {otlp_endpoint} is reachable, port is open, and collector is running")
                return None

        elif TELEMETRY_BACKEND == "azure":
            if not AZURE_MONITOR_AVAILABLE:
                logger.error("[OTel:Logging] FAILED: Azure Monitor SDK not available. Install: pip install azure-monitor-opentelemetry")
                return None
                
            connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
            if not connection_string:
                logger.error("[OTel:Logging] FAILED: APPLICATIONINSIGHTS_CONNECTION_STRING not set in environment. Azure Monitor logging disabled.")
                return None
            
            masked_cs = connection_string[:50] + "..." if len(connection_string) > 50 else connection_string
            logger.info(f"[OTel:Logging] Connecting to Azure Monitor (connection_string={masked_cs})")
                
            try:
                from opentelemetry.sdk._logs import LoggerProvider
                from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
                from opentelemetry import _logs
                from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
                
                logger.info(f"[OTel:Logging] Creating AzureMonitorLogExporter...")
                azure_exporter = AzureMonitorLogExporter(connection_string=connection_string)
                self._otel_logger_provider = LoggerProvider(resource=resource)
                _logs.set_logger_provider(self._otel_logger_provider)
                self._otel_logger_provider.add_log_record_processor(BatchLogRecordProcessor(azure_exporter))
                logger.info(f"[OTel:Logging] INIT COMPLETE | Azure Monitor log pipeline ready")
            except Exception as e:
                logger.error(f"[OTel:Logging] FAILED: Could not initialize Azure Monitor logging: {e}", exc_info=True)
                logger.error(f"[OTel:Logging] TROUBLESHOOT: Verify connection string, network connectivity to Azure, and SDK version compatibility")
                return None

        return self._otel_logger_provider

    def get_tracer(self):
        return self._tracer

    def get_logger_provider(self):
        return self._otel_logger_provider

    def get_azure_handler(self):
        """Returns the Azure-specific logging handler if configured."""
        return self._azure_handler

    def log_startup_diagnostics(self):
        """Log a comprehensive diagnostics summary of OTel configuration at startup."""
        logger.info("=" * 80)
        logger.info("[OTel:Diagnostics] OPENTELEMETRY CONFIGURATION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"[OTel:Diagnostics]   ENABLE_LOGGING          = {ENABLE_LOGGING}")
        logger.info(f"[OTel:Diagnostics]   TELEMETRY_BACKEND       = {TELEMETRY_BACKEND}")
        logger.info(f"[OTel:Diagnostics]   USE_OTEL_LOGGING        = {USE_OTEL_LOGGING}")
        logger.info(f"[OTel:Diagnostics]   SERVER_NAME             = {SERVER_NAME}")
        logger.info(f"[OTel:Diagnostics]   TracerProvider ready    = {self._otel_tracer_provider is not None}")
        logger.info(f"[OTel:Diagnostics]   LoggerProvider ready    = {self._otel_logger_provider is not None}")
        logger.info(f"[OTel:Diagnostics]   Tracer instance ready   = {self._tracer is not None}")

        if TELEMETRY_BACKEND == "elasticsearch":
            traces_ep = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "NOT SET")
            logs_http_ep = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP", "NOT SET")
            logs_grpc_ep = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC", "NOT SET")
            use_http = os.getenv("USE_HTTP", "True")
            logger.info(f"[OTel:Diagnostics]   Traces endpoint         = {traces_ep}")
            logger.info(f"[OTel:Diagnostics]   Logs endpoint (HTTP)    = {logs_http_ep}")
            logger.info(f"[OTel:Diagnostics]   Logs endpoint (gRPC)    = {logs_grpc_ep}")
            logger.info(f"[OTel:Diagnostics]   USE_HTTP                = {use_http}")

            if traces_ep == "NOT SET":
                logger.warning("[OTel:Diagnostics] WARNING: Traces endpoint not configured - spans will not export")
            if logs_http_ep == "NOT SET" and logs_grpc_ep == "NOT SET":
                logger.warning("[OTel:Diagnostics] WARNING: No logs endpoint configured - OTel logs will not export")

        elif TELEMETRY_BACKEND == "azure":
            cs = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
            logger.info(f"[OTel:Diagnostics]   Azure connection string = {'configured' if cs else 'NOT SET'}")
            logger.info(f"[OTel:Diagnostics]   AZURE_MONITOR_AVAILABLE = {AZURE_MONITOR_AVAILABLE}")

        logger.info("=" * 80)

    def shutdown(self):
        """
        Shuts down OpenTelemetry tracing and logging providers.
        """
        if ENABLE_LOGGING and self._otel_tracer_provider:
            logger.info("[OTel:Shutdown] Shutting down OpenTelemetry Tracing...")
            try:
                self._otel_tracer_provider.shutdown()
                logger.info("[OTel:Shutdown] TracerProvider shutdown complete")
            except Exception as e:
                logger.error(f"[OTel:Shutdown] Error shutting down TracerProvider: {e}", exc_info=True)
        if ENABLE_LOGGING and self._otel_logger_provider:
            logger.info("[OTel:Shutdown] Shutting down OpenTelemetry Logging...")
            try:
                self._otel_logger_provider.shutdown()
                logger.info("[OTel:Shutdown] LoggerProvider shutdown complete")
            except Exception as e:
                logger.error(f"[OTel:Shutdown] Error shutting down LoggerProvider: {e}", exc_info=True)

# --- 2. SpanContextManager Class ---
# Manages thread-local storage for span context and provides helper functions.
class SpanContextManager:
    _thread_local = threading.local()

    @staticmethod
    def get_or_create_span_context(tracer: Optional[trace.Tracer]):
        """
        Get the current span context or create a new one if none exists.
        This ensures we always have a valid trace context for logging.
        """
        # First, try to get the current span from OTel context
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return current_span
        
        # If no valid span exists, check if we have one in thread-local storage
        if hasattr(SpanContextManager._thread_local, 'current_span') and SpanContextManager._thread_local.current_span:
            span_context = SpanContextManager._thread_local.current_span.get_span_context()
            if span_context.is_valid:
                return SpanContextManager._thread_local.current_span
        
        # Create a new span if none exists
        if tracer:
            span_name = f"logging-operation-{uuid.uuid4().hex[:8]}"
            span = tracer.start_span(span_name)
            SpanContextManager._thread_local.current_span = span
            return span
        
        return None

    @staticmethod
    def start_logging_span(tracer: Optional[trace.Tracer], operation_name: Optional[str] = None):
        """
        Start a new span for logging operations. This helps group related logs together.
        """
        if not tracer:
            return None
        operation_name = operation_name or f"logging-session-{uuid.uuid4().hex[:8]}"
        span = tracer.start_span(operation_name)
        SpanContextManager._thread_local.current_span = span
        return span

    @staticmethod
    def end_logging_span():
        """
        End the current logging span.
        """
        if hasattr(SpanContextManager._thread_local, 'current_span') and SpanContextManager._thread_local.current_span:
            SpanContextManager._thread_local.current_span.end()
            SpanContextManager._thread_local.current_span = None

# --- 3. SessionContext Class ---
# Manages session-specific attributes for logging.
_session_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar('session_context', default={})
class SessionContext:
    @classmethod
    def _serialize_if_complex(cls, value: Any) -> Any:
        """Helper to serialize lists/dicts to JSON strings, pass others."""
        if isinstance(value, (list, dict)):
            try:
                return json.dumps(value)
            except TypeError as e:
                logger.warning(f"SessionContext: Could not JSON serialize value of type {type(value)}, falling back to str(): {e}")
                return str(value)
        return value

    @classmethod
    def set(
        cls,
        user_id: Optional[str] = None, session_id: Optional[str] = None, user_session: Optional[str] = None, agent_id: Optional[str] = None,
        agent_name: Optional[str] = None, tool_id: Optional[str] = None, tool_name: Optional[str] = None, model_used: Optional[str] = None,
        tags: Optional[Union[List[str], str]] = None, agent_type: Optional[str] = None, tools_binded: Optional[Union[List[str], str]] = None,
        agents_binded: Optional[Union[List[str], str]] = None, user_query: Optional[str] = None, response: Optional[str] = None,
        action_type: Optional[str] = None, action_on: Optional[str] = None, previous_value: Optional[Any] = None, new_value: Optional[Any] = None,
        agent_call_id: Optional[str] = None, call_category: Optional[str] = None, request_id: Optional[str] = None,
        department_name: Optional[str] = None
    ):
        current_ctx = _session_context.get().copy()
        if user_id is not None: current_ctx['user_id'] = user_id
        if session_id is not None: current_ctx['session_id'] = session_id
        if user_session is not None: current_ctx['user_session'] = user_session
        if agent_id is not None: current_ctx['agent_id'] = agent_id
        if agent_name is not None: current_ctx['agent_name'] = agent_name
        if tool_id is not None: current_ctx['tool_id'] = tool_id
        if tool_name is not None: current_ctx['tool_name'] = tool_name
        if model_used is not None: current_ctx['model_used'] = model_used
        if tags is not None: current_ctx['tags'] = cls._serialize_if_complex(tags)
        if agent_type is not None: current_ctx['agent_type'] = agent_type
        if tools_binded is not None: current_ctx['tools_binded'] = cls._serialize_if_complex(tools_binded)
        if agents_binded is not None: current_ctx['agents_binded'] = cls._serialize_if_complex(agents_binded)
        if user_query is not None: current_ctx['user_query'] = cls._serialize_if_complex(user_query)
        if response is not None: current_ctx['response'] = cls._serialize_if_complex(response)
        if action_type is not None: current_ctx['action_type'] = action_type
        if action_on is not None: current_ctx['action_on'] = action_on
        if previous_value is not None: current_ctx['previous_value'] = cls._serialize_if_complex(previous_value)
        if new_value is not None: current_ctx['new_value'] = cls._serialize_if_complex(new_value)
        if agent_call_id is not None: current_ctx['agent_call_id'] = agent_call_id
        if call_category is not None: current_ctx['call_category'] = call_category
        if request_id is not None: current_ctx['request_id'] = request_id
        if department_name is not None: current_ctx['department_name'] = department_name
        _session_context.set(current_ctx)

    @classmethod
    def get(cls):
        """Retrieve all context values, defaulting to 'Unassigned' if not set"""
        current_ctx = _session_context.get()
        return (
            current_ctx.get('user_id', 'Unassigned'), current_ctx.get('session_id', 'Unassigned'),
            current_ctx.get('user_session', 'Unassigned'), current_ctx.get('agent_id', 'Unassigned'),
            current_ctx.get('agent_name', 'Unassigned'), current_ctx.get('tool_id', 'Unassigned'),
            current_ctx.get('tool_name', 'Unassigned'), current_ctx.get('model_used', 'Unassigned'),
            current_ctx.get('tags', 'Unassigned'), current_ctx.get('agent_type', 'Unassigned'),
            current_ctx.get('tools_binded', 'Unassigned'), current_ctx.get('agents_binded', 'Unassigned'),
            current_ctx.get('user_query', 'Unassigned'), current_ctx.get('response', 'Unassigned'),
            current_ctx.get('action_type', 'Unassigned'), current_ctx.get('action_on', 'Unassigned'),
            current_ctx.get('previous_value', 'Unassigned'), current_ctx.get('new_value', 'Unassigned'),
            current_ctx.get('agent_call_id', 'Unassigned'), current_ctx.get('call_category', 'Unassigned'),
            current_ctx.get('request_id', 'Unassigned'),
            current_ctx.get('department_name', 'Unassigned')
        )
    @classmethod

    def clear(cls):
        _session_context.set({})

# --- 4. CustomFilter Class ---
# Custom logging filter to inject session context and trace IDs into log records.
class CustomFilter(logging.Filter):
    def filter(self, record):
        (user_id, session_id, user_session, agent_id, agent_name,
         tool_id, tool_name, model_used, tags, agent_type, tools_binded,
         agents_binded, user_query, response, action_type, action_on,
         previous_value, new_value, agent_call_id, call_category, request_id,
         department_name) = SessionContext.get()
        current_span = SpanContextManager.get_or_create_span_context(otel_manager.get_tracer())
        record.trace_id = "00000000000000000000000000000000"
        record.span_id = "0000000000000000"
        if current_span and current_span.get_span_context().is_valid:
            span_context = current_span.get_span_context()
            record.trace_id = "{:032x}".format(span_context.trace_id)
            record.span_id = "{:016x}".format(span_context.span_id)
        record.user_id = user_id
        record.session_id = session_id
        record.user_session = user_session
        record.agent_id = agent_id
        record.agent_name = agent_name
        record.tool_id = tool_id
        record.tool_name = tool_name
        record.model_used = model_used
        record.tags = tags
        record.agent_type = agent_type
        record.tools_binded = tools_binded
        record.agents_binded= agents_binded
        record.user_query = user_query
        record.response = response
        record.action_type = action_type
        record.action_on = action_on
        record.previous_value = previous_value
        record.new_value = new_value
        record.agent_call_id = agent_call_id
        record.call_category = call_category
        record.request_id = request_id
        record.department_name = department_name
        # Always inject server name into each log record
        try:
            record.server_name = SERVER_NAME
        except Exception:
            record.server_name = "server"
        return True


# --- 4b. Custom Azure Monitor Logging Handler ---
# This handler properly captures session context as custom dimensions for Azure Monitor
if TELEMETRY_BACKEND == "azure" and AZURE_MONITOR_AVAILABLE:
    class AzureMonitorLoggingHandler(logging.Handler):
        """Custom logging handler for Azure Monitor that captures session context as customDimensions."""
        
        # Map Python logging levels to OTel severity numbers
        LEVEL_TO_SEVERITY = {
            logging.DEBUG: 5,     # SeverityNumber.DEBUG
            logging.INFO: 9,      # SeverityNumber.INFO
            logging.WARNING: 13,  # SeverityNumber.WARN
            logging.ERROR: 17,    # SeverityNumber.ERROR
            logging.CRITICAL: 21, # SeverityNumber.FATAL
        }

        def __init__(self, logger_provider, level=logging.NOTSET):
            super().__init__(level)
            self._logger_provider = logger_provider
            self._otel_logger = logger_provider.get_logger(__name__)

        def emit(self, record):
            try:
                # Get the message
                msg = self.format(record) if self.formatter else record.getMessage()
                
                # Build attributes from session context
                attributes = {}
                
                # Add all session context fields as attributes
                context_fields = [
                    'user_id', 'session_id', 'user_session', 'agent_id', 'agent_name',
                    'tool_id', 'tool_name', 'model_used', 'tags', 'agent_type',
                    'tools_binded', 'agents_binded', 'user_query', 'response',
                    'action_type', 'action_on', 'previous_value', 'new_value',
                    'agent_call_id', 'call_category', 'request_id', 'server_name',
                    'trace_id', 'span_id'
                ]
                
                for field in context_fields:
                    value = getattr(record, field, None)
                    if value is not None:
                        attributes[field] = str(value) if not isinstance(value, (str, int, float, bool)) else value
                
                # Add standard log record attributes (same as OTLP/Elasticsearch path)
                attributes['log_level'] = record.levelname
                attributes['logger_name'] = record.name
                attributes['pathname'] = record.pathname
                attributes['lineno'] = record.lineno
                attributes['funcName'] = record.funcName
                attributes['module'] = record.module
                
                # Additional standard Python logging attributes
                attributes['filename'] = record.filename
                attributes['thread'] = record.thread
                attributes['threadName'] = record.threadName
                attributes['process'] = record.process
                attributes['processName'] = record.processName
                
                # Exception info if present
                if record.exc_info:
                    import traceback
                    attributes['exception_type'] = str(record.exc_info[0].__name__) if record.exc_info[0] else None
                    attributes['exception_message'] = str(record.exc_info[1]) if record.exc_info[1] else None
                    attributes['exception_stacktrace'] = ''.join(traceback.format_exception(*record.exc_info)) if record.exc_info[0] else None
                
                # Get severity number
                severity_number = self.LEVEL_TO_SEVERITY.get(record.levelno, 9)
                
                # Get trace context if available
                trace_id = 0
                span_id = 0
                trace_flags = TraceFlags.DEFAULT
                if hasattr(record, 'trace_id') and record.trace_id != "00000000000000000000000000000000":
                    try:
                        trace_id = int(record.trace_id, 16)
                    except (ValueError, TypeError):
                        pass
                if hasattr(record, 'span_id') and record.span_id != "0000000000000000":
                    try:
                        span_id = int(record.span_id, 16)
                    except (ValueError, TypeError):
                        pass
                
                # Create OTel LogRecord
                import time
                
                otel_record = OTelLogRecord(
                    timestamp=int(record.created * 1e9),  # nanoseconds
                    observed_timestamp=int(time.time_ns()),
                    trace_id=trace_id,
                    span_id=span_id,
                    trace_flags=trace_flags,
                    severity_text=record.levelname,
                    severity_number=SeverityNumber(severity_number),
                    body=msg,
                    attributes=attributes,
                )
                
                self._otel_logger.emit(otel_record)
                
            except Exception:
                self.handleError(record)
else:
    # Placeholder class when Azure is not the backend
    AzureMonitorLoggingHandler = None


# --- 5. Global Logger Initialization ---
# This part remains at the global scope to ensure the logger is ready on import.

# Create the singleton instance of OpenTelemetryManager
otel_manager = OpenTelemetryManager()


# --- 5a. Environment-Aware Logger Wrapper ---
class EnvironmentAwareLogger:
    """
    A wrapper around the standard Python logger that automatically applies
    environment-aware exception logging behavior:
    
    - Development: Automatically adds exc_info=True to error/critical/warning calls
      when inside an exception handler, providing full stack traces.
    - Production: Logs without stack traces unless explicitly requested.
    
    Usage remains the same as the standard logger:
        log.error(f"Something failed: {format_error(e)}")
    """

    def __init__(self, underlying_logger: logging.Logger):
        self._logger = underlying_logger

    def _should_add_exc_info(self, kwargs: dict) -> dict:
        """Auto-add exc_info=True if inside an exception handler and not explicitly set.

        Applies to all environments (development and production) so that stack
        traces are always captured for error/warning/critical logs.
        """
        import sys
        if 'exc_info' not in kwargs:
            # Check if we're currently inside an exception handler
            if sys.exc_info()[0] is not None:
                kwargs['exc_info'] = True
        return kwargs

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        kwargs = self._should_add_exc_info(kwargs)
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        kwargs = self._should_add_exc_info(kwargs)
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        kwargs = self._should_add_exc_info(kwargs)
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        """Always logs with exc_info regardless of environment."""
        self._logger.exception(msg, *args, **kwargs)

    def setLevel(self, level):
        self._logger.setLevel(level)

    @property
    def handlers(self):
        return self._logger.handlers

    def addHandler(self, handler):
        self._logger.addHandler(handler)

    def addFilter(self, filter):
        self._logger.addFilter(filter)

    def __getattr__(self, name):
        """Proxy any other attributes to the underlying logger."""
        return getattr(self._logger, name)



logger = EnvironmentAwareLogger(_base_logger)

# --- WRAP LOGGER SETUP IN THE MASTER SWITCH ---
if ENABLE_LOGGING:
    logger.setLevel(logging.DEBUG)

    # Configure handlers and filters only if not already configured
    # This prevents duplicate handlers if the module is imported multiple times
    if not logger.handlers:
        logger.addFilter(CustomFilter())

        log_format = "%(asctime)s [%(levelname)s] [%(server_name)s] [session:%(session_id)s] - %(message)s"
        formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        if USE_OTEL_LOGGING:
            otel_manager.setup_tracing(service_name="agentic-workflow-service")
            otel_manager.setup_logging(service_name="agentic-workflow-service", use_http=True)
            
            if otel_manager.get_logger_provider():
                if TELEMETRY_BACKEND == "azure" and AzureMonitorLoggingHandler is not None:
                    # Use custom Azure handler that properly captures session context
                    azure_handler = AzureMonitorLoggingHandler(
                        logger_provider=otel_manager.get_logger_provider(),
                        level=logging.DEBUG
                    )
                    logger.addHandler(azure_handler)
                    logger.info(f"[OTel:Startup] SUCCESS: Azure Monitor logging handler attached (backend: {TELEMETRY_BACKEND})")
                else:
                    # Use standard OTel handler for elasticsearch backend
                    from opentelemetry.sdk._logs import LoggingHandler
                    otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=otel_manager.get_logger_provider())
                    logger.addHandler(otel_handler)
                    logger.info(f"[OTel:Startup] SUCCESS: OTel LoggingHandler attached (backend: {TELEMETRY_BACKEND})")
            else:
                logger.error("[OTel:Startup] FAILED: LoggerProvider is None - OTel handler NOT added. Logs will only go to console/file.")
            
            otel_manager.log_startup_diagnostics()
else:
    # If logging is disabled, disable it at the root to efficiently stop all logs.
    logging.disable(logging.CRITICAL)
    # Optionally print a single message to stderr to confirm the state.
    print("[Master Switch] All logging is DISABLED via ENABLE_LOGGING=False.", file=os.sys.stderr)

# --- 6. Global Utility Functions (for direct import) ---
# These functions wrap the class methods for convenience, maintaining the original import interface.

def update_session_context(
        user_id=None, session_id=None, user_session=None, agent_id=None,agent_name=None, tool_id=None, tool_name=None,
        model_used=None, tags=None, agent_type=None,
        tools_binded=None, agents_binded=None, user_query=None, response=None,
        action_type=None, action_on=None, previous_value=None, new_value=None,
        agent_call_id=None, call_category=None, request_id=None,
        department_name=None
    ):
    SessionContext.set(
        user_id=user_id, session_id=session_id, user_session=user_session,agent_id=agent_id, agent_name=agent_name,
        tool_id=tool_id, tool_name=tool_name, model_used=model_used, tags=tags,
        agent_type=agent_type, tools_binded=tools_binded, agents_binded=agents_binded,
        user_query=user_query, response=response, action_type=action_type, action_on=action_on,
        previous_value=previous_value, new_value=new_value, agent_call_id=agent_call_id,
        call_category=call_category, request_id=request_id,
        department_name=department_name
    )

# Alias for convenience (shorter name)
set_context = update_session_context

def with_logging_span(operation_name: Optional[str] = None):
    """
    Decorator that automatically creates a span for the decorated function.
    This ensures all logging within the function has a valid trace context.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            span_name = operation_name or f"{func.__name__}"
            span = SpanContextManager.start_logging_span(otel_manager.get_tracer(), span_name)
            try:
                return func(*args, **kwargs)
            finally:
                if span: # Ensure span exists before ending
                    SpanContextManager.end_logging_span()
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Fix #20 — OpenTelemetry span helpers for LLM / tool / node operations
# ---------------------------------------------------------------------------
import contextlib
import time as _time


@contextlib.contextmanager
def trace_operation(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Synchronous context manager that wraps a block in an OTel span.

    Usage::

        with trace_operation("llm_call", {"model": "gpt-4o"}):
            result = call_llm(...)
    """
    tracer = otel_manager.get_tracer()
    if not tracer:
        yield
        return
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v) if not isinstance(v, (str, int, float, bool)) else v)
        _t0 = _time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(exc)[:256])
            span.record_exception(exc)
            raise
        finally:
            span.set_attribute("duration_ms", round((_time.perf_counter() - _t0) * 1000, 2))


@contextlib.asynccontextmanager
async def atrace_operation(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Async context manager that wraps a block in an OTel span.

    Usage::

        async with atrace_operation("tool_execution", {"tool": "web_search"}):
            result = await run_tool(...)
    """
    tracer = otel_manager.get_tracer()
    if not tracer:
        yield
        return
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v) if not isinstance(v, (str, int, float, bool)) else v)
        _t0 = _time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(exc)[:256])
            span.record_exception(exc)
            raise
        finally:
            span.set_attribute("duration_ms", round((_time.perf_counter() - _t0) * 1000, 2))


def create_otel_hooks(runner):
    """Register OTel span hooks with a HookRunner instance.

    Creates spans for:
    - ``before_llm`` / ``after_llm``  → ``llm.invoke`` span
    - ``pre_hook`` / ``post_hook``    → ``tool.<name>`` span
    - ``on_node_start`` / ``on_node_end`` → ``node.<name>`` span

    Call once during hook runner initialisation (e.g. in ``create_default_hooks``).
    """
    tracer = otel_manager.get_tracer()
    if not tracer:
        return  # OTel tracing not configured — skip silently

    # -- LLM spans --
    _llm_span_key = "_otel_llm_span"

    @runner.before_llm(priority=20)
    def _otel_before_llm(state):
        """Start an OTel span before LLM invocation."""
        span = tracer.start_span("llm.invoke")
        model = ""
        if isinstance(state, dict):
            model = state.get("model", state.get("model_name", ""))
        if model:
            span.set_attribute("llm.model", str(model))
        # Stash span on state dict so after_llm can close it
        if isinstance(state, dict):
            state[_llm_span_key] = span
        return state

    @runner.after_llm(priority=20)
    def _otel_after_llm(state):
        """End the LLM span after invocation completes."""
        if isinstance(state, dict):
            span = state.pop(_llm_span_key, None)
            if span:
                # Record token counts if present
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    val = state.get(key)
                    if val is not None:
                        span.set_attribute(f"llm.{key}", val)
                span.end()
        return state

    # -- Tool spans --
    _tool_span_key = "_otel_tool_span"

    @runner.pre_hook("*", priority=20)
    def _otel_pre_tool(tool_name, tool_input, state):
        """Start an OTel span before tool execution."""
        span = tracer.start_span(f"tool.{tool_name}")
        span.set_attribute("tool.name", tool_name)
        if isinstance(state, dict):
            state[_tool_span_key] = span
        return tool_name, tool_input

    @runner.post_hook("*", priority=20)
    def _otel_post_tool(tool_name, tool_output, state):
        """End the tool span after execution completes."""
        if isinstance(state, dict):
            span = state.pop(_tool_span_key, None)
            if span:
                span.set_attribute("tool.output_length", len(str(tool_output)) if tool_output else 0)
                span.end()
        return tool_output

    # -- Node spans --
    _node_span_key = "_otel_node_span"

    @runner.on_node_start(priority=20)
    def _otel_on_node_start(state):
        """Start an OTel span on graph node entry."""
        node_name = state.get("current_node", "unknown") if isinstance(state, dict) else "unknown"
        span = tracer.start_span(f"node.{node_name}")
        span.set_attribute("node.name", node_name)
        if isinstance(state, dict):
            state[_node_span_key] = span
        return state

    @runner.on_node_end(priority=20)
    def _otel_on_node_end(state):
        """End the node span on graph node exit."""
        if isinstance(state, dict):
            span = state.pop(_node_span_key, None)
            if span:
                span.end()
        return state

# --- 7. Register Atexit Shutdown Hook ---
atexit.register(otel_manager.shutdown)