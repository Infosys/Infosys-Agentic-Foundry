---
type: maintainer_rules
title: Finance AP Knowledge Bundle Maintainer Rules
description: Rules for maintaining the Finance AP knowledge bundle.
resource: /shared/knowledge/finance_ap/MAINTAINER.md
tags: [finance, ap, knowledge-bundle, maintainer]
timestamp: 2026-07-11T10:00:00Z
status: active
---

# Finance AP Knowledge Bundle Maintainer Rules

Use these rules when maintaining `/shared/knowledge/finance_ap/`.

## Routing

- Invoice lookup, pending invoice, vendor, PO, GR, payment, and three-way-match learnings belong in this bundle.
- Rules and controls go under `policies/`.
- Step-by-step operational procedures go under `runbooks/`.
- Table and database schema facts go under `tables/` or `databases/`.
- API facts go under `apis/`.
- Metrics and KPI definitions go under `metrics/`.
- General facts that do not fit a stronger category go under `notes/`.

## Write Rules

1. Prefer additive sections under `## Confirmed Knowledge`.
2. Create a new page only when no existing page clearly fits.
3. If a new page is created, add it to `index.md`.
4. Append one dated line to `log.md` for every maintained page change.
5. Cite provenance: source query, database/API, file path, or approval id.
6. Do not change `Enterprise_Context.md` from this bundle maintainer flow.

## AP Interpretation Rules

- Treat pending AP invoices as `status IN ('open', 'overdue')` unless the user explicitly asks for a correction queue.
- Use `/shared/databases/ap_ops.db` for AP transaction examples and `/shared/knowledge/finance_ap/databases/ap_ops.md` for schema guidance.
- Use `policies/three_way_match.md` for invoice, PO, and goods-receipt matching decisions.
