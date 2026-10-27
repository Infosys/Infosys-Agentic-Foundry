# IAF AgentOS — Developer Guide

**Infosys Agentic Foundry** | Agentic Harness Platform

---

## Who This Guide Is For

- **Skill authors** — adding new domain capabilities (no Python required)
- **Platform developers** — extending the engine, writing tools, adding hooks
- **Integrators** — wiring the platform to external systems

---

## Part 1 — Adding a New Skill (No Code Required)

A skill is a markdown file (`SKILL.md`) that tells the agent what it knows and which tools to use. No Python needed.

### Step 1 — Create the skill folder

```
enterprise_root/tenants/company/skills/
└── <your_skill_name>/
    └── SKILL.md
```

### Step 2 — Write SKILL.md

Minimum required frontmatter + body:

```markdown
---
name: invoice_ops
description: Handles invoice lookups, payment status, and vendor queries
version: "1.0"
execution_mode: react
tools:
  - read_file
  - query_memory
  - run_sql
keywords:
  - invoice
  - payment
  - vendor
  - PO number
context_file: /shared/contexts/AP_Policy.md
---

You are an expert in Accounts Payable operations.

## Your job
Answer questions about invoices, payment terms, and vendor records.

## How to answer
1. Call `query_memory` first — the user may have asked about this vendor before.
2. Use `run_sql` on the AP database for live invoice status.
3. For policy questions, read `/shared/contexts/AP_Policy.md`.

## Rules
- Never guess payment dates — always query the database.
- If a PO number is missing, ask the user before proceeding.
- Format currency as ₹XX,XX,XXX or $XX,XXX depending on region.
```

### Step 3 — Register the skill in `_index.yaml`

```yaml
# enterprise_root/tenants/company/skills/_index.yaml
skills:
  - name: invoice_ops
    path: invoice_ops/SKILL.md
    domains: [finance, accounts_payable]
```

### Step 4 — Restart the server

```bash
cd IAF-Agent-Studio && python3 server.py
```

The skill appears immediately in the Skills tab. Test it from Command Centre.

---

## SKILL.md Field Reference

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique identifier — used for routing |
| `description` | Yes | One sentence — used by LLM semantic router |
| `version` | No | Semver string |
| `execution_mode` | Yes | `react` / `workflow` / `parallel` / `supervisor` |
| `tools` | Yes | List of tool names the agent may call |
| `keywords` | Yes | Routing keywords — more is better |
| `context_file` | No | Path to a single domain knowledge file loaded into the prompt at runtime |
| `approval_rules` | No | HITL approval rules for tool calls |
| `sql_mode` | No | SQL write control — defaults to `read_only` |
| `max_steps` | No | Override default orchestrator/step ceiling (default: 10) |
| `evidence_highlights` | No | Optional terms/regex rules for Evidence Viewer highlights |

### Optional Evidence Highlight Rules

Use `evidence_highlights` when a skill owns domain-specific terms that should be highlighted in Evidence Viewer documents. If the block is omitted, the platform keeps the default deterministic query/tool/response highlighting.

```yaml
evidence_highlights:
  enabled: true
  terms:
    - "AI Led Value Delivered"
  patterns:
    - name: amount
      regex: '\$\s?\d+(?:\.\d+)?\s?[KMB]?'
      reason: configured_amount
  llm_suggestions:
    enabled: false
```

Regex and term matches are accepted only when they appear in the captured evidence text. Invalid regex patterns are ignored with a warning so an authoring mistake does not fail the agent run.

---

## Part 2 — ContextOS: Domain Knowledge Files

Context files separate **knowledge** from **instructions**. Update knowledge without touching the skill prompt.

### Creating a context file

```bash
# Place in shared/contexts/
enterprise_root/tenants/company/shared/contexts/AP_Policy.md
```

Format is free-form markdown. The agent reads the full file as additional context.

### Referencing from SKILL.md

```yaml
context_file: /shared/contexts/AP_Policy.md
```

`context_file` takes a single path. The leading `/shared/` is resolved relative to `enterprise_root/tenants/{TENANT_ID}/`.

### When to use a context file vs. the skill body

| Use the skill body for | Use a context file for |
|---|---|
| Instructions, rules, persona | Reference data, policies, lookup tables |
| Tool usage guidance | Benchmarks, thresholds, SLAs |
| Formatting requirements | Org charts, system descriptions |

---

## Part 3 — Execution Modes

| Mode | When to use | SKILL.md declaration |
|---|---|---|
| `react` | Open-ended Q&A, investigation tasks | `execution_mode: react` |
| `workflow` | Fixed sequence of steps with no branching | `execution_mode: workflow` |
| `parallel` | Steps that can run concurrently (DAG) | `execution_mode: parallel` |
| `supervisor` | One skill orchestrates others | `execution_mode: supervisor` |
| `orchestrator` | Sequential chaining across 2+ skills — output of one feeds next | **Auto-selected by router** — never declare in SKILL.md |
| `planned` | Query explicitly spans 2+ unrelated business domains | **Auto-selected by router** — never declare in SKILL.md |

`orchestrator` and `planned` are decided by the router LLM using the taxonomy signal pre-signal (TaxonomySignalIndex cosine scores) injected before the routing call. No SKILL.md change triggers either mode.

Full details: `IAF-Agent-Skills/docs/execution_modes.md`

---

## Part 4 — Tools (Python)

There is **no drop-in tool registry** (no `iaf_agent_skills/tools/__init__.py` `ALL_TOOLS` list). The runtime exposes a fixed set of built-in tools, each produced by a `create_*_tool()` factory function in `IAF-Agent-Skills/iaf_agent_skills/tool_factory.py`. A skill turns tools on by naming them in its `SKILL.md` `tools:` list; there is no per-tool Python file to author for the built-ins.

### The built-in tools

| Tool name (use in SKILL.md `tools:`) | Factory in `tool_factory.py` |
|---|---|
| `shell` | `create_shell_tool` (line 47) |
| `run_sql_query` | `create_sql_tool` (line 343) |
| `write_file` | `create_write_file_tool` (line 838) |
| `query_memory` | `create_memory_tool` (line 889) |
| `invoke_skill` | `create_invoke_skill_tool` (line 1153) |
| `create_plan` | `create_create_plan_tool` (line 1256) |
| `invoke_plan` | `create_invoke_plan_tool` (line 1406) |

`request_human_approval` and `pause_in_chat` are added automatically when the skill declares them (or, for approvals, when the skill has `approval_rules`) — see `agent.py` (~lines 3245-3255).

### How a tool reaches a skill

Tool availability is the **intersection of two gates** (`iaf_agent_skills/tool_gating.py`, `tool_allowed_for_skill`, lines 50-88):

1. **Agent gate** — the tool must appear in the agent's `config.yaml` → `tools.allowed` list. A skill can never widen what the agent forbids.
2. **Skill gate** — if a `SKILL.md` declares a non-empty `tools:` list, only the tools it names are granted (strict opt-in). A skill that declares no `tools:` inherits the agent-level allowlist.

The assembly happens in `agent.py` (`_get_allowed_tools`, line 1580; tool build loop from line 3171). For `run_sql_query`, the skill's `sql_mode` (`read_only` default / `read_write`) controls whether writes are permitted (`agent.py` lines 3235-3239).

```yaml
# SKILL.md — turn on the tools this skill needs (must also be in the agent allowlist)
tools:
  - shell
  - run_sql_query
  - query_memory
```

### Adding external tools

The supported extension path for *new* capabilities is **MCP connections**, declared per skill via `mcp_tools` / `connections` in `SKILL.md` frontmatter (loaded by `loader.py`; discovered through `tools/mcp_bridge.py`). This does not require editing the engine.

### Adding a brand-new built-in tool

This is a **core-engine change, not a first-class extension point**. It means: write a new `create_<name>_tool()` factory in `tool_factory.py`, wire it into the tool-build loop in `agent.py` (around line 3171), and add its canonical name to the agent allowlist and the skill's `tools:` list. Prefer an MCP connection unless the capability genuinely belongs in the kernel.

---

## Part 5 — Hooks

Hooks are **shell commands** declared in the agent's `config.yaml` under a `hooks:` section — not Python files in a folder. They are used for circuit breakers, audit logging, PII redaction, and HITL gates. The runtime that loads and executes them is `IAF-Agent-Skills/iaf_agent_skills/hook_runner.py`.

### Hook events

| Event | When it fires | Can block? |
|---|---|---|
| `PreToolUse` | Before every tool call (synchronous) | Yes — `block_on_nonzero: true` + non-zero exit blocks the call |
| `PostToolUse` | After a tool completes (async, fire-and-forget) | No |
| `PostTurn` | Before the HTTP response is returned (synchronous) | Yes — can block/modify the response |

Event names are defined in `hook_runner.py` (lines 93-95); behaviour summary at `hook_runner.py` lines 6-8.

### Hook manifest fields

Each entry is a shell command with metadata (`ExternalHook`, `hook_runner.py` lines 485-522; parsed at lines 640-664):

```yaml
# enterprise_root/tenants/company/agents/enterprise_agent/config.yaml
hooks:
  PreToolUse:
    - command: 'echo "$IAF_TOOL_INPUT" | grep -qiE "DROP TABLE|DELETE FROM" && exit 1 || exit 0'
      matcher: run_sql_query        # regex matched against tool name (default ".*")
      skills:                       # skill-name filter — empty/omitted = all skills
        - fa_ar
      block_on_nonzero: true        # non-zero exit blocks the tool call
      timeout_seconds: 5            # on timeout: log warning and CONTINUE (default 10)
      hook_id: block_dangerous_sql

  PostToolUse:
    - command: 'echo "tenant audit: $IAF_TOOL_NAME"'
      matcher: run_sql_query
      hook_id: tenant_audit_sql
```

Key fields: `command`, `matcher` (default `.*`), `skills`, `block_on_nonzero` (default `false`), `timeout_seconds` (default 10), `hook_id`, `priority`, and — for HITL — `mode: blocking`, `fail_policy: closed`, `on_block: hitl`, and an `approval:` block. See the live `PostTurn` HITL hooks in the real `enterprise_agent/config.yaml`.

### Environment variables passed to the hook process

The command runs with these `IAF_*` env vars set (`hook_runner.py` lines 962-984):

| Variable | Value |
|---|---|
| `IAF_TOOL_NAME` | Name of the tool being called |
| `IAF_TOOL_INPUT` | Full tool input as a JSON string |
| `IAF_TOOL_OUTPUT` | Tool output (PostToolUse / PostTurn only) |
| `IAF_SKILL_NAME` | Currently active skill |
| `IAF_USER_ID` | User ID of the session |
| `IAF_AGENT_ROOT` | Absolute path to the agent's root folder |
| `IAF_SESSION_ID`, `IAF_AGENT_ID`, `IAF_TENANT_ID`, `IAF_TRACE_ID` | Session / agent / tenant / trace identifiers |

For the full hook model (all events, queue and sampling hooks, blocking-vs-observe semantics) see [DEVELOPER_QUICKSTART Part 8](../IAF-Agent-Skills/docs/DEVELOPER_QUICKSTART.md) and `docs/HOOK_EVENT_REFERENCE.md`.

---

## Part 6 — Agent Config (`config.yaml`)

An agent is a **permission wrapper**: it controls which skills a team can reach and which tools those skills may use. The config uses a nested schema (see the real `enterprise_root/tenants/company/agents/enterprise_agent/config.yaml`):

```
enterprise_root/tenants/company/agents/enterprise_agent/config.yaml
```

```yaml
agent:
  name: enterprise_agent
  description: CCD Operations Agents
  version: '1.0'

skills:
  mode: all               # all | allowlist | denylist  (allowlist/denylist add allowed:/denied: lists)

tools:
  allowed:                # agent-level tool gate — see Part 4
    - fs
    - shell
    - write_file
    - run_sql_query
    - query_memory
    - invoke_skill
    - invoke_plan
    - create_plan

audit:
  log_queries: true
  log_responses: true
  log_tool_calls: true

hooks:                    # see Part 5 — PreToolUse / PostToolUse / PostTurn
  PostToolUse:
    - command: 'echo "tenant audit: $IAF_TOOL_NAME"'
      matcher: run_sql_query
      hook_id: tenant_audit_sql
```

`tools.allowed` is the outer boundary for every skill this agent runs (`agent.py` `_get_allowed_tools`, line 1580). Model selection and persona are **not** set here — they are resolved by the model/provider layer, not agent `config.yaml`.

---

## Part 7 — Adding a Business Database

Skills can query SQLite databases via the `run_sql` tool.

```bash
# Place the database here
enterprise_root/tenants/company/shared/databases/my_data.db
```

Reference it in SKILL.md:

```yaml
tools:
  - run_sql
```

In the skill body, tell the agent the database name and key tables:

```
## Data sources
Use `run_sql` with database `my_data` for all queries.
Key tables: orders(id, customer_id, status, amount), customers(id, name, region)
```

The `run_sql` tool resolves `my_data` → `shared/databases/my_data.db` automatically.

---

## Part 8 — Testing a Skill

### Quick test from Command Centre

1. Start the server: `python3 server.py`
2. Open `http://localhost:8080`
3. Type a query that should route to your skill
4. Check the skill badge in the response header — confirms routing worked
5. Check the tool call trace (expand the response) — confirms tools fired correctly

### Unit-testing a skill in isolation

```python
import asyncio
from iaf_agent_skills.agent import SkillAgent

async def test_skill():
    agent = SkillAgent()
    result = await agent.run(
        query="What is the payment status for PO-1234?",
        skill_name="invoice_ops",
        session_id="test-session-001"
    )
    print(result["answer"])
    assert "PO-1234" in result["answer"]

asyncio.run(test_skill())
```

---

## Part 9 — Project Layout for Developers

```
IAF_AgentOS/
├── IAF-Agent-Skills/          # Core engine (Python package)
│   ├── iaf_agent_skills/
│   │   ├── agent.py           # SkillAgent — LangGraph ReAct executor
│   │   ├── router.py          # SkillRouter — keyword + semantic routing
│   │   ├── loader.py          # SkillLoader — SKILL.md parser
│   │   ├── planner.py         # PlannerEngine — cross-domain DAG planner
│   │   ├── memory.py          # Agent memory (Redis + markdown)
│   │   ├── hook_runner.py     # Pre/post-step hook executor
│   │   ├── self_evolution.py  # Self-evolution engine (Tier 1–4)
│   │   ├── taxonomy_signal_index.py  # L5 taxonomy vector index — feeds process signal into router
│   │   ├── entity_guide_seeder.py    # Background entity seeder with fragment dedup
│   │   ├── scheduler/         # Cron engine (Redis-backed)
│   │   └── tools/             # All tool implementations
│   └── docs/                  # Deep-dive: execution modes, memory schema, etc.
│
├── IAF-Agent-Studio/          # Web server + UI
│   ├── server.py              # FastAPI app entry point
│   ├── routers/               # API endpoints (chat, skills, queue, cron, auth…)
│   ├── context_graph_builder.py  # Context tree builder for Studio context map view
│   ├── shared/
│   │   ├── config.py          # All env vars — single source of truth
│   │   ├── state.py           # Singleton: agent, router, scheduler, Redis
│   │   └── models.py          # Pydantic request/response models
│   ├── static/                # Dashboard UI (Alpine.js)
│   └── docs/                  # API reference, WebSocket protocol
│
├── agent_os/                  # SafeKernel — sandboxed shell + code execution
│   └── docs/                  # Kernel internals, tools reference
│
├── enterprise_root/           # Tenant data — customer-specific, never shipped
│   └── tenants/company/
│       ├── agents/            # Agent config.yaml
│       ├── skills/            # SKILL.md files + _index.yaml
│       └── shared/            # contexts/, hooks/, databases/, memory/
│
└── docs/                      # This folder — top-level guides
    ├── 03_architecture.md
    ├── DEPLOYMENT_GUIDE.md
    └── DEVELOPER_GUIDE.md     # ← you are here
```

---

## Part 10 — Useful References

| Document | Location | What's in it |
|---|---|---|
| Execution modes deep-dive | `IAF-Agent-Skills/docs/execution_modes.md` | workflow/parallel/supervisor examples |
| Memory schema | `IAF-Agent-Skills/docs/memory_schema.md` | Redis key layout, markdown memory format |
| API reference | `IAF-Agent-Studio/docs/api_reference.md` | All REST endpoints, request/response shapes |
| WebSocket protocol | `IAF-Agent-Studio/docs/websocket_protocol.md` | Event types, streaming format |
| Skill authoring guide | `docs/04_skill_authoring.md` | SKILL.md field-by-field walkthrough |
| Auth and users | `docs/07_auth_and_users.md` | JWT setup, user profiles, HITL |
| HITL design guide | `docs/HITL_DESIGN_GUIDE.md` | All 4 HITL mechanisms, approvals tab, queue monitor, decision guide |
| Kernel internals | `agent_os/docs/kernel_internals.md` | Sandbox, path resolution, tool execution |

---

## Part 11 — Common Issues & Known Gotchas

### Redis AOF not enabled — state lost on restart

**Symptom:** Agent memory and cron jobs disappear after Redis restarts.

**Fix:** Enable AOF persistence in `redis.conf`:
```
appendonly yes
appendfsync everysec
```
Or start Redis with: `redis-server --appendonly yes`

**Never run `redis-cli flushall`** — it wipes users, sessions, and cron jobs permanently.

---

### SafeKernel heredoc failure — `python3 - << 'EOF'` not supported

**Symptom:** Evidence text shows `Error [PYTHON3]: ...` or a Python traceback as the excerpt.

**Cause:** SafeKernel treats `-` in `python3 -` as a literal filename, not stdin. Heredoc stdin redirection is not supported.

**Fix:** Always use `python3 -c "..."` for inline Python in tool calls:
```bash
# ✗ broken
python3 - << 'EOF'
...
EOF

# ✓ correct
python3 -c "import json; print(json.dumps({'key': 'value'}))"
```

---

### Orchestrator called for simple queries — fails with JSON parse error

**Symptom:** Log shows `Router complexity: multi_step → mode_hint: orchestrator` for a simple document read, then `❌ Orchestrator failed: Manager LLM returned unparseable response: Extra data`.

**Cause:** The router over-scores queries with a file path + analytical question as `multi_step`. The manager LLM also sometimes appends commentary after the JSON response.

**Status:** JSON parse robustness fixed in `execution.py` (`raw_decode` instead of `json.loads`). Router threshold tuning is ongoing.

**Workaround:** Rephrase the query to be more direct (e.g. "read this PDF and find X" rather than "analyse document at path...").

---

### Agent loses conversation context mid-session

**Symptom:** Agent responds as if starting fresh after a few turns — asks for information already provided.

**Cause (fixed):** `loadConversations()` in the frontend was overwriting `currentSessionId` after every message poll, routing subsequent messages to a fresh session clone with only the last 2 Redis-persisted turns.

**Fix applied:** `index.html` — `loadConversations()` now only sets `currentSessionId` when it is null (first load), never overwrites an established session.

---

### MCP DirectAdapter TaskGroup error on startup

**Symptom:** Log shows `DirectAdapter: failed to get tools — unhandled errors in a TaskGroup (1 sub-exception)` on first query.

**Cause:** One or more MCP server processes defined in config failed to start (missing binary, wrong path, network issue).

**Fix:** Check which MCP servers are configured in `config.env` or `config.yaml` and verify they are reachable. The error is non-fatal — the agent continues without those tools.

---

### State restoration race condition — first message has no history

**Symptom:** On a cold server start, the first message in an existing conversation gets no prior history, even though Redis has it.

**Cause:** `get_or_create()` in `state.py` fires `asyncio.create_task(_restore_state_async(...))` without awaiting — state loads after `agent.run()` has already started.

**Workaround:** Use `get_or_create_async()` from async call sites to await full state restoration before the first run. The sync path is a known limitation.

---

### PDF preview blank / white screen

**Symptom:** Evidence Rendered tab shows blank white area.

**Cause:** Previous PDF.js canvas approach had private field errors (`this.#d`, `this.#o`) across multiple versions.

**Fix applied:** Switched to native `<iframe>` with blob URL as the primary render approach. PDF.js is only loaded on demand for the optional Highlight View mode. If you see a blank native iframe, the content URL fetch likely failed — check browser console for a 401/403.

---

### Server startup fails — port already in use

```bash
lsof -ti:8081 | xargs kill -9 2>/dev/null
python3 server.py
```

---

## Repo Layout and Optional Modules

The harness separates core runtime from optional accelerators:

| Path | Role |
|---|---|
| `IAF-Agent-Studio/` | Full-product server, routers, core static UI |
| `IAF-Agent-Skills/` | Engine runtime plus composable slices (`agentos_contracts`, `agentos_model`, `agentos_engine`) |
| `agent_os/` | SafeKernel (`agentos-kernel`) |
| `enterprise_root/` | Canonical installed skills, workstreams, policies, tenant data |
| `solution_modules/` | Optional domain accelerators such as IRIS Finance Intelligence |
| `scripts/verification/` | Ad-hoc live smoke and security verification scripts |
| `docs/generated/` | Ignored generated HTML review artifacts |

Installed skills and workstreams stay in `enterprise_root` only. Solution modules
reference those assets instead of duplicating them. See
[SOLUTION_MODULES.md](SOLUTION_MODULES.md).

For selective adoption of kernel, engine, or provider layers, see
[COMPOSABLE_ADOPTION_SPEC.md](COMPOSABLE_ADOPTION_SPEC.md) and
[PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md).

For ad-hoc verification after server restart, see
[scripts/verification/README.md](../scripts/verification/README.md).
