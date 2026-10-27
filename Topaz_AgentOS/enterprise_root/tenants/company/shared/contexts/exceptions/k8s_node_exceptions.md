---
name: K8s Node Exceptions
type: exceptions
description: Node-level failure patterns, root causes, and resolution playbooks for Kubernetes
status: active
skills:
  - ccdops
---

# K8s Node Exception Patterns
_Last updated: 2026-04-20_

Node-level failure patterns extracted from CCD operations experience.
Includes cluster-wide health sweep procedures.

---

## Node NotReady

**What it means:** The node has lost connectivity to the API server, kubelet has crashed, or the node has a critical failure.

**Symptoms:**
- Node condition `Ready` = `False` or `Unknown`
- Pods on the node may show `Terminating` or `Unknown` status
- Events show `NodeNotReady`

**Investigation Sequence:**
1. List all nodes → identify which node is NotReady and its conditions
2. Check node allocatable vs capacity (resource exhaustion?)
3. Check actual resource usage via metrics-server
4. Check system namespace pods (kube-system, calico-system) for failures on that node
5. Cross-reference with CheckMK — is the host VM reachable? (PING, disk, memory, CPU)
6. If SSH available: check kubelet status, containerd status, system logs

**Common Root Causes:**

| Root Cause | Evidence | Resolution |
|-----------|----------|------------|
| Kubelet crashed | Node was Ready, suddenly NotReady. CheckMK PING OK | Restart kubelet service on the node |
| VM unreachable | CheckMK PING CRITICAL (lost 100%) | Contact hypervisor team, check VM host |
| Disk full | DiskPressure=True, CheckMK disk CRITICAL | Clean up logs, images, expand disk |
| Memory exhaustion | MemoryPressure=True, CheckMK memory CRITICAL | Identify top consumers, add capacity |
| Network partition | Node reachable by SSH but not by API server | Check network policies, Calico health, VPN |
| Certificate expired | kubelet logs show TLS/certificate errors | Renew node certificates (RKE2 auto-rotation check) |

---

## MemoryPressure

**What it means:** Node kernel is under memory pressure. Kubernetes may start evicting pods.

**Symptoms:**
- Node condition `MemoryPressure` = `True`
- Pods being evicted (status `Evicted`)
- OOMKilled events appearing on pods

**Investigation Sequence:**
1. Confirm MemoryPressure on node conditions
2. Get actual memory usage from metrics-server
3. Identify top memory-consuming pods on that node
4. Check if any pod has no memory limits set (unbounded consumers)
5. Check CheckMK host for memory CRITICAL/WARNING
6. Check for memory leak patterns (pods whose memory grows over time)

**Resolution:**
- Short-term: Evict low-priority pods, cordon node, move workloads
- Medium-term: Increase memory limits on offending pods, fix memory leaks
- Long-term: Add nodes to cluster, implement resource quotas per namespace

---

## DiskPressure

**What it means:** Node disk usage exceeds eviction threshold (typically >85%).

**Symptoms:**
- Node condition `DiskPressure` = `True`
- Pods being evicted
- New pods failing to schedule on this node

**Investigation Sequence:**
1. Confirm DiskPressure on node conditions
2. SSH to node (if available) → `df -h` to check disk usage
3. Check container log sizes: `/var/log/containers/`
4. Check container image cache size: `crictl images`
5. Check emptyDir volumes (no default size limit)
6. Check Longhorn storage health

**Common Disk Consumers:**
- Container runtime logs (containerd)
- Application pod logs (no rotation configured)
- Unused container images (old deployments)
- emptyDir volumes without sizeLimit
- Longhorn replicas (if Longhorn is on same disk)

**Resolution:**
- Immediate: Prune unused images (`crictl rmi --prune`), delete old container logs
- Short-term: Add log rotation to pods, set emptyDir sizeLimit
- Long-term: Expand disk, move Longhorn to separate volume

---

## PIDPressure

**What it means:** Node is running out of process IDs. Rare but critical.

**Symptoms:**
- Node condition `PIDPressure` = `True`
- Pods failing to start with "cannot allocate memory" or "fork: resource temporarily unavailable"

**Investigation Sequence:**
1. Confirm PIDPressure on node
2. Check total processes: `ps aux | wc -l`
3. Identify top process consumers: `ps aux --sort=-%mem | head -20`
4. Check if a pod is fork-bombing or spawning excessive threads

**Resolution:**
- Identify and kill the runaway process/pod
- Set PID limits per pod via `resources.limits.pid` (if supported)
- Increase kernel pid_max if appropriate

---

## Cluster-Wide Health Sweep

Use when asked for "overall cluster health" or as a scheduled background check.

**Sequence:**
1. **API Server Health Gates** — verify `/healthz`, `/readyz`, `/livez` all return `ok`
   - All OK → API server healthy, continue
   - Any error → API server degraded, escalate immediately to CCD platform team
2. **Node Status + Resource Usage** — list all nodes with conditions + metrics-server actual usage
   - Any NotReady → trigger Node NotReady investigation
   - Any MemoryPressure/DiskPressure → trigger respective investigation
3. **Cluster-Wide Warning Events** — scan all namespaces for Warning events (last 30)
   - Warnings in kube-system/calico-system → infrastructure issue, escalate
   - Warnings in workload namespaces → route to Pod Exception patterns
4. **Top Memory Consumers** — identify top 20 pods by memory usage
   - Any pod approaching its limit → flag for capacity review

**Decision After Sweep:**
- All nodes Ready + no Warning events + all healthz OK → cluster healthy, no action
- Nodes with high memory approaching allocatable → flag for capacity review
- Warning events in infrastructure namespaces → escalate to CCD team
- Warning events in workload namespaces → route to relevant pod/network exception
