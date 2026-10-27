---
type: runbook
title: Kubernetes Incident Triage
description: Generic read-first procedure for Kubernetes incident investigation.
resource: /shared/knowledge/it_ops/runbooks/kubernetes_incident_triage.md
tags: [it-ops, kubernetes, incident, runbook, triage]
timestamp: 2026-07-11T10:00:00Z
status: active
---

# Kubernetes Incident Triage

Use this runbook for questions about pod failures, deployment health, cluster
alerts, node pressure, ingress issues, or service availability.

## Steps

1. Identify the affected cluster, namespace, workload, and time window.
2. Gather read-only evidence first: status, events, logs, recent changes, and alerts.
3. Classify likely cause: resource pressure, image/config error, dependency outage, network/ingress, storage, or node issue.
4. Recommend the least invasive next action.
5. Require explicit approval before write operations such as restart, scale, rollback, or config change.

## Response Shape

Include:

- Impact summary.
- Evidence checked.
- Likely cause.
- Next safe diagnostic step.
- Any action that requires approval.
