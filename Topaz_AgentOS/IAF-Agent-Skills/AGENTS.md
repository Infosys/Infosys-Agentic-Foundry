# AGENTS.md

> Instructions for AI coding agents working on this codebase.

## Project Overview

**IAF-Agent-Skills** is the multi-agentic skill framework for enterprise AI agents. It provides:
- **SkillRouter** - LLM-based query classification with keyword shortcuts
- **SkillLoader** - Dynamic loading of skills from SKILL.md files  
- **SkillAgent** - LangGraph agent that routes and executes skills
- **Execution Engines** - 4 execution modes (REACT, WORKFLOW, PARALLEL, SUPERVISOR)
- **Memory System** - Persistent learning, context retention, and knowledge management
- **Knowledge Manager** - CRUD for agent knowledge with batch extraction from episodes
- **Knowledge Indexer** - SQLite-backed semantic index (embeddings + FTS5 fallback)
- **Entity Registry** - APQC process taxonomy tree (tower→process→activity→skill hierarchy)
- **Conversation Manager** - Session history tracking and management
- **Queue Manager** - OpenClaw-style lane queuing with Memory/Redis backends
- **HITL Approval System** - Rule-based human-in-the-loop with checkpoint & resume
- **Approval Rules Engine** - Pure-function evaluator for skill-level approval policies
- **MCP Tool Bridge** - Unified adapter for direct MCP servers and Enterprise MCP Registry
- **Skill Tool Loader** - Auto-discovers bundled Python tools from skill `tools/` subfolders
- **Code Executor Tool** - Wraps Smart Code Executor for agent Python/JS/Bash execution
- **Session Store** - Redis-backed session state for horizontal scaling

### Architecture
```
IAF-Agent-Skills/
├── iaf_agent_skills/
│   ├── __init__.py       # Package exports
│   ├── agent.py          # SkillAgent - main orchestrator with multi-mode execution
│   ├── router.py         # SkillRouter - query classification
│   ├── loader.py         # SkillLoader - SKILL.md parsing with execution mode support
│   ├── execution.py      # WorkflowEngine, ParallelEngine, SupervisorEngine
│   ├── memory.py         # Agent memory system (knowledge, episodes, context graph)
│   ├── queue_manager.py  # OpenClaw lane-based concurrency control
│   ├── approval_store.py # Redis-backed HITL approval persistence
│   ├── approval_rules.py # Pure-function rule evaluator for approval policies
│   ├── knowledge_indexer.py # SQLite semantic index (embeddings + FTS5 fallback)
│   ├── entity_registry.py   # APQC taxonomy tree (entity_registry table in agent_knowledge.db)
│   ├── conversation_manager.py # Session history tracking
│   ├── session_store.py  # Redis-backed session state for horizontal scaling
│   ├── task_integration.py # Chat task visibility in Redis
│   ├── tools/            # LangChain tool wrappers
│   │   ├── __init__.py   # Exports: create_code_executor_tool, MCPToolBridge
│   │   ├── mcp_bridge.py # MCP direct + registry adapter → StructuredTool
│   │   ├── code_executor.py  # Smart Code Executor wrapper
│   │   └── skill_tool_loader.py # Bundled Python tool discovery (AST-based)
│   └── scheduler/        # Enterprise cron scheduler
│       ├── models.py     # Job, JobRun, RunStatus
│       ├── scheduler.py  # CronScheduler orchestrator
│       ├── store.py      # JobStore abstract base
│       ├── redis_store.py       # Async Redis backend
│       ├── sync_redis_store.py  # Sync Redis backend
│       └── worker.py     # CLI worker for scaling
├── scripts/              # Seed and utility scripts
│   ├── seed_entity_registry.py  # Seeds APQC taxonomy into agent_knowledge.db
│   ├── seed_skill_aliases_from_l5.py
│   ├── clean_entity_registry.py
│   └── clean_noisy_entities.py
├── skills/
│   ├── _index.yaml       # Skill registry with descriptions & keywords
│   ├── general/SKILL.md
│   ├── ar_ops/SKILL.md
│   ├── invoice/SKILL.md
│   ├── parallel_report/SKILL.md   # Parallel execution example
│   ├── supervisor_report/SKILL.md # Supervisor mode example
│   └── workflow_test/SKILL.md     # Workflow example
└── tests/
```

## Execution Modes

Skills can operate in 4 different execution modes:

### 1. REACT Mode (Default)
LLM reasoning loop with tool calls. Best for open-ended, complex tasks.

```yaml
---
name: general
execution_mode: react  # or omit (default)
---
# Prompt for LLM
```

### 2. WORKFLOW Mode
Deterministic sequential steps. Best for predictable multi-step processes.

```yaml
---
name: workflow_test
execution_mode: workflow
steps:
  - name: step1
    action: shell
    command: "echo 'Step 1'"
  - name: step2
    action: skill
    skill: general
    task: "Analyze the output from step1: {step1.output}"
  - name: step3
    action: condition
    check: "{step2.output}"
    operator: contains
    value: "success"
    on_true: step4
    on_false: END
---
```

### 3. PARALLEL Mode
Concurrent execution with dependency DAG. Best for independent tasks.

```yaml
---
name: parallel_report
execution_mode: parallel
steps:
  - name: get_ar_summary
    action: skill
    skill: ar_ops
    task: "Summarize AR status"
    depends_on: []  # Wave 1 - runs in parallel
    
  - name: get_invoice_summary
    action: skill
    skill: invoice
    task: "Summarize open invoices"
    depends_on: []  # Wave 1 - runs in parallel
    
  - name: create_executive_summary
    action: skill
    skill: general
    task: "Create executive summary from: AR: {get_ar_summary.output}, Invoice: {get_invoice_summary.output}"
    depends_on: [get_ar_summary, get_invoice_summary]  # Wave 2 - waits for Wave 1
---
```

### 4. SUPERVISOR Mode
Orchestrator delegates to worker skills. Best for complex multi-agent coordination.

```yaml
---
name: supervisor_report
execution_mode: supervisor
worker_skills:
  - name: ar_ops
    task: "Handle AR analysis"
  - name: invoice
    task: "Handle invoice queries"
---
# Supervisor prompt - decides which worker to call
```

## Key Classes

### SkillAgent (agent.py)
Main orchestrator that routes queries and executes skills.

```python
from iaf_agent_skills import SkillAgent

agent = SkillAgent(
    kernel=safe_kernel,      # SafeKernel for file/command access
    skills_path="./skills",  # Path to skills folder
    user_id="demo"           # User context for memory
)

result = await agent.run("Show me my invoices")
```

Key methods:
- `run(query)` - Routes and executes query, returns response
- `_run_react()` - LangGraph reasoning loop
- `_run_workflow()` - Sequential step execution
- `_run_parallel()` - Concurrent DAG execution
- `_run_supervisor()` - Delegated worker execution
- `_create_approval_tool(skill)` - Creates `request_human_approval` tool when skill has `approval_rules`

### SkillRouter (router.py)
Hybrid routing with keyword shortcuts + LLM fallback.

```python
from iaf_agent_skills import SkillRouter

router = SkillRouter("./skills")
skill_name = router.match("show my dilo", current_skill="general")
```

Three-phase routing:
1. **Keyword match** (fast, no LLM): `_index.yaml` keywords field
2. **Sticky behavior** (≤5 words): Short replies stay with current skill
3. **LLM classification** (>5 words): Uses skill descriptions

### SkillLoader (loader.py)
Parses SKILL.md files with YAML frontmatter.

```python
from iaf_agent_skills import SkillLoader

loader = SkillLoader("./skills")
skill = loader.load("ar_ops")

print(skill.name)           # "ar_ops"
print(skill.execution_mode) # "react"
print(skill.prompt)         # The markdown body
print(skill.steps)          # [] or list of step dicts
print(skill.worker_skills)  # [] or list of worker dicts
```

### Execution Engines (execution.py)

```python
from iaf_agent_skills.execution import WorkflowEngine, ParallelEngine, SupervisorEngine

# Workflow - sequential with conditions
engine = WorkflowEngine(kernel, steps, user_input)
result = await engine.execute()

# Parallel - concurrent with dependencies
engine = ParallelEngine(kernel, steps, user_input, agent_factory=create_agent_fn)
result = await engine.execute()

# Supervisor - delegates to workers
engine = SupervisorEngine(kernel, workers, llm, query)
result = await engine.execute()
```

### Memory System (memory.py)
Persistent context and learning with Context Graph architecture.

```python
from iaf_agent_skills.memory import AgentMemory

memory = AgentMemory(
    kernel=kernel,
    user_id="demo",
    session_id="session_123",
    llm=main_llm,        # For fact extraction
    light_llm=mini_llm   # For cheap classification (gpt-4o-mini)
)

# Context assembly before LLM call
context = memory.assemble_context(
    query="show pending invoices",
    skill="ar_ops",
    include_facts=True,
    include_history=True,
    include_learnings=True,
    include_context_graph=True
)

# Episode logging after response
memory.log_episode(user_input, response, skill, tool_calls, decision_context)

# Implicit feedback analysis
feedback = memory.analyze_implicit_feedback(prev_query, prev_response, current_query)
```

### Memory Storage Structure

```
memory/
├── context_graph/           # Context Graph (entities + decisions + knowledge)
│   ├── grounding/           # Skill capability docs
│   ├── entities/            # Business entities (customers, invoices)
│   │   ├── users/           # User profiles  
│   │   └── objects/         # Business objects
│   ├── decisions/           # Immutable decision records
│   ├── patterns/            # Learned patterns
│   ├── knowledge.jsonl      # Knowledge store (JSONL, append-only) (NEW)
│   └── index.json           # Semantic search index
├── history/                 # Episodic memory (by date)
│   └── YYYY-MM-DD/
│       └── session_id.jsonl
├── learnings/               # Procedural memory
│   ├── general/
│   │   └── tool_execution.jsonl
│   └── {skill_name}/
│       └── implicit_feedback.jsonl
└── master_index.json        # Brain-like topic index
```

---

## Knowledge Manager (NEW)

Full CRUD system for persistent agent knowledge. Knowledge items are stored in `knowledge.jsonl` using an append-only JSONL format with last-write-wins deduplication by `knowledge_id`.

### Knowledge Constants

```python
KNOWLEDGE_TYPES = ["fact", "preference", "procedure", "pattern", "correction"]
KNOWLEDGE_STATUSES = ["confirmed", "pending_review", "archived"]
KNOWLEDGE_SOURCES = ["explicit", "batch_extract", "implicit"]
```

### Knowledge Record Schema

```json
{
  "knowledge_id": "kn_a1b2c3d4",
  "knowledge_type": "fact",
  "summary": "US invoices require 3-way match before payment",
  "applies_when": "When processing AP payments for US entities",
  "scope": "global",
  "confidence": 0.85,
  "tags": ["ap", "invoices", "us"],
  "source": "batch_extract",
  "status": "pending_review",
  "created_at": "2026-02-14T02:00:00Z",
  "updated_at": "2026-02-14T02:00:00Z",
  "provenance": {
    "extracted_from": "session_abc123",
    "episode_date": "2026-02-13"
  },
  "usage_count": 0
}
```

### Knowledge CRUD Methods

#### `write_knowledge(knowledge_type, summary, applies_when, scope, confidence, tags, source, status)`
Creates a new knowledge record. Generates `kn_` prefixed ID. Defaults to `pending_review` status for `batch_extract` source, `confirmed` for `explicit`.

#### `confirm_knowledge(knowledge_id) -> bool`
Sets status to `confirmed`. Returns True on success.

#### `reject_knowledge(knowledge_id) -> bool`
Sets status to `archived`. Returns True on success.

#### `edit_knowledge(knowledge_id, summary, knowledge_type, applies_when, tags) -> bool`
**In-place update** — modifies record fields while preserving current status. A pending item stays pending, a confirmed item stays confirmed. Uses the same JSONL append-with-same-ID pattern (last-write-wins).

#### `query_knowledge(status, knowledge_type, source, include_archived, limit, offset) -> Dict`
Returns a Dict with `items` (list), `total` (count before pagination), and filter metadata.

```python
result = memory.query_knowledge(status="pending_review", limit=10, offset=0)
# Returns: {"items": [...], "total": 15, "status": "pending_review", ...}
```

**Important:** Returns a `Dict`, not a `List`. Callers must access `result["items"]`.

#### `get_knowledge_stats() -> Dict`
Returns counts by status, type, and source:
```json
{
  "total": 42,
  "by_status": {"confirmed": 30, "pending_review": 10, "archived": 2},
  "by_type": {"fact": 20, "preference": 8, ...},
  "by_source": {"explicit": 15, "batch_extract": 25, "implicit": 2}
}
```

### Batch Knowledge Extraction (NEW)

#### `batch_extract_knowledge(hours_back=24, max_tokens_budget=150000) -> Dict`

Mines recent episodic history for new knowledge using the light LLM (`gpt-4o-mini`).

**Flow:**
1. `_collect_recent_episodes(cutoff)` — reads JSONL history files since `cutoff`
2. `_get_existing_knowledge_summaries()` — loads summaries of confirmed + pending records for dedup
3. Chunks episodes into batches within token budget
4. For each chunk, calls `_extract_knowledge_from_chunk(episodes, existing_summaries)` — single LLM call with JSON array response
5. Writes extracted items as `status: pending_review`, `source: batch_extract`
6. Dedup: LLM is given existing summaries and instructed to skip duplicates

**Returns:**
```json
{
  "extracted": 11,
  "skipped_duplicates": 3,
  "errors": 0,
  "total_episodes": 44
}
```

**Cron Integration:** Server cron executor routes `job.task == "batch_extract_knowledge"` to this method.

---

## HITL Approval System (NEW)

### Approval Rules Engine (approval_rules.py)

Pure-function module for evaluating skill-level approval policies. All functions are stateless and side-effect free.

#### Key Functions

```python
from iaf_agent_skills.approval_rules import (
    evaluate_rules,           # Check if action needs approval
    compile_rules_to_prompt,  # Convert rules to natural-language LLM instructions
    escalate_urgency,         # Escalate urgency level (medium → high → critical)
    get_sla_minutes,          # Get SLA timeout by urgency level
)
```

#### Rule Format (in SKILL.md frontmatter)
```yaml
---
name: ar_ops
approval_rules:
  - condition: "amount > 10000"
    reason: "High-value transaction requires manager approval"
    urgency: high
  - condition: "action == 'delete'"
    reason: "Destructive operations require confirmation"
    urgency: critical
---
```

#### Urgency Levels & SLA
| Level | SLA (minutes) | Use Case |
|-------|---------------|----------|
| `low` | 480 (8h) | FYI / audit trail |
| `medium` | 120 (2h) | Standard review |
| `high` | 30 | Time-sensitive decision |
| `critical` | 10 | Blocking / destructive |

### Approval Store (approval_store.py)

Redis-backed persistence for HITL approval lifecycle (checkpoint & resume pattern).

```python
from iaf_agent_skills.approval_store import (
    ApprovalStore, ApprovalRequest, ApprovalStatus,
    get_approval_store, init_approval_store,
)
```

#### Lifecycle
1. `create_approval(request, agent_state)` — Persist approval + checkpoint agent state
2. `get_pending(tenant_id)` — List pending approvals (ZSET sorted by created_at)
3. `resolve(approval_id, decision, decided_by, note)` — Mark resolved, move to history
4. `get_agent_state(approval_id)` — Retrieve checkpointed state for resume

### Agent Integration (agent.py)

SkillAgent exposes `request_human_approval` as a LangChain tool:

```python
# Created by _create_approval_tool() when skill has approval_rules
@tool
def request_human_approval(reason: str, context: dict, urgency: str = "medium") -> str:
    """Request human approval for an action. Agent pauses until resolved."""
    ...
```

When called:
1. `agent.approval_pending` is set with approval details
2. Agent returns a message indicating it's waiting for approval
3. Server persists to Redis via `checkpoint_hitl_if_needed()`
4. Human resolves via Dashboard or API
5. Server restores agent state and injects decision to continue execution

```python
# Agent state during HITL pause
agent.approval_pending = {
    "approval_id": "apr_abc123",
    "reason": "Amount $50,000 exceeds threshold",
    "urgency": "high",
    "context": {"amount": 50000, "action": "approve_payment"},
    "options": ["Approve", "Reject"],
    "sla_minutes": 30,
    "skill": "ar_ops",
    "timestamp": "2026-02-14T10:00:00Z"
}
```

### Implicit Feedback Types

| Type | Signal | Learning |
|------|--------|----------|
| `successful_query` | User moved on/thanked | Positive pattern |
| `skill_pattern` | Good tool selection | Route similar queries |
| `correction` | "No, it's actually X" | Factual correction |
| `rephrase` | Same question differently | Agent unclear |
| `skill_error` | Wrong skill used | Routing issue |
| `more_detail` | "Tell me more" | Partial success |

## Queue Manager (queue_manager.py) - NEW

OpenClaw-style lane-based concurrency control with swappable backends.

### Usage

```python
from iaf_agent_skills.queue_manager import (
    create_queue_manager, QueueConfig, QueueBackend, QueueNames
)

# Memory backend (default)
queue = create_queue_manager()

# Redis backend (enterprise scaling)
queue = create_queue_manager(QueueConfig(
    backend=QueueBackend.REDIS,
    redis_url="redis://localhost:6379"
))

# Enqueue with concurrency control
result = await queue.enqueue(
    QueueNames.session("company", "user123"),
    lambda: agent.run(message),
    max_concurrent=1  # Serial per lane
)
```

### Key Classes

- `BaseQueueManager` - Abstract interface for all backends
- `MemoryQueueManager` - In-memory queues (development/single-server)
- `RedisQueueManager` - Redis-backed queues (enterprise/multi-server)
- `QueueNames` - Standard naming patterns for lanes

### Queue Naming Patterns

```python
QueueNames.session(tenant_id, user_id)  # "session:company:user123"
QueueNames.agent(tenant_id, agent_id)   # "agent:company:studio_agent"
QueueNames.cron(tenant_id)              # "cron:company"
QueueNames.tools(tenant_id, session_id) # "tools:company:sess123"
QueueNames.memory(tenant_id, agent_id)  # "memory:company:studio_agent"
```

### API Methods

```python
# Enqueue and execute task
result = await queue.enqueue(lane_name, task, max_concurrent=1, timeout=30)

# Inspect queue
pending = await queue.get_pending_tasks(lane_name)
status = await queue.get_queue_status(lane_name)
all_status = queue.get_all_queues_status()

# Cancel pending tasks
cancelled = await queue.cancel_pending(lane_name)
```

## SkillAgent.run() Parameters

```python
def run(
    self, 
    query: str, 
    skill_name: str = None,           # Force specific skill
    return_tool_calls: bool = False,  # Return (response, tool_calls) tuple
    status_callback = None,           # Real-time progress updates
    skip_memory: bool = False,        # Skip memory ops (faster batch)
    render_ui: bool = False,          # Include UI generation instructions
    light_mode: bool = False          # Fast mode - skip memory context + async learning
) -> str:
```

### Light Mode (NEW)

When `light_mode=True`, the agent runs in fast mode:
- **Skips memory context assembly** - No LLM calls for keyword expansion, Context Graph search
- **Skips async learning** - No episode logging, entity updates, implicit feedback
- **Saves 2-4 LLM calls** per request
- **Reduces latency** by 0.5-2 seconds

```python
# Fast mode - skip memory + learning
response = agent.run(content, skill_name=skill, light_mode=True)
```

### render_ui Parameter (NEW)

When `render_ui=True`, UI generation instructions are appended to the system prompt.
The agent can output Generative UI components:

```python
# Browser request with UI components
response = agent.run(content, render_ui=True)
# Response may contain: ```ui:data_table {...}```
```

### skip_memory Parameter

When `skip_memory=True`, the agent skips all memory operations after LLM response:
- No episodic logging
- No context graph updates
- No implicit feedback analysis
- Reduces latency by ~1-2 seconds per call

Use for batch processing where individual memory logging isn't needed:

```python
# Batch mode - skip memory for speed
response = agent.run(content, skill_name=skill, skip_memory=True)
```

---

## Generative UI Components (NEW)

When `render_ui=True`, the agent can output structured UI components:

### Available Components

| Component | Use Case | Example |
|-----------|----------|--------|
| `ui:data_table` | Lists, records, invoices | Tables with action buttons |
| `ui:stat_cards` | KPIs, summaries (max 4) | Cards with icons, trends |
| `ui:chart` | Trends, comparisons | Bar/line/pie charts |
| `ui:action_buttons` | Follow-up actions | Clickable button groups |
| `ui:progress` | Status bars | Percentage completion |
| `ui:alert` | Warnings, success, info | Highlighted messages |
| `ui:form` | User input collection | Input fields with submit |
| `ui:accordion` | Collapsible sections | FAQ-style content |
| `ui:list` | Simple lists | Bullet/numbered items |

### Example Output

```markdown
Here are the pending invoices:

```ui:data_table
{
  "title": "Pending Invoices",
  "columns": ["Invoice #", "Customer", "Amount", "Due Date"],
  "rows": [
    ["INV-001", "Acme Corp", "$5,000", "2026-02-15"],
    ["INV-002", "Beta Inc", "$3,200", "2026-02-20"]
  ],
  "actions": ["View", "Approve", "Reject"]
}
```

```ui:action_buttons
{
  "buttons": [
    {"label": "Export CSV", "icon": "📥", "style": "primary"},
    {"label": "Send Reminders", "icon": "📧", "style": "secondary"}
  ]
}
```
```

---

## Confirmation Flow (Ask-First Mode)

When `agent.auto_run=False`, dangerous operations require confirmation:

```python
# Agent detects dangerous action
response = "I'll delete 47 records from invoices.\n[AWAITING_CONFIRMATION: DELETE 47 records]"

# Pending action saved in agent.pending_action
agent.pending_action = {
    "skill": "ar_ops",
    "original_query": "delete draft invoices",
    "action_summary": "DELETE 47 records",
    "timestamp": datetime.now()
}

# User says "yes" or "proceed"
# Router detects confirmation, injects context, action executes
```

### Confirmation Protocol Constants

```python
CONFIRMATION_TAG = "[AWAITING_CONFIRMATION:"
PENDING_ACTION_TIMEOUT_MINUTES = 10
```

## Skill File Format

### Basic REACT Skill
```markdown
---
name: my_skill
version: "1.0"
description: "What this skill does"
keywords:
  - keyword1
  - keyword2
---

# System Prompt

Instructions for the LLM when this skill is active.
```

### Workflow/Parallel Skill
```markdown
---
name: my_workflow
execution_mode: workflow  # or parallel
steps:
  - name: step_name
    action: shell          # shell | skill | condition
    command: "echo hello"  # for shell
    skill: general         # for skill action
    task: "Do something"   # for skill action
    depends_on: []         # for parallel mode
---
```

### Supervisor Skill
```markdown
---
name: my_supervisor
execution_mode: supervisor
worker_skills:
  - name: ar_ops
  - name: invoice
---

# Supervisor prompt
Decide which worker to delegate to based on the query.
```

### SQL Write Mode (`sql_mode`)

By default, `run_sql_query` only allows **SELECT** queries for safety. To enable INSERT/UPDATE/DELETE for a skill, add `sql_mode: read_write` to the YAML frontmatter.

#### Values

| Value | Behavior |
|---|---|
| `read_only` (default) | Only SELECT queries allowed. INSERT/UPDATE/DELETE return an error. |
| `read_write` | SELECT + INSERT + UPDATE + DELETE allowed. DDL (DROP, ALTER, CREATE, TRUNCATE) always blocked. |

#### Example: Skill with SQL Write Access

```yaml
---
name: correction_agent
version: "1.1"
description: "Books AP corrections with approval"
execution_mode: react
sql_mode: read_write          # ← Enables INSERT/UPDATE/DELETE
tools:
  - shell
  - run_sql_query             # ← Tool must also be listed
  - request_human_approval
approval_rules:
  thresholds:
    - field: "amount"
      operator: ">="
      value: 10000
      urgency: high
---
```

#### How It Works

1. **Loader** (`loader.py`): Parses `sql_mode` from SKILL.md frontmatter into `Skill.sql_mode` (default: `"read_only"`)
2. **Agent** (`agent.py`): When building tools for a skill, reads `skill.sql_mode` and sets `self._sql_write_allowed = True` if `read_write`
3. **SQL Tool** (`agent.py` → `_create_sql_tool()`): Checks `self._sql_write_allowed` before executing non-SELECT queries
4. **Safety**: DDL (`DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `VACUUM`) is **always blocked** regardless of `sql_mode`
5. **Writes auto-commit**: INSERT/UPDATE/DELETE execute with `conn.commit()` and return `"Success: INSERT affected N row(s)."`

#### Log Output

```
# read_write mode
✅ Added run_sql_query (read_write ✏️) for skill 'correction_agent'
✏️ SQL write (INSERT): allowed by sql_mode
✅ SQL INSERT: 1 row(s) affected

# read_only mode (default)
✅ Added run_sql_query (read_only 🔒) for skill 'my_skill'
❌ Write blocked (sql_mode: read_only)
```

#### When to Use

- **`read_only`** (default): Reporting skills, analytics, dashboards — any skill that only reads data
- **`read_write`**: Correction booking, transaction processing, data updates — skills that modify DB records. Pair with `approval_rules` for HITL oversight on sensitive writes.

### Workflow Shell Auto-Execute

Shell steps in **workflow mode** (`execution_mode: workflow`) auto-execute without confirmation prompts. The workflow definition in SKILL.md acts as the authorization — these are deterministic, pre-defined commands (not LLM-generated).

This means `auto_run=False` (ask-first mode in chat) does NOT affect workflow shell steps. Only react-mode shell commands respect the `auto_run` toggle.

## Skills Index (_index.yaml)

```yaml
version: "1.0"
default_skill: general

skills:
  general:
    description: "General-purpose assistant"
    
  ar_ops:
    description: "Accounts Receivable operations"
    keywords:
      - ar report
      - aging analysis
      - receivables
      
  parallel_report:
    description: "Runs AR and Invoice analysis in parallel"
    keywords:
      - parallel report
      - combined report
```

## Build and Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Test routing
python -c "from iaf_agent_skills import SkillRouter; r = SkillRouter('./skills'); print(r.match('show my dilo'))"

# Test skill loading
python -c "from iaf_agent_skills import SkillLoader; l = SkillLoader('./skills'); print(l.load('ar_ops').execution_mode)"
```

## Code Style Guidelines

- **Python 3.10+** required
- **Type hints** on all function signatures
- **async/await** for all agent execution methods
- **Docstrings** for all public methods (Google style)
- Use `Path` from pathlib for file operations
- Max line length: 100 characters

## Adding a New Skill

1. Create folder: `skills/new_skill/`
2. Create `SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: new_skill
   version: "1.0"
   description: "What this skill does"
   execution_mode: react  # or workflow, parallel, supervisor
   keywords:
     - trigger word
   ---
   # Prompt content
   ```
3. Add entry to `skills/_index.yaml`:
   ```yaml
   new_skill:
     description: "Keywords: trigger word. What this skill does."
     keywords:
       - trigger word
   ```

---

## Cron Scheduler Module

Enterprise-ready scheduler for running skills on a schedule with Redis backend.

### Architecture

```
scheduler/
├── models.py          # Job, JobRun, RunStatus dataclasses
├── scheduler.py       # CronScheduler - main orchestrator
├── store.py           # JobStore abstract base class
├── redis_store.py     # Async Redis backend (RedisJobStore)
├── sync_redis_store.py # Sync Redis backend (SyncRedisJobStore)
├── redis_scheduler.py # Async scheduler variant
└── worker.py          # CLI worker for distributed execution
```

### Key Classes

| Class | Purpose |
|-------|---------|
| `Job` | Cron job definition (name, skill, cron expr, enabled) |
| `JobRun` | Execution record (status, output, duration) |
| `CronScheduler` | Orchestrator - manages jobs, triggers runs |
| `SyncRedisJobStore` | Redis-backed storage (for server.py) |
| `RedisJobStore` | Async Redis storage |

### Usage

```python
from iaf_agent_skills.scheduler import CronScheduler, Job, SyncRedisJobStore

# Create scheduler with Redis backend
store = SyncRedisJobStore(redis_url="redis://localhost:6379")
scheduler = CronScheduler(store=store)

# Create a job
job = scheduler.create_job(Job(
    name="Daily Report",
    skill_name="general",
    task="Generate daily summary",
    cron="0 9 * * *",  # Every day at 9am
    enabled=True
))

# Start scheduler (runs in background thread)
scheduler.start()

# Trigger manual run
run = scheduler.run_now(job.id)
```

### Redis Keys

| Key | Type | Description |
|-----|------|-------------|
| `iaf:scheduler:job:{id}` | Hash | Job configuration |
| `iaf:scheduler:jobs:due` | ZSet | Jobs sorted by next run time |
| `iaf:scheduler:run:{id}` | Hash | Run execution record |
| `iaf:scheduler:runs:job:{id}` | List | Run IDs per job |

### Distributed Workers

```bash
# Run standalone worker (competes for jobs via Redis locks)
python -m iaf_agent_skills.scheduler.worker \
  --redis-url redis://localhost:6379 \
  --poll-interval 5
```

### Cron Expressions

Standard 5-field format: `minute hour day month weekday`

- `0 9 * * *` - Daily at 9am
- `*/15 * * * *` - Every 15 minutes
- `0 8-17 * * 1-5` - Hourly 8am-5pm weekdays

---

## MCP Tool Bridge (tools/mcp_bridge.py)

Unified adapter that connects agents to MCP (Model Context Protocol) servers. Discovers tools from MCP sources and converts them to LangChain `StructuredTool` instances for ReAct agents.

### Connection Types

| Type | Transport | Config Fields | Description |
|------|-----------|---------------|-------------|
| `direct` | `stdio` | `command`, `args` | Local MCP server via stdin/stdout |
| `direct` | `http` | `url` | Remote MCP server via streamable HTTP |
| `registry` | REST | `url`, `auth`, `server_filter` | Enterprise MCP Registry (REST discovery + proxied execution) |

### Usage

```python
from iaf_agent_skills.tools import MCPToolBridge

# Create bridge with connections
bridge = MCPToolBridge(connections=[
    {
        "name": "calc",
        "type": "direct",
        "transport": "stdio",
        "command": "python3",
        "args": ["calc_server.py"]
    },
    {
        "name": "corp-registry",
        "type": "registry",
        "url": "http://registry:7001",
        "auth": {"type": "bearer", "token": "${MCP_TOKEN}"},
        "server_filter": ["approved-server-1"]
    },
])

# Discover and wrap all tools as LangChain StructuredTool
tools = await bridge.get_tools()  # List[StructuredTool]
```

### Configuration in SKILL.md

```yaml
---
name: my_skill
mcp_connections:
  - name: calculator
    type: direct
    transport: http
    url: "http://localhost:9876/mcp"
  - name: enterprise
    type: registry
    url: "${MCP_REGISTRY_URL}"
    auth:
      type: bearer
      token: "${MCP_TOKEN}"
---
```

### Configuration in config.yaml (Agent-Level)

```yaml
mcp:
  connections:
    - name: shared-tools
      type: direct
      transport: stdio
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
```

### Merge Behavior

Agent-level and skill-level MCP connections are merged at runtime. Skill-level takes precedence for duplicate names. Both support `${VAR}` environment variable resolution.

### Key Classes

- **`MCPToolBridge`** — Facade that merges configs, deduplicates, creates adapters
- **`DirectAdapter`** — Uses `langchain-mcp-adapters` `MultiServerMCPClient` for stdio/HTTP
- **`RegistryAdapter`** — REST calls to registry (`GET /approved-servers`, `GET /tools`, `POST /query`)

### Validation

```python
from iaf_agent_skills.tools.mcp_bridge import validate_connection

errors = validate_connection({
    "name": "calc", "type": "direct", "transport": "stdio",
    "command": "python3"
})
# errors = [] (valid)
```

---

## Skill Tool Loader (tools/skill_tool_loader.py)

Auto-discovers and loads bundled Python tools from skill `tools/` subfolders. Scripts with a `TOOL_SPEC` dict at module level are wrapped as LangChain tools via AST parsing (never executed at discovery time).

### Script Contract

```python
# skills/invoice_processing_ap/tools/calculate_late_fee.py

TOOL_SPEC = {
    "name": "calculate_late_fee",
    "description": "Calculate late payment fee for an invoice",
    "parameters": {
        "invoice_id": {"type": "string", "description": "Invoice ID"},
        "days_late": {"type": "integer", "description": "Days past due"}
    },
    "timeout": 30
}

import json, sys
data = json.loads(sys.stdin.read())
result = {"fee": float(data["days_late"]) * 0.015 * 1000}
print(json.dumps(result))
```

### Folder Layout

```
skills/
  invoice_processing_ap/
    SKILL.md
    tools/
      calculate_late_fee.py   ← has TOOL_SPEC + stdin/stdout contract
      validate_po.py          ← another bundled tool
```

### Usage

```python
from iaf_agent_skills.tools.skill_tool_loader import discover_skill_tools

tools = discover_skill_tools(Path("skills/invoice_processing_ap"))
# Returns: List[StructuredTool] — each wraps a subprocess call to the script
```

### How It Works

1. `discover_skill_tools(skill_path)` scans `skill_path/tools/*.py`
2. Each file is parsed via `ast.literal_eval` (never executed) for `TOOL_SPEC`
3. Valid specs are wrapped as `StructuredTool` with Pydantic input models
4. At invocation time, the script receives JSON on stdin, returns JSON on stdout
5. Output is capped at 10KB; timeout defaults to 30s

---

---

## Entity Registry (entity_registry.py) (NEW)

Manages the `entity_registry` table inside `agent_knowledge.db`. Provides APQC process taxonomy tree traversal and skill→node lookups.

### Key Class

```python
from iaf_agent_skills.entity_registry import EntityRegistry

registry = EntityRegistry(db_path=Path("workspaces/default/context_graph/agent_knowledge.db"))
```

### Methods

| Method | Description |
|--------|-------------|
| `get_tree()` | Returns full hierarchy as nested dict (for UI visualization) |
| `get_node(node_id)` | Get single node with parent_id, skill_name, aliases |
| `get_children(parent_id)` | List child nodes of a parent |
| `get_breadcrumb(node_id)` | Array of ancestors from root to node |
| `find_by_skill(skill_name)` | Find node linked to a skill |
| `search(query)` | FTS search across display_name and aliases |
| `upsert(node)` | Insert or update a node |

### Tree Structure

```python
tree = registry.get_tree()
# Returns:
{
    "node_id": "apqc:l1:fa",
    "display_name": "Finance & Accounting",
    "node_type": "tower",
    "skill_name": None,
    "children": [
        {
            "node_id": "apqc:l2:o2c",
            "display_name": "Order to Cash",
            "children": [...]
        },
        ...
    ]
}
```

### Table Schema

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

---

## Conversation Manager (conversation_manager.py) (NEW)

Manages the `conversations` table for session history tracking. Lives in `knowledge_index.db` (or sibling DB).

### Key Class

```python
from iaf_agent_skills.conversation_manager import ConversationManager

mgr = ConversationManager(db_path=memory_root / "knowledge_index.db")
```

### Methods

| Method | Description |
|--------|-------------|
| `create_session(user_id, agent_id)` | Create new session, returns session_id |
| `list_sessions(user_id, limit, offset)` | List sessions for a user |
| `get_session(session_id)` | Get session details |
| `append_turn(session_id, role, content)` | Add turn to session |
| `get_turns(session_id, limit)` | Get turns for a session |
| `summarize_session(session_id)` | Generate session summary |

---

## Databases (Important) (NEW)

The system uses **two separate SQLite databases**:

| Database | Location (default) | Created By | Tables |
|----------|-------------------|------------|--------|
| `agent_knowledge.db` | `workspaces/default/context_graph/` | `seed_entity_registry.py` | `entity_registry` |
| `knowledge_index.db` | `enterprise_root/.../memory/` | KnowledgeIndexer (runtime) | `knowledge_vectors`, `episode_vectors`, `entity_xref`, `fts_knowledge`, `conversations` |

### agent_knowledge.db

Stores structural/taxonomy data:
- **`entity_registry`** — APQC process taxonomy (tower→process→activity→skill hierarchy)

Seeded by:
```bash
python3 IAF-Agent-Skills/scripts/seed_entity_registry.py
# Default: workspaces/default/context_graph/agent_knowledge.db
```

### knowledge_index.db

Stores runtime operational data:
- **`knowledge_vectors`** — Embedded knowledge records
- **`episode_vectors`** — Embedded episode summaries
- **`entity_xref`** — Entity→record cross-reference
- **`fts_knowledge`** — FTS5 keyword search fallback
- **`conversations`** — Session tracking

Created automatically by KnowledgeIndexer on first use.

---

## Seed Scripts (NEW)

Scripts to initialize databases and demo data.

### seed_entity_registry.py

Seeds the `entity_registry` table with APQC F&A process taxonomy.

```bash
# Default path
python3 IAF-Agent-Skills/scripts/seed_entity_registry.py

# Custom path
python3 IAF-Agent-Skills/scripts/seed_entity_registry.py --db /path/to/agent_knowledge.db
```

**Default path**: `workspaces/default/context_graph/agent_knowledge.db`

Creates directories if needed. Idempotent (uses INSERT OR REPLACE).

### Other Seed Scripts

| Script | Purpose |
|--------|---------|
| `seed_skill_aliases_from_l5.py` | Seeds skill aliases from L5 data |
| `clean_entity_registry.py` | Clean up noisy entities |
| `clean_noisy_entities.py` | Remove low-quality entities |

---

## Knowledge Indexer (knowledge_indexer.py)

SQLite-backed semantic index for knowledge records and episode files. Supports embedding-based cosine similarity search with FTS5 keyword fallback.

### Tables

| Table | Purpose |
|-------|---------|
| `knowledge_vectors` | Knowledge record embeddings with metadata |
| `episode_vectors` | Episode file embeddings with file paths |
| `entity_xref` | Entity → record_id cross-reference |
| `fts_knowledge` | FTS5 virtual table for keyword fallback |

### Usage

```python
from iaf_agent_skills.knowledge_indexer import KnowledgeIndexer

indexer = KnowledgeIndexer(
    db_path=Path("memory/knowledge_index.db"),
    get_embedding_fn=my_embedding_function,  # or None for FTS5-only
)

# Index a knowledge record
indexer.upsert_knowledge(record_dict)

# Semantic search (embedding cosine similarity)
results = indexer.search_similar("payment processing rules", top_k=5)

# Entity cross-reference lookup
results = indexer.entity_lookup("vendor_master")

# Rebuild index from scratch
indexer.reindex_all(Path("memory/context_graph/knowledge.jsonl"))
```

### Design

- **Injectable embedding function** — accepts any `Callable[[str], List[float]]`
- **Graceful degradation** — embeddings → FTS5 → empty results
- **Thread-safe** — SQLite WAL mode, `check_same_thread=False`
- **Idempotent** — upsert semantics, safe to call repeatedly
- **Minimum cosine score** — 0.72 threshold filters noise

---

## Session Store (session_store.py)

Redis-backed session state for horizontal scaling. Enables `SkillAgent` state to persist across server restarts and load-balanced requests.

### Key Classes

- **`RedisSessionStore`** — Async Redis session persistence
- **`AgentStateSnapshot`** — Serializable agent state (history, pending_action, summary)

### Usage

```python
from iaf_agent_skills.session_store import RedisSessionStore, AgentStateSnapshot

store = RedisSessionStore(redis_url="redis://localhost:6379")

# Save state after agent.run()
snapshot = agent.export_state()
await store.save_session(tenant_id, user_id, snapshot)

# Restore state on next request
snapshot = await store.load_session(tenant_id, user_id)
if snapshot:
    agent.import_state(snapshot)
```

### Redis Key Structure

| Key | Type | Description |
|-----|------|-------------|
| `iaf:session:{tenant}:{user}:state` | Hash | Main agent state |
| `iaf:session:{tenant}:{user}:history` | List | Conversation history (JSON strings) |
| `iaf:session:index:{tenant}` | ZSet | Users sorted by last_active timestamp |

### Features

- **Feature-flagged** — `USE_REDIS_SESSIONS` env var for gradual rollout
- **Graceful degradation** — Falls back to in-memory if Redis unavailable
- **TTL** — 24-hour default session TTL
- **Memory cache** — 60-second in-memory cache to reduce Redis reads

---

## Common Issues

### "Skill X not found"
Check that `skills/_index.yaml` contains the skill entry.

### Routing goes to wrong skill
1. Check `keywords` field in `_index.yaml`
2. Add more specific keywords
3. Enable debug: `SKILL_DEBUG=1`

### Workflow step fails
1. Check step `action` is valid: `shell`, `skill`, `condition`
2. For `skill` action, ensure target skill exists
3. Check template variables: `{step_name.output}`

### Parallel execution hangs
1. Check for circular dependencies in `depends_on`
2. Ensure all dependency step names are correct
3. Check if skill invocation is failing (API key, etc.)

### Supervisor doesn't delegate
1. Ensure `worker_skills` is populated
2. Check supervisor prompt has clear delegation instructions
3. Verify worker skills exist and are loadable

## Dependencies

External packages:
- `langchain` - LLM abstractions
- `langgraph` - Agent graph execution
- `pyyaml` - YAML parsing
- `openai` / `azure-openai` - LLM providers
- `redis` - Redis client (required for HITL approvals, sessions, cron, queues)
- `fastmcp` - MCP server/client framework (for MCP tool bridge)
- `langchain-mcp-adapters` - MCP ↔ LangChain tool adapters
- `httpx` - Async HTTP client (MCP registry adapter)

Internal dependencies:
- `agent_os.SafeKernel` - Sandboxed filesystem access
- `smart_code_executor` - Code execution engine (for code_executor tool)

## Session Compaction (OpenClaw-style)

Automatically manages conversation history size:

```python
# Settings in SkillAgent
SESSION_COMPACT_THRESHOLD = 30  # Trigger compaction when > 30 turns
SESSION_KEEP_RECENT = 8         # Keep last 8 turns uncompacted
```

When history exceeds threshold, older turns are summarized via LLM call.
