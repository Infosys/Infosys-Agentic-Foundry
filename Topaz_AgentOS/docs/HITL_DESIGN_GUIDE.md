# Human-in-the-Loop (HITL) Design Guide

**Infosys Agentic Foundry** | IAF AgentOS

---

## What is HITL?

Human-in-the-Loop (HITL) is the mechanism that pauses agent execution and waits for a human to approve, reject, or escalate before the agent proceeds. It applies to both interactive chat sessions and autonomous background queue jobs.
Deterministic Automations are a no-LLM path and do not call
`request_human_approval`; if a process needs human judgment, model that part as a
Skill or a governed Workstream action.

When `RL_CAPTURE=true`, HITL lifecycle events are mirrored best-effort into the
independent RL/eval store through `iaf_agent_skills.capture_events` as raw
`human_approval` rewards. Creation, approve, reject, escalate, blocked resume,
follow-up pause, successful resume, and resume error labels are stored without
shaping; exporters decide later whether each label is desirable, undesirable, or
filtered for a specific training format.

---

## The 4 Mechanisms — Choose the Right One

### 1. `approval_rules:` in SKILL.md
**Use when:** The trigger is a **business condition** — an amount threshold, a specific action name, or a keyword in the context. The agent understands the situation and decides when to ask.

```yaml
# skills/invoice_ops/SKILL.md
---
name: invoice_ops
approval_rules:
  default_urgency: medium
  thresholds:
    - field: amount
      operator: ">="
      value: 500000
      reason: "Invoice above ₹5L requires CFO approval"
      urgency: high
  always_require:
    - delete_vendor
    - override_payment_terms
  never_require:
    - read_invoice
    - view_status
  conditions:
    - when: "new_vendor"
      reason: "New vendor onboarding requires finance review"
      urgency: medium
  sla_minutes: 120
---
```

**How it works:** The engine injects the `request_human_approval` tool into the agent's toolset and compiles the rules into the system prompt. The LLM evaluates the context at runtime and calls the tool when a rule matches.

**Where approval appears:**
- Chat (WebSocket): `#approvals` tab + chat message
- Chat (HTTP): chat message only
- Queue/background: `#approvals` tab + Queue Monitor awaiting_human status

---

### 2. `hitl:` section in `config.yaml`
**Use when:** The trigger is a **specific tool call pattern** — a regex match on the command or query. No LLM reasoning needed. Applies to every skill in that agent.

```yaml
# enterprise_root/tenants/company/agents/enterprise_agent/config.yaml
hitl:
  # Block specific tools entirely
  dangerous_tools:
    - execute_code

  # Block all tool calls when these skills are active
  hitl_skills:
    - payroll_ops
    - hr_records

  # Shell command regex patterns
  shell_patterns:
    - '\bdocker\s+(rm|stop|kill)\b'
    - '\baws\s+ec2\s+terminate\b'

  # SQL mutation gate (opt-in — empty by default)
  sql_patterns:
    - '\b(DELETE|UPDATE|DROP|TRUNCATE|ALTER|INSERT)\b'

  # Keyword scan across all tool args
  keyword_patterns:
    - 'production'
    - 'salary'
```

**How it works:** The HITL gate (`_is_dangerous_call`) runs deterministic regex matching before every tool call. If matched, the tool is blocked before it executes — no LLM involved.

**Where approval appears:**
- Chat: `#approvals` tab (kernel source) + chat message inline
- Queue/background: `#approvals` tab (HITL source) + Queue Monitor awaiting_human status

---

### 3. PreToolUse hook in `config.yaml`
**Use when:** The trigger requires **custom Python logic** — a database lookup, an API call, an ACL check, or any condition that can't be expressed as a regex.

```yaml
# config.yaml
hooks:
  PreToolUse:
    - matcher: "shell"
      command: python3 /shared/hooks/ccdops_block_writes.py
      block_on_nonzero: true
      timeout_seconds: 5
    - matcher: "run_sql_query"
      command: python3 /shared/hooks/check_table_permissions.py
      block_on_nonzero: true
      timeout_seconds: 5
```

Hook script receives the tool name and args via `IAF_TOOL_INPUT` (JSON env var). Exit 1 to block:

```python
#!/usr/bin/env python3
import json, os, sys

tool_input = json.loads(os.environ.get("IAF_TOOL_INPUT", "{}"))
command = tool_input.get("command", "")

if "kubectl delete" in command:
    print(json.dumps({"blocked": True, "reason": "Destructive k8s operation blocked"}))
    sys.exit(1)

sys.exit(0)
```

**How it works:** `HookRunner.run_pre_tool()` fires synchronously before every tool call, before the HITL gate. A non-zero exit blocks the tool and surfaces the reason.

**Where approval appears:**
- Chat: `#approvals` tab (kernel source) + chat message inline
- Queue/background: `#approvals` tab (HITL source) + Queue Monitor awaiting_human status

---

### 4. Prompt instructions in SKILL.md body
**Use when:** You want the agent to ask when **uncertain** or when the situation is ambiguous. Not a hard block — a guideline for the LLM.

```markdown
## When to ask for human input
- If the user's request is ambiguous and could mean two different actions, ask before proceeding.
- If you are about to modify more than 10 records, confirm the scope first.
- If you encounter an unexpected error, report it rather than retrying silently.
```

**How it works:** The LLM reads these instructions and decides when to ask. This produces a conversational question back to the user — not a formal approval gate.

**Where approval appears:** Chat message only (no approval record created).

---

## Decision Guide

```
Is the trigger a business rule (amount, action name, entity type)?
  → approval_rules: in SKILL.md

Is the trigger a specific command pattern (regex on tool args)?
  → hitl: in config.yaml

Does the trigger need real logic (DB lookup, API call, ACL check)?
  → PreToolUse hook script

Is it about agent uncertainty or ambiguous user input?
  → Prompt instructions in SKILL.md body
```

---

## Where Approvals Surface — Full Picture

| Mechanism | Chat inline | `#approvals` tab | Queue Monitor awaiting_human |
|---|---|---|---|
| Write intercept (write_file / rm) | ✓ | ✓ kernel source | ✗ |
| PreToolUse hook block | ✓ | ✓ kernel (chat) / HITL (queue) | ✓ queue only |
| HITL gate patterns/keywords | ✓ | ✓ kernel (chat) / HITL (queue) | ✓ queue only |
| `request_human_approval` tool | ✓ WS + HTTP | ✓ HITL source (WS + queue) | ✓ queue only |

For Mission Mode Workstreams, approving an item resumes the worker in the
background. The resumed answer is persisted back onto the Workstream item as
the visible `last_result_summary`, the approval decision plus resumed answer is
stored in `resolution`, and a `hitl_resume` row is appended to the item's
structured execution ledger. The Workstream Detail page can therefore show the
post-approval result even when the original chat WebSocket is not connected.
Workstream-linked approvals also create a non-blocking Knowledge Manager
candidate with `source="hitl_feedback"` and `status="pending_review"`. A note
from the approver becomes explained precedent; a decision without a note becomes
observed precedent from the approval reason and item context.

---

## The `#approvals` Tab

**URL:** `http://localhost:8081/dashboard/v2#approvals`

This is the **primary approval action UI**. It merges two sources into one unified table:

- **HITL source** (purple tag) — approvals from `request_human_approval` tool and HITL gate in queue/auto_run mode. Backed by Redis (`approval_store`). Persists across server restarts.
- **Kernel source** (blue tag) — approvals from hook blocks and HITL gate in chat mode. Backed by in-memory `agent.pending_action`. Lost on server restart.

**Columns:** Urgency | Source | Reason/Operation | User | Skill | Age | Rule | Actions (✓ ✗)

**Detail panel:** Full context, SLA countdown bar, notes textarea, Approve / Reject / Escalate buttons.

**History tab:** All resolved approvals — Status, Reason, User, Skill, Decided By, Duration.

**To action an approval:** Click a row → detail panel opens → add an optional note → click Approve or Reject.

**Real-time chat notification:** The moment an approval is resolved (from this tab
or anywhere), `resolve_hitl_approval` pushes an `hitl_approval_resolved` event to
the *originating* user's chat session via `chat_registry.send_to_user` (keyed by
tenant+user). A user waiting in chat therefore sees the approve/reject outcome
immediately — the inline Approve/Reject buttons clear and a toast shows the
decision and approver — independently of, and ahead of, the slower background
resume. This also covers reject / skip-resume paths that never emit a resume
result. Delivery is best-effort: a disconnected chat socket never blocks
resolution (the dashboard broadcast and background resume still run).

---

## Queue Monitor — `awaiting_human` Status

**URL:** `http://localhost:8081/dashboard/v2#command-center` → click `awaiting human` filter

This is the **queue job status view**, not the primary approval UI. It shows queue items (`cc_queue`) that are paused waiting for human input.

An item appears here when:
1. A background queue job hits the HITL gate (pattern match in `config.yaml hitl:`)
2. A background queue job's agent calls `request_human_approval` tool
3. A background queue job is blocked by a PreToolUse hook

The Approve/Reject buttons inside the item detail panel call the same `/api/hitl/{id}/resolve` endpoint as the `#approvals` tab. Both views can action the same item — actioning in one automatically removes it from the other.

**Key difference from `#approvals` tab:** Queue Monitor shows all job statuses (queued, running, done, failed, dlq). The `awaiting_human` filter is one of those statuses. It does not show chat-session approvals.

---

## Approval Urgency and SLA

Set via `approval_rules` in SKILL.md or hardcoded to `high` for gate/hook blocks.

| Urgency | Default SLA | SLA bar colour |
|---|---|---|
| low | 480 min (8h) | green |
| medium | 120 min (2h) | green |
| high | 30 min | amber |
| critical | 10 min | red → flashing |

SLA countdown is visible in the `#approvals` tab detail panel. Items exceeding SLA are sorted to the top.

---

## Configuring HITL per Agent

All HITL configuration lives in one file per agent:

```
enterprise_root/tenants/company/agents/<agent_name>/config.yaml
```

No code changes required. Server restart picks up config changes.

---

## What Happens After Approval

**Chat path (kernel source):**
User clicks Approve/Reject (or types `approve`/`yes`/`no`/`reject`) → `agent.execute_approved_action()` / `agent.reject_pending_action()` → the held tool runs and, on the warm path, the **turn continues to completion** (see "Interactive tool-block HITL" below for warm-vs-cold resume semantics).

**HITL path (HITL source):**
Operator clicks Approve/Reject in `#approvals` tab → `/api/hitl/{id}/resolve` called → agent state loaded from Redis checkpoint → a **service principal** (`service:hitl_resume`) is created with the originating `user_id` and wired via `set_entitlement_context()` → approval lifecycle hooks fire (`OnApprovalResolved`, `BeforeApprovalResume`, `AfterApprovalResume`) → the resume path chooses the correct continuation mode. If the checkpoint contains a concrete `pending_tool_call` / `context.resume_kind == "stream_intercept"`, approval runs the exact saved tool call via `agent.resume_approved_tool_call()` and rejection calls `agent.reject_pending_tool_call()`; the LLM is not asked to reconstruct the approved side-effect. Business approvals without a concrete pending tool call keep the existing `[HUMAN DECISION] APPROVED/REJECTED by {user}. Note: {note}` natural-language continuation. If `BeforeApprovalResume` blocks, the agent is not resumed, the checkpoint is cleaned up, and chat receives a blocked-resume message.

Approved business-policy resumes also include explicit replay-guard markers:
`Human approval was granted by ...` and `Approval decision: approve`. Blocking
PostTurn hooks can use those markers to avoid re-raising the same approval after
the human has already approved the policy gate.

**Queue HITL exact replay:**
Queue Monitor approvals follow the same replay contract. When a queue item pauses because a PreToolUse hook, HITL pattern, or tool governance block captured a concrete pending tool call, `/api/queue/hitl/{item_id}/respond` restores the checkpoint and executes the exact stored `pending_tool_call` on approval. It does not regenerate the command from the queue description or a human-decision prompt, so a stored endpoint such as `/payments/release` cannot be shortened or rewritten during resume. For shell/curl HTTP calls, the replay response is persisted as API evidence against the queue execution. If the replayed tool returns a structured API error envelope, the queue execution is marked failed and the result summary is normalized as a tool failure rather than retaining the approved-tool wrapper. Queue approvals that represent business decisions rather than a concrete tool call continue through the existing prompt-based workflow resume path.

> The service principal ensures that credential, MCP, DB, and curl audit gates remain enforced during the resumed execution — even though the resume path has no HTTP request context.
> If `AGENTOS_KERNEL_BACKEND=remote`, the resumed shell/file/Python call is sent
> to the signed kernel worker with the reconstructed service principal context;
> the HITL replay contract and visible approval behavior do not change.

**Mission Mode workstream path:**
Workstream approvals use approval-then-continue-work semantics. When a Mission Mode item pauses, its YAML status is `awaiting_human`. Approving the HITL row moves the item to `in_progress` and schedules the checkpointed worker resume. The resume prompt is explicitly anchored to the originating `workstream_name` + `mission_item_id`, the YAML item description, acceptance criteria, and scalar approval context, and the resumed turn runs in fresh mode with shared session memory disabled so nearby workstream items cannot bleed into the continuation. The item is marked `done` only after the resumed worker returns successfully. If the resumed worker needs another governed tool call or business approval, the new approval is checkpointed and the same item returns to `awaiting_human` with the new `escalated_approval_id`. If resume fails, is blocked by `BeforeApprovalResume`, or the checkpoint is missing, the item is marked `failed` with a bounded reason. Rejecting the approval marks the item `failed` and does not run the worker. This keeps workstream completion aligned with actual post-approval side effects rather than the approval click alone.

---

## Admin Delete And Discard — Destructive Lifecycle

Approve and reject are the normal, auditable resolution paths: they run or refuse
the held side effect and append a resolved record to tenant history. Delete and
discard are **admin-only destructive** operations that remove an approval without
producing a resolved outcome, so they must be used deliberately.

- `DELETE /api/approvals/{user_id}` (discard a pending kernel action) drops the
  held tool call, clears the durable stream-intercept row, and persists the
  cleaned session state so a Redis reload cannot resurrect it. The action is
  **never executed** and no reward/history "resolved" record is written.
- `DELETE /api/hitl/{approval_id}` (discard a pending HITL approval) removes the
  approval record, its pending-set entry, and its checkpointed agent state.
- `DELETE /api/hitl/history/{approval_id}` removes a single already-resolved entry
  from tenant HITL history.

**Authorization and tenant scoping.** All three require an admin role *and* are
bound through `require_scoped_identity`, so the effective `tenant_id`/`agent_id`
come from the caller's principal and allowed-tenant set — an admin scoped to one
tenant cannot target another tenant's approvals by passing a foreign id. The HITL
discard additionally re-checks that the stored approval belongs to the caller's
resolved tenant before deleting.

**Pending-only, atomic with resolution.** Discarding a pending HITL approval only
succeeds while the record is still `pending`. The status check and deletion run as
a single server-side Redis compare-and-delete, mirroring the resolve path's
compare-and-set. A resolved approval is therefore never dropped, and a concurrent
resolver cannot interleave — exactly one of {resolve, discard} wins, so history and
resume checkpoints stay consistent.

**Audit implications.** Because discard produces no resolved record, it is not a
substitute for approve/reject when a decision must be traceable. History deletion
is irreversible and removes the audit entry for that approval; restrict it to
data-hygiene cleanup, not routine operations.

---


When a **PreToolUse hook or the kernel danger-check blocks a tool call mid-turn** (PreToolUse mechanisms #2/#3 above), the interactive "stream-intercept" path pauses the turn. This is distinct from the `request_human_approval`/cron/workstream path (which re-plans on resume): here the model already chose a concrete call, so resume must run **that exact call**.

**Two resume modes:**

- **Warm (same instance still in memory) — continues the turn.** Approving runs the held call *and* lets the model finish the task, pausing again if it hits another gated call (multi-step HITL). Implemented via the native runtime checkpoint (`NativeReactRuntime.pending_resume` → `resume_and_continue`) and `agent._resume_native_turn`. Held shell/`write_file` calls run with kernel `confirmed=True` (`agent._execute_held_tool_call`) so they don't re-trip the auto-run gate.
- **Cold (after a restart / session eviction) — executes the held call once.** Each interactive block also writes a **durable** approval record: governance calls `_set_stream_intercept_approval`, setting `agent.approval_pending` with `context.resume_kind == "stream_intercept"` plus the routing keys and a **bounded, redacted preview**; the full executable call rides in the checkpointed `agent_state.pending_tool_call`. On resume, `_resume_agent_from_hitl_sync` branches on `resume_kind`: for `stream_intercept` it calls `agent.resume_approved_tool_call()`/`reject_pending_tool_call()` (runs the exact saved call), otherwise the unchanged `[HUMAN DECISION]` natural-language path. Cold resume runs the single held call and returns its result — it does **not** continue the turn (the in-RAM message state is gone).

**Endpoint behavior (`POST /api/approve`):** warm in-memory pending is resolved first; if the instance is gone, it resolves durably by `approval_id` (echoed by the client in the `pending_approval` payload) or by scanning the user's pending stream-intercept rows (409 if ambiguous), delegating to `/api/hitl/{id}/resolve`.

**Lifecycle / cleanup:** after a warm approve, the endpoints reconcile the durable row (`reconcile_stream_intercept_durable`): resolve+delete the consumed record, re-checkpoint if the turn re-paused on a new call, and persist the cleaned session state. Stream-intercept rows are **filtered out of the business-HITL `#approvals` view** (`/api/hitl/pending`) — they surface only via the chat `pending_approval` buttons and the kernel approval queue. `checkpoint_hitl_if_needed` is idempotent by `approval_id` (won't re-stamp an existing row) and returns `None` for stream-intercept rows so they don't render a duplicate business-HITL card.

Redis-backed approval/session/queue components log connection state without
printing `REDIS_URL`, credentials, or query parameters. Keep Redis credentials
in the deployment secret manager.

Strict API replicas must start with shared Redis sessions connected. This keeps
pending actions and conversation checkpoints consistent when a later request
lands on another replica. `/health/ready` returns 503 if that session dependency
is unavailable; local non-strict development retains in-memory fallback.

---

## Summary Table — Which File to Edit

| Goal | File |
|---|---|
| Approve invoices above a threshold | `SKILL.md` → `approval_rules.thresholds` |
| Always approve before deleting a vendor | `SKILL.md` → `approval_rules.always_require` |
| Block kubectl delete / rm -rf | `config.yaml` → `hitl.shell_patterns` |
| Block SQL DELETE/UPDATE | `config.yaml` → `hitl.sql_patterns` |
| Block all tools in a sensitive skill | `config.yaml` → `hitl.hitl_skills` |
| Block curl DELETE on k8s | Hook script → `ccdops_block_writes.py` |
| Check ACL before querying a table | Hook script → custom Python |
| Agent asks when uncertain | `SKILL.md` body → prompt instructions |
