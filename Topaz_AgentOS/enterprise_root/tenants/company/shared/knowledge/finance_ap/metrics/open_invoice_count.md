---
type: metric
title: Open Invoice Count
description: Count of AP invoice transactions currently open and awaiting payment, correction, or review.
resource: /shared/databases/ap_ops.db#ap_transactions.status
tags: [finance, ap, metric, invoices, open-invoices]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Open Invoice Count

## Definition

Number of rows in [AP transactions](../tables/ap_transactions.md) where:

```sql
transaction_type = 'invoice' AND status = 'open'
```

For broad pending invoice questions, count all `status = 'open'` AP transaction
rows unless the user explicitly asks for invoice-only rows.

## Formula

```sql
SELECT COUNT(*) AS open_invoice_count
FROM ap_transactions
WHERE status = 'open';
```

## Business Meaning

A high open invoice count can indicate payment backlog, unresolved matching
exceptions, vendor master issues, or close exposure.

## Related Runbook

- [Find pending invoices](../runbooks/pending_invoices.md)
