# AgentPro — Setup & Developer Reference

> Drop this file into Cursor, GitHub Copilot Chat, or Claude as context.
> Ask questions like: "How do I create a skill?", "How do I configure Azure OpenAI?", "My dashboard is blank — why?"

---

## Platform Overview

AgentPro is an enterprise AI agent platform. Four core components:

| Folder | Purpose |
|--------|---------|
| `IAF-Agent-Studio/` | Web server + dashboard UI (FastAPI) |
| `IAF-Agent-Skills/` | Agent engine + skill definitions |
| `agent_os/` | Kernel, tools, filesystem abstraction |
| `enterprise_root/` | Tenant config, shared databases, user profiles |

---

## Initial Setup

### 1. Create a virtual environment & install dependencies
From the harness root (`IAF_AgentOS_Harness/`). Windows form first; macOS/Linux in the comment.
```bash
python -m venv venv                    # macOS/Linux: python3 -m venv venv
venv\Scripts\activate                  # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt        # consolidated root lockfile — the sole dependency source
```
> The root `requirements.txt` merges the `agent_os` / `IAF-Agent-Skills` / `IAF-Agent-Studio`
> deps. No per-package or editable (`pip install -e`) installs are needed — `server.py` puts
> the sibling packages on the import path at startup.

### 2. Configure environment
```bash
cp agent_os/config.env.example agent_os/config.env
```

Edit `agent_os/config.env`:
```bash
# Azure OpenAI (required)
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_DEPLOYMENT_LIGHT=gpt-4o-mini   # cheaper model for routing/critique
AZURE_OPENAI_API_VERSION=2024-12-01-preview

# Server
HOST=127.0.0.1
PORT=8081
DATA_ROOT=../enterprise_root

# Optional temporary rollback for router-selected multi-step orchestration
# true by default; false makes those requests use normal ReAct
DYNAMIC_ORCHESTRATOR_ENABLED=false

# Auth — set AUTH_ENABLED=true to require login
AUTH_ENABLED=true
AUTH_BACKEND=redis          # "redis" (default) or "sqlite" (if Redis unavailable)
AUTH_REGISTRATION_MODE=admin_only   # open | approval | admin_only

# Optional RL/eval capture + advisory Trace Value Router
RL_CAPTURE=true
TRACE_VALUE_ROUTER_ENABLED=false    # set true to auto-assess completed traces
TRACE_VALUE_ROUTER_SKILL=trace_value_router
# Judge calls use the light model role (AZURE_OPENAI_DEPLOYMENT_LIGHT, e.g. gpt-5-nano).

# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=change-this-to-a-long-random-secret

# Redis (optional — enables cron scheduling, session sharing, redis queue)
REDIS_URL=redis://localhost:6379
QUEUE_BACKEND=redis         # "redis" or "memory" (default when Redis absent)
CC_QUEUE_DB_PATH=           # optional SQLite Command Center DB override for isolated tests/workers
CC_QUEUE_STORAGE_BACKEND=sqlite  # sqlite by default; postgres enables fenced queue-worker leases
CC_QUEUE_DATABASE_URL=           # optional queue-specific Postgres DSN; falls back to DATABASE_URL
WORKSTREAM_RUNTIME_DB_PATH= # optional SQLite Workstream execution trace DB override
AUTOMATION_RUNTIME_DB_PATH= # optional SQLite Deterministic Automation trace DB override

# Telemetry (both default true — set false to disable)
TWIN_TELEMETRY=true
TRACE_TELEMETRY=true

# Response grounding critique (default off — enable for production accuracy)
CRITIQUE_ENABLED=false
CRITIQUE_MODE=async         # sync (blocks until done) | async (background)
```

### Dedicated enterprise deployment

For production, start from the stricter template:

```bash
cp agent_os/config.enterprise.env.example agent_os/config.env
```

Replace every placeholder through the enterprise secret/configuration manager.
Deploy the same application artifact as three process types:

```bash
# API replicas
STUDIO_RUNTIME_ROLES=api python3 IAF-Agent-Studio/server.py

# Optional hardened kernel worker. Use with AGENTOS_KERNEL_BACKEND=remote and
# a shared AGENTOS_KERNEL_TOKEN_SECRET on Studio and the worker.
cd IAF-Agent-Studio && python3 kernel_worker.py

# Two candidates are allowed; Redis keeps one active scheduler leader.
STUDIO_RUNTIME_ROLES=scheduler python3 IAF-Agent-Studio/scheduler_worker.py

# Exactly one while the Command Center claim store is SQLite. After migrating
# with CC_QUEUE_STORAGE_BACKEND=postgres, multiple queue roles may run.
STUDIO_RUNTIME_ROLES=queue python3 IAF-Agent-Studio/queue_worker.py
```

Strict mode requires authentication, explicit CORS origins, disabled demo and
unsigned-file compatibility, and 32-character queue/signing secrets. It rejects
unsafe startup. API processes also require `USE_REDIS_SESSIONS=true` and a
reachable Redis endpoint; use `/health/live` for liveness and `/health/ready`
for load-balancer readiness. Run entitlement policy in `observe` mode before `enforce`; see
`docs/ENTERPRISE_OPERATIONS_PROFILE.md` for rollout, rollback, sandbox, and
backup/restore instructions.

To enable Recovery Readiness, restore a backup into a separate data directory
and set `RECOVERY_VERIFICATION_ROOT` to that restored root. It must not overlap
the active `DATA_ROOT`. Admins can then use **Dashboard V2 → Recovery
Readiness**, or run
`python3 scripts/verification/verify_enterprise_restore.py verify --root <path>`.
The dashboard never accepts a browser-supplied filesystem path.
Optional live read probes require `RECOVERY_LIVE_BASE_URL`, a secret-managed
`RECOVERY_LIVE_TOKEN`, `RECOVERY_LIVE_CONFIRMATION=isolated-recovery-cell`, and
a `RECOVERY_REDIS_URL` whose host/port differs from production `REDIS_URL`.

### 3. Create admin user
```bash
python3 IAF-Agent-Studio/auth/seed_admin.py
# → admin@iaf.local / <value of IAF_ADMIN_PASSWORD>
# Change password after first login
```

### 4. Start the server
```bash
python3 IAF-Agent-Studio/server.py
# → http://localhost:8080

# Different port:
PORT=8081 python3 IAF-Agent-Studio/server.py
```

During startup, Studio starts the embedded cron scheduler and reconciles any
Workstream YAML with `cron_schedule` plus `cron_user_id` into a `ws_<name>` cron
job. This repairs stale or missing `cron_job_id` values after Redis resets,
branch restores, or demo pack restores.

Studio also reconciles standalone (non-workstream) cron jobs from
`enterprise_root/tenants/<tenant>/scheduler/jobs/*.yaml`. Existing Redis-only
standalone jobs can be exported with
`python3 IAF-Agent-Studio/scripts/export_standalone_crons.py`.

Deterministic Automation definitions live under
`enterprise_root/tenants/<tenant>/automations/*.yaml`; Python automation steps
run tenant scripts from `/shared/scripts`, backed by
`enterprise_root/tenants/<tenant>/shared/scripts/`. Run traces are stored in
`automation_runtime.db` under the tenant `shared/databases` directory by default.

Local setup uses the in-process AgentOS kernel by default
(`AGENTOS_KERNEL_BACKEND=local`). To test the enterprise process boundary, start
`IAF-Agent-Studio/kernel_worker.py`, set `AGENTOS_KERNEL_BACKEND=remote`, and
share the same 32+ character `AGENTOS_KERNEL_TOKEN_SECRET` between Studio and
the worker. Shell tools such as `cat`, `grep`, `ls`, `write_file`, and guarded
`python3` keep the same behavior.

Domain dashboards (e.g. a Digital Twin or Process Intelligence view) can be
shipped as an optional solution module under `solution_modules/`; none is
bundled by default. See [SOLUTION_MODULES.md](SOLUTION_MODULES.md).

---

## Directory Structure

```
AgentPro/
├── IAF-Agent-Studio/
│   ├── server.py                    ← Main entry point
│   ├── routers/                     ← API handlers (chat, skills, auth, knowledge…)
│   ├── auth/
│   │   └── seed_admin.py            ← Create/reset admin login
│   ├── shared/
│   │   └── config.py                ← Reads PORT, HOST, AUTH_ENABLED from env
│   └── static/
│       ├── dashboard_v2.html        ← Main dashboard UI
│       ├── skill-builder-v2.html    ← Visual skill editor
│       └── vendor/                  ← Offline JS (Alpine, Chart.js, D3, marked — no CDN)
│
├── solution_modules/
│   └── common/                      ← Reusable Digital Twin / Process Intelligence contracts
│                                      (no module bundled by default; see SOLUTION_MODULES.md)
│
├── IAF-Agent-Skills/
│   ├── agentos_contracts/           ← Dependency-free extension SDK
│   ├── agentos_model/               ← Model registry and provider adapters
│   ├── agentos_engine/              ← Compatibility facade over iaf_agent_skills
│   ├── skills/
│   │   ├── _index.yaml              ← Skill registry — router reads this
│   │   ├── general/                 ← Default fallback skill
│   │   │   └── SKILL.md
│   │   └── payment_processing/      ← Reference domain skill
│   │       └── SKILL.md
│   ├── iaf_agent_skills/
│   │   ├── router.py                ← Routes user query → correct skill (LLM + keyword)
│   │   ├── agent.py                 ← Executes skill (ReAct loop)
│   │   └── loader.py                ← Parses SKILL.md files
│   └── config/
│       └── credentials.yaml         ← API credentials for skills
│
├── scripts/
│   └── verification/                ← Ad-hoc live smoke and security verification scripts
│
├── docs/
│   └── generated/                   ← Ignored generated HTML review artifacts
│
├── agent_os/
│   ├── config.env                   ← Your secrets (never commit this)
│   ├── config.env.example           ← Template to copy from
│   └── kernel.py                    ← Tool execution engine
│
└── enterprise_root/
    └── tenants/
        └── company/
            ├── agents/
            │   └── enterprise_agent/
            │       └── config.yaml          ← Agent behaviour settings
            ├── shared/
            │   ├── Enterprise_Context.md    ← Business context injected into every prompt
            │   ├── contexts/                ← Domain-specific context files
            │   ├── policies/                ← Business rules
            │   └── databases/               ← SQLite skill/runtime DBs
            ├── scheduler/
            │   └── jobs/                    ← Standalone cron YAML source of truth
            └── users/
                └── admin/
                    └── profile.md           ← Admin user profile
```

---

## How Routing Works

Every user message goes through `IAF-Agent-Skills/iaf_agent_skills/router.py`:

1. **LLM classification** — sends query + skill list from `_index.yaml` to LLM → returns `{"skill": "payment_processing"}`
2. **Keyword fallback** — if LLM fails, matches `keywords:` in `_index.yaml` with word boundaries
3. **Sticky fallback** — short replies (< 15 words) stay with the current skill
4. **Default** — falls back to `default_skill: general`

The router validates the returned skill name against the known list — unknown names fall back to `default_skill`.

---

## Creating a Skill

### Step 1 — Create the folder
```bash
mkdir IAF-Agent-Skills/skills/my_skill
```

### Step 2 — Write SKILL.md
```markdown
---
name: my_skill
version: "1.0"
description: "What this skill does — this text is shown to the router LLM"
execution_mode: react

tools:
  - shell
  - run_sql_query

triggers:
  - keyword one
  - keyword two

approval_rules:
  always_require:
    - dangerous_action_name
---

# My Skill Agent

You are an expert in [domain]. Your job is to...

## Instructions
- Rule 1
- Rule 2
```

### Step 3 — Register in _index.yaml
```yaml
skills:
  my_skill:
    description: "What this skill does — be specific, this drives LLM routing"
    keywords:
      - keyword one
      - keyword two
    status: active
```

No restart needed — the router hot-reloads `_index.yaml` automatically.

---

## SKILL.md Frontmatter Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Skill identifier — must match folder name |
| `version` | string | `"1.0"` | Skill version |
| `description` | string | `""` | Used by router LLM for intent matching |
| `execution_mode` | string | `react` | `react` — standard ReAct agent loop |
| `tools` | list | `[]` | Tools available to the skill |
| `triggers` | list | `[]` | Keywords for keyword-based routing fallback |
| `knowledge` | list | `[]` | Paths to context folders auto-injected into prompt |
| `approval_rules` | dict | `{}` | HITL rules — which actions require human sign-off |
| `sql_mode` | string | `read_only` | `read_only` or `read_write` for `run_sql_query` |
| `mcp_connections` | list | `[]` | External MCP tool servers this skill can use |
| `business_context` | dict | `{}` | Domain metadata (domain, KPIs, databases) |

---

## Available Tools

| Tool | What it does |
|------|-------------|
| `shell` | Run bash commands, curl, python3 inline |
| `run_sql_query` | Query SQLite databases in `enterprise_root/` |
| `request_human_approval` | Pause execution and wait for human approval |
| `query_memory` | Search agent knowledge/memory store |

---

## _index.yaml Full Reference

```yaml
version: '1.0'
default_skill: general           # Fallback when no skill matches

entity_types:                    # Entity types the router extracts from queries
  - vendor
  - customer
  - invoice
  - purchase_order

entity_guide_path: null          # Path to entity guide .md (optional)

skills:
  skill_name:
    description: 'Shown to router LLM — be specific about what triggers this skill'
    keywords:
      - trigger phrase
      - another phrase
    status: active                # active | inactive
```

---

## Business Context

Every agent prompt is prefixed with:
```
enterprise_root/tenants/company/shared/Enterprise_Context.md
```

Customise this with your company's domain knowledge:
```markdown
# Acme Corp — Enterprise Context

**Industry:** Manufacturing
**ERP:** SAP S/4HANA
**Fiscal Year:** April–March

## Key Terms
- PO: Purchase Order
- GR: Goods Receipt
- AP: Accounts Payable
```

---

## Adding a Database

1. Place SQLite file in `enterprise_root/tenants/company/shared/databases/`
2. Reference it in SKILL.md frontmatter:
```yaml
business_context:
  databases:
    my_db:
      location: "/shared/databases/my_db.db"
```
3. Use `run_sql_query` tool in the skill body — the agent queries it directly.

---

## Human-in-the-Loop (HITL) Approvals

```yaml
approval_rules:
  always_require:
    - release_payment          # Tool call names that always need approval
    - delete_record
  thresholds:
    - field: "amount"
      operator: ">="
      value: 100000
      reason: "Payments over $100K require sign-off"
      urgency: high            # low | medium | high | critical
  conditions:
    - when: "blocked_vendor"
      reason: "Vendor is blocked — override needed"
      urgency: critical
  never_require:
    - list_payments            # Read-only actions — skip approval
```

Pending approvals appear in the **Approvals** tab of the dashboard.

---

## API Credentials

Edit `IAF-Agent-Skills/config/credentials.yaml`:
```yaml
my_api:
  type: api_key               # bearer | basic | api_key
  key: "your-key-here"
  scope: [my_skill, general]  # Which skills can use this — empty = all
  metadata:
    base_url: "https://api.example.com"
    description: "My external API"

# Basic auth example:
# sap_rfc:
#   type: basic
#   username: "svc_agent"
#   password: "your_password"
#   scope: [my_skill]
```

---

## UI Components

Skills return rich UI by embedding fenced blocks in their response:

```ui:data_table
{"columns":["Vendor","Invoice","Amount","Status"],"rows":[["Acme","INV-001","$1,500","Ready"]],"actions":["Approve","Hold"]}
```

```ui:stat_cards
{"cards":[{"icon":"📊","label":"Total","value":"1,234","trend":"▲ 5%"}]}
```

```ui:alert
{"type":"warning","title":"Action Required","message":"3 items need review"}
```

```ui:chart
{"type":"bar","title":"Payments by Month","labels":["Jan","Feb","Mar"],"datasets":[{"label":"Amount","data":[120000,95000,140000]}]}
```

```ui:progress
{"label":"Close Readiness","value":7,"max":10,"color":"green"}
```

---

## Enabling HTTPS (TLS)

By default the server runs on plain HTTP. Enable HTTPS when users access the server
over a network (office LAN, VPN, internet) so passwords and tokens are encrypted in transit.

No extra software needed — uvicorn handles TLS directly.

### Step 1 — Generate a self-signed certificate (once per deployment)

**Linux / Mac / WSL / Git Bash:**
```bash
mkdir -p agent_os/tls
openssl req -x509 -newkey rsa:4096 \
  -keyout agent_os/tls/key.pem \
  -out agent_os/tls/cert.pem \
  -days 3650 -nodes -subj "/CN=AgentPro"
```

**Windows PowerShell** (requires OpenSSL — use Git Bash or WSL if not installed):
```powershell
mkdir agent_os\tls
openssl req -x509 -newkey rsa:4096 `
  -keyout agent_os\tls\key.pem `
  -out agent_os\tls\cert.pem `
  -days 3650 -nodes -subj "/CN=AgentPro"
```

This creates two files:
- `agent_os/tls/cert.pem` — the public certificate
- `agent_os/tls/key.pem` — the private key (keep this secret, never commit)

The cert is valid for 10 years. Regenerate it when deploying to a new machine.

### Step 2 — Enable in config.env

Uncomment the two TLS lines in `agent_os/config.env`:
```bash
SSL_CERTFILE=../agent_os/tls/cert.pem
SSL_KEYFILE=../agent_os/tls/key.pem
```

### Step 3 — Restart the server

```bash
python3 IAF-Agent-Studio/server.py
```

You will see this in the startup log:
```
[TLS] HTTPS enabled — cert=../agent_os/tls/cert.pem
```

### Step 4 — Access via HTTPS

Open `https://<your-server-IP>:8080` (note **https**, not http).

The browser will show a "Your connection is not private" warning on the first visit —
this is expected for self-signed certs. Click **Advanced → Proceed** to continue.
Users only need to do this once per browser.

> **Note:** To remove the browser warning entirely you would need a cert signed by a
> trusted CA (e.g. Let's Encrypt with a public domain). For internal/enterprise
> deployments a self-signed cert pushed via group policy also silences the warning.

### Reverting to HTTP

Comment out both `SSL_CERTFILE` and `SSL_KEYFILE` lines in `config.env` and restart.
The startup log will show `[TLS] No cert configured — running plain HTTP`.

---

## Troubleshooting

### Windows Deployment

#### UTF-8 encoding error (`charmap codec can't decode byte`)
Windows Python defaults to `cp1252` (charmap) for file I/O. SKILL.md files and YAML
configs contain UTF-8 content (emojis, special characters) that `cp1252` cannot read.

**Fix — always start the server with UTF-8 mode set:**

Command Prompt:
```cmd
set PYTHONUTF8=1
python IAF-Agent-Studio\server.py
```

PowerShell:
```powershell
$env:PYTHONUTF8 = "1"
python IAF-Agent-Studio\server.py
```

**Or add to `agent_os/config.env`:**
```bash
PYTHONUTF8=1
```

**Or create a `start.bat` launcher:**
```bat
@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python IAF-Agent-Studio\server.py
pause
```

> The codebase already uses `encoding='utf-8'` on all file reads/writes
> and `allow_unicode=True` on all YAML dumps. The env var additionally covers
> logging output and any subprocesses launched by the shell tool.

#### Path separators
All internal paths use `pathlib.Path` — forward and back slashes are both handled.
You do not need to change any paths for Windows deployment.

#### Running as a Windows Service
Use `NSSM` (Non-Sucking Service Manager) or `pywin32`:
```cmd
nssm install AgentPro "C:\Python311\python.exe" "C:\AgentPro\IAF-Agent-Studio\server.py"
nssm set AgentPro AppEnvironmentExtra PYTHONUTF8=1
nssm set AgentPro AppDirectory C:\AgentPro\IAF-Agent-Studio
nssm start AgentPro
```

---

### Server won't start — port already in use
```bash
lsof -ti :8080          # Find process on port
kill <PID>              # Kill it
PORT=8082 python3 IAF-Agent-Studio/server.py   # Or use different port
```

### "Skill folder not found" error
- Folder name must exactly match the skill name in `_index.yaml`
- Check folder exists: `ls IAF-Agent-Skills/skills/`
- Remove any `_index.yaml` entries that don't have a matching folder

### Login not working / forgot password
```bash
python3 IAF-Agent-Studio/auth/seed_admin.py
# Resets to: admin@iaf.local / <value of IAF_ADMIN_PASSWORD>
```

### Dashboard is white/blank
- Open browser DevTools → Console tab to see the JS error
- All vendor JS is served locally from `/static/vendor/` — no internet required
- If Alpine.js fails to initialize, check `/static/vendor/alpine.min.js` exists

### Agent routes to wrong skill
- Make the skill `description` in `_index.yaml` more specific
- Add more `keywords:` to the skill entry
- Check `default_skill` is set to `general` as the catch-all

### Azure OpenAI errors
- Verify `config.env` values match exactly what's in Azure Portal
- Deployment name is case-sensitive
- Use API version `2024-08-01-preview` or later

---

## Quick Reference

| Task | How |
|------|-----|
| Start server (Linux/Mac) | `python3 IAF-Agent-Studio/server.py` |
| Start kernel worker | `cd IAF-Agent-Studio && AGENTOS_KERNEL_TOKEN_SECRET=<32+ chars> python3 kernel_worker.py` |
| Start server (Windows) | `set PYTHONUTF8=1 && python IAF-Agent-Studio\server.py` |
| Change port | `PORT=8081 python3 IAF-Agent-Studio/server.py` |
| Reset admin | `python3 IAF-Agent-Studio/auth/seed_admin.py` |
| Generate JWT secret | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| Add a skill | `mkdir skills/<name>` → write `SKILL.md` → add entry to `_index.yaml` |
| Edit business context | `enterprise_root/tenants/company/shared/Enterprise_Context.md` |
| Enable HTTPS | Generate cert → uncomment SSL_CERTFILE/SSL_KEYFILE in config.env → restart |
| Generate TLS cert | `openssl req -x509 -newkey rsa:4096 -keyout agent_os/tls/key.pem -out agent_os/tls/cert.pem -days 3650 -nodes -subj "/CN=AgentPro"` |
| Skill builder UI | http://localhost:8080/skill-builder/v2 |
| Dashboard | http://localhost:8080/dashboard/v2 |
| Admin login | `admin@iaf.local` / the password set in `IAF_ADMIN_PASSWORD` |
