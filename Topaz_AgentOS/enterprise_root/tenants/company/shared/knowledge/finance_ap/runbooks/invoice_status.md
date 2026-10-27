---
type: runbook
title: Investigate Invoice Status
description: Agent procedure for answering invoice-specific status and payment questions.
resource: /shared/knowledge/finance_ap/runbooks/invoice_status.md
tags: [finance, ap, runbook, invoice-status, payment-status]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Investigate Invoice Status

Use this runbook when the user provides an invoice number, transaction id, vendor,
or PO number and asks for status.

## Steps

1. Search [AP transactions](../tables/ap_transactions.md) by invoice number,
   transaction id, vendor, or PO number.
2. Join to [Vendors](../tables/vendors.md) to check vendor status.
3. If a PO exists, query [Purchase orders](../tables/purchase_orders.md).
4. If a PO exists, query [Goods receipts](../tables/goods_receipts.md).
5. If the question asks whether it can be paid, apply
   [Three-way match and approval routing](../policies/three_way_match.md).

## SQL: Invoice Lookup

```sql
SELECT t.*, v.vendor_status, v.payment_terms
FROM ap_transactions t
LEFT JOIN vendors v ON t.vendor_id = v.vendor_id
WHERE t.invoice_number LIKE '%{search}%'
   OR t.transaction_id LIKE '%{search}%'
   OR t.vendor_name LIKE '%{search}%'
   OR t.po_number LIKE '%{search}%'
ORDER BY t.posting_date DESC;
```

## Response Shape

Include:

- Invoice/transaction id.
- Vendor and vendor status.
- Amount and currency.
- Posting date, due date, and current status.
- PO/GR match status when relevant.
- Recommended next action.
