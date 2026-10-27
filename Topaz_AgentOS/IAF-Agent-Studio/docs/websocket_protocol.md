# IAF Agent Studio — WebSocket Protocol

## Overview

IAF Agent Studio uses five WebSocket connections for real-time streaming and push notifications. All WebSocket endpoints are on the same server as the REST API.

Knowledge confirmation request fields such as `target_file`,
`allow_skill_definition`, `skip_file_write`, and
`publish_to_suggested_file` belong to the REST Knowledge API. They do not add
WebSocket message or event types.

| Endpoint | Purpose |
|---|---|
| `WS /ws/chat` | Streaming chat responses with tool call visibility |
| `WS /ws/dashboard` | Live dashboard state and approval notifications |
| `WS /ws/twin` | Digital twin telemetry and task lifecycle events |
| `WS /ws/queue` | Command Center queue item lifecycle events |
| `WS /ws/workstreams/{name}` | Workstream item lifecycle and live execution trace events |

---

## Chat WebSocket — `/ws/chat`

The primary interface for real-time agent interaction. Clients connect once and exchange messages for the duration of a session.

### Connection

```
ws://localhost:8080/ws/chat?token=<jwt_token>
```

The `token` query parameter is optional when `AUTH_ENABLED=false`. In dev/manual mode, a missing or stale browser token falls back to the dev identity from the incoming message. When `AUTH_ENABLED=true`, the token is resolved through the same `IdentityContext` access-token resolver used by HTTP middleware, so local JWT and configured OIDC/JWKS providers share tenant, role, group, scope, and allowed-tenant mapping. The message `tenant_id` must be in the resolved identity's allowed tenants, and the browser-supplied `user_id` is ignored in authenticated mode.

### Client → Server: Chat Message

```json
{
  "content": "Show overdue invoices for ACME Corp",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo",
  "session_id": "optional_session_key",
  "skill_name": null,
  "source_page": "dashboard_v2",
  "page_context": {"page": "overview", "selectedAgentId": "enterprise_agent"},
  "human_approval": true,
  "render_ui": false,
  "light_mode": false,
  "knowledge_mode": "hybrid",
  "plan_requested": false,
  "force_plan": false,
  "type": "chat",
  "critique_mode": "sync"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `content` | string | required | User's query |
| `tenant_id` | string | `"company"` | Tenant identifier |
| `agent_id` | string | `"enterprise_agent"` | Agent to invoke |
| `user_id` | string | `"demo"` | User identifier |
| `session_id` | string | null | Scope or resume a specific conversation session; AskTwin uses this to isolate each page/tab context |
| `skill_name` | string | null | Force a specific skill (bypasses routing) |
| `source_page` | string | null | AskTwin/source UI route that sent the message |
| `page_context` | object | null | Whitelisted page state used by AskTwin for contextual answers |
| `human_approval` | bool | `true` | Whether agent should request approval for write ops |
| `render_ui` | bool | `false` | Request structured UI component in response |
| `light_mode` | bool | `false` | Skip context loading for simple queries |
| `knowledge_mode` | string | `"hybrid"` | `"hybrid"` \| `"semantic"` \| `"fts5"` |
| `plan_requested` | bool | `false` | Request a plan rather than immediate execution |
| `force_plan` | bool | `false` | Force Plan Mode: route to `general`, set `execution_mode=planned`, and call `create_plan` for user approval before execution. Also sets `mode_hint=planned` so auto-orchestrator does not bypass the plan path. |
| `type` | string | `"chat"` | Message type identifier |
| `critique_mode` | string | `"sync"` | `"sync"` \| `"async"` \| `"off"` |

AskTwin can be opened by page UI actions as well as the floating button. For
example, Workstream Detail metric cards open a docked AskTwin panel and send a
short natural-language question over `/ws/chat` while the selected metric,
visible records, workstream status counts, and current lens mode are supplied in
`page_context`.

### Server → Client: Streaming Events

Events are sent as newline-delimited JSON objects. Each object has a `type` field identifying the event class.

#### `routing` — Skill Selection

```json
{
  "type": "routing",
  "skill": "ar_ops",
  "confidence": 0.95,
  "method": "keyword",
  "timestamp": "2026-04-13T09:23:41.123Z"
}
```

Emitted immediately after routing completes, before any tool calls begin.

#### `status` — Progress Update

```json
{
  "type": "status",
  "status": "Searching invoice database...",
  "timestamp": "2026-04-13T09:23:41.200Z"
}
```

Free-text progress messages emitted during execution.

#### `tool_call` — Tool Invocation

```json
{
  "type": "tool_call",
  "tool": "shell",
  "args": {
    "command": "grep -r 'ACME' /shared/contexts/p2p_context.md"
  },
  "timestamp": "2026-04-13T09:23:41.300Z"
}
```

Emitted when the agent invokes a tool. Visible in the "reasoning" panel.

#### `tool_result` — Tool Output

```json
{
  "type": "tool_result",
  "tool": "shell",
  "result": "ACME Corp: Net 60 payment terms, PO required above $50k",
  "duration_ms": 42,
  "timestamp": "2026-04-13T09:23:41.342Z"
}
```

#### `reasoning_event` — Safe Reasoning Timeline Card

```json
{
  "type": "reasoning_event",
  "event": "native_reasoning",
  "card_type": "native_reasoning",
  "label": "Azure reasoning preview",
  "provider": "azure",
  "text": "Bounded provider-native reasoning preview...",
  "origin_session_id": "session_abc",
  "timestamp": "2026-04-13T09:23:43.200Z"
}
```

Emitted over `/ws/chat` for safe right-panel reasoning timeline cards. Supported
`card_type` values include `reasoning_event`, `native_reasoning`, `continuity`,
and `governance`. The payload is bounded and intended for UI observability; it
must not contain raw private chain-of-thought. Phase 2 Azure Responses replay can
emit `native_reasoning` when the provider returns an exposed preview. If the
provider confirms native reasoning but returns no text summary for the turn, the
server emits an `Azure reasoning trace` card backed by the bounded observable
execution summary instead, so the right-side panel still shows the reasoning
path. A `continuity` card is emitted when a `response_id` is captured for
follow-up replay.

#### `response` — Final Answer

```json
{
  "type": "response",
  "content": "Found 3 overdue invoices for ACME Corp totalling $45,200...",
  "skill": "ar_ops",
  "rl_trajectory_id": "trace-uuid",
  "rl_model_call_id": "trace-uuid:model:final",
  "request_trace_id": "request-uuid",
  "evidence_trace_id": "abc12345",
  "source_documents": {
    "schema_version": "1.1",
    "trace_id": "abc12345",
    "documents": [],
    "evidence_items": []
  },
  "timestamp": "2026-04-13T09:23:44.100Z",
  "reasoning_context": {
    "routing": {
      "skill": "ar_ops",
      "confidence": 0.95,
      "method": "keyword"
    },
    "context_used": {
      "facts_referenced": ["ACME Net 60 terms"],
      "data_sources": ["/shared/contexts/p2p_context.md"],
      "short_term_turns": 2,
      "prior_skill": null
    },
    "tool_calls": [
      {
        "tool": "shell",
        "command": "grep -r 'ACME' /shared/contexts/p2p_context.md",
        "duration_ms": 42
      }
    ],
    "reasoning_summary": "Used provider-native React for skill 'ar_ops'. Gathered evidence with 1 tool call(s): shell...",
    "native_reasoning": {
      "provider": "azure",
      "preview": "Bounded provider-native reasoning preview..."
    },
    "trace_id": "abc12345",
    "critique": null
  }
}
```

The `response` event is the final event in a turn. After receiving it, the client is ready for the next user message. When business files or supported artifacts were read, `source_documents` carries the evidence bundle and `evidence_trace_id` can be used with `GET /api/evidence/{trace_id}`. `reasoning_context.reasoning_summary` is an immediate, bounded execution summary for the chat Reasoning panel; it is derived from routing/runtime/tool metadata and may later be replaced in the browser by the asynchronous episode reasoning extractor. `reasoning_context.native_reasoning` is present when native provider exposure is enabled and either the provider returned a safe preview or the server supplied an observable-summary fallback marked with `preview_source: "observable_summary"`. If `RL_CAPTURE=true`, the server records neutral capture events best-effort into tenant `rl.db` through `iaf_agent_skills.capture_events`. `rl_trajectory_id` and `rl_model_call_id` let thumbs/correction flows target the exact captured answer. If `TRACE_VALUE_ROUTER_ENABLED=true`, any follow-up Trace Value assessment is scheduled after capture and does not emit a separate WebSocket event.

#### `critique_result` — Grounding Assessment

```json
{
  "type": "critique_result",
  "trace_id": "abc12345",
  "critique": {
    "confidence": "high",
    "issues": [],
    "was_revised": false,
    "original_issues": [],
    "revised_response": null
  },
  "label": "grounding",
  "timestamp": "2026-04-13T09:23:44.500Z"
}
```

Emitted after `response` when `critique_mode != "off"`. The `was_revised` flag indicates whether the agent corrected itself during critique.

#### `plan` — Plan Pending Approval

```json
{
  "type": "plan",
  "plan_id": "plan_abc12345",
  "steps": [
    {
      "id": "step_1",
      "skill": "ar_ops",
      "task": "Get AR aging summary for ACME Corp",
      "depends_on": []
    },
    {
      "id": "step_2",
      "skill": "invoice",
      "task": "List invoices pending approval for ACME Corp",
      "depends_on": []
    },
    {
      "id": "step_3",
      "skill": "general",
      "task": "Summarise AR and invoice findings",
      "depends_on": ["step_1", "step_2"]
    }
  ],
  "critique": {
    "confidence": "high",
    "suggestions": []
  }
}
```

Emitted when `plan_requested=true` or the router decides a plan is needed. Client must respond with a `plan_action` message.

#### `error` — Execution Error

```json
{
  "type": "error",
  "message": "Failed to connect to database: /shared/databases/ap_regular.db not found",
  "timestamp": "2026-04-13T09:23:44.100Z"
}
```

### Client → Server: Plan Actions

After receiving a `plan` event, the client responds with one of:

**Approve plan:**
```json
{
  "type": "plan_action",
  "action": "approve",
  "plan_id": "plan_abc12345"
}
```

**Reject plan:**
```json
{
  "type": "plan_action",
  "action": "reject",
  "plan_id": "plan_abc12345"
}
```

**Modify and re-plan:**
```json
{
  "type": "plan_action",
  "action": "modify",
  "plan_id": "plan_abc12345",
  "feedback": "Also check the GL trial balance and include in the summary"
}
```

### Client → Server: Plan Feedback

After plan execution completes, clients can submit quality feedback:

```json
{
  "type": "plan_feedback",
  "plan_id": "plan_abc12345",
  "overall": "good",
  "step_feedback": {
    "step_1": {"rating": "good", "note": "Accurate aging data"},
    "step_2": {"rating": "poor", "note": "Missed 2 invoices on hold"}
  }
}
```

### Turn Sequence Diagram

```
Client                        Server
  |                             |
  |── chat message ────────────>|
  |                             |
  |<── {"type":"routing"} ──────|  skill selected
  |<── {"type":"status"} ───────|  progress update
  |<── {"type":"tool_call"} ────|  tool invoked
  |<── {"type":"tool_result"} ──|  tool output
  |<── {"type":"tool_call"} ────|  (may repeat)
  |<── {"type":"tool_result"} ──|
  |<── {"type":"response"} ─────|  final answer
  |<── {"type":"critique_result"}|  if critique enabled
  |                             |
  |── (next message) ──────────>|
```

---

## Dashboard WebSocket — `/ws/dashboard`

Live push feed for the Agent Command Surface dashboard. Clients receive state snapshots and real-time events about approvals and tasks.

### Connection

```
ws://localhost:8080/ws/dashboard
```

### Server → Client Events

#### `snapshot` — Full State

```json
{
  "type": "snapshot",
  "tenant_id": "company",
  "active_sessions": 3,
  "pending_approvals": 1,
  "total_tasks_today": 47,
  "success_rate": 0.94,
  "queue_depth": 8,
  "top_skills": ["ar_ops", "invoice", "general"],
  "agents": [
    {
      "key": "company:enterprise_agent:amy@iaf.local:admin",
      "tenant_id": "company",
      "agent_id": "enterprise_agent",
      "user_id": "amy@iaf.local",
      "user_role": "admin",
      "current_skill": "fa_ap",
      "has_pending": false,
      "history_length": 12,
      "auto_run": false
    }
  ],
  "agent_liveness": {
    "enterprise_agent": {
      "is_online": true,
      "last_active": "2026-09-04T09:23:11.900000+00:00",
      "session_count": 2
    }
  },
  "timestamp": "2026-04-13T09:23:41.123Z"
}
```

Sent immediately on connection and periodically (every 30 seconds).

**Scope.** Every field is scoped to one tenant, resolved from the connection's
identity and echoed back as `tenant_id`. `agents` lists only that tenant's live
sessions.

**`agents[]`.** One row per live session. `agent_id`, `tenant_id`, `user_id` and
`user_role` are served as separate fields — clients must **not** parse them out
of `key`, which is an internal cache key and not a stable contract.

**`agent_liveness`.** Keyed by `agent_id`. `is_online` means at least one session
for that agent was used within the server's idle window
(`SessionState.ONLINE_IDLE_SECONDS`, 300 s) — not merely that a cached agent
object exists. `last_active` is an ISO-8601 UTC timestamp, or `null` if no
activity has been recorded. `session_count` counts sessions, so an agent with two
users is one online agent with `session_count: 2`.

**Limitation — single process.** Liveness is computed from this process's agent
cache. Behind more than one replica it reflects the replica serving the socket,
not the deployment. Cross-replica liveness requires publishing the signal to a
shared store and is not implemented.

#### `approval_new` — New Approval Required

```json
{
  "type": "approval_new",
  "user_id": "demo",
  "approval_id": "ap_20260413_abc",
  "operation": "write_file",
  "target": "/workspace/monthly_report.md",
  "skill": "ar_ops",
  "reason": "Writing month-end AR report",
  "timestamp": "2026-04-13T09:23:45.000Z"
}
```

#### `approval_resolved` — Approval Decision Made

```json
{
  "type": "approval_resolved",
  "user_id": "demo",
  "approval_id": "ap_20260413_abc",
  "action": "approved",
  "timestamp": "2026-04-13T09:23:52.000Z"
}
```

#### `task_started` — Agent Task Began

```json
{
  "type": "task_started",
  "task_id": "task_20260413_xyz",
  "user_id": "demo",
  "skill": "ar_ops",
  "query_preview": "Show overdue invoices...",
  "timestamp": "2026-04-13T09:23:41.000Z"
}
```

#### `task_completed` — Agent Task Finished

```json
{
  "type": "task_completed",
  "task_id": "task_20260413_xyz",
  "user_id": "demo",
  "skill": "ar_ops",
  "duration_ms": 3240,
  "success": true,
  "timestamp": "2026-04-13T09:23:44.240Z"
}
```

#### `cron_started` / `cron_completed` — Scheduled Job Lifecycle

```json
{
  "type": "cron_started",
  "job_id": "job_morning_ar",
  "name": "Morning AR Digest",
  "skill": "ar_ops",
  "timestamp": "2026-04-13T09:00:00.000Z"
}
```

### Client → Server

```json
{"type": "refresh"}
```

Requests an immediate `snapshot` response.

---

## Twin WebSocket — `/ws/twin`

Operational telemetry stream for the Digital Twin dashboard.

### Connection

```
ws://localhost:8080/ws/twin
```

### Server → Client Events

#### `refresh` — Periodic Snapshot

```json
{
  "type": "refresh",
  "summary": {
    "active_tasks": 2,
    "pending_hitl": 0,
    "throughput_1h": 24,
    "error_rate_1h": 0.04
  },
  "timestamp": "2026-04-13T09:23:41.123Z"
}
```

Emitted every 30 seconds from the `twin_telemetry.db`.

#### `task_started` / `task_completed` / `task_error`

```json
{"type": "task_started",   "task_id": "...", "user_id": "...", "skill": "..."}
{"type": "task_completed", "task_id": "...", "skill": "...", "duration_ms": 3240}
{"type": "task_error",     "task_id": "...", "error": "..."}
```

#### `hitl_resolved`

```json
{
  "type": "hitl_resolved",
  "approval_id": "ap_20260413_abc",
  "decision": "approved",
  "timestamp": "2026-04-13T09:23:52.000Z"
}
```

### Client → Server

```json
{"type": "ping"}
```

Server responds with `{"type": "pong"}`.

---

## Queue WebSocket — `/ws/queue`

Real-time lifecycle events for the Command Center autonomous queue.

### Connection

```
ws://localhost:8080/ws/queue
```

### Server → Client Events

#### `item_created`

```json
{
  "type": "item_created",
  "item": {
    "id": "CC-A1B2C3D4",
    "title": "AR Invoice #INV-001",
    "domain": "ar",
    "priority": "P2",
    "status": "queued",
    "created_at": "2026-04-13T09:23:41.000Z"
  }
}
```

#### `item_updated`

```json
{
  "type": "item_updated",
  "item_id": "CC-A1B2C3D4",
  "status": "running",
  "skill": "ar_ops",
  "routed_at": "2026-04-13T09:23:42.000Z"
}
```

#### `item_completed`

```json
{
  "type": "item_completed",
  "item_id": "CC-A1B2C3D4",
  "exec_id": "exec_20260413_xyz",
  "summary": "Invoice escalated to collections team. 3 follow-up emails sent.",
  "timestamp": "2026-04-13T09:23:47.000Z"
}
```

#### `item_failed`

```json
{
  "type": "item_failed",
  "item_id": "CC-A1B2C3D4",
  "reason": "max_retries_exceeded",
  "retry_count": 3,
  "timestamp": "2026-04-13T09:24:00.000Z"
}
```

#### `hitl_pending`

```json
{
  "type": "hitl_pending",
  "item_id": "CC-A1B2C3D4",
  "exec_id": "exec_20260413_xyz",
  "approval_id": "ap_20260413_abc",
  "prompt": "Invoice INV-001 from ACME Corp ($125,000) exceeds auto-approval limit. Approve to escalate to VP Finance?",
  "timestamp": "2026-04-13T09:23:45.000Z"
}
```

#### `step_added`

```json
{
  "type": "step_added",
  "item_id": "CC-A1B2C3D4",
  "exec_id": "exec_20260413_xyz",
  "step": {
    "step_number": 4,
    "step_name": "EXECUTING_TOOLS",
    "output": "SQL query completed",
    "action": "progress"
  }
}
```

Emitted while an expanded Command Center item is running. The event carries a
bounded preview; the dashboard refetches the full item detail to render the
persisted `job_steps` rows.

#### `snapshot`

```json
{
  "type": "snapshot",
  "metrics": {
    "claim_backend": "postgres",
    "queued": 8,
    "routing": 1,
    "running": 2,
    "awaiting_human": 1,
    "processor_online": true,
    "workers_online": 2,
    "workers_expected": 2,
    "stale_claims": 0
  }
}
```

Sent on connect and in response to `{"type":"refresh"}`. The `metrics` object
matches `GET /api/queue/metrics`; the worker and stale-claim fields are
additive and backward compatible.

---

## Workstream WebSocket — `/ws/workstreams/{name}`

Real-time lifecycle and execution-trace events for one Mission Mode workstream.

### Connection

```
ws://localhost:8080/ws/workstreams/ap_nightly_cleanup?tenant_id=company&token=<access-token>
```

When authentication is enabled, Studio validates the JWT, binds the requested
tenant to the principal's allowed tenants, and requires `read` entitlement on
`workstream:<name>` before accepting. Authentication failure closes with 4401;
tenant or entitlement denial closes with 4403. Development mode still binds a
local dev principal.

### Server -> Client Events

#### `snapshot`

```json
{
  "type": "snapshot",
  "workstream": {
    "name": "ap_nightly_cleanup",
    "status": "active",
    "items": []
  }
}
```

Sent immediately after connection with the current workstream YAML/API state.

#### `mission_item_started`

```json
{
  "type": "mission_item_started",
  "workstream_name": "ap_nightly_cleanup",
  "item_id": "AP-0421",
  "execution_id": "wse_abc123def456",
  "attempts": 1,
  "summary": "item AP-0421 -> running",
  "ts": "2026-06-15T17:58:00+00:00"
}
```

Emitted after Mission Mode claims an item and before `agent.run()` starts. The
detail page uses it to mark the item in progress and clear the live trace buffer.

#### `mission_item_step`

```json
{
  "type": "mission_item_step",
  "workstream_name": "ap_nightly_cleanup",
  "item_id": "AP-0421",
  "execution_id": "wse_abc123def456",
  "step": {
    "step_id": 42,
    "step_index": 3,
    "step_number": 3,
    "tool_name": "run_sql_query",
    "step_name": "run_sql_query",
    "status": "completed",
    "duration_ms": 120,
    "input_preview": "",
    "output_preview": "Fetched payment release candidate",
    "error_preview": "",
    "action": "progress",
    "phase": "EXECUTING_TOOLS",
    "timestamp": "2026-06-15T17:58:02+00:00"
  },
  "summary": "Fetched payment release candidate",
  "ts": "2026-06-15T17:58:02+00:00"
}
```

Emitted for normalized `agent.run(status_callback=...)` progress and tool steps.
When Studio's Workstream runtime DB is available, the step is first appended to
`workstream_steps`; `step_id`, `step_number`, and `timestamp` identify the
stored row. The generic and BP Workstream Detail pages optimistically append the
event, deduplicate by `step_id` or execution/step number, and if the item is
expanded refetch `/api/workstreams/{name}/items/{id}/executions` to render the
durable trace. After completion or HITL pause, the UI can still fall back to the
bounded YAML `execution_ledger[].steps` audit history.

#### Terminal mission events

Mission Mode also emits the existing terminal lifecycle events:

- `mission_item_processed`
- `mission_item_escalated`
- `mission_item_failed`
- `mission_complete`
- `item_resuming`
- `item_resolved`

The detail page refreshes workstream state and pending approvals when these
events arrive.

---

## Connection Management

### Reconnection

WebSocket connections are not automatically resumed after a disconnect. Clients should implement exponential backoff reconnection:

```javascript
let retryDelay = 1000;
function connect() {
  const ws = new WebSocket("ws://localhost:8080/ws/chat");
  ws.onclose = () => {
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 30000);
  };
  ws.onopen = () => { retryDelay = 1000; };
}
```

### Session Continuity

Session state is maintained server-side in Redis (or in-memory when Redis is unavailable). After reconnecting, send the same `session_id` to resume conversation context.

### Authentication Expiry

When `AUTH_ENABLED=true`, the JWT in the query parameter must be valid at connection time. The WebSocket stays open until the client disconnects — the token is not re-validated mid-session. Refresh the token before connecting if it is close to expiry. When `AUTH_ENABLED=false`, expired browser tokens are ignored and the server uses the dev identity for local testing.

---

## Error Handling

If the server encounters an unrecoverable error during a request, it sends:

```json
{"type": "error", "message": "..."}
```

The WebSocket connection remains open after an error — clients do not need to reconnect.

If the server cannot parse an incoming message, it responds:

```json
{"type": "error", "message": "Invalid message format"}
```

---

## Testing WebSockets

Using `wscat`:

```bash
# Install wscat
npm install -g wscat

# Connect to chat
wscat -c "ws://localhost:8080/ws/chat"

# Send a message
> {"content":"Hello","tenant_id":"company","agent_id":"enterprise_agent","user_id":"demo"}
```
