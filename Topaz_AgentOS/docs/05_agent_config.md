# IAF AgentPro — Agent Configuration

## What Is an Agent?

An agent is a configuration boundary. It determines:
- Which skills are available to users
- Which tools the skills can call
- What MCP servers are connected
- What hooks run during execution
- Where memory is stored

Multiple agents can coexist in a tenant, each with different permissions and capabilities. For example:
- `enterprise_agent` — full access to all skills and tools
- `ap_regular` — scoped to Accounts Payable skills only
- `gbs_agent_fa` — Finance & Accounting domain only

Designer Studio's Agent Config and Context Explorer surfaces can be used in dark,
hybrid, or light visual themes; hybrid/light hover states are kept on light
surfaces so labels remain readable.
The Skills editor's Capabilities accordion section also includes a Component
sub-section for skill-local `component.html` files; those chat cards are part
of the skill package and do not change the selected agent's `config.yaml`.
Designer Studio also has an Automations page for tenant-level no-LLM pipelines.
Those definitions live under `enterprise_root/tenants/{tenant_id}/automations/`
and are not part of an agent's `config.yaml` allowlist/denylist.

---

## Runtime Feature Flags

These process environment variables change agent runtime behavior without
changing an individual agent's `config.yaml`:

- `MODEL_CALL_PIPELINE_ENABLED` — default `false`. When `true`, `SkillAgent`
  wraps the primary chat model with `PolicyChatModel` so each LangGraph/native
  ReAct provider call passes through ordered `BeforeModelCall`,
  `AroundModelCall`, and `AfterModelCall` in-process hooks before tool-call
  parsing. Active `AfterModelCall` central policies with `decision: redact` are
  loaded from `security/policy_control.yaml` for the current tenant/agent.
- `RL_CAPTURE` — default `false`. When `true`, neutral capture events emitted
  through `iaf_agent_skills.capture_events` are projected best-effort into
  `enterprise_root/tenants/{tenant}/shared/databases/rl.db` using the
  framework-neutral `rl_capture` schema. The bridge covers completed chat turns,
  incremental model calls, tool calls/observations, feedback, HITL, queue,
  workstream, hook, and evaluator outcomes without requiring runtime modules to
  import RL schema types directly.
- `RL_REDACT` — default `true`. Redacts secret-looking keys, authorization
  headers, bearer/basic tokens, and email-like text before RL/eval records are
  persisted.
- RL/eval exporters materialize only usable rows for the selected training or
  replay format. For Eval JSONL, metadata-only captures with no task, message,
  or output text are skipped before the shared export quality gate.
- `RL_CAPTURE_REASONING` — default `false`. Reserved for explicit reasoning
  capture controls; the current slice stores only available reasoning metadata
  and references.
- `RL_DB_PATH` — optional custom SQLite path for RL/eval capture. When unset,
  the tenant-scoped `rl.db` path is used.
- `TRACE_VALUE_ROUTER_ENABLED` — default `false`. When true, successful completed
  RL captures schedule advisory Trace Value assessment through the tenant
  `trace_value_router` skill. Manual `/api/trace-value/evaluate` backfill remains
  available even when automatic scheduling is disabled.
- `TRACE_VALUE_ROUTER_SKILL`, `TRACE_VALUE_ROUTER_BATCH_LIMIT`,
  `TRACE_VALUE_ROUTER_RETRY_LIMIT`, and
  `TRACE_VALUE_ROUTER_MAX_EVIDENCE_CHARS` control the skill name, batch size,
  retry count, and bounded evidence packet sent to the router skill.
- `SKILL_PROVIDER`, `ROUTER_PROVIDER`, `TOOL_PROVIDER`, `HOOK_PROVIDER`, and
  `TRACE_PROVIDER` — default `default`. Runtime provider slots for partner
  skills registries, routers, tool catalogs, hook engines, and observability.
  Custom values use `module:Class` import paths; see
  `docs/PROVIDER_ARCHITECTURE.md`.
- `JWT_SECRET`, `JWT_ALGORITHM`, and `TENANT_ID` — used by the Studio auth layer
  and exported at boot for `agent_os.self_auth`, so lower-level kernel code can
  mint short-lived service JWTs for agent self-calls without importing Studio
  modules. Set `JWT_SECRET` explicitly in production so service tokens survive
  restart.

---

## Agent Configuration (YAML)

Agent configuration is stored as YAML at `enterprise_root/tenants/{tenant_id}/agents/{agent_id}/config.yaml`.

```yaml
name: enterprise_agent
description: "Full-access enterprise orchestrator for Finance & Accounting and IT Operations"
skills_mode: all          # all | allowlist | denylist
skills_list: []           # Used when skills_mode = allowlist or denylist
tools_allowed:
  - shell
  - run_sql_query
  - write_file
  - query_memory
  - invoke_skill
  - request_human_approval
mcp_connections: []
hooks: {}
```

### `skills_mode`

| Value | Behaviour |
|---|---|
| `all` | All active skills available |
| `allowlist` | Only skills named in `skills_list` |
| `denylist` | All skills except those named in `skills_list` |

### `tools_allowed`

Restricts which tools skills can call within this agent. Even if a SKILL.md declares `tools: [shell, run_sql_query]`, if `run_sql_query` is not in the agent's `tools_allowed`, it is blocked.

Available tools:
- `shell` — SafeKernel shell commands
- `run_sql_query` — SQL against shared databases
- `write_file` — Direct file writing (bypasses shell parsing)
- `query_memory` — Knowledge record search

Tool execution uses the configured AgentOS kernel runtime. The default
`AGENTOS_KERNEL_BACKEND=local` runs `SafeKernel` in-process. With
`AGENTOS_KERNEL_BACKEND=remote`, `shell` and `write_file` calls are sent to the
signed kernel worker while preserving the same virtual paths and command
behavior.
- `invoke_skill` — Delegate to another skill
- `request_human_approval` — HITL pause

---

## Managing Agents via UI

Open [http://localhost:8080/skill-builder/v2](http://localhost:8080/skill-builder/v2) and click **Agent Config** in the sidebar.
The Skill Builder sidebar includes a **Theme** selector for Dark, Hybrid, and
Light visual modes; this affects the designer presentation only, not agent
configuration values.
The **Ask Twin** button can answer questions using the active Agent Config tab,
current draft agent name, skills mode, selected skills/tools, and MCP connection
count when that state is visible in the UI.

### Creating an Agent

1. Click **+ New Agent**
2. Fill in:
   - **Name** — lowercase, underscores only
   - **Description** — shown in the agent selector
   - **Skills Mode** — usually `all` for a general agent
   - **Tools Allowed** — select from the tool checklist
3. Click **Save**

### Editing an Agent

Select an agent from the list, modify any field, click **Save**.

### Deleting an Agent

Select the agent → click **Delete**. The agent directory is moved to the recyclebin (not permanently deleted).

---

## Managing Agents via API

### Create

```http
POST /api/agents
Content-Type: application/json

{
  "name": "finance_agent",
  "description": "Finance-only agent for AP/AR tasks",
  "skills_mode": "allowlist",
  "skills_list": ["ar_ops", "invoice", "invoice_dbs", "ap_account_maintenance"],
  "tools_allowed": ["shell", "run_sql_query", "query_memory"],
  "mcp_connections": [],
  "hooks": {}
}
```

### Update

```http
PUT /api/agents/finance_agent
{"skills_mode": "all", "tools_allowed": ["shell", "run_sql_query", "write_file", "query_memory"]}
```

### List

```http
GET /api/agents?tenant_id=company
```

### Delete

```http
DELETE /api/agents/finance_agent?tenant_id=company
```

---

## Hooks

Hooks run shell or Python scripts at specific lifecycle points. They are configured per-agent in the `hooks` field.

### Hook Types

| Hook | When | Blocking? | Can modify? |
|---|---|---|---|
| `pre_tool_use` | Before each tool call | Yes | Can cancel the call |
| `post_tool_use` | After each tool call | No | No |
| `post_turn` | After each conversation turn | Yes | Can modify response |
| `post_sampling` | After LLM sampling | No | No |

### Hook Configuration

```yaml
hooks:
  pre_tool_use:
    - shell: "echo '{{tool_name}} called at {{timestamp}}' >> /me/tool_log.txt"
  post_turn:
    - shell: "python3 /shared/hooks/audit_turn.py"
  post_tool_use:
    - shell: "grep -c 'error' /me/tool_log.txt > /dev/null || true"
```

Hook scripts run through the configured SafeKernel runtime and have access to
the same virtual paths. In remote-kernel mode, the worker process owns the real
kernel execution boundary.

### Hook Scripts

Pre-built hooks in `enterprise_root/tenants/company/shared/hooks/`:

| Script | Purpose |
|---|---|
| `ccdops_audit.py` | Logs CCD Kubernetes operations |
| `ccdops_alert_oom.py` | Alert on out-of-memory signals |
| `ccdops_block_writes.py` | Block write operations for safety |
| `ccdops_disclaimer.sh` | Append legal disclaimer on CCD ops |

---

## MCP Connections

MCP (Model Context Protocol) connections allow agents to call external tools served by MCP servers.

### Direct Connection (stdio/HTTP)

```yaml
mcp_connections:
  - type: direct
    transport: stdio
    command: "python3"
    args: ["/tools/my_mcp_server.py"]
    env:
      API_KEY: "${MY_API_KEY}"
```

### Registry Connection (REST proxy)

```yaml
mcp_connections:
  - type: registry
    registry_url: "http://mcp-registry:8090"
    server_id: "my_mcp_server"
    api_key: "${MCP_REGISTRY_KEY}"
```

MCP-provided tools appear in the agent's tool list alongside built-in tools and are callable from any skill.

---

## Multi-Agent Patterns

### Specialist + Orchestrator

```
enterprise_agent (orchestrator)
  → invoke_skill("ar_ops")    → ar_regular (AR specialist)
  → invoke_skill("invoice")   → ap_regular (AP specialist)
```

The orchestrator has `skills_mode: all` and can `invoke_skill` to delegate to any specialist. Specialists have narrower `skills_list` and `tools_allowed`.

This agent access pattern is separate from automatic dynamic orchestration.
Setting `DYNAMIC_ORCHESTRATOR_ENABLED=false` makes router-selected multi-step
chat requests use ReAct while preserving agent skill allowlists, `invoke_skill`,
and Planned mode.

### Domain Isolation

```
finance_agent:
  skills_mode: allowlist
  skills_list: [ar_ops, invoice, invoice_dbs, p2p_consultant]
  tools_allowed: [shell, run_sql_query, query_memory]

itops_agent:
  skills_mode: allowlist
  skills_list: [it_helpdesk, itops_rca, ccdops]
  tools_allowed: [shell, run_sql_query, query_memory, request_human_approval]
```

Users connect to the agent appropriate for their domain. No cross-domain data leakage.

---

## Personal Agents

A personal agent is a per-user agent scoped to a specific person's needs — their personal productivity skills, local file access, and private memory partition. Personal agents are isolated from the enterprise agent's memory and skills.

### Creating a Personal Agent

```yaml
# enterprise_root/tenants/company/agents/my_personal_agent/config.yaml
name: my_personal_agent
description: "Personal agent for Madhan — daily reviews, meeting prep, personal queries"
skills_mode: allowlist
skills_list:
  - mu_weekly_review
  - my_meeting_prep
  - general
tools_allowed:
  - shell
  - write_file
  - query_memory
  - invoke_skill
mcp_connections: []
hooks: {}
```

### Personal Agent Design Considerations

**Use `allowlist` mode, not `all`**

Setting `skills_mode: all` gives the personal agent access to every enterprise skill (AR, AP, IT Ops, etc.). This clutters the skill dropdown and may route personal queries to the wrong skill. Use `allowlist` and explicitly name only the skills the user needs.

**Memory is per-agent**

Each agent has its own memory partition — knowledge confirmed under `my_personal_agent` is not visible when using `enterprise_agent` and vice versa. Preferences, entity records, and context files are all scoped to the agent.

**Skill selection resets on agent switch**

When a user switches agents in the chat UI, the sticky skill selector resets to **Auto** routing. This prevents skills from the previous agent being silently applied to the new agent where they may not exist.

**Personal skills are automatically available**

Skills with `scope: personal` that belong to the user are merged into the agent's skill list at runtime. You do not need to add them to `skills_list` manually — they appear automatically for the owning user.

---

## Default Configuration

The default tenant ships with three agents:

| Agent | Mode | Skills | Purpose |
|---|---|---|---|
| `enterprise_agent` | `all` | 34 skills | Full-access orchestrator |
| `finance_agents` | `allowlist` | 65 synced BP finance skills | Finance Agents pack (`bp-finance-skills`) |
| `ap_regular` | `allowlist` | AP-focused skills | Accounts Payable specialist |
| `gbs_agent_fa` | `allowlist` | F&A skills | Finance & Accounting domain |

For most deployments, `enterprise_agent` is the primary user-facing agent.

Agent YAML remains part of the tenant backup inventory. The enterprise Recovery
Readiness verifier inventories restored `agents/<agent_id>/config.yaml` and
related memory files from an isolated `RECOVERY_VERIFICATION_ROOT`; it does not
load or execute the restored agent configuration.

## Enterprise runtime profile

Agent definitions remain tenant-scoped and unchanged by the P0 deployment
split. Production process/security settings belong in the deployment
environment, starting from `agent_os/config.enterprise.env.example`; do not put
queue keys, queue claim backend settings, signing secrets, CORS origins, or
runtime roles in agent YAML.
