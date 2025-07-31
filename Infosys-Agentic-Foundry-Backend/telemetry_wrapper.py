# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import logging
import os
import atexit # For graceful shutdown
import json # Import json for serialization
from opentelemetry import trace, _logs # Use _logs for the logs API/SDK
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler # The OTel handler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor # Recommended processor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP # Alias for clarity
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from logging import Logger
from functools import wraps
from urllib.parse import urlparse
import threading
import uuid
 
# --- Global variables to hold the configured providers (initialized once) ---
_otel_logger_provider = None
_otel_tracer_provider = None
_tracer = None
USE_OTEL_LOGGING = os.getenv("USE_OTEL_LOGGING", "False").lower() == "true" # keep it as True in VM for Otel Collector, False in local dev

# --- Function for one-time OTel tracing setup ---
def setup_otel_tracing(service_name="agentic-workflow-service"):
    """
    Initializes the OpenTelemetry tracing pipeline. Should be called once.
    """
    global _otel_tracer_provider, _tracer
    if _otel_tracer_provider is not None:
        print("--- OpenTelemetry Tracing already initialized. ---")
        return _otel_tracer_provider
 
    print(f"--- Setting up OpenTelemetry Tracing for service: {service_name} ---")
    resource = Resource(attributes={SERVICE_NAME: service_name})
    
    _otel_tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(_otel_tracer_provider)
    
    # Set up OTLP span exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318/v1/traces")
    print(f"--- OTLP Trace Exporter Endpoint: {otlp_endpoint} ---")
    
    exporter_args = {"endpoint": otlp_endpoint}
    
    # Add headers if needed
    headers_str = os.getenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
    if headers_str:
        try:
            exporter_args["headers"] = dict(item.split("=") for item in headers_str.split(","))
            print(f"--- Using OTLP Trace Headers: {exporter_args['headers']} ---")
        except ValueError:
            print(f"[ERROR] Invalid format for OTEL_EXPORTER_OTLP_TRACES_HEADERS. Expected 'key1=value1,key2=value2'.")
    
    try:
        span_exporter = OTLPSpanExporter(**exporter_args)
        span_processor = BatchSpanProcessor(span_exporter)
        _otel_tracer_provider.add_span_processor(span_processor)
    except Exception as e:
        print(f"[ERROR] Failed to initialize OTLP span exporter: {e}")
    
    _tracer = trace.get_tracer(__name__)
    print("--- OpenTelemetry Tracing Setup Complete ---")
    return _otel_tracer_provider

# --- Function for one-time OTel logging setup ---
def setup_otel_logging(service_name="agentic-workflow-service", use_http=True):
    """
    Initializes the OpenTelemetry logging pipeline. Should be called once.
    """
    global _otel_logger_provider
    if _otel_logger_provider is not None:
        print("--- OpenTelemetry Logging already initialized. ---")
        return _otel_logger_provider
 
    print(f"--- Setting up OpenTelemetry Logging for service: {service_name} ---")
    resource = Resource(attributes={SERVICE_NAME: service_name})
 
    if use_http:
        default_endpoint = "http://localhost:4320/v1/logs"
        env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP"
        ExporterClass = OTLPLogExporterHTTP
        protocol = "HTTP"
    else: # Assuming gRPC for the else case, ensure opentelemetry-exporter-otlp-proto-grpc is installed
        default_endpoint = "localhost:4319"
        env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC"
        try:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as OTLPLogExporterGRPC
            ExporterClass = OTLPLogExporterGRPC
        except ImportError:
            print("[ERROR] OTLP gRPC Exporter not found. Please install 'opentelemetry-exporter-otlp-proto-grpc'. Falling back to HTTP.")
            default_endpoint = "http://localhost:4320/v1/logs" # Fallback
            env_var_name = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP"
            ExporterClass = OTLPLogExporterHTTP
            protocol = "HTTP"
        protocol = "gRPC"
 
 
    otlp_endpoint = os.getenv(env_var_name, default_endpoint)
    print(f"--- OTLP Log Exporter ({protocol}) Endpoint: {otlp_endpoint} ---")
    exporter_args = {"endpoint": otlp_endpoint}
 
    # Add headers if needed
    headers_str = os.getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS")
    if headers_str:
        try:
            exporter_args["headers"] = dict(item.split("=") for item in headers_str.split(","))
            print(f"--- Using OTLP Headers: {exporter_args['headers']} ---")
        except ValueError:
            print(f"[ERROR] Invalid format for OTEL_EXPORTER_OTLP_LOGS_HEADERS. Expected 'key1=value1,key2=value2'.")
 
 
    try:
      log_exporter = ExporterClass(**exporter_args)
    except Exception as e:
        print(f"[ERROR] Failed to initialize OTLP exporter ({protocol}): {e}")
        return None
 
    _otel_logger_provider = LoggerProvider(resource=resource)
    _logs.set_logger_provider(_otel_logger_provider)
    log_processor = BatchLogRecordProcessor(log_exporter)
    _otel_logger_provider.add_log_record_processor(log_processor)
 
    print("--- OpenTelemetry Logging Setup Complete ---")
    return _otel_logger_provider

# --- Thread-local storage for span context ---
_thread_local = threading.local()

def get_or_create_span_context():
    """
    Get the current span context or create a new one if none exists.
    This ensures we always have a valid trace context for logging.
    """
    global _tracer
    
    # First, try to get the current span from OTel context
    current_span = trace.get_current_span()
    if current_span and current_span.get_span_context().is_valid:
        return current_span
    
    # If no valid span exists, check if we have one in thread-local storage
    if hasattr(_thread_local, 'current_span') and _thread_local.current_span:
        span_context = _thread_local.current_span.get_span_context()
        if span_context.is_valid:
            return _thread_local.current_span
    
    # Create a new span if none exists
    if _tracer:
        span_name = f"logging-operation-{uuid.uuid4().hex[:8]}"
        span = _tracer.start_span(span_name)
        _thread_local.current_span = span
        return span
    
    return None

def start_logging_span(operation_name=None):
    """
    Start a new span for logging operations. This helps group related logs together.
    """
    global _tracer
    if not _tracer:
        return None
    
    if not operation_name:
        operation_name = f"logging-session-{uuid.uuid4().hex[:8]}"
    
    span = _tracer.start_span(operation_name)
    _thread_local.current_span = span
    return span

def end_logging_span():
    """
    End the current logging span.
    """
    if hasattr(_thread_local, 'current_span') and _thread_local.current_span:
        _thread_local.current_span.end()
        _thread_local.current_span = None
 

# --- SessionContext class (MODIFIED to JSON serialize complex types) ---
class SessionContext:
    _context = {}
 
    @classmethod
    def _serialize_if_complex(cls, value):
        """Helper to serialize lists/dicts to JSON strings, pass others."""
        if isinstance(value, (list, dict)):
            try:
                return json.dumps(value)
            except TypeError as e:
                # Fallback for unserializable objects: convert to string
                # You might want more sophisticated handling or logging here
                print(f"[WARNING] SessionContext: Could not JSON serialize value of type {type(value)}, falling back to str(): {e}")
                return str(value)
        return value # Return as is if not list/dict (e.g. string, int, bool)
 
    @classmethod
    def set(
        cls,
        user_id=None, session_id=None, user_session=None, agent_id=None,
        tool_id=None, tool_name=None, model_used=None,
        tags=None, agent_name=None, agent_type=None, tools_binded=None,
        agents_binded=None, user_query=None, response=None,
        action_type=None, action_on=None, previous_value=None, new_value=None
    ):
        """Update specific fields, JSON serializing complex types."""
        if user_id is not None: cls._context['user_id'] = user_id
        if session_id is not None: cls._context['session_id'] = session_id
        if user_session is not None: cls._context['user_session'] = user_session
        if agent_id is not None: cls._context['agent_id'] = agent_id
        if agent_name is not None: cls._context['agent_name'] = agent_name
        if tool_id is not None: cls._context['tool_id'] = tool_id
        if tool_name is not None: cls._context['tool_name'] = tool_name
        if model_used is not None: cls._context['model_used'] = model_used
 
        # Serialize complex fields
        if tags is not None: cls._context['tags'] = cls._serialize_if_complex(tags)
        if agent_type is not None: cls._context['agent_type'] = agent_type
        if tools_binded is not None: cls._context['tools_binded'] = cls._serialize_if_complex(tools_binded)
        if agents_binded is not None: cls._context['agents_binded'] = cls._serialize_if_complex(agents_binded)
        if user_query is not None: cls._context['user_query'] = cls._serialize_if_complex(user_query) # User query might be complex
        if response is not None: cls._context['response'] = cls._serialize_if_complex(response) # Response might be complex
        if action_type is not None: cls._context['action_type'] = action_type
        if action_on is not None: cls._context['action_on'] = action_on
        if previous_value is not None: cls._context['previous_value'] = cls._serialize_if_complex(previous_value)
        if new_value is not None: cls._context['new_value'] = cls._serialize_if_complex(new_value)
 
 
    @classmethod
    def get(cls):
        """Retrieve all context values, defaulting to 'Unassigned' if not set"""
        # The values are already serialized strings if they were complex
        return (
            cls._context.get('user_id', 'Unassigned'),
            cls._context.get('session_id', 'Unassigned'),
            cls._context.get('user_session', 'Unassigned'),
            cls._context.get('agent_id', 'Unassigned'),
            cls._context.get('agent_name', 'Unassigned'),
            cls._context.get('tool_id', 'Unassigned'),
            cls._context.get('tool_name', 'Unassigned'),
            cls._context.get('model_used', 'Unassigned'),
            cls._context.get('tags', 'Unassigned'), # Will be JSON string if originally list/dict
            cls._context.get('agent_type', 'Unassigned'),
            cls._context.get('tools_binded', 'Unassigned'), # Will be JSON string
            cls._context.get('agents_binded', 'Unassigned'),# Will be JSON string
            cls._context.get('user_query', 'Unassigned'),   # Will be JSON string
            cls._context.get('response', 'Unassigned'),     # Will be JSON string
            cls._context.get('action_type', 'Unassigned'),
            cls._context.get('action_on', 'Unassigned'),
            cls._context.get('previous_value', 'Unassigned'),# Will be JSON string
            cls._context.get('new_value', 'Unassigned')     # Will be JSON string
        )
 
# --- update_session_context function (Keep as is, uses SessionContext.set) ---
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
 
# --- CustomFilter class (MODIFIED to ensure valid trace context) ---
class CustomFilter(logging.Filter):
    def filter(self, record):
        (
            user_id, session_id, user_session, agent_id, agent_name,
            tool_id, tool_name, model_used, tags,
            agent_type, tools_binded, agents_binded, user_query, response,
            action_type, action_on, previous_value, new_value
        ) = SessionContext.get()
 
        # Get or create a valid span context
        current_span = get_or_create_span_context()
        
        # Default values if no valid span is available
        record.trace_id = "00000000000000000000000000000000"
        record.span_id = "0000000000000000"
        
        if current_span and current_span.get_span_context().is_valid:
            span_context = current_span.get_span_context()
            record.trace_id = "{trace:032x}".format(trace=span_context.trace_id)
            record.span_id = "{span:016x}".format(span=span_context.span_id)
 
        record.user_id = user_id
        record.session_id = session_id
        record.user_session = user_session
        record.agent_id = agent_id
        record.agent_name = agent_name
        record.tool_id = tool_id
        record.tool_name = tool_name
        record.model_used = model_used
        record.tags = tags # This will be the JSON string if tags was a list/dict
        record.agent_type = agent_type
        record.tools_binded = tools_binded # JSON string
        record.agents_binded= agents_binded # JSON string
        record.user_query = user_query # JSON string if complex
        record.response = response     # JSON string if complex
        record.action_type = action_type
        record.action_on = action_on
        record.previous_value = previous_value # JSON string if complex
        record.new_value = new_value         # JSON string if complex
 
        return True
 
# --- get_logger function (Modified slightly for clarity) ---
def get_logger(otel_provider_instance) -> Logger: # Renamed arg for clarity
    """Create a logger with context-specific attributes and OTel handler"""
 
    if otel_provider_instance is None:
        print("[ERROR] OpenTelemetry Logging provider is None in get_logger. Attempting fallback init.")
        otel_provider_instance = setup_otel_logging()
        if otel_provider_instance is None:
             raise RuntimeError("OpenTelemetry Logging not initialized and fallback failed. Cannot create OTel handler.")
 
    log_format = "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] [trace_id=%(trace_id)s span_id=%(span_id)s] [%(name)s] [SessID:%(session_id)s AgentID:%(agent_id)s] - %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
 
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
 
    otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=otel_provider_instance)
 
    log = logging.getLogger("agentic_workflow_logger") # Consistent logger name
    log.setLevel(logging.DEBUG)
 
    # Check if handlers of specific types are already added to prevent duplicates more robustly
    has_console_handler = any(isinstance(h, logging.StreamHandler) for h in log.handlers)
    has_otel_handler = any(isinstance(h, LoggingHandler) for h in log.handlers)
    has_custom_filter = any(isinstance(f, CustomFilter) for f in log.filters)
 
    if not has_console_handler: log.addHandler(console_handler)
    if not has_otel_handler: log.addHandler(otel_handler)
    if not has_custom_filter: log.addFilter(CustomFilter())
 
    return log

# --- Decorator for automatic span creation ---
def with_logging_span(operation_name=None):
    """
    Decorator that automatically creates a span for the decorated function.
    This ensures all logging within the function has a valid trace context.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            span_name = operation_name or f"{func.__name__}"
            span = start_logging_span(span_name)
            try:
                return func(*args, **kwargs)
            finally:
                end_logging_span()
        return wrapper
    return decorator
 
# --- Initialize OTel Tracing and Logging ONCE ---
_otel_tracer_provider = None
_otel_logger_provider = None

if USE_OTEL_LOGGING:
    # Initialize tracing first
    _otel_tracer_provider = setup_otel_tracing(
        service_name="agentic-workflow-service"
    )
    
    # Then initialize logging
    _otel_logger_provider = setup_otel_logging(
        service_name="agentic-workflow-service",
        use_http=True
    )

 
# --- Initialize the logger instance ---
if _otel_logger_provider:
    logger = get_logger(_otel_logger_provider)
else:
    print("[WARNING] OTel setup skipped or failed. Falling back to console-only logging.")
    logger = logging.getLogger("agentic_workflow_logger_fallback")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
 
# --- Add a shutdown function ---
def shutdown_otel_logging():
    global _otel_logger_provider, _otel_tracer_provider
    if _otel_tracer_provider:
        print("--- Shutting down OpenTelemetry Tracing ---")
        try:
            _otel_tracer_provider.shutdown()
            print("--- OpenTelemetry Tracing Shutdown Complete ---")
        except Exception as e:
            print(f"[ERROR] Exception during OTel tracing shutdown: {e}")
        finally:
            _otel_tracer_provider = None
            
    if _otel_logger_provider:
        print("--- Shutting down OpenTelemetry Logging ---")
        try:
            _otel_logger_provider.shutdown()
            print("--- OpenTelemetry Logging Shutdown Complete ---")
        except Exception as e:
            print(f"[ERROR] Exception during OTel logging shutdown: {e}")
        finally:
            _otel_logger_provider = None
 
atexit.register(shutdown_otel_logging)
