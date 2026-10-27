---
type: table
title: Goods Receipts
description: Goods receipt data used to confirm receipt before invoice matching and payment recommendation.
resource: /shared/databases/ap_ops.db#goods_receipts
tags: [finance, ap, table, goods-receipts, three-way-match]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Goods Receipts

Goods receipt table used in three-way matching. A confirmed receipt supports
invoice processing; partial or rejected receipts require explanation and review.

## Columns

| Column | Meaning |
|---|---|
| `gr_number` | Goods receipt number |
| `po_number` | Purchase order number |
| `vendor_id` | Vendor key |
| `receipt_date` | Receipt date |
| `quantity_ordered` | Ordered quantity |
| `quantity_received` | Received quantity |
| `unit_price` | Unit price |
| `total_amount` | Receipt value |
| `status` | `confirmed`, `partial`, or `rejected` |
| `received_by` | Receiver |
| `notes` | Receipt notes |

## Common Query

```sql
SELECT gr_number, po_number, receipt_date, quantity_ordered, quantity_received, total_amount, status
FROM goods_receipts
WHERE po_number = '{po_number}';
```

## Related Concepts

- [Purchase orders](purchase_orders.md)
- [Three-way match and approval routing](../policies/three_way_match.md)
