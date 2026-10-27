---
name: K8s Pod Exceptions
type: exceptions
description: Pod-level failure patterns, root causes, and resolution playbooks for Kubernetes
status: active
skills:
  - ccdops
---

# K8s Pod Exception Patterns
_Last updated: 2026-04-20_

Pod-level failure patterns extracted from CCD operations experience.
Each pattern includes: symptoms, investigation steps, root causes, and resolution.

---

## CrashLoopBackOff

**What it means:** Container keeps crashing and Kubernetes keeps restarting it, with exponential backoff delays.

**Symptoms:**
- Pod status shows `CrashLoopBackOff`
- `restartCount` increasing (>3 in 1 hour = warning, >10 = critical)
- Events show `BackOff` + `Restarting container`

**Investigation Sequence:**
1. List pods → identify affected pod by restartCount and phase
2. Get current container logs (tailLines=200, grep for errors)
3. Get previous container logs (`?previous=true`) — shows what happened before crash
4. Check namespace events for OOM, scheduling, pull errors
5. If logs show memory errors → check node MemoryPressure
6. If logs empty → check liveness probe config (probe may be killing healthy container)

**Common Root Causes:**

| Root Cause | Log Signature | Resolution |
|-----------|---------------|------------|
| Application crash | `panic`, `fatal`, `unhandled exception`, `segfault` | Fix application code → escalate to dev team |
| OOM (memory limit) | `OOMKilled` in lastState, `OutOfMemoryError` in logs | Increase memory limit in deployment spec |
| Missing config/secrets | `FileNotFoundException`, `env variable not set` | Check ConfigMap/Secret mounts, verify they exist |
| Database connection failure | `connection refused`, `ECONNREFUSED`, `timeout` | Check DB pod health, network policies, service endpoints |
| Dependency not ready | `dial tcp: connection refused`, `service unavailable` | Check dependent service is running, use init containers |
| Bad image / entrypoint | `exec format error`, `not found` | Verify image tag, architecture (amd64 vs arm64) |
| Liveness probe too aggressive | Logs look healthy but pod keeps restarting | Increase `initialDelaySeconds` and `failureThreshold` |

**Decision Tree After Investigation:**
- Logs show OOM / heap / memory errors → resource limit too low, recommend increasing
- Logs show application error / panic → application-level bug, escalate to dev team
- Logs empty + restartCount > 0 → check liveness probe config
- Spec shows no resource limits set → container is unbounded, may starve node

---

## OOMKilled

**What it means:** Linux kernel killed the container because it exceeded its memory limit.

**Symptoms:**
- `lastState.terminated.reason` = `OOMKilled`
- Events show `OOMKilling`
- Pod may be Running (restarted) or CrashLoopBackOff (if repeated)
- Node may show `MemoryPressure` if cluster-wide

**Investigation Sequence:**
1. Confirm OOMKilled in pod status (`lastState.terminated.reason`)
2. Check pod spec for memory limits vs requests
3. Get pod logs → grep for heap/memory errors before kill
4. Check node MemoryPressure condition
5. Check node actual memory usage via metrics-server
6. Cross-reference with CheckMK for host-level memory alerts

**Common Root Causes:**

| Root Cause | Evidence | Resolution |
|-----------|----------|------------|
| Memory limit too low | Pod consistently hits limit before OOM | Increase `resources.limits.memory` |
| Memory leak | Memory usage grows over time until OOM | Fix application code, add JVM `-Xmx` flags |
| Traffic spike | OOM coincides with traffic increase | Scale replicas via HPA, increase memory |
| Sidecar memory | Istio sidecar consuming unexpected memory | Set sidecar resource limits via annotations |
| No limits set | Container uses all available node memory | Add explicit memory limits |

---

## ImagePullBackOff

**What it means:** Kubernetes cannot pull the container image from the registry.

**Symptoms:**
- Pod status `Pending` or `ImagePullBackOff`
- Events show `Failed to pull image`, `ErrImagePull`

**Investigation Sequence:**
1. Check events → get exact error message for image pull
2. Verify image name and tag exist in registry
3. Check imagePullSecrets in pod spec → is the secret present?
4. Check if registry is reachable from the node (network policies, firewall)
5. Check if registry credentials are expired

**Common Root Causes:**

| Root Cause | Event Message | Resolution |
|-----------|---------------|------------|
| Wrong image tag | `manifest unknown` | Fix image tag in deployment spec |
| Registry auth failed | `unauthorized`, `401` | Update imagePullSecret with valid credentials |
| Registry unreachable | `timeout`, `connection refused` | Check network policies, DNS, firewall rules |
| Image deleted | `not found` | Re-push image or update to available tag |
| Rate limiting | `429 Too Many Requests` | Use private registry mirror, add pull credentials |

---

## Pending (Stuck)

**What it means:** Pod cannot be scheduled to any node.

**Symptoms:**
- Pod phase = `Pending` for >5 minutes
- Events may show `FailedScheduling`

**Investigation Sequence:**
1. Check events → look for `FailedScheduling` with reason
2. Check node resources → are nodes full? (`kubectl describe node` / metrics API)
3. Check for taints/tolerations mismatch
4. Check node affinity rules in pod spec
5. Check namespace resource quotas

**Common Root Causes:**

| Root Cause | Event Message | Resolution |
|-----------|---------------|------------|
| Insufficient CPU/memory | `Insufficient cpu`, `Insufficient memory` | Scale cluster (add nodes) or reduce requests |
| Node selector mismatch | `didn't match node selector` | Fix nodeSelector in pod spec or label nodes |
| Taint not tolerated | `node had taint that pod didn't tolerate` | Add toleration or remove taint |
| PVC not bound | `persistentvolumeclaim not found` or `not bound` | Check PV/PVC, storage provisioner (Longhorn) |
| Resource quota exhausted | `exceeded quota` | Increase namespace quota or reduce other pods |

---

## Evicted

**What it means:** Kubernetes evicted the pod from the node due to resource pressure.

**Symptoms:**
- Pod status = `Failed`, reason = `Evicted`
- Events show `Evicted` with pressure type (disk, memory)
- Node conditions show DiskPressure or MemoryPressure = True

**Investigation Sequence:**
1. Check pod status → confirm Evicted and get message (usually shows which pressure)
2. Check node conditions → DiskPressure? MemoryPressure?
3. Check node disk usage and memory usage
4. Identify what's consuming disk (container logs, emptyDir volumes, images)
5. Cross-reference with CheckMK host alerts

**Common Root Causes:**

| Root Cause | Evidence | Resolution |
|-----------|----------|------------|
| Node disk full | DiskPressure=True, disk >90% | Clean up container logs, prune images, expand disk |
| Node memory exhaustion | MemoryPressure=True | Identify top memory pods, increase node capacity |
| Log volume explosion | Container writing excessive logs to emptyDir | Add log rotation, set emptyDir sizeLimit |
| Image cache full | Too many cached images on node | Prune unused images: `crictl rmi --prune` |

---

## General Pod Health Check (No Specific Symptom)

When user says "check pod X" or "is pod X healthy" without specifying what's wrong.

**Investigation Sequence:**
1. Find pod across all namespaces (name may be partial)
2. Check namespace events (Warning only) for this pod
3. **If** any of: zero Warning events + pod not healthy, restartCount > 0, phase is Pending/Unknown/Failed → deep diagnosis:
   - Fetch pod spec (resource limits, image, restart details)
   - Fetch current container logs (filtered for errors)
   - If restartCount > 0, fetch previous container logs
4. Apply decision tree:
   - Logs show OOM → resource limit too low
   - Logs show app error → escalate to dev team
   - Logs empty + restarts → check liveness probe
   - No limits set → container unbounded, may starve node
   - All clean but not ready → check readiness probe and service endpoints
