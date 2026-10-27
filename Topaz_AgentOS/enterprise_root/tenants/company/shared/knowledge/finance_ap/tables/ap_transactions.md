---
type: table
title: AP Transactions
description: Invoice, payment, credit note, and correction transactions for Accounts Payable.
resource: /shared/databases/ap_ops.db#ap_transactions
tags: [finance, ap, table, invoices, payments, transactions]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# AP Transactions

One row per AP transaction. This is the first table to query for pending
invoices, overdue invoices, payment status, and invoice aging.

## Columns

| Column | Meaning |
|---|---|
| `transaction_id` | Internal transaction identifier |
| `vendor_name` | Vendor display name |
| `vendor_id` | Vendor key, joins to [Vendors](vendors.md) |
| `invoice_number` | Supplier invoice number |
| `amount` | Transaction amount |
| `currency` | Currency code |
| `transaction_type` | `invoice`, `payment`, `credit_note`, or `correction` |
| `status` | `open`, `posted`, `cleared`, or `pending_correction` |
| `posting_date` | Posting date |
| `due_date` | Due date |
| `gl_account` | GL account |
| `cost_center` | Cost center |
| `description` | Free-text transaction description |
| `po_number` | Purchase order number, joins to [Purchase orders](purchase_orders.md) |
| `requires_correction` | `1` when a correction is required |
| `correction_reason` | Reason for correction |
| `corrected_by` | User or process that corrected the transaction |
| `corrected_date` | Correction date |

## Common Query

```sql
SELECT transaction_id, vendor_name, invoice_number, amount, currency, status, due_date
FROM ap_transactions
WHERE status = 'open'
ORDER BY due_date;
```

## Related Concepts

- [Vendors](vendors.md)
- [Purchase orders](purchase_orders.md)
- [Find pending invoices](../runbooks/pending_invoices.md)
