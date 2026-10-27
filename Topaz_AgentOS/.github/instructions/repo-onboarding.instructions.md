---
description: "Use when a first-time contributor asks how to install, set up, run, or contribute to the IAF AgentOS Harness locally. Covers Python 3.13 install steps, virtualenv, dependencies, Redis/Postgres prerequisites, config.env, starting the server, and repo layout. Trigger phrases: install, onboard, first time, how do I start, setup, run locally, python version, python 3.13, python 3.14, virtualenv, requirements."
applyTo: "**/README.md, requirements.txt, **/config.env.example, IAF-Agent-Studio/server.py"
---

# IAF AgentOS Harness — Install & First-Run Guide

## Python version

- **Supported: Python 3.13.** Install and run the AgentOS code on CPython 3.13.
- **Python 3.14: work in progress** — not yet supported. Do not target 3.14 for local setup; some pinned dependencies do not yet publish 3.14 wheels. Track 3.14 support separately.
- Minimum floor across subpackages is 3.10 (declared in each `pyproject.toml`), but the verified, tested runtime is **3.13**.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.13** | 3.14 is WIP/unsupported |
| Redis | 6+ | Session store, cron scheduler, queue, HITL approvals |
| PostgreSQL | 14+ | Only when `DB_BACKEND=postgres` (+ `pgvector` extension for vector search). SQLite is the zero-dependency default. |
| An LLM provider | one of Azure OpenAI / OpenAI-compatible / Vertex | Configured in `config.env` |

## Install (Python 3.13)

```bash
# 1. Create and activate a 3.13 virtualenv
py -3.13 -m venv venv            # Windows
# python3.13 -m venv venv        # macOS/Linux
.\venv\Scripts\Activate.ps1      # Windows PowerShell
# source venv/bin/activate       # macOS/Linux

# 2. Install pinned dependencies (single root lockfile)
pip install -r requirements.txt

# 3. Install the local subpackages (editable)
pip install -e ./agent_os ./IAF-Agent-Skills

# 4. Configure the LLM provider + secrets
cp IAF-Agent-Studio/config.env.example IAF-Agent-Studio/config.env
# edit config.env - pick ONE provider block, set REDIS_URL / DATABASE_URL
```

## Run the server locally

```bash
cd IAF-Agent-Studio
python server.py                 # serves http://localhost:8080 (or PORT from config.env)
```

Redis (and Postgres if `DB_BACKEND=postgres`) must be running first. On a clean boot you should see `PostgresEngine: connection pool ready`, `RedisQueueManager initialized`, and `Application startup complete`.

## Dependencies strategy

- **Edit only the root [requirements.txt](../../requirements.txt)** - it is the single pinned lockfile.
- Each subpackage (`agent_os/`, `IAF-Agent-Skills/`) declares its own runtime deps in its `pyproject.toml` (loose floors) so it can be installed standalone for future microservice extraction. Do not add per-subpackage `requirements.txt` files.

## Repo layout (orientation)

```text
agent_os/            SafeKernel: sandbox, credential store (pip-installed)
IAF-Agent-Skills/    Skill engine, providers, model registry (pip-installed)
IAF-Agent-Studio/    FastAPI server, routers, static UI  <- run server.py here
enterprise_root/     Tenant seed: skills, workstreams, agents, policies
solution_modules/    Optional domain accelerators
requirements.txt     Root pinned lockfile (the only one to edit)
```

## Working conventions

- **Resolve paths from config**, not hardcoded absolutes: `DATA_ROOT`, `SKILLS_PATH`, `TENANT_ID`. See [AGENTS.md](../../AGENTS.md).
- **Model calls go through the provider layer** (`ModelProviderAdapter`/`ModelRegistry`), not SDKs directly.
- **Routers stay thin** - business logic in service modules, not FastAPI routers or Alpine UI handlers.
- **Tests define behavior.** When docs and code disagree, trust code + tests. See [docs/DOCUMENTATION_AUTHORITY.md](../../docs/DOCUMENTATION_AUTHORITY.md).

## Common first-run issues

- **`RequestsDependencyWarning: urllib3 ... doesn't match a supported version`** - harmless version-skew warning; safe to ignore.
- **Server exits immediately** - Redis not running, or `REDIS_URL`/`DATABASE_URL` wrong in `config.env`.
- **Trying Python 3.14** - not supported yet; recreate the venv with 3.13.
- **UnicodeDecodeError on a `.py` file** - a copy-paste corrupted a non-ASCII char (em-dash); re-transfer via git/scp, not clipboard.
