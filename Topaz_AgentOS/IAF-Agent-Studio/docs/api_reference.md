# IAF Agent Studio — API Reference

## Base URL

```
http://localhost:8080/api
```

All endpoints return JSON. Authentication is optional (controlled by `AUTH_ENABLED` setting). When enabled, pass an access token as `Authorization: Bearer <token>` header. The middleware resolves either local Studio-issued JWTs or configured OIDC/JWKS tokens into `IdentityContext`, then preserves the legacy `request.state.user_id/email/role/tenant_id/groups/allowed_tenants` fields for routers. When `AUTH_ENABLED=false`, REST and WebSocket chat paths use a dev identity even if the browser still sends a stale token. If `ENTITLEMENTS_ENABLED=true`, chat and Studio APIs evaluate tenant-owned policies from `enterprise_root/tenants/{tenant_id}/security/policies.yaml` through the selected `EntitlementProvider`. Decisions are normalized into identity, tenant, action, resource, skill, tool, risk, and request-context inputs. `ENTITLEMENTS_ENFORCEMENT_MODE=observe` records would-deny decisions but lets requests continue for rollout validation; default `enforce` fails closed.

Knowledge, Memory, Files, Workstreams, and RL Capture routes explicitly bind
tenant/agent/user scope to that principal and enforce their matching resource
permission. Client parameters select a resource but cannot impersonate another
tenant or user when authentication is enabled.

## Health probes

Health probes are public, return no connection details, and sit outside the
`/api` prefix:

- `GET /health/live` returns 200 when the process is running. It does not probe
  Redis or other external systems.
- `GET /health/ready` returns the role-aware dependency state. API processes
  report `dependencies.sessions` as `ready` or `unavailable`; unavailable
  session Redis returns 503. Scheduler/queue-only roles report
  `not_required`.

## Metrics — `GET /metrics`

Public (no auth), sits outside the `/api` prefix, and is meant for a Prometheus
scraper. Returns the Prometheus 0.0.4 text exposition format
(`Content-Type: text/plain; version=0.0.4; charset=utf-8`) built by hand — no
`prometheus_client` dependency. Every sample is a best-effort gauge taken at
scrape time; a source that fails is simply omitted and the endpoint still
returns 200 (it never errors). Sampling runs in a worker thread so the event
loop is not blocked.

Series emitted:

- `agentos_up` — always `1` while the process serves requests.
- `agentos_build_info{db_backend,knowledge_backend,trace_backend,vector_backend}` —
  value always `1`; the active storage backends are carried as labels.
- `agentos_db_pool_size`, `agentos_db_pool_available`,
  `agentos_db_pool_requests_waiting` — psycopg connection-pool stats (only when
  `DB_BACKEND=postgres` and pooling is active; sampled without building a pool).
- `agentos_postgres_up` (`1`/`0`) and `agentos_postgres_connections`
  (`count(*)` from `pg_stat_activity`) — Postgres reachability + backend count.
- `agentos_traces_24h` — execution traces recorded in the last 24h.
- `agentos_redis_up` (`1`/`0`) — Redis reachability, probed with a fresh
  short-lived client via `REDIS_URL` (2s connect/socket timeout).

---

## Recovery Readiness — `/api/recovery-readiness`

All recovery endpoints require an authenticated administrator and the
corresponding `recovery` entitlement. They never accept a filesystem path from
the client.

- `GET /api/recovery-readiness/summary?tenant_id=...` returns configured status,
  RPO/RTO targets, safe root metadata, and the latest report summary.
- `GET /api/recovery-readiness/roots?tenant_id=...` returns opaque configured
  root ids and availability; absolute server paths are not returned.
- `GET /api/recovery-readiness/reports?tenant_id=...&limit=50` lists compact
  historical report summaries.
- `GET /api/recovery-readiness/reports/{report_id}?tenant_id=...` returns the
  full check/evidence report.
- `GET /api/recovery-readiness/evidence?tenant_id=...&limit=50` lists sanitized
  live drill evidence bundles.
- `GET /api/recovery-readiness/evidence/{evidence_id}?tenant_id=...` returns one
  sanitized evidence bundle.
- `POST /api/recovery-readiness/evidence` stores a sanitized drill evidence
  bundle collected from an isolated recovery cell:

```json
{
  "tenant_id": "company",
  "root_id": "configured_restore",
  "evidence": {
    "evidence_id": "drill_20260720",
    "scheduler_leader": {"active_leaders": 1, "candidates_observed": 2},
    "queue_resume": {
      "expected_items": 3,
      "observed_items": 3,
      "terminal_items": 3,
      "duplicate_completed_items": 0,
      "stale_claims": 0
    },
    "signed_files": {"list_status": 200, "serve_status": 200},
    "slo": {"service_rto_minutes": 12.0, "load_p95_ms": 900}
  }
}
```
- `POST /api/recovery-readiness/verify` runs the read-only verifier in a worker
  thread:

```json
{"tenant_id": "company", "root_id": "configured_restore", "evidence_id": "drill_20260720"}
```

The configured restore root must not overlap active `DATA_ROOT`. Reports include
manifest comparison, required assets, structured-file parsing, SQLite integrity,
operational definitions, and RPO/RTO measurements. Checks requiring a running
isolated recovery cell are explicitly returned as `not_run`. When the
server-side live probe settings are present, the same request adds non-mutating
health, tenant-read, scheduler-status, queue-metrics, and signed-file checks.
When `evidence_id` is supplied, sanitized drill evidence can promote scheduler,
queue, signed-file, service-RTO, and load/failover checks from warning/not-run to
pass/fail. Redis URLs, bearer tokens, signatures, and raw credentials are never
returned.

---

## UI Routes

The FastAPI server also serves no-build HTML surfaces outside the `/api` prefix:

| Route | Purpose |
|---|---|
| `/` | Main chat UI |
| `/studio` and `/customize` | Unified AgentPro Studio for browsing skills, creating personal drafts, submitting/reviewing skills, testing, scheduling, attaching knowledge, reviewing connectors, managing agents, operating security policies, and monitoring per-skill runs/traces/cost |
| `/skill-builder/v2` | Advanced skill editor for SKILL.md, execution modes, workflow steps, tools, Deterministic Automations, and YAML-level authoring |
| `/skill-creator` | Guided document/prompt-to-skill creation flow |
| `/dashboard/v2` | Agent Operations Command Center for HITL, queue, cron, workstream, knowledge, governance, and platform operations |
| `/rl-capture` and `/rl-eval` | Agent Training Studio (Part of Topaz Fabric) as a stage-based pipeline (Capture → Evaluate → Curate → Test → Export) over `/api/rl-capture/*` and `/api/evals/*`; includes shared Light, Hybrid, and Dark themes |
| `/rl-capture/workbench` | Agent Training Workbench (Part of Topaz Fabric) for per-trajectory inspection, evaluation, curation, testing, and export |

Shared AskTwin side panels on these pages use the existing chat APIs and
WebSocket protocol. Contextual UI entry points, such as Workstream Detail
Business Impact metric cards, can auto-open AskTwin in a docked panel and send a
natural-language question while passing selected metric and visible record data
through `page_context`; this does not add a separate REST endpoint.
The main Chat UI's right-side Execution Trace panel consumes `/ws/chat`
`progress` and `reasoning_event` messages to show bounded live progress,
safe reasoning/timeline cards, tool evidence, and provider-native reasoning
previews when exposure is enabled. If the provider confirms native reasoning but
does not expose a text summary for a turn, the server emits an observable
reasoning-trace fallback instead of leaving the panel blank.

---

## Deterministic Automations — `/api/automations`

Deterministic Automations are no-LLM shell/python pipelines stored under
`enterprise_root/tenants/{tenant_id}/automations/*.yaml`. Run traces are stored
in `enterprise_root/tenants/{tenant_id}/shared/databases/automation_runtime.db`.
The REST contract is unchanged by kernel isolation: local mode executes through
in-process `SafeKernel`, while `AGENTOS_KERNEL_BACKEND=remote` sends automation
shell/python steps to the signed kernel worker.

| Endpoint | Method | Description |
|---|---|---|
| `/api/automations` | GET | List automation YAML definitions |
| `/api/automations/{automation_id}` | GET | Get one automation definition |
| `/api/automations` | POST | Create or update an automation YAML definition |
| `/api/automations/{automation_id}` | DELETE | Delete an automation YAML definition |
| `/api/automations/{automation_id}/run` | POST | Run an automation immediately and persist trace steps |
| `/api/automations/{automation_id}/runs` | GET | List recent runs for one automation |
| `/api/automations/runs/{run_id}` | GET | Get a run and its step trace |

### POST `/api/automations`

```json
{
  "id": "nightly_close",
  "name": "Nightly Close",
  "description": "Run close scripts without LLM involvement",
  "enabled": true,
  "steps": [
    {"name": "extract", "action": "python", "params": {"script": "extract.py", "args": "--date today"}},
    {"name": "publish", "action": "shell", "params": {"command": "echo done"}}
  ]
}
```

Allowed actions are `shell`, `python`, and `condition`. `skill` actions are
rejected by the automation engine.

---

## Private Learning Loop Evals — `/api/evals`

Eval suites and golden sets are tenant-owned files under `enterprise_root`:

- `enterprise_root/tenants/{tenant_id}/evals/{suite_id}.yaml`
- `enterprise_root/tenants/{tenant_id}/golden_sets/{set_id}.jsonl`
- `enterprise_root/tenants/{tenant_id}/eval_evaluators/{evaluator_id}/manifest.yaml`

| Endpoint | Method | Description |
|---|---|---|
| `/api/evals` | GET | List eval suite YAML definitions |
| `/api/evals` | POST | Create or update an eval suite |
| `/api/evals/validate` | POST | Validate a suite definition, including referenced evaluator manifest, without writing it |
| `/api/evals/{suite_id}` | GET | Get one eval suite |
| `/api/evals/{suite_id}` | DELETE | Delete one eval suite |
| `/api/evals/evaluators` | GET | List registered tenant evaluator manifests |
| `/api/evals/evaluators/{evaluator_id}` | GET | Get one evaluator manifest |
| `/api/evals/evaluators/{evaluator_id}/test` | POST | Execute a registered evaluator against a supplied or default JSON payload |
| `/api/evals/golden/{set_id}` | GET | Read one golden-set JSONL file |
| `/api/evals/golden/{set_id}` | POST | Replace one golden set |
| `/api/evals/golden/{set_id}/promote` | POST | Promote a captured trajectory into a golden case |
| `/api/evals/{suite_id}/run` | POST | Run a suite against its golden set and persist run/case trace rows |
| `/api/evals/{suite_id}/runs` | GET | List recent runs for one suite |
| `/api/evals/{suite_id}/gates` | GET | List manual promotion-gate decisions for one suite |
| `/api/evals/{suite_id}/gates` | POST | Record an approve/reject decision for a run without deploying anything |
| `/api/evals/runs/{run_id}` | GET | Fetch one run with per-case results |
| `/api/evals/dashboard/summary` | GET | Read-only dashboard summary: latest score, delta, regressions, and trend rows |
| `/api/evals/recommendations` | GET | Advisory model-role recommendation from eval score, cost, and latency |

Run/case persistence goes through the AgentOS `StorageEngine` seam. SQLite uses
`enterprise_root/tenants/{tenant_id}/shared/databases/eval_runtime.db`; Postgres
deployments use the shared `DB_BACKEND=postgres` connection. The RL Workbench
(`/rl-capture/workbench`) exposes suites, golden cases, evaluator testing, run
traces, and gate decisions through its **Curate** and **Test** pipeline stages.
The Training Studio (`/rl-capture`) mirrors this at the portfolio level: its
**Curate** stage reads every golden set (`/api/evals` + `/api/evals/golden/{set_id}`)
and its **Test** stage shows the dashboard summary plus per-suite latest runs and
a run button (`/api/evals/{id}/runs`, `POST /api/evals/{id}/run`), linking out to
the Workbench for gates and full traces. Python evaluators are
allowlisted by manifest and executed in a constrained subprocess with JSON
stdin/stdout; the subprocess boundary is for trusted tenant plug-ins, not
hostile-code isolation. Recommendations do not affect runtime routing unless
`EVAL_ROUTER_ENABLED=true` and a role map has been explicitly published.

---

## RL/Eval Exports — `/api/rl-capture/exports`

`POST /api/rl-capture/exports` accepts the existing `tenant_id`, `kind`,
`format`, and `limit` fields plus optional Fine-tune Export Center filters:

- `eval_verdict`: `pass`, `partial`, or `fail`
- `golden_set`: golden-set id; filters to promoted trajectory ids in that set
- `since`: ISO timestamp lower bound
- `until`: ISO timestamp upper bound

The export record stores these filters in `params` so generated datasets remain
auditable.

---

## Dashboard Operations — `/api/dashboard`

### GET `/api/dashboard/ops-summary`
Returns the Dashboard V2 operations summary used by the Agent Operations Command Center. This endpoint is additive; the legacy `/api/dashboard/summary` payload remains unchanged.

**Query params:** `tenant_id` (default `company`)

**Response:**
```json
{
  "schema_version": "dashboard_ops_summary.v1",
  "health": "healthy|warning|critical|degraded",
  "active_sessions": 2,
  "pending_approvals": 1,
  "queue": {"status": "ok", "total_active": 3, "awaiting_human": 1, "failed": 0, "dlq": 0},
  "cron": {"status": "ok", "total": 14, "enabled": 4, "running": 0},
  "workstreams": {"status": "ok", "total": 2, "active": 1, "awaiting_human": 1},
  "finops": {"status": "ok", "total_cost_usd": 0.0, "total_tokens": 0},
  "control_plane": {
    "status": "warning",
    "approvals_pending": 1,
    "blocked_actions": 0,
    "rules_active": 0,
    "queue_failures": 0,
    "paused_actions": 2
  },
  "needs_attention": [
    {"type": "approval", "severity": "high", "title": "Approval required", "source": "finance-ops", "action": {"type": "navigate", "page": "approvals"}}
  ],
  "degraded_sources": [],
  "generated_at": "2026-06-08T00:00:00+00:00"
}
```

Each section is bounded and independently degradable. If a provider fails, the response keeps the same shape, marks that section `status="degraded"`, adds the source to `degraded_sources`, and reports overall `health="degraded"` unless live critical operational items are also present.

---

## Learning Signals — `/api/learning-inbox`

`GET /api/learning-inbox?tenant_id=company&agent_id=enterprise_agent` returns a
read-only triage summary that combines pending-review knowledge and captured
feedback signals. Dashboard V2's Knowledge Manager uses the summary counts for
the Learning Signals panel; final confirm/reject governance still happens in the
existing knowledge table.

---

## Central Policy & Control Registry — `/api/policy-control`

Dashboard V2 exposes a governance-facing Policy Control page that stores structured business controls in `enterprise_root/tenants/{tenant_id}/security/policy_control.yaml`. Published active policies compile into the existing lifecycle hook contract and call the fixed tenant hook evaluator at `shared/hooks/policy_engine.py`; the API preserves manually authored hooks and replaces only the generated hook for the selected policy. The list response also surfaces existing tenant hooks from the selected agent as read-only unmanaged controls, so hooks created in Skill Builder V2 remain visible in the central registry and can be adopted into managed policy drafts.

### GET `/api/policy-control/policies`
Returns the structured policy registry, validation summary, generated hook previews, and combined control inventory.

**Query params:** `tenant_id` (default `company`), `agent_id` (default `enterprise_agent`)

Key response fields:

- `policies`: managed policies loaded from `policy_control.yaml`
- `controls`: managed policies plus read-only unmanaged hook-backed controls from the selected agent's `config.yaml`
- `unmanaged_controls`: existing Skill Builder hooks that are not generated `policy.*` hooks
- `control_count`, `unmanaged_count`, `active_control_count`: inventory counts for the governance UI

### GET `/api/policy-control/events`
Returns the runtime hook event catalog used by Policy Control. Each event entry
includes whether it is gateable, observe-only, HITL-safe, and which decisions are
recommended for that lifecycle point. The dashboard uses this endpoint instead of
hard-coding event dropdowns.

### PUT `/api/policy-control/policies`
Validate and save the full structured registry.

```json
{
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "policies": [
    {
      "policy_id": "ap_high_value_payment_approval",
      "name": "AP High Value Payment Approval",
      "status": "active",
      "event": "PreToolUse",
      "matcher": "shell",
      "decision": "approve",
      "fail_policy": "closed",
      "scope": {"agent_id": "enterprise_agent", "skills": ["fa_ap", "invoice_processing_ap"]},
      "conditions": {"all": [
        {"field": "command", "operator": "contains", "value": "/payments/release"},
        {"field": "extracted.amount", "operator": "greater_than_or_equal", "value": 50000}
      ]}
    }
  ]
}
```

### POST `/api/policy-control/policies/validate`
Validate one policy or a full policy list without saving. The response includes registry validation and generated-hook validation.

### POST `/api/policy-control/policies/draft`
Draft a structured policy from plain-English intent by running the dedicated
`policy_authoring` skill. The response includes `policy`, `policy_yaml`,
`authoring_yaml`, `sample_context`, `assumptions`, `event_catalog`, validation
results, and a generated hook preview. `authoring_yaml` is the editor bundle:
it includes the managed `policy:` plus the compiled `hooks:` preview so reviewers
can see the final `on_block: hitl` runtime hook before publishing. The skill emits
managed Policy Control YAML only; publishing still compiles to the fixed
`policy_engine.py` command after admin review.

### POST `/api/policy-control/policies/parse-yaml`
Parse YAML from the Policy Definition YAML view into normalized form data. This
does not save or publish. It returns the same normalized policy, validation, and
hook preview shape as the draft endpoint. If the YAML includes both `policy:` and
`hooks:`, the managed `policy:` section remains the source of truth and `hooks:`
is regenerated from it for validation/readability.

### GET `/api/policy-control/policies/{policy_id}/hook-preview`
Return the generated hook binding and YAML preview for a saved policy.

### POST `/api/policy-control/policies/{policy_id}/publish`
Compile the policy to the target agent's `config.yaml` `hooks:` section. Active `approve`, `deny`, and `escalate` policies must use a gateable event; `approve` is intended for `PreToolUse` so existing HITL checkpoint/resume and exact tool replay remain in force. Generated `approve` hooks explicitly include `on_block: hitl` and an `approval` payload.

### POST `/api/policy-control/policies/simulate`
Evaluate a policy against a sample context and return `allow`, `deny`, `approve`, or `escalate` plus per-condition match details.

---

## Authentication — `/auth`

Local auth issues short-lived access tokens and httpOnly refresh cookies. Access tokens carry normalized tenant, role, group, and allowed-tenant claims. When `AUTH_PROVIDER` is set to an enterprise OIDC provider, access-token validation uses issuer, audience, and JWKS configuration and maps provider claims into the same `IdentityContext` contract.

### POST `/auth/register`
Register a new user account.
```json
{
  "username": "john_smith",
  "email": "john@company.com",
  "password": "SecurePass123!"
}
```
**Response:** `{"access_token": "...", "token_type": "bearer", "user": {...}}`

### POST `/auth/login`
```json
{"username": "john_smith", "password": "SecurePass123!"}
```
**Response:** `{"access_token": "...", "token_type": "bearer", "user": {"id": "...", "username": "...", "role": "user"}}`
Refresh token is set as HttpOnly cookie (`iaf_refresh`).

### POST `/auth/logout`
Clears refresh cookie.

### POST `/auth/refresh`
Uses `iaf_refresh` cookie to issue a new access token.

### GET `/auth/me`
Returns current user profile, including `must_change_password` — the live
rotation state. The readable `iaf_user` cookie carries the same field but is only
a snapshot taken when the token was issued, so clients should treat `/auth/me`
as authoritative.

### PUT `/auth/me/password`
```json
{"current_password": "old", "new_password": "new"}
```
Rejects with **400** when the new password matches the current one — rotation
must actually rotate. On success it clears `must_change_password` and refreshes
the `iaf_user` cookie so the browser does not re-enter the change screen.

#### Temporary-password gate

Passwords chosen by an administrator (`POST /auth/users`, and
`POST /auth/users/{id}/reset-password`) are temporary. Until the account owner
replaces one, the session authenticates but is refused elsewhere:

```json
{ "detail": "PASSWORD_CHANGE_REQUIRED",
  "message": "Your temporary password must be changed before continuing." }
```

- **Blocked:** everything under `/api/*` and `/auth/*` — including the
  `/auth/users*` administration surface — with HTTP **403**.
- **Reachable:** `/auth/me`, `/auth/me/password`, `/auth/policy`,
  `/auth/logout`, `/auth/refresh`, `/auth/version`,
  `/auth/registration-mode`, the `/auth/oauth/*` refresh and logout routes, and
  the `/auth/privacy/*` routes, so a user always has a way to resolve it.
- **WebSockets** do not pass through HTTP middleware, so authenticated sockets
  (`/ws/chat`, `/ws/workstreams/{name}`) apply the same check themselves and
  refuse the connection or return an error frame carrying the same code.

The gate fails open if the user store cannot be read: the credential was already
verified at login, so what is enforced here is rotation, not authentication.

### Admin: GET `/auth/users`
List all users (admin only).

### Admin: POST `/auth/users`
Create user (admin only). Body: `{username, email, password, role}`. The
password is recorded as temporary as part of the create, so the new account is
subject to the gate above from its first sign-in.

### Admin: PUT `/auth/users/{id}/status`
```json
{"status": "active|suspended"}
```

### Admin: POST `/auth/users/{id}/reset-password`
```json
{"new_password": "..."}
```
The replacement is temporary by definition — an administrator chose it, not the
account owner — so the target user must rotate it at next sign-in.

### Admin: DELETE `/auth/users/{id}`
Delete user.

---

## Chat — `/api/chat`

### POST `/api/chat`
Synchronous (non-streaming) chat. Returns after full response.

**Request:**
```json
{
  "content": "Show overdue invoices for ACME Corp",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo",
  "skill_name": null,
  "session_id": null,
  "source_page": null,
  "page_context": null,
  "human_approval": true,
  "render_ui": false,
  "light_mode": false,
  "knowledge_mode": "hybrid",
  "force_plan": false
}
```

`force_plan: true` mirrors the chat UI Plan Mode toggle: routes to `general`, sets
`execution_mode=planned`, and calls `create_plan` for user approval before execution.

`session_id`, `source_page`, and `page_context` are optional AskTwin fields.
When present, the chat router uses the session id to isolate the page
conversation and adds the whitelisted page state to the agent prompt so the
`iaf_guide` skill can answer for the current route, tab, filters, visible
records, selected skill/workstream, or visible metrics before falling back to
documentation.

**Response:**
```json
{
  "response": "Found 3 overdue invoices...",
  "skill": "ar_ops",
  "user_id": "demo",
  "rl_trajectory_id": "trace-uuid",
  "rl_model_call_id": "trace-uuid:model:final",
  "evidence_trace_id": "trace-uuid",
  "source_documents": {
    "schema_version": "1.1",
    "trace_id": "trace-uuid",
    "documents": [],
    "evidence_items": []
  },
  "pending_approval": null,
  "reasoning_context": {
    "routing": {"skill": "ar_ops", "confidence": 0.95},
    "context_used": {"facts_referenced": [], "data_sources": ["/shared/contexts/p2p_context.md"]},
    "tool_calls": [{"tool": "shell", "command": "...", "duration_ms": 42}],
    "reasoning_summary": "Used provider-native React for skill 'ar_ops'. Gathered evidence with 1 tool call(s): shell...",
    "trace_id": "abc123"
  }
}
```

When auth is enabled, `tenant_id` must be in the resolved identity's `allowed_tenants`, and the server ignores the browser-supplied `user_id` in favor of the authenticated subject from `IdentityContext`. Entitlements then check `agent:{agent_id}` and the selected `skill:{skill_name}` before execution through the provider boundary; provider errors return 403 in enforce mode and are recorded as observe-mode allow decisions when explicitly configured. When the agent reads business files or other supported artifacts, `source_documents` contains the evidence bundle and `evidence_trace_id` can be used with `/api/evidence/{trace_id}`. Evidence persistence goes through the sink-backed `EvidenceCollectorAdapter`: local SQLite remains authoritative, while optional JSONL mirrors receive bounded/redacted summaries for compliance forwarding. `reasoning_context.reasoning_summary` is a bounded, observable execution summary for the UI and does not expose raw hidden chain-of-thought. When native reasoning exposure is enabled but the provider returns an empty reasoning text summary, `reasoning_context.native_reasoning.preview` can carry this observable summary with `preview_source: "observable_summary"` so the right-side panel still shows a safe trace card. If `RL_CAPTURE=true`, the server also records neutral capture events best-effort into tenant `rl.db` through `iaf_agent_skills.capture_events`. `rl_trajectory_id` and `rl_model_call_id` are stable target IDs used by feedback/correction flows.

---

## Conversations — `/api/conversations`

Sidebar endpoints for listing, loading, creating, deleting, and renaming chat sessions.

- `GET /api/conversations` — list recent sessions (newest first), `{sessions[], total, current_session_id}`. Each session has `session_id`, `title`, `last_active_at` (unix seconds), `turn_count`, `skills_used`.
- `POST /api/conversations/new` — save current + start a fresh session.
- `POST /api/conversations/{session_id}/load` — resume a past session in place (no fork).
- `DELETE /api/conversations/{session_id}` — soft-delete (status=`deleted`; JSONL audit trail retained).
- `PATCH /api/conversations/{session_id}` — rename `{title}`.
- `POST /api/conversations/backfill` — index existing JSONL history into the session index.

**Identity resolution (important):** conversation sessions are stored under the **authenticated user identity** resolved into `IdentityContext`, exactly as the chat path does. When auth is enabled, all conversation endpoints **ignore the browser-supplied `user_id`** query param and resolve it from `request.state.user_id`, so the sidebar lists/loads the same sessions the chat backend wrote. Trusting the browser-supplied `user_id` would key listing by the email and silently miss the user's sessions. The `user_id` query param is honored only when auth is disabled (dev).

---

## RL Capture — `/api/rl-capture`

Inspection, drill-down, correction, and export endpoints for the opt-in
RL/eval capture store. All endpoints accept an optional `tenant_id` query
parameter and are scoped to the tenant's `rl.db` (respecting `RL_DB_PATH`).

**Inspection & summary**

- `GET /api/rl-capture/health?tenant_id=company` — table counts plus effective
  `db_path`.
- `GET /api/rl-capture/latest?tenant_id=company` — compact preview of the
  newest trajectory.
- `GET /api/rl-capture/summary?tenant_id=company` — signal richness, judgement
  totals, reward channel/label breakdowns, export readiness
  (`sft`, `eval`, `dpo`, `kto`, `rejection_sft`, `rft`), and recent
  trajectories/rewards/preferences/exports.
- `GET /api/rl-capture/timeseries?tenant_id=company&hours=24` — hourly counts
  for `trajectories`, `reward_events`, `preference_signals`, and
  `candidate_outputs` (used for sparklines).

**Drill-down**

- `GET /api/rl-capture/trajectories?tenant_id=company&limit=&q=&skill=&terminal_status=&session_id=&include_debug=&trace_assessment_status=&trace_destination=&trace_route_status=&trace_min_score=`
  — trajectory preview list with lightweight filters (task/skill search,
  terminal status, session id, limit ≤ 500) plus server-side Trace Value filters.
  `trace_assessment_status` accepts `assessed`, `unassessed`, or `debug_only`;
  `trace_destination` accepts a destination such as `golden_eval`, `memory`, or
  `model_training`. Without `trace_min_score`, destination filtering matches the
  latest assessment's top destination (the same semantics as recommendation
  queues); with a positive 0–1 threshold, it matches that destination's score
  even when another destination ranks first. `trace_route_status` filters
  promotion decisions such as `pending_review`,
  `approved`, or `promoted`. Preview rows include a compact `trace_value` badge
  payload with top destination/score and latest route status. If an older captured trajectory
  has no explicit `task`, the preview derives the label from the first model
  input message or outcome metadata so the Workbench does not show a blank task.
  Blank/debug-only traces are hidden unless `include_debug=true`.
- `GET /api/rl-capture/trajectories/{trajectory_id}?tenant_id=company` — full
  trajectory JSON plus rewards, preferences, candidates, evaluator results,
  latest Trace Value assessment, and route decisions scoped to that trajectory.

**Correction**

- `POST /api/rl-capture/correction` — records a human-edited answer for a
  trajectory. Emits through `iaf_agent_skills.capture_events` and creates
  candidate outputs plus a `human_edit` preference signal for DPO export.

```json
{
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo",
  "trajectory_id": "trace-uuid",
  "original_response": "Original assistant text",
  "corrected_response": "Human corrected assistant text",
  "source": "api_correction"
}
```

**Exports**

- `GET  /api/rl-capture/exports?tenant_id=company&kind=&limit=` — list recorded
  export runs (id, kind, params, file path, checksum, row count, timestamp).
- `POST /api/rl-capture/exports` — trigger an export through the shared
  `rl_capture.cli.run_export()` helper (same code path as the CLI). Writes
  JSONL to `exports/{tenant}/{kind}_{utc_stamp}.jsonl` and records the run in
  the `exports` table. Body:

```json
{
  "tenant_id": "company",
  "kind": "sft",              // sft | eval | dpo | kto | rejection_sft | rft
  "format": "prompt_completion", // chat | prompt_completion (SFT only)
  "limit": 1000,
  "trace_destination": "model_training", // optional; requires approved route
  "trace_route_status": "approved"
}
```

- `GET /api/rl-capture/exports/{export_id}/download?tenant_id=company` —
  streams the JSONL artifact for a recorded export. This protected endpoint
  requires the normal `Authorization: Bearer <token>` header. Browser clients
  should fetch it as a Blob and trigger a local download rather than navigating
  directly to the URL.
- `GET /api/rl-capture/exports/preview` — returns live `counts` for SFT, Eval,
  DPO, KTO, Rejection-SFT, and RFT plus `candidate_trajectories`, using the same
  `format`, `eval_verdict`, `golden_set`, `trace_destination`,
  `trace_route_status`, `since`, `until`, and `limit` filters without creating
  an export file. An active route/golden filter with zero matches returns zero;
  it never falls back to all trajectories. The service scans the corpus before
  applying `limit`, so eligible older traces remain visible.
- `POST /api/rl-capture/evaluate` — auto-evaluator: scores trajectories and
  writes `evaluator`-channel judgement rewards (lights up `rft`/`kto`/
  `rejection_sft` readiness). `mode="rule"` is a deterministic heuristic (no
  model calls); `mode="llm"` invokes the `trajectory_judge` skill once per
  trajectory and parses its strict-JSON verdict. Returns
  `{evaluated, skipped, errors, judge_id, mode, results[]}`. Body:

```json
{
  "tenant_id": "company",
  "mode": "rule",             // rule | llm
  "limit": 50,
  "overwrite": false,
  "trajectory_id": null        // set to evaluate a single trajectory (implies overwrite)
}
```

## Trace Value Router — `/api/trace-value`

Advisory assessment and human-reviewed promotion APIs for routing completed
eligible traces into learning destinations. These APIs do not train or deploy
models and do not directly mutate `SKILL.md`.

- `GET /api/trace-value/summary?tenant_id=company&limit=25` — portfolio counts
  plus destination queues for `skill`, `context`, `memory`, `golden_eval`,
  `model_training`, and `debug_only`.
- `GET /api/trace-value/assessments?tenant_id=company&destination=&verdict=&include_debug=&limit=`
  — filterable assessment review list.
- `GET /api/trace-value/assessments/{trajectory_id}?tenant_id=company` — latest
  assessment for a trajectory.
- `POST /api/trace-value/evaluate` — manual single/batch backfill. Automatic
  evaluation after capture is controlled by `TRACE_VALUE_ROUTER_ENABLED`.
- `POST /api/trace-value/promote` — bulk human-reviewed route decisions.
  `golden_eval` delegates to `/api/evals/golden/{set_id}/promote`;
  `skill`/`context`/`memory` create pending-review knowledge records;
  `model_training` records approval for export filtering; `debug_only` archives
  the trace from curated queues.

```json
{
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "items": [
    {
      "trajectory_id": "trace-uuid",
      "destination": "model_training",
      "reason": "Generalizable answer-quality pattern",
      "training_pool": "default"
    }
  ]
}
```

Dashboard V2's **RL Capture** launch card links to `/rl-capture`, which
consumes these endpoints. All endpoints require the same authentication as
the rest of the dashboard when auth is enabled.

---

## Evidence — `/api/evidence`

Evidence bundles are generated by chat, WebSocket, cron, and queue executions when the agent reads supported sources.

### GET `/api/evidence/{trace_id}`
Retrieve a full evidence bundle for a past run.

### GET `/api/evidence/{trace_id}/items/{evidence_id}`
Retrieve one normalized evidence item.

### GET `/api/evidence/{trace_id}/items/{evidence_id}/text`
Return the text/excerpt seen by the agent.

### GET `/api/evidence/{trace_id}/items/{evidence_id}/content`
Stream original content for `resolve_on_demand` sources or stored bytes for `stored_payload` sources. Local evidence streams a tenant-scoped file path; configured remote providers such as SharePoint, Azure Blob, S3, or URL sources may stream downloaded payload bytes.

### POST `/api/evidence`
Store an evidence bundle. This is primarily for internal job integrations.

```json
{
  "trace_id": "trace-uuid",
  "execution_source": "rest|websocket|cron|queue",
  "evidence_items": [
    {
      "evidence_id": "uuid-per-read",
      "source_uri": "/shared/policies/ar.md",
      "source_type": "local",
      "artifact_type": "text",
      "content_strategy": "resolve_on_demand"
    }
  ]
}
```

---

## Workstreams — `/api/workstreams`

Workstreams are YAML-backed Mission Mode backlogs under
`enterprise_root/tenants/{tenant_id}/workstreams/{name}.yaml`. The list,
create, patch, run, retry, skip, and WebSocket endpoints drive the
Workstream UI. Item-level execution metadata is additive and backward
compatible: older YAML files load with defaulted fields.

### POST `/api/workstreams`
Create a YAML-backed workstream. The request accepts core YAML fields such as
`name`, `display_name`, `owner`, `description`, `skill`,
`priority_strategy`, `max_attempts_per_item`, `batch_size`, `parallelism`,
`items`, `items_source`, `escalation`, `business_lens`, and optional
`cron_schedule` / `cron_user_id`. When cron is supplied, the backend creates a
paired scheduler job named `ws_<workstream_name>` that runs `mission_mode`.

### PATCH `/api/workstreams/{name}`
Patch workstream-level YAML fields. Supported fields include `display_name`,
`owner`, `description`, `skill`, `status`, `priority_strategy`,
`max_attempts_per_item`, `batch_size`, `parallelism`, `items_source`,
`escalation`, `business_lens`, `business_metrics`, `cron_schedule`,
`cron_user_id`, and `cron_job_id`. Item rows are intentionally not replaced by
this endpoint; use item action/update flows for item lifecycle changes.

The merged document is validated before anything is written, and the write, the
validation, and the execution-field check all happen inside the workstream's
file lock — so a rejected patch leaves the stored YAML byte-identical.

**Execution-field lock.** `skill`, `automation`, `batch_size` and `parallelism`
change how already-queued work executes, so they are only editable while the
workstream's **stored** status is `paused` or `completed`. Attempting to change
them in any other state returns `409`:

```json
{"detail": {"errors": ["cannot change skill while the workstream is 'active'; pause it first"]}}
```

Because the check reads the *stored* status, a single request cannot authorise
its own change by pausing at the same time — `{"status": "paused", "skill": "x"}`
is rejected with `409` and nothing is persisted, including the pause. Pause
first, then patch.

**Other failures.** `400` with `{"detail": {"errors": [...]}}` when the merged
document fails validation or `skill` names a skill that does not resolve; `422`
when `batch_size` or `parallelism` fall outside their declared bounds (Pydantic
rejects these before the route runs); `404` for an unknown workstream; `400` for
an empty patch body.

### GET `/api/workstreams/capabilities`
Return the calling principal's effective permissions on workstreams in the
resolved tenant, as decided by the entitlement provider. Clients should use this
to decide whether to offer write and destructive controls, rather than deriving
them from a role string — the tenant policy, not the role, is authoritative.

**Response:**
```json
{"read": true, "write": true, "delete": false}
```

Every value is a plain boolean. When `ENTITLEMENTS_ENABLED` is false the provider
is a no-op that allows everything, so all three come back `true`. Callers should
treat a missing key as "not permitted" and fail closed.

Declared before `/api/workstreams/{name}`; otherwise the parameterised route
would capture `capabilities` as a workstream name.

### DELETE `/api/workstreams/{name}`
Permanently delete the workstream YAML. This is a hard delete, not an archive,
and requires the `delete` action on `workstream:{name}`.

By default the paired scheduler job is torn down with it, so no schedule
survives to fire against a workstream that no longer exists.

**Response:**
```json
{"deleted": "alpha_ws", "cron_removed": "job-123", "cron_warning": null}
```

`cron_removed` carries the job id only when the scheduler confirms the deletion.
If the job could not be removed, `cron_removed` is `null` and `cron_warning`
explains that an orphaned schedule may still fire — clients must surface that
rather than reporting an unqualified success.

### GET `/api/workstreams/{name}/items/{item_id}/context`
Return a bounded item cockpit payload for Workstream Detail.

**Response:**
```json
{
  "workstream": {
    "name": "ap_nightly_cleanup",
    "display_name": "AP Nightly Cleanup",
    "status": "active",
    "skill": "fa_ap",
    "owner": "admin@iaf.local"
  },
  "item": {
    "id": "INV-3040",
    "description": "Resolve invoice INV-3040",
    "status": "done",
    "attempts": 1,
    "last_trace_id": "trace-uuid",
    "evidence_trace_id": "trace-uuid",
    "evidence_count": 2,
    "last_result_summary": "Released invoice successfully",
    "last_result_at": "2026-06-06T12:00:00+00:00",
    "current_execution_id": "wse_abc123def456",
    "execution_log": [
      {
        "attempt": 1,
        "status_before": "pending",
        "status_after": "done",
        "duration_ms": 842,
        "trace_id": "trace-uuid",
        "evidence_count": 2,
        "result_preview": "Released invoice successfully"
      }
    ],
    "execution_ledger": [
      {
        "execution_id": "wse_abc123def456",
        "attempt": 1,
        "status_before": "pending",
        "status_after": "done",
        "duration_ms": 842,
        "trace_id": "trace-uuid",
        "evidence_trace_id": "trace-uuid",
        "evidence_count": 2,
        "result_preview": "Released invoice successfully",
        "steps": []
      }
    ],
    "action_events": [],
    "last_failure_reason": null,
    "suggested_actions": [
      {"id": "continue_chat", "label": "Continue", "kind": "chat", "side_effect": false}
    ],
    "chat_session_id": "workstream:ap_nightly_cleanup:item:INV-3040",
    "chat_transcript_preview": []
  },
  "approval": null
}
```

When the item is waiting on HITL, `approval` contains the pending approval row
from the shared ApprovalStore. The same approval id can be resolved from the
Dashboard approvals tab or the Workstream Detail item panel.

### POST `/api/workstreams/{name}/items/{item_id}/chat`
Continue from a background item result without leaving Workstream Detail.

**Request:**
```json
{
  "message": "What evidence supported this decision?",
  "action": "chat"
}
```

**Response:**
```json
{
  "workstream_name": "ap_nightly_cleanup",
  "item_id": "INV-3040",
  "chat_session_id": "workstream:ap_nightly_cleanup:item:INV-3040",
  "response": "Item INV-3040 is done. Last result: Released invoice successfully Evidence trace: trace-uuid.",
  "side_effect_blocked": false,
  "chat_backend": "api_chat",
  "chat_skill": "fa_ap",
  "item": {"id": "INV-3040", "chat_transcript_preview": []}
}
```

The endpoint stores only a bounded transcript preview in YAML. Every follow-up
message calls the existing `/api/chat` backend with a Workstream item context
prompt, including messages that mention actions such as email, release, update,
approve, or reject. The response keeps `side_effect_blocked=false` and
`chat_backend="api_chat"`; explicit governed item actions remain on the
`/actions` endpoint.

### POST `/api/workstreams/{name}/items/{item_id}/actions`
Run a governed state/action command against one Workstream item and append a
bounded `action_events` row to that item.

**Request:**
```json
{
  "action_type": "retry",
  "reason": "operator retry after vendor master fix",
  "payload": {}
}
```

Supported `action_type` values are:

| Value | Behaviour |
|---|---|
| `retry` / `retry_item` | Reset item to `pending`, clear attempts/failure/approval/close metadata, and let Mission Mode reprocess it on a later tick. |
| `skip` / `skip_item` | Mark item `done` with `resolution: "SKIPPED: <reason>"`. |
| `close` / `close_item` | Set `closed_at` and `closed_by` for an item already `done` or `failed`. |
| `email`, `post`, `resend`, `correct` | Return `status="blocked"` and record a blocked action event until a connector/policy executor is configured. |

**Response:**
```json
{
  "workstream_name": "ap_nightly_cleanup",
  "item_id": "INV-3040",
  "action_id": "wsa_abc123def456",
  "action_type": "retry",
  "status": "completed",
  "side_effect_blocked": false,
  "result": "Item INV-3040 reset to pending for governed retry.",
  "item": {
    "id": "INV-3040",
    "status": "pending",
    "attempts": 0,
    "action_events": [
      {
        "action_id": "wsa_abc123def456",
        "action_type": "retry",
        "requested_by": "demo",
        "requested_at": "2026-06-06T12:05:00+00:00",
        "status": "completed",
        "side_effect": true,
        "reason": "operator retry after vendor master fix",
        "result": "Item INV-3040 reset to pending for governed retry."
      }
    ]
  }
}
```

Unknown workstreams or item ids return `404`; unsupported action types return
`400`. Action events and preview fields are bounded before YAML persistence.

### POST `/api/workstreams/{name}/chat`
Ask questions about the whole Workstream from the Workstream Detail sidebar.

**Request:**
```json
{
  "message": "Which items need attention next?",
  "action": "chat"
}
```

**Response:**
```json
{
  "workstream_name": "ap_nightly_cleanup",
  "chat_session_id": "workstream:ap_nightly_cleanup:overall",
  "response": "Two invoices are awaiting approval; the oldest blocked item is INV-3040.",
  "side_effect_blocked": false,
  "chat_backend": "api_chat",
  "chat_skill": "fa_ap",
  "workstream": {
    "name": "ap_nightly_cleanup",
    "total_items": 20,
    "status_counts": {"done": 12, "awaiting_human": 2, "pending": 6}
  },
  "chat_transcript_preview": []
}
```

Every message calls the existing `/api/chat` backend with a bounded Workstream
context prompt covering status counts, item previews, evidence trace ids, and
last result summaries. The transcript preview is stored under `meta` and capped.
The response keeps `side_effect_blocked=false` and `chat_backend="api_chat"`.

### POST `/api/approve`
Submit human approval decision for a pending HITL action.

```json
{
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo",
  "session_id": "optional",
  "approved": true,
  "edited_content": null,
  "approval_id": "optional"
}
```

Resolution is **warm-first**: if the in-memory pending is found it executes in-process
(and, for an interactive tool block, continues the turn). If the warm instance is gone
(restart / session eviction), it resolves **durably** by `approval_id` (echoed back from
the `pending_approval` payload) — or by scanning the user's pending stream-intercept rows
(409 if more than one) — and runs the exact saved tool call on a rebuilt agent. When the
turn re-pauses on a new gated call, the response includes a fresh `pending_approval`
(carrying its own `approval_id`). See `docs/HITL_DESIGN_GUIDE.md` → "Interactive tool-block
HITL" for warm-vs-cold semantics.

Durable business-policy HITL resumes include explicit approval markers in the
continuation prompt (`Human approval was granted by ...`, `Approval decision:
approve`) so blocking PostTurn hooks can recognize an approved replay and avoid
creating the same approval again.

When a durable HITL approval is linked to a Workstream item, resolving it also
creates a governed Knowledge Manager candidate with `source="hitl_feedback"` and
`status="pending_review"`. This is a server-side side effect of the existing
approval resolution path, not a separate public API call. The candidate captures
the approval/rejection decision, optional `decision_note`, approval reason,
workstream/item ids, and available supplier/invoice entity keys so reviewers can
confirm, edit, archive, and route the precedent from `/dashboard/v2#knowledge`.

### GET `/api/pending`
Check if there is a pending human approval for a user.

**Query params:** `tenant_id`, `agent_id`, `user_id`

**Response:**
```json
{
  "has_pending": true,
  "operation": "write_file",
  "target": "/workspace/report.md",
  "command": "echo '...' > /workspace/report.md",
  "skill": "ar_ops",
  "type": "file_write",
  "approval_id": "ap_20260413_abc123",
  "reason": "Writing report to workspace"
}
```

### DELETE `/api/hitl/{approval_id}` (admin)
Permanently discard a **pending** HITL approval. Removes the approval record, its
tenant pending-set entry, and the checkpointed agent state. This is a discard, not
a resolve — the paused agent behind it is not resumed (use `/api/approve` or
`POST /api/hitl/{approval_id}/resolve` to actually approve/reject). Admin role
required; the caller's identity must be entitled to the resolved tenant.

**Query params:** `tenant_id` (optional; resolved against the caller's entitlements)

**Response:** `{ "deleted": true, "approval_id": "ap_20260413_abc123" }`
Returns `404` if the approval no longer exists, `403` if the caller is not an admin.

### DELETE `/api/hitl/history/{approval_id}` (admin)
Remove a single **resolved** approval from the tenant's HITL history (audit list).
Admin role required and tenant-scoped to the caller's entitlements.

**Query params:** `tenant_id` (optional; resolved against the caller's entitlements)

**Response:** `{ "deleted": true, "approval_id": "ap_20260413_abc123" }`
Returns `404` if no matching history entry is found.

### DELETE `/api/approvals/{user_id}` (admin)
Discard a pending **kernel-level** action (in-memory `pending_action`) without
executing or formally rejecting it. Clears the held action and the durable
stream-intercept row so the queue no longer surfaces it. Admin role required.

**Query params:** `tenant_id` (default `company`), `agent_id` (default `enterprise_agent`)

**Response:** `{ "deleted": true, "user_id": "demo" }`
Returns `404` if there is no pending action, `409` if multiple pending actions
exist for the user (resolve from the specific chat session instead).

### POST `/api/batch`
Run multiple queries in parallel.

```json
{
  "items": [
    {"item_id": "q1", "content": "Get AR aging", "skill_name": "ar_ops"},
    {"item_id": "q2", "content": "Get AP balance", "skill_name": "invoice"}
  ],
  "max_concurrent": 3,
  "human_approval": false,
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

**Response:** `{batch_id, total, completed, failed, results[]}`

### GET `/api/batch/status/{batch_id}`
Poll batch job status.

### GET `/api/reasoning/{trace_id}`
Get grounding critique and reasoning context for a completed trace.

---

## Skills — `/api/skills`

Read endpoints require authentication when `AUTH_ENABLED=true`. Shared skill mutations, clone/status changes, registry writes, and knowledge deletion require admin role; when entitlements are enabled they also require matching `skill:*`, `context:*`, or `skill_registry:_index` policy grants. `GET /api/skills` and `/names` filter out skills the principal cannot `use`.
`GET /api/skills` reads through the configured skill/router providers; the default path wraps the filesystem `SkillLoader` and `SkillRouter`.

### GET `/api/skills`
List all skills with metadata.

**Query params:** `user_id` (optional, for personal skills), `tenant_id`

**Response:** `{skills[], category_labels, category_order}`

### GET `/api/skills/names`
Lightweight list of skill names and categories.

### GET `/api/skills/{skill_name}`
Get full skill detail including SKILL.md content.

### POST `/api/skills`
Create a new skill.

```json
{
  "name": "my_skill",
  "description": "Handles X queries",
  "version": "1.0",
  "execution_mode": "react",
  "keywords": ["invoice", "billing"],
  "steps": [],
  "worker_skills": [],
  "tools": ["shell", "run_sql_query"],
  "business_context": {},
  "connections": [],
  "context_file": "/shared/contexts/p2p_context.md",
  "prompt": "You are an expert at...",
  "tool_scripts": []
}
```

### PUT `/api/skills/{skill_name}`
Update existing skill (same body as POST).

### DELETE `/api/skills/{skill_name}`
Delete skill and all associated files.

### POST `/api/skills/{skill_name}/test`
Run a test query against a skill.

```json
{
  "query": "Test query",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

**Response:** `{status, response, skill, duration_ms}`

### GET `/api/skills/{skill_name}/test-runs`
List recent compact Studio test runs for a skill/user.

**Query params:** `tenant_id`, `agent_id`, `user_id`, `limit`

**Response:** `{skill, runs: [{id, skill, status, duration_ms, timestamp, prompt_preview, response_preview}]}`

### POST `/api/skills/{skill_name}/clone`
```json
{"new_name": "my_skill_v2"}
```

### PATCH `/api/skills/{skill_name}/status`
```json
{"status": "draft|active|deprecated"}
```

### GET `/api/skills/{skill_name}/knowledge`
List uploaded knowledge files for a skill.

**Response:** `{files: [{filename, size_bytes, ext, modified_at, status}]}`

### POST `/api/skills/{skill_name}/knowledge/upload`
Upload a knowledge file (multipart/form-data, field `file`). Unsupported extensions return `400` with the allowed extension list.

### DELETE `/api/skills/{skill_name}/knowledge/{filename}`
Delete a knowledge file.

### GET `/api/skills/{skill_name}/component`
Serve the skill-local `component.html` template used by chat renderers when the
skill emits a fenced `skill_component` block.

### GET `/api/skills/{skill_name}/component-source`
Return editable component source for Skill Builder.

**Response:** `{skill, exists, html, url, size_bytes, updated_at}`

### PUT `/api/skills/{skill_name}/component-source`
Save reviewed component source to `skills/{skill_name}/component.html`. Requires
`manage` entitlement on the target skill. The server rejects empty HTML and
dangerous markup such as scripts, iframes, inline handlers, and `javascript:`
URLs.

```json
{"html": "<div class=\"skill-card\" data-skill-component=\"send_email\">...</div>"}
```

### POST `/api/skills/{skill_name}/component-draft`
Invoke the platform `component_authoring` skill to create or revise a proposed
component. This returns an editable draft and does not save automatically. The
request requires `read` on the target skill and `use` on `component_authoring`;
saving the reviewed HTML still requires `manage`.

```json
{
  "instruction": "Create an approval card with invoice amount and approver note",
  "current_html": "",
  "detected_contract": {"skill": "invoice_processing_ap", "props": {"invoice_id": "INV-1"}},
  "sample_props": {"invoice_id": "INV-1"},
  "tenant_id": "company"
}
```

**Response:** `{status, skill, html, sample_props, notes, warnings}`

### POST `/api/skills/tools/validate`
Validate a custom tool script.
```json
{"skill_name": "my_skill", "filename": "my_tool.py", "content": "..."}
```

### POST `/api/skills/tools/test-run`
Test-execute a custom tool script.

### GET/PUT `/api/registry`
Get or update the skill registry YAML (maps keywords → skill names).

**`entity_types` validation (PUT).** Entity types are routing/extraction identifiers,
so each must be a `snake_case` token matching `^[a-z][a-z0-9_]*$` (lowercase, letter-led,
alphanumerics + underscore; e.g. `server_name`, `cve_id`). The backend enforces this on
both payload shapes (`{raw: <yaml>}` and `{parsed: <dict>}`); a malformed value — spaces,
uppercase, a leading digit, a hyphen, or a non-string — is rejected with **HTTP 400** and
the offending entries in `detail`, regardless of which client wrote it. `entity_types` may
be omitted or an empty list (allowed; the UI warns about the routing/extraction impact).

---

## Agents — `/api/agents`

Agent reads require authentication. Create/update/delete require admin role and a `manage` entitlement on the target `agent:{agent_id}` when entitlements are enabled.

### GET `/api/agents`
List agents for a tenant.

Query parameters:

| Name | Default | Meaning |
| --- | --- | --- |
| `tenant_id` | `company` | Tenant whose agents to list. |
| `q` | _(none)_ | Case-insensitive substring filter applied server-side to the agent's `id`, `name` **and** `description`. A blank or whitespace-only value is treated as no filter and returns every agent. A term matching nothing returns `{"agents": []}`. |

The Command Center Agents page uses `q` for its search box (debounced), and keeps
an unfiltered copy of the list for the global agent selector and the registered/
online counts — those must not narrow when someone types a search term.

### GET `/api/agents/{agent_id}`
Get agent config + raw YAML.

### POST `/api/agents`
Create a new agent.

```json
{
  "name": "my_agent",
  "description": "Finance agent",
  "skills_mode": "all",
  "skills_list": [],
  "tools_allowed": ["fs", "shell", "write_file", "run_sql_query"],
  "mcp_connections": [],
  "hooks": {}
}
```

### PUT `/api/agents/{agent_id}`
Update agent config.

### DELETE `/api/agents/{agent_id}`
Delete agent.

### GET `/api/agents/{agent_id}/connectors/health`
Validate MCP connector configuration for an agent without launching connector processes.

**Response:** `{agent_id, status, connectors: [{index, name, type, transport, status, errors}]}`

### GET `/api/agents/{agent_id}/tool-execution/snapshot`
Return a bounded, redacted snapshot of passive tool observations for one agent session. The authenticated user id takes precedence over a browser-supplied `user_id`. `limit` defaults to `50`, rejects negative values with `400`, and is capped at `500`.

**Response:** `{tenant_id, agent_id, user_id, limit, count, dropped_count, events[]}`

### GET `/api/capabilities/snapshot`
Return redacted capability registry metadata plus dependency validation status. Optional query params: `tenant_id`, `include_tenant_overrides`.

**Response:** `{tenant_id, count, capabilities[], tenant_override_count, tenant_overrides[], dependency_valid, dependency_error}`

### GET `/api/capabilities/parity`
Compare registry metadata with live runtime singletons where verification is possible. Results are `ok`, `drift`, or `metadata_only` per capability.

**Response:** `{status, drift_count, checks[]}`

### GET `/api/tools`
List all available tools with descriptions and categories.

---

## Security — `/api/security`

Security Console APIs require admin role. When entitlements are enabled, the caller also needs `manage` on `security:policies`.

### GET `/api/security/policies`
Return the tenant policy YAML, parsed policy document, policy count, and validation status.

**Query params:** `tenant_id`, optional `q` and `effect` for API-backed policy search/filter results.

### PUT `/api/security/policies`
Validate and atomically save tenant policy YAML.

```json
{
  "tenant_id": "company",
  "raw": "version: \"1.0\"\npolicies: []\n"
}
```

### POST `/api/security/policies/validate`
Validate raw policy YAML without saving.

```json
{"raw": "version: \"1.0\"\npolicies: []\n"}
```

### POST `/api/security/simulate`
Evaluate the active YAML provider for an arbitrary principal, action, and resource.

```json
{
  "tenant_id": "company",
  "principal": {
    "user_id": "analyst1",
    "email": "analyst1@example.com",
    "roles": ["user"],
    "groups": ["finance"]
  },
  "action": "use",
  "resource": {"type": "skill", "id": "ar_ops"}
}
```

**Response:** `{allowed, reason, matched_policy, metadata, principal, action, resource}`.

### POST `/api/security/effective-access`
Evaluate the same principal across live tenant resources: agents, skills, tools, context files, external systems, governed databases, and MCP connections. Studio uses this for the Effective Access panel.

```json
{
  "tenant_id": "company",
  "principal": {
    "user_id": "analyst1",
    "email": "analyst1@example.com",
    "roles": ["user"],
    "groups": ["finance"]
  },
  "include_denied": true
}
```

**Response:** `{tenant_id, principal, summary, resources}` where each resource category contains `allowed`, `denied`, and per-action decision details.

### GET `/api/security/external-access`
Return the tenant external access registry from `security/external_access.yaml`, including validation status and linked credentials/MCP/context/tool metadata.

**Query params:** `tenant_id`

**Response:** `{tenant_id, path, raw, parsed, validation, resources, resource_count}`.

### POST `/api/security/external-access/validate`
Validate external access YAML without saving. **Admin only.**

**Body:** `{raw: "<yaml>"}`

**Response:** `{valid, errors[], warnings[], resource_count}`

### PUT `/api/security/external-access`
Validate and atomically save the external access registry. **Admin only.**

**Body:** `{tenant_id, raw: "<yaml>"}`

**Response:** Same as GET (updated registry).

### GET `/api/credentials`
List credential metadata for a tenant. **Secret values are never returned.** Admin only.

**Query params:** `tenant_id`

**Response:** `{tenant_id, credentials: [{name, type, scope[], ttl, metadata{}, has_value}], count}`

### PUT `/api/credentials/{name}`
Create or update a credential. Values are encrypted at rest via Fernet. **Admin only.**

**Body:** `{tenant_id, type, value: {token|key|username|password}, scope[], ttl, metadata{}}`

**Response:** `{saved: true, credential: {name, type, scope[], ttl, has_value}}`

### DELETE `/api/credentials/{name}`
Delete a credential from the tenant store. **Admin only.**

**Query params:** `tenant_id`

**Response:** `{deleted: true, name}`

### GET `/api/security/audit`
Read recent entitlement and external access decisions from `shared/databases/entitlements_audit.jsonl` and `shared/databases/external_access_audit.jsonl`.

**Query params:** `tenant_id`, `user_id`, `action`, `resource`, `allowed`, `limit`.

---

## Knowledge — `/api/knowledge`

### GET `/api/knowledge`
Query the knowledge store. This read-only dashboard endpoint uses the
lightweight `KnowledgeDashboardStore` read model and does not cold-start a full
`SkillAgent`.

**Query params:** `status` (confirmed/pending_review/archived), `knowledge_type`, `skill`, `tag`, `source`, `limit` (default 50), `offset`, `include_archived`, `tenant_id`, `agent_id`, `user_id`

### GET `/api/knowledge/stats`
Knowledge store statistics by type, status, source. This is also served from the
lightweight dashboard read model.

### GET `/api/knowledge/context-files`
List writable markdown targets for knowledge records. The response includes
traditional context files, MEMORY.md topic files, and convention-discovered
Knowledge Bundle pages under `shared/knowledge/{bundle_id}/`. It also includes
advanced skill definition targets as `category: "skill-definition"` for
`skills/{skill}/SKILL.md`.

### GET `/api/knowledge/{knowledge_id}/suggest-file`
Get a suggested file to write this knowledge record to. Suggestions can now
resolve to:

- `context` files under `/shared/contexts/`
- `memory:*` topic files under `/memory/`
- `bundle:<bundle_id>` pages under `/shared/knowledge/{bundle_id}/`
- `skill-definition` entries for explicit `SKILL.md` overrides

Bundle suggestions are selected by `manifest.yaml` skill match first, then tag
overlap. Responses include `bundle_id` when a bundle target is selected.
`SKILL.md` entries are override targets only and are not auto-selected.

### POST `/api/knowledge/confirm`
```json
{
  "knowledge_id": "k_20260413_abc",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo",
  "target_file": "/shared/contexts/p2p_context.md",
  "allow_skill_definition": false,
  "skip_file_write": false
}
```

`target_file` accepts tenant-aware virtual paths (`/shared/contexts/...`,
`/shared/knowledge/...`, `/memory/...`, `/skills/...`) or an absolute path
inside those configured roots. Paths outside the tenant roots are rejected.
If no target is supplied and `skip_file_write=false`, a convention-matched
Knowledge Bundle may be selected. `skip_file_write=true` guarantees a
record/index-only confirmation.

For `skills/<skill>/SKILL.md`, `allow_skill_definition=true` is required and the
record's skill scope must exactly match the target skill. The server confirms
the record first, publishes the file, and persists `written_to` only after the
write succeeds.

Response:
```json
{
  "status": "confirmed",
  "knowledge_id": "k_20260413_abc",
  "publication_status": "published",
  "written_to": "/absolute/tenant/path/p2p_context.md"
}
```

`publication_status` is `published`, `skipped`, `failed`, or
`published_metadata_failed`. A publication failure returns `status: "partial"`
with `append_error`; the knowledge record remains confirmed but `written_to`
stays unset when the target was not written.

### POST `/api/knowledge/bulk-confirm`
```json
{
  "knowledge_ids": ["k_abc", "k_def"],
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "reviewer",
  "publish_to_suggested_file": true
}
```

Bulk Confirm & Route auto-publishes deterministic routes (`entity`,
`source_context`, and `bundle_*`). LLM-only or unmatched routes are confirmed
record-only. The response reports `confirmed`, `published`, `confirmed_only`,
`publication_failed`, `failed`, and per-record `results`.

### POST `/api/knowledge/edit`
```json
{
  "knowledge_id": "k_20260413_abc",
  "summary": "Updated summary",
  "applies_when": "...",
  "tags": ["tag1"]
}
```

### POST `/api/knowledge/merge`
Merge duplicate knowledge records.
```json
{
  "keep_id": "k_abc",
  "archive_ids": ["k_def", "k_ghi"],
  "merged_summary": "Combined summary"
}
```

### POST `/api/knowledge/bulk-reject`
Archive multiple records. The request uses the same tenant/agent/user identity
fields as bulk confirm.

### POST `/api/thumbs`
Submit thumbs-up/thumbs-down feedback on a response.

### POST `/api/learn`
Explicitly teach the agent a new fact.
```json
{
  "summary": "ACME Corp requires PO approval above $50k",
  "type": "rule",
  "skill": "invoice",
  "applies_when": "invoice vendor is ACME Corp AND amount > 50000",
  "tags": ["approval", "vendor"]
}
```
Confirmed `/api/knowledge/learn` calls can also be mirrored into a matched
Knowledge Bundle by skill or tags; `pending_review` records wait for dashboard
confirmation before bundle writes occur.

### POST `/api/knowledge/batch-extract`
Trigger batch extraction of knowledge from recent session history.

---

## Conversations — `/api/conversations`

### GET `/api/conversations`
List conversation sessions for a user.

**Query params:** `tenant_id`, `agent_id`, `user_id`, `limit` (default 50), `offset`

**Response:** `{sessions[], total, current_session_id}`

### POST `/api/conversations/new`
Start a new session (ends current session).

### POST `/api/conversations/{session_id}/load`
Load a historical session (restores conversation history). Turns that have an `evidence_trace_id` include rehydrated `source_documents` when the persisted evidence bundle is available.

### DELETE `/api/conversations/{session_id}`
Delete a session and its history files.

### PATCH `/api/conversations/{session_id}`
Rename a session.
```json
{"title": "ACME Invoice Analysis"}
```

---

## Cron — `/api/cron`

### GET `/api/cron`
List all cron jobs. `enabled_only=true` filters inactive jobs.

### POST `/api/cron`
Create a scheduled job.
```json
{
  "name": "Morning AR Digest",
  "skill_name": "ar_ops",
  "task": "Generate daily AR aging summary and save to /workspace/morning_digest.md",
  "cron": "0 9 * * 1-5",
  "description": "Weekday morning AR digest",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "scheduler",
  "max_runtime_seconds": 300,
  "enabled": true,
  "tags": ["ar", "daily"],
  "retry_max_retries": 2,
  "retry_initial_delay": 60,
  "retry_backoff_multiplier": 2.0
}
```

### GET `/api/cron/status`
Scheduler status (running/stopped, job count).

### POST `/api/cron/start` / POST `/api/cron/stop`
Start or stop the cron scheduler.

### GET `/api/cron/{job_id}`
Get job detail with run history.

**Query params:** `include_runs=true`, `runs_limit` (default 10)

### PUT `/api/cron/{job_id}`
Update job (partial update supported).

### DELETE `/api/cron/{job_id}`
Delete job.

### POST `/api/cron/{job_id}/run`
Trigger an immediate run.

### POST `/api/cron/{job_id}/enable` / POST `/api/cron/{job_id}/disable`
Toggle job enabled state.

---

## Self-Evolution — `/api/evolution`

### POST `/api/evolution/analyze`
Start an evolution analysis job.

```json
{
  "tier": 4,
  "days_back": 7,
  "max_sessions": 100,
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "skill_filter": null,
  "analysis_mode": "standard",
  "confidence_threshold": 0.7,
  "dedup_threshold": 0.85,
  "force_fresh": false
}
```

**Tier values:**
- `1` — Load sessions only
- `2` — + Behaviour pattern classification
- `"3a"` — + Skill prompt review (SKILL.md analysis)
- `"3b"` — + Code review (Python files)
- `3` — + Both 3a and 3b combined
- `4` — + Improvement generation (full pipeline)

**Response:** Full evolution report or `{job_id}` for async jobs.

### GET `/api/evolution/status/{job_id}`
Poll async evolution job status.

### GET `/api/evolution/report/{job_id}`
Get completed evolution report.

### GET `/api/evolution/summary`
Summary of evolution capabilities and last run.

---

## Audit & Observability — `/api/audit`, `/api/traces`, `/api/history`

### GET `/api/audit`
Raw audit log entries (from `.audit/commands_*.jsonl`).

**Query params:** `tenant_id`, `agent_id`, `user_id`, `skill`, `status`, `session_id`, `limit`

### GET `/api/traces`
Execution traces with span details, paginated.

**Query params:**
- `tenant_id`, `session_id`, `since` (ISO datetime), `limit`, `offset` — scope, time filter, and pagination.
- `skill`, `user_id` — legacy single free-text filters (case-insensitive substring).
- `skills`, `users` — **repeatable** multi-select filters (e.g. `?skills=fa_ap&skills=invoice&users=admin@iaf.local`). Exact, case-insensitive match; multiple values within one parameter are OR'd, and the two parameters are AND'd together. Populate them from `/api/traces/facets`.
- `status` — one of `success`, `error`, `awaiting_human`, `cancelled`, `running`, `stale`, `partial`.

Identity scoping: a non-admin caller is pinned to their own `user_id`, and their `users` selection is ignored (they can never query across users); an admin may filter across all users.

**Response:** `{traces[], total, limit, offset}` — `total` is the count under the same scoped filters (drives pagination). Each trace carries a readable `user_name` (display name/email, a service label such as `Service (cron)`, or `Unknown user`; the raw id is never surfaced).

### GET `/api/traces/facets`
Distinct `skills` and `users` present in the trace store, for the Trace Explorer filter dropdowns. Scoped to the caller: a non-admin sees only their own activity; an admin sees all. Registered before `/api/traces/{trace_id}` so the literal path is matched.

**Query params:** `tenant_id`

**Response:** `{skills: string[], users: [{user_id, user_name}]}` — `user_name` is the readable label to display; `user_id` is the value to pass back in the `users` filter. Each list is capped for payload size.

### GET `/api/traces/{trace_id}`
Full trace with all spans and tool call timings.

### GET `/api/traces/{trace_id}/sources`
Context sources used during a trace (which context files were loaded).

### GET `/api/history`
Conversation session list with metadata.

---

## Files — `/api/files`

### GET `/api/files`
List directory contents via virtual path.

**Query params:** `path` (default "/"), `tenant_id`, `agent_id`, `user_id`

### GET `/api/files/content`
Read file content.

### POST `/api/files/write`
```json
{"path": "/workspace/report.md", "content": "# Report\n...", "tenant_id": "company", "agent_id": "enterprise_agent", "user_id": "demo"}
```

### POST `/api/files/mkdir`
Create directory.

### POST `/api/files/upload`
Upload file (multipart/form-data: `file`, `path`, `tenant_id`, `agent_id`, `user_id`).

### GET `/api/files/serve`
Download/serve a file with correct MIME type. In strict mode the query must
include `path`, `tenant_id`, `agent_id`, `user_id`, `expires`, and `signature`.
The HMAC signature binds every field and expired or modified links return 401.

### GET `/api/files/url`
Return a short-lived signed `/api/files/serve` URL for an authenticated,
file-entitled caller. File list responses also include a `serve_url`.

### GET/POST `/api/files/local-mount`
Get or configure the local filesystem mount for `/local/`.

---

## Context Manager — `/api/context-manager`

### GET `/api/context-manager`
List all context items in the knowledge base.

### POST `/api/context-manager`
Add a new context item (text, JSON, or file).

### PUT `/api/context-manager/{item_id}`
Update a context item.

### DELETE `/api/context-manager/{item_id}`
Delete a context item.

### POST `/api/context-manager/upload`
Upload a document (PDF, DOCX, TXT) to the knowledge base.

### POST `/api/context-manager/fetch-url`
```json
{"url": "https://example.com/policy.html"}
```
Fetches URL and converts to Markdown for storage.

### POST `/api/context-manager/search`
Semantic search across context items.

### POST `/api/context-manager/analyse-gap`
Analyse what context is missing for a given skill.

### POST `/api/context-manager/check-conflicts`
Check if a new context item conflicts with existing ones.

### POST `/api/context-manager/check-impact`
Assess impact of modifying an existing context item.

### GET `/api/context-manager/tree`
Get LLM-clustered tree view of context items (cached 1 hour).

### POST `/api/context-manager/reindex`
Force reindex of all context items.

---

## Command Center Queue — `/api/queue`

### GET `/api/queue/items`
List queue items. **Query params:** `status`, `priority`, `page`, `limit`

### POST `/api/queue/items`
Create a queue item.
```json
{
  "title": "AR Invoice #INV-001",
  "description": "Invoice from ACME Corp overdue by 90 days — investigate and escalate",
  "domain": "ar",
  "entity_id": "CUST-ACME",
  "priority": "P2",
  "source": "manual"
}
```

### POST `/api/queue/ingest`

Webhook endpoint for external systems (PagerDuty, ServiceNow, Kafka relays, cron
skills, custom scripts) to push work items into the Command Center queue. Send a
matching `QUEUE_INGEST_API_KEY` in `X-API-Key`. Strict mode refuses requests when
the key is missing from server configuration and rejects a body tenant other
than the deployment tenant. The keyless compatibility path exists only outside
strict mode.

**Request body:**

```json
{
  "title":          "<required, short summary shown in UI>",
  "description":    "<full text passed to the agent>",
  "domain":         "itops",                    // default: "itops"
  "entity_id":      "<optional — customer/host/incident id>",
  "priority":       "P1",                       // P1 / P2 / P3 (default P3)
  "tenant_id":      "company",                  // default: "company"
  "external_id":    "SNOW-123456",              // optional — see Idempotency below
  "bucket_seconds": 300                         // optional — see Idempotency below
}
```

**Response:** `201 Created`

```json
{ "id": "CC-A1B2C3D4", "status": "queued" }
```

**Idempotency.** Duplicate posts are silently rejected at the DB layer (`ON CONFLICT(external_id) DO NOTHING`). There are two ways to control this:

| You supply | What the server does |
|---|---|
| `external_id` (non-empty) | Honoured verbatim. Use this when you have a natural dedup key — ServiceNow incident number, PagerDuty event id, etc. |
| `external_id` omitted / empty | Server auto-computes `auto:webhook:<sha256(payload)[:12]>:<bucketed_ts>`. Two identical posts within the same time bucket collapse to one row. |
| `bucket_seconds` | Tunes the auto-bucket size. Default is `QUEUE_INGEST_DEFAULT_BUCKET_SECONDS` env (3600). Use `300` for 5-min cadence, `60` for tight retries, `86400` for daily. |

Note: the response always reports `201` and a freshly-minted `id` even when the row was deduped — the actual row count in the DB is the authoritative answer. See [cc_queue.md → Idempotency](cc_queue.md#idempotency) for full mechanics.

### GET `/api/queue/items/{item_id}`
Get full item detail including execution history.

### GET `/api/queue/hitl/pending`
List items awaiting human approval.

### POST `/api/queue/hitl/{item_id}/respond`
```json
{"approved": true, "comment": "Proceed with escalation"}
```

### POST `/api/queue/simulate`
Seed demo items for testing.

### GET `/api/queue/metrics`
Queue health metrics. Existing count fields remain stable; replica-safe queue
deployments also expose backend and worker health.

```json
{
  "claim_backend": "postgres",
  "queued": 8,
  "routing": 1,
  "running": 2,
  "awaiting_human": 1,
  "done": 34,
  "failed": 1,
  "dlq": 2,
  "avg_latency_ms": 4200,
  "total_active": 12,
  "processor_online": true,
  "processor_heartbeat": "2026-04-13T09:23:41.000Z",
  "workers_online": 2,
  "workers_expected": 2,
  "stale_claims": 0
}
```

---

## Settings — `/api/settings`, `/api/admin/config`

### GET/POST `/api/settings`
User preferences (per tenant+user).

### GET `/api/admin/config`
Read the full admin config with live values, defaults, and saved overrides.

### POST `/api/admin/config`
Save admin parameter overrides and hot-reload where possible.

### POST `/api/admin/config/reset`
Reset specific admin config overrides back to defaults. Body accepts
`{"keys": ["MAX_READ_BYTES", ...]}` or `{"keys": "__all__"}` to reset everything.

---

## Digital Twin — `/api/twin`

### GET `/api/twin/summary`
Dashboard summary (active tasks, pending approvals, throughput, error rate).

### GET `/api/twin/skills`
Per-skill performance metrics.

### GET `/api/twin/hitl`
HITL metrics (approval rate, avg decision time).

### GET `/api/twin/trends`
**Query params:** `period` (7d, 30d, 90d)

### GET `/api/twin/ar` / GET `/api/twin/ap`
AR / AP operational data.

### GET `/api/twin/exceptions`
Exception list with severity and status.

### GET `/api/twin/feed`
Activity feed (recent agent actions).

### POST `/api/twin/optimization/analyze`
Submit an optimization analysis request.

### GET `/api/twin/optimization/status/{job_id}`
Poll optimization job status.

---

## FinOps — `/api/finops`

**Tenant scoping.** Every endpoint in this section is restricted to the calling
identity's `allowed_tenants` when `AUTH_ENABLED` is on:

- Passing a `tenant_id` the caller is not entitled to returns **403 Tenant
  access denied**. It is refused before the query runs, so the refusal is never
  masked by the empty-payload fallback described below.
- Omitting `tenant_id` means *all tenants the caller is entitled to* — not every
  tenant in the database. For a single-tenant user that is their own tenant.
- An empty entitlement list resolves to the caller's own tenant, matching the
  platform-wide `... or [tenant_id]` convention in identity resolution.
- With `AUTH_ENABLED=false` (local development) no tenant filter is applied.

Query failures degrade to an empty payload with HTTP 200 so a FinOps panel never
breaks the page. Authorization failures deliberately do **not** degrade this way.

### GET `/api/finops/tenants`
Distinct tenant ids that have trace/cost data, for the dashboard tenant-filter
dropdown. The configured default `TENANT_ID` is always included so the list is
never empty on a fresh deployment. Degrades to just the default on any DB error.
Restricted to the caller's `allowed_tenants`.

```json
{ "tenants": ["company", "tenant_b"] }
```

### GET `/api/finops/dashboard`
Single read for the FinOps page. Returns summary, daily trends, purpose and model
breakdowns, skills, users, and rule-based insights together so the UI does not
fan out one request per panel.

**Query params:** `period` (days, default 7), `tenant_id`, `start` and `end`
(`YYYY-MM-DD`, both required to replace `period` with a custom range; span capped
at 366 days).

```json
{
  "summary": {
    "total_cost_usd": 1.234,
    "total_prompt_tokens": 450000,
    "total_completion_tokens": 120000,
    "total_requests": 892,
    "avg_cost_per_request": 0.00138,
    "period_days": 7
  },
  "trends": {"days": []},
  "purposes": [],
  "models": [],
  "skills": [],
  "users": [],
  "insights": []
}
```

Blank or whitespace skill names are grouped as `Unattributed`.

### GET `/api/finops/summary`
LLM cost summary. **Query params:** `period` (days, default 7), `tenant_id`, `skill`

```json
{
  "total_cost_usd": 1.234,
  "total_prompt_tokens": 450000,
  "total_completion_tokens": 120000,
  "total_requests": 892,
  "avg_cost_per_request": 0.00138,
  "period_days": 7
}
```

### GET `/api/finops/trends`
Daily cost breakdown (date, cost_usd, tokens, requests).

### GET `/api/finops/by-purpose`
Cost by LLM call purpose (routing, execution, evolution, critique).

### GET `/api/finops/by-skill`
Cost per skill.

### GET `/api/finops/by-user`
Cost per user.

### GET `/api/finops/by-model`
Model usage breakdown (model name, token counts, cost).

---

## Doc-to-Skill — `/api/skills/from-document`

### POST `/api/skills/from-document`
Upload a document (PDF, DOCX, TXT) and generate a SKILL.md from it.
Multipart form: `document` (file), `skill_name`, options.

**Response:** `{skill_md, context_files[], metadata}`

### POST `/api/skills/save-context-files`
Save generated context files to the skills directory.

### GET `/api/skill-creator/templates`
List available skill templates.

---

## File Explorer — `/api/explorer`

Admin file browser for `enterprise_root` and skills directories.

### GET `/api/explorer/roots`
List available root directories.

### GET `/api/explorer/list`
List directory. **Query params:** `root`, `path`

### GET `/api/explorer/read`
Read file content. Returns text for text files, MIME info for binaries.

### POST `/api/explorer/write`
```json
{"root": "enterprise_root", "path": "tenants/company/shared/contexts/p2p_context.md", "content": "..."}
```

### POST `/api/explorer/mkdir`
Create directory.

### DELETE `/api/explorer/delete`
Delete file or directory.

### POST `/api/explorer/rename`
Rename/move a file.

---

## Personal Skills — `/api/personal-skills`

Personal skill routes still enforce owner-or-admin access. Entitlements add `read`, `write`, `delete`, and `submit` checks on `skill:personal/{username}/{skill_name}` resources; review queue endpoints require admin plus `review` on `skill_submission:*`.

### GET `/api/personal-skills/{username}`
List personal skills for a user.

### POST `/api/personal-skills/{username}/save`
Save a personal skill draft. The body includes `skill_name`, `skill_md_content`,
optional `component_html`, and optional `source_scope`/`source_skill_name`
metadata. When supplied, the component is stored beside the personal `SKILL.md`
as `component.html`.

### GET `/api/personal-skills/{username}/{skill_name}/skill-md`
Read a personal skill draft's `SKILL.md` content for owner/admin editing.

### GET `/api/personal-skills/{username}/notifications`
List personal skill review notifications written after approval or rejection.

### DELETE `/api/personal-skills/{username}/{skill_name}`
Delete a personal skill.

### POST `/api/personal-skills/{username}/{skill_name}/submit`
Submit skill for review (promotion to shared skills). If the personal draft has
`component.html`, it is copied into the submission and promoted with the skill
when approved. Submissions opened from an existing shared skill can send
`publish_mode: "update_existing"` plus `source_skill_name`; approval then updates
that live shared skill instead of publishing a namespaced copy.

### GET `/api/skill-submissions`
Admin: list all skill submissions pending review.
Rows include `has_component` when the submission contains a skill-local
`component.html`.

### GET `/api/skill-submissions/{submission_id}/skill-md`
Admin: retrieve submitted `SKILL.md` content for preview.

### GET `/api/skill-submissions/{submission_id}/preview`
Admin: preview publish impact before approval, including conflict status, target published skill name, publish mode, conflict strategy, and a truncated SKILL.md diff when a shared skill already exists.

### POST `/api/skill-submissions/{submission_id}/review`
Admin: approve or reject a skill submission. Rejections require feedback. Approval updates an existing shared skill when `publish_mode` is `update_existing`; otherwise name conflicts are safely published as `{skill_name}__{submitted_by}` rather than overwriting the existing shared skill. On approval the submitter (`submitted_by_email`, falling back to `submitted_by`) is recorded as the skill's owner (`created_by`), so they can still edit it from Designer Studio. When an existing shared skill is updated, its original owner is kept and the approval is added as a new active version; a skill that predates versioning is first snapshotted (including its graph file) as a v1 baseline owned by `admin@iaf.local`, so it can be rolled back.

---

## Plans — `/api/plans`

### GET `/api/plans`
List saved execution plans.

### GET `/api/plans/stats`
Plan status counts (pending_review, approved, rejected).

### POST `/api/plans`
Create a plan.

### PUT `/api/plans/{plan_id}`
Update plan.

### POST `/api/plans/{plan_id}/approve`
Approve a pending plan.

### POST `/api/plans/{plan_id}/reject`
Reject a plan.

---

## Error Responses

```json
{"detail": "Error description"}
```

| Status | Meaning |
|---|---|
| 400 | Validation error or bad request |
| 401 | Missing or invalid JWT |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 409 | Conflict (duplicate name, etc.) |
| 429 | Rate limited |
| 500 | Server error |
| 503 | Dependency unavailable (Redis offline, etc.) |
