# IAF AgentOS Harness

> Infosys Agentic Foundry — container-shipped runtime for multi-tenant AI agents.

**Version `1.0.8`** — the app/harness version from the repo-root `Version` file, served at `GET /auth/version`. See [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md) for what changed and how the image tag and package versions relate.

Skill-based agent execution platform. Each **skill** is a self-contained domain expert defined by a `SKILL.md` prompt, context files, and approval rules. The harness handles routing, memory, hooks, planning, human approval gates, and a web UI.

- **Image**: framework code + generic agent-OS scaffolding + finance-domain agents. Customer-neutral.
- **Customer-specific solutions**: domain accelerators ship separately as optional solution modules (see [solution_modules/](solution_modules/)), not baked into the generic image. See [What ships in the image (and what does not)](#what-ships-in-the-image-and-what-does-not) below.

---

## Quickstart

> This branch is source-only — container/deploy assets (`Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `deploy/`) have been removed. For a containerized run, use a branch that still ships them (e.g. `dev`).

### Local dev (no container)

Prereqs: **Python 3.12**, **Redis** (required), **Postgres** (only if `DB_BACKEND=postgres`; SQLite is the default), and an LLM provider (Azure / OpenAI-compatible / Vertex).

Commands below show the Windows form first; the macOS/Linux equivalent is in the inline comment.

```bash
# 1. Clone/extract the code base, then enter the harness
cd IAF_AgentOS_Harness

# 2. Create a virtual environment
python -m venv venv                    # macOS/Linux: python3 -m venv venv

# 3. Activate it
venv\Scripts\activate                  # macOS/Linux: source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Ensure agent_os/config.env exists and is filled in (copy the sample if needed)
copy agent_os\config.env.example agent_os\config.env   # macOS/Linux: cp agent_os/config.env.example agent_os/config.env
#   then edit agent_os\config.env — provider creds, REDIS_URL, etc.

# 6. Make sure Redis is running (and Postgres only if DB_BACKEND=postgres)

# 7. Start the server from the harness root (defaults to port 8081)
python IAF-Agent-Studio\server.py      # macOS/Linux: python3 IAF-Agent-Studio/server.py
```

Open `http://localhost:8081`.

> **No editable installs needed.** `server.py` bootstraps `sys.path` on startup (via
> `shared/config.py`), so `agent_os` and `IAF-Agent-Skills` import correctly when you run it
> from the harness root as shown. The server reads its config from `agent_os/config.env`; TLS
> is optional — set `SSL_CERTFILE`/`SSL_KEYFILE` there to serve HTTPS instead of HTTP on 8081.
> On Windows use `venv\Scripts\Activate.ps1` (PowerShell) or `venv\Scripts\activate.bat` (cmd).

---

## What ships in the image (and what does not)

| Layer | In image | Delivered separately |
|---|---|---|
| Framework code (`agent_os`, `IAF-Agent-Skills`, `IAF-Agent-Studio`) | yes | — |
| Generic OS agents (`agentos_guide`, `iaf_guide`, `deep_research`, `mission_mode`, hooks, tools, viewers) | yes | — |
| Finance-domain agents (`ap_*`, `ar_*`, `sts-*`, `journal-*`, `fa_*`, etc.) | yes | — |
| Customer-specific solution modules | no | [solution_modules/](solution_modules/) is the extension point; none ship by default |
| Demo DB rows (AP/AR invoices, entity registry, digital twin) | scripts shipped, off by default | `DEMO_DATA=true` opt-in |
| Runtime state (databases, memory, audit, workspace, users) | no | Named volume `agentos-data` |
| TLS keys | no | Bind-mount `./certs` |

---

## Repository layout

```text
IAF_AgentOS_Harness/
├── agent_os/                    # SafeKernel, sandbox, credential store
├── IAF-Agent-Skills/            # Skill engine, contracts SDK, providers, model registry
├── IAF-Agent-Studio/            # FastAPI server, REST + WebSocket, static UI
├── iaf_agentos/                 # CLI + bootstrap utilities
├── enterprise_root/             # Tenant seed — code-shaped, baked into image
│   └── tenants/<tenant>/
│       ├── agents/              # Agent configs
│       ├── skills/              # Skill folders
│       ├── workstreams/         # Mission Mode YAML
│       ├── evals/               # Eval suites
│       ├── eval_evaluators/     # Evaluator definitions
│       ├── shared/              # Enterprise context, docs, knowledge bundles
│       ├── security/            # Policies, entitlements
│       └── config/              # Tenant-scoped config
├── solution_modules/            # Optional reusable accelerators; none ship by default
├── onboarding/                  # Demo-data seeds (opt-in via DEMO_DATA=true)
├── scripts/                     # Migration + seed utilities
├── partner_adapters/            # Sample bring-your-own provider adapters
├── rl_capture/                  # RL/eval capture package
├── requirements.txt             # Root lockfile — SOLE source of pinned deps
├── Version                      # Authoritative app/harness version (served at /auth/version)
├── AGENTS.md                    # Repo-wide guidance for AI coding agents
└── docs/                        # Product + architecture docs
    ├── README.md                # Doc index (persona-based reading paths)
    ├── RELEASE_NOTES.md         # Themed release notes (file-level detail in CHANGES.md)
    └── *_RUNBOOK.md             # Operations runbooks (VM startup, storage cutover)
```

Runtime files (`databases/`, `memory/`, `.audit/`, `workspace/`, `users/`, workstream synthesis, `__pycache__/`, `*.egg-info/`, `docs/generated/`) are git-ignored.

---

## Adding a new skill

1. Create `enterprise_root/tenants/<tenant>/skills/<your-skill>/`.
2. Add `SKILL.md` with frontmatter (`name`, `description`, `keywords`, `tools`, `context_files`) and the agent system prompt.
3. Register the skill in `enterprise_root/tenants/<tenant>/shared/Enterprise_Context.md` (routing context) and `_index.yaml`.
4. Restart the server.

Full authoring guide: [docs/AUTHORING_GUIDE.md](docs/AUTHORING_GUIDE.md). Starter templates: [docs/skill_templates/](docs/skill_templates/).

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8081` | Server port |
| `HOST` | `0.0.0.0` | Bind address |
| `DATA_ROOT` | `/app/enterprise_root` | Tenant tree root |
| `SKILLS_PATH` | `${DATA_ROOT}/tenants/${TENANT_ID}/skills` | Skill discovery root |
| `TENANT_ID` | `company` | Active tenant |
| `AGENT_ID` | `enterprise_agent` | Active agent config folder |
| `REDIS_URL` | *(required — set in `iaf-agentos.env`)* | Session store, queue, cron scheduler |
| `DATABASE_URL` | *(required — set in `iaf-agentos.env`)* | Postgres (knowledge/evidence/trace/queue) |
| `DB_BACKEND` | `postgres` | Storage backend (`sqlite` or `postgres`) |
| `AUTH_ENABLED` | `false` | Enable login/user auth |
| `DEMO_DATA` | `false` | Run demo seed scripts on boot |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Full env reference: [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md).

---

## Documentation

- **First stop**: [docs/README.md](docs/README.md) — persona-based reading paths.
- **When docs and code disagree**: code wins. See [docs/DOCUMENTATION_AUTHORITY.md](docs/DOCUMENTATION_AUTHORITY.md).
- **What changed**: [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md) (themed) · [docs/CHANGES.md](docs/CHANGES.md) (file-level).
- **Architecture**: [docs/03_architecture.md](docs/03_architecture.md).
- **Decisions**: [docs/ADR_001_ENTERPRISE_P0_CELL.md](docs/ADR_001_ENTERPRISE_P0_CELL.md).
- **Operations runbooks**: [docs/GEMMA_VM_STARTUP_RUNBOOK.md](docs/GEMMA_VM_STARTUP_RUNBOOK.md), [docs/SHARED_STORAGE_CUTOVER_RUNBOOK.md](docs/SHARED_STORAGE_CUTOVER_RUNBOOK.md).

---

## Contributing

- Read [AGENTS.md](AGENTS.md) for repo-wide guidance (also loaded by AI coding agents).
- Update [docs/CODE_DOC_MAP.yaml](docs/CODE_DOC_MAP.yaml) when you add or move a source file.
- Only edit the root [requirements.txt](requirements.txt). Subpackage deps live in each subpackage's `pyproject.toml`.
- Tests are the contract. See [docs/DOCUMENTATION_AUTHORITY.md](docs/DOCUMENTATION_AUTHORITY.md).
