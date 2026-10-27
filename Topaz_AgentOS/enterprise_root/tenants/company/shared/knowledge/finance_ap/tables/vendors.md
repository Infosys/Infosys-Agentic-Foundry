---
type: table
title: Vendors
description: Vendor master data used to validate invoice status, payment terms, blocks, and credit exposure.
resource: /shared/databases/ap_ops.db#vendors
tags: [finance, ap, table, vendors, supplier-master]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Vendors

Vendor master table for AP investigations.

## Columns

| Column | Meaning |
|---|---|
| `vendor_id` | Vendor key |
| `vendor_name` | Vendor display name |
| `vendor_status` | `active`, `blocked`, `flagged`, or `new` |
| `payment_terms` | Terms used to calculate expected due date |
| `credit_limit` | Approved exposure threshold |
| `ytd_spend` | Year-to-date spend |

## Common Query

```sql
SELECT vendor_id, vendor_name, vendor_status, payment_terms, credit_limit, ytd_spend
FROM vendors
WHERE vendor_name LIKE '%{vendor_name}%';
```

## Agent Guidance

If `vendor_status = 'blocked'`, do not recommend payment release. Explain the
block and route for review.
