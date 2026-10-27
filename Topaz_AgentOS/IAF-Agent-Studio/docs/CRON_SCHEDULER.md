# Cron Scheduler System (Enterprise-Ready)

The IAF Agent Studio includes a **Redis-backed cron scheduler** for running skills on a schedule. This is production-ready with support for distributed workers.

> **Security:** Every cron job runs under a **service principal** (`service:cron`) with entitlement
> context wired before `agent.run()`. This ensures credential, MCP, DB, and curl audit gates are
> enforced even without an HTTP request. The default `company` tenant grants broad `external:*`
> access to `service:cron` — production deployments should tighten this to specific resources.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        server.py                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  REST APIs   │  │  Chat/Skills │  │  CronScheduler       │  │
│  │  /api/cron/* │  │              │  │  (embedded thread)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │     Redis       │
                     │  (shared state) │
                     └─────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌──────────────────────┐         ┌──────────────────────┐
│  worker.py (CLI)     │         │  worker.py (CLI)     │
│  (optional extra     │         │  (scale horizontally)│
│   workers)           │         │                      │
└──────────────────────┘         └──────────────────────┘
```

## Redis Key Structure

| Key Pattern | Type | Description |
|-------------|------|-------------|
| `iaf:scheduler:job:{id}` | Hash | Job configuration |
| `iaf:scheduler:jobs` | Set | All job IDs |
| `iaf:scheduler:jobs:enabled` | Set | Enabled job IDs |
| `iaf:scheduler:jobs:due` | Sorted Set | Jobs sorted by next_run_at timestamp |
| `iaf:scheduler:run:{id}` | Hash | Run execution record |
| `iaf:scheduler:runs:job:{job_id}` | List | Run IDs for a specific job |
| `iaf:scheduler:runs:recent` | Sorted Set | All runs sorted by time |

## Cron Job API

> **Authorization (owner-scoped RBAC).** Cron jobs are creator-owned, like skills. Every
> `/api/cron*` data endpoint requires authentication (`Depends(require_auth)`); unauthenticated
> requests get `401`.
>
> - **Ownership is server-truth.** On create, `created_by` / `user_id` / `tenant_id` are stamped
>   from the authenticated identity — the request body **cannot** set them (no impersonating another
>   user or targeting another tenant).
> - **Visibility & management.** A normal user sees and manages **only jobs they created**
>   (`created_by == user_id`); a **tenant admin** sees and manages **all** jobs in their tenant.
>   `GET /api/cron` returns `scope: "owned"` or `"all"` accordingly.
> - **Tenant isolation.** The tenant is derived from the identity; cross-tenant jobs are invisible
>   even to an admin.
> - **No existence leak.** A job the caller may not access (another user's, a different tenant's, or
>   a legacy/system job with empty `created_by` — e.g. workstream reconcilers, platform `ccd-*`, the
>   scheduler itself) returns `404`, not `403`.
> - **Scheduler start/stop** (`/api/cron/start`, `/api/cron/stop`) remain **admin-only**
>   (`Depends(require_admin)`) — they are fleet-wide operational controls, not per-user actions.
> - When `AUTH_ENABLED=false` (local dev) the dependencies resolve to a dev admin, so everything is
>   visible.
>
> Note: pre-existing jobs created before this change have an empty `created_by` and are therefore
> **admin-only** until re-attributed to a user.

| Endpoint | Method | AuthZ | Description |
|----------|--------|-------|-------------|
| `/api/cron` | GET | auth (owner-scoped; admin=all) | List cron jobs the caller may see |
| `/api/cron` | POST | auth (owner stamped from identity) | Create new cron job |
| `/api/cron/status` | GET | auth | Get scheduler status |
| `/api/cron/start` | POST | **admin** | Start the scheduler |
| `/api/cron/stop` | POST | **admin** | Stop the scheduler |
| `/api/cron/{job_id}` | GET | owner or admin | Get job with run history |
| `/api/cron/{job_id}` | PUT | owner or admin | Update job |
| `/api/cron/{job_id}` | DELETE | owner or admin | Delete job |
| `/api/cron/{job_id}/run` | POST | owner or admin | Trigger job manually |
| `/api/cron/{job_id}/enable` | POST | owner or admin | Enable job |
| `/api/cron/{job_id}/disable` | POST | owner or admin | Disable job |
| `/api/cron/{job_id}/runs` | GET | owner or admin | Get run history for a job (optional `status`/`limit` filters) |

## Create Cron Job Request

```json
{
  "name": "Daily Report",
  "skill_name": "general",
  "task": "Generate a daily summary report",
  "cron": "0 9 * * *",
  "description": "Runs every day at 9am",
  "enabled": true,
  "tags": ["reports", "daily"],
  "max_runtime_seconds": 300
}
```

## Cron Expression Format

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6)
* * * * *
```

Examples:
- `0 9 * * *` - Every day at 9:00 AM
- `*/15 * * * *` - Every 15 minutes
- `0 8-17 * * 1-5` - Hourly 8am-5pm weekdays

## Distributed Workers

```bash
# API server (includes embedded scheduler)
python3 server.py

# Optional: Additional workers for scaling
python -m iaf_agent_skills.scheduler.worker --redis-url redis://localhost:6379
```

## Scheduler Files

```
IAF-Agent-Skills/iaf_agent_skills/scheduler/
├── models.py            # Job, JobRun, RunStatus
├── scheduler.py         # CronScheduler orchestrator
├── stores.py            # JobStore abstract base
├── sqlite_store.py      # SQLite backend (dev)
├── redis_store.py       # Async Redis backend
├── sync_redis_store.py  # Sync Redis backend (server.py)
└── worker.py            # CLI worker for scaling
```

## Starting Services

```bash
# Start Redis
redis-server --daemonize yes && redis-cli ping

# Start server
python3 /path/to/IAF-Agent-Studio/server.py

# View Redis data
redis-cli KEYS 'iaf:scheduler:*'
```

On startup, Studio also reconciles Mission Mode workstreams that declare
`cron_schedule` and `cron_user_id` in
`enterprise_root/tenants/<tenant>/workstreams/*.yaml`. If Redis was reset, a
demo pack was restored from Git, or a workstream YAML has a stale `cron_job_id`,
the server recreates/updates the `ws_<workstream_name>` cron job and writes the
current `cron_job_id` back to the YAML. Non-active workstreams are registered as
disabled jobs so they remain visible without firing.

## Cron Job Form Fields

When creating or editing a job via the UI or API, the following fields are used:

| Field | Description | Example |
|---|---|---|
| `name` | Unique job identifier | `weekly_review` |
| `skill_name` | The actual skill to run (see Route via note below) | `mu_weekly_review` |
| `task` | Prompt / description passed to the skill | `"Generate my weekly review"` |
| `cron` | Cron expression for the schedule | `0 17 * * 5` |
| `enabled` | Whether the job fires automatically | `true` |
| `tags` | Optional labels for grouping | `["personal", "weekly"]` |
| `max_runtime_seconds` | Timeout before the job is marked failed | `300` |

---

## Route via: Direct vs Queue

Each cron job has a **Route via** setting that controls how the skill is invoked:

### Direct (default)
```
Scheduler fires → calls skill_name with task prompt → result in task log
```
Use this for skills that do not need visibility in the Command Center queue monitor. Examples: personal productivity skills (`mu_weekly_review`, `my_meeting_prep`), file operations, report generation.

### Queue
```
Scheduler fires → queue_ingest skill → POST /api/queue/ingest → queue processor → skill_name
```
Use this when you want the job to appear in the **Command Center monitor** at `/dashboard/v2#command-center`. The job becomes a queue item with status tracking, retry logic, and audit trail.

When Queue is selected in the UI, the system **automatically wraps** the payload — you still only specify the actual skill and prompt. The UI constructs the `queue_ingest` call transparently:

```json
// What you specify in the form:
{ "skill_name": "ccdops", "task": "process high priority invoice exceptions", "route_via": "queue", "BUCKET_SECONDS": 300 }

// What gets stored and fired by the scheduler:
{ "skill_name": "queue_ingest", "task": "skill: ccdops, priority: P2, description: process high priority invoice exceptions, BUCKET_SECONDS=300" }
```

The `queue_ingest` skill builds the `external_id` as `<skill_name>-<bucketed_timestamp>` so two firings within the same scheduling window collapse to one queue item via the UNIQUE constraint. Pick `BUCKET_SECONDS` to match the cron cadence (300 = 5 min, 900 = 15 min, 3600 = 1 hour, 86400 = 1 day). Default is 3600 if the prompt omits it. See `enterprise_root/tenants/company/skills/queue_ingest/SKILL.md` for the full mechanics.

### Cron audit row (automatic, both modes)

After **every** cron run — Direct or Queue mode — the scheduler also writes one **audit row** into `queue_items` so the firing is visible in the Command Center monitor. This row is inserted with `status='done'` (the skill already ran in the cron executor); the queue processor only picks up rows with `status='queued'`, so the audit row is never re-executed.

Two consequences worth knowing:

1. **No double execution.** The audit row is for visibility only — the processor explicitly skips `done` rows.
2. **One audit row per firing.** The audit `external_id` is `cron-<job_id>-<scheduled_epoch>` so a retry or restart within the same second cannot duplicate it.

### Choosing between Direct and Queue

| Scenario | Use |
|---|---|
| Personal skill (weekly review, meeting prep) | Direct |
| File or report generation with no monitoring need | Direct |
| Batch work item processing (invoice exceptions, tickets) | Queue |
| Any job you want visible in Command Center dashboard | Queue |
| Jobs that need retry/DLQ behaviour | Queue |

---

## UI Access

Access via `/skill-builder` → **⏰ Cron Jobs** tab:

- View all jobs with status (enabled/disabled, last run, next run)
- Create new jobs with **Skill to Run** picker, **Route via** toggle, and cron builder
- Trigger jobs manually with ▶️ button
- View run history with **View Details** modal
- See stats: total runs, success/failed counts, avg duration

**Note on existing jobs**: Jobs saved before the Route via feature was added (with `skill_name = queue_ingest`) are automatically detected when opened in the edit form — the actual skill is extracted from the task string and the toggle is set to Queue, so they display correctly.

---

## Production Deployment

### Current vs Production

| Mode | Command | Use Case |
|------|---------|----------|
| **Dev** | `python3 server.py` | Local development |
| **Prod** | API pods + Worker pods + Managed Redis | Kubernetes |

### Why Redis Matters

- **Before**: SQLite = single file, single server, can't scale
- **After**: Redis = shared state, multiple pods, horizontal scaling

Workers compete for jobs using Redis locks - no duplicate execution.

---

## Read-path performance (`/api/cron`, `/api/cron/status`)

The cron list is polled by the Command Center (~30 s per focused tab) and read by
the every-15 s dashboard ops-summary, so the **read** path is hardened to keep the
single API worker responsive (see `docs/PERF_NAVIGATION_INVESTIGATION.md`):

- **Batched Redis read.** `SyncRedisJobStore.list_jobs` fetches every job HASH in a
  single Redis **pipeline** round-trip instead of an `hgetall`-per-job loop (was a
  `1 + N` fan-out).
- **Off the event loop.** The reads run the sync scheduler via `asyncio.to_thread`,
  so a Redis walk never stalls other requests. The `/api/cron/start` and
  `/api/cron/stop` admin controls are also offloaded — `stop(wait=True, timeout=10s)`
  would otherwise block every request on the single worker for up to 10 seconds.
- **One shared read model (`shared/cron_read_cache.py`).** Both the `/api/cron`
  router and the dashboard ops-summary read through the same cache, so a multi-tab
  burst plus the 15 s ops poll collapse into one Redis walk. It provides:
  - **Short TTL (~3 s)** — a just-created/toggled job surfaces within a couple seconds.
  - **Single-flight** — concurrent misses coalesce onto one in-flight read (no
    thundering herd), verified in `tests/test_cron_read_cache.py`.
  - **Generation guard** — a read whose Redis walk started *before* a mutation is
    discarded rather than repopulating the cache after `invalidate()`, so it cannot
    serve pre-mutation data over a write.
  - **Cancellation-safe** — a cancelled read clears its in-flight slot, so it never
    poisons the key for later callers.
- **Read-your-write from every mutation path.** `invalidate()` is called by the cron
  router mutations **and** the workstream/standalone cron reconcilers, so a job
  created/removed on any path refreshes the next poll. **Eventual-consistency note:**
  a change made directly in Redis by an *external* process can still take up to the
  TTL to appear. Ownership/tenant scoping is applied *after* the cache, so the cache
  never crosses identity boundaries.
