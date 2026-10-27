# Workstreams as Recurring Operations

## Security boundary

Workstream REST routes bind tenant/user scope from the authenticated principal
and require `workstream` read/write/use/delete entitlements. The live
`/ws/workstreams/{name}` connection carries the access token in the query
string, validates tenant membership before acceptance, and requires read access
to that workstream. Service cron/queue principals are limited to explicitly
listed skills, tools, and external resources.

## Purpose

This note summarizes how to position **Workstreams** relative to **cron jobs** and the **queue monitor**, and how to use Workstreams for recurring operational use cases such as server-health monitoring.

The key idea:

```text
Cron / Queue Monitor = scheduling and technical execution layer
Workstream = business / operations control plane
```

Cron can still wake up the process periodically, but the Workstream becomes the richer place where teams see backlog, item state, evidence, approvals, results, and next actions.

---

## Executive Message

For recurring agentic operations, we should move from a “cron job queue monitor” mental model to a **Workstream model**.

The queue monitor answers:

> Did the scheduled job run?

The Workstream answers:

> What business or operational work is open, what did agents resolve, what is blocked, who needs to decide, what evidence exists, and what should happen next?

This makes Workstreams more useful for business users, operations teams, and demos. Queue monitor remains valuable for platform/admin diagnostics, but Workstreams should be the user-facing operating layer.

---

## Queue Monitor vs Workstream

| Capability | Cron / Queue Monitor | Workstream |
|---|---|---|
| Scheduled execution | Yes | Yes, triggered by cron |
| Job status | Yes | Yes, plus item-level lifecycle |
| Retry visibility | Yes | Yes, with per-item context |
| Logs / traces | Basic | Trace, evidence, result summary, execution history |
| Business backlog | No | Yes |
| Item-level state | Limited | `pending`, `in_progress`, `awaiting_human`, `done`, `failed` |
| Human approval | Usually external | Built into item lifecycle |
| Run Now / Pause / Resume | Sometimes | First-class |
| Business metrics | Limited | Native pattern via workstream summaries and business metrics |
| Copilot explanation | No | Yes, page/workstream/item context |
| Best user | Platform admin | Business user + operations user |

Recommended positioning:

```text
Use cron for: when to run
Use queue monitor for: technical diagnosis
Use workstream for: operational control and business visibility
```

---

## Why Workstreams Are Richer

Workstreams provide:

- A recurring process backlog, not just a job log.
- Per-item status and lifecycle.
- Evidence and trace links per run.
- HITL approval state.
- Result summary and last execution details.
- Run controls: Run Now, Pause, Resume, Retry.
- Business metrics and North Star outcome cards.
- Copilot-assisted explanation of what is blocked and what to do next.

This is why Workstreams are better for recurring business/ops workflows where the question is not merely “did the job execute?” but “what work remains and what is the operational impact?”

---

## Example Use Case: Server Monitoring

Goal:

> Periodically monitor servers/services, scan logs and health signals, detect issues, summarize evidence, and escalate remediation when needed.

Model it like this:

```text
Workstream = Server Health Monitoring
Items = servers / services / log sources
Cron = periodic trigger every 5 minutes
Skill = diagnostic agent for one monitored item
```

Example items:

| Workstream Item | Meaning |
|---|---|
| `api-server-01` | Check app logs, health endpoint, 5xx errors, latency, memory pressure |
| `worker-queue` | Check queue depth, failed jobs, stuck workers |
| `redis-cache` | Check Redis connectivity, memory, slow logs, evictions |
| `postgres-db` | Check connection count, locks, slow queries |
| `nginx-edge` | Check 5xx spikes, upstream failures |

Each cron tick runs the workstream. The workstream processes due items and records the current operational state.

---

## Runtime Flow

```text
Cron fires every 5 minutes
→ calls workstream run/tick
→ workstream selects eligible items
→ server_health_monitor skill checks each server/service
→ agent records evidence, trace, status, severity, and recommendation
→ high severity can trigger HITL approval
→ workstream UI shows current server health and open issues
```

The queue monitor can still show the technical job execution, but the Workstream UI shows the operational outcome.

---

## Workstream Configuration Example

```yaml
name: server_health_monitoring
display_name: Server Health Monitoring
owner: platform-ops
description: Periodically monitor server health, logs, errors, latency, and queue pressure.
skill: server_health_monitor
status: active

priority_strategy: highest_amount
batch_size: 5
parallelism: 3
max_attempts_per_item: 2

items:
  - id: api-server-01
    description: >
      Check API server 01 for the last 10 minutes. Inspect health endpoint,
      recent logs, 5xx errors, latency, memory pressure, and queue failures.
    status: pending
    priority_metric: 90
    case_summary:
      case_type: server_health_check
      title: API Server 01
      primary_entity: api-server-01
      category: runtime_monitoring
      impact_label: Service health
      risk_level: medium
      recommended_action: Diagnose and recommend remediation if unhealthy.
    acceptance_criteria:
      - Health endpoint checked
      - Recent logs scanned
      - Error patterns summarized
      - Severity assigned
      - Recommended action captured

  - id: redis-cache
    description: >
      Check Redis health, connectivity, memory, slow logs, evictions, and queue impact.
    status: pending
    priority_metric: 80
    case_summary:
      case_type: server_health_check
      title: Redis Cache
      primary_entity: redis-cache
      category: runtime_monitoring
      impact_label: Platform dependency health
      risk_level: high
    acceptance_criteria:
      - Connectivity checked
      - Memory and evictions reviewed
      - Slow logs reviewed
      - Severity assigned
      - Recommended action captured

escalation:
  - when: severity >= high
    action: request_human_approval
    approver_role: platform_ops
    reason: High-severity production remediation requires operator approval.

business_metrics:
  - id: unhealthy_services
    label: Unhealthy Services
    source: items
    formula: count(status in ["failed", "awaiting_human"])

  - id: checks_completed
    label: Checks Completed
    source: items
    formula: count(status == "done")

  - id: pending_approvals
    label: Pending Operator Approvals
    source: items
    formula: count(status == "awaiting_human")
```

---

## Cron Configuration Example

```yaml
name: server_health_monitoring_tick
display_name: Server health monitoring every 5 minutes
enabled: true
schedule: "*/5 * * * *"
timezone: "Asia/Kolkata"

target:
  type: workstream
  workstream_name: server_health_monitoring
  action: run_now

run:
  batch_size: 5
  parallelism: 3
  reset_done_items: true
  reset_done_after_minutes: 5

failure_policy:
  max_retries: 2
  retry_delay_seconds: 60
  on_failure: keep_failed_for_review

audit:
  trace: true
  evidence: true
  notify_on_high_severity: true
```

---

## Skill Contract Example

The Workstream points to a skill such as `server_health_monitor`.

```yaml
name: server_health_monitor
description: Diagnose one monitored server/service item and return health, evidence, severity, and next action.
execution_mode: react
tools:
  - shell
  - run_sql_query
  - http_request
  - request_human_approval
```

Expected output per item:

```yaml
status: healthy | degraded | critical
severity: low | medium | high | critical
evidence:
  - health endpoint status
  - log snippets
  - error counts
  - latency / memory observations
recommended_action: Restart worker queue after approval
requires_human_approval: true
```

---

## Item Lifecycle for Monitoring

| Status | Meaning |
|---|---|
| `pending` | Due for next health check |
| `in_progress` | Agent is checking logs/metrics |
| `done` | Healthy for this cycle |
| `failed` | Check failed or issue detected |
| `awaiting_human` | Needs operator approval/action |
| `paused` | Server/service temporarily excluded |

For monitoring, the item is not just a one-time ticket. It represents a recurring monitored entity. Each run produces a new trace/result and updates the current health state.

---

## How To Explain This To The Team

Use this framing:

> We are not removing cron. We are moving cron behind Workstreams. Cron still wakes up the process, but Workstreams give us the operational control plane: backlog, state, evidence, approvals, metrics, and Copilot explanations.

And:

> Queue monitor is for platform operators. Workstreams are for business and operations teams who need to know what is happening, what is blocked, why it matters, and what to do next.

---

## Recommended Adoption Pattern

1. Keep existing cron jobs for technical scheduling.
2. Wrap recurring operational jobs as Workstreams.
3. Represent each monitored entity or business case as a Workstream item.
4. Use cron to trigger Workstream `run_now` or scheduled ticks.
5. Store item-level evidence, traces, HITL state, and result summaries.
6. Use Workstream UI for demos and day-to-day operations.
7. Use Queue Monitor only for backend troubleshooting.

This gives the team the reliability of cron plus the richer operating experience of Workstreams.
