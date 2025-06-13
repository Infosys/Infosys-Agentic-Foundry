# Arize Phoenix Setup Guide

## Python Dependencies

Install the required packages:

```bash
pip install arize-phoenix openinference-instrumentation-langchain
```

- **arize-phoenix**: Core Phoenix library for observability and tracing
- **openinference-instrumentation-langchain**: Automatic instrumentation for LangChain applications


## Trace Recording Methods

Phoenix offers two primary approaches for recording traces in your application:

**Method 1: Direct Import**
```python
from phoenix.otel import register
```

**Method 2: Project Context Manager**
```python
from phoenix.trace import using_project
```

## Environment Variables

Configure the following environment variables for proper setup:

**Set GRPC Port**

- In command prompt
```bash
set PHOENIX_GRPC_PORT=50051
```
- In terminal 
```bash
$env: PHOENIX_GRPC_PORT=50051
```

Default port is used by OpenTelemetry (OTEL) for trace collection and should change Phoenix's default configuration.

## Trace Storage Configuration

Phoenix provides flexible storage options for your traces:

**Default Storage (SQLite)**
By default, Phoenix stores traces in a local SQLite database, which is suitable for development and small-scale deployments.

**PostgreSQL Storage (Production)**
For production environments or when you need more robust storage, configure PostgreSQL:

```bash
set PHOENIX_SQL_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/arize_traces
```

Replace the connection parameters with your actual PostgreSQL credentials:

- provide your username: `postgres`
- provide your password: `postgres`
- host and port: `localhost:5432`
- database name: `arize_traces`


## Project Registration in Python Code

**Example 1: Evaluation Service**

```python
@app.post('/evaluate')
async def evaluate(evaluating_model1, evaluating_model2):
    register(
        project_name='add-tool',
        auto_instrument=True,
        set_global_tracer_provider=False,
        batch=True
    )
    
    with using_project('evaluation-metrics'):
        return await process_unprocessed_evaluations(
            model1=evaluating_model1,
            model2=evaluating_model2
        )
```

**Configuration Parameters Explained:**

- `project_name`: Unique identifier for your project in Phoenix
- `auto_instrument`: Automatically instruments supported libraries
- `set_global_tracer_provider`: Prevents conflicts with other tracing systems
- `batch`: Enables batch processing of traces for better performance

**Example 2: Tool Update Service**

```python
register(
    project_name='update-tool',
    auto_instrument=True,
    set_global_tracer_provider=False,
    batch=True
)

with using_project('update-tool'):
    response = await update_tool_by_id(
        model_name=request.model_name,
        user_email_id=request.user_email_id,
        is_admin=request.is_admin,
        tool_id_to_modify=tool_id,
        tool_description=request.tool_description,
        code_snippet=request.code_snippet,
        updated_tag_id_list=request.updated_tag_id_list
    )
```

## Server Management

**Starting the Phoenix Server**

Launch the Phoenix server using the following command:

```bash
python -m phoenix.server.main serve
```

**Server Details for local:**

- **Default Port**: 6006
- **Endpoint**: `http://localhost:6006`
- **Purpose**: Provides web interface for trace visualization and analysis

**Server Details for VM:**

when we have network proxy on VM, before starting the backend uvicorn server set the following commands:

```bash
set HTTP_PROXY=
set NO_PROXY=localhost,127.0.0.1
```


## User Interface Features

**Phoenix Web UI Capabilities**

Once the server is running, access the web interface at `http://localhost:6006` in local.

**Project Management**

- View all registered projects in a centralized dashboard
- Monitor different services and applications separately
    ![all projects](../images/projects.png)


**Agent Monitoring**

- Track individual agent performances and behaviors
- Compare different models or configurations
    ![agent details](../images/agent_details.png)


- **Detailed Trace Inspection**: Examine complete request flows
- **Token Usage Tracking**: Monitor token consumption and costs
![agent trace details](../images/agent_trace_details.png)
- **Input/Output Analysis**: Review all inputs and outputs for debugging.

    sample input: 
    ![Input](../images/sample_input.png)
    sample output:
    ![Output](../images/sample_output.png)

- **Performance Metrics**: Analyze latency, throughput, and error rates
