# Hook Event Reference

Every hook event supported by `iaf_agent_skills.hook_runner.HookRunner` is
listed below. Each entry describes:

- **When it fires** — the runtime callsite
- **Context payload** — keys available in the `ctx` dict passed to internal
  Python handlers (and corresponding `IAF_*` env vars for external shell
  hooks)
- **Gateable** — whether returning `HookResult(blocked=True)` actually halts
  the protected operation, or whether the event is observe-only
- **Fail policy semantics** — what happens when the hook times out / raises

All events inherit the parent `trace_id` via `build_hook_context`. Hooks
must NOT mint a new root trace; child spans are fine.

Setting the env var `CAPABILITY_HOOKS_ENABLED=false` (read at process start)
short-circuits every `run_*` method to a no-op without touching kernel
hard-gates. Use it for production rollback or A/B baseline comparison.

---

## Phase 1 events (original release)

### `PreToolUse`
- **When:** before every LLM-emitted tool call (also fires from
  `agent_os.kernel._cmd_get_credential` for direct kernel credential
  lookups, see Batch 3).
- **Gateable:** yes. Returning `blocked=True` aborts the tool call.
- **Context:** `tool_name`, `tool_input`, `current_skill`, `tool_subtype`
  (Batch 3 — coarse classification of shell commands: `curl`, `kubectl`,
  `ssh`, `get_credential`, etc.), plus the standard correlation fields.
- **Fail policy:** see [Batch 1 — fail_policy semantics](#fail_policy-semantics).
- **Fires `OnBlocked`** on deny (Batch 1).

### `PostToolUse`
- **When:** after every tool returns or errors, from `trace_callback.on_tool_end`
  and `on_tool_error`. Also from `kernel._cmd_get_credential` for direct
  kernel paths (Batch 3).
- **Gateable:** no — fire-and-forget on a daemon thread.
- **Context:** `tool_name`, `tool_input`, `tool_output`, duration, error.

### `PostTurn`
- **When:** synchronously, before the agent response reaches the caller.
- **Gateable:** yes. Returning `blocked=True` replaces the response with a
  compliance error string. A non-None `response` field replaces the
  outgoing text. Fires `OnBlocked` on deny.

### `PostSampling`
- **When:** fire-and-forget on a daemon thread at end of background
  learning extraction. Used for telemetry export / notification.
- **Gateable:** no.

### `PreStep` / `PostStep` / `OnExecutionFailure`
- **When:** orchestrator / workflow / parallel step boundaries.
- **`PreStep`:** gateable. Returning `blocked=True` skips the step and
  records the reason in the step log so the manager LLM can adapt.
  Fires `OnBlocked` on deny.
- **`PostStep`:** synchronous. Can return a `feedback` string appended to
  the OrchestratorStep + surfaced to the manager LLM on its next decision.
- **`OnExecutionFailure`:** fire-and-forget on step exception. Use for
  compensation / saga rollback / alerting.

---

## HITL approval events

### `OnApprovalResolved`
- **When:** after an HITL approval decision is recorded in
  `routers/approvals.py`.
- **Gateable:** no — observe-only.
- **Context:** `approval_id`, `decision`, `decided_by`, `decision_note`,
  `reason`.

### `BeforeApprovalResume`
- **When:** before restoring and resuming an HITL checkpoint.
- **Gateable:** yes. Returning `blocked=True` cancels the resume. Fires
  `OnBlocked` on deny.
- **Context:** same as `OnApprovalResolved`.

### `AfterApprovalResume`
- **When:** after a resume attempt finishes.
- **Gateable:** no — observe-only.
- **Context:** adds `resume_status` and optional `error_msg`.

---

## Batch 1 — `OnBlocked` (deny broadcast)

### `OnBlocked`
- **When:** AFTER any blocking-capable hook denies (`PreToolUse`,
  `PostTurn`, `PreStep`, `BeforeApprovalResume`, or the Batch 1 credential
  fail-closed gate).
- **Gateable:** no — observe-only. Even if every observer fails, the
  original deny still propagates.
- **Context:** standard correlation fields plus
  `blocked_event` (the event that denied), `blocked_hook_id`,
  `blocked_reason`.
- **Use case:** single-seam audit + Slack/email alerts on any deny without
  having to wrap every `PreToolUse` manually.

---

## Batch 2 — turn lifecycle

### `BeforeTurn`
- **When:** at the top of `SkillAgent.run()`, after session indexing.
- **Gateable:** yes. Returning `blocked=True` short-circuits the turn
  with a "Turn blocked by policy hook: <reason>" string. `OnTurnEnd`
  still fires so observers see consistent lifecycle.
- **Context:** standard + `query`, `execution_mode="react"`, `entrypoint`.

### `OnTurnEnd`
- **When:** after `PostTurn` completes (or after `BeforeTurn` denied).
- **Gateable:** no — observe-only.
- **Context:** `response` (post-PostTurn), `error_msg` ("blocked_by_hook"
  when applicable).

### `OnError`
- **When:** from the LLM-invocation exception handler in `agent.run()`.
  Fires for rate-limit fallback paths AND fatal paths.
- **Gateable:** no — observe-only.
- **Context:** `error_msg`.

### `BeforeModelCall`
- **When:** right before `_run_with_sufficiency()` invokes the model.
- **Gateable:** yes (caller currently treats as observe-only — promotion
  to blocking is a future decision).
- **Context:** `model_role` (e.g. `"primary"`), `model_name`.

### `AfterModelCall`
- **When:** after `_run_with_sufficiency()` returns successfully.
- **Gateable:** no — observe-only.
- **Context:** `model_role`, `model_name`, `prompt_tokens`,
  `completion_tokens`, `duration_ms`. Token counts come from the per-
  request LLM budget so they cover ALL calls in the sufficiency loop.

### `AroundModelCall`
- **When:** wraps the model provider call itself, via
  `model_call_pipeline.py`'s `_compose_around_hooks` — not the same
  dispatch path as `BeforeModelCall`/`AfterModelCall`.
- **Gateable:** yes. Each registered hook receives a `next_call`
  continuation and can call it, replace its result, or raise
  `ModelCallBlocked` to short-circuit the call entirely. Hooks compose
  onion-style: the highest-priority hook is outermost.
- **Context:** the standard model-call context plus `next_call`.
- **Fail policy:** an exception from a `fail_policy="closed"` hook denies
  the call; `"open"` (default) lets the next hook (or the real provider
  call) proceed.

---

## Batch 2 — schedule lifecycle (cron)

### `BeforeScheduleFire`
- **When:** before `agent.run()` inside `state._cron_executor`, after the
  service principal is wired.
- **Gateable:** yes. Returning `blocked=True` SKIPs the firing — the
  cron executor records "Skipped by BeforeScheduleFire hook: <reason>"
  and still fires `AfterScheduleFire` so dashboards see the skip.
- **Context:** `job_name`, `cron_expr`, plus correlation fields.

### `AfterScheduleFire`
- **When:** on the success path of `_cron_executor`.
- **Gateable:** no — observe-only.
- **Context:** `job_name`, `duration_ms`, `response` (truncated to 500).

### `OnScheduleError`
- **When:** on exception in `_cron_executor`. Fires before re-raise.
- **Gateable:** no — observe-only.
- **Context:** `job_name`, `error_msg`, `duration_ms`.

---

## Queue execution lifecycle

Phase 1 is observe-only / fail-open for all six events — even the `Before*`
names do not block queue execution today; callers deliberately ignore any
deny result (`HookResult.blocked`). These fire only once a queue item has a
resolved `SkillAgent`, so skill-scoped hooks still apply; pre-skill
received/routed events are structured audit records, not `HookRunner` events.

### `BeforeQueueItemStart`
- **When:** before a queue item begins executing.
- **Gateable:** no (today) — a `HookResult` is returned but the caller
  ignores `blocked`.
- **Context:** `item_id`, `exec_id`, `skill_name`, `queue_status="running"`,
  `priority`, `retry_count`, `payload_preview`.

### `AfterQueueItemComplete`
- **When:** after a queue item finishes successfully.
- **Gateable:** no — observe-only.
- **Context:** `item_id`, `exec_id`, `skill_name`, `queue_status="done"`,
  `duration_ms`, `result_summary`, `payload_preview`, `evidence_trace_id`,
  `evidence_count`.

### `OnQueueItemError`
- **When:** a queue item raises.
- **Gateable:** no — observe-only.
- **Context:** `item_id`, `exec_id`, `skill_name`, `queue_status="failed"`,
  `error_msg`, `error_type`, `retry_count`, `will_dlq`, `duration_ms`,
  `payload_preview`.

### `BeforeQueueRetry`
- **When:** before a failed item is requeued for another attempt.
- **Gateable:** no — observe-only, fire-and-forget (`-> None`).
- **Context:** `item_id`, `exec_id`, `skill_name`, `queue_status="queued"`,
  `retry_count`, `error_msg`, `error_type`, `payload_preview`.

### `OnQueueDLQ`
- **When:** a queue item is moved to the dead-letter queue after exhausting
  retries.
- **Gateable:** no — observe-only.
- **Context:** `item_id`, `exec_id`, `skill_name`, `queue_status="dlq"`,
  `failure_reason`, `error_msg`, `error_type`, `retry_count`,
  `will_dlq=True`, `payload_preview`.

### `OnQueueHITLPending`
- **When:** a queue item is now waiting on a human approval decision.
- **Gateable:** no — observe-only.
- **Context:** `item_id`, `exec_id`, `skill_name`,
  `queue_status="awaiting_human"`, `approval_id`, `approval_reason`
  (the prompt shown to the approver), `payload_preview`.

---

## Batch 5 — background-task instrumentation (Phase 3b)

These events fire from non-tool background code paths (implicit learning,
self-evolution) that bypass the ReAct loop. Callers SHOULD pass session
context when available; when absent the context carries
`background_context_missing=True` so auditors can find orphan writes.

### `OnKnowledgeEntryPending`
- **When:** from `SkillAgent._analyze_implicit_feedback` per returned signal.
- **Gateable:** no — observe-only.
- **Context:** `skill_name`, `entry_kind`, `entry_preview` (≤500 chars).

### `OnMemoryWrite`
- **When:** from `SkillAgent.append_learning` after the underlying write.
- **Gateable:** no — observe-only.
- **Context:** `memory_store` (learning_type), `memory_key` (path),
  `value_preview` (≤500 chars).

### `OnSkillGapDetected`
- **When:** from `routers/evolution.py` after a self-evolution analysis
  reports gaps. One event per gap.
- **Gateable:** no — observe-only.
- **Context:** `skill_name`, `gap_summary`, `severity`.

### `OnSelfEvolutionPass`
- **When:** once per self-evolution analysis from `routers/evolution.py`.
- **Gateable:** no — observe-only.
- **Context:** `pass_id` (job_id), `skills_analyzed`, `gaps_found`,
  `duration_ms`.

### `OnBackgroundTaskError`
- **When:** from `append_learning`, `_analyze_implicit_feedback`, or
  `self_evolution.analyze_*` exception paths.
- **Gateable:** no — observe-only.
- **Context:** `task_name`, `error_msg`.

The `iaf_agent_skills.background_hooks` module exposes
`fire_on_self_evolution_pass`, `fire_on_skill_gap_detected`, and
`fire_on_background_task_error` helpers so background code can fire
events without holding a `SkillAgent` reference.

---

## Mission Mode lifecycle

Mission Mode is the workstream grinder — a single workstream activation runs
across many cron iterations. These three events fire once per workstream
activation (`BeforeMissionStart`), once per item that exhausts its retries
(`OnMissionItemFailed`), and once per workstream reaching a terminal state
(`OnMissionComplete`). Per-item start/end overlaps with `BeforeTurn`/
`OnTurnEnd`, so there are no dedicated per-item events here.

### `BeforeMissionStart`
- **When:** before a workstream's first activation.
- **Gateable:** yes. The caller may halt the first activation on deny.
- **Context:** `workstream_name`, `owner`, `total_items`, `skill`.

### `OnMissionItemFailed`
- **When:** a workstream item exhausts its retries.
- **Gateable:** no — observe-only.
- **Context:** `workstream_name`, `item_id`, `attempts`, `error_msg`.

### `OnMissionComplete`
- **When:** a workstream reaches a terminal state (done, or no items left
  to retry).
- **Gateable:** no — observe-only.
- **Context:** `workstream_name`, `duration_total_sec`, `items_done`,
  `items_failed`, `items_escalated`.

---

## Research workflow events

Fired by `research_orchestrator` + `research_decomposer` skills and the
`/api/workstreams` POST handler. These exist so tenant governance can
intercept research-specific moments (low-confidence decompositions,
expensive workstream launches) without filtering through generic
`PreToolUse`.

### `OnDecompositionComplete`
- **When:** after `research_decomposer` returns its JSON. The orchestrator
  emits this BEFORE drafting the workstream YAML.
- **Gateable:** yes — a blocking handler with `fail_policy=closed` can
  deny low-confidence decompositions to prevent expensive downstream
  workstreams. Default observe-only.
- **Context:**
  - `question` — the original research question (truncated to 500 chars)
  - `angles` — list of `{id, description, target_skill, rationale}`
  - `target_skills` — flat list of skill names selected (`["ccdops", "fa_ap", ...]`)
  - `confidence` — `HIGH | MEDIUM | LOW`
  - `confidence_reason` — one-sentence rationale (truncated to 500 chars)
  - `decomposer_model` — model name that ran the decomposition
  - `tokens_used` — token count for the decomposer call
- **Typical handler:** governance ("deny if confidence == LOW AND
  question matches financial DOA tiers"), learning ("persist successful
  decomposition patterns to memory for future reuse"), telemetry
  ("emit to cost dashboard").

### `OnResearchWorkstreamCreated`
- **When:** from the `/api/workstreams` POST handler, AFTER the YAML
  validates but BEFORE it's committed to disk. Only fires when
  `meta.source == "research_orchestrator"` is set on the incoming
  payload.
- **Gateable:** yes — a blocking handler can deny the launch (over budget,
  exceeds tenant cap, off-policy skill assignment). Default observe-only.
- **Context:**
  - `workstream_name` — the proposed workstream name
  - `source_question` — the originating research question (truncated to 500 chars)
  - `parent_session_id` — chat session that triggered the research
  - `parent_trace_id` — inherited trace_id for lineage
  - `item_count` — number of items in the workstream
  - `estimated_cost_usd` — orchestrator's pre-flight cost estimate (best-effort)
  - `target_skills` — list of worker skills the items will use
  - `decomposer_confidence` — confidence rating from the upstream decomposer
- **Typical handler:** budget guard ("deny if tenant's monthly spend +
  estimated_cost > cap"), per-tenant scope guard ("deny if any
  target_skill is not in this tenant's purchased plan"), audit emit
  ("log the launch with lineage to the trace store").

Both events follow the standard hook contract — see
[`fail_policy` semantics](#fail_policy-semantics) below for what happens
when a blocking handler times out or errors.

---

## `fail_policy` semantics

Each `ExternalHook` and `InternalHook` carries a `fail_policy` field
(`"open"` | `"closed"`, defaults to `"open"`):

| Failure mode | `fail_policy="open"` (default) | `fail_policy="closed"` |
|---|---|---|
| External hook timeout (`subprocess.TimeoutExpired`) | Treated as non-blocking; the operation proceeds with a warning logged. | The operation is **denied** with reason "hook unavailable (fail_policy=closed): timeout after Ns". Fires `OnBlocked`. |
| External hook non-zero exit when `block_on_nonzero=False` | Non-blocking continue. | Denied with reason carrying the parsed stderr/stdout. |
| External hook exec error (subprocess fails to start) | Non-blocking continue. | Denied with reason "hook unavailable (fail_policy=closed): exec error: …". |
| Internal hook `handler(ctx)` raises | Non-blocking continue. | Denied with reason "hook unavailable (fail_policy=closed): internal error: …". |

Use `fail_policy="closed"` for security gates that MUST not silently allow
when the hook can't render an opinion (policy engine outage, credential
verifier crash). Use `"open"` for telemetry / notifications where the
operation should proceed even if the hook is broken.

---

## Hook ordering

Within an event:

1. Internal Python hooks fire first, in `(priority ascending,
   registration order)` order.
2. External shell hooks fire next, same ordering.
3. The first blocking hook to return `blocked=True` short-circuits — no
   later hooks run for the same event on this call.

> **Exception — step events.** `PreStep`, `PostStep`, and
> `OnExecutionFailure` run **external shell hooks first, then internal
> Python hooks** — the reverse of steps 1–2 above (`run_pre_step` /
> `run_post_step` / `run_on_exec_failure` iterate `self._external` before
> `self._internal`). All other events fire internal-first as described.

Set `priority` in the manifest (integer ≥ 0; lower = earlier) to control
the order between hooks at the same event.

---

## Authoring a hook

See [`docs/EXTENDING.md`](EXTENDING.md) for the full step-by-step guide
(handler signature, manifest fields, registration paths, feature-flag
behaviour, and how to write a custom capability).
