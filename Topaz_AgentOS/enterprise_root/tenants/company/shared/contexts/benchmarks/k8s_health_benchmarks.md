---
name: K8s Health Benchmarks
type: benchmarks
description: Performance benchmarks, SLA targets, and alert thresholds for Kubernetes operations
status: active
skills:
  - ccdops
---

# K8s Health Benchmarks & SLA Targets
_Last updated: 2026-04-20_

Operational benchmarks derived from CCD team experience and industry standards.
Agents use these to assess severity, set MTTR expectations, and flag anomalies.

---

## Alert Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Pod restart count | >3 in 1h | >10 in 1h | CrashLoopBackOff investigation |
| Node CPU utilization | 75% | 90% | Scale or investigate workload |
| Node memory utilization | 80% | 95% | OOM investigation → eviction risk |
| Node disk utilization | 80% | 90% | Disk cleanup or PVC expansion |
| Pod pending duration | >5 min | >15 min | Scheduling failure → node pressure or quota |
| API server response time | >500ms | >2s | API server degraded — check etcd, load |
| CoreDNS failure rate | >1% | >5% | DNS investigation — check CoreDNS pods |
| Ingress gateway 5xx rate | >1% | >5% | Gateway investigation — check upstream health |

---

## MTTR Targets by Severity

| Severity | Description | Detection | Acknowledge | Resolve | Total MTTR |
|----------|-------------|-----------|-------------|---------|------------|
| P1 | Service down, multiple users impacted | 5 min | 5 min | 30 min | 40 min |
| P2 | Single service degraded, workaround available | 10 min | 10 min | 60 min | 80 min |
| P3 | Non-critical issue, no immediate user impact | 30 min | 30 min | 4 hours | 5 hours |
| P4 | Cosmetic, informational, or scheduled maintenance | Next business day | Next business day | 5 days | 5 days |

---

## MTTR by Activity (L5 Level)

| L5 Activity | Severity | Target MTTR | Notes |
|-------------|----------|-------------|-------|
| Restart CrashLoopBackOff pod | P2 | 15 min | Most common — check logs first |
| Evict & resize OOMKilled pod | P2 | 15 min | Quick if just memory limit increase |
| Fix ImagePullBackOff | P3 | 10 min | Usually wrong tag or registry auth |
| Resolve pod Pending | P3 | 15 min | Check quotas and node capacity |
| Drain NotReady node | P1 | 30 min | High impact — workloads relocate |
| Cordon & replace node | P1 | 60 min | Requires provisioning replacement |
| Resolve MemoryPressure | P2 | 20 min | Identify top consumers, evict or scale |
| Resolve DiskPressure | P2 | 20 min | Prune images, clean logs |
| Triage PagerDuty alert | P1-P4 | 5 min | Acknowledge and classify only |
| Ingress gateway errors | P2 | 20 min | Check upstream pod health |
| CoreDNS failure | P1 | 15 min | Critical — breaks all service discovery |
| Cluster upgrade (RKE2) | — | Planned | Maintenance window, CAB approved |
| OS patching with drain | — | Planned | Maintenance window |

---

## Pod Restart Baselines

Known normal restart counts for CCD cluster (as of 2026-03-30):

| Namespace | Pods | Normal Restarts | Escalate If |
|-----------|------|-----------------|-------------|
| `istio-system` | istio-ingressgateway, istiod | 4–8 | >15 or latency spike |
| `kube-system` | All core pods | 0 | Any restart |
| `calico-system` | calico-node, calico-typha | 0–1 | >3 |
| `longhorn-system` | longhorn-manager, CSI driver | 0–1 | >3 |
| `ai-gateway` | Workload pods | 0 | >3 in 1h |

---

## Node Capacity Benchmarks

CCD cluster reference (6 nodes, RKE2 v1.31.7):

| Metric | Per Node (Typical) | Cluster Total | Healthy Threshold |
|--------|-------------------|---------------|-------------------|
| CPU cores | 8 | 48 | <75% utilized |
| Memory | 32 Gi | 192 Gi | <80% utilized |
| Pods | 110 (default max) | 660 | <80% allocated |
| Disk | Varies | Varies | <80% used |

---

## Availability Targets

| Component | Target | Measurement |
|-----------|--------|-------------|
| Cluster API server | 99.9% | /healthz returns ok |
| Worker nodes (Ready) | 100% (n-1 tolerated) | At least 5 of 6 Ready |
| Pod availability (workload) | 99.5% | Pods Running and Ready |
| Ingress gateway | 99.9% | <1% 5xx error rate |
| DNS resolution | 99.99% | CoreDNS success rate |

---

## CheckMK Correlation Thresholds

When cross-referencing K8s issues with CheckMK host health:

| CheckMK State | K8s Impact | Action |
|---------------|------------|--------|
| PING CRITICAL (lost 100%) | Node unreachable — kubelet cannot communicate | Escalate to infra team immediately |
| Disk CRITICAL (>95%) | DiskPressure → pod evictions | Clean disk, expand storage |
| Memory WARNING (>80%) | Risk of MemoryPressure | Monitor, prepare to scale |
| Memory CRITICAL (>95%) | MemoryPressure active → OOMKilled pods | Immediate remediation |
| CPU CRITICAL (>90%) | Pod throttling → slow startup, timeouts | Identify hogs, scale |
| Service check CRITICAL | Application failure on VM itself | Investigate VM service, not K8s |
