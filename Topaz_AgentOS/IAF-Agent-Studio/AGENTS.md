# AGENTS.md

> Instructions for AI coding agents working on this codebase.

## Project Overview

**IAF Agent Studio** is a zero-build web UI for the IAF Agent Skills framework. It provides:
- FastAPI server with WebSocket streaming for real-time chat
- Multi-agent management with skill/tool restrictions
- Skill Builder UI for creating multi-agentic skills (REACT, WORKFLOW, PARALLEL, SUPERVISOR)
- Reasoning trace panel showing agent thinking steps
- File browser with virtual filesystem access
- **OpenClaw Lane Queue Manager** for concurrency control
- **Batch Processing API** for parallel bulk operations
- **Generative UI Components** - Rich interactive responses (tables, charts, forms)
- **Light Mode Toggle** - Fast responses without memory/learning
- **Dark/Light Theme** - User-selectable UI theme
- **Cron Scheduler API** - Enterprise job scheduling with Redis backend
- **HITL Approval System** - Human-in-the-loop checkpoint & resume with Redis persistence
- **Dashboard v2** - Command surface with HITL queue, Knowledge Manager, cron monitoring
- **Knowledge Manager** - Full CRUD for agent knowledge with batch extraction from episodes
- **Skill Builder v2** - Enterprise Skill Designer Studio with 6-tab layout, agent management, MCP connections
- **MCP Connections** - Agent-level MCP server configuration (direct stdio/HTTP + enterprise registry)
- **Operational Digital Twin Dashboard** - Live telemetry, process health, skill usage, AR/AP drill-downs
- **ESAA Optimization Engine** - Two-tier process optimization (rule-based + LLM-powered analysis)
- **Trace Emitter** - Fire-and-forget agent observability with waterfall timeline views
- **Twin Emitter** - Operational telemetry writer powering the Digital Twin dashboard

### Architecture
```
IAF-Agent-Studio/
├── server.py              # FastAPI + WebSocket server (main entry point)
├── trace_emitter.py       # Agent observability — traces + spans to SQLite
├── twin_emitter.py        # Digital Twin telemetry writer to SQLite
├── esaa_enricher.py       # ESAA process optimization engine
├── static/
│   ├── index.html         # Main UI (Alpine.js + TailwindCSS CDN)
│   ├── dashboard.html     # Dashboard v1 (HITL approvals + cron)
│   ├── dashboard_v2.html  # Dashboard v2 (HITL + Knowledge Manager + stats)
│   ├── skill-builder.html # Skill Builder v1 (legacy)
│   └── skill-builder-v2.html # Skill Builder v2 — 6-tab enterprise designer
├── config.env             # Environment configuration (gitignored)
├── config.env.example     # Template for configuration
└── requirements.txt       # Python dependencies

# Data storage
enterprise_data/
└── tenants/
    └── company/           # tenant_id
        └── agents/
            └── {agent_id}/
                ├── config.yaml   # Agent configuration
                └── memory/       # Agent memory storage
                    ├── history/          # Episodic logs (JSONL by date/session)
                    └── context_graph/
                        └── knowledge.jsonl  # Knowledge store (JSONL)
```

### Key Components
- `SessionState` - Manages agent instances per user session
- `TraceEmitter` - Fire-and-forget trace writer (traces + spans → SQLite)
- `TwinBroadcaster` - WebSocket hub for real-time Digital Twin event streaming
- `TwinEmitter` - Async telemetry writer for operational events → `twin_telemetry.db`
- `SkillAgent` - LangGraph agent from IAF-Agent-Skills (supports 4 execution modes)
- `SafeKernel` - Sandboxed filesystem from agent_os
- `QueueManager` - OpenClaw lane-based concurrency control (Memory/Redis backends)
- `DashboardBroadcaster` - WebSocket hub for real-time dashboard event streaming
- `ApprovalStore` - Redis-backed HITL approval persistence and lifecycle management
- WebSocket handlers for streaming responses with reasoning trace
- REST APIs for skills, agents, chat, batch, queue, knowledge, and HITL management

## Build and Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run server (development)
python server.py
# Opens at http://localhost:8080

# Production
uvicorn server:app --host 0.0.0.0 --port 8080 --workers 4
```

## API Endpoints

### Chat API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Simple HTTP chat (non-streaming) |
| `/ws/chat` | WS | WebSocket streaming chat |

#### ChatMessage Schema
```json
{
  "content": "User message",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo",
  "skill_name": null,
  "human_approval": true,
  "render_ui": true,
  "light_mode": false
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `human_approval` | `true` | Ask-first mode (vs auto-run) |
| `render_ui` | `false` | Include UI component generation instructions |
| `light_mode` | `false` | Skip memory context + async learning for faster responses |

---

### Queue Management API (NEW)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/queue/status` | GET | Get all lane queue metrics |
| `/api/queue/{queue_name}/pending` | GET | Get pending tasks in a lane |
| `/api/queue/{queue_name}/cancel` | POST | Cancel all pending tasks in a lane |

```bash
# Check queue status
curl http://localhost:8080/api/queue/status

# Response:
{
  "backend": "memory",
  "pattern": "openclaw_lanes",
  "lanes": {
    "session:company:user123": {"queue_length": 0, "active": 1}
  },
  "metrics": {
    "total_enqueued": 42,
    "total_completed": 40,
    "avg_wait_time_ms": 12.5
  }
}
```

### Batch Processing API (NEW)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/batch` | POST | Process multiple requests in parallel |
| `/api/batch/status/{batch_id}` | GET | Get status of a batch job |

```bash
# Submit batch job
curl -X POST http://localhost:8080/api/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"content": "What is 2+2?", "item_id": "calc1"},
      {"content": "What is 3+3?", "item_id": "calc2"}
    ],
    "max_concurrent": 3,
    "default_skill": "general"
  }'

# Response:
{
  "batch_id": "abc123",
  "total": 2,
  "completed": 2,
  "failed": 0,
  "results": [
    {"item_id": "calc1", "status": "success", "skill": "general", "response": "4"},
    {"item_id": "calc2", "status": "success", "skill": "general", "response": "6"}
  ]
}
```

#### Batch Request Schema
```json
{
  "items": [{"content": "...", "item_id": "optional_id", "skill_name": null}],
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "batch",
  "max_concurrent": 3,
  "human_approval": false,
  "default_skill": "general"  // Skip router for faster batch
}
```

### Skills API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/skills` | GET | List all skills with metadata |
| `/api/skills` | POST | Create new skill (all execution modes) |
| `/api/skills/names` | GET | Simple list of skill names for dropdowns |
| `/api/skills/{name}` | GET | Get skill details for editing |
| `/api/skills/{name}` | PUT | Update existing skill |
| `/api/skills/{name}` | DELETE | Delete skill (protected: general) |

#### Create/Update Skill Request
```json
{
  "name": "my_skill",
  "description": "What this skill does",
  "execution_mode": "workflow",  // react | workflow | parallel | supervisor
  "keywords": ["trigger", "words"],
  "prompt": "# System Prompt\n\nInstructions...",
  "steps": [  // For workflow/parallel modes
    {
      "name": "step1",
      "action": "shell",
      "command": "echo hello"
    },
    {
      "name": "step2", 
      "action": "skill",
      "skill": "general",
      "task": "Analyze {step1.output}"
    }
  ],
  "worker_skills": [  // For supervisor mode
    {"name": "ar_ops"},
    {"name": "invoice"}
  ]
}
```

### Agents API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents` | GET | List all agents |
| `/api/agents` | POST | Create new agent |
| `/api/agents/{id}` | GET | Get agent details |
| `/api/agents/{id}` | PUT | Update agent config |
| `/api/agents/{id}` | DELETE | Delete agent (protected: enterprise_agent, studio_agent) |

#### Agent Config Schema
```yaml
# enterprise_data/tenants/company/agents/{agent_id}/config.yaml
agent:
  name: "Agent Name"
  description: "What this agent does"
  version: "1.0"

skills:
  mode: all  # all | allowlist | denylist
  allowed: []  # For allowlist mode
  denied: []   # For denylist mode

tools:
  allowed:
    - shell          # ls, cat, echo, mkdir, find, grep
    - run_sql_query  # Database access

mcp:
  connections:
    - name: "calculator"
      type: "direct"
      transport: "http"
      url: "http://localhost:9876/mcp"
    - name: "enterprise-registry"
      type: "registry"
      url: "${MCP_REGISTRY_URL}"
      auth:
        type: "bearer"
        token: "${MCP_TOKEN}"
      server_filter: ["approved-tool-server"]

audit:
  log_queries: true
  log_responses: true
  log_tool_calls: true
```

### WebSocket API

Connect to `/ws/chat` for streaming chat:

```javascript
const ws = new WebSocket('ws://localhost:8080/ws/chat');

// Send message
ws.send(JSON.stringify({
  content: "Hello",
  tenant_id: "company",
  agent_id: "studio_agent",
  user_id: "demo",
  skill: null  // or specific skill name
}));

// Receive events
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // data.type: routing | tool_call | tool_result | response | error | heartbeat
};
```

## UI Toggles (Header Bar)

### Human Approval Toggle
Controls whether tools require confirmation before execution:

| State | Icon | Behavior |
|-------|------|----------|
| **Ask First** | 🔒 | Tools ask for confirmation (yellow) |
| **Auto-Run** | 🚀 | Tools execute immediately (green glow) |

### Light Mode Toggle (NEW)
Controls memory and learning operations:

| State | Icon | Behavior |
|-------|------|----------|
| **Learn** | 🧠 | Full context + learning enabled (purple) |
| **Fast** | ⚡ | Skip memory + learning for speed (cyan) |

Saves 2-4 LLM calls per request. Use for quick Q&A.

### Theme Toggle
| State | Icon | Behavior |
|-------|------|----------|
| **Dark** | 🌙 | Dark terminal theme (default) |
| **Light** | ☀️ | Light professional theme |

---

## Generative UI Components (NEW)

When `render_ui=true`, agent responses can include interactive components:

### Component Registry

| Component | Purpose | Example Use |
|-----------|---------|-------------|
| `ui:data_table` | Structured data with actions | Invoice lists, search results |
| `ui:stat_cards` | KPI tiles (max 4) | Dashboard summaries |
| `ui:chart` | Visualizations | Trends, comparisons |
| `ui:action_buttons` | Follow-up actions | Export, approve, reject |
| `ui:progress` | Status indicators | Processing progress |
| `ui:alert` | Notifications | Warnings, success, info |
| `ui:form` | Input collection | Quick approval reasons |
| `ui:accordion` | Collapsible sections | FAQ content |
| `ui:list` | Simple lists | Bullet points |

### Rendering Flow

1. Agent outputs: ` ```ui:data_table {...}``` `
2. Frontend parses markdown, extracts `ui:` blocks
3. Component registry renders appropriate HTML
4. Action buttons send new messages to chat

### Example Response

```markdown
Here are 3 pending invoices:

```ui:data_table
{
  "title": "Pending Invoices",
  "columns": ["Invoice #", "Amount", "Due Date"],
  "rows": [["INV-001", "$5,000", "Feb 15"]],
  "actions": ["Approve", "Reject"]
}
```

```ui:action_buttons
{"buttons": [{"label": "Export CSV", "icon": "📥", "style": "primary"}]}
```
```

---

## UI Pages

### Main Chat UI (/)
- Chat interface with message history
- Reasoning panel (toggle with 🔍 button)
- File browser panel
- Skills modal (🎯 button) - view/select skills
- Agents modal (🤖 button) - manage agents

### Dashboard v1 (/dashboard)
- HITL approval queue with approve/reject actions
- Cron job status and run history

### Dashboard v2 (/dashboard/v2) (NEW)
- Three-tab command surface: HITL Approvals, Knowledge Manager, Cron/Stats
- Real-time WebSocket updates via `DashboardBroadcaster`
- Knowledge CRUD with inline edit, confirm, reject
- Batch knowledge extraction trigger
- See **Dashboard v2** section above for implementation details

### Skill Builder (/skill-builder)
Full-featured skill creation/editing page:
- Mode selector: REACT, Workflow, Parallel, Supervisor
- Dynamic form sections based on mode
- Step builder for workflow/parallel (add/remove steps)
- Worker builder for supervisor mode
- Live YAML preview
- Create/Update/Delete support
- Edit existing skill via URL: `/skill-builder?edit=skill_name`

## Code Style Guidelines

### Python (server.py)
- **Python 3.10+** required
- **Type hints** on all function signatures
- **async/await** for all endpoint handlers
- **Pydantic models** for request/response validation
- Use `Path` from pathlib for file operations
- Max line length: 100 characters

### Frontend (static/*.html)
- **No build step** - CDN dependencies only
- **Alpine.js** for reactivity (`x-data`, `x-on`, `x-show`, etc.)
- **TailwindCSS** for styling (utility classes)
- Keep all JavaScript inline in the HTML file
- Use template literals for dynamic content

## Key Files Reference

### server.py
- Lines 1-40: Imports and config loading
- Lines 185-220: Pydantic models (SkillCreate, SkillStep, WorkerSkill, AgentConfig)
- Lines 256-265: Static routes (/, /skill-builder)
- Lines 389-600: Skills API endpoints
- Lines 600-820: Agents API endpoints
- Lines 900-1100: WebSocket chat handler

### static/index.html
- Lines 1-110: HTML head, fonts, Tailwind config
- Lines 111-460: Main layout (header, chat, panels, toolbar)
- Lines 462-620: Modals (Skills, Create Skill)
- Lines 620-800: Agent Management Modal
- Lines 800-1000: Alpine.js data and init
- Lines 1000-1200: Message handling and WebSocket
- Lines 1200-1400: Skills and Agents functions
- Lines 1400-1600: Utility functions

### static/skill-builder.html
- Lines 1-60: HTML head with js-yaml CDN
- Lines 60-300: Form layout (basic info, mode selector, step builders)
- Lines 300-400: YAML preview panel
- Lines 400-600: Alpine.js skillBuilder() component

## Testing Instructions

1. **Test skill CRUD via API:**
   ```bash
   # Create
   curl -X POST http://localhost:8080/api/skills \
     -H "Content-Type: application/json" \
     -d '{"name":"test","description":"Test","execution_mode":"react","prompt":"Hello"}'
   
   # Read
   curl http://localhost:8080/api/skills/test
   
   # Update
   curl -X PUT http://localhost:8080/api/skills/test \
     -H "Content-Type: application/json" \
     -d '{"name":"test","description":"Updated","execution_mode":"react","prompt":"Updated"}'
   
   # Delete
   curl -X DELETE http://localhost:8080/api/skills/test
   ```

2. **Test execution modes via UI:**
   - `what is 5+5` → REACT mode (general skill)
   - `run workflow test` → WORKFLOW mode
   - `run parallel report` → PARALLEL mode
   - `run supervisor report` → SUPERVISOR mode

3. **Test agent management:**
   - Click 🤖 Agents → New Agent
   - Set skills mode to Allowlist, select skills
   - Create agent, switch to it, verify skill restrictions

4. **Test Skill Builder:**
   - Open /skill-builder
   - Create a workflow skill with 2 steps
   - Verify YAML preview
   - Save and test via chat

---

## Skill Builder v2 (/skill-builder/v2)

Enterprise Skill Designer Studio — full redesign with dark Tailwind palette, sidebar navigation, and 6-tab layout. Replaces the legacy `/skill-builder`.

### Tabs

| Tab | Function |
|-----|----------|
| **Skills** | Card grid with search/filter, create/edit/delete skills, mode selector (REACT/WORKFLOW/PARALLEL/SUPERVISOR), step builder, YAML preview |
| **Tools** | Custom Python tool scripts — create/edit/delete tools with TOOL_SPEC, group by skill |
| **Connections** | Database connections — verify connectivity, map to agents |
| **Knowledge** | Per-agent knowledge CRUD (confirm/reject/edit), batch extraction, stats |
| **Agents** | Full agent management — create/edit/delete, skills mode, tools, **MCP connections** editor |
| **Test** | Interactive test panel for skill invocation |

### MCP Connections (in Agents Tab)

The agent create/edit modal includes an MCP Connections section:
- **Add Connection** button — choose type (direct/registry), configure transport (stdio/http)
- Each connection renders as an inline card with type badge (cyan=direct, purple=registry)
- **Direct (stdio):** command, args fields
- **Direct (http):** URL field
- **Registry:** URL, auth token, server filter list
- Connections saved to `config.yaml` under `mcp.connections[]`

### Route
```
GET /skill-builder/v2 → static/skill-builder-v2.html
```

---

## Operational Digital Twin Dashboard

Live operational analytics at `/twin` with real-time WebSocket push. Feature-flagged via `TWIN_TELEMETRY` env var.

### UI Routes

| Route | Description |
|-------|-------------|
| `GET /twin` | Main Twin dashboard - task summary, skill usage, HITL metrics, trends |
| `GET /twin/optimization` | ESAA process optimization page |

### Twin API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/twin/summary` | GET | Aggregate task metrics (total, succeeded, failed, avg latency) |
| `/api/twin/skills` | GET | Skill usage breakdown (counts, latency by skill) |
| `/api/twin/hitl` | GET | HITL metrics (pending, resolved, avg resolution time) |
| `/api/twin/trends` | GET | Time-series trends (hourly/daily aggregates) |
| `/api/twin/ar` | GET | AR-specific operational metrics |
| `/api/twin/ap` | GET | AP-specific operational metrics |
| `/api/twin/exceptions` | GET | Exception patterns and rates |
| `/api/twin/feed` | GET | Live event feed (recent operational events) |
| `/api/twin/drill/ar` | GET | AR drill-down (by customer, aging bucket) |
| `/api/twin/drill/ap` | GET | AP drill-down (by vendor, status) |
| `/api/twin/drill/exceptions` | GET | Exception drill-down (by type, frequency) |
| `/api/twin/drill/task` | GET | Task drill-down (by skill, status) |
| `/api/twin/process_health` | GET | Process health heatmap by tower/L2 |

### WebSocket

`/ws/twin` — real-time push of task lifecycle, HITL, and skill usage events via `TwinBroadcaster`.

---

## ESAA Process Optimization Engine

Two-tier process optimization accessible at `/twin/optimization`.

### Tiers

| Tier | Method | Cache TTL | Description |
|------|--------|-----------|-------------|
| **Tier 1** | Rule-based SQL queries | 15 seconds | Exception patterns, SLA breaches, volume anomalies from `twin_telemetry.db` |
| **Tier 2** | LLM-powered analysis | 4 hours | Deep root-cause analysis, process redesign recommendations |

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/twin/optimization` | GET | Cached Tier 1 recommendations |
| `/api/twin/optimization/analyze` | POST | Trigger Tier 2 LLM analysis (async job) |
| `/api/twin/optimization/status/{job_id}` | GET | Check async analysis job status |

---

## Trace Emitter (trace_emitter.py)

Fire-and-forget agent observability system. Records every step (span) within every request (trace) to SQLite for waterfall timeline views, latency analysis, and root-cause debugging.

### Tables

| Table | Fields | Purpose |
|-------|--------|---------|
| `traces` | trace_id, tenant_id, agent_id, user_id, skill, status, latency_ms, created_at | Per-request summary |
| `spans` | span_id, trace_id, parent_span_id, name, kind, status, start_ms, end_ms, attributes | Per-step detail |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/traces` | GET | List traces with filters and pagination |
| `/api/traces/{trace_id}` | GET | Single trace with all child spans |
| `/api/reasoning/{trace_id}` | GET | Reasoning trace view for agent debugging |

### Design

- **Fire-and-forget** — async queue with single background writer, never blocks agent execution
- **Single-writer** — SQLite WAL mode, one background thread handles all writes
- **Pluggable exporters** — designed for OpenTelemetry/Datadog/Kafka integration

---

## Twin Emitter (twin_emitter.py)

Fire-and-forget telemetry writer powering the Digital Twin dashboard. Writes operational events to `twin_telemetry.db` SQLite database.

### Event Types

| Event | Trigger |
|-------|---------|
| `task_started` | Agent begins processing a request |
| `task_completed` | Agent finishes successfully |
| `task_error` | Agent encounters an error |
| `hitl_requested` | Agent requests human approval |
| `hitl_resolved` | Human resolves approval |
| `skill_usage` | Skill invocation recorded |

### Design

- **Feature-flagged** — `TWIN_TELEMETRY` env var (disabled = no overhead)
- **Never-block** — async queue with single background writer
- **Powers** — all `/api/twin/*` endpoints and `/ws/twin` WebSocket

---

## Common Issues

### "ModuleNotFoundError: No module named 'agent_os'"
Ensure sys.path includes parent directory:
```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### WebSocket connection fails
Check that no other process is using port 8080:
```bash
lsof -i :8080
```

### Skills not showing in Agent modal
Ensure `loadSkills()` is called when opening Agents modal.

### Skill Builder not loading skills
Check `/api/skills/names` endpoint returns data.

### YAML import error
Ensure `import yaml` is at top of server.py.

## Dependencies

External packages (requirements.txt):
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `python-dotenv` - Environment loading
- `python-multipart` - File uploads
- `websockets` - WebSocket support
- `pyyaml` - YAML parsing
- `redis` - Redis client (required for HITL approvals, cron, sessions, queues)
- `httpx` - Async HTTP client (ESAA engine, MCP registry adapter)

Internal dependencies:
- `agent_os.SafeKernel` - From sibling directory
- `iaf_agent_skills.SkillAgent` - From IAF-Agent-Skills
- `iaf_agent_skills.SkillRouter` - Skill routing
- `iaf_agent_skills.SkillLoader` - Skill loading
- `iaf_agent_skills.queue_manager` - Lane queue concurrency control
- `iaf_agent_skills.approval_store` - HITL approval persistence (Redis-backed)
- `iaf_agent_skills.session_store` - Redis-backed session state
- `iaf_agent_skills.task_integration` - Chat task visibility in Redis
- `iaf_agent_skills.tools.MCPToolBridge` - MCP server integration
- `iaf_agent_skills.knowledge_indexer` - Semantic knowledge index

## Concurrency Control (OpenClaw Pattern)

The server uses lane-based queuing for concurrency control:

```python
# Same user = serial execution (prevents race conditions)
# Different users = parallel execution
lane_name = QueueNames.session(tenant_id, user_id)

response = await queue_manager.enqueue(
    lane_name,
    lambda: agent.run(message),
    max_concurrent=1  # Serial per user
)
```

### Queue Backends

1. **Memory** (default): In-process, no external dependencies
   ```python
   queue = create_queue_manager()  # Uses memory by default
   ```

2. **Redis** (enterprise): Persistent, multi-server
   ```python
   queue = create_queue_manager(QueueConfig(
       backend=QueueBackend.REDIS,
       redis_url="redis://localhost:6379"
   ))
   ```

Switch backends via environment:
```bash
QUEUE_BACKEND=redis
REDIS_URL=redis://localhost:6379
```

## Key Server Features

### Activity Streaming
Captures agent's print output and streams to WebSocket in real-time:
- Loading memory messages
- LLM calls
- Tool execution progress
- Reasoning steps

### Reload Excludes
Server won't restart when files change in these patterns:
```python
reload_excludes=["workspaces/*", "*.pyc", "__pycache__/*"]
```

This prevents restarts during code execution in sandboxed workspaces.

## Cron Scheduler API (NEW)

Enterprise job scheduling with Redis backend:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cron/jobs` | GET | List all cron jobs |
| `/api/cron/jobs` | POST | Create new cron job |
| `/api/cron/jobs/{id}` | GET | Get job details |
| `/api/cron/jobs/{id}` | PUT | Update job config |
| `/api/cron/jobs/{id}` | DELETE | Delete job |
| `/api/cron/jobs/{id}/run` | POST | Trigger immediate run |
| `/api/cron/jobs/{id}/runs` | GET | Get job run history |
| `/api/cron/runs/{run_id}` | GET | Get run details |

### Create Job Request
```json
{
  "name": "Daily AR Summary",
  "skill_name": "ar_ops",
  "task": "Generate daily AR aging report",
  "cron": "0 9 * * *",
  "enabled": true,
  "tenant_id": "company",
  "agent_id": "enterprise_agent"
}
```

### Cron Expression Examples
- `0 9 * * *` - Daily at 9am
- `*/15 * * * *` - Every 15 minutes
- `0 8-17 * * 1-5` - Hourly 8am-5pm weekdays
- `0 0 1 * *` - Monthly on the 1st at midnight

---

## HITL Approval System (NEW)

Human-in-the-loop checkpoint & resume pattern. Agents pause for human decisions, persist state to Redis, and resume when resolved.

### Architecture

1. Agent calls `request_human_approval()` tool during execution
2. Server persists approval request + full agent state to Redis via `ApprovalStore`
3. Agent execution cleanly pauses (returns message to user)
4. Human resolves via Dashboard v2 or REST API (hours/days later)
5. Resume engine restores agent state, injects decision, continues execution

### HITL API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/hitl/pending` | GET | List pending approvals (Redis ZSET) |
| `/api/hitl/history` | GET | Resolved approval history (capped at 500) |
| `/api/hitl/stats` | GET | Approval statistics (pending/resolved/expired counts) |
| `/api/hitl/{approval_id}` | GET | Get single approval details |
| `/api/hitl/{approval_id}/resolve` | POST | Resolve approval (approve/reject/escalate) |

### Resolve Request
```json
{
  "decision": "approved",
  "decided_by": "john.doe",
  "decision_note": "Approved after reviewing amounts"
}
```

### Redis Key Structure
```
iaf:approval:{approval_id}               → HASH (approval record)
iaf:approval:pending:{tenant_id}         → ZSET (pending, sorted by created_at)
iaf:approval:history:{tenant_id}         → LIST (resolved, capped at 500)
iaf:approval:agent_state:{approval_id}   → STRING (JSON blob of checkpointed agent state)
```

### Dashboard WebSocket Events

The `DashboardBroadcaster` streams real-time events to `/ws/dashboard`:

| Event Type | Trigger |
|------------|---------|
| `hitl_approval_new` | Agent requests approval |
| `hitl_resolved` | Human resolves approval |
| `cron_started` | Cron job begins execution |
| `cron_completed` | Cron job finishes (success/failure/paused_for_approval) |

### Kernel-Level Approvals (Legacy)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/approvals/queue` | GET | Legacy per-session pending actions |
| `/api/approvals/{user_id}/approve` | POST | Approve pending kernel action |
| `/api/approvals/{user_id}/reject` | POST | Reject pending kernel action |

---

## Knowledge Manager API (NEW)

Full CRUD for persistent agent knowledge with HITL review workflow.

### Knowledge Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/knowledge` | GET | List knowledge items with filters |
| `/api/knowledge/stats` | GET | Knowledge statistics by status/type/source |
| `/api/knowledge/confirm` | POST | Confirm a pending knowledge item |
| `/api/knowledge/reject` | POST | Reject (archive) a knowledge item |
| `/api/knowledge/edit` | POST | Edit knowledge in-place (preserves status) |
| `/api/knowledge/batch-extract` | POST | Mine episodes for new knowledge via LLM |

### Query Parameters for GET `/api/knowledge`

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | `"confirmed"` | Filter: `confirmed`, `pending_review`, `archived`, `all` |
| `knowledge_type` | string | `null` | Filter: `fact`, `preference`, `procedure`, `pattern`, `correction` |
| `source` | string | `null` | Filter: `explicit`, `batch_extract`, `implicit` |
| `include_archived` | bool | `false` | Include archived items (auto-true when status=`all`) |
| `limit` | int | `50` | Page size |
| `offset` | int | `0` | Pagination offset |

### Knowledge Action Schema (Confirm/Reject)
```json
{
  "knowledge_id": "kn_abc123",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

### Knowledge Edit Schema
```json
{
  "knowledge_id": "kn_abc123",
  "summary": "Updated summary text",
  "knowledge_type": "fact",
  "applies_when": "When processing US invoices",
  "tags": ["ar", "invoices"],
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

The edit endpoint performs an **in-place update** — it preserves the current status (pending stays pending, confirmed stays confirmed). This differs from the old learn+reject pattern which always created a new confirmed record.

### Batch Extract Schema
```json
{
  "hours_back": 24,
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

Response:
```json
{
  "extracted": 11,
  "skipped_duplicates": 3,
  "errors": 0,
  "total_episodes": 44
}
```

### Cron Bridge for Batch Extract

The cron executor recognizes `batch_extract_knowledge` as a special task name:

```json
{
  "name": "Nightly Knowledge Extract",
  "skill_name": "general",
  "task": "batch_extract_knowledge",
  "cron": "0 2 * * *",
  "enabled": true
}
```

When `job.task == "batch_extract_knowledge"`, the executor calls `agent.memory.batch_extract_knowledge()` directly instead of `agent.run()`.

---

## Feedback & Learning API (NEW)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/thumbs` | POST | Thumbs up/down feedback on a response |
| `/api/learn` | POST | Teach agent explicit knowledge |

### Thumbs Feedback Schema
```json
{
  "message_index": 0,
  "direction": "up",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

### Learn Request Schema
```json
{
  "content": "When processing AP invoices, always check the 3-way match",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

---

## Dashboard v2 (NEW)

Accessible at `/dashboard/v2`. Command surface with three main tabs:

### HITL Approvals Tab
- Real-time pending approval cards with urgency badges (critical/high/medium/low)
- Approve/Reject/Escalate buttons
- Decision notes input
- SLA countdown timers
- History table with resolution details
- WebSocket-driven auto-refresh on `hitl_approval_new` / `hitl_resolved` events

### Knowledge Manager Tab
- Tabbed filters: All / Confirmed / Pending / Archived
- Source filter: All / Explicit / Batch Extract / Implicit
- Knowledge cards with inline **Edit** (✎), **Confirm** (✓), **Reject** (✕) buttons
- Edit mode: editable summary textarea, type dropdown, applies_when input
- **Extract Now** button (⚡) — triggers `/api/knowledge/batch-extract` on-demand
- Stats bar: total, confirmed, pending, archived counts
- Pagination with offset/limit

### Alpine.js Button Pattern (Important for Maintenance)

Dashboard v2 knowledge buttons use **vanilla JS capture-phase handlers** instead of Alpine `@click`. This is required because nested `<template x-if>` inside `<template x-for>` swallows Alpine click events.

```javascript
// Buttons use class="v2-kn-btn" + data-kn-action + data-kn-id (set via x-init)
// Fields use data-kn-field="summary|type|applies_when" (NOT $refs)
// x-init (NOT x-effect) for field initialization to prevent overwriting user edits

// Vanilla JS capture-phase handler at bottom of file:
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.v2-kn-btn');
  if (!btn) return;
  const action = btn.dataset.knAction;
  const id = btn.dataset.knId;
  // ... direct fetch() calls + Alpine.evaluate() for state refresh
}, true);  // capture phase
```

**Do NOT replace this with Alpine @click** — the nested template bug will resurface.

### Dashboard API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/dashboard` | GET | Dashboard v1 (simpler HITL + cron view) |
| `/dashboard/v2` | GET | Dashboard v2 (full command surface) |
| `/ws/dashboard` | WS | Real-time event stream for dashboard |
| `/api/dashboard/summary` | GET | Aggregate stats (agents, skills, cron jobs, queues, HITL) |

---

---

## Memory Dashboard (NEW)

The dashboard_v2.html `#memory` page provides a 5-tab visualization of the agent's memory system. Accessible via the Memory tab in Dashboard v2.

### Sub-Tabs

| Tab | Description |
|-----|-------------|
| **Overview** | Memory stats (knowledge, episodes, session counts), quick actions |
| **Ontology** | Entity registry tree view (APQC taxonomy: L1→L2→L3→L4), click nodes to open detail panel |
| **Search** | Semantic search across knowledge and episodes |
| **Entity Usage** | Top-N entities by reference count, click to see detail |
| **Sessions** | Session history browser |

### Entity Detail Panel

Slide-out panel triggered by clicking any entity in Ontology or Entity Usage tabs:

| Section | Content |
|---------|---------|
| **Identity** | node_id, node_type, display_name, skill_name (if skill node) |
| **Breadcrumb** | Full path from root: F&A → O2C → AR Operations → skill:ar_ops |
| **Aliases** | Alternative names for the entity |
| **Linked Knowledge** | Knowledge records tagged with this entity |
| **Linked Episodes** | Recent episodes that mention this entity |

---

## Entity Ontology APIs (NEW)

APIs for the hybrid entity ontology system (APQC taxonomy + dynamic entities).

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/memory/ontology` | GET | Returns full entity tree for visualization |
| `/api/memory/entity-usage` | GET | Top-N entities by usage count |
| `/api/memory/entity/{node_id}` | GET | Single entity detail (identity, breadcrumb, linked_knowledge, linked_episodes) |
| `/api/memory/entity-path` | GET | Get hierarchical path for a node_id |
| `/api/memory/taxonomy` | GET | List taxonomy nodes (filters: node_type, parent_id) |
| `/api/memory/entity-register` | POST | Create/update entity in registry |
| `/api/memory/entity-graph` | GET | Entity relationship graph for visualization |
| `/api/memory/traversal-path` | GET | Traverse from one entity to another |
| `/api/memory/simulate-routing` | GET | Simulate skill routing for a query |
| `/api/memory/entity-intelligence-recommendations` | GET | LLM-generated suggestions for entity structure |

### GET /api/memory/ontology Response

```json
{
  "tree": {
    "node_id": "apqc:l1:fa",
    "display_name": "Finance & Accounting",
    "node_type": "tower",
    "skill_name": null,
    "children": [
      {
        "node_id": "apqc:l2:o2c",
        "display_name": "Order to Cash",
        "node_type": "process",
        "children": [...]
      }
    ]
  },
  "total_nodes": 45,
  "skill_nodes": 18
}
```

### GET /api/memory/entity/{node_id} Response

```json
{
  "identity": {
    "node_id": "skill:ar_ops",
    "node_type": "skill",
    "display_name": "AR Operations",
    "skill_name": "ar_ops",
    "aliases": ["AR ops", "receivables ops"]
  },
  "breadcrumb": [
    {"node_id": "apqc:l1:fa", "display_name": "Finance & Accounting"},
    {"node_id": "apqc:l2:o2c", "display_name": "Order to Cash"},
    {"node_id": "apqc:l3:ar_ops", "display_name": "AR Operations"},
    {"node_id": "skill:ar_ops", "display_name": "AR Operations"}
  ],
  "linked_knowledge": [
    {"knowledge_id": "kn_abc123", "summary": "AR aging buckets: 0-30, 31-60, 61-90, 90+", "status": "confirmed"}
  ],
  "linked_episodes": [
    {"trace_id": "tr_xyz789", "query": "show AR aging", "timestamp": "2026-03-09T10:00:00Z"}
  ]
}
```

### GET /api/memory/entity-usage Response

```json
{
  "entities": [
    {"node_id": "skill:ar_ops", "display_name": "AR Operations", "usage_count": 142},
    {"node_id": "skill:invoice", "display_name": "Invoice Approval", "usage_count": 98}
  ],
  "total": 25
}
```

---

## Databases (Important)

The system uses **two separate SQLite databases** — do not confuse them:

| Database | Created By | Location | Tables |
|----------|------------|----------|--------|
| `agent_knowledge.db` | `seed_entity_registry.py` | `workspaces/default/context_graph/` | `entity_registry` |
| `knowledge_index.db` | KnowledgeIndexer (runtime) | `enterprise_root/.../memory/` | `knowledge_vectors`, `episode_vectors`, `entity_xref`, `fts_knowledge` |

### entity_registry table (agent_knowledge.db)

Stores the APQC process taxonomy and skill→node mappings:

```sql
CREATE TABLE entity_registry (
    node_id       TEXT PRIMARY KEY,  -- "apqc:l2:o2c" or "skill:ar_ops"
    node_type     TEXT NOT NULL,     -- "tower", "process", "activity", "skill"
    display_name  TEXT NOT NULL,
    parent_id     TEXT,              -- FK to parent node_id
    skill_name    TEXT,              -- For skill nodes only
    embedding     BLOB,
    metadata_json TEXT DEFAULT '{}',
    aliases_json  TEXT DEFAULT '[]',
    updated_at    TEXT
);
```

### Seed Scripts

| Script | Command | Purpose |
|--------|---------|---------|
| Entity Registry | `python3 IAF-Agent-Skills/scripts/seed_entity_registry.py` | Seeds APQC taxonomy into `agent_knowledge.db` |
| Twin Demo | `python3 IAF-Agent-Studio/seed_twin_demo.py` | Creates demo data in `twin_telemetry.db`, `ar_receivables.db` |

---

## Additional Documentation

- **[CRON_SCHEDULER.md](./CRON_SCHEDULER.md)** - Enterprise cron scheduler with Redis backend, distributed workers, and Kubernetes deployment guide

