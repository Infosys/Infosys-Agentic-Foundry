---
type: policy
title: Three-Way Match and Approval Routing
description: AP rule for validating invoice, purchase order, and goods receipt before recommending payment.
resource: /shared/knowledge/finance_ap/policies/three_way_match.md
tags: [finance, ap, policy, three-way-match, approvals, controls]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Three-Way Match and Approval Routing

## Rule

An invoice passes the standard AP match when:

1. Vendor exists and is not blocked.
2. Purchase order exists and vendor matches.
3. Goods receipt exists and is confirmed.
4. Invoice amount is within 2 percent of PO amount.

## Variance Calculation

```text
variance_pct = abs(invoice_amount - po_amount) / po_amount * 100
```

## Match Outcomes

| Result | Condition | Agent action |
|---|---|---|
| `MATCH` | Invoice amount <= PO amount and GR confirmed | Recommend processing |
| `MATCH_WITHIN_TOLERANCE` | Variance <= 2 percent | Recommend review/approval routing |
| `MISMATCH` | Variance > 2 percent, missing PO, missing GR, blocked vendor | Do not recommend payment; explain blocker |

## Agent Response Requirements

When the user asks to process or validate an invoice:

1. Query [AP transactions](../tables/ap_transactions.md) for invoice details.
2. Query [Vendors](../tables/vendors.md) for vendor status.
3. Query [Purchase orders](../tables/purchase_orders.md).
4. Query [Goods receipts](../tables/goods_receipts.md).
5. Return match result, variance, blocker, and recommended next action.

Payment release remains destructive and needs explicit human approval.

---

## Confirmed Knowledge
<!-- auto-generated – do not edit this section manually -->

### [2026-07-11] TEST: Pending invoices filter status IN (open, overdue) in ap_ops.db
**Type**: rule | **Skill**: — | **ID**: k_20260711_8cb32b807a75
**Applies when**: —
> TEST: Pending invoices filter status IN (open, overdue) in ap_ops.db
