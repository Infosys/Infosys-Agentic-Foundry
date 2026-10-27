# IAF AgentPro — Quick Start

## Prerequisites

- Python 3.11+
- macOS, Linux, or Windows (WSL recommended on Windows)
- Azure OpenAI or OpenAI API key
- Redis (optional — required only for cron scheduling and HITL approval store)

---

## Step 1 — Create a virtual environment & install

Run everything from the harness root (`IAF_AgentOS_Harness/`). The Windows form is shown first; the macOS/Linux equivalent is in the inline comment.

```bash
python -m venv venv                    # macOS/Linux: python3 -m venv venv
venv\Scripts\activate                  # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt        # consolidated root lockfile (agent_os + Skills + Studio)
```

The root `requirements.txt` is the sole dependency source — you do **not** need per-package
or editable (`pip install -e`) installs. `server.py` puts `agent_os/` and `IAF-Agent-Skills/`
on the import path at startup. (The dependency-free contracts SDK at
`IAF-Agent-Skills/agentos_contracts/` can be installed separately as `agentos-contracts` for
embeddable-provider work, but that's optional.)

---

## Step 2 — Configure Environment

The server reads its config from `agent_os/config.env`. Copy the sample and fill it in:

```bash
copy agent_os\config.env.example agent_os\config.env   # macOS/Linux: cp agent_os/config.env.example agent_os/config.env
```

Edit `agent_os/config.env`:

```bash
# Azure OpenAI (recommended)
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-12-01-preview

# OR standard OpenAI-compatible
OPENAI_API_KEY=your-key-here
OPENAI_MODEL_NAME=gpt-4o

# Optional: Redis for cron + HITL + sessions
REDIS_URL=redis://localhost:6379

# Optional: Authentication
AUTH_ENABLED=false
```

---

## Step 3 — Start the Server

Run from the harness root:

```bash
python IAF-Agent-Studio\server.py      # macOS/Linux: python3 IAF-Agent-Studio/server.py
```

By default this uses the in-process AgentOS kernel. To test the enterprise
kernel process boundary, start `python3 kernel_worker.py` in `IAF-Agent-Studio`
and run Studio with `AGENTOS_KERNEL_BACKEND=remote` plus the same
`AGENTOS_KERNEL_TOKEN_SECRET`.

Expected startup output:

```
IAF Agent Studio starting...
URL: http://localhost:8081
Cron Scheduler: STARTED (0 jobs)
Workstream cron reconcile: 0 job(s), 0 skipped
Standalone cron reconcile: 0 job(s), 0 skipped
HITL Approval Store: DISABLED (start Redis to enable)
Twin Telemetry: DISABLED
Workstream Runtime DB: ENABLED
Automation Runtime DB: ENABLED
Admin Config: 0 applied, 0 skipped, 0 errors
```

If Workstream YAML files include `cron_schedule` and `cron_user_id`, startup
reconciles them into Redis-backed cron jobs. This keeps restored demo/workstream
packs visible on the Cron page even if Redis was reset.

Open [http://localhost:8081](http://localhost:8081) in your browser.

Domain-specific dashboards (e.g. a process-intelligence or digital-twin view)
can be added as an optional solution module under `solution_modules/`; see
[SOLUTION_MODULES.md](SOLUTION_MODULES.md). No module is bundled by default.

---

## Step 4 — First Chat

1. Open [http://localhost:8081](http://localhost:8081)
2. Type a query in the chat box: `"What can you help me with?"`
3. The agent will respond using the `general` skill

Try a domain-specific query:

```
Show me overdue invoices
```

The router will detect the AR/AP domain and route to the `ar_ops` or `invoice` skill.

---

## Step 5 — Create Your First Skill

1. Open [http://localhost:8081/skill-builder/v2](http://localhost:8081/skill-builder/v2)
2. Click **Skills** in the sidebar → **+ New Skill**
3. Fill in:
   - **Name:** `my_first_skill`
   - **Description:** `Answers questions about my domain`
   - **Keywords:** `my-topic, my-query-type`
   - **Execution Mode:** `react`
   - **Prompt:** `You are an expert assistant for [your domain]. Answer questions clearly and concisely.`
4. Click **Save**
5. Click **Test** → enter a test query → observe the response

---

## Step 6 — Upload a Knowledge File

1. In Skill Builder, select your skill
2. Click the **Knowledge** tab
3. Upload a PDF, TXT, or Markdown file relevant to your skill domain
4. The file will be available to the agent at `/shared/knowledge/{skill_name}/`

---

## Step 7 — Set Up a Scheduled Job

1. Open [http://localhost:8081/dashboard](http://localhost:8081/dashboard)
2. Click **Cron** in the sidebar
3. Click **+ New Job**:
   - **Name:** `Daily Digest`
   - **Skill:** `general`
   - **Task:** `Generate a brief summary of today's date and save to /workspace/daily.md`
   - **Schedule:** `0 9 * * 1-5` (9am weekdays)
4. Click **Save** → **Run Now** to test immediately

---

## Step 8 — Monitor with the Dashboard

The dashboard at [http://localhost:8081/dashboard](http://localhost:8081/dashboard) shows:

- **Active sessions** — currently running agent tasks
- **Approval queue** — HITL decisions pending human input
- **Cron jobs** — scheduled task history and next run times
- **Queue Monitor** — Command Center item state plus backend, worker, and stale
  claim health
- **Knowledge** — pending knowledge records awaiting confirmation
- **Traces** — per-request execution traces with tool call details
- **Recovery Readiness** — admin-only reports for a separately restored
  enterprise data root when `RECOVERY_VERIFICATION_ROOT` is configured

---

## Typical Configuration for Production

```bash
# .env
AUTH_ENABLED=true
JWT_SECRET=your-32-char-random-secret
REDIS_URL=redis://localhost:6379/0
TWIN_TELEMETRY=true
TRACE_TELEMETRY=true
CONTEXT_LOADING_MODE=file
QUEUE_BACKEND=redis

# SSL (optional)
SSL_CERTFILE=/path/to/cert.pem
SSL_KEYFILE=/path/to/key.pem
```

---

## Directory Structure After Setup

```
IAF-Agent-Studio/
├── server.py           Entry point
├── routers/            API endpoints
├── shared/             Config, models, state
├── static/             Web UI HTML files
├── auth/               JWT authentication
├── cc_queue/           Command Center queue
└── logs/               Server logs

IAF-Agent-Skills/
├── iaf_agent_skills/   Core engine (agent, router, memory, etc.)
├── skills/             SKILL.md files (one per skill)
└── docs/               Technical documentation

enterprise_root/
├── tenants/
│   └── company/
│       ├── config/     Tenant config + auth DB
│       ├── agents/     Agent memory and workspaces
│       └── shared/     Shared contexts, databases, policies
└── docs/               Data schema documentation

agent_os/
├── kernel.py           SafeKernel — sandboxed shell execution
├── kernel_runtime.py   Local/remote kernel runtime factory
├── safe_path.py        Path sandboxing
├── vector_store.py     Semantic memory index
└── docs/               Architecture documentation
```

---

## Troubleshooting

**Server won't start:**
- Check `pip install -r requirements.txt` completed successfully
- Verify Azure OpenAI key and endpoint in `.env`
- Check port 8081 is not in use: `lsof -i :8081`

**Agent returns errors:**
- Check server logs in `IAF-Agent-Studio/logs/`
- Try `python3 server.py` directly to see startup errors

**Redis warnings on startup:**
- In local non-strict mode these are non-blocking and chat can use process-local sessions
- Strict API mode requires `USE_REDIS_SESSIONS=true` and reachable Redis, so it
  fails startup instead of risking inconsistent sessions across replicas
- Check `/health/ready` when diagnosing a running API replica

**Skill not routing correctly:**
- Open the Skills tab → check keywords match your query
- Try `force_skill` in the chat options panel

## Production note

This quick start is the single-process developer path. A dedicated enterprise
deployment starts from `agent_os/config.enterprise.env.example` and separates
API, scheduler, and queue roles. Follow `ENTERPRISE_OPERATIONS_PROFILE.md`;
do not expose the developer defaults as a production configuration.
