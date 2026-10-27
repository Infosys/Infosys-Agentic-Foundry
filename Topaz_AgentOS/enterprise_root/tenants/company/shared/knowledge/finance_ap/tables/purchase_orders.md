---
type: table
title: Purchase Orders
description: Purchase order header data used for PO lookup and three-way invoice matching.
resource: /shared/databases/ap_ops.db#purchase_orders
tags: [finance, ap, table, purchase-orders, three-way-match]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Purchase Orders

Purchase order table used to validate invoice vendor, amount, PO status, and
delivery expectation.

## Columns

| Column | Meaning |
|---|---|
| `po_number` | Purchase order number |
| `vendor_id` | Vendor key |
| `vendor_name` | Vendor display name |
| `po_date` | PO creation date |
| `delivery_date` | Expected or actual delivery date |
| `total_amount` | PO amount |
| `currency` | Currency code |
| `status` | `open`, `partially_received`, `fully_received`, `closed`, or `cancelled` |
| `description` | PO description |
| `cost_center` | Cost center |
| `gl_account` | GL account |
| `created_by` | PO creator |
| `approved_by` | Approver |

## Common Query

```sql
SELECT po_number, vendor_id, vendor_name, total_amount, currency, status, delivery_date
FROM purchase_orders
WHERE po_number = '{po_number}';
```

## Related Concepts

- [Goods receipts](goods_receipts.md)
- [Three-way match and approval routing](../policies/three_way_match.md)
