---
name: K8s Escalation & Decision Rules
type: judgment
description: Escalation paths, auto-fix vs human approval gates, severity classification, and correlation logic
status: active
skills:
  - ccdops
---

# K8s Escalation & Decision Rules
_Last updated: 2026-04-20_

Decision rules for the ccdops agent: when to auto-fix, when to escalate,
how to classify severity, and approval requirements.

---

## Severity Classification

| Severity | Criteria | Examples |
|----------|----------|---------|
| **P1 — Critical** | Service down, multiple users/namespaces impacted, data loss risk | Node NotReady, CoreDNS down, API server degraded, multiple pods CrashLoopBackOff |
| **P2 — High** | Single service degraded, workaround exists, no data loss | Pod OOMKilled (single), ingress 5xx intermittent, single pod CrashLoopBackOff |
| **P3 — Medium** | Non-critical issue, no immediate user impact | ImagePullBackOff, pod Pending, config drift, resource warning |
| **P4 — Low** | Cosmetic, informational, scheduled | Unused resources, capacity planning, audit findings |

### Severity Upgrade Triggers
- P3 → P2: Issue persists >1 hour without resolution
- P2 → P1: Multiple pods/services now affected OR user-facing impact confirmed
- Any → P1: CCD head (Prakash) or CIO escalates directly

---

## Approval Gates — Read vs Write

### NEVER Require Approval (Read-Only)
These operations are safe and the agent should execute immediately:
- `GET` any K8s API endpoint (pods, logs, events, nodes, services)
- `curl` to CheckMK API (read-only queries)
- Any log fetch, event listing, node check, health check
- Metrics-server queries
- Cluster health sweep

### ALWAYS Require Approval (Write Operations)
Call `request_human_approval` before executing:
| Operation | Urgency | Why |
|-----------|---------|-----|
| Delete pod | High | Disrupts running workload |
| Patch deployment | High | Changes live configuration |
| Scale replicas | High | Changes capacity |
| Restart service/deployment | High | Causes brief downtime |
| Cordon node | High | Prevents new scheduling |
| Drain node | Critical | Evicts all workloads |
| Apply config change | High | Changes cluster state |

### Conditional Approval
| Condition | Approval |
|-----------|----------|
| P1 incident + auto-fix available | Still require approval — P1 = mandatory human sign-off |
| Mandatory escalation flag in job | Always require — even for read-only |
| Scheduled change (CAB approved) | Pre-approved — execute per change record |

---

## Escalation Decision Tree

```
Agent receives issue
    │
    ├── Can agent diagnose with K8s API + CheckMK? 
    │   ├── YES → Complete investigation, produce report
    │   │   ├── Root cause identified + fix is read-only (no changes needed)
    │   │   │   └── RESOLVE: Report findings, no approval needed
    │   │   ├── Root cause identified + fix is write operation
    │   │   │   └── REQUEST APPROVAL → present evidence + proposed action
    │   │   └── Root cause unclear after full investigation
    │   │       └── ESCALATE to CCD on-call with evidence collected
    │   │
    │   └── NO (API unreachable, token expired, etc.)
    │       └── ESCALATE immediately — agent cannot operate
    │
    └── Is this a known pattern with playbook?
        ├── YES → Follow playbook in exceptions/ files
        └── NO → Investigate using ReAct loop, document findings, escalate if unresolved
```

---

## Escalation Contacts

| Level | Contact | When |
|-------|---------|------|
| L1 | Agent (ccdops) | First response — investigation, diagnosis, read-only actions |
| L2 | CCD on-call | Agent cannot resolve, write action needed, or unfamiliar pattern |
| L3 | Platform lead | Infrastructure-level issue, multi-cluster impact |
| L4 | CCD head (Prakash) | Major incident, data loss risk, executive escalation |
| Token refresh | Vinoth (CCD team) | HTTP 401 on K8s API — token expired |

**IHD Ticket Required For:**
- Any P1 incident
- Any write action performed on the cluster
- Any issue that required human intervention
- Any new pattern not in the exceptions files

---

## Auto-Fix Rules

These are situations where the fix is well-understood but still requires approval:

| Pattern | Proposed Auto-Fix | Approval Required | Post-Fix Validation |
|---------|-------------------|-------------------|---------------------|
| CrashLoopBackOff (OOMKilled, low limits) | Patch deployment to increase memory limit | Yes | Verify pod Running, no restarts for 5 min |
| Pod stuck Pending (quota exhausted) | Increase namespace quota | Yes | Verify pod scheduled and Running |
| Ingress gateway OOM | Increase gateway memory limit | Yes | Verify gateway healthy, 0% 5xx |
| Stale pod (Evicted, still showing) | Delete evicted pod | Yes | Verify pod cleaned up |
| Node DiskPressure (image cache) | Prune unused images on node | Yes (SSH action) | Verify DiskPressure=False |

**No Auto-Fix — Always Escalate:**
- Node NotReady (root cause uncertain)
- CoreDNS down (critical path)
- Multi-namespace outage (shared component likely)
- Cluster upgrade related
- Anything involving certificates or secrets
- Any pattern not seen before

---

## Cross-Layer Correlation Rules

Use these to determine which layer owns the root cause:

| Symptom Combination | Root Cause Layer | Action |
|---------------------|------------------|--------|
| Pod errors + Istio errors | Application | Not infra — escalate to project team |
| Pod OOMKilled + Node MemoryPressure | Resource config | Increase pod limits or scale nodes |
| Node NotReady + calico/kube-system failures | Infrastructure | Escalate to CCD platform team |
| Multiple namespaces affected | Shared component | Check LB, DNS, Longhorn, Calico |
| Single namespace affected | App or quota | Check with project team |
| K8s node issue + CheckMK host CRITICAL | VM / hardware | Infrastructure — check hypervisor |
| K8s healthy + CheckMK host CRITICAL | VM layer | Preemptive action before K8s impact |
| K8s unhealthy + CheckMK host OK | K8s config | Inside Kubernetes — config, image, limits |

---

## Change Management Rules

| Change Type | Risk | CAB Required | Maintenance Window | Rollback Plan Required |
|-------------|------|-------------|-------------------|----------------------|
| Pod restart / delete | Low | No | No | No (K8s auto-recovers) |
| Deployment patch (limits) | Medium | No | No | Yes (revert patch) |
| Scale replicas | Low | No | No | Yes (scale back) |
| Node drain for patching | Medium | Yes | Yes | Yes (uncordon) |
| Cluster upgrade (minor) | High | Yes | Yes | Yes (downgrade path documented) |
| Cluster upgrade (major) | Critical | Yes | Yes | Yes (full cluster rebuild if needed) |
| Network policy change | Medium | Yes | No | Yes (remove policy) |
| RBAC change | Medium | Yes | No | Yes (revert binding) |

---

## Output Format

After every investigation, produce this report:

```
## CCD Ops Investigation Report

**Cluster**: 10.232.173.106 (RKE2 v1.31.7)
**Namespace**: <namespace>
**Reported Issue**: <what user said>
**Severity**: P1 / P2 / P3 / P4
**Confidence**: HIGH / MEDIUM / LOW

### Evidence Chain
1. [SOURCE: K8s API /pods] → found: <pod_name> restarts=8, lastReason=OOMKilled
2. [SOURCE: K8s API /pods/<pod>/log] → found: "java.lang.OutOfMemoryError"
3. [SOURCE: K8s API /events] → found: Warning OOMKilling at 14:32 UTC
4. [SOURCE: CheckMK <host>] → host memory OK (45% used)

### Root Cause
<one clear sentence>

### Impact
<which pods/services affected, which project teams>

### Proposed Action
<specific remediation — restart pod, adjust memory limit, scale node>
<approval_required: yes/no>

### Escalation
<IHD ticket needed? CCD on-call? Platform lead?>
```
