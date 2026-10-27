---
type: log
title: Finance AP Knowledge Layer Change Log
description: Chronological changes for the Finance AP OKF-style knowledge bundle.
resource: /shared/knowledge/finance_ap/log.md
tags: [finance, ap, knowledge-layer, changelog]
timestamp: 2026-07-05T11:01:00Z
status: active
---

# Finance AP Knowledge Layer Change Log

## 2026-07-05

- Created first OKF-style AP knowledge bundle for customer demo use.
- Added root index, AP database, Finance API, core table concepts, open invoice
  metric, three-way match policy, and two runbooks.
- Wired intended runtime entry point:
  `/shared/knowledge/finance_ap/index.md`.

## 2026-07-11

- Added generic Knowledge Bundle manifest and maintainer rules.
- Updated index to expose manifest, maintainer rules, and changelog as bundle contract files.

- 2026-07-11: Added confirmed knowledge `k_20260711_8cb32b807a75` to `policies/three_way_match.md` - TEST: Pending invoices filter status IN (open, overdue) in ap_ops.db
