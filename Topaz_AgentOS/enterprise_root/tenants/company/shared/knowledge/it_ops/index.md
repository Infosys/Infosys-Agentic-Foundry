---
type: knowledge_index
title: IT Ops Knowledge Layer
description: Entry point for IT operations agent knowledge: incidents, Kubernetes operations, monitoring, change controls, and runbooks.
resource: /shared/knowledge/it_ops/index.md
tags: [it-ops, kubernetes, monitoring, incidents, knowledge-bundle]
timestamp: 2026-07-11T10:00:00Z
status: active
---

# IT Ops Knowledge Layer

Use this file as the first IT Operations knowledge entry point. It follows the
same Knowledge Bundle contract as other domains: manifest, index, log, maintainer
rules, and linked pages.

## Runbooks

- [Kubernetes incident triage](runbooks/kubernetes_incident_triage.md)

## Agent Rules

1. Start with the relevant runbook before issuing operational commands.
2. Prefer read-only diagnostics unless the user or governance hook approves a change.
3. Cite the source concept used in responses when practical, for example:
   "Source: IT Ops knowledge layer."
