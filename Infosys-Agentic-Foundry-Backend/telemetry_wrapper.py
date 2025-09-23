# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import logging
import os
import atexit # For graceful shutdown
import json # Import json for serialization
import contextvars
from opentelemetry import trace, _logs # Use _logs for the logs API/SDK
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler # The OTel handler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor # Recommended processor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from logging import Logger
from functools import wraps
import threading
import uuid
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv


load_dotenv()

# --- Global Configuration Flags ---
USE_OTEL_LOGGING = os.getenv("USE_OTEL_LOGGING", "True").lower() == "true"
# --- MODIFICATION 1: ADDED MASTER LOGGING SWITCH ---
ENABLE_LOGGING = os.getenv("ENABLE_LOGGING", "False").lower() == "true"

# --- 1. OpenTelemetryManager Class (No changes) ---
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
        self._otel_logger_provider: Optional[LoggerProvider] = None
        self._otel_tracer_provider: Optional[TracerProvider] = None
        self._tracer: Optional[trace.Tracer] = None
        self._initialized = True

    def setup_tracing(self, service_name: str = "agentic-workflow-service"):
        """
        Initializes the OpenTelemetry tracing pipeline. Should be called once.
        """
        if self._otel_tracer_provider:
            logger.debug("OpenTelemetry Tracing already initialized.")
            return self._otel_tracer_provider

        logger.info(f"Setting up OpenTelemetry Tracing for service: {service_name}")
        resource = Resource(attributes={SERVICE_NAME: service_name})

        self._otel_tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(self._otel_tracer_provider)
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        logger.info(f"OTLP Trace Exporter Endpoint: {otlp_endpoint}")
        exporter_args = {"endpoint": otlp_endpoint}
        headers_str = os.getenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
        if headers_str:
            try:
                exporter_args["headers"] = dict(item.split("=") for item in headers_str.split(","))
                logger.info(f"Using OTLP Trace Headers: {exporter_args['headers']}")
            except ValueError:
                logger.error("Invalid format for OTEL_EXPORTER_OTLP_TRACES_HEADERS.")
        try:
            span_exporter = OTLPSpanExporter(**exporter_args)
            self._otel_tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        except Exception as e:
            logger.error(f"Failed to initialize OTLP span exporter: {e}", exc_info=True)

        self._tracer = trace.get_tracer(__name__)
        logger.info("OpenTelemetry Tracing Setup Complete.")
        return self._otel_tracer_provider

    def setup_logging(self, service_name: str = "agentic-workflow-service", use_http: bool = True):
        """
        Initializes the OpenTelemetry logging pipeline. Should be called once.
        """
        if self._otel_logger_provider:
            logger.debug("OpenTelemetry Logging already initialized.")
            return self._otel_logger_provider

        logger.info(f"Setting up OpenTelemetry Logging for service: {service_name}")
        resource = Resource(attributes={SERVICE_NAME: service_name})

        ExporterClass = OTLPLogExporterHTTP
        default_endpoint = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP")
        env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP"
        protocol = "HTTP"

        # Fallback to HTTP if gRPC is chosen but not installed
        if not use_http:
            try:
                from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as OTLPLogExporterGRPC
                ExporterClass = OTLPLogExporterGRPC
                default_endpoint = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC")
                env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC"
                protocol = "gRPC"
            except ImportError:
                logger.error("OTLP gRPC Exporter not found. Falling back to HTTP.")
                use_http = os.getenv("USE_HTTP", "True").lower() == "true"

        otlp_endpoint = os.getenv(env_var_name, default_endpoint)
        logger.info(f"OTLP Log Exporter ({protocol}) Endpoint: {otlp_endpoint}")
        exporter_args = {"endpoint": otlp_endpoint}

        headers_str = os.getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS")
        if headers_str:
            try:
                exporter_args["headers"] = dict(item.split("=") for item in headers_str.split(","))
                logger.info(f"Using OTLP Headers: {exporter_args['headers']}")
            except ValueError:
                logger.error("Invalid format for OTEL_EXPORTER_OTLP_LOGS_HEADERS.")

        try:
            log_exporter = ExporterClass(**exporter_args)
            self._otel_logger_provider = LoggerProvider(resource=resource)
            _logs.set_logger_provider(self._otel_logger_provider)
            self._otel_logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
            logger.info("OpenTelemetry Logging Setup Complete.")
        except Exception as e:
            logger.error(f"Failed to initialize OTLP exporter ({protocol}): {e}", exc_info=True)
            return None
        return self._otel_logger_provider

    def get_tracer(self) -> Optional[trace.Tracer]:
        return self._tracer

    def get_logger_provider(self) -> Optional[LoggerProvider]:
        return self._otel_logger_provider

    def shutdown(self):
        """
        Shuts down OpenTelemetry tracing and logging providers.
        """
        if ENABLE_LOGGING and self._otel_tracer_provider:
            logger.info("Shutting down OpenTelemetry Tracing.")
            self._otel_tracer_provider.shutdown()
        if ENABLE_LOGGING and self._otel_logger_provider:
            logger.info("Shutting down OpenTelemetry Logging.")
            self._otel_logger_provider.shutdown()

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
        action_type: Optional[str] = None, action_on: Optional[str] = None, previous_value: Optional[Any] = None, new_value: Optional[Any] = None
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
            current_ctx.get('previous_value', 'Unassigned'), current_ctx.get('new_value', 'Unassigned')
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
         previous_value, new_value) = SessionContext.get()
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
        return True

# --- 5. Global Logger Initialization ---
# This part remains at the global scope to ensure the logger is ready on import.

# Create the singleton instance of OpenTelemetryManager
otel_manager = OpenTelemetryManager()
logger = logging.getLogger("agentic_workflow_logger")

# --- WRAP LOGGER SETUP IN THE MASTER SWITCH ---
if ENABLE_LOGGING:
    logger.setLevel(logging.DEBUG)

    # Configure handlers and filters only if not already configured
    # This prevents duplicate handlers if the module is imported multiple times
    if not logger.handlers:
        logger.addFilter(CustomFilter())

        log_format = "%(asctime)s [%(levelname)s] - %(message)s"
        formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        if USE_OTEL_LOGGING:
            otel_manager.setup_tracing(service_name="agentic-workflow-service")
            otel_manager.setup_logging(service_name="agentic-workflow-service", use_http=True)
            if otel_manager.get_logger_provider():
                otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=otel_manager.get_logger_provider())
                logger.addHandler(otel_handler)
            else:
                logger.warning("OTel setup was requested but failed. OTel handler not added.")
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
        action_type=None, action_on=None, previous_value=None, new_value=None
    ):
    SessionContext.set(
        user_id=user_id, session_id=session_id, user_session=user_session,agent_id=agent_id, agent_name=agent_name,
        tool_id=tool_id, tool_name=tool_name, model_used=model_used, tags=tags,
        agent_type=agent_type, tools_binded=tools_binded, agents_binded=agents_binded,
        user_query=user_query, response=response, action_type=action_type, action_on=action_on,
        previous_value=previous_value, new_value=new_value
    )

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

# --- 7. Register Atexit Shutdown Hook ---
atexit.register(otel_manager.shutdown)


