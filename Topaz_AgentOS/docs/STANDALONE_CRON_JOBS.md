# Standalone Cron Jobs

Standalone cron jobs are scheduled jobs that are **not** attached to a
workstream. Their source of truth lives under `enterprise_root` so tenant
business logic can move independently from the AgentPro solution code.

## Storage Layout

```text
enterprise_root/
  tenants/
    <tenant_id>/
      scheduler/
        jobs/
          daily_ar_aging.yaml
          weekly_vendor_check.yaml
```

Redis remains the active scheduler runtime. On server startup, Studio reconciles
the YAML files above into Redis, the same way it reconciles `cron_schedule` from
workstream YAML. If Redis is reset, standalone cron definitions are recreated
from `enterprise_root`.

## YAML Format

```yaml
id: daily_ar_aging
name: daily_ar_aging
skill_name: ar_aging_report
task: "Generate AR aging report"
cron: "0 8 * * 1-5"
timezone: UTC
tenant_id: company
agent_id: enterprise_agent
user_id: service:cron
enabled: true
max_runtime_seconds: 300
description: "Run AR aging report every weekday morning"
params:
  customer_segment: all
tags:
  - finance
  - ar
```

Required fields: `skill_name`, `cron`, and `user_id`. `id` and `name` default to
the filename stem when omitted. `payload` is accepted as an alias for `params`.

To run a no-LLM Deterministic Automation from standalone cron, set
`skill_name: automation` and put the automation id in `task`:

```yaml
id: nightly_close
name: nightly_close
skill_name: automation
task: nightly_close
cron: "0 2 * * *"
user_id: service:cron
```

To run a Private Learning Loop eval suite continuously, set
`skill_name: eval_suite` and put the suite id in `task`:

```yaml
id: nightly_invoice_eval
name: nightly_invoice_eval
skill_name: eval_suite
task: invoice_suite
cron: "0 3 * * *"
user_id: service:cron
params:
  sample: nightly
```

## Startup Reconciliation

At startup, after the Redis-backed cron scheduler starts:

1. Workstream crons are reconciled from `workstreams/*.yaml`.
2. Standalone crons are reconciled from `scheduler/jobs/*.yaml`.
3. Redis stores active runtime state such as due-time indexes, locks, run
   history, and retry/failure counters.

In the dedicated-enterprise topology, reconciliation runs only in
`STUDIO_RUNTIME_ROLES=scheduler` processes. Multiple scheduler candidates are
safe: a Redis lease selects one leader, the owner renews the lease, and standby
candidates retry after `SCHEDULER_LEADER_RETRY_SECONDS`. API and queue roles may
initialize their own durable stores, but they do not start cron services. Use
`IAF-Agent-Studio/scheduler_worker.py` as the
standalone entry point.

Scheduler executions construct agents through the AgentOS kernel runtime
factory. With `AGENTOS_KERNEL_BACKEND=remote`, scheduled shell/file/Python work
executes in the signed kernel worker instead of the scheduler process while
preserving the same `SafeKernel` command semantics.

Scheduler-only processes do not require `USE_REDIS_SESSIONS`; that setting and
the `/health/ready` session check apply to the API role. Scheduler Redis remains
required separately for leader election and active cron state.

The reconciler creates or updates YAML-backed jobs. It does **not** delete
Redis-only jobs automatically; that avoids losing manually-created jobs before
they are exported to YAML.

## Export Existing Redis-Only Cron Jobs

Before treating `enterprise_root` as the only portable source of cron
definitions, export existing standalone Redis jobs:

```bash
cd IAF_AgentOS_Harness_latest
python3 IAF-Agent-Studio/scripts/export_standalone_crons.py
```

Use `--overwrite` to replace existing YAML files:

```bash
python3 IAF-Agent-Studio/scripts/export_standalone_crons.py --overwrite
```

Workstream jobs (`ws_*` or jobs tagged `workstream`) are skipped because their
source is already the corresponding workstream YAML.

## Migration / Backup Rule

For a tenant migration, copy `enterprise_root/tenants/<tenant_id>/scheduler/jobs/`
with the rest of the tenant root. Redis does not need to be copied for cron
definitions; it can be rebuilt by startup reconciliation.

The Recovery Readiness verifier parses restored scheduler YAML and reports the
definition count. This offline check proves the portable definitions are
readable; the separate live recovery drill must still prove that one scheduler
leader reconciles them without duplicate execution.
