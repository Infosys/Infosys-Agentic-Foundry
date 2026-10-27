# Dashboard V2 Help

Dashboard V2 is the operations control surface for AgentPro. It gives visibility into active sessions, approvals, knowledge, cron jobs, traces, queue/command-center work, governance, memory, and platform operations.

## Ask Twin Context

Ask Twin on Dashboard V2 receives:

- current dashboard tab/page
- selected agent
- summary KPIs
- kernel and HITL approval counts
- command-center queue state when visible
- selected entity/detail context when available

Use this context to answer questions like "what needs attention?", "what does this approval count mean?", or "what tab should I use?"

## Main Areas

- Overview: live operational summary and needs-attention signals. The Control
  Plane Snapshot's `traces_today` and the Needs Attention error items are read
  live from the active trace store (Postgres or SQLite per `TRACE_BACKEND`), not
  a hardcoded value, so they reflect real activity as it happens.
- Approvals: pending HITL decisions and history. History and the per-user Stats
  numbers are scoped to the signed-in user (admins see the whole tenant). The
  cross-user **Top Requesters** leaderboard on the Stats tab is admin-only; a
  regular user sees only their own statistics, which refresh live on a poll.
- Knowledge/Memory: knowledge records, ontology, entity usage, search, sessions
- Cron: scheduled jobs and run history
- Traces: execution history and reasoning details
- Queue/Command Center: autonomous job processing, claim backend, worker
  heartbeat, and stale-lease health
- Governance/Policy Control: business controls, effective access, and policy status
- Recovery Readiness: admin-only isolated restore verification, RPO/RTO
  measurements, report history, and per-check evidence
- RL/Eval Center: standalone page launched from Dashboard V2 for dataset health,
  signal richness, reward/preference visibility, and export readiness

When `RL_CAPTURE=true`, dashboard-visible feedback, HITL, queue, and workstream
signals are mirrored to the independent RL/eval store through the neutral
`iaf_agent_skills.capture_events` bridge. Dashboard workflows do not write
training-format records directly.

## Trace Explorer

The **Traces** area lists recent executions with their status, skill, user, query,
spans, tokens, cost, and duration; click a row for the full waterfall and
reasoning detail.

- **Status** covers success, error, awaiting human, cancelled, running, and stale.
  A run stopped from the chat Stop button is finalized as **cancelled** — it is no
  longer left hanging as *running* with a blank skill.
- **Filters** — the **User** and **Skill** filters are searchable multi-select
  dropdowns: type in the search box to narrow the list, then tick any number of
  values. The options are the distinct users and skills actually present in the
  trace store, scoped to you: a regular user only ever sees and filters their own
  activity, while an admin sees everyone's. The **Status** dropdown filters by a
  single status. Filters combine as AND across the three; multiple ticks within
  one filter are OR.
- **User names** show a readable display name or email; service/automation
  principals show a friendly label (e.g. "Service (cron)"); ids that cannot be
  resolved show "Unknown user". The raw internal id is never displayed — in the
  User filter it is only the hidden option value used to filter.
- **Pagination** — results load 50 at a time. The footer shows "Showing X–Y of N",
  the current page number, and Prev/Next controls; the header shows the total
  number of matching traces. Changing any filter returns to the first page.

## Recovery Readiness

The Platform group includes **Recovery Readiness** when an administrator needs
to inspect recovery evidence. The page shows the latest overall result,
tenant-data RPO, service RTO, passed/failed/pending checks, and historical
reports. Selecting **Run verification** performs read-only checks against the
server-configured `RECOVERY_VERIFICATION_ROOT`; the UI does not accept arbitrary
filesystem paths.

An offline verification validates the backup manifest and checksums, required
tenant assets, YAML/JSON/JSONL parsing, SQLite integrity, and operational
definition inventory. When the operator configures an explicitly confirmed live
cell, a dedicated recovery Redis endpoint, and a secret-managed token, the same
Run action also performs non-mutating API readiness, tenant-read, and signed-file
probes. Scheduler uniqueness and queue exactly-once execution remain warnings
until sanitized live drill evidence is attached. The page lists available
evidence bundles, shows whether scheduler, queue, signed-file, and SLO proof are
present, and lets an admin attach an evidence id to the next verification run.
The attached evidence can promote live checks to pass/fail while keeping tokens,
Redis URLs, signatures, and raw logs out of the report. A warning result must
not be interpreted as full recovery certification. Ask Twin receives the visible
report summaries, targets, evidence status, and selected report context from
this tab.

The RL/Eval Center export card also acts as the Fine-tune Export Center. It can
filter generated JSONL datasets by evaluator verdict, golden-set id, and ISO date
range before download. When reviewers approve Trace Value Router recommendations
for `model_training`, exports can also be filtered to that approved training pool.
Export downloads use the signed-in session token and save the returned JSONL
Blob directly. Authorization or missing-file errors are shown in the page
instead of opening a raw error response in a new tab.

Each format card shows **eligible now** for the current filters separately from
the row count of the **last export**, which is a historical snapshot. Approving
Trace Value items for model training offers an **Open Filtered Export** link that
preselects the approved model-training route. Reviewers still click Export to
materialize a fresh file. Golden promotion defaults to the first configured
golden set and remains disabled until both a target and actionable trace rows are
selected.

An eligible Export action immediately reports that preparation started and
shows the final success/error toast. A format with zero eligible rows displays
**Why unavailable?**; selecting it explains that the current filters produced
no rows rather than silently ignoring the click.

## Queue Monitor

The Queue/Command Center page shows the active claim backend, online workers
versus expected workers, stale claim count, and current in-flight count above the
item list. SQLite deployments should show one worker at most. Postgres
deployments use `CC_QUEUE_STORAGE_BACKEND=postgres` and fenced leases so multiple
queue workers can claim different items without allowing a stale worker to
complete an item after its lease is replaced.

If `stale_claims` is non-zero, at least one routing/running item has an expired
lease and should be reclaimed by the queue worker reaper or investigated before
scaling further. Worker counts come from shared heartbeats, so API replicas can
show queue health even though they do not process queue items.

## Policy Control

The Policy Control tab manages business-friendly policies that compile into the
same lifecycle hook runtime used by Skill Builder. The event dropdown is sourced
from the runtime hook catalog, with metadata for gateable events, observe-only
events, and HITL-safe events.

Use `decision: approve` when a matching policy should reach a human. Published
approval policies generate blocking hooks with `on_block: hitl` and an `approval`
payload, so the existing HITL approval queue and checkpoint resume path handle the
decision.

The Create With Assistant panel accepts plain-English policy intent and runs the
`policy_authoring` skill to draft managed Policy Control YAML. The draft fills the
existing form, populates the YAML view, generates sample simulation context, and
still requires Validate/Simulate plus admin Save or Publish before any hook is
written. While drafting, the assistant panel shows a bright animated status row so
reviewers know the Policy Authoring skill is working.

The Policy Definition window has both Form View and YAML View. YAML edits are
parsed and normalized by the backend before they are applied to the form, so the
same deterministic validation and simulation gates are used regardless of how the
policy was authored. YAML View displays a readable bundle with both the managed
`policy:` and the compiled `hooks:` preview, including generated `on_block: hitl`
for approval policies.

## Knowledge Manager

The Knowledge tab loads the paginated knowledge table, stats, and extraction
status first. Context-file choices for the `Written To` picker are loaded lazily
when a reviewer edits a knowledge record or opens the confirm flow, so opening
the tab does not block on indexing context files. Long suggested and selected
target paths wrap inside the confirm modal so reviewers can see the full
destination without horizontal overflow.

The list, stats, and extraction status calls use a lightweight read-only store
over the agent memory files, so opening the Knowledge tab does not need to
cold-start the full agent runtime after a server restart.

The Learning Signals panel summarizes pending-review knowledge, thumbs-down
responses, corrected answers, eval failures, and Trace Value Router
recommendations. Trace-value actions deep-link to `/rl-capture/workbench` with the
exact trajectory preselected in the Evaluate stage; final confirm/reject decisions
still happen in the governed Knowledge Manager table or Trace Value bulk-promotion
flow.

The linked learning surfaces are branded **Agent Training Studio** and **Agent
Training Workbench**, with the subtitle **Part of Topaz Fabric**. Their shared
theme selector offers Light, Hybrid, and Dark modes; Hybrid uses navy navigation,
softly tinted tiles, and high-contrast interactive states.

In Agent Training Studio, Trace Value queues support explicit row selection and
destination-specific bulk actions. Skill/context and memory learnings move to
this Knowledge Manager as `pending_review`; golden cases move to Curate, while
approved training traces move to Export. The Workbench remains a one-trajectory
review surface and adds server-side filters for assessment, destination, score,
and promotion status.

The same picker now includes convention-discovered Knowledge Bundle pages under
`/shared/knowledge/<bundle_id>/`, grouped as `Knowledge Bundle › <bundle_id>`.
Memory topic files remain available under groups such as `Memory › Skills` and
`Memory › Org State`. Skill definitions are available under
`Skill Definition (Advanced)` for explicit reviewer overrides to
`skills/<skill>/SKILL.md`; choosing one shows a warning because it changes future
skill behavior. Skill-definition publication is blocked unless the record has
the same skill scope as the selected target.

**Confirm & Write** reports the exact file that was published. The record's
`written_to` field is saved only after that write succeeds; if publication fails,
the dashboard shows a warning rather than a successful file-write toast.
**Confirm without writing to file** is an explicit record/index-only action.

**Bulk Confirm & Route** confirms every selected record and auto-publishes only
safe deterministic suggestions: entity memory, source context, and
convention-matched bundle pages. The completion toast separately reports
published, record-only, publication-failed, and confirmation-failed counts.
LLM-only or unmatched suggestions remain confirmed record-only for manual
routing. All knowledge mutations carry the currently selected agent and user
identity.

## Themes

Dashboard V2 supports Dark and Light visual modes. Light mode uses a brighter executive content surface with readable hover states across Agent Control Plane and Command Center lists.

## Enterprise security

Knowledge, Memory, RL Capture, and queue APIs use the authenticated tenant
principal and resource entitlements. The external queue ingest surface requires
`X-API-Key` in strict mode. Dashboard query parameters select resources but
cannot override the JWT tenant or user identity.
