---
type: maintainer_rules
title: IT Ops Knowledge Bundle Maintainer Rules
description: Rules for maintaining the IT Ops knowledge bundle.
resource: /shared/knowledge/it_ops/MAINTAINER.md
tags: [it-ops, knowledge-bundle, maintainer]
timestamp: 2026-07-11T10:00:00Z
status: active
---

# IT Ops Knowledge Bundle Maintainer Rules

Use these rules when maintaining `/shared/knowledge/it_ops/`.

## Routing

- Incident response, Kubernetes operations, alerts, monitoring, change, and reliability learnings belong in this bundle.
- Diagnostic and remediation procedures go under `runbooks/`.
- Operational controls and approval policies go under `policies/`.
- Metrics and SLO definitions go under `metrics/`.
- General facts that do not fit a stronger category go under `notes/`.

## Write Rules

1. Prefer additive sections under `## Confirmed Knowledge`.
2. Create a new page only when no existing page clearly fits.
3. If a new page is created, add it to `index.md`.
4. Append one dated line to `log.md` for every maintained page change.
5. Cite provenance: source query, alert, trace, ticket, command output, or approval id.
6. Do not run or recommend destructive operational actions without human approval.
