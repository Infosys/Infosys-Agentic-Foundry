# Telemetry

### Key Components of Telemetry:
1. **Logs**: Captures LLM inputs, outputs, prompts, responses, errors, and debugging information.
2. **Traces**: Tracks the chain of thought, agent decisions, and agent state to observe how individual LLM tasks are executed.

---

### OpenTelemetry Workflow

OpenTelemetry is an open-source framework for collecting telemetry data (logs and traces) from applications. Below is an explanation of the workflow:

1. **OpenTelemetry - Logging Statements (Actions)**: Logs are generated in the application code using OpenTelemetry libraries.
2. **OpenTelemetry Collector - Transfers Logs from Code**: The OpenTelemetry Collector gathers logs from the application and forwards them to a suitable backend.
3. **ElasticSearch - Log Format Compatibility**: Logs are stored in ElasticSearch, which provides a structured and searchable format for telemetry data.
4. **ElasticSearch - Grafana Connection**: ElasticSearch integrates with Grafana to visualize the telemetry data.
5. **Final Dashboard**: Grafana displays the logs and metrics in a user-friendly dashboard for monitoring and analysis.

---

### Telemetry Flowchart

<style>
.flow-mini {
  font-family: sans-serif;
  max-width: 300px;
  margin: 2em auto;
  text-align: center;
  font-size: 14px;
}
.flow-mini .step {
  background: #eef;
  border: 1px solid #88a;
  border-radius: 6px;
  padding: 8px;
  margin: 8px 0;
}
.flow-mini .arrow {
  font-size: 1.2em;
  color: #888;
  margin: 4px 0;
}
</style>
 
<div class="flow-mini">
  <div class="step">OpenTelemetry<br><small>Logging Statements</small></div>
  <div class="arrow">↓</div>
 
  <div class="step">Open telemetry collector<br><small>Transfer Logs</small></div>
  <div class="arrow">↓</div>
 
  <div class="step">Elasticsearch<br><small>For Longer Format</small></div>
  <div class="arrow">↓</div>
 
  <div class="step">Graphana<br><small>Connection to Graphana</small></div>
  <div class="arrow">↓</div>
 
  <div class="step">Final Dashboard<br><small></small></div>
</div>

---

### Data Collection & Monitoring

- **Data Collection**: 
The OpenTelemetry SDK is used to collect traces and logs from the agent framework, capturing detailed telemetry data.

- **Data Export**:
The OpenTelemetry Collector transfers the collected logs and traces from the framework to an external storage or analysis system.

- **Centralized Storage & Anlysis**:
All telemetry data is centrally stored in ElasticSearch, enabling structured storage and efficient querying.

- **Visualization**:
Grafana retrieves data from the centralized storage to populate dashboards, offering real-time insights into application performance, user interactions, and agent workflows.

---


### Implementation of OpenTelemetry Logging

The `setup_otel_logging` function initializes the OpenTelemetry logging pipeline for an application. It ensures that logs are collected, processed, and exported to a backend system for analysis. 

```python
import logging, atexit 
from opentelemetry import trace, _logs 
from logging import Logger
from functools import wraps
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor 
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP 
from opentelemetry.sdk._logs import (
    LoggerProvider,
    LoggingHandler 
)
from opentelemetry.sdk.resources import (
    Resource,
    SERVICE_NAME  
)


# --- Global variable to hold the configured provider (initialized once) ---
_otel_logger_provider = None
USE_OTEL_LOGGING = False # keep it as True in VM for Otel Collector, False in local dev

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
 
```

**`USE_OTEL_LOGGING` Configuration Flag**

The `USE_OTEL_LOGGING` flag determines whether OpenTelemetry (Otel) logging is enabled in your application, and it helps control the telemetry data flow between your application and the OpenTelemetry Collector. This flag is particularly useful in managing the difference between development and production environments.

**Local Development:**

```python
USE_OTEL_LOGGING = False  # Default value for local development
```
When developing locally, If the required dependencies are not available or if logging is disabled by setting USE_OTEL_LOGGING to false, the system will output relevant information to the console when you run the file. This ensures you are informed of any missing configurations or services, helping to avoid confusion during local development.

**Production or Remote Environments:**
```python
USE_OTEL_LOGGING = True  # Set this to True when running in a VM or production environment
```

In production or more complex environments (e.g., Virtual Machines), telemetry data collection (such as logs, traces, and metrics) is crucial for monitoring and troubleshooting application performance. This flag ensures the application sends telemetry data to the Otel Collector in such environments.

## Components

**1. SessionContext class** 

The `SessionContext` class manages session specific metadata. It allows setting and retrieving context values.

```python
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
        return value
 
    @classmethod
    def set(
        cls,
        user_id=None, session_id=None, agent_id=None,
        tool_id=None, tool_name=None, model_used=None,
        tags=None, agent_name=None, agent_type=None, tools_binded=None,
        agents_binded=None, user_query=None, response=None,
        action_type=None, action_on=None, previous_value=None, new_value=None
    ):
        """Update specific fields, JSON serializing complex types."""
        if user_id is not None: cls._context['user_id'] = user_id
        if session_id is not None: cls._context['session_id'] = session_id
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
        if user_query is not None: cls._context['user_query'] = cls._serialize_if_complex(user_query) 
        if response is not None: cls._context['response'] = cls._serialize_if_complex(response) 
        if action_type is not None: cls._context['action_type'] = action_type
        if action_on is not None: cls._context['action_on'] = action_on
        if previous_value is not None: cls._context['previous_value'] = cls._serialize_if_complex(previous_value)
        if new_value is not None: cls._context['new_value'] = cls._serialize_if_complex(new_value)
 
 
    @classmethod
    def get(cls):
        """Retrieve all context values, defaulting to 'Unassigned' if not set"""
        return (
            cls._context.get('user_id', 'Unassigned'),
            cls._context.get('session_id', 'Unassigned'),
            cls._context.get('agent_id', 'Unassigned'),
            cls._context.get('agent_name', 'Unassigned'),
            cls._context.get('tool_id', 'Unassigned'),
            cls._context.get('tool_name', 'Unassigned'),
            cls._context.get('model_used', 'Unassigned'),
            cls._context.get('tags', 'Unassigned'),
            cls._context.get('agent_type', 'Unassigned'),
            cls._context.get('tools_binded', 'Unassigned'), 
            cls._context.get('agents_binded', 'Unassigned'),
            cls._context.get('user_query', 'Unassigned'),   
            cls._context.get('response', 'Unassigned'),     
            cls._context.get('action_type', 'Unassigned'),
            cls._context.get('action_on', 'Unassigned'),
            cls._context.get('previous_value', 'Unassigned'),
            cls._context.get('new_value', 'Unassigned')     
        )
```


---

**2. update_session_context function**

This `update_session_context` function dynamically updates the session context.
```python
ef update_session_context(
        user_id=None, session_id=None, agent_id=None,agent_name=None, tool_id=None, tool_name=None,
        model_used=None, tags=None, agent_type=None,
        tools_binded=None, agents_binded=None, user_query=None, response=None,
        action_type=None, action_on=None, previous_value=None, new_value=None
    ):
    SessionContext.set(
        user_id=user_id, session_id=session_id, agent_id=agent_id, agent_name=agent_name,
        tool_id=tool_id, tool_name=tool_name, model_used=model_used, tags=tags,
        agent_type=agent_type, tools_binded=tools_binded, agents_binded=agents_binded,
        user_query=user_query, response=response, action_type=action_type, action_on=action_on,
        previous_value=previous_value, new_value=new_value
    )
```
---

**3. CustomFilter class**

The CustomFilter class is a custom logging filter that enriches log records with additional context-specific attributes and trace/span IDs. It ensures that logs contain detailed metadata, making them more informative and traceable in distributed systems.

```python
class CustomFilter(logging.Filter):
    def filter(self, record):
        (
            user_id, session_id, agent_id, agent_name,
            tool_id, tool_name, model_used, tags,
            agent_type, tools_binded, agents_binded, user_query, response,
            action_type, action_on, previous_value, new_value
        ) = SessionContext.get()
 
        current_span = trace.get_current_span()
        record.trace_id = "00000000000000000000000000000000"
        record.span_id = "0000000000000000"
        if current_span and current_span.get_span_context().is_valid:
            record.trace_id = "{trace:032x}".format(trace=current_span.get_span_context().trace_id)
            record.span_id = "{span:016x}".format(span=current_span.get_span_context().span_id)
 
        record.user_id = user_id
        record.session_id = session_id
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
```

---

**4. get_logger function**

The `get_logger` function creates and configures a logger with context-specific attributes and integrates it with OpenTelemetry (OTel) for enhanced observability. This logger is designed to capture detailed logs enriched with trace and span information, making it suitable for distributed systems.


```python
def get_logger(otel_provider_instance) -> Logger: 
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
 
    log = logging.getLogger("agentic_workflow_logger") 
    log.setLevel(logging.DEBUG)
 
    # Check if handlers of specific types are already added to prevent duplicates more robustly
    has_console_handler = any(isinstance(h, logging.StreamHandler) for h in log.handlers)
    has_otel_handler = any(isinstance(h, LoggingHandler) for h in log.handlers)
    has_custom_filter = any(isinstance(f, CustomFilter) for f in log.filters)
 
    if not has_console_handler: log.addHandler(console_handler)
    if not has_otel_handler: log.addHandler(otel_handler)
    if not has_custom_filter: log.addFilter(CustomFilter())
 
    return log
```

---

**Example Usage**:

- Initialize OTel Logging
- Call setup using HTTP by default, matching the intended collector port 4320
```python
_otel_logger_provider = None
if USE_OTEL_LOGGING:
    _otel_logger_provider = setup_otel_logging(
        service_name="agentic-workflow-service",
        use_http=True
    )
```

 
- Initialize the logger instance that other modules will import
- Check if provider setup was successful before creating logger
```python 
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
```
---

**shutdown function**: 
```python
def shutdown_otel_logging():
    global _otel_logger_provider
    if _otel_logger_provider:
        print("--- Shutting down OpenTelemetry Logging ---")
        try:
            _otel_logger_provider.shutdown()
            print("--- OpenTelemetry Logging Shutdown Complete ---")
        except Exception as e:
            print(f"[ERROR] Exception during OTel logging shutdown: {e}")
        finally:
            _otel_logger_provider = None
```
- Register the shutdown function to be called when the Python process exits
```python
atexit.register(shutdown_otel_logging)
```
---

## Benefits of Telemetry

- **Improved Monitoring**: Real-time insights into system performance.
- **Faster Debugging**: Easier identification of issues through logs and traces.
- **Enhanced Optimization**: Data-driven decisions to improve system efficiency.
- **Scalability**: Suitable for distributed systems and microservices.

By leveraging OpenTelemetry, ElasticSearch, and Grafana, organizations can build robust observability pipelines to monitor and maintain their systems effectively.

---
