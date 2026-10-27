---
type: runbook
title: Find Pending Invoices
description: Agent procedure for answering pending/open invoice questions using the AP operations database.
resource: /shared/knowledge/finance_ap/runbooks/pending_invoices.md
tags: [finance, ap, runbook, pending-invoices, open-invoices]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Find Pending Invoices

Use this runbook for questions like:

- "How many pending invoices are present?"
- "Show open invoices."
- "Which vendors have overdue AP invoices?"

## Steps

1. Read [AP operations database](../databases/ap_ops.md).
2. Query [AP transactions](../tables/ap_transactions.md) where
   `status IN ('open', 'overdue')`. In this demo database, `overdue` can appear
   as its own status and still means pending/unpaid.
3. Group by vendor if the user asks for a summary.
4. Flag overdue invoices where `status = 'overdue'` or `due_date < date('now')`.
5. Return count, total amount, top vendors, and earliest due dates.

Do **not** use `pending_correction` for generic "pending invoices" questions.
Only use `pending_correction` when the user explicitly asks for correction queue
items or invoices pending correction.

## SQL: Count Pending Invoices

```sql
SELECT COUNT(*) AS pending_invoice_count
FROM ap_transactions
WHERE status IN ('open', 'overdue');
```

## SQL: Vendor Summary

```sql
SELECT vendor_name, COUNT(*) AS count, SUM(amount) AS total, MIN(due_date) AS earliest_due
FROM ap_transactions
WHERE status IN ('open', 'overdue')
GROUP BY vendor_name
ORDER BY total DESC;
```

## Response Shape

Include:

- Total pending count.
- Total open amount.
- Vendor breakdown if useful.
- Any overdue risk.
- Source: `/shared/databases/ap_ops.db`.
