---
name: K8s Network Exceptions
type: exceptions
description: Network and service mesh failure patterns for Kubernetes (Istio, DNS, Ingress)
status: active
skills:
  - ccdops
---

# K8s Network & Service Mesh Exception Patterns
_Last updated: 2026-04-20_

Network-layer failure patterns including Istio service mesh, CoreDNS, Calico,
ingress, and inter-service communication issues.

---

## Ingress Gateway Errors

**What it means:** Istio ingress gateway returning 5xx errors or upstream connection failures.

**Symptoms:**
- Users report HTTP 502/503/504 from external endpoints
- Ingress gateway logs show `upstream connect error`, `upstream reset`, `no healthy upstream`
- Latency spikes on services behind the gateway

**Investigation Sequence:**
1. List istio-system pods → check ingress gateway restartCount and phase
2. Get ingress gateway logs → grep for `error|warn|upstream|5[0-9][0-9]|timeout|reset`
3. Check if backend pods are healthy (readiness probe passing)
4. Check service endpoints → are endpoints populated?
5. Check VirtualService and Gateway configs for routing errors
6. Check node pressure → gateway pod may be resource-starved

**Common Root Causes:**

| Root Cause | Log Signature | Resolution |
|-----------|---------------|------------|
| Backend pod not ready | `no healthy upstream` | Fix backend pod health (see pod exceptions) |
| Backend pod restarting | `upstream connect error or disconnect/reset` | Investigate CrashLoopBackOff on backend |
| Gateway resource limits | Gateway pod OOMKilled or throttled | Increase gateway resource limits |
| Config error | `error occurred` in gateway logs, no upstream matched | Check VirtualService routing rules |
| mTLS mismatch | `TLS handshake failed` | Verify PeerAuthentication and DestinationRule |

---

## Sidecar Injection Failure

**What it means:** Istio sidecar (Envoy proxy) not injecting into new pods.

**Symptoms:**
- Pod running but no `istio-proxy` container
- Service mesh routing not working for this pod
- Events may show webhook admission errors

**Investigation Sequence:**
1. Check if namespace has `istio-injection=enabled` label
2. Check if pod has `sidecar.istio.io/inject: "false"` annotation
3. Check istiod pod health in istio-system → is the webhook working?
4. Check MutatingWebhookConfiguration for istio-sidecar-injector

**Common Root Causes:**

| Root Cause | Resolution |
|-----------|------------|
| Namespace not labeled | `kubectl label ns <ns> istio-injection=enabled` |
| Pod annotation disables it | Remove `sidecar.istio.io/inject: "false"` |
| istiod down | Restart istiod or check its logs |
| Webhook cert expired | Restart istiod to regenerate cert |

---

## mTLS Communication Failure

**What it means:** Service-to-service mutual TLS handshake failing within the mesh.

**Symptoms:**
- Inter-service calls failing with connection reset
- Logs show `TLS handshake error`, `certificate verify failed`
- Works when mTLS is set to PERMISSIVE, fails in STRICT

**Investigation Sequence:**
1. Check PeerAuthentication policy for the namespace/service
2. Check DestinationRule for TLS settings
3. Verify both source and destination have Istio sidecar
4. Check certificate expiry: `istioctl proxy-config secret <pod>`

**Common Root Causes:**

| Root Cause | Resolution |
|-----------|------------|
| One side has no sidecar | Ensure both pods have istio-proxy container |
| PeerAuthentication set to STRICT, client not in mesh | Set to PERMISSIVE or add client to mesh |
| Certificate expired | Restart istiod to trigger cert rotation |
| DestinationRule TLS mode mismatch | Align DestinationRule trafficPolicy.tls.mode with PeerAuthentication |

---

## DNS Resolution Failure (CoreDNS)

**What it means:** Pods cannot resolve Kubernetes service names or external DNS names.

**Symptoms:**
- Application logs show `could not resolve host`, `DNS lookup failed`, `NXDOMAIN`
- `nslookup` or `dig` from within pod fails
- External service calls timeout

**Investigation Sequence:**
1. Check CoreDNS pods in kube-system → are they Running with 0 restarts?
2. Get CoreDNS logs → look for errors, SERVFAIL, timeouts
3. Check CoreDNS ConfigMap for correct configuration
4. Test DNS from inside a pod: `kubectl exec <pod> -- nslookup kubernetes.default`
5. Check network policies → anything blocking DNS traffic (port 53)?
6. Check Calico pods → network plugin issues can break DNS

**Common Root Causes:**

| Root Cause | Evidence | Resolution |
|-----------|----------|------------|
| CoreDNS pods crashed | CoreDNS restartCount > 0 | Check CoreDNS logs, restart if needed |
| Network policy blocking DNS | DNS works after removing NetworkPolicy | Allow egress to kube-dns on port 53 |
| CoreDNS config error | ConfigMap has wrong upstream or wrong zone | Fix CoreDNS ConfigMap |
| Calico network issue | All networking broken, not just DNS | Check calico-system pods |
| Node DNS config wrong | `/etc/resolv.conf` on node points wrong | Fix node DNS configuration |

---

## Service Endpoint Not Found

**What it means:** A Kubernetes Service exists but has no backing pod endpoints.

**Symptoms:**
- Calls to service return `connection refused` or `no route to host`
- `kubectl get endpoints <svc>` shows empty or no addresses
- Service exists but selector doesn't match any pod labels

**Investigation Sequence:**
1. Check service exists and its selector labels
2. Check endpoints → are addresses populated?
3. List pods with matching labels → are they Running and Ready?
4. Check if readiness probe is failing on backing pods
5. Check if pods are in a different namespace than the service

**Common Root Causes:**

| Root Cause | Resolution |
|-----------|------------|
| Selector label mismatch | Fix service selector to match pod labels |
| All backing pods not ready | Fix readiness probe issues on pods |
| Backing pods crashed | Investigate pod failures (see pod exceptions) |
| Wrong namespace | Service and pods must be in same namespace (or use ExternalName) |

---

## Performance Degradation / High Latency

**What it means:** Services experiencing increased latency or intermittent failures without clear error.

**Investigation Sequence:**
1. Check all pods in affected namespace for restarts and readiness
2. Check Istio ingress gateway logs for upstream errors
3. Check node pressure (CPU, memory, disk) on nodes hosting affected pods
4. Check pod resource usage vs limits via metrics-server
5. Check for noisy-neighbor pods consuming shared node resources
6. Cross-reference with CheckMK for host-level performance alerts

**Common Root Causes:**

| Root Cause | Evidence | Resolution |
|-----------|----------|------------|
| Pod CPU throttled | CPU usage at limit, request latency high | Increase CPU limits |
| Node under pressure | MemoryPressure or DiskPressure on node | Scale cluster or reduce workloads |
| Istio sidecar overhead | Latency added by Envoy proxy | Tune sidecar resources, check proxy config |
| Network saturation | CheckMK shows high network utilization | Check for bandwidth hogs, add capacity |
| Downstream dependency slow | Traces show latency in external calls | Not a K8s issue — escalate to dependency owner |
