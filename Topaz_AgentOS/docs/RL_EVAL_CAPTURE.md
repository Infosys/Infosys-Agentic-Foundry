# RL/Eval Capture

AgentPro includes an opt-in, framework-neutral RL/eval capture layer under
`rl_capture/`. The layer records raw trajectories and judgment signals for
evaluation, SFT, rejection-SFT, DPO, KTO, RFT, and future model-migration
workflows. It does not train models or assign shaped rewards during capture.

## Runtime Flags

- `RL_CAPTURE` defaults to `false`. When `true`, REST/WebSocket chat turns and
  selected AgentPro operational outcomes are captured best-effort into the
  tenant RL database.
- `RL_REDACT` defaults to `true`. Secret-looking keys and sensitive text are
  masked before records are persisted.
- `RL_CAPTURE_REASONING` defaults to `false`. The first implementation stores
  reasoning references and previews already available in decision context, not
  hidden provider reasoning blobs.
- `RL_DB_PATH` optionally points to a custom database path. If unset, the
  default tenant path is used.

## Storage

The default database is:

```text
enterprise_root/tenants/{tenant}/shared/databases/rl.db
```

The SQLite store creates tables for:

- `trajectories`
- `trajectory_steps`
- `model_calls`
- `tool_calls`
- `observations`
- `candidate_outputs`
- `reward_events`
- `preference_signals`
- `evaluator_results`
- `trace_value_assessments`
- `trace_route_decisions`
- `shadow_runs`
- `exports`

Writes are best-effort and must never block or fail chat execution.

## Core Contract

The neutral core schema stores raw attributed records:

- `Trajectory` captures a turn or stitched session.
- `ModelCall` captures input/output messages, policy identity, token/cost
  metadata when available, and capture fidelity.
- `ToolCall` and `Observation` capture tool inputs, outputs, errors, and timing.
- `RewardEvent` stores raw labels such as `approve`, `reject`, `up`, `down`,
  `done`, `failed`, `awaiting_human`, or `dlq` bound to a `TargetRef`.
- `PreferenceSignal` stores references to preferred and dispreferred candidates;
  DPO rows are materialized only during export.
- `CandidateOutput` stores original, revised, corrected, rejected, approved, or
  shadow outputs so preference signals can reference stable candidates.

The core keeps AgentPro concepts out of the schema. AgentPro-specific mapping
lives under `rl_capture/adapters/agentpro/`.

Runtime code does not import RL adapters directly. AgentPro emits neutral capture
events through `iaf_agent_skills.capture_events`, the single lazy import boundary
outside `rl_capture/`. The bridge no-ops when `RL_CAPTURE=false`, suppresses all
adapter failures, and maps enabled events into the AgentPro RL adapter functions.
Automation-backed Workstreams still emit the same Workstream lifecycle labels
(`done`, `failed`, `retry`, and related item-action labels); the automation
runtime trace itself is stored in `automation_runtime.db`, not the RL schema.

## Private Learning Loop Registry

Tenant-owned eval suites and golden datasets live in the framework-neutral
`rl_capture/evals/` package. The core package is path-agnostic; the AgentPro
adapter resolves tenant paths under:

```text
enterprise_root/tenants/{tenant}/evals/{suite_id}.yaml
enterprise_root/tenants/{tenant}/golden_sets/{set_id}.jsonl
enterprise_root/tenants/{tenant}/eval_evaluators/{evaluator_id}/manifest.yaml
```

Suites can define target metadata, rubric overrides, assertion checks
(`exact`, `contains`, `not_contains`, `numeric`, `regex`), thresholds, and
judge budget controls. They can also reference an allowlisted Python evaluator
manifest. Python evaluators run in fresh subprocesses with JSON stdin/stdout,
sanitized environment, timeout, output-size limits, and best-effort resource
limits; this is for trusted tenant plug-ins, not hostile-code sandboxing. Studio
exposes CRUD endpoints under `/api/evals`, evaluator discovery/test endpoints,
and can promote an existing captured trajectory into a golden case. See
`docs/PRIVATE_LEARNING_LOOP.md`.

Suite execution is handled by `rl_capture/evals/runner.py`. The runner receives
a candidate producer from the AgentPro adapter, scores each golden case with
weighted rule/assertion/Python/judge components, stores run/case rows through
`rl_capture/store/eval_store.py` (using the injected AgentOS `StorageEngine`),
records manual promotion-gate decisions, and mirrors evaluator or shadow-eval
judgement signals into the existing RL store on a best-effort basis.

The RL Workbench (`/rl-capture/workbench`) surfaces this through its **Curate**
and **Test** stages, backed by `/api/evals/*` for suite editing, golden case
editing, evaluator testing, runs, case traces, trajectory promotion, and manual
promotion gates. Dashboard summaries still come from `/api/evals/dashboard/summary`.
`/api/evals/recommendations` exposes advisory model-role recommendations; model
routing changes only when the explicit `EVAL_ROUTER_ENABLED` opt-in is set.
Standalone cron jobs can run suites continuously with `skill_name: eval_suite`
and `task: <suite_id>`.

## First Slice

The current implementation captures completed chat turns passively:

- user query and final assistant response
- routed skill and routing metadata
- available trace/session IDs
- model/provider metadata when available
- summarized tool calls from decision context
- redaction metadata
- final assistant response as an `original` candidate output
- each `PolicyChatModel` provider invocation as an incremental `ModelCall`
  row when the model-call pipeline is enabled
- thumbs up/down as raw `RewardEvent` rows when the UI sends RL target IDs
- sync critique revisions as `PreferenceSignal` rows with original/revised
  candidates
- model-call policy audit outcomes as raw `model_call_policy` reward events
- async critique revisions as `PreferenceSignal` rows after the first response
  has already been delivered
- HITL approval creation, decision, resume success, blocked resume, follow-up
  pause, and error outcomes as raw `human_approval` rewards
- queue item queued/ingested/done/retry/DLQ/awaiting-human outcomes as raw
  `queue` rewards. These labels remain unchanged whether the Command Center
  claim backend is SQLite or Postgres fenced leases.
- workstream item and workstream run outcomes as raw `workstream` rewards
- failed, cancelled, and HITL-paused chat turns using the trajectory
  `terminal_status`
- incremental tool call and observation rows from the agent's tool-message
  boundary, before chat UI preview truncation
- hook pass/block/error outcomes as raw `hook` rewards when hook audit context
  carries a trace ID
- sufficiency-check evaluator results as `EvaluatorResult` rows when the
  iterative evaluator runs

`AGENTOS_KERNEL_BACKEND=remote` does not change the capture contract: tool-call
rows are still emitted at the agent tool boundary, while the actual
shell/file/Python execution and kernel audit writes happen in the signed kernel
worker.

Shadow runs have schema support and remain a later phase unless explicitly
enabled by a shadow-model producer.

## Exporters

Exporters live under `rl_capture/exporters/`:

- `sft.py` emits OpenAI-style chat SFT rows or prompt/completion rows.
- `eval_jsonl.py` emits replay/eval JSONL rows from captured trajectories that
  still have usable replay text (task/input messages or actual output);
  metadata-only captures are skipped rather than blocking the export.
- `dpo.py` materializes DPO rows from `PreferenceSignal` references via an
  export-time resolver.
- `kto.py` maps selected raw reward labels into desirable/undesirable rows.
- `rejection_sft.py` emits accepted/rejected targets from raw reward labels.
- `rft.py` emits trajectory-plus-reward rows for reinforcement fine-tuning.

Export-time configuration owns reward shaping, channel weights, filters, and
minimum confidence thresholds.

The RL/Eval Center's Fine-tune Export Center can further filter exports by
evaluator verdict (`pass`, `partial`, `fail`), golden-set promoted trajectory
ids, and ISO date bounds (`since`, `until`). The same filters are recorded in
the export `params` metadata for auditability.

The CLI supports inspection and JSONL export:

```bash
python -m rl_capture.cli --data-root enterprise_root --tenant company inspect --latest
python -m rl_capture.cli --data-root enterprise_root --tenant company export --kind sft --out exports/sft.jsonl
python -m rl_capture.cli --data-root enterprise_root --tenant company export --kind eval --out exports/eval.jsonl
```

Every export records path, checksum, row count, parameters, and kind in the
`exports` table.

## Inspection & Drill-Down API

AgentPro exposes tenant-scoped RL/eval endpoints under `/api/rl-capture/`:

- `GET /api/rl-capture/health?tenant_id=company` returns table counts and the
  effective `db_path` currently in use.
- `GET /api/rl-capture/latest?tenant_id=company` returns a compact preview of
  the newest trajectory.
- `GET /api/rl-capture/summary?tenant_id=company` returns executive summary
  data for the RL/Eval Center, including signal richness, reward channel
  breakdowns, export readiness (`sft`, `eval`, `dpo`, `kto`, `rejection_sft`,
  `rft`), and recent trajectories/rewards/preferences/exports.
- `GET /api/rl-capture/timeseries?tenant_id=company&hours=24` returns hourly
  bucketed counts for trajectories, reward events, preference signals, and
  candidate outputs so the UI can render sparklines.
- `GET /api/rl-capture/trajectories?tenant_id=company&limit=&q=&skill=&terminal_status=`
  lists trajectory previews with lightweight filtering (task/skill search,
  terminal status, session id). For older rows with no explicit `task`, the
  preview label falls back to the first model input message or outcome metadata.
- `GET /api/rl-capture/trajectories/{id}?tenant_id=company` returns full
  drill-down detail — trajectory JSON plus rewards, preferences, candidates,
  and evaluator results scoped to that trajectory.
- `POST /api/rl-capture/correction` records a human-corrected answer through
  the neutral capture bridge and creates candidate outputs plus a `human_edit`
  preference signal for DPO exports.
- `GET  /api/rl-capture/exports?tenant_id=company` lists recorded exports.
- `GET  /api/rl-capture/exports/preview?tenant_id=company&...` materializes
  in-memory eligibility counts for all six formats using the active export
  filters without writing a file. Eval eligibility uses the same non-empty
  replay-case filter as the writer, so the preview count matches the export.
- `POST /api/rl-capture/exports` runs an export via the shared `run_export()`
  helper (same code path as the CLI), writes JSONL to
  `exports/{tenant}/{kind}_{timestamp}.jsonl`, and records the row count,
  checksum, and file path in the `exports` table.
- `GET  /api/rl-capture/exports/{id}/download?tenant_id=company` streams the
  JSONL artifact for a recorded export. The Studio downloads it with an
  authenticated fetch and then saves the response Blob, because direct
  new-tab navigation cannot carry the required Bearer header.

## Reward shaping (Phase 3)

RFT/RL exports need a scalar reward per trajectory, but the raw `reward_events`
stream mixes **judgement** signal (thumbs, human approval/edit, evaluator /
verifier / critique / shadow-eval, business outcomes) with **operational**
traces (policy `allow`, hook `ok`, queue/workstream). Summing everything —
the old behaviour — let process noise dominate the reward.

`rl_capture.core.reward_shaping` fixes this:

- `classify_channel()` maps every channel to a category —
  `human` / `judge` / `business` / `operational`.
- `CATEGORY_WEIGHTS` weights contributions (`human 1.0`, `judge 0.7`,
  `business 0.6`, `operational 0.0` → **excluded**).
- `DEFAULT_LABEL_VALUES` maps labels to `[-1, 1]`; operational labels like
  `allow`/`ok` are deliberately absent so they never read as quality.
  An explicit numeric `raw_value` (clipped to `[-1, 1]`) takes precedence.
- `shape_trajectory_reward()` returns a **bounded, confidence-weighted average**
  reward in `[-1, 1]` (not a sum), plus a per-event `components` breakdown and
  `{n_judgement, n_operational, by_category}`. With **no judgement events the
  reward is `None`** (the trajectory is not RL-trainable yet) rather than a
  misleading number from operational noise.

`materialize_rft_rows()` attaches `reward`, `reward_components`, and
`reward_shaping` to each row. The `/api/rl-capture/summary` endpoint reports the
judgement-vs-operational split (`effectiveness.reward_breakdown`), counts only
judgement toward `judgement_signals` / signal-richness, and gates `rft`, `kto`,
and `rejection_sft` readiness on judgement signal being present.
`breakdowns.channel_categories` lets the UI grey out operational channels.

## Auto-evaluator (judgement signal generation)

Reward shaping only produces a reward when a trajectory carries **judgement**
signal. In a demo (or any low-human-feedback) environment most trajectories have
none, so `rft`/`kto`/`rejection_sft` never light up. The auto-evaluator
(`rl_capture.core.auto_evaluator`) closes that gap by scoring trajectories and
writing `evaluator`-channel `RewardEvent`s (the **judge** category) plus
`EvaluatorResult` rows. It supports two interchangeable modes behind one
interface:

- **Rule-based** (`score_trajectory()`, default) — a pure, deterministic
  heuristic over terminal status, response substance, refusal / error markers,
  and tool outcomes. No model calls, instant, unit-testable. Emits **moderate
  confidence `0.5`**, so its effective weight is `judge(0.7) × 0.5 = 0.35` — it
  never overpowers a real human thumbs-up (weight `1.0`).
- **LLM judge** — the `trajectory_judge` skill (tenant skill, `tools: []`) is
  invoked once per trajectory via `agent.run(prompt, skill_name="trajectory_judge",
  light_mode=True)`. It grades correctness / faithfulness and returns **strict
  JSON** (`score`, `verdict`, `rationale`), parsed by `parse_judge_response()`
  (extracts the JSON object, clamps score to `[-1, 1]`, re-derives verdict when
  missing). LLM verdicts get higher confidence (`0.8`), still below human.

`evaluate_trajectories(store, *, judge_fn=None, trajectory_id=None, overwrite=…)`
runs either scorer, isolates per-trajectory judge errors (a bad call is recorded
in `results` and skipped, not fatal), and skips trajectories that already carry
an evaluator reward unless `overwrite`/`trajectory_id` is set.

**Endpoint:** `POST /api/rl-capture/evaluate` with
`{tenant_id, mode: "rule"|"llm", limit, overwrite, trajectory_id?}`. `mode="llm"`
builds the judge_fn in-process (`_build_llm_judge`) and runs the batch in a
threadpool so the event loop is not blocked. Returns
`{evaluated, skipped, errors, judge_id, mode, results[]}`.

**UI:** the Studio (`/rl-capture`) "Reward channels" card has a **Run
auto-evaluator** control with a rule / LLM toggle; the Workbench
(`/rl-capture/workbench`) right pane has per-trajectory **rule score** / **LLM
judge** actions. Both refresh the summary so judgement signals and export
readiness update immediately.

> Note: re-running against the same trajectory appends a new evaluator reward
> (the shaper averages them); `overwrite` controls the skip-set, not deletion of
> prior evaluator events.

## Trace Value Router (advisory learning destinations)

The Trace Value Router is a sidecar capability that answers a different question
from the auto-evaluator: **"valuable for what?"** It does not replace
`trajectory_judge` and it does not mutate skills or train models automatically.

Flow:

1. `rl_capture.core.trace_value` applies deterministic eligibility only:
   completed trajectory, non-empty task/final answer, bounded redacted evidence,
   no obvious capture/tool error, and no residual detectable PII.
2. Eligible traces are sent to the tenant skill
   `enterprise_root/tenants/company/skills/trace_value_router/SKILL.md` via the
   **light** model role (`AZURE_OPENAI_DEPLOYMENT_LIGHT`, e.g. `gpt-5-nano`).
   `light_mode=True` skips heavy memory/context; it does not select the model by
   itself.
3. The strict JSON response is normalized into a persisted
   `TraceValueAssessment` snapshot in `rl.db`.
4. Reviewers bulk-promote recommendations through `/api/trace-value/promote`.
   Promotions remain auditable `TraceRouteDecision` rows and delegate to existing
   golden, knowledge, and export paths.

Destinations are multi-label: `skill`, `context`, `memory`, `golden_eval`,
`model_training`, and `debug_only`. `model_training` means "approved for an
external training pool"; AgentPro does not fine-tune or deploy weights.

Automatic post-capture routing is opt-in via `TRACE_VALUE_ROUTER_ENABLED=true`.
Manual backfill is always available through `POST /api/trace-value/evaluate`.

## PII redaction gate (Phase 2)

Every export — regardless of kind (`sft`, `eval`, `dpo`, `kto`, `rejection_sft`,
`rft`) — passes through a mandatory redaction gate in `run_export()` **before**
the JSONL is written:

1. **Redact** each row via `rl_capture.core.redaction.redact_rows()`
   (policy `rl_redaction_v2`), which scrubs, structure-preserving:
   - **secrets** — dict keys naming a secret (`token`, `auth_token`,
     `api_key`, `password`, `authorization`, `client_secret`, …) plus inline
     `Bearer`/`Basic` credentials;
   - **emails**, **phone numbers** (separator/`+`-qualified), **IBANs**,
     **Luhn-valid card numbers**, and **US SSNs**.
2. **Quality-check** the redacted rows (`validate_export_rows`).
3. **Hard gate** — `_assert_no_residual_pii()` re-scans the redacted rows and
   raises (export fails, HTTP 400) if any detectable PII survived.

The runner records a **redaction summary** on the export
(`params.redaction` + top-level `redaction` in the API response):
`{policy_version, rows_total, rows_redacted, fields_redacted, categories{…}}`.

**Deliberately preserved** (training signal, not PII): token *counts*
(`prompt_tokens`/`completion_tokens`), token-faithful sequences
(`prompt_token_ids`/`output_token_ids`), contiguous invoice/reference ids, and
decimal amounts. The `token\b` key rule is what keeps `*_token_ids`/`*_tokens`
out of the secret redaction path.

**Known limitation:** free-text personal *names* are not auto-detected (that
needs NER and would over-redact); reviewers remain responsible for name-level
sign-off before sharing a dataset externally.

## Agent Training Studio UI (`/rl-capture`)

The standalone page is served at `/rl-capture` (alias `/rl-eval`) as
**Agent Training Studio**, branded as **Part of Topaz Fabric** — a
**stage-based pipeline** that walks the whole
lifecycle end-to-end: **Capture → Evaluate → Curate → Test → Export**. Rather
than one long scrolling dashboard, each stage is its own view, navigated from the
left sidebar and the horizontal **pipeline spine** at the top (each spine segment
shows a live one-line context and a ✓ once that stage has signal). It wires to
the live `/api/rl-capture/*` **and** `/api/evals/*` endpoints, sharing the same
design language and theme as the Workbench.

The five stages:

- **Capture** — stat cards with 24-hour sparklines (trajectories, model calls,
  reward events, preference signals) plus the **filterable trajectory list**
  (search, terminal status, skill). Rows and the header **"Detailed view"** open
  the separate **Workbench** page rather than expanding inline.
- **Evaluate** — the **Trace Value Router** recommendation queue, the
  **signal-richness ring** (trajectory coverage, model-call depth, judgement
  signals, preference pairs; Strong/Growing/Sparse), the **reward-channels** bars
  with the **Run auto-evaluator** control (rule / LLM judge toggle,
  `POST /api/rl-capture/evaluate`), and recent rewards / preference feeds. Trace
  recommendations have per-row checkboxes, Select all/Clear controls, contextual
  bulk labels, destination-specific targets, confirmation prompts, and next-step
  links to Curate, Knowledge Review, or Export.
- **Curate** — read view of every **golden set** (from `/api/evals` + per-set
  `/api/evals/golden/{set_id}`): each eval suite's golden set with a live case
  count and a preview of its cases. Authoring/promotion links out to the
  Workbench's Curate stage.
- **Test** — eval-suite scoring backed by `/api/evals/dashboard/summary` (suites,
  runs, avg latest score, regressions) plus a per-suite row showing the latest
  run status/score (`/api/evals/{id}/runs`) and a **Run suite** button
  (`POST /api/evals/{id}/run`). Gates and full run traces live in the Workbench.
- **Export** — the **Datasets & exports** panel with one card per kind (`SFT`,
  `Eval`, `DPO`, `KTO`, `Rejection-SFT`, `RFT / RL`), each with a plain-English
  explainer, a "feeds:" line naming compatible trainers (e.g. TRL DPOTrainer,
  GRPO/PPO loop), a readiness badge, an export button (`POST /api/rl-capture/exports`),
  and one-click authenticated Blob download. Download errors remain in the
  Studio as visible status/toast messages instead of opening an authorization
  JSON response in a new tab. Each card distinguishes **eligible now** under the
  current filters from the immutable **last export** row count. Training-pool
  promotion links to Export with the approved model-training route filter already
  active. Export filtering scans the tenant trajectory corpus before applying the
  requested output-row limit, so older approved traces are not omitted merely
  because newer unapproved traces filled the scan window. Eval exports also skip
  metadata-only captures with no replayable text, so "eligible now" reflects the
  rows that can actually be written. A global **format toggle** switches SFT-style rows
  between `prompt → completion` and `chat messages`. The **PII redaction banner**
  confirms the gate is active (see "PII redaction gate" above); each export card
  and the recent-exports list show a 🛡 badge with the number of PII fields
  redacted.

Clicking an eligible Export action immediately shows a preparing indicator and
then success or failure as a toast. Formats with zero eligible rows use a
**Why unavailable?** action that explains the active-filter result instead of
silently behaving like a disabled export button.

Golden-eval promotion requires both selected trace rows and a target golden set.
Studio defaults the target to the first configured suite's golden set and keeps
the promote action disabled while either requirement is missing.

Cross-cutting:

- **Sidebar** lists the five pipeline stages with live counts and done markers,
  plus a **Detailed workbench** link.
- The active stage is reflected in the URL (`?stage=…`) so a stage is deep-linkable.
- **Auto-refresh (5s)** toggle for live testing.
- **Light/Dark theme selector**. The choice is stored in
  `localStorage['rl_theme']` and shared with the Workbench, so both pages honour
  the same theme; a previously stored Hybrid preference migrates to Light on load.
  Defaults: Studio = light, Workbench = dark.

## Agent Training Workbench UI (`/rl-capture/workbench`)

Deep work lives in the **Agent Training Workbench**, branded as **Part of Topaz
Fabric**, a dedicated **stage-based learning-pipeline Workbench** served
at `/rl-capture/workbench`, opened from the Studio's Trajectories card. Clicking a
row opens it deep-linked to that run via `?traj=<trajectory_id>` (preselected on
load); the header **"⤴ Studio"** link returns. Instead of a flat tab bar, the
surface is organized around the lifecycle a run travels through, shown as an
always-visible **pipeline strip** at the top:

1. **Capture** — the recorded trajectory: overview (task + final response), model
   calls (input/output message previews), tool calls, observations, and raw JSON.
2. **Evaluate** — attach a judgement signal: rule / LLM auto-evaluate, thumbs
   up/down, and a **record correction → preference (DPO)** editor; shows this
   trajectory's verdict, shaped reward, reward events, plus the advisory Trace
   Value assessment with destination scores, risks, and promotion actions.
3. **Curate** — pick a suite's golden set, edit golden cases, and **promote the
   current trajectory** into the benchmark in one click.
4. **Test** — suites (list + editor), evaluators (list + test), runs (run selected
   suite, run list, last-run trace), and manual **promotion gates**.
5. **Export** — export-readiness summary plus a wired **build dataset** action that
   calls `POST /api/rl-capture/exports` (sft/eval/dpo/kto/rejection_sft/rft, with
   sft format and eval-verdict filter) and offers a download link for the result.

Supporting panes:

- **Left pane** — searchable/filterable trajectory list with status dots (always visible).
  Server-side Trace Value filters cover assessment state, recommended destination,
  minimum destination score, and promotion status; compact route/score badges
  make assessed and promoted traces visible in the list. The SQLite read query
  joins each trajectory to its latest assessment and matching route decision,
  avoiding per-row assessment lookups. Destination-only filtering matches the
  top recommendation; choosing a minimum score matches any destination meeting
  that threshold.
- **Right pane — Pipeline status** — a per-trajectory tracker showing which stages
  are complete (captured / evaluated / curated / tested / exported), the tenant-wide
  **reward stream**, and copy-full-JSON.

The per-trajectory Value Assessment uses destination-specific actions, displays
existing route decisions to prevent duplicate promotion, confirms writes, and
links to the appropriate next stage. It wires to the same `/api/rl-capture/*`
and `/api/evals/*` endpoints as before; thumbs and the correction editor route
through the neutral capture bridge. A
**Light/Dark theme selector** shared with the Studio via
`localStorage['rl_theme']` provides accessible text, controls, tiles, and hover
states in both themes.

Dashboard V2 keeps its executive launch card that links to the separate
Training Studio, which in turn links out to the Workbench — keeping the module
visually and architecturally independent from AgentPro's dashboard chrome.

## Enterprise access boundary

RL Capture health, read, correction, evaluation, export, preview, and download
routes bind the authenticated principal to the requested tenant and enforce
`rl_capture` read/write/use entitlements. Queue-originated capture remains an
internal service path; queue operational surfaces require the configured key or
an allowlisted service principal in strict mode.

RL Capture storage is independent of chat session persistence. Its API routes
still inherit strict API readiness: when shared Redis session state is
unavailable, `/health/ready` returns 503 so ingress stops routing interactive
traffic to that replica.
