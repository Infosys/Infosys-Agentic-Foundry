# Cost and Token Tracking

The Infyagent Framework provides comprehensive token usage tracking and cost calculation capabilities for all LLM operations. This system operates independently of LiteLLM proxy settings and provides detailed metrics for cost analysis, budget management, and operational insights.

---

## Architecture

**Core Components**

**1. Standalone Token Tracker**

**File**: `litellm_standalone_tracker.py`

- Tracks token usage for both LiteLLM proxy and direct Azure OpenAI calls
- Calculates costs using database-stored pricing data
- Logs all metrics to PostgreSQL database
- Works regardless of `USE_LITELLM_PROXY` setting

**2. Model Cost Service**

**File**: `src/services/model_cost_service.py`

- Maintains in-memory cache of model pricing
- Supports multiple cost lookup strategies
- Handles base model mapping and version-specific pricing
- Auto-updates costs from LiteLLM API every 2 days (when enabled)

**3. Telemetry Context System**

**File**: `telemetry_wrapper.py`

- Context-aware logging with OpenTelemetry integration
- Session tracking across async operations
- Agent and user identification in all logs

---

## Database Schema

**`llm_token_usage` Table**

Stores detailed token usage metrics for every LLM call:

```sql
CREATE TABLE llm_token_usage (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    agent_id VARCHAR,
    session_id VARCHAR,
    user_id VARCHAR,
    model VARCHAR NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cached_tokens INTEGER DEFAULT 0,
    cost DECIMAL(10, 6),
    request_id VARCHAR,
    metadata JSONB
);
```

**Key Fields**:

- `prompt_tokens` — Input tokens consumed
- `completion_tokens` — Output tokens generated
- `cached_tokens` — Tokens served from cache (reduced cost)
- `cost` — Calculated cost in USD
- `metadata` — Additional context (category, sub_category, etc.)

**`model_costs` Table**

Stores pricing information for LLM models:

```sql
CREATE TABLE model_costs (
    id SERIAL PRIMARY KEY,
    name VARCHAR UNIQUE NOT NULL,
    model_name VARCHAR,
    model_version VARCHAR,
    provider_key VARCHAR,
    input_cost_per_token DECIMAL(15, 10),
    output_cost_per_token DECIMAL(15, 10),
    cache_read_input_token_cost DECIMAL(15, 10),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

!!! note "Pricing Notes"
    - Costs are stored **per token** (not per 1M tokens)
    - Example: $0.15 per 1M tokens = `0.00000015` per token
    - Supports cache-read pricing for optimized costs

---

## Cost Calculation Logic

**4-Tier Fallback System**

The system uses a cascading lookup strategy to determine model costs:

```
1. Exact Match      (model_name + version)
         ↓
2. Deployment Name Match  (provider_key)
         ↓
3. Base Model Match  (gpt-4o-mini-2024-07-18 → gpt-4o-mini)
         ↓
4. Model Mapping    (.env variable)
```

**Cost Formula**

```python
total_cost = (
    (prompt_tokens * input_cost_per_token) +
    (completion_tokens * output_cost_per_token) +
    (cached_tokens * cache_read_input_token_cost)
)
```

**Example Calculation**:

```
Model: gpt-4o-mini
Prompt tokens:     1000
Completion tokens:  500
Cached tokens:      200

Input cost:  0.00000015 per token
Output cost: 0.00000060 per token
Cache cost:  0.00000008 per token

Total cost = (1000 × 0.00000015) + (500 × 0.00000060) + (200 × 0.00000008)
           = $0.00015 + $0.00030 + $0.000016
           = $0.000466
```

---

## Usage Examples

**Basic Token Tracking**

Token tracking happens automatically for all LLM calls through the framework. No manual instrumentation needed.

```python
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.schemas import AgentInferenceRequest

# Make an agent inference call
request = AgentInferenceRequest(
    query="What is machine learning?",
    agentic_application_id="agent-123",
    session_id="session-456",
    model_name="gpt-4o-mini"
)

# Token usage is automatically tracked and logged
async for response in inference_service.run(request):
    print(response)

# Check database for usage:
# SELECT * FROM llm_token_usage 
# WHERE session_id = 'session-456' 
# ORDER BY timestamp DESC;
```

**Setting Telemetry Context**

For operations that need explicit context (evaluations, tool calls):

```python
from telemetry_wrapper import set_context

# Set context before LLM operations
set_context(
    agent_id="agent-123",
    session_id="session-456",
    user_id="user@example.com"
)

# Make LLM calls - context automatically included in logs
response = await llm.ainvoke(prompt)
```

**Querying Token Usage**

**Total cost by agent:**
```sql
SELECT 
    agent_id,
    COUNT(*) as total_calls,
    SUM(total_tokens) as total_tokens,
    SUM(cost) as total_cost
FROM llm_token_usage
WHERE agent_id = 'agent-123'
GROUP BY agent_id;
```

**Cost breakdown by model:**
```sql
SELECT 
    model,
    COUNT(*) as calls,
    AVG(prompt_tokens) as avg_prompt_tokens,
    AVG(completion_tokens) as avg_completion_tokens,
    SUM(cost) as total_cost
FROM llm_token_usage
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY model
ORDER BY total_cost DESC;
```

**Session-level analysis:**
```sql
SELECT 
    session_id,
    MIN(timestamp) as session_start,
    MAX(timestamp) as session_end,
    COUNT(*) as total_interactions,
    SUM(total_tokens) as total_tokens,
    SUM(cost) as total_cost
FROM llm_token_usage
WHERE session_id = 'session-456'
GROUP BY session_id;
```

---

## Configuration

**Environment Variables**

```bash
# Token Tracking (Always Enabled)
DATABASE_URL=postgresql://user:pass@localhost:5432/infyagent

# LiteLLM Integration (Optional)
USE_LITELLM_PROXY=true
LITELLM_PROXY_BASE_URL=http://localhost:4000

# Model Cost Updates (Optional - when LiteLLM enabled)
# Costs auto-update every 2 days from LiteLLM API
```

### Configuration Notes

1. **Token tracking works in all modes:**

    - With LiteLLM proxy (`USE_LITELLM_PROXY=true`)
    - Without LiteLLM proxy (direct Azure OpenAI calls)

2. **Cost updates:**

    - When LiteLLM is enabled: Auto-updates from LiteLLM API every 2 days
    - When LiteLLM is disabled: Uses existing costs in database

3. **Database requirement:**

    - PostgreSQL database is **required** for token tracking
    - Tables are auto-created on startup

---

## Best Practices

**1. Session Management**

Always provide unique session IDs for tracking user conversations:

```python
import uuid
session_id = str(uuid.uuid4())
```

**2. Agent Identification**

Use consistent agent IDs for cost attribution:

```python
agentic_application_id = "customer-support-agent"
```

**3. Cost Monitoring**

Set up regular queries to monitor costs:

```sql
-- Daily cost summary
SELECT 
    DATE(timestamp) as date,
    SUM(cost) as daily_cost,
    SUM(total_tokens) as daily_tokens
FROM llm_token_usage
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

**4. Budget Alerts**

Create database triggers or scheduled jobs to alert on budget thresholds:

```sql
-- Example: Alert if daily cost exceeds $10
SELECT SUM(cost) FROM llm_token_usage 
WHERE DATE(timestamp) = CURRENT_DATE;
```

**5. Token Optimization**

Monitor token usage patterns to optimize prompts:

```sql
-- Find expensive queries
SELECT 
    agent_id,
    AVG(total_tokens) as avg_tokens,
    AVG(cost) as avg_cost
FROM llm_token_usage
GROUP BY agent_id
HAVING AVG(cost) > 0.01
ORDER BY avg_cost DESC;
```
