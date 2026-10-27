# Topaz AgentOS

> An enterprise-grade, skill-based agent execution platform. Multi-tenant, LLM-agnostic, and designed to be extended by domain experts — no deep Python knowledge required to add new capabilities.

**Version `1.0.0`** 

---

## What It Is

Topaz AgentOS is a production-ready harness for running AI agents at enterprise scale. Rather than treating an AI agent as a single monolithic system prompt, it breaks capabilities into **skills** — self-contained, file-based domain experts that can be authored, versioned, and routed to independently.

The harness handles everything the skill author shouldn't have to think about: routing queries to the right skill, managing memory across sessions, enforcing human approval gates, sandboxing tool execution, scheduling recurring jobs, and streaming results to a web UI.

---

## Key Capabilities

### Skill-Based Architecture
Each capability is a **SKILL.md** file — a markdown document with a YAML frontmatter block declaring the skill's name, routing keywords, tools, context files, and execution mode, followed by the agent system prompt. Domain experts write and maintain skills without touching Python. A doc-to-skill pipeline can also auto-generate a deployable SKILL.md from an uploaded PDF, DOCX, PPTX, or audio file.

### Intelligent Multi-Signal Router
Every query is routed using three pre-LLM signals combined in a single router LLM call:
- **Entity signal** — who/what the query is about, resolved via FTS5 full-text search and ontology lookup
- **Taxonomy signal** — what business activity is requested, scored against 272+ L5 activity nodes indexed at startup
- **Keyword signal** — direct keyword match from each skill's declared keywords

The router returns the target skill, entity name, complexity class, and execution mode in a single JSON response.

### Multiple Execution Modes on One Runtime
Declare the execution mode per skill in SKILL.md, or let the router auto-select based on query complexity:

| Mode | When to use |
|---|---|
| `react` | Default — tool-calling loop, agent decides sequence at each step |
| `orchestrator` | Multi-step queries — manager LLM dispatches child skills sequentially |
| `planned` | Multi-domain queries — PlannerEngine builds a DAG of sub-agents |
| `workflow` | Deterministic pipelines with fixed step order |
| `parallel` | Concurrent sub-tasks via asyncio |
| `supervisor` | Meta-agent coordinating specialist agents |
| `rlm` | Reasoning-as-code — model writes governed Python; AST-guarded with HITL holds |
| `graph` | Stored process graph with verifier nodes and convergence loop |

### SafeKernel — Sandboxed Tool Execution
Every tool call goes through **SafeKernel**, a secure shell-like execution engine that enforces:
- Virtual path sandboxing (`/shared/`, `/me/`, `/workspace/`) — `..` traversal blocked at the string level
- Allowlist-controlled commands — only declared commands (`cat`, `ls`, `grep`, `curl`, `python3`, etc.) can run; anything unlisted is rejected at parse time
- Sliding-window rate limiting per kernel instance
- Thread-safe atomic file writes (threading.Lock + fcntl.flock)
- Optional OS-level isolation for inline Python execution

### Three-Layer Memory
| Layer | Store | What it holds |
|---|---|---|
| Episodic | JSONL per session | Turn-by-turn interaction history |
| Knowledge | SQLite + FTS5 + pgvector | Persistent facts, entity records, learned rules |
| Session | Redis | Active session state, plan cache, streaming context |

### Human-in-the-Loop (HITL)
Four built-in mechanisms for requiring human approval before sensitive actions: hook-based pre-tool gates, skill-level approval rules, Command Centre queue for async batch approval, and HITL holds inside RLM skills. Approval state survives server restarts via Redis.

### Self-Evolution & Learning
The agent can propose and save new skills, refine existing ones, and accumulate per-skill learnings from interaction feedback. An eval/capture pipeline records trajectories for SFT, DPO, and RFT fine-tuning workflows.

### Cron & Workstreams
Redis-backed cron scheduler with distributed worker support. **Workstreams** (Mission Mode) model recurring autonomous operations over item backlogs — defined in YAML, backed by cron, and surfaced in the web UI.

### Multi-Tenant
All tenant state lives under `enterprise_root/tenants/<tenant_id>/`. Skills, agents, context, security policies, memory, and eval suites are all scoped per tenant. Switch tenants with a single env var.

### LLM-Agnostic
Pluggable provider layer supports Azure OpenAI, Anthropic Claude, any OpenAI-compatible endpoint, and Vertex AI. Provider slots are declared in config; swapping the LLM backend requires no code changes.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  IAF-Agent-Studio                                            │
│  Web UI + REST API + WebSocket streaming                     │
│  FastAPI · Alpine.js · TailwindCSS  (port 8081)             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  IAF-Agent-Skills                                            │
│  Skill routing · execution modes · memory · self-evolution   │
│  LangGraph ReAct · LangChain · SQLite / pgvector             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  agent_os (SafeKernel)                                       │
│  Sandboxed shell · RBAC · path safety · audit logging        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  enterprise_root                                             │
│  Filesystem data store: skills · memory · config · policies  │
│  JSONL · SQLite · Markdown · YAML                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Quickstart

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.12 | Required |
| Redis | Required — session store, queue, cron scheduler |
| PostgreSQL | Optional — only when `DB_BACKEND=postgres`; SQLite is the default |
| LLM provider | Azure OpenAI, Anthropic Claude, any OpenAI-compatible endpoint, or Vertex AI |

### Local setup

Windows commands are shown first; the macOS/Linux equivalent is in the inline comment.

```bash
# 1. Enter the harness directory
cd IAF_AgentOS_Harness

# 2. Create a virtual environment
python -m venv venv                    # macOS/Linux: python3 -m venv venv

# 3. Activate it
venv\Scripts\activate                  # macOS/Linux: source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Copy and fill in the config
copy agent_os\config.env.example agent_os\config.env
#    macOS/Linux: cp agent_os/config.env.example agent_os/config.env
#    Edit the file — set your LLM provider credentials, REDIS_URL, etc.

# 6. Make sure Redis is running

# 7. Start the server (defaults to port 8081)
python IAF-Agent-Studio\server.py      # macOS/Linux: python3 IAF-Agent-Studio/server.py
```

Open `http://localhost:8081`.

> `server.py` bootstraps `sys.path` at startup, so `agent_os` and `IAF-Agent-Skills` import correctly when run from the harness root — no editable installs needed. TLS is optional: set `SSL_CERTFILE` and `SSL_KEYFILE` in `agent_os/config.env` to serve HTTPS.

For a managed stack bring-up (Postgres → Redis → server in order), use the scripts in `ops/`:
```bash
ops\start.sh     # macOS/Linux: bash ops/start.sh
```

---

## Repository Layout

```text
IAF_AgentOS_Harness/
├── agent_os/                    # SafeKernel — sandboxed execution, RBAC, path safety, audit
├── IAF-Agent-Skills/            # Skill engine, routing, memory, self-evolution, contracts SDK
├── IAF-Agent-Studio/            # FastAPI server, REST + WebSocket API, web UI (Designer Studio)
├── iaf_agentos/                 # CLI entry point and bootstrap factory
├── enterprise_root/             # Tenant data tree — all state lives here
│   └── tenants/<tenant>/
│       ├── agents/              # Agent configuration (tools, hooks, MCP connections)
│       ├── skills/              # Skill folders — one SKILL.md per capability
│       ├── workstreams/         # Mission Mode YAML — recurring autonomous operations
│       ├── evals/               # Eval suites and golden sets
│       ├── eval_evaluators/     # Evaluator rubric definitions
│       ├── shared/              # Enterprise context, knowledge bundles, taxonomy
│       ├── security/            # Policies, entitlements, approval rules
│       └── config/              # Tenant-scoped configuration
├── solution_modules/            # Optional domain accelerators (loaded at startup if present)
├── partner_adapters/            # Reference bring-your-own provider adapter implementations
├── rl_capture/                  # RL/eval trajectory capture package
├── scripts/                     # DB migration and maintenance utilities
├── ops/                         # Stack management scripts (start / stop / status / restart)
├── frontend/                    # Auth JS utilities (MSAL, session management)
├── templates/                   # HTML templates for auth pages (login, register)
├── tests/                       # Test suite
├── docs/                        # Full documentation (see docs/README.md for reading paths)
├── requirements.txt             # Root dependency lockfile — the sole source of pinned versions
├── Version                      # Authoritative app version string (served at /auth/version)
└── AGENTS.md                    # Repo-wide guidance for AI coding agents (Claude, Copilot, etc.)
```

Runtime-generated directories (`databases/`, `memory/`, `.audit/`, `workspace/`, `users/`, `__pycache__/`, `*.egg-info/`, `docs/generated/`) are git-ignored.

---

## Adding a Skill

1. Create a folder: `enterprise_root/tenants/<tenant>/skills/<your-skill>/`
2. Add `SKILL.md` with a frontmatter block (`name`, `description`, `keywords`, `tools`, `context_files`, `execution_mode`) followed by the agent system prompt.
3. Register the skill in `enterprise_root/tenants/<tenant>/shared/Enterprise_Context.md` (routing context) and `_index.yaml`.
4. Restart the server (or use the Designer Studio → Skill Creator UI to author and register without a restart).

Full authoring guide: [docs/AUTHORING_GUIDE.md](docs/AUTHORING_GUIDE.md)  
Starter templates (one per execution mode): [docs/skill_templates/](docs/skill_templates/)  
End-to-end developer flow: [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8081` | Server listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `DATA_ROOT` | `./enterprise_root` | Tenant tree root |
| `TENANT_ID` | `company` | Active tenant |
| `AGENT_ID` | `enterprise_agent` | Active agent config folder |
| `REDIS_URL` | *(required)* | Session store, cron scheduler, HITL queue |
| `DATABASE_URL` | *(required for postgres)* | PostgreSQL connection string |
| `DB_BACKEND` | `sqlite` | Storage backend — `sqlite` or `postgres` |
| `AUTH_ENABLED` | `false` | Enable login and user authentication |
| `SSL_CERTFILE` | — | Path to TLS certificate (enables HTTPS) |
| `SSL_KEYFILE` | — | Path to TLS private key |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CONTEXT_LOADING_MODE` | `file` | Context strategy — `file` (markdown) or `table` (entity registry + FTS5) |
| `AGENT_PYTHON3_ENABLED` | `false` | Allow inline Python execution inside skills |

Full reference with all runtime knobs: [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md)  
Exhaustive catalog of every execution knob: [docs/HARNESS_CONFIGURATION_CATALOG.md](docs/HARNESS_CONFIGURATION_CATALOG.md)

---

## Documentation

The `docs/` folder is comprehensive. Start with the index which has persona-based reading paths (skill author, platform developer, integration developer, operator):

**[docs/README.md](docs/README.md)** — master documentation index

Key guides by role:

| Role | Where to start |
|---|---|
| Adding a skill (no Python) | [AUTHORING_GUIDE.md](docs/AUTHORING_GUIDE.md) |
| Extending the engine (Python) | [docs/03_architecture.md](docs/03_architecture.md) → [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) |
| Calling the API / building a frontend | [IAF-Agent-Studio/docs/api_reference.md](IAF-Agent-Studio/docs/api_reference.md) |
| Deploying and operating | [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) · [CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) |
| Security and auth | [docs/07_auth_and_users.md](docs/07_auth_and_users.md) · [SECURITY_DEVELOPER_GUIDE.md](docs/SECURITY_DEVELOPER_GUIDE.md) |
| Human approval gates | [HITL_DESIGN_GUIDE.md](docs/HITL_DESIGN_GUIDE.md) |
| Scheduled / recurring jobs | [docs/STANDALONE_CRON_JOBS.md](docs/STANDALONE_CRON_JOBS.md) · [WORKSTREAMS_AS_RECURRING_OPERATIONS.md](docs/WORKSTREAMS_AS_RECURRING_OPERATIONS.md) |
| Eval, RL capture, learning loop | [RL_EVAL_CAPTURE.md](docs/RL_EVAL_CAPTURE.md) · [PRIVATE_LEARNING_LOOP.md](docs/PRIVATE_LEARNING_LOOP.md) |

---

## Contributing

- Read [AGENTS.md](AGENTS.md) for repo-wide conventions (also loaded automatically by AI coding agents).
- After adding or moving a source file, update [docs/CODE_DOC_MAP.yaml](docs/CODE_DOC_MAP.yaml) to keep the doc map in sync.
- All dependency versions live in the root [requirements.txt](requirements.txt). Subpackage `pyproject.toml` files declare package metadata only — do not add version pins there.
- When docs and code disagree, code wins. See [docs/DOCUMENTATION_AUTHORITY.md](docs/DOCUMENTATION_AUTHORITY.md).
