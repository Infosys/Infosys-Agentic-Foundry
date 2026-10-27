# IAF Agent Studio — Command Center Queue

## Overview

The Command Center Queue (cc_queue) is an autonomous job processor that handles asynchronous agent tasks. Instead of requiring a human to type each query, external systems or scheduled processes push work items into the queue, and the processor routes each item to the correct skill and runs it autonomously.

Typical use cases:
- AR invoice exceptions pushed by ERP webhooks
- IT helpdesk tickets escalated from ServiceNow
- Periodic compliance checks (without cron scheduling)
- Batch processing of pending approvals

## Storage Location

The queue DB is tenant business/runtime state, so the default location is now:

```text
enterprise_root/tenants/<tenant_id>/shared/databases/command_center.db
```

`CC_QUEUE_DB_PATH` can still override this location. Relative override paths
resolve from `IAF-Agent-Studio/`. On first startup after the path change, if a
legacy `IAF-Agent-Studio/command_center.db` exists and the tenant-root DB does
not, Studio copies the legacy file into the tenant-root location.

SQLite is the local/default Command Center backend. Startup applies additive
schema upgrades to existing SQLite queue databases before creating indexes, so
older local `command_center.db` files continue to work when new queue lease
columns are introduced.

---

## Architecture

```
External System              Queue Processor          Agent Engine
(ERP, ServiceNow, etc.)           │                        │
        │                         │                        │
        │ POST /api/queue/ingest   │                        │
        ├────────────────────────>│                        │
        │                         │                        │
        │                    items table                   │
        │                  (status=queued)                 │
        │                         │                        │
        │                    Poll every 2s                 │
        │                         │                        │
        │                    Claim item                    │
        │                  (status=running)                │
        │                         │                        │
        │                    Route to skill                │
        │                         ├──────────────────────>│
        │                         │    SkillAgent.run()    │
        │                         │<──────────────────────┤
        │                         │                        │
        │                    Update item                   │
        │                  (status=done|dlq)               │
        │                         │                        │
WS /ws/queue <──── push events ──┤                        │
```

---

## Queue Item Lifecycle

### State Machine

```
                  [queued]
                      │
         Processor.claim_next()
                      │
                  [running]
                      │
           ┌──────────┼──────────┐
           │          │          │
        [done]  [awaiting_human]  [dlq]
                      │
              (HITL approval)
                      │
                  [running]
                      │
                  [done|dlq]
```

### States

| State | Description |
|---|---|
| `queued` | Waiting to be processed |
| `routing` | Claimed and being routed to a skill (leased, in-flight) |
| `running` | Currently being executed by the processor |
| `done` | Completed successfully |
| `awaiting_human` | Paused, waiting for human approval |
| `failed` | Execution failed (moved to DLQ on max retries; a `dlq_items` row is also written) |
| `dlq` | Dead letter queue — max retries exceeded or unroutable (tracked in the separate `dlq_items` table) |

When `RL_CAPTURE=true`, queue lifecycle changes are emitted through
`iaf_agent_skills.capture_events` and mirrored best-effort into the independent
RL/eval store as raw `queue` reward events. Queue execution does not import
`rl_capture` directly.

---

## Queue Item Model

### `QueueItem`

| Field | Type | Description |
|---|---|---|
| `id` | string | Auto-generated `CC-XXXXXXXX` |
| `tenant_id` | string | Tenant this item belongs to |
| `external_id` | string | Deduplication key (UNIQUE). Auto-computed by the server if the caller doesn't supply one — see "Idempotency" below. |
| `title` | string | Short summary (shown in UI) |
| `description` | string | Full context text passed to the agent |
| `domain` | string | Business domain: `ar`, `ap`, `itops`, `finops` |
| `entity_id` | string | Customer/invoice/ticket ID |
| `priority` | string | `P1`, `P2`, `P3` |
| `status` | string | Current state (see above) |
| `source` | string | `webhook`, `manual`, `simulated` |
| `created_at` | datetime | When the item was queued |
| `claimed_at` | datetime | When a processor claimed it |
| `completed_at` | datetime | When processing finished |
| `retry_count` | int | Number of times retried |
| `routed_skill` | string | Skill assigned after routing |
| `routing_reason` | string | Human-readable routing explanation |

### `Execution` (per attempt)

| Field | Type | Description |
|---|---|---|
| `id` | string | UUID per execution attempt |
| `item_id` | string | Parent item |
| `skill_name` | string | Skill used |
| `status` | string | `completed`, `failed`, `awaiting_human`, `timeout` |
| `started_at` | datetime | |
| `completed_at` | datetime | |
| `result_summary` | string | Truncated agent response |
| `evidence_trace_id` | string | Trace id for the evidence bundle stored by `/api/evidence` |
| `evidence_count` | int | Number of normalized evidence items captured for the execution |
| `job_steps` | List[dict] | Status callback messages captured during execution |

---

## Processor Logic

When a queue item reads business files or supported artifacts, the processor persists the normalized evidence bundle through `EvidenceCollectorAdapter` to `shared/databases/evidence.db` and writes `evidence_trace_id` plus `evidence_count` to `job_executions`. Queue monitors and downstream systems can retrieve the bundle via `GET /api/evidence/{evidence_trace_id}`.

The processor also emits bounded lifecycle telemetry without changing the queue schema:

- `QueueItemReceived` and `QueueItemRouted` are structured audit records written before a skill-scoped agent exists. They do not go through `HookRunner`.
- After routing, queue execution hooks run through the per-item `SkillAgent.hook_runner`: `BeforeQueueItemStart`, `AfterQueueItemComplete`, `OnQueueItemError`, `BeforeQueueRetry`, `OnQueueDLQ`, and `OnQueueHITLPending`.
- Phase 1 queue hooks are observe-only and fail-open. A failing hook cannot block queue state transitions, and the global `CAPABILITY_HOOKS_ENABLED` switch suppresses fan-out.
- Hook context includes `queue_item_id`, execution id, queue status, skill, priority, retry count, redacted payload/result previews, and evidence trace/count when available.
- If `RL_CAPTURE=true`, queue state transitions are also mirrored best-effort to
  the RL/eval store as raw `queue` reward events. Labels include `queued`,
  `ingested`, `done`, `retry`, `awaiting_human`, `failed`, `dlq`, and
  `dlq_retry`; exporters decide later how those labels map to shaped rewards.

### Poll Loop

The processor runs a background async loop (interval: `QUEUE_POLL_INTERVAL=2` seconds):

1. Query DB: `SELECT * FROM queue_items WHERE status='queued' ORDER BY priority, created_at LIMIT {max_concurrent}`
2. Claim each item atomically: `UPDATE SET status='running', claimed_at=now()`
3. Launch each claimed item as an `asyncio.Task`

Maximum concurrent items: `8` (configurable via the `QUEUE_MAX_CONCURRENT_JOBS` env var; the processor holds this as the internal `MAX_CONCURRENT` constant).

### Routing

If `entity_id` names a skill that exists in `_index.yaml`, the processor treats it as an explicit target and routes directly to that skill with confidence `1.0`. This is the preferred path for scheduler-created queue work because the cron definition already knows the intended processor skill.

```python
skill_name, confidence, reasoning, latency_ms = await SkillRouter.match(
    description,
    return_details=True
)
```

If no explicit skill is present, the processor falls back to the configured
router provider's `match(...)` method. The default provider wraps
`SkillRouter.match(...)`. If no skill matches (confidence below threshold), the
item moves directly to DLQ with reason `"no_matching_skill"`.

### Skill Execution

```python
agent = SkillAgent(
    tenant_id=item.tenant_id,
    agent_id="enterprise_agent",
    user_id=f"queue_{item.id}"      # Isolated session per item
)
result = await asyncio.to_thread(
    agent.run,
    item.description,
    skill_name=skill_name
)
```

- Each item gets its own session ID: `queue_{item_id}`
- A **service principal** (`service:queue`) is created and wired via `set_entitlement_context()` before execution, ensuring credential, MCP, DB, and curl audit gates are enforced even without an HTTP request context
- Skill-scoped queue lifecycle hooks use this same per-item agent's `hook_runner`; no processor-global hook runner is created
- The processor stamps `entrypoint=queue`, `queue_item_id`, and execution id onto the agent before `agent.run()`, so any blocking hook configured with `on_block: hitl` creates an approval checkpoint with queue attribution
- Execution timeout: `QUEUE_SKILL_TIMEOUT_SEC=300` (5 minutes). A value `<= 0` means **no limit** — the processor normalises non-positive values to `None` so `asyncio.wait_for` waits indefinitely instead of timing out immediately.
- Status callback messages are captured and stored in `job_steps`

### HITL Detection

During execution, the processor monitors for HITL signals in the agent output:

```python
_HITL_SIGNALS = [
    "waiting for human approval",
    "approval requested",
    "approval_id",
    "awaiting approval",
    "human approval",
    "hitl"
]
```

When detected:
1. `_HITLPauseSignal` is raised with `approval_id` and `prompt`
2. Item status set to `awaiting_human`
3. Item ID stored in `ApprovalStore`
4. WebSocket event `hitl_pending` pushed to queue subscribers

On approval resolution:
1. `ApprovalStore` callback fires
2. Item status set back to `running`
3. Execution resumes with the approval decision injected

### Retry Policy

| Condition | Retry? | Limit |
|---|---|---|
| Skill execution exception | Yes | 3 |
| Skill execution timeout | Yes | 3 |
| Max retries exceeded | → DLQ | — |
| No matching skill | → DLQ immediately | — |
| Unhandled exception | Yes | 3 |

After each failure, `retry_count` is incremented and status set back to `queued`. Exponential backoff is not applied in the current implementation — items rejoin the queue tail immediately.

---

## REST API

### Create an Item

```http
POST /api/queue/items
Content-Type: application/json

{
  "title": "ACME Corp — Invoice #INV-2024-089 Overdue 90+ Days",
  "description": "ACME Corp (CUST-ACME) has invoice INV-2024-089 for $45,200 overdue 90+ days. No response to 2 reminder emails. Investigate and determine next escalation step per AR SLA policy.",
  "domain": "ar",
  "entity_id": "CUST-ACME",
  "priority": "P1",
  "source": "manual"
}
```

### Webhook Ingest

External systems use the webhook endpoint with an API key:

```http
POST /api/queue/ingest
X-API-Key: your-api-key
Content-Type: application/json

{
  "external_id": "SNOW-123456",
  "title": "Server CPU High — PROD-APP-01",
  "description": "Production application server PROD-APP-01 showing sustained CPU >90% for 15 minutes. ServiceNow incident INC-123456. Investigate root cause.",
  "domain": "itops",
  "entity_id": "PROD-APP-01",
  "priority": "P1",
  "source": "webhook"
}
```

`QUEUE_INGEST_API_KEY` is mandatory in strict enterprise mode and should be at
least 32 random characters. A missing server key returns 503; a wrong caller key
returns 401. Strict mode also rejects payloads for a tenant other than the
dedicated deployment tenant. The keyless path is development compatibility
only.

### Idempotency

Duplicate protection is enforced by the platform — callers no longer have to compute a stable dedup key themselves.

**If the caller passes `external_id`:**

The value is honoured verbatim. A second POST with the same `external_id` is rejected by the UNIQUE constraint (`ON CONFLICT(external_id) DO NOTHING`) and the row is not inserted again. Use this when you have a natural dedup key (ServiceNow incident number, PagerDuty event id, etc.).

**If the caller omits `external_id` (or sends an empty string):**

The server synthesises one from a content fingerprint plus a time bucket:

```
external_id = auto:<source>:<sha256(tenant|domain|entity|title|description|priority)[:12]>:<bucketed_timestamp>
```

- The **content hash** changes when the payload changes — different work → different external_id.
- The **time bucket** is `int(time.time()) // bucket_seconds * bucket_seconds`. Two posts of the same payload within the same window collapse to one row. The next window admits a fresh row.
- The default bucket is **3600 seconds** (1 hour). Tune per request by passing `bucket_seconds` in the body, or globally via the env var `QUEUE_INGEST_DEFAULT_BUCKET_SECONDS`.

Example — a periodic webhook fires every minute but you only want one row per 5-minute window:

```json
{
  "title": "GC pressure on PROD-APP-01",
  "description": "JVM old-gen > 85% for 2 minutes",
  "domain": "itops",
  "priority": "P2",
  "bucket_seconds": 300
}
```

Five firings within the same 300-second window → one queue item. The next window admits a fresh one if the alert is still active.

**For cron-fed work items:**

Cron jobs running in Queue mode are inserted by the scheduler's internal trusted path rather than by an agent-generated shell/curl call. The scheduler parses legacy `queue_ingest` task prompts into the same payload fields, computes the same content/time-bucket dedup key with source `cron`, and inserts a real `queue_items` row. If the dedup key already exists, the scheduler returns the existing row; if that row is `failed`, it requeues the existing item for recovery instead of reporting a fake new ID. The `queue_ingest` skill remains useful for manual/demo compatibility, but scheduler-to-queue handoff should be programmatic.

### Check Pending HITL

```http
GET /api/queue/hitl/pending
```

Returns all items in `awaiting_human` state with their approval prompts.

### Respond to HITL

```http
POST /api/queue/hitl/{item_id}/respond
Content-Type: application/json

{
  "response": "Approve",
  "notes": "Proceed with escalation to VP Finance"
}
```

---

## WebSocket Events

Subscribe to `WS /ws/queue` to receive real-time lifecycle events. See [websocket_protocol.md](websocket_protocol.md) for the full event schema.

Key events:
- `item_created` — New item added
- `item_updated` — Status change (queued → running, etc.)
- `item_completed` — Successful completion with result summary
- `item_failed` — Processing failed, moved to DLQ
- `hitl_pending` — Item paused, needs human decision
- `metrics` — Aggregate queue health (every 10 seconds)

---

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `QUEUE_POLL_INTERVAL` | `2` | Seconds between poll cycles |
| `QUEUE_MAX_CONCURRENT_JOBS` | `8` | Maximum simultaneous items |
| `QUEUE_SKILL_TIMEOUT_SEC` | `300` | Per-item execution timeout (seconds). `<= 0` = no limit (wait indefinitely) |
| _(max retries)_ | `3` | Hardcoded to `3` in the processor (`MAX_RETRIES`); not read from an env var. Reaching it moves the item to DLQ |
| `QUEUE_SEED_DEMO` | `false` | Seed demo items on startup |
| `CC_QUEUE_DB_PATH` | `IAF-Agent-Studio/command_center.db` | Optional SQLite DB path override; useful for isolated tests or separate queue workers |
| `CC_QUEUE_STORAGE_BACKEND` | `sqlite` | Command Center claim store: `sqlite` or `postgres` |
| `CC_QUEUE_DATABASE_URL` | empty | Optional Postgres DSN for the Command Center claim store; falls back to `DATABASE_URL` |
| `QUEUE_CLAIM_LEASE_SECONDS` | `360` | Lease duration for claimed queue items |
| `QUEUE_CLAIM_RECLAIM_LIMIT` | `3` | Expired claim requeues before an item is sent to DLQ |
| `QUEUE_WORKER_HEARTBEAT_TTL_SECONDS` | `30` | Worker heartbeat freshness window used by metrics and the dashboard |
| `STUDIO_RUNTIME_ROLES` | `all` | Use `queue` for the standalone worker process |
| `QUEUE_WORKER_REPLICAS` | `1` | Startup guard; values greater than one require `DB_BACKEND=postgres` and `CC_QUEUE_STORAGE_BACKEND=postgres` |

Run `python3 IAF-Agent-Studio/queue_worker.py` as a dedicated process in the
enterprise topology. API replicas initialize the shared queue store for reads,
ingest, metrics, HITL, and DLQ actions, but only queue roles process items.

SQLite remains the default single-worker backend. The Postgres backend adds
transactional claims with `FOR UPDATE SKIP LOCKED`, `claim_token` fencing,
renewed leases, stale-claim reclaim, and a `queue_workers` heartbeat registry.
Fencing prevents a stale worker from completing an item after another worker has
reclaimed it. External side effects are still at-least-once and must use the
existing idempotency keys or provider-level idempotency controls.

### SQLite to Postgres queue migration

Pause queue workers, back up `command_center.db`, then dry-run and copy queue
tables into the initialized Postgres claim schema:

```bash
python3 IAF-Agent-Studio/scripts/migrate_command_center_to_postgres.py \
  --sqlite enterprise_root/tenants/company/shared/databases/command_center.db \
  --postgres "$DATABASE_URL" \
  --dry-run

python3 IAF-Agent-Studio/scripts/migrate_command_center_to_postgres.py \
  --sqlite enterprise_root/tenants/company/shared/databases/command_center.db \
  --postgres "$DATABASE_URL"
```

Start one Postgres queue worker first and verify `/api/queue/metrics`, item
listing, HITL, DLQ, and Recovery Readiness duplicate checks. Only then raise
`QUEUE_WORKER_REPLICAS` above one. Rollback returns to one SQLite worker using
the pre-migration backup.

For staging soak, run:

```bash
python3 IAF-Agent-Studio/scripts/soak_command_center_queue.py \
  --api-url https://staging-agentpro.example.com \
  --api-key "$QUEUE_INGEST_API_KEY" \
  --count 100
```

The helper ingests uniquely keyed items, polls until they reach terminal states,
checks for duplicate completed executions per item, and fails if stale claims
remain. During the poll window, operators can terminate one queue worker to
exercise lease reclaim and failover.

---

## Monitoring

### Health Metrics (`GET /api/queue/metrics`)

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
  "workers_online": 2,
  "workers_expected": 2,
  "stale_claims": 0
}
```

The local `processor_heartbeat` timestamp advances on queue-role poll cycles.
With the Postgres claim backend, `processor_online` is aggregated from shared
worker heartbeats so API replicas can report worker health without running a
processor.

### Item Status History

Every item has a full execution history:

```http
GET /api/queue/items/{item_id}
```

Returns the item plus all `Execution` records — including failed attempts, HITL pauses, and the final completion.

---

## Demo Mode

Set `QUEUE_SEED_DEMO=true` to populate the queue with realistic demo items on startup. This is useful for demoing the queue UI without external webhook infrastructure.

Alternatively, trigger manual simulation:

```http
POST /api/queue/simulate
```

This injects 4 pre-built ITOps demo scenarios (all `domain=itops`) at mixed priorities (P1/P2) to demonstrate the full queue lifecycle. The seed is idempotent — items are deduped/re-queued by a tenant-qualified `external_id`.
