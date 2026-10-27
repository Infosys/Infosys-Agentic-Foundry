---
type: knowledge_index
title: Finance AP Knowledge Layer
description: "Entry point for Accounts Payable agent knowledge: live data sources, schemas, APIs, metrics, policies, and runbooks."
resource: /shared/knowledge/finance_ap/index.md
tags: [finance, accounts-payable, ap, procure-to-pay, knowledge-layer, okf]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Finance AP Knowledge Layer

Use this file as the first AP knowledge entry point. It is an OKF-style bundle:
plain Markdown files with YAML frontmatter, linked concepts, and agent-readable
runbooks.

## Bundle Contract

- [Bundle manifest](manifest.yaml) - convention-discovered bundle metadata,
  skill/tag matching, and write targets.
- [Maintainer rules](MAINTAINER.md) - rules for approved bundle page updates.
- [Change log](log.md) - append-only bundle maintenance history.

## Live Sources

- [AP operations database](databases/ap_ops.md) - primary live AP data for the
  `invoice_processing_ap` skill.
- [World-model graph](databases/graph.md) - entities + relationships; query with
  `run_sql_query(database="graph", ...)` for multi-hop / "what's exposed" questions.
- [Finance API](apis/finance_api.md) - live mock API for invoice/vendor/PO/payment
  lookups and approved payment release flows.

## Core Tables

- [AP transactions](tables/ap_transactions.md)
- [Vendors](tables/vendors.md)
- [Purchase orders](tables/purchase_orders.md)
- [Goods receipts](tables/goods_receipts.md)

## Metrics

- [Open invoice count](metrics/open_invoice_count.md)

## Policies

- [Three-way match and approval routing](policies/three_way_match.md)

## Runbooks

- [Find pending invoices](runbooks/pending_invoices.md)
- [Investigate invoice status](runbooks/invoice_status.md)

## Agent Rules

1. Use `run_sql_query` for `/shared/databases/ap_ops.db`; do not write SQL changes.
2. Use Finance API for external-style invoice lookups or actions that must go
   through an API contract.
3. For destructive payment actions, require explicit human approval before the
   API call.
4. Interpret "pending invoices" in the business sense: invoices/payables waiting
   for action. In `ap_transactions`, count `status IN ('open', 'overdue')` when
   the database has a separate `overdue` status. Do **not** treat pending as
   `pending_correction` unless the user explicitly asks for correction queue
   items.
5. Cite the source concept used in the response when practical, for example:
   "Source: AP operations database knowledge layer."
