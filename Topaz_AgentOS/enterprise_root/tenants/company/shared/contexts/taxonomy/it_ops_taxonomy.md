---
name: IT Operations Taxonomy
type: taxonomy
description: L1-L5 process hierarchy for IT Operations — Container Orchestration (K8s), Cloud, Network, Database
status: active
skills:
  - ccdops
---

# IT Operations — Process Taxonomy (L1→L5)
_Last updated: 2026-04-20_

This taxonomy defines the **process hierarchy** for IT Operations.
Each L5 activity is tagged with its ITIL v4 practice for cross-reference reporting.

ITIL tags: `[incident]` `[change]` `[monitoring]` `[capacity]` `[security]` `[problem]`

---

## Quick Index — All L5 Activities (flat)

Every L5 activity with its full hierarchy pre-baked. Use this for fast lookup — detailed sections below.

| L5 Activity | L2 | L3 | L4 | ITIL | Sev | MTTR |
|---|---|---|---|---|---|---|
| Restart CrashLoopBackOff pod | K8s | Pod Lifecycle | Pod Failure Remediation | incident | P2 | 15 min |
| Evict & resize OOMKilled pod | K8s | Pod Lifecycle | Pod Failure Remediation | incident | P2 | 15 min |
| Fix ImagePullBackOff | K8s | Pod Lifecycle | Pod Failure Remediation | incident | P3 | 10 min |
| Resolve pod Pending state | K8s | Pod Lifecycle | Pod Failure Remediation | incident | P3 | 15 min |
| Recover Evicted pod | K8s | Pod Lifecycle | Pod Failure Remediation | incident | P2 | 20 min |
| Scale HPA for traffic spike | K8s | Pod Lifecycle | Pod Scaling & Scheduling | capacity | P3 | 10 min |
| Rebalance pods across nodes | K8s | Pod Lifecycle | Pod Scaling & Scheduling | capacity | P4 | 20 min |
| Resolve quota exhaustion | K8s | Pod Lifecycle | Pod Scaling & Scheduling | capacity | P3 | 15 min |
| Rolling update deployment | K8s | Pod Lifecycle | Pod Deployment & Rollback | change | — | — |
| Rollback failed deployment | K8s | Pod Lifecycle | Pod Deployment & Rollback | change | — | — |
| Canary deployment validation | K8s | Pod Lifecycle | Pod Deployment & Rollback | change | — | — |
| Drain NotReady node | K8s | Node Management | Node Failure Recovery | incident | P1 | 30 min |
| Cordon & replace unhealthy node | K8s | Node Management | Node Failure Recovery | incident | P1 | 60 min |
| Resolve MemoryPressure | K8s | Node Management | Node Failure Recovery | incident | P2 | 20 min |
| Resolve DiskPressure | K8s | Node Management | Node Failure Recovery | incident | P2 | 20 min |
| OS patching with drain | K8s | Node Management | Node Maintenance | change | — | — |
| Node pool resize (scale up/down) | K8s | Node Management | Node Maintenance | change | — | — |
| Kernel/containerd upgrade | K8s | Node Management | Node Maintenance | change | — | — |
| RKE2 minor version upgrade | K8s | Cluster Operations | Cluster Upgrades | change | — | — |
| RKE2 patch version upgrade | K8s | Cluster Operations | Cluster Upgrades | change | — | — |
| Rancher management plane upgrade | K8s | Cluster Operations | Cluster Upgrades | change | — | — |
| Create namespace with quotas | K8s | Cluster Operations | Namespace & RBAC | security | — | — |
| Update RBAC roles/bindings | K8s | Cluster Operations | Namespace & RBAC | security | — | — |
| Audit namespace permissions | K8s | Cluster Operations | Namespace & RBAC | security | — | — |
| API server health gates check | K8s | Cluster Operations | Cluster Health Assessment | monitoring | — | — |
| Cluster-wide warning events sweep | K8s | Cluster Operations | Cluster Health Assessment | monitoring | — | — |
| Node capacity vs utilization review | K8s | Cluster Operations | Cluster Health Assessment | monitoring | — | — |
| Top memory consumers report | K8s | Cluster Operations | Cluster Health Assessment | monitoring | — | — |
| Run pod readiness probe review | K8s | Observability & Alerting | Health Check Routines | monitoring | — | — |
| Check resource utilization vs limits | K8s | Observability & Alerting | Health Check Routines | monitoring | — | — |
| Validate monitoring stack health | K8s | Observability & Alerting | Health Check Routines | monitoring | — | — |
| Triage PagerDuty/Chime alert | K8s | Observability & Alerting | Alert Response | incident | P1-P4 | 5 min |
| Acknowledge & classify severity | K8s | Observability & Alerting | Alert Response | incident | — | 5 min |
| Correlate K8s + CheckMK alerts | K8s | Observability & Alerting | Alert Response | incident | — | 10 min |
| Ingress gateway errors | K8s | Networking & Service Mesh | Istio / Service Mesh | incident | P2 | 20 min |
| Sidecar injection failure | K8s | Networking & Service Mesh | Istio / Service Mesh | incident | P3 | 15 min |
| mTLS communication failure | K8s | Networking & Service Mesh | Istio / Service Mesh | incident | P2 | 20 min |
| CoreDNS resolution failure | K8s | Networking & Service Mesh | DNS & Service Discovery | incident | P1 | 15 min |
| Service endpoint not found | K8s | Networking & Service Mesh | DNS & Service Discovery | incident | P2 | 10 min |
| Create/update network policy | K8s | Networking & Service Mesh | Network Policy Mgmt | security | — | — |
| Audit Calico network policies | K8s | Networking & Service Mesh | Network Policy Mgmt | security | — | — |

---

## L1: IT Operations

### L2: Container Orchestration (K8s)

#### L3: Pod Lifecycle Management
<!-- skill: ccdops -->

##### L4: Pod Failure Remediation `[incident]`
| L5 | Description | Severity | MTTR Target | Exception File |
|----|-------------|----------|-------------|----------------|
| Restart CrashLoopBackOff pod | Container keeps crashing and restarting. Check logs for OOM, app errors, config issues | P2 | 15 min | `exceptions/k8s_pod_exceptions.md` → CrashLoopBackOff |
| Evict & resize OOMKilled pod | Kernel killed container for exceeding memory limit. Increase limits or fix memory leak | P2 | 15 min | `exceptions/k8s_pod_exceptions.md` → OOMKilled |
| Fix ImagePullBackOff | Container image cannot be pulled. Check registry access, image tag, or pull secret | P3 | 10 min | `exceptions/k8s_pod_exceptions.md` → ImagePullBackOff |
| Resolve pod Pending state | Pod cannot be scheduled. Check node resources, affinity rules, taints/tolerations | P3 | 15 min | `exceptions/k8s_pod_exceptions.md` → Pending |
| Recover Evicted pod | Pod evicted due to node disk or memory pressure. Check node health, redeploy | P2 | 20 min | `exceptions/k8s_pod_exceptions.md` → Evicted |

##### L4: Pod Scaling & Scheduling `[capacity]`
| L5 | Description | Severity | MTTR Target |
|----|-------------|----------|-------------|
| Scale HPA for traffic spike | Horizontal Pod Autoscaler triggered or needs manual intervention | P3 | 10 min |
| Rebalance pods across nodes | Pods unevenly distributed after node recovery or scale-up | P4 | 20 min |
| Resolve quota exhaustion | Namespace resource quota hit — pods can't schedule | P3 | 15 min |

##### L4: Pod Deployment & Rollback `[change]`
| L5 | Description | Risk | Approval |
|----|-------------|------|----------|
| Rolling update deployment | Deploy new version with zero-downtime rolling strategy | Low | No |
| Rollback failed deployment | Revert to previous known-good version after deployment failure | Medium | Yes |
| Canary deployment validation | Validate canary release metrics before full rollout | Low | No |

---

#### L3: Node Management
<!-- skill: ccdops -->

##### L4: Node Failure Recovery `[incident]`
| L5 | Description | Severity | MTTR Target | Exception File |
|----|-------------|----------|-------------|----------------|
| Drain NotReady node | Node lost connectivity or kubelet crashed. Drain workloads, investigate | P1 | 30 min | `exceptions/k8s_node_exceptions.md` → NotReady |
| Cordon & replace unhealthy node | Node has persistent hardware/OS issues. Cordon, drain, replace | P1 | 60 min | `exceptions/k8s_node_exceptions.md` → NotReady |
| Resolve MemoryPressure | Node kernel under memory pressure — pods at risk of OOM eviction | P2 | 20 min | `exceptions/k8s_node_exceptions.md` → MemoryPressure |
| Resolve DiskPressure | Node disk >90% — pod evictions imminent. Clean up or expand storage | P2 | 20 min | `exceptions/k8s_node_exceptions.md` → DiskPressure |

##### L4: Node Maintenance `[change]`
| L5 | Description | Risk | Approval |
|----|-------------|------|----------|
| OS patching with drain | Drain node, apply OS patches, uncordon. Schedule during maintenance window | Medium | Yes (CAB) |
| Node pool resize (scale up/down) | Add or remove nodes from the cluster | Medium | Yes |
| Kernel/containerd upgrade | Upgrade container runtime or kernel on worker node | High | Yes (CAB) |

---

#### L3: Cluster Operations
<!-- skill: ccdops -->

##### L4: Cluster Upgrades `[change]`
| L5 | Description | Risk | Approval |
|----|-------------|------|----------|
| RKE2 minor version upgrade | Upgrade Kubernetes minor version (e.g., 1.30 → 1.31) | High | Yes (CAB) |
| RKE2 patch version upgrade | Apply patch release for security/bug fixes | Medium | Yes |
| Rancher management plane upgrade | Upgrade Rancher server components | High | Yes (CAB) |

##### L4: Namespace & RBAC Management `[security]`
| L5 | Description | Risk | Approval |
|----|-------------|------|----------|
| Create namespace with quotas | Provision new namespace with resource limits for project team | Low | No |
| Update RBAC roles/bindings | Modify role-based access for user or service account | Medium | Yes |
| Audit namespace permissions | Review who has access to what across namespaces | Low | No |

##### L4: Cluster Health Assessment `[monitoring]`
| L5 | Description | Frequency |
|----|-------------|-----------|
| API server health gates check | Verify /healthz, /readyz, /livez all return ok | On-demand / scheduled |
| Cluster-wide warning events sweep | Scan all namespaces for Warning events, identify patterns | Daily |
| Node capacity vs utilization review | Compare allocatable vs actual usage across all nodes | Weekly |
| Top memory consumers report | Identify top 20 pods by memory usage cluster-wide | Weekly |

---

#### L3: Observability & Alerting
<!-- skill: ccdops -->

##### L4: Health Check Routines `[monitoring]`
| L5 | Description | Frequency |
|----|-------------|-----------|
| Run pod readiness probe review | Check which pods have readiness/liveness probes configured | Weekly |
| Check resource utilization vs limits | Compare actual CPU/memory usage against limits per pod | Daily |
| Validate monitoring stack health | Ensure Grafana/Prometheus/CheckMK are collecting data | Daily |

##### L4: Alert Response `[incident]`
| L5 | Description | Severity | MTTR Target |
|----|-------------|----------|-------------|
| Triage PagerDuty/Chime alert | Receive alert, classify severity, begin investigation | P1-P4 | 5 min |
| Acknowledge & classify severity | Determine P1-P4 based on impact and urgency | — | 5 min |
| Correlate K8s + CheckMK alerts | Cross-reference K8s pod/node issues with CheckMK host health | — | 10 min |

---

#### L3: Networking & Service Mesh
<!-- skill: ccdops -->

##### L4: Istio / Service Mesh Issues `[incident]`
| L5 | Description | Severity | MTTR Target | Exception File |
|----|-------------|----------|-------------|----------------|
| Ingress gateway errors | 5xx responses, upstream connection failures at Istio ingress | P2 | 20 min | `exceptions/k8s_network_exceptions.md` → Ingress |
| Sidecar injection failure | Istio sidecar not injecting into new pods | P3 | 15 min | `exceptions/k8s_network_exceptions.md` → Sidecar |
| mTLS communication failure | Service-to-service mTLS handshake failing | P2 | 20 min | `exceptions/k8s_network_exceptions.md` → mTLS |

##### L4: DNS & Service Discovery `[incident]`
| L5 | Description | Severity | MTTR Target | Exception File |
|----|-------------|----------|-------------|----------------|
| CoreDNS resolution failure | Pods cannot resolve service names | P1 | 15 min | `exceptions/k8s_network_exceptions.md` → DNS |
| Service endpoint not found | Service exists but has no backing endpoints | P2 | 10 min | `exceptions/k8s_network_exceptions.md` → Endpoints |

##### L4: Network Policy Management `[security]`
| L5 | Description | Risk | Approval |
|----|-------------|------|----------|
| Create/update network policy | Restrict or allow traffic between namespaces/pods | Medium | Yes |
| Audit Calico network policies | Review all network policies for unintended blocks | Low | No |

---

### L2: Cloud Infrastructure (AWS/Azure/GCP) — _Future_

_Placeholder for VM management, IAM, cloud networking, serverless, storage services._

### L2: Network Operations — _Future_

_Placeholder for firewall management, DNS, load balancers, VPN, WAN optimization._

### L2: Database Operations — _Future_

_Placeholder for Oracle, SQL Server, PostgreSQL, DB monitoring, backup/restore, schema changes._

---

## Cross-Layer Correlation Rules

These rules help the agent determine root cause when symptoms span multiple layers:

| Symptom Combination | Root Cause Layer | Action |
|---------------------|-----------------|--------|
| Pod errors + Istio errors | Application | Not infra — escalate to project team |
| Pod OOMKilled + Node MemoryPressure | Resource config | Increase pod memory limits or scale nodes |
| Node NotReady + calico/kube-system pod failures | Infrastructure | Escalate to CCD platform team |
| Multiple namespaces affected | Shared component | Check LB, DNS, Longhorn storage, Calico |
| Single namespace affected | App or quota | Check with project team, review quotas |
| K8s node issue + CheckMK host CRITICAL | VM/hardware | Infrastructure issue — check hypervisor |
| K8s healthy + CheckMK host CRITICAL | VM layer | VM problem not yet affecting K8s — preemptive action |
| K8s unhealthy + CheckMK host OK | K8s config | Problem is inside Kubernetes (config, image, limits) |
