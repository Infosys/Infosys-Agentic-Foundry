---
type: api
title: Finance API
description: Live mock finance API for invoice, vendor, purchase order, and payment release workflows.
resource: http://localhost:9092
tags: [finance, ap, api, invoices, payments, purchase-orders]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Finance API

Use this API when the task asks for an API-backed invoice lookup, external-style
integration, or payment release workflow.

## Base URL

```text
http://localhost:9092
```

## Authentication

Read calls require:

```text
X-API-Key: read_demo_key_abc123
```

Payment release requires an admin key and explicit human approval before calling
the endpoint.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health |
| `GET` | `/invoices` | List invoices |
| `GET` | `/invoices/<INVOICE_ID>` | Retrieve one invoice and linked purchase order |
| `POST` | `/payments/release` | Release payment after approval |

## Examples

```bash
curl -s -H "X-API-Key: read_demo_key_abc123" \
  http://localhost:9092/invoices/INV-3040
```

```bash
curl -s -X POST \
  -H "X-API-Key: <admin-key>" \
  -H "Content-Type: application/json" \
  http://localhost:9092/payments/release \
  -d '{"invoice_id":"INV-3040"}'
```

## Safety Rules

1. Read-only calls do not require human approval.
2. Payment release is destructive and must be gated by explicit approval.
3. Do not send JSON as form data; always use `Content-Type: application/json`.
