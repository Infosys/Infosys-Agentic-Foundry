# Scheduler + Async Job Queue

AgentOS runs skills three ways: **interactive** (chat), **scheduled**
(cron), and **queued** (async / batch).

## Cron Scheduler — Redis-backed

Schedule any skill to run on a cron expression. Workers across multiple
nodes coordinate via Redis (distributed-lock safe — only one worker
picks up each fire).

```yaml
# Example schedule (registered via /api/cron)
name: nightly_ar_close
skill: fa_ar_orchestrator
cron: "0 2 * * *"          # every day at 02:00
tenant: company
user_id: scheduled@iaf.local
input: "Close AR for previous business day"
```

Visible in the dashboard at `/dashboard/v2`. Manual trigger and pause
supported. Failed runs surface in the same trace store.

## Command Centre Queue (cc_queue)

Long-running or HITL-paused skills live in the cc_queue. Use it for:

- Multi-hour deal closes
- Workflows paused on approval gates
- Webhook-triggered work (PagerDuty/ServiceNow incidents)

The queue persists in `IAF-Agent-Studio/cc_queue.db` (SQLite) and is
visible at `/dashboard/v2` → Queue Monitor.

## Webhook ingestion

```
POST /api/queue/ingest
Authorization: ApiKey <tenant_webhook_token>
{
  "skill":  "incident_responder",
  "input":  "P1 - app server cluster down",
  "source": "pagerduty",
  "event_id": "PD-12345"
}
```

External systems post events → queue picks them up → assigned skill
runs in the background → results flow back into the trace store.

## How long-running skills stay alive

- Workflow checkpoints persist to disk between approval pauses
- Engine restores state when the approval lands → resumes from the next
  step (not from the beginning)
- Failures fire `on_failure` hook for compensation / cleanup

Read more: IAF-Agent-Studio/docs/CRON_SCHEDULER.md · IAF-Agent-Studio/docs/cc_queue.md
