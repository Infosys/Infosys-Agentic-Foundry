# Dedicated Enterprise Operations Profile

This is the P0 operating baseline for one AgentPro deployment dedicated to one
enterprise. It is not a shared SaaS control plane. Capacity, availability, and
recovery targets below are provisional until that enterprise's staging load and
restore tests pass.

## Required topology

- Enterprise ingress terminates TLS and SSO, then forwards only to API replicas.
- API processes run with `STUDIO_RUNTIME_ROLES=api` and
  `USE_REDIS_SESSIONS=true`; strict startup fails unless shared Redis sessions
  are reachable.
- Two scheduler candidates may run with `STUDIO_RUNTIME_ROLES=scheduler`; Redis
  elects one active leader and the other remains standby.
- Command Center starts with one process using `STUDIO_RUNTIME_ROLES=queue`,
  `QUEUE_WORKER_REPLICAS=1`, and SQLite. Queue replicas are allowed only after
  the Command Center store has migrated to Postgres with
  `CC_QUEUE_STORAGE_BACKEND=postgres`; workers then claim rows with fenced leases
  and heartbeat into the shared registry.
- Kernel execution can be isolated into a separate worker process. Run
  `IAF-Agent-Studio/kernel_worker.py` under the restricted kernel identity and
  set API/queue/scheduler processes to `AGENTOS_KERNEL_BACKEND=remote` with the
  same `AGENTOS_KERNEL_TOKEN_SECRET`.
- Redis uses authentication, TLS, and AOF persistence.
- Tenant files, SQLite databases, audit mirrors, and backups use
  enterprise-owned encrypted storage.

Use `agent_os/config.enterprise.env.example` as the baseline. Secret values must
come from the enterprise secret manager, not a checked-in env file.
Redis/session/queue startup logs intentionally omit connection URLs because
those URLs may contain credentials.

Configure ingress liveness against `/health/live` and readiness against
`/health/ready`. A strict API replica returns 503 readiness when Redis session
state is unavailable, preventing the load balancer from routing requests that
could create divergent conversation or approval state.

## Provisional service objectives

These are design targets, not validated customer commitments:

- API and WebSocket availability: 99.5% per calendar month.
- Chat p95 completion: under 15 seconds, excluding time waiting for human
  approval and external systems.
- Runtime coordination RPO: no more than 15 minutes.
- Tenant file/database RPO: no more than one hour.
- Service RTO: no more than four hours.

Promote these targets to contractual SLOs only after representative load,
failover, and restore drills provide measured evidence.

## Security rollout

1. Deploy strict identity, signed file URLs, queue keys, explicit CORS, and demo
   disabling in staging.
2. Set `ENTITLEMENTS_ENFORCEMENT_MODE=observe` for 48–72 hours of representative
   traffic.
3. Investigate every would-deny audit event. Add only the smallest registered
   resource required by a real job.
4. Run cron, queue, HITL resume, file rendering, and RL export tests.
5. Switch to `ENTITLEMENTS_ENFORCEMENT_MODE=enforce`.
6. Keep `EXTERNAL_ACCESS_UNKNOWN_MODE=deny`.

Rollback is limited to one controlled step at a time:

- Policy regression: change entitlements from `enforce` to `observe`.
- Signed-link UI regression: temporarily set `ALLOW_UNSIGNED_FILE_URLS=true`
  only behind enterprise ingress; revert after the client fix.
- Runtime-role regression: set `STUDIO_RUNTIME_ROLES=all` and
  `UVICORN_WORKERS=1` for one instance.
- Session dependency issue: restore Redis or roll back the application image and
  temporarily operate one API replica. Do not keep multiple replicas on
  process-local sessions.
- Scheduler issue: stop scheduler candidates; API remains available without
  scheduled execution.
- Queue issue: stop the queue role; queued data remains in the authoritative
  database for later processing.
- Postgres queue migration issue: stop queue workers, return
  `CC_QUEUE_STORAGE_BACKEND=sqlite`, keep `QUEUE_WORKER_REPLICAS=1`, and restore
  the pre-migration `command_center.db` backup.

Do not roll back `AUTH_ENABLED`, tenant binding, or external-access deny mode on
an internet- or enterprise-network-exposed deployment.

## Python sandbox provisioning

Agent Python should remain disabled unless a skill requires it. For Linux:

1. Create a non-login account such as `agentpro_python`.
2. Grant read access only to the Python runtime and approved shared reference
   files; grant write access only to tenant workspace/memory paths required by
   the product.
3. Deny access to env files, credential stores, SSH material, host sockets,
   container runtimes, and other tenant roots.
4. Add a sudoers rule that permits the Studio service account to run only the
   approved Python executable as `agentpro_python`, without a password. The
   runtime uses `sudo -n -u <user> -- <python> -I`.
5. Set `AGENT_PYTHON3_SANDBOX_USER=agentpro_python`, keep a bounded timeout and
   memory limit, and run allowed-code, blocked-import, timeout, filesystem, and
   secret non-disclosure tests.

Strict mode refuses to construct a Python-enabled kernel when the sandbox user
is absent. Child Python receives an isolated environment and does not receive
`CREDENTIAL_MASTER_KEY`.

For stronger production isolation, enable the remote kernel worker:

```bash
AGENTOS_KERNEL_BACKEND=remote
AGENTOS_KERNEL_URL=http://127.0.0.1:18081
AGENTOS_KERNEL_TOKEN_SECRET=<32+ chars>
AGENTOS_KERNEL_REQUIRE_REMOTE=true
```

In this mode the agent executor keeps the same shell surface, including `cat`,
`grep`, `ls`, `write_file`, and guarded `python3`, but the real `SafeKernel`
runs in the worker process. Keep the worker bound to a private interface or
service mesh endpoint and rotate `AGENTOS_KERNEL_TOKEN_SECRET` like any internal
service credential.

## Backup and restore drill

Back up Redis AOF/snapshots, tenant `shared/databases`, workstream and automation
YAML, knowledge/memory files, eval/golden-set assets, and audit mirrors. Encrypt
backups and test restoration into an isolated staging cell.

A passing restore drill must demonstrate:

1. Login and tenant authorization work.
2. Knowledge, workstreams, conversations, approvals, and export history are
   readable.
3. One scheduler leader reconciles jobs without duplicate execution.
4. The queue resumes work. On SQLite this means the single worker continues from
   `command_center.db`; on Postgres this means multiple workers report healthy
   heartbeats and no stale or duplicate terminal queue records.
5. Signed file rendering and evidence downloads work.
6. Recovery timestamps meet the provisional RPO/RTO targets.

Record measured restore duration, newest recovered timestamps, data gaps, and
all manual steps. A backup that has not passed this drill is not considered a
recoverable backup.

For the Postgres queue rollout, run the staging soak helper after starting one
worker and again after scaling to two or more workers:

```bash
python3 IAF-Agent-Studio/scripts/soak_command_center_queue.py \
  --api-url "$STAGING_AGENTPRO_URL" \
  --api-key "$QUEUE_INGEST_API_KEY" \
  --count 100
```

During the poll window, terminate one queue worker to verify lease reclaim. The
helper fails if items do not reach terminal states, duplicate completed
executions appear for a soak item, or stale claims remain.

### Automated offline verification

Create the checksum manifest after producing a backup artifact and before moving
it to long-term storage:

```bash
python3 scripts/verification/verify_enterprise_restore.py capture \
  --root /backup/agentpro-data \
  --tenant-id company \
  --redis-snapshot /backup/agentpro-data/redis/dump.rdb \
  --output /backup/agentpro-data/.agentpro-recovery-manifest.json
```

After restoring that artifact into an isolated directory, run:

```bash
python3 scripts/verification/verify_enterprise_restore.py verify \
  --root /restore-cell/agentpro-data \
  --tenant-id company \
  --report-dir /secure/recovery-reports
```

The verifier is read-only against the restore root and rejects any root that
equals, contains, or is contained by the active `DATA_ROOT`. It compares
capture-time checksums, parses YAML/JSON/JSONL, runs SQLite `PRAGMA quick_check`,
checks capture-time table inventories, classifies authoritative/rebuildable/
optional files, validates optional Redis snapshot checksum and freshness,
flags multiple completed Command Center executions for one queue item,
inventories operational definitions, and measures data freshness. Corrupt
`knowledge_index.db` files are warnings because they are rebuildable; corrupt
authoritative runtime databases fail the report. Add
`restore_started_at` to the capture manifest when the recovery workflow can
record that timestamp; otherwise service RTO is reported as `not_run`.

For the dashboard workflow, configure `RECOVERY_VERIFICATION_ROOT` to the
isolated restored data root and use **Dashboard V2 → Recovery Readiness**.
Admins can run the same verifier and inspect persisted reports without supplying
an arbitrary server path. Matching JSON and Markdown reports live under
`tenants/<tenant>/shared/databases/recovery_reports/`.

For optional non-mutating live probes, first start the restored cell through the
enterprise deployment orchestrator using separate API ports and a dedicated
recovery Redis host/port. Then set these values through the secret/config
manager:

```bash
RECOVERY_LIVE_BASE_URL=https://recovery-cell.example
RECOVERY_REDIS_URL=rediss://recovery-redis:6380/0
RECOVERY_LIVE_TOKEN=<short-lived-recovery-admin-token>
RECOVERY_LIVE_CONFIRMATION=isolated-recovery-cell
```

The `RECOVERY_REDIS_URL` above is shown without its ACL user and credential.
Inject the complete URL (including the recovery cell's ACL user/credential) from
the credential manager; never write a credentialed URL into config files or docs.

`RECOVERY_REDIS_URL` is compared with production `REDIS_URL`; reuse of the same
host/port is rejected even when usernames, passwords, or database indexes differ.
The dashboard Run action automatically adds live probes when configured. The
CLI equivalent appends `--run-live` to `verify`; all sensitive values come from
environment/secret injection rather than command-line arguments.

Offline verification does not prove login, leader election, queue exactly-once
resume, or signed file rendering. Live read probes cover API readiness,
authenticated tenant reads, conversations/workstreams, and signed downloads.
Scheduler status and queue metrics alone cannot prove leader uniqueness or
exactly-once execution, so those remain warnings until live drill evidence is
attached.

Use the drill harness against the isolated recovery cell to collect and submit
that proof:

```bash
python3 scripts/verification/run_recovery_drill.py \
  --api-url "$RECOVERY_LIVE_BASE_URL" \
  --token "$RECOVERY_LIVE_TOKEN" \
  --queue-api-key "$QUEUE_INGEST_API_KEY" \
  --queue-count 3 \
  --active-leaders 1 \
  --scheduler-candidates-observed 2 \
  --submit \
  --verify
```

The submitted bundle is sanitized before it is persisted under the tenant's
Recovery Readiness report store. When the bundle proves exactly one scheduler
leader, a drill-prefixed queue canary with no duplicate completed executions or
stale claims, signed-file rendering, and measured RTO/load/failover values, the
matching checks move from warning/not-run to pass/fail. A warning-only report is
evidence of partial readiness, not complete recovery certification.
