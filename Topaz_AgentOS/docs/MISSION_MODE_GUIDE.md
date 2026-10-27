# Mission Mode — Workstreams Guide

Mission Mode lets you turn a multi-item backlog into an autonomous,
auditable, human-overridable workstream that runs across many cron
iterations. A cron tick advances the workstream by its configured
`batch_size` and `parallelism` limits. The platform owns the loop; you
author the backlog as YAML or click through a wizard.

This guide covers:
1. The mental model
2. How to create a workstream (UI + API + script)
3. The 3 Mission Mode hook events
4. How HITL approval flows in
5. How evidence rolls up per item and per workstream
6. The launch use case (AP nightly cleanup)
7. Operator runbook

---

## 1. Mental model

```
┌──────────────────────────────────────────────────────────────────────┐
│  workstream YAML (canonical state)                                   │
│  enterprise_root/tenants/<tenant>/workstreams/<name>.yaml            │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  cron job ws_<name>  →  mission_mode skill  (every N min)            │
│                          │                                           │
│                          ▼                                           │
│  mission_engine.run_iteration()                                      │
│   1. Fire BeforeMissionStart (first activation only — gateable)      │
│   2. Pick next item by priority_strategy                             │
│   3. Run worker: skill -> agent.run(...) OR automation -> no-LLM engine│
│      ⇡ Skill path keeps ReAct/security/HITL/evidence unchanged        │
│   4. Persist outcome to YAML (done | awaiting_human | failed | retry)│
│   5. If terminal → fire OnMissionComplete + auto-pause cron          │
│   6. If item exhausted retries → fire OnMissionItemFailed            │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  UI:  /static/workstreams.html  (index)                              │
│       /static/workstream_detail.html?name=<name>  (live view)        │
│       /static/workstream_new.html  (create wizard)                   │
│  API: /api/workstreams  (20 REST + /ws/workstreams/<name>)           │
└──────────────────────────────────────────────────────────────────────┘
```

**Bounded items per cron tick.** Mission Mode never has to turn an entire
business batch into one giant prompt. By default a tick processes one item;
enterprise workstreams can raise `batch_size` and `parallelism` so multiple
independent items advance safely while each item keeps its own status,
trace, evidence, HITL state, and execution log.
Worker responses that say the agent cannot proceed, failed to fetch mandatory
evidence, or still require approval are not treated as completed outcomes; the
item remains retryable or fails visibly at the retry limit.

**No new reasoning engine.** Mission Mode is a thin outer loop. The
real work happens inside `agent.run()`, which uses the same ReAct loop,
the same hooks, the same security gates, the same evidence collector,
the same HITL flow that chat queries use.

**No-LLM worker option.** A workstream can declare `automation: <id>` instead of
`skill: <skill_name>`. In that case Mission Mode still owns item claiming,
attempts, status updates, runtime traces, and completion checks, but the item is
processed by the Deterministic Automation engine. That engine allows only
`shell`, `python`, and `condition` steps and rejects `skill` actions. See
`DETERMINISTIC_AUTOMATIONS.md`.

Workstream agents and deterministic automation workers use the AgentOS kernel
runtime factory. With `AGENTOS_KERNEL_BACKEND=remote`, item shell/file/Python
execution runs in the signed kernel worker while Mission Mode keeps the same
YAML state, HITL, evidence, and runtime DB behavior.

**Queue-style execution trace.** Workstream YAML remains the canonical business
state, but Studio also initializes `workstream_runtime.db` for high-churn runtime
details. Each item attempt creates a durable `workstream_executions` row and each
`status_callback`/tool step appends a `workstream_steps` row while the WebSocket
streams `mission_item_step`. Late page loads can reconstruct the running trace
through `/api/workstreams/{name}/items/{id}/context` or the focused
`/api/workstreams/{name}/items/{id}/executions` endpoint instead of relying only
on browser-local live events.

**RL/eval outcome signals.** When `RL_CAPTURE=true`, Workstream REST actions and
run/iterate results are emitted through `iaf_agent_skills.capture_events` and
mirrored best-effort into the independent RL/eval store as raw `workstream`
reward events. Labels include `done`, `failed`, `awaiting_human`, `retry`,
`skipped`, `cancelled`, and `action_blocked`; reward shaping is still handled by
exporters, not by Mission Mode.

**Multi-skill items use workflow worker skills.** A workstream still names one
worker `skill:`, but that worker can use `execution_mode: workflow` and call
multiple child skills with `action: skill` steps. Child-skill HITL pauses are
checkpointed with the parent workflow, so approval resumes the paused step and
then continues to the next child skill — for example, a no-HITL classifier step,
a prompt-driven approval step, a hook-enforced approval step, and a no-HITL
learning-capture step chained in one workflow.
Workflow child agents inherit the parent Mission Mode workstream and item ids,
so child skill approvals and hook-created approvals are stamped back to the
correct workstream item instead of being treated as unrelated HITL.

---

## 2. Creating a workstream

### Items: hand-typed OR auto-sourced

Workstream items can be hand-typed in the YAML, OR pulled automatically
from an external system on every cron tick via the `items_source` config.
**Auto-sourcing is what production use cases want** — hand-typing 50
invoices into YAML doesn't scale.

#### `items_source` schema

```yaml
items_source:
  type: sql | http | directory | skill
  refresh_strategy: append_new | merge | replace_all
  # type-specific keys below
```

**Refresh strategies:**

| Strategy | Behaviour |
|---|---|
| `append_new` (default, safe) | Only items with new ids get appended. Existing items keep their status/attempts/trace. |
| `merge` | Update description/priority on existing items; append new ones; never delete. |
| `replace_all` | **Destructive.** Wipes all existing items, replaces with current fetch. Use only when in-flight items shouldn't be preserved. |

#### Source type: `sql`

Pull items from a SQLite database under `enterprise_root/tenants/<tenant>/shared/databases/`. Read-only — only SELECT is permitted.

```yaml
items_source:
  type: sql
  refresh_strategy: append_new
  database: ap_regular                 # without .db suffix
  query: |
    SELECT invoice_id AS id,
           'Resolve ' || invoice_id || ' (' || amount_eur || ' EUR, ' || vendor_id || ')' AS description,
           amount_eur AS priority_metric
    FROM invoices
    WHERE status IN ('pending', 'on_hold', 'disputed')
```

The query must return at least two columns — one identifying the item
(named `id`, `item_id`, `invoice_id`, `account_id`, `ticket_id`,
`vendor_id`, `customer_id`, `doc_id`, or `uid`) and one describing it
(named `description`, `task`, `summary`, `title`, `reason`, or `note`).
Optional `priority_metric` (or `amount_eur` / `amount`) for the
`highest_amount` priority strategy.

SQL rows can also return JSON object/list columns for richer Workstream Detail
contracts. If `case_summary`, `case_insights`, or `metadata` contain JSON
objects, the resolver stores them as structured item dictionaries. If
`acceptance_criteria` contains a JSON list, the resolver stores it as the item
checklist. This is the recommended path for cron workstreams that need the
business lens to refresh from backend data rather than hand-authored YAML.

```sql
SELECT debit_id AS id,
       description,
       debit_amount AS priority_metric,
       case_summary_json AS case_summary,
       case_insights_json AS case_insights,
       json_array('Confirm balance', 'Recommend recovery path') AS acceptance_criteria
FROM debit_balances
WHERE status = 'open';
```

To try this pattern, seed a tenant source database with:

```bash
python3 onboarding/data/seed_ap_db.py --ap-ops-cron-demo
```

A workstream using `items_source[sql]` against that seeded data would read
rows from `shared/databases/ap_ops.db`, merge them into Workstream items, and
then let the backend business-lens refresh overwrite the seeded metric values.

#### Source type: `http`

Poll an HTTP endpoint. Expects a JSON response. Credentials are pulled
from `credentials.yaml` and injected as `X-API-Key` (or `Bearer` for
token-type creds).

```yaml
items_source:
  type: http
  refresh_strategy: append_new
  url: http://localhost:9092/aging
  method: GET                          # default GET
  credential: finance_api_readonly     # optional — name in credentials.yaml
  items_path: items                    # dotted path into JSON; root if empty
  item_template:                       # optional field mapping
    id: invoice_id
    description: "Aging {invoice_id} ({amount_eur} EUR, {exception_code})"
    priority_metric: amount_eur
```

`item_template` is optional — if the response objects already use one of
the recognized id/description field names, the engine maps them
automatically (see SQL source notes above).

#### Source type: `directory`

Scan a filesystem path on a glob. Restricted to
`enterprise_root/tenants/<tenant>/` for safety.

```yaml
items_source:
  type: directory
  refresh_strategy: append_new
  path: /agents/enterprise_agent/users/admin@iaf.local/   # relative to tenant_root
  pattern: "*.pdf"                     # any glob
  id_template: "review-{stem}"         # placeholders: filename, stem, path, size, ext
  description_template: "Review {filename}"
```

#### Source type: `skill`

Delegate to a worker skill that returns a JSON array. Use this when the
items_source logic is itself agentic (e.g. needs to query multiple APIs,
join data, dedup based on history).

```yaml
items_source:
  type: skill
  refresh_strategy: append_new
  skill: fa_ap_item_lister             # must exist in your skills/_index.yaml
  query: |
    List all AP invoices that need nightly attention.
    Return a JSON array: [{"id": "INV-...", "description": "...", "priority_metric": 12500}, ...]
```

The skill's response is parsed tolerantly — both bare JSON arrays and
fenced ` ```json [...] ``` ` blocks work.

#### Optional business lens metadata

Each workstream can expose domain-aware business KPIs at the workstream level.
This keeps the top of Workstream Detail useful for business users without
hardcoding invoice, ticket, or reconciliation-specific labels in the UI. If
`business_lens` is absent, the page simply shows the existing Agent Execution
metrics.

```yaml
business_lens:
  title: Business Impact
  subtitle: Domain-aware KPIs for this workstream
  primary_entity_label: Customer
  secondary_entity_label: Invoice
  value_label: Exposure
  metrics:
    - id: total_exposure
      label: Total Exposure
      value: "$390K"
      unit: currency
      trend: "+8%"
      severity: high
      explanation: Open value across unresolved cases
    - id: aging_risk
      label: Aging / SLA Risk
      value: "2 cases"
      severity: critical
      explanation: Cases breaching or nearing SLA
```

`business_metrics` can also be supplied as a short list alias; the runtime
normalizes both shapes for Workstream chat and AskTwin context. The UI renders
business metrics as a **Business Impact** lens above the existing **Agent
Execution** lens, with a `Combined | Business | Agent` selector. Each Business
Impact metric card is clickable: it opens a docked AskTwin panel beside the
workstream, passes the selected metric plus current visible cases and status
counts, and asks a metric-specific question.

#### Optional case workbench metadata

Each workstream item can also expose domain-neutral analyst metadata. This is
optional: existing items still render from `id`, `description`,
`priority_metric`, status, acceptance criteria, evidence, and suggested actions.
When present, the Workstream Detail page renders the item as an Analyst Case
Workbench with an always-visible case header, action bar, **Research Pack** tab,
and **Insights & Patterns** tab.

```yaml
items:
  - id: CASE-001
    description: Resolve the current exception or ticket
    priority_metric: 100
    case_summary:
      case_id: CASE-001
      case_type: AR dispute | IT ticket | reconciliation break | other
      title: Short case title
      primary_entity: Customer, supplier, application, account, or owner
      secondary_entity: Invoice, ticket, document, or related record
      category: Domain-aware category
      impact_label: Exposure
      impact_value: "$100,000"
      age_or_sla: 90+ days or SLA breached
      risk_level: low | medium | high | critical
      priority_reason: Why this item should be worked now
      recommended_action: What the agent recommends next
      recommendation_confidence: 0.86
      policy_trigger: Approval or policy rule that applies
      evidence_summary: Short evidence summary
      resolution_mode: auto_resolved | review_only | human_required
      auto_resolution_status: cleared_overnight | ready_for_review | blocked
      auto_resolution_reason: Why the agent could or could not complete the item
      analyst_action: What the human should do next
      audit_summary: What was logged for review
    case_insights:
      current_findings:
        - Current fact about this case
      historical_patterns:
        - label: Repeat pattern
          value: Pattern value
          explanation: Why it matters
      recommendation_reasoning:
        - Reason behind the recommended action
      prevention_opportunities:
        - Upstream change that could avoid similar cases
      research_pack:
        - label: SAP / CRM / Contract Repository / Monitoring System
          source_type: erp | procurement | communications | approval | supplier_master | history
          status: checked | missing | blocked
          confidence: high | medium | low
          findings:
            - What the agent found in this source
          source_refs:
            - Source document, system id, or evidence reference
      next_best_action: Recommended next action after the research pack
      similar_cases:
        - id: CASE-000
          summary: Similar previous case
          outcome: Resolved
          resolution_time: 3 days
```

Skills should produce domain-aware values in this contract, but the UI remains
domain-neutral. For example, an invoice dispute and an IT incident both become a
case with impact, risk, recommendation, evidence, patterns, and prevention
opportunities. Items can also expose auto-resolution metadata when the agent has already completed routine work inside policy; Workstream Detail then shows an Overview callout that the analyst only needs to review the audit trail. For a full skill authoring walkthrough, see
`docs/WORKSTREAM_SKILL_CONTRACT_GUIDE.md`.

### What you see at runtime

On every cron tick (when `items_source` is set):

```
mission_engine: items_source[sql] refreshed workstream ap_nightly_cleanup —
    appended=3 updated=0 (strategy=append_new, total_items=27)
```

The workstream YAML's `last_source_refresh_at` timestamp updates each tick.

---

### Via UI

1. Open <http://localhost:8081/static/workstreams.html>
2. Click **+ New Workstream**
3. Fill the wizard:
   - **Name** — lowercase + digits + underscore, starts with a letter
   - **Skill** — the worker skill that processes each item (e.g. `fa_ap`)
   - **Cron schedule** — pick "Every 5 minutes" for testing, "Daily at 2am UTC" for production nightly
   - **Items** — manual entry, paste `id | description` lines, or paste a YAML items array
4. Click **Create + Activate**. You land on the Workstream Detail page.

The Workstreams index opens as the operator's daily brief. The top panel shows
decisions waiting, agents currently running, exceptions to triage, handled
outcomes, and a lens-based feed for today's work. The snapshot strip and cards
remain below it for broader workstream health, sorting, search, pause/resume
controls, and a persisted theme switch for dark, hybrid, or light viewing
preferences. The same page also exposes a collapsed right-side Workstream
Copilot rail. Opening or dragging it expands an inline main-chat-style panel
with WebSocket streaming, markdown rendering, page context, skill selection,
`@skill` routing, and skill-component hydration for governed action forms.

You can also create and edit Workstreams from **Designer Studio → Workstreams**
(`/skill-builder/v2`). The create tab writes the same Workstream YAML contract
as `POST /api/workstreams`, including worker skill, `items_source`, cron
metadata, escalation rules, and `business_lens`. The edit tab patches
workstream-level YAML fields such as display name, owner, description, skill,
priority strategy, batch/parallel settings, `items_source`, escalation, business
lens, and cron metadata. Existing item rows remain lifecycle-managed by
Mission Mode and item action APIs.

Ask Twin is available from the bottom-right corner of the creation wizard and
detail cockpit. The Workstreams index now uses the inline Workstream Copilot for
page-wide questions, while Workstream Detail exposes an embedded Workstream
Copilot beside the expanded item workbench for item-specific briefing,
business-action prompts, skill routing, and wide/normal panel layouts. These
surfaces receive bounded page context such as current filters, visible
workstream counts, draft workstream form fields, selected workstream, expanded
item, generic visible item records, approval blockers, and recent activity so
they can answer questions about what the operator is currently viewing without
relying on domain-specific row names.

### Via API

```bash
curl -X POST http://localhost:8081/api/workstreams \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my_workstream",
    "skill": "fa_ap",
    "owner": "ops@example.com",
    "priority_strategy": "highest_amount",
    "max_attempts_per_item": 3,
    "cron_schedule": "*/5 * * * *",
    "cron_user_id": "admin@iaf.local",
    "items": [
      {"id": "x1", "description": "First task", "priority_metric": 100},
      {"id": "x2", "description": "Second task", "priority_metric": 50}
    ]
  }'
```

### Via direct YAML

Drop a file at
`enterprise_root/tenants/company/workstreams/<name>.yaml` and create the
cron job manually pointing at `mission_mode` skill with `task=<name>`. If the
YAML includes both `cron_schedule` and `cron_user_id`, Studio now also
reconciles it on server startup: it creates or updates `ws_<name>` in the cron
scheduler and writes the live `cron_job_id` back to the workstream YAML.

---

## 3. Hook events

Mission Mode emits three lifecycle events. All inherit `trace_id` from
the cron firing's session_ctx.

| Event | Gateable | Fires when | Context payload |
|---|---|---|---|
| `BeforeMissionStart` | yes | First activation of a workstream (once, on the cron tick that first transitions it from never-started to running) | `workstream_name`, `owner`, `total_items`, `skill` |
| `OnMissionItemFailed` | no (observe) | An item exhausts `max_attempts_per_item` retries | `workstream_name`, `item_id`, `attempts`, `error_msg` |
| `OnMissionComplete` | no (observe) | All items reach terminal state (`done`/`failed`) — `awaiting_human` items count as *not* terminal | `workstream_name`, `duration_total_sec`, `items_done`, `items_failed`, `items_escalated` |

These complement (not duplicate) the existing cron and turn events:

- `BeforeScheduleFire` / `AfterScheduleFire` fire on every cron tick (5-minutely)
- `BeforeTurn` / `OnTurnEnd` fire on every item's `agent.run()` call
- `BeforeMissionStart` / `OnMissionItemFailed` / `OnMissionComplete` fire on **workstream-level** state changes that span many ticks

### Example: Slack on workstream completion

```yaml
# enterprise_root/tenants/company/agents/enterprise_agent/config.yaml
hooks:
  OnMissionComplete:
    - id: slack-mission-complete
      command: python3 $IAF_AGENT_ROOT/../../shared/hooks/slack_notify.py
      timeout_seconds: 10
      fail_policy: open
```

Then `slack_notify.py` reads `IAF_WORKSTREAM_NAME`, `IAF_ITEMS_DONE`,
`IAF_ITEMS_FAILED`, `IAF_ITEMS_ESCALATED`, `IAF_DURATION_TOTAL_SEC` from env.

### Example: freeze window gate

```yaml
hooks:
  BeforeMissionStart:
    - id: release-freeze-gate
      command: python3 $IAF_AGENT_ROOT/../../shared/hooks/freeze_check.py
      timeout_seconds: 5
      mode: blocking
      block_on_nonzero: true
      fail_policy: closed
```

`freeze_check.py` exits non-zero during a release freeze window. The
workstream stays paused until you remove the freeze and resume manually.

---

## 4. HITL integration

Mission Mode does NOT have its own approval queue. When an item calls
`request_human_approval`, the approval lands in the **existing**
`/api/hitl/pending` queue exactly like a chat-originated or
cron-originated approval. The platform has one approval store; two UIs
render from it:

| Where | What you see |
|---|---|
| Dashboard approvals tab (`dashboard_v2.html`) | All pending approvals — chat, cron, AND mission items mixed |
| Workstream Detail page (`workstream_detail.html?name=…`) | Just approvals filtered to this workstream |

The workstream approval cards disable the clicked Approve/Reject action, show
`Approving…` or `Rejecting…`, and remove the card after the resolve POST
succeeds. The item may still show `in_progress` while the checkpointed worker
continues the post-approval run in the background.

Workstream item approval metadata is a hard platform gate. If an item has
`approval_required: 1`, `bucket: judgement_required`,
`case_summary.resolution_mode: human_required`, or
`auto_resolution_status: human_required`, Mission Mode still asks the worker
skill to call `request_human_approval` after evidence collection, but it also
synthesizes a linked approval if the worker returns a completion summary without
pausing. The item remains `awaiting_human` until the approval is resolved.

Both views post to the same `POST /api/hitl/{id}/resolve` endpoint. The
filter is one query parameter:

```
GET /api/hitl/pending?workstream=ap_nightly_cleanup
```

The filter matches in two ways (whichever fires first):

1. Approval ID appears in the workstream YAML's `item.escalated_approval_id`
   (deterministic; doesn't need the LLM to populate context).
2. The approval's `context.workstream_name` equals the filter
   (works for new approvals — `mission_engine` stamps this into context).

### Closing the loop after a human decides

When the human clicks Approve or Reject, the workstream item is closed only
after the post-approval worker run finishes:

1. **Approval store** marks the approval `status=approved|rejected`.
2. **Approval endpoint releases the workstream gate**. Approved items move
  from `awaiting_human` to `in_progress` and emit an `item_resuming` event.
  Rejected items move directly to `failed` and do not resume the worker.
3. **Agent resumes** under the `service:hitl_resume` principal —
  `BeforeApprovalResume` hook fires (gateable), state is restored, the
  resume prompt is anchored to the originating workstream item, and the
  resumed turn runs in fresh mode without shared session memory so parallel
  items cannot bleed into each other. The worker skill (e.g. `fa_ap`) then
  continues the post-approval work (queries DB, updates ERP, etc.). If that
  continuation hits another governed tool call or business approval, the new
  approval is checkpointed and the same item returns to `awaiting_human`
  instead of being finalized.
4. **Approval resume finalizes the workstream YAML**. If the resumed worker
  returns successfully, `item.status` becomes `done`, `item.last_result_summary`
  is replaced with the resumed worker's answer, `item.resolution` stores the
  approval decision plus resumed result, stale approval actions are replaced
  with done-state actions, and a structured `execution_ledger` row with
  `execution_source: hitl_resume` is appended. If the worker errors or
  `BeforeApprovalResume` blocks, `item.status` becomes `failed` with a
  bounded failure reason and failed-state actions.
5. **HITL feedback becomes governed learning**. Every workstream-linked
  approval or rejection writes one `source=hitl_feedback`,
  `status=pending_review` Knowledge Manager candidate. Approver notes become
  explained precedent; no-note decisions still become observed precedent using
  the approval reason, workstream/item ids, skill, and available supplier or
  invoice entity keys. The write is idempotent by approval id and non-fatal, so
  approval resolution is never blocked by knowledge persistence.

Connector-originated approvals, such as a high-value `post_to_sap` component
submission, use the same pending queue and workstream linkage. They may not have
an agent checkpoint; on approval the connector-specific resolver records the
mock connector outcome on the originating item instead of attempting a worker
resume.

Hook-created stream-intercept approvals also carry workstream linkage when a
`PreToolUse` guard blocks a tool call during Mission Mode. Tool governance stamps
`context.workstream_name` and `context.mission_item_id` on the approval before it
is checkpointed, so Workstream Detail can show the item as `awaiting_human` and
resolve the held tool call through the same approval card pattern used by queue
monitor approvals.

Blocking hooks can be used for deterministic business approvals after the
worker has gathered evidence and drafted its final response. Configure the hook
with `on_block: hitl` and optional `approval` metadata. When such a hook blocks
during Mission Mode, `agent.run()` converts the block reason into a normal
`approval_pending` checkpoint with the current workstream and item id, so the
existing Mission Mode persistence path stores the approval and pauses the item
before it is marked `done`. Hooks without `on_block: hitl` keep the safer
deny-only behavior.

Step 4 is the **closing of the loop** that `mission_engine.run_iteration()`
cannot do on its own. The mission engine returned with `awaiting_human`
when the agent paused — it had no way to learn about the eventual
decision or resumed-worker result because the resume happens in a separate
process triggered by the HITL API, not through the engine.

Hook is registered in
`enterprise_root/tenants/<tenant>/agents/<agent>/config.yaml` under
`hooks.AfterApprovalResume`:

```yaml
AfterApprovalResume:
- id: mission-resume-sync
  command: python3 $IAF_AGENT_ROOT/../../shared/hooks/mission_resume_sync.py
  timeout_seconds: 10
  fail_policy: open    # observe-only, never blocks
```

The hook script (`enterprise_root/tenants/<tenant>/shared/hooks/mission_resume_sync.py`)
reads `IAF_APPROVAL_ID` + `IAF_APPROVAL_DECISION` from env, locates the
matching workstream + item (via context dict, falling back to scanning
all workstreams for the `escalated_approval_id`), and writes an observe-only
audit line. It does not patch YAML; `routers/approvals.py` is the single
writer for post-resume workstream final state. Audit log lives at
`/tmp/mission_resume_sync.log`.

**Behaviour when one approval was raised for multiple items**
(LLM-batched in a single `request_human_approval` call): the approval
resume path finalizes the item identified by the approval context
(`context.workstream_name` + `context.mission_item_id`). If you want
per-item human decisions, tune the worker skill's prompt to call
`request_human_approval` once per item rather than batching.

**Resume identity guardrail:** The resumed prompt includes a `WORKSTREAM
RESUME CONTEXT` block with the workstream name, item id, original item
description, acceptance criteria, and scalar approval context. That resumed
turn passes `skip_memory=True` and `light_mode=True` to `agent.run()`; the
checkpoint still restores the paused agent state, but shared short-term memory,
procedural memory, and plan-cache context are not allowed to substitute facts
from neighbouring parallel items.

**Follow-up approval guardrail:** If the resumed worker pauses again, for
example because a post-approval SQL/tool call needs its own confirmation, the
new approval inherits `workstream_name` + `mission_item_id`, is persisted to the
same approval store, and the YAML item returns to `awaiting_human` with that new
approval id. The item does not become `done` until a resumed worker returns a
normal completion result.

---

## 5. Evidence per item

Every item's `agent.run()` produces an evidence bundle keyed by the
item's `trace_id`. The mission engine stores the current trace in both
`item.last_trace_id` and `item.evidence_trace_id`, plus `item.evidence_count`
when captures exist. The Workstream Detail page renders this inline when you
expand an item row. Behind the scenes it just fetches `/api/evidence/{trace_id}`
— the same endpoint the chat evidence viewer uses.

Each attempt also appends a bounded `item.execution_log` entry with attempt
number, status before/after, start/end timestamps, duration, trace id,
evidence count, approval id when present, result preview, and error preview.
For queue-grade Workstream-native operation, the same attempt also appends a
structured `item.execution_ledger` row keyed by `current_execution_id` (for
example `wse_...`). The ledger preserves the attempt status transition,
trace/evidence ids, duration, result/error previews, and bounded tool-step
previews when the worker exposes them. During the run, Mission Mode also passes
a `status_callback` into `agent.run()` and streams normalized progress/tool
steps to `/ws/workstreams/<name>` as `mission_item_step` events after a
`mission_item_started` event. The Workstream Detail `Execution Trace` tab shows
those steps live for the active item and then falls back to
`execution_ledger[].steps` for historical review. The legacy `execution_log` stays in
place for backward compatibility; new UI and APIs prefer `execution_ledger`
when they need a durable execution record. Only the most recent execution and
step entries are retained in YAML so long-running workstreams do not grow
unbounded.

A failed item that retried 3 times has 3 trace_ids — only the most
recent is stored in `item.last_trace_id`. To see earlier attempts,
query `traces.db` filtered by the item id (the engine writes
`mission_item_id` into the span context).

### Item context and continuation chat

The Workstream Detail page is the business cockpit for completed and blocked
items. Its top level presents a command summary with completion, active workers,
approval blockers, exceptions, evidence coverage, risk posture, an executive
narrative, and next-best-action chips. Expanding an item switches into the
operator drilldown: summary KPIs plus purpose-colored tabs for Overview,
Evidence, Run Timeline, Audit Ledger, Execution Trace, Actions, and item-scoped chat. The page
shares the Workstreams theme preference, so the detail cockpit can be viewed in
dark, hybrid, or light mode. Expanding an item can call:

```text
GET /api/workstreams/<name>/items/<item_id>/context
```

The response includes bounded item state, optional `case_summary` and
`case_insights` metadata, result summary, evidence trace/count, approval state
when pending, legacy execution log, structured execution ledger, governed action
history, suggested actions, and chat session metadata. The detail page shows a
generic Analyst Case Workbench for each expanded item with three distinct visual
zones: a risk-aware Case Snapshot header, a Decision Actions strip, and a
Workbench area containing summary KPIs plus Overview, Research Pack, Insights & Patterns,
Evidence, Timeline, Audit Ledger, Execution Trace, Actions, and item-scoped chat tabs. Overview also highlights auto-resolved items when `case_summary.resolution_mode` is `auto_resolved`. After a
human approval resumes and completes an item, the Workstream Detail page shows
the resumed answer in the item result area and the ledger includes both the
initial `awaiting_human` execution and the `hitl_resume` completion row.
Item-scoped continuation uses:

```text
POST /api/workstreams/<name>/items/<item_id>/chat
```

The Workstream Detail inline chat form and Ctrl+Enter shortcut both submit to
this endpoint from the **Ask About This Item** tab, then clear the draft and
refresh the item transcript preview when the server returns successfully.
The request body can also include `skill_name` when a UI wants to route the
follow-up through a specific skill instead of the workstream's default skill.

The chat session id is deterministic: `workstream:<name>:item:<item_id>`. The
endpoint persists the most recent transcript turns in YAML with long response
previews retained for operator readability; item chat responses are bounded at
8,000 characters so normal operator answers survive refresh while the
workstream file cannot grow without limit. Every follow-up message is routed
through the existing `/api/chat` backend with a Workstream item context prompt,
so it uses the same agent/chat infrastructure as the main chat surface. The
inline item chat does not pre-block side-effect-looking text; the agent receives
the item context and can answer naturally with the same approval/tool controls
as the main chat surface. If that REST chat turn raises a business HITL approval,
the checkpoint is persisted to the shared approval store and the YAML item is
stamped with `status=awaiting_human`, `escalated_approval_id`, and
`last_approval_context`, so Command Center and the workstream-filtered inbox can
show the same pending approval. The stamp is accepted only when the returned
approval context matches the current `workstream_name` and `mission_item_id`;
mismatched or stale approvals stay out of the item state. Explicit operator
actions remain available through governed buttons, HITL approval flow, or the
governed action endpoint.

### Governed item actions

Workstream items are the business execution unit, so safe operator actions are
recorded on the item rather than mirrored into Queue Monitor rows. The endpoint
is:

```text
POST /api/workstreams/<name>/items/<item_id>/actions
```

Supported actions are:

| Action | Behaviour |
|---|---|
| `retry` / `retry_item` | Reset `status=pending`, `attempts=0`, clear failure/approval/closed metadata, and let the next cron tick or manual **Run Now** reprocess the item. |
| `skip` / `skip_item` | Mark the item `done` with `resolution: "SKIPPED: <reason>"`. |
| `close` / `close_item` | Set `closed_at` and `closed_by` for an item already `done` or `failed`. |
| `email`, `post`, `resend`, `correct` | Record a blocked governed action event until a connector and policy-backed executor is configured. |

Every action appends a bounded `item.action_events` row with an action id,
requesting user, requested time, status, reason, and result. This creates a
single Workstream-native ledger for retries, skips, closes, and blocked future
side effects without creating duplicate business records in Queue Monitor.

---

## 6. Launch use case — AP nightly cleanup

A no-code pre-built example is not shipped; build it yourself by authoring
`enterprise_root/tenants/company/workstreams/ap_nightly_cleanup.yaml` following
the contract in §3-4 above (or via the workstream creation wizard).

**What it does:**
- Pulls every pending/on-hold AP invoice (20 items spanning thresholds)
- Drives the `fa_ap` skill to resolve each one
- For items > €500k → forces CFO approval (request_human_approval)
- For HIGH_RISK_VENDOR items → forces sanctions/bank review
- For NO_PO items > €10k → forces Finance Director approval
- Auto-completes when every item is `done` or `failed`

**Run it:**

```bash
# Make sure the ap_regular.db is seeded
python3 onboarding/data/seed_ap_db.py

# Wire the cron (you can also click through the wizard)
curl -X POST http://localhost:8081/api/cron \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ws_ap_nightly_cleanup",
    "skill_name": "mission_mode",
    "task": "ap_nightly_cleanup",
    "cron": "*/5 * * * *",
    "tenant_id": "company",
    "agent_id": "enterprise_agent",
    "user_id": "admin@iaf.local",
    "max_runtime_seconds": 180,
    "enabled": true
  }'
```

Watch progress at
<http://localhost:8081/static/workstream_detail.html?name=ap_nightly_cleanup>.

**Expected behaviour over ~3 hours:**
- ~12 items auto-resolve (simple pending invoices below thresholds)
- ~8 items escalate to HITL (CFO/Director tier + high-risk + maverick)
- You approve/reject each escalation in the UI
- `OnMissionComplete` fires when the last item is resolved
- Cron auto-pauses

---

## 7. Operator runbook

### Pause a workstream
```bash
curl -X POST http://localhost:8081/api/workstreams/<name>/pause
```
The next cron tick will skip (the engine sees `status != active` and returns immediately).

### Retry a failed item
Open the detail page, expand the item, click **Retry now**. This calls the
governed item action endpoint, records an `action_events` row, and resets
`attempts=0` and `status=pending`. You can then wait for the next cron tick or
click **Run Now** to process the pending retry immediately. If the workstream had
already reached `completed` or `failed`, manual **Run Now** reactivates it before
dispatching the pending item. Paused workstreams still require **Resume** first.

### Continue from an item result
Open the detail page, expand the item, and use the item chat box to ask about
that item's result, evidence, approval state, or next steps. The chat is scoped
to that one workstream item and routes every message to the existing `/api/chat`
backend with the item context attached.

### Ask about a business metric
Open the detail page and click a **Business Impact** card such as `Total
Exposure`, `SLA / Aging Risk`, or `Approval-Gated Value`. The shared AskTwin
docked side panel opens inline with the Workstream page, shifting the main
content left, aligns with the Business Impact cockpit, adopts the current
Workstream theme, and immediately sends a clean metric question. The page keeps
the selected metric, business lens, visible
cases, status counts, and current lens mode in `page_context`. This keeps the
visible prompt readable while still letting AskTwin explain what the metric
means, which cases contribute, and what should be prioritized next. Item-level
chat responses continue to render as sanitized Markdown for headings, bullets,
tables, and code snippets.

See `docs/WORKSTREAM_SKILL_CONTRACT_GUIDE.md` for two worked examples of this
contract: an AR-dispute workstream and an AP debit-balance-recovery workstream.

Business lens values are refreshed by the backend workstream store whenever
workstream state is written: creation/save, item claim, item completion/failure,
approval pause/resume, manual retry/skip/close actions, item append, and cron or
run-now batch execution. YAML values can still provide the initial labels and
seed values, but `workstream_business_lens.refresh_business_lens` overwrites the
metric values from current `case_summary`, status, approval, and impact metadata
on the next refresh.

### Skip an item
Open the detail page, expand the item, click **Skip**. This records an action
event and marks the item as `done` with `resolution: "SKIPPED: <reason>"`.

### Add an item to a running workstream
```bash
curl -X POST http://localhost:8081/api/workstreams/<name>/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id": "new-item", "description": "task to add"}'
```

### Cancel a workstream
```bash
curl -X POST http://localhost:8081/api/workstreams/<name>/cancel
```
Sets `status=failed` + `completed_at=now`. Cron auto-pauses on next
tick. Existing items are not touched — you can resume by patching
status back to `active`.

### Delete a workstream
```bash
curl -X DELETE 'http://localhost:8081/api/workstreams/<name>?also_delete_cron=true'
```
Removes the YAML AND the cron job. Items lost.

---

## What Mission Mode is NOT

- Not a new reasoning engine — it's a 250-line wrapper around `agent.run()`
- Not a new approval queue — it uses the existing HITL store
- Not a new evidence model — it reuses `evidence.db` keyed by trace_id
- Not a new audit channel — its hook events flow through `traces.db` like everything else
- Not unbounded fan-out — each tick is capped by `batch_size` and `parallelism`

That's deliberate. Every primitive is the same primitive that powers
chat. The only new thing is the **convention** of "a backlog YAML +
a cron that grinds it."

## Enterprise route boundary

Mission Mode REST calls bind tenant/user scope from the authenticated principal
and enforce `workstream` permissions. Its live WebSocket validates the JWT,
allowed tenant, and read entitlement before acceptance. Browser clients append
the current access token to the connection URL. Scheduled Mission Mode work is
owned by the elected scheduler role; API replicas do not run duplicate ticks.

---

## Related reading

- [SECURITY_TESTING_GUIDE.md](SECURITY_TESTING_GUIDE.md) — the 4-layer defence model that protects every Mission Mode item
- [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md) — how human approval checkpoints work
- [HOOK_EVENT_REFERENCE.md](HOOK_EVENT_REFERENCE.md) — full catalogue of hook events
- [EXTENDING.md](EXTENDING.md) — how to write a hook for OnMissionComplete (Slack, email, downstream workstream)
