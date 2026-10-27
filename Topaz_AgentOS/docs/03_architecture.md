# IAF AgentPro — Architecture

## System Overview

IAF AgentPro is a four-layer system where each layer has a single responsibility:

```
┌─────────────────────────────────────────────────────────────┐
│  IAF Agent Studio                                            │
│  Web UI + REST API + WebSocket streaming                     │
│  FastAPI, Alpine.js, TailwindCSS — port 8080                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ imports
┌──────────────────────────▼──────────────────────────────────┐
│  IAF Agent Skills                                            │
│  Execution engine, skill routing, memory, self-evolution     │
│  LangGraph ReAct, LangChain, SQLite                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ imports
┌──────────────────────────▼──────────────────────────────────┐
│  AgentOS (agent_os)                                          │
│  Sandboxed shell kernel, RBAC, path safety, audit            │
│  SafeKernel, SafePath, VectorStore, RateLimiter              │
└──────────────────────────┬──────────────────────────────────┘
                           │ reads/writes
┌──────────────────────────▼──────────────────────────────────┐
│  Enterprise Root (enterprise_root)                           │
│  Filesystem data store: memory, history, databases           │
│  JSONL, SQLite, Markdown, YAML                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Request Lifecycle

A typical user chat request flows through the system as follows:

```
1. User submits query via WebSocket /ws/chat or REST /api/chat
                    │
2. routers/chat.py receives the message
   - Load session from Redis (or in-memory)
   - Verify user auth (if AUTH_ENABLED)
   - For AskTwin, use a page-scoped session and compact source_page/page_context into the prompt; current page context overrides prior AskTwin topics
                    │
3. SkillAgent.run(query, skill_name=None)
                    │
4. EntityRegistryStore.collect_context(query)
   - WHO signal: entity resolution (FTS5 → embedding)
   - WHAT signal: process taxonomy match
   - Returns skill_hint, process_hint, signals_agree
                    │
5. SkillRouter.match(query, entity_context)
   - If signals agree → route to single skill
   - If signals conflict → execution_mode="planned"
   - If forced → use skill_name parameter
                    │
6. Skill execution (mode determines path):
   ┌─────────────────────────────────────────────┐
   │ react mode:    LangGraph/native ReAct loop   │
   │                LLM → tool calls → observe    │
   │ workflow mode: WorkflowEngine deterministic  │
   │                child callbacks tagged by step │
   │ parallel mode: ParallelEngine asyncio.gather │
   │ supervisor:    SupervisorEngine threads      │
   │ orchestrator:  OrchestratorEngine (LLM picks │
   │                next skill each step)         │
   │ rlm mode:      RLM engine — governed code    │
   │                actions + propose-then-apply  │
   │ graph mode:    process_graph → execute_graph │
   │                (verifier + convergence loop) │
   │ planned:       PlannerEngine DAG (multi-dom) │
   └─────────────────────────────────────────────┘
                    │
7. Tool calls go through the KernelRuntime boundary
   - Local mode calls SafeKernel in-process
   - Remote mode sends signed internal calls to the kernel worker process
   - Path sandboxing (SafePath.resolve)
   - RBAC check (_check_user_access)
   - Command execution (_cmd_*)
   - Audit logging (_log_command)
                    │
8. Knowledge retrieval (query_memory tool)
   - Tier 1: entity_xref exact match
   - Tier 2: semantic (cosine similarity)
   - Tier 3: FTS5 keyword fallback
                    │
9. Response generation
   - Conversation turn saved to history JSONL
   - Learning signals extracted
   - Knowledge records written to context_graph JSONL
                    │
10. Response is returned:
    - WebSocket streams routing → status → tool_call → tool_result → response
    - REST returns the final response payload
    - Both paths checkpoint business HITL approvals into approval_store; workstream item callers only stamp approvals whose context matches the current workstream and item
    - Gateable blocking hooks can use `on_block: hitl` to create the same approval_pending checkpoint; `on_block: deny` keeps the block as a policy denial
    - Approved HITL resumes include explicit approval markers so PostTurn policy hooks can distinguish an approved replay from a fresh unapproved violation

Non-interactive entry points (cron executor, queue processor, HITL resume) follow the
same entitlement enforcement. Each creates a service `IdentityContext` exported as a
service principal (`service:cron`, `service:queue`, `service:hitl_resume`) and calls
`set_entitlement_context()` before `agent.run()`. Service principal grants live in
`policies.yaml` alongside user/group policies.

```

The RL/eval subsystem is intentionally sidecar-style. `rl_capture/` owns the
framework-neutral capture schema, exporters, auto-evaluator, Private Learning
Loop eval registry (`rl_capture/evals/`), weighted suite runner, and trusted
Python evaluator subprocess executor. AgentPro-specific wiring lives under
`rl_capture/adapters/agentpro/`, including tenant paths for `evals/`,
`golden_sets/`, and `eval_evaluators/`. Studio provides thin REST endpoints, the
Workbench Eval Builder UI, and manual promotion-gate recording; it does not train
models or auto-deploy artifacts from eval results. Exporters apply format-specific
materialization rules before the shared redaction/quality gate; for example, eval
JSONL skips metadata-only captures that do not contain replayable task, message,
or output text.

The Trace Value Router follows the same sidecar rule. Completed captures can
schedule advisory assessment in the background, but runtime chat correctness does
not depend on routing success; promotion remains a governed human action.
Trajectory list filtering joins this advisory read model at the Studio router
boundary, returning compact assessment/destination/decision metadata without
changing the authoritative capture schema or starting a runtime agent.

---

## IAF Agent Studio (Layer 4)

**Technology:** FastAPI, Alpine.js, TailwindCSS

**Entry point:** `IAF-Agent-Studio/server.py`

### Key Responsibilities

- Serve the web UI (single-file Alpine.js apps in `/static/*.html`) and
  compatibility routes for module-owned dashboards such as IRIS Finance
  Digital Twin and Process Intelligence.
- Expose REST API endpoints across 40+ routers (the Router Map below is a selected subset)
- Manage WebSocket connections for streaming
- Run background services (cron scheduler, queue processor, telemetry emitters)
- Initialize durable SQLite runtime stores for Command Center queue items,
  Workstream item executions, and Deterministic Automation runs under
  `enterprise_root/tenants/<tenant>/shared/databases/`; Workstream YAML stays
  the business state while `workstream_runtime.db` and
  `automation_runtime.db` store high-churn execution and step trace rows.
- Reconcile Workstream YAML schedules into Redis-backed cron jobs on startup so
  restored workstreams with `cron_schedule`/`cron_user_id` remain visible and
  runnable after Redis resets or branch restores.
- Reconcile standalone cron YAML from
  `enterprise_root/tenants/<tenant>/scheduler/jobs/*.yaml` into Redis-backed
  cron jobs on startup; Redis is active runtime, not the portable definition.
- Manage Deterministic Automation YAML under
  `enterprise_root/tenants/<tenant>/automations/` for no-LLM shell/python
  pipelines that can be run from REST, cron, or Workstreams.

### Router Map

| Router | Prefix | Purpose |
|---|---|---|
| `chat.py` | `/api/chat`, `/ws/chat` | Core agent interaction |
| `skills.py` | `/api/skills` | Skill CRUD and testing (incl. graph create/validate + `graph.yaml`) |
| `designer.py` | `/api/designer` | Skill Designer — NL authoring (draft/validate/submit), isolated + governed |
| `personal_skills.py` | `/api/personal-skills`, `/api/skill-submissions` | Personal-skill workspace + review-queue (submit → admin approve) |
| `agents.py` | `/api/agents` | Agent configuration |
| `knowledge.py` | `/api/knowledge` | Knowledge store management |
| `approvals.py` | `/ws/dashboard` | HITL approval queue |
| `evolution.py` | `/api/evolution` | Self-evolution analysis |
| `cron.py` | `/api/cron` | Scheduled jobs |
| `queue.py` | `/api/queue`, `/ws/queue` | Command Center |
| `twin.py` | `/api/twin`, `/ws/twin` | Digital twin telemetry |
| `finops.py` | `/api/finops` | LLM cost analytics |
| `auth.py` | `/auth` | Authentication |
| `context_manager.py` | `/api/context-manager` | Knowledge base management |
| `workstreams.py` | `/api/workstreams`, `/ws/workstreams` | Mission Mode / recurring operations over item backlogs |
| `automations.py` | `/api/automations` | Deterministic (no-LLM) shell/python pipelines |
| `world_model.py` | `/api/world-model` | World Model graph — promote/reject entities & relations |
| `policy_control.py` | `/api/policy-control` | Central policy & control registry (governance rules) |
| `skill_packs.py` | `/api/skill-packs` | Skill Pack import/export |
| `rl_capture.py` | `/api/rl-capture` | RL/eval capture — trajectories, exports, corrections |
| `trace_value.py` | `/api/trace-value` | Trace-value assessment + governed promotion to learning destinations |
| `evals.py` | `/api/evals` | Private Learning Loop — eval suites, golden sets, gates, runs |

### Shared State

`shared/state.py` holds all singletons:
- `approval_store` — Redis-backed HITL approval store
- `cron_scheduler` — APScheduler instance
- `twin_emitter` — Digital twin telemetry emitter
- `trace_emitter` — Execution trace emitter, including token/cost totals, router usage attribution, non-ReAct execution finalization, HITL pause finalization, and stale-running trace display markers
- `session_store` — Redis or in-memory session store

### Authoring surfaces & live reasoning UX

- **Skill Designer (NL authoring)** — `routers/designer.py` + a draft-only `skill_designer` skill
  (`tools: []`) let developers describe a capability in English and get a drafted skill / graph /
  workstream / cron. It is isolated (forced `skill_name` server-side → never hits the runtime router)
  and persists only through the existing governed creators; skills/graphs go through the
  personal → review-queue → admin-approve flow (`personal_skills.py`). Surfaced as **Dev Mode** in the
  main chat and **Draft with AI** in the Graph Studio. See [SKILL_DESIGNER.md](SKILL_DESIGNER.md).
- **Graph Studio** — an admin-only "🕸 Graphs" tab in `/skill-builder/v2`
  (`static/js/graph-studio.js`, a `window.graphStudio()` mixin spread into the page's Alpine
  component): a gallery of graph skills + a structured visual editor (node/edge/convergence forms ⇄
  synced `graph.yaml` ⇄ live Mermaid diagram) + templates + inline Validate + Run-in-chat. See
  [PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md).
- **Live "thinking box"** — a contextual heartbeat (`chat.py`, ~1.5s: narrates the current step +
  per-activity elapsed) plus per-turn reasoning/tool activity emitted by the native React runtime.
  The chat UI shows a per-turn box (live label + ticking elapsed + phase dots + timeline) that
  collapses to "Thought for Ns", so long silent steps still narrate roughly every second.

---

## IAF Agent Skills (Layer 3)

**Technology:** LangGraph, LangChain, SQLite, Redis

**Entry point:** `iaf_agent_skills/agent.py`

### Key Modules

| Module | Responsibility |
|---|---|
| `agent.py` | `SkillAgent` — main orchestrator; initialises all components, runs skill |
| `router.py` | `SkillRouter` — keyword + semantic routing; loads registry |
| `memory.py` | `AgentMemory` — episodic history + knowledge record persistence |
| `knowledge_indexer.py` | SQLite FTS5 + vector index for knowledge search |
| `entity_registry.py` | `EntityRegistryStore` — entity resolution + ontology tree |
| `execution.py` | `ExecutionMode` enum + `WorkflowEngine`, `ParallelEngine`, `SupervisorEngine`, `OrchestratorEngine` |
| `rlm/` | RLM (reasoning-as-code) engine — governed code-action loop, AST guard, propose-then-apply holds |
| `process_graph.py` | Load/validate/`compile_to_plan` for stored process graphs (`execution_mode: graph`) |
| `react_runtime/` | React runtime selector — `native` (Azure-native tool calls) vs `langgraph` (default/rollback) |
| `model_call_pipeline.py` | `PolicyChatModel` — Before/Around/After provider-call phases (`MODEL_CALL_PIPELINE_ENABLED`) |
| `capture_events.py` | Neutral RL/eval event emitters (mirrored into the `rl_capture` sidecar store) |
| `mission_engine.py` / `workstream_store.py` | Mission Mode — per-item workstream execution over a backlog |
| `world_model.py` | World Model graph store (entities/relations; `GRAPH_BACKEND=relational\|age`) |
| `queue_manager.py` | Command Center queue lanes + concurrency control |
| `loader.py` | `SkillLoader` — reads SKILL.md frontmatter and prompt (incl. `graph_ref`) |
| `agentos_contracts/` | Dependency-free extension SDK: `Skill` descriptor, provider Protocols, React runtime selector |
| `planner.py` | `PlannerEngine` — `execute_plan` (planned DAG) + `execute_graph` (graph convergence: verifier loop + escalate) |
| `self_evolution.py` | `SelfEvolutionEngine` — 4-tier improvement pipeline |
| `plan_critic.py` | `PlanCritic` — plan critique + response grounding critique |
| `session_store.py` | Redis or in-memory session persistence |

### Skill Loading

```python
# SkillLoader reads every SKILL.md in skills/**/SKILL.md
skills = SkillLoader.load_all()
# Returns stable Skill descriptors from agentos_contracts.Skill.
# Legacy imports from iaf_agent_skills.loader.Skill still re-export that type.
```

### Routing Pipeline

```
query → SkillRouter.match(query)
    ↓
1. Keyword match against all skills' keywords list
2. Entity context (WHO signal from entity_registry)
3. Process taxonomy match (WHAT signal)
4. Signals agree? → single skill
5. Signals conflict? → planned mode
6. No match? → general skill
```

### Memory Architecture

```
Layer 1 — Episodic (what happened):
  memory/history/{date}/{session}.jsonl

Layer 2 — Knowledge (what was learned):
  memory/context_graph/knowledge.jsonl
  memory/context_graph/knowledge_pending.jsonl
  ← indexed in knowledge_index.db (FTS5 + vectors)

Layer 3 — Learnings (skill patterns):
  memory/learnings/{skill}/tool_execution.jsonl
  memory/learnings/{skill}/agent_error.jsonl
```

---

## AgentOS (Layer 2)

**Technology:** Pure Python, no external dependencies

**Entry point:** `agent_os/kernel.py`

**Embeddable package:** `agentos-kernel` (import package remains `agent_os`).
The kernel can be installed independently for sandboxed execution. Studio still
imports it from the source tree during local full-product runs.

Studio now constructs kernels through `create_kernel_runtime()`. The default
`AGENTOS_KERNEL_BACKEND=local` returns the historical in-process `SafeKernel`.
Enterprise deployments can set `AGENTOS_KERNEL_BACKEND=remote` and run
`IAF-Agent-Studio/kernel_worker.py`; the agent executor keeps the same shell,
`write_file`, and Python tool surface while the worker process owns the real
kernel, credential handles, path sandbox, subprocesses, and kernel audit writes.
Requests are HMAC-signed with `AGENTOS_KERNEL_TOKEN_SECRET`.

### Key Responsibilities

- Translate LLM commands to filesystem operations
- Enforce path sandboxing (no escaping agent_root)
- Enforce RBAC (USER/MANAGER/ADMIN/AUDITOR)
- Block dangerous commands and operators
- Rate limit command execution
- Audit log every command
- Auto-index `/memory/` writes for semantic search
- Mint short-lived self-auth service JWTs from environment settings
  (`JWT_SECRET`, `JWT_ALGORITHM`, `TENANT_ID`) without importing Studio modules

### Safety Model

```
run_shell_command("cat /../../etc/passwd")
      ↓
_parse_command() → detects .. → SecurityError
      ↓
Returns: "Error: path traversal not allowed"

run_shell_command("rm /workspace/file.md")
      ↓
_execute() → cmd='rm' → BLOCKED_COMMANDS check
      ↓
Returns: "Command 'rm' is not available"
```

### Virtual Path Translation

```
/me/profile.md     → enterprise_root/tenants/company/agents/enterprise_agent/users/demo/profile.md
/shared/contexts/  → enterprise_root/tenants/company/shared/contexts/
/workspace/        → enterprise_root/tenants/company/agents/enterprise_agent/workspace/
```

---

## Model Package Boundary

`agentos-model` is the composable model layer being extracted from
`iaf_agent_skills`. It now owns provider-neutral reasoning metadata,
`ModelRegistry`, `ModelProviderAdapter`, and the Azure Responses, Vertex/Gemini,
and Anthropic chat adapters. Historical imports through
`iaf_agent_skills.model_registry`, `iaf_agent_skills.model_provider`,
`iaf_agent_skills.model_reasoning_meta`, and provider chat modules remain as
compatibility shims.

When `MODEL_CALL_PIPELINE_ENABLED=true`, every provider call is wrapped by
`PolicyChatModel` (`model_call_pipeline.py`), which runs ordered `BeforeModelCall`,
`AroundModelCall`, and `AfterModelCall` phases before the runtime parses tool calls — the
governance/observability seam used for policy gating and RL/eval model-call capture.

## Engine Package Boundary

`agentos-engine` is the composable engine facade under
`IAF-Agent-Skills/agentos_engine/`. It re-exports the historical
`iaf_agent_skills` runtime for skill routing, memory, execution modes, and
session state. This gives customers a stable target import path while avoiding a
risky in-place rename of the full-product engine.

---

## Solution Modules (Optional Accelerators)

Optional domain packages live under `solution_modules/`. They consume core
AgentPro capabilities — traces, workstreams, skills, HITL, policy mining — but
do not duplicate installed tenant assets.

```
solution_modules/
  common/                         # Reusable Digital Twin / Process Intelligence contracts
  <your_module>/                  # Optional domain accelerator (none bundled by default)
    routers/
    services/
    static/
    manifest.yaml
    config/assets.yaml            # Reference-only list of required enterprise_root assets
```

Skills and workstreams stay in one place:

```
enterprise_root/tenants/<tenant>/skills
enterprise_root/tenants/<tenant>/workstreams
```

See [SOLUTION_MODULES.md](SOLUTION_MODULES.md).

---

## Enterprise Root (Layer 1)

A filesystem database — no database server required for basic operation. Structure:

```
enterprise_root/
  tenants/
    company/
      config/          Tenant config + auth SQLite DBs
      agents/          Agent memory, workspaces, history
      shared/          Shared contexts, knowledge, databases, policies
      users/           Tenant-level user profiles
  global_shared/       Cross-tenant resources (read-only)
```

All data is human-readable: JSONL for events, Markdown for docs, SQLite for indexes.

---

## Deployment Topology

### Single-Server (Development)

```
[Browser] ←→ [FastAPI server :8080] ←→ [SQLite] ←→ [Filesystem]
                      ↑
               [Azure OpenAI API]
```

### Production with Redis

```
[Browser] ←→ [FastAPI server :8080] ←→ [Redis :6379]
                      ↓
               [Azure OpenAI API]
                      ↓
               [SQLite databases]
                      ↓
               [enterprise_root/]
```

Redis enables:
- Persistent session state across server restarts
- Horizontal scaling (multiple FastAPI instances)
- HITL approval store with pub/sub
- Cron job persistence

### With SSL/TLS

```bash
# .env
SSL_CERTFILE=/path/to/cert.pem
SSL_KEYFILE=/path/to/key.pem
```

---

## Concurrency Model

| Component | Model | Notes |
|---|---|---|
| WebSocket connections | asyncio coroutines | Each connection is a coroutine in the event loop |
| Chat requests | asyncio.to_thread | SkillAgent.run() is synchronous; wrapped in thread |
| Parallel execution mode | asyncio.gather | Steps run concurrently in thread pool |
| Supervisor execution | ThreadPoolExecutor | Worker skills run in parallel threads |
| Cron scheduler | Background thread | APScheduler in blocking=False mode |
| Queue processor | asyncio tasks | Items claimed and run as asyncio.Task |
| File audit logging | File locking | fcntl.flock on Unix for concurrent writes |

Production separates the modular monolith into process roles using
`STUDIO_RUNTIME_ROLES`: horizontally scalable `api` replicas, Redis-elected
`scheduler` candidates, and queue workers. SQLite remains the default
single-worker queue claim store. After `command_center.db` is migrated and
`CC_QUEUE_STORAGE_BACKEND=postgres` is enabled with `DB_BACKEND=postgres`,
queue workers use transactional fenced leases and shared heartbeats so replicas
can safely claim distinct items. `all` preserves the single-process development
topology. Startup validation blocks embedded background roles with multiple
Uvicorn workers and blocks multiple queue workers unless the Postgres claim
store is active.

Strict API replicas use one Redis-backed session state so conversation history,
pending tools, and approval checkpoints survive load balancing and process
replacement. API startup fails when that dependency is unavailable.
`/health/live` reports process liveness; `/health/ready` probes the shared
session dependency and returns 503 while the replica is unsafe to receive
traffic. Scheduler/queue-only roles do not require the session store.

Recovery Readiness follows the dashboard read-service boundary: the API role
verifies only a server-configured isolated restore root, never cold-starts an
agent, and persists compact reports under the active tenant. The verifier reads
restored files and SQLite databases in read-only mode and rejects any restore
root that overlaps active `DATA_ROOT`.

---

## Extension Points

| What to extend | Where | How |
|---|---|---|
| New skill | `IAF-Agent-Skills/skills/` | Create `{name}/SKILL.md` |
| New tool | `agent_os/kernel.py` | Add `_cmd_{name}` handler |
| New API endpoint | `IAF-Agent-Studio/routers/` | Create new `APIRouter` |
| New execution mode | `iaf_agent_skills/execution.py` | Implement engine class |
| Custom memory layer | `iaf_agent_skills/memory.py` | Extend `AgentMemory` |
| New learning signal | `iaf_agent_skills/self_evolution.py` | Add signal type + handler |

---

## Execution Modes

| Mode | When used | How decided |
|---|---|---|
| `react` | Default — open-ended queries | Declared in SKILL.md or router LLM `mode_hint: react` |
| `orchestrator` | Sequential multi-skill queries | Router LLM `mode_hint: orchestrator` (complexity: multi_step) |
| `workflow` | Deterministic sequential steps | Declared in SKILL.md |
| `parallel` | Concurrent DAG steps | Declared in SKILL.md |
| `supervisor` | One skill delegates to others | Declared in SKILL.md |
| `rlm` | Reasoning-as-code: model writes Python over a governed tool allow-list (AST guard + propose-then-apply HITL holds) | Declared in SKILL.md (`tools:` allow-list) |
| `graph` | Stored process-graph (DAG of skill-nodes + verifier + convergence loop), run by `planner.execute_graph` | Declared in SKILL.md (`graph_ref: graph.yaml`) |
| `planned` | Multi-domain queries or UI Plan Mode (`force_plan`) | Router `mode_hint: planned` or chat `force_plan: true` → `general` + `create_plan` |

`graph` shares the planner engine with `planned`: `process_graph.compile_to_plan()` emits the same
plan dict `execute_plan` consumes, plus `graph_meta` (verifier + convergence) that routes it to
`execute_graph`. Plan mode = ephemeral LLM-built DAG (discovery); graph = stored governed DAG (codification).

See [IAF-Agent-Skills/docs/execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md),
[RLM_EXECUTION_MODE.md](RLM_EXECUTION_MODE.md), and
[PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md) for full details.

`DYNAMIC_ORCHESTRATOR_ENABLED=false` disables only the router-driven upgrade
from ReAct to dynamic orchestration. Such requests use ReAct instead; Planned
mode and execution modes explicitly declared by skills are unaffected.

`react_runtime` is separate from `execution_mode`. Skills may set `react_runtime: native` to
request the Azure-native React loop, but `execution_mode` remains `react`. Rollback is
`react_runtime: langgraph` or `IAF_REACT_RUNTIME=langgraph`.

---

## Key Design Decisions

**Skills are prompts, not code.** A skill is a `SKILL.md` file — a system prompt with
metadata. Adding a new domain capability means writing markdown, not deploying Python.

**ContextOS separates knowledge from instructions.** Skills reference context files
(`context_files: [/shared/contexts/...]`). Knowledge can be updated without changing the
skill prompt.

**Platform vs domain separation.** `IAF-Agent-Skills/`, `IAF-Agent-Studio/`, and
`agent_os/` are the platform. `enterprise_root/` is the customer layer. Optional
`solution_modules/` add domain accelerators without duplicating installed skills or
workstreams.

**Redis is runtime infrastructure.** Sessions, active cron due indexes/locks/run
history, HITL approval gates, and distributed worker coordination live in Redis.
Portable business definitions (skills, workstreams, standalone cron YAML, contexts,
policies) live in `enterprise_root`.

**Provider-backed replaceability.** Local providers remain authoritative defaults.
Customers can swap skill registry, routing, hooks, traces, and models through provider
Protocols. See [PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md) and
[COMPOSABLE_ADOPTION_SPEC.md](COMPOSABLE_ADOPTION_SPEC.md).

---

## Infrastructure Dependencies

| Dependency | Used for | Required? |
|---|---|---|
| Redis 6+ | Sessions, cron jobs, auth, HITL, scheduler leader lease | Yes for full product |
| Azure OpenAI / OpenAI | LLM inference (primary + light models) | Yes |
| SQLite | Business data DBs, default single-worker Command Center queue, local trace/twin telemetry | Auto-created |
| PostgreSQL | Optional pooled storage, pgvector, and multi-worker Command Center claim store | Required for queue replicas |
| OTLP HTTP collector | Optional external telemetry mirror via `TELEMETRY_EXPORTERS=local,otlp` | No |
| Python 3.11+ | Runtime | Yes |
