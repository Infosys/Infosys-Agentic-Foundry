---
name: IT Ops ITIL Mapping
type: itil_mapping
description: Cross-reference mapping from L4/L5 taxonomy activities to ITIL v4 practices
status: active
skills:
  - ccdops
---

# IT Operations → ITIL v4 Practice Mapping
_Last updated: 2026-04-20_

This file provides an **ITIL-oriented view** over the technology-first taxonomy.
Use this for CIO reporting, ITSM compliance, and cross-technology analysis.

The taxonomy (`taxonomy/it_ops_taxonomy.md`) organizes by technology (L2) → subprocess (L3).
This file reorganizes the same L5 activities by ITIL practice for management views.

---

## Incident Management

All activities tagged `[incident]` in the taxonomy.

| L5 Activity | Taxonomy Path | Severity | MTTR Target | Exception File |
|-------------|---------------|----------|-------------|----------------|
| Restart CrashLoopBackOff pod | IT Ops > K8s > Pod Lifecycle > Pod Failure | P2 | 15 min | `exceptions/k8s_pod_exceptions.md` |
| Evict & resize OOMKilled pod | IT Ops > K8s > Pod Lifecycle > Pod Failure | P2 | 15 min | `exceptions/k8s_pod_exceptions.md` |
| Fix ImagePullBackOff | IT Ops > K8s > Pod Lifecycle > Pod Failure | P3 | 10 min | `exceptions/k8s_pod_exceptions.md` |
| Resolve pod Pending state | IT Ops > K8s > Pod Lifecycle > Pod Failure | P3 | 15 min | `exceptions/k8s_pod_exceptions.md` |
| Recover Evicted pod | IT Ops > K8s > Pod Lifecycle > Pod Failure | P2 | 20 min | `exceptions/k8s_pod_exceptions.md` |
| Drain NotReady node | IT Ops > K8s > Node Mgmt > Node Failure | P1 | 30 min | `exceptions/k8s_node_exceptions.md` |
| Cordon & replace unhealthy node | IT Ops > K8s > Node Mgmt > Node Failure | P1 | 60 min | `exceptions/k8s_node_exceptions.md` |
| Resolve MemoryPressure | IT Ops > K8s > Node Mgmt > Node Failure | P2 | 20 min | `exceptions/k8s_node_exceptions.md` |
| Resolve DiskPressure | IT Ops > K8s > Node Mgmt > Node Failure | P2 | 20 min | `exceptions/k8s_node_exceptions.md` |
| Triage PagerDuty/Chime alert | IT Ops > K8s > Observability > Alert Response | P1-P4 | 5 min | — |
| Acknowledge & classify severity | IT Ops > K8s > Observability > Alert Response | — | 5 min | — |
| Correlate K8s + CheckMK alerts | IT Ops > K8s > Observability > Alert Response | — | 10 min | — |
| Ingress gateway errors | IT Ops > K8s > Networking > Istio | P2 | 20 min | `exceptions/k8s_network_exceptions.md` |
| Sidecar injection failure | IT Ops > K8s > Networking > Istio | P3 | 15 min | `exceptions/k8s_network_exceptions.md` |
| mTLS communication failure | IT Ops > K8s > Networking > Istio | P2 | 20 min | `exceptions/k8s_network_exceptions.md` |
| CoreDNS resolution failure | IT Ops > K8s > Networking > DNS | P1 | 15 min | `exceptions/k8s_network_exceptions.md` |
| Service endpoint not found | IT Ops > K8s > Networking > DNS | P2 | 10 min | `exceptions/k8s_network_exceptions.md` |

---

## Change Management

All activities tagged `[change]` in the taxonomy.

| L5 Activity | Taxonomy Path | Risk | CAB Required | Rollback Plan |
|-------------|---------------|------|-------------|---------------|
| Rolling update deployment | IT Ops > K8s > Pod Lifecycle > Deployment | Low | No | Rollback to previous revision |
| Rollback failed deployment | IT Ops > K8s > Pod Lifecycle > Deployment | Medium | Yes | Re-deploy previous version |
| Canary deployment validation | IT Ops > K8s > Pod Lifecycle > Deployment | Low | No | Abort canary |
| OS patching with drain | IT Ops > K8s > Node Mgmt > Maintenance | Medium | Yes (CAB) | Uncordon, skip patch |
| Node pool resize | IT Ops > K8s > Node Mgmt > Maintenance | Medium | Yes | Scale back |
| Kernel/containerd upgrade | IT Ops > K8s > Node Mgmt > Maintenance | High | Yes (CAB) | Rollback kernel |
| RKE2 minor version upgrade | IT Ops > K8s > Cluster Ops > Upgrades | High | Yes (CAB) | Downgrade path |
| RKE2 patch version upgrade | IT Ops > K8s > Cluster Ops > Upgrades | Medium | Yes | Rollback patch |
| Rancher mgmt plane upgrade | IT Ops > K8s > Cluster Ops > Upgrades | High | Yes (CAB) | Restore backup |

---

## Monitoring & Event Management

All activities tagged `[monitoring]` in the taxonomy.

| L5 Activity | Taxonomy Path | Frequency |
|-------------|---------------|-----------|
| API server health gates check | IT Ops > K8s > Cluster Ops > Health Assessment | On-demand / scheduled |
| Cluster-wide warning events sweep | IT Ops > K8s > Cluster Ops > Health Assessment | Daily |
| Node capacity vs utilization review | IT Ops > K8s > Cluster Ops > Health Assessment | Weekly |
| Top memory consumers report | IT Ops > K8s > Cluster Ops > Health Assessment | Weekly |
| Run pod readiness probe review | IT Ops > K8s > Observability > Health Check | Weekly |
| Check resource utilization vs limits | IT Ops > K8s > Observability > Health Check | Daily |
| Validate monitoring stack health | IT Ops > K8s > Observability > Health Check | Daily |

---

## Capacity Management

All activities tagged `[capacity]` in the taxonomy.

| L5 Activity | Taxonomy Path | Trigger |
|-------------|---------------|---------|
| Scale HPA for traffic spike | IT Ops > K8s > Pod Lifecycle > Scaling | HPA trigger or manual |
| Rebalance pods across nodes | IT Ops > K8s > Pod Lifecycle > Scaling | Post node recovery |
| Resolve quota exhaustion | IT Ops > K8s > Pod Lifecycle > Scaling | Quota hit |

---

## Security Management

All activities tagged `[security]` in the taxonomy.

| L5 Activity | Taxonomy Path | Approval Required |
|-------------|---------------|-------------------|
| Create namespace with quotas | IT Ops > K8s > Cluster Ops > RBAC | No |
| Update RBAC roles/bindings | IT Ops > K8s > Cluster Ops > RBAC | Yes |
| Audit namespace permissions | IT Ops > K8s > Cluster Ops > RBAC | No |
| Create/update network policy | IT Ops > K8s > Networking > Policy | Yes |
| Audit Calico network policies | IT Ops > K8s > Networking > Policy | No |

---

## Summary Statistics

| ITIL Practice | L5 Activity Count | P1 | P2 | P3 | P4 |
|---------------|-------------------|----|----|----|----|
| Incident Management | 17 | 3 | 9 | 4 | 1 |
| Change Management | 9 | 0 | 0 | 0 | 0 |
| Monitoring & Event Management | 7 | 0 | 0 | 0 | 0 |
| Capacity Management | 3 | 0 | 0 | 0 | 0 |
| Security Management | 5 | 0 | 0 | 0 | 0 |
| **Total** | **41** | **3** | **9** | **4** | **1** |
