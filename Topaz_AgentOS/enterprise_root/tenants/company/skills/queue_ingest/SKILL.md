---
name: queue_ingest
version: "1.2"
description: "Manual/demo compatibility skill for posting a single work item to the Command Center queue ingest API. Cron-scheduled Queue mode jobs no longer execute this skill; the scheduler inserts trusted queue rows internally and uses the same content+time idempotency contract."
execution_mode: react
keywords:
  - "post to queue"
  - "ingest queue item"
  - "queue ingest"
  - "add to queue"
  - "schedule queue item"
  - "feed queue item"
tools:
  - shell
---

# Queue Ingest

You post a single item to the Command Center queue ingest API for manual/demo flows. The queue processor picks it up within a few seconds and routes it to the appropriate skill agent.

Cron-scheduled Queue mode jobs do not execute this skill. The scheduler parses the same comma-delimited task contract and inserts the queue row internally with `source="cron"`, `entity_id=<target skill>`, a fresh trace ID, and platform-computed idempotency. This avoids shell/curl dependencies and keeps scheduler behavior deterministic.

## Idempotency — the platform handles it

You do **not** compute `external_id`. The `/api/queue/ingest` endpoint synthesises a content fingerprint (`auto:webhook:<hash-of-payload>:<bucketed_timestamp>`) when the caller omits it. Two identical posts within the same time bucket collapse to one queue item. The bucket defaults to one hour; pass `bucket_seconds` in the body to tune it per call.

Rules:

- NEVER include `external_id` in the JSON body — let the platform compute it
- If the task prompt contains `BUCKET_SECONDS=<n>`, pass that value as `bucket_seconds` in the body
- Extract `skill`, `title`, `description`, `domain`, `priority` from the task prompt
- Cron task prompts must use comma-delimited fields, for example: `skill: ar_ops, priority: P1, title: Daily AR review, description: Review overdue receivables, domain: finance, BUCKET_SECONDS=86400`
- Two different cron jobs that produce different `title` / `description` payloads are treated as different work (the platform hashes the content), so they will not accidentally dedup each other

---

## Step 1 — Decide the bucket size

Read the task prompt. If it contains `BUCKET_SECONDS=<n>` (e.g. `BUCKET_SECONDS=600`), use that integer. Otherwise omit the field and the server uses its default (3600).

| Cron cadence | Recommended `BUCKET_SECONDS` |
|---|---|
| Every 5 minutes | 300 |
| Every 15 minutes | 900 |
| Every hour | 3600 (default — can omit) |
| Daily | 86400 |

## Step 2 — POST to queue ingest for manual/demo use

Compose the JSON body **without** `external_id`. Include `bucket_seconds` only if the prompt specified it.

```
shell(command="curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8082/api/queue/ingest -H 'Content-Type: application/json' -d '{\"title\": \"<TITLE>\", \"description\": \"<DESCRIPTION>\", \"domain\": \"<DOMAIN>\", \"entity_id\": \"<SKILL_NAME>\", \"priority\": \"<PRIORITY>\", \"tenant_id\": \"company\", \"bucket_seconds\": <BUCKET_SECONDS>}'")
```

If `BUCKET_SECONDS` is not in the prompt, drop the field entirely:

```
shell(command="curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8082/api/queue/ingest -H 'Content-Type: application/json' -d '{\"title\": \"<TITLE>\", \"description\": \"<DESCRIPTION>\", \"domain\": \"<DOMAIN>\", \"entity_id\": \"<SKILL_NAME>\", \"priority\": \"<PRIORITY>\", \"tenant_id\": \"company\"}'")
```

Fill in from the task:

| Placeholder | Where it comes from |
|---|---|
| `<TITLE>` | short title for the queue item (must reflect the work — title is part of the dedup fingerprint) |
| `<DESCRIPTION>` | full task prompt the queue processor will run |
| `<DOMAIN>` | `itops`, `operations`, `general`, etc. |
| `<SKILL_NAME>` | skill to route to, e.g. `ccdops`, `itops_rca`, `general` |
| `<PRIORITY>` | `P1`, `P2`, or `P3` |
| `<BUCKET_SECONDS>` | from the prompt; omit if not provided |

## Step 3 — Report

- **HTTP 201** → "Item posted to queue. Queue processor will pick it up within a few seconds."

  Note: the API always returns 201 even when the row was silently deduped — that's expected and correct behaviour. The dedup is reflected in the database, not the response code.

- **HTTP 4xx / 5xx** → Report the status code. Do not retry — the next cron firing will try again automatically.

## Example

Cron task prompt:
```
skill: general, priority: P3, title: payload A, description: hello A, domain: general, BUCKET_SECONDS=600
```

What you POST:
```json
{
  "title": "payload A",
  "description": "hello A",
  "domain": "general",
  "entity_id": "general",
  "priority": "P3",
  "tenant_id": "company",
  "bucket_seconds": 600
}
```

What the server stores (you never see this):
- `external_id = auto:webhook:<hash-of-title+desc+domain+priority+tenant>:<10-min-bucket>`

Two cron firings of this exact prompt within the same 10-minute window produce the same `external_id` and the second is silently deduped. A different cron job with `title: payload B` produces a different content hash, so it lands as a fresh row even in the same window.
