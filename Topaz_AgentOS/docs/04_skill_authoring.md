# IAF AgentPro — Skill Authoring Guide

## What Is a Skill?

A skill is a SKILL.md file that defines an agent capability. It contains:
- Frontmatter (YAML) — machine-readable configuration
- Prompt body — the system prompt injected when this skill handles a query

Skills live at `IAF-Agent-Skills/skills/{skill_name}/SKILL.md`.
Tenant-specific enterprise skills can also live under
`enterprise_root/tenants/{tenant_id}/skills/{skill_name}/SKILL.md` when the
server is configured to load tenant skills.

Internally, loaded skills use the stable `agentos_contracts.Skill` descriptor.
The legacy import `iaf_agent_skills.loader.Skill` still re-exports that type, so
existing skill tooling and tests continue to work.

---

## SKILL.md Structure

```markdown
---
name: my_skill
description: "Handles queries about my business domain"
version: "1.0"
execution_mode: react
keywords:
  - my-domain
  - my-query-type
  - another-keyword
tools:
  - shell
  - run_sql_query
  - query_memory
context_file: /shared/contexts/my_domain_context.md
category: Finance
status: active
---

You are an expert assistant for [your domain].

## Your Responsibilities
- Answer questions about [topic A]
- Investigate [topic B] using the available tools
- Escalate to humans when approval is needed

## How to Use Tools
When querying data, use `run_sql_query` for structured queries and `shell` with grep for searching context files.

Always call `query_memory` before answering questions about specific vendors or entities.

## Response Format
- Lead with the key finding
- Include supporting data
- End with recommended next step
```

---

## Frontmatter Fields

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | Unique skill identifier (lowercase, underscores) |
| `description` | ✅ | One-line description (shown in UI) |
| `version` | ✅ | Semantic version (e.g., `"1.0"`) |
| `execution_mode` | ✅ | `react`, `workflow`, `parallel`, `supervisor` |
| `keywords` | ✅ | List of routing keywords (used by router to match queries) |
| `tools` | ✅ | List of permitted tools |
| `context_file` | optional | Virtual path to context markdown injected as additional context |
| `category` | optional | UI grouping label |
| `status` | optional | `active`, `draft`, `deprecated` |
| `scope` | optional | `personal` — marks skill as user-private (not in shared library) |
| `steps` | workflow/parallel only | Execution steps (see Execution Modes) |
| `worker_skills` | supervisor only | Worker skill names |

---

## Execution Modes

Router-selected dynamic orchestration is a runtime behavior, not a SKILL.md
field. Operators can temporarily set `DYNAMIC_ORCHESTRATOR_ENABLED=false` to
make multi-step mode hints use ReAct. This does not alter a skill's declared
execution mode.

### `react` — Default

LangGraph ReAct loop: reason → call tool → observe → repeat. Best for open-ended queries.

```yaml
execution_mode: react
tools: [shell, run_sql_query, query_memory, invoke_skill]
```

The agent decides which tools to call based on intermediate results. Suitable for any investigative or analytical task.

### `workflow` — Deterministic Steps

Fixed sequence of steps. Best for repeatable, auditable processes.

```yaml
execution_mode: workflow
steps:
  - name: fetch_data
    action: shell
    params:
      command: "sqlite3 /shared/databases/ap_regular.db 'SELECT * FROM invoices WHERE status=\"pending\"'"

  - name: summarize
    action: skill
    skill: general
    task: "Summarize these pending invoices: {{fetch_data.output}}"

  - name: save_report
    action: shell
    params:
      command: "echo '{{summarize.output}}' > /workspace/pending_report.md"
```

Template variables: `{{step_name.output}}` references a previous step's output.
For `action: skill` steps, the child skill's runtime progress and tool callbacks
are forwarded with the parent workflow step name. In Workstream Detail this
appears in the `Execution Trace` tab as the workflow step plus the child
context/API/SQL/tool activity, and the completed run is saved as structured
`execution_ledger[].steps` history.

Do not use `execution_mode: workflow` for a pure script pipeline that must avoid
LLM involvement. Use a Deterministic Automation instead; Automations live under
`enterprise_root/tenants/<tenant_id>/automations/`, allow only `shell`,
`python`, and `condition`, and reject `skill` steps. See
`docs/DETERMINISTIC_AUTOMATIONS.md`.

**Conditional branching:**

```yaml
  - name: check_amount
    action: condition
    if: "{{fetch_invoice.output}}"
    contains: "amount > 100000"
    then: require_approval
    else: auto_process
```

### `parallel` — Concurrent DAG

Steps run concurrently unless they declare `depends_on`. Best for dashboard-style data gathering.

```yaml
execution_mode: parallel
steps:
  - name: get_ar
    action: skill
    skill: ar_ops
    task: "Get AR aging summary"

  - name: get_ap
    action: skill
    skill: invoice
    task: "Get AP open balance"

  - name: combine
    action: skill
    skill: general
    task: "Combine: AR={{get_ar.output}}, AP={{get_ap.output}}"
    depends_on: [get_ar, get_ap]
```

### `supervisor` — Multi-Agent Orchestration

A meta-agent delegates to worker skills and synthesises results. Best for complex multi-domain queries.

```yaml
execution_mode: supervisor
worker_skills:
  - name: ar_ops
    task: "Summarise overdue AR above 90 days"
  - name: invoice
    task: "List invoices pending approval"
  - name: general
    # task omitted → receives the original user query
```

---

## Routing Keywords

Keywords are the primary routing signal. The router matches the user's query against all skills' keyword lists using:

1. Exact keyword match (highest confidence)
2. Semantic similarity to keyword (with embeddings)
3. Entity + process signal from Entity Registry

**Good keywords:**
```yaml
keywords:
  - overdue invoice
  - accounts receivable
  - ar aging
  - payment dispute
  - collections
  - vendor payment
```

**Bad keywords (too generic):**
```yaml
keywords:
  - report
  - data
  - help
  - query
```

Include synonyms, abbreviations, and domain-specific terms. The router handles case-insensitively.

---

## Tools Reference

| Tool | What It Does | When To Use |
|---|---|---|
| `shell` | Execute Unix commands in the sandboxed kernel | File operations, grep, data exploration |
| `run_sql_query` | Execute SQL against shared databases | Structured data queries |
| `query_memory` | Search the agent's knowledge records | Before answering about specific entities |
| `invoke_skill` | Delegate to another skill | When a sub-task belongs to a different domain |
| `write_file` | Write structured content to a file | Reports, summaries, generated docs |
| `request_human_approval` | Pause and wait for human decision; the trace closes as `awaiting_human` with token/cost totals | High-value actions, policy-required approvals |

---

## Context Files

The `context_file` field injects additional markdown into the skill's system prompt at runtime. It is loaded from the virtual path at each invocation.

```yaml
context_file: /shared/contexts/p2p_context.md
```

Skills can also point at a convention-discovered Knowledge Bundle entry point:

```yaml
context_file: /shared/knowledge/finance_ap/index.md
```

Use a Knowledge Bundle when the domain needs a maintained wiki of linked
runbooks, policies, table notes, metrics, and APIs. The platform discovers
bundles under `/shared/knowledge/*/` when they contain `manifest.yaml` with
`kind: knowledge_bundle` and an `index.md`. Confirmed learning records can be
mirrored into matched bundle pages by skill or tags after approval.

This is the primary mechanism for skill customisation without prompt changes:
- Update the context file to change business rules
- No code deployment required
- Changes take effect immediately

Good candidates for context file content:
- Vendor-specific rules and exceptions
- Database schema descriptions
- Business process descriptions
- SLAs and escalation policies
- Known workarounds

---

## Writing Effective Prompts

### Structure

```markdown
You are an expert at [domain]. Your job is to [primary purpose].

## Your Responsibilities
- [Responsibility 1]
- [Responsibility 2]

## How to Use Tools
[Specific guidance on which tools to use and when]

## Response Format
[Expected output structure]

## Important Rules
[Hard constraints: don't do X, always check Y first, escalate when Z]
```

### Prompt Writing Tips

**Be specific about tool usage:**
```markdown
# Good
When asked about vendor payment terms, always:
1. Call `query_memory` with the vendor name first
2. If no knowledge record exists, grep /shared/contexts/p2p_context.md
3. If still not found, say "No payment terms on record for this vendor"

# Bad
Use tools to find information.
```

**Define output format explicitly:**
```markdown
Always respond in this format:
**Finding:** [one-line summary]
**Supporting Data:** [table or list]
**Recommended Action:** [specific next step]
```

**Specify escalation triggers:**
```markdown
Use `request_human_approval` when:
- Invoice amount exceeds $100,000
- Vendor is flagged in the blocklist
- User explicitly asks for manager review
```

**Reference memory for continuity:**
```markdown
Before answering questions about specific vendors or customers, always call 
`query_memory` to check if there are any known rules, exceptions, or corrections 
for that entity. Use what you find to inform your response.
```

---

## Custom Tool Scripts

> **Untrusted multi-tenant note:** custom tool scripts run as subprocesses under the server-process
> user. When `AGENTOS_UNTRUSTED_EXECUTION_GUARD=true` (shared/SaaS deployments), bundled tool
> scripts in **personal** skills (under `.../agents/<agent>/users/<user>/skills/...`) are **not
> loaded** — only trusted global/promoted (admin-reviewed) skills may ship executable tool
> scripts. With the guard off (default, trusted single-tenant) all skills load their scripts.

Skills can define custom Python tools by adding `tool_scripts` to the frontmatter and uploading `.py` files via the Skill Builder:

```yaml
tool_scripts:
  - filename: calculate_dso.py
    description: "Calculate Days Sales Outstanding for a customer"
```

The tool script must follow the LangChain `@tool` decorator pattern:

```python
from langchain_core.tools import tool

@tool
def calculate_dso(customer_id: str) -> str:
    """Calculate Days Sales Outstanding for a customer.
    
    Args:
        customer_id: Customer identifier (e.g., CUST-001)
    
    Returns:
        DSO value with supporting invoice data
    """
    # Implementation here
    return f"DSO for {customer_id}: 45 days"
```

## Skill-Local UI Components

A skill can include an adjacent `component.html` file when a chat surface needs
to render an editable form for a governed action. For example:

```text
enterprise_root/tenants/company/skills/send_email/
  SKILL.md
  component.html
```

The skill response should emit a fenced `skill_component` block with the skill
name and draft props. The chat UI loads `component.html` through
`GET /api/skills/{skill_name}/component`, fills the draft fields, and handles the
final button click with user confirmation before calling the backend connector.
Do not add `request_human_approval` or `approval_rules` to draft-only component
skills when the intended UX is to show the editable form first; those settings
pause the agent before the component can be rendered.

### Multiple components per skill

A skill can ship more than one UI component. The default lives at the skill root
as `component.html` (component id `component`); additional named components live
under `components/<id>.html`:

```text
  SKILL.md
  component.html            # default (id: "component")
  components/
    approval.html           # id: "approval"
    summary.html            # id: "summary"
```

- **Select one at runtime** by adding a `component` key to the emitted block:
  ```skill_component
  {"skill": "ap_ops", "component": "approval", "props": { ... }}
  ```
  Omitting `component` (or using `component`/`default`) renders `component.html`.
- **APIs** take an optional `?name=<id>` on `GET /api/skills/{skill}/component`,
  `GET`/`PUT /api/skills/{skill}/component-source`, and
  `POST /api/skills/{skill}/component-draft`. `GET /api/skills/{skill}/components`
  lists every component the skill ships. Component ids must match
  `^[A-Za-z0-9_-]{1,64}$` and resolve only inside the skill folder.
- **Skill Builder** has a component selector (chips for existing components + a
  name field to create a new one); the runtime path label shows where it saves.
- Chat rendering in the main chat honors the `component` key today; the workstream
  chat surfaces still render the default `component.html` (frontend consolidation
  is a follow-up).

---

## Hooks

Hooks run shell commands or Python scripts at specific lifecycle points:

```yaml
hooks:
  pre_tool_use:
    - shell: "echo 'tool call started' >> /me/tool_log.txt"
  post_turn:
    - shell: "python3 /shared/hooks/audit_turn.py"
```

Hook lifecycle:
- `pre_tool_use` — runs before each tool call (blocking — can cancel the call)
- `post_tool_use` — runs after each tool call (async)
- `post_turn` — runs after each conversation turn (blocking/modifying)

Blocking hooks can either deny or request approval. Add `on_block: hitl` when a
policy block should create a normal HITL checkpoint; omit it or set
`on_block: deny` when the response/tool should simply be blocked. The optional
`approval` object controls `urgency`, `options`, and `sla_minutes`:

```yaml
hooks:
  PostTurn:
  - command: python3 $IAF_AGENT_ROOT/../../shared/hooks/high_value_gate.py
    mode: blocking
    block_on_nonzero: true
    on_block: hitl
    approval:
      urgency: high
      options: [Approve, Reject]
      sla_minutes: 60
```

This works across chat, cron, queue, and Mission Mode surfaces that persist
`agent.approval_pending`. Workstream items still only stamp approvals whose
context matches the current workstream and item.
- `post_sampling` — runs after LLM sampling (async)

---

## Testing Your Skill

**In the Skill Builder:**
1. Click the **Test** tab
2. Enter a representative query
3. Observe skill selection, tool calls, and response

**Via API:**
```http
POST /api/skills/{skill_name}/test
Content-Type: application/json

{
  "query": "Your test query",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

**Tips:**
- Test with your most common query patterns
- Test with edge cases (missing data, ambiguous requests)
- Check that keywords route correctly via the routing panel
- Verify context file content is injected (check the trace for `context_used.data_sources`)

---

## Skill Status Lifecycle

```
draft → active → deprecated
```

- **`draft`** — Skill is saved but not included in routing
- **`active`** — Skill is live and routed to normally
- **`deprecated`** — Skill is excluded from routing but preserved for history

Change status in the Skill Builder or via:
```http
PATCH /api/skills/{skill_name}/status
{"status": "active"}
```

## Saving in the Designer: Global vs Personal Draft

When you save a skill in the Designer / Skill Builder, choose a **save scope**:

- **🌐 Global (all users)** — publishes a live global skill immediately visible to
  **all users and tenants**. There is no separate draft copy. Because the blast
  radius is large, a global save shows an explicit confirmation naming the impact
  before it is written. Admins only.
- **📝 Personal draft** — saves to your private personal-skills path. It stays
  visible only to you, does **not** change the live global skill, and can later be
  promoted via **Submit for Review**. Available to admins and non-admin authors.

Non-admin authors always save as a personal draft. Admins default to the scope
selector next to the **Save** button; a normal save never publishes globally
without the confirmation step, so there is no accidental global publish.


---

## Personal Skills

Non-admin users can create skills that are private to them, stored at `/api/personal-skills/{user_id}/` rather than the shared `IAF-Agent-Skills/skills/` directory.

### Creating a Personal Skill

Add `scope: personal` to the frontmatter:

```yaml
---
name: my_daily_review
description: "Reads my day log and summarises wins and carry-forwards"
version: "1.0"
execution_mode: workflow
scope: personal
keywords:
  - daily review
  - my day
  - end of day summary
tools:
  - shell
---
```

Personal skills:
- Are saved to the user's private path, not the shared skills library
- Appear in the Skill Builder with a **personal** badge
- Are visible only in the creating user's personal agent skill dropdown
- Are not routed to for other users or the enterprise agent

### Promoting a Personal Skill to Shared

Submit via the **Submit for Review** button in the Skill Builder. An admin reviews and copies it to the shared skills library. On approval you are recorded as the skill's owner, so you can still edit it from Designer Studio.

### Personal Skills and the `/local` Path

Personal workflow skills often read from `/local/` — the user's local folder mount:

```yaml
steps:
  - name: gather_logs
    action: shell
    params:
      command: "ls /local/"

  - name: read_log
    action: shell
    params:
      command: "cat /local/my_day_{{today}}.md"

  - name: summarize
    action: skill
    skill: general
    task: "Summarise my day log: {{read_log.output}}"
```

Set up the `/local` mount in the Skill Builder sidebar before using `/local/` paths.
