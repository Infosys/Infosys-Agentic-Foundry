---
name: CCD Ops Environment Context
type: document
description: CCD Kubernetes cluster environment configuration, API access, and operational baselines
status: active
skills:
  - ccdops
---

# CCD Operations — Environment Context
_Last updated: 2026-04-20_

This file contains **environment-specific** configuration for the CCD Kubernetes cluster.
The agent uses this to CONNECT and EXECUTE — not to understand what K8s concepts mean
(that's in the taxonomy and exception files).

---

## Cluster Environment

| Property | Value |
|----------|-------|
| Cluster IP | `10.232.173.106:6443` |
| Platform | Rancher RKE2 v1.31.7+rke2r1 |
| Nodes | 6 (all Ready as of 2026-03-30) |
| Namespace count | 21 |
| SSL | Self-signed cert — always pass `-k` to curl |
| Team | CCD (Cloud & Container Delivery) — Infosys internal IT infra |
| Escalation path | IHD ticket → CCD on-call → platform lead → CCD head (Prakash) |
| Token refresh contact | Vinoth (CCD team) |
| Token expiry | ~2026-04-07 (HTTP 401 = expired) |

---

## Credential References

| Key | Type | Notes |
|-----|------|-------|
| `ccd_k8s_api` | bearer_token | Base URL: `https://10.232.173.106:6443`. Use `curl -sk`. Expires ~7 days. 401 = call Vinoth |
| `checkmk_api` | basic_auth | URL: `https://blrhcicmkmas.ad.infosys.com/BLR_MASTER/check_mk/api/1.0`. No expiry |
| `ccd_node_ssh` | ssh_key | Worker node SSH — TBD from CCD team |
| `ccd_kubeconfig` | kubeconfig_file | kubectl access — cluster cert TBD |

**Loading credentials:**
```bash
# Bearer token (K8s API)
get_credential ccd_k8s_api token
# → Sets $CRED_CCD_K8S_API_TOKEN — use in all subsequent curl calls

# CheckMK (basic auth)
get_credential checkmk_api username
get_credential checkmk_api password
# → Sets $CRED_CHECKMK_API_USERNAME and $CRED_CHECKMK_API_PASSWORD
```

---

## Namespace Map

| Namespace | Purpose |
|-----------|---------|
| `kube-system` | Kubernetes core: DNS, scheduler, API server, controllers |
| `istio-system` | Service mesh — Istio ingress/egress gateways, Envoy sidecars |
| `ai-gateway` | AI workloads — primary project team namespace |
| `cattle-monitoring-system` | Rancher Grafana/Prometheus monitoring stack |
| `cattle-fleet-system` | Rancher Fleet — multi-cluster management |
| `cattle-system` | Rancher management plane |
| `checkmk-monitoring` | CheckMK infrastructure monitoring agent |
| `twistlock` | Prisma Cloud / container security scanning |
| `vaultauth` | HashiCorp Vault auth — secrets management |
| `calico-system` | Calico CNI — pod networking and network policies |
| `cert-manager` | TLS certificate automation |
| `longhorn-system` | Longhorn distributed storage — PVC backend |
| `default` | Default namespace — unspecified workloads |

_Remaining 8: cattle-impersonation-system, fleet-local, kube-node-lease, kube-public, rancher-monitoring, and Rancher internal namespaces._

---

## Known Baselines (as of 2026-03-30)

| Namespace | Pod | Restarts | Status | Notes |
|-----------|-----|----------|--------|-------|
| `istio-system` | istio-ingressgateway, istiod | 4–8 | Running | Normal baseline — could be OOM or config reload. Escalate only if restarts increase sharply or latency spikes |

---

## Log Layers — Architecture

```
[Hypervisor / LB]        ← Linux VMs — SSH access, log directory
      ↓
[Worker Nodes]           ← Kubernetes nodes — SSH access, kubeadm/kubelet logs
      ↓
[Service Mesh]           ← Istio/Envoy — API access (REST + token)
      ↓
[Application Pods]       ← App-level observability — API access (REST + token)
```

---

## Triggering Sources

| Source | Description |
|--------|-------------|
| Rancher RKE2 alerts | Out-of-box alerts from the Kubernetes distribution |
| Grafana / Prometheus | Chime-based monitoring — metric thresholds and alerting |
| CheckMK | Enterprise host monitoring — PING, CPU, memory, disk, service checks on underlying VMs |
| IHD tickets | Users report cluster issues via Infosys Help Desk |
| Direct user report | Project teams (~10 per cluster) report issues to CCD team |

---

## API Patterns — Kubernetes REST API

### Verify Connectivity
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' https://10.232.173.106:6443/version
```
- Response with `gitVersion` → cluster reachable
- HTTP 401 → token expired — contact Vinoth (CCD team)
- Connection refused → check VPN / network access

### List Pods in Namespace
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  'https://10.232.173.106:6443/api/v1/namespaces/<NS>/pods' \
| python3 -c "
import json, sys
data = json.load(sys.stdin)
for pod in data.get('items', []):
    name = pod['metadata']['name']
    phase = pod['status'].get('phase', 'Unknown')
    cs = pod['status'].get('containerStatuses', [{}])
    restarts = cs[0].get('restartCount', 0) if cs else 0
    ready = cs[0].get('ready', False) if cs else False
    reason = (cs[0].get('lastState', {}).get('terminated', {}) or {}).get('reason', '') if cs else ''
    print(f'{name:60} phase={phase} restarts={restarts} ready={ready} lastReason={reason}')
"
```

### Get Pod Logs (Filtered)
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  'https://10.232.173.106:6443/api/v1/namespaces/<NS>/pods/<POD>/log?tailLines=200' \
| grep -iE 'oom|OOMKilled|error|warn|fail|exception|panic|fatal|crash|timeout'
```

### Get Previous Container Logs (After Crash)
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  'https://10.232.173.106:6443/api/v1/namespaces/<NS>/pods/<POD>/log?previous=true&tailLines=200' \
| grep -iE 'oom|OOMKilled|error|warn|fail|exception|panic|fatal|crash|timeout'
```

### Get Warning Events
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  'https://10.232.173.106:6443/api/v1/namespaces/<NS>/events' \
| python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('items', [])
warnings = [e for e in items if e.get('type') == 'Warning']
warnings_sorted = sorted(warnings, key=lambda e: e.get('lastTimestamp', ''))
print(f'Total events: {len(items)}, Warnings: {len(warnings)}')
for e in warnings_sorted[-20:]:
    print(e.get('lastTimestamp',''), e.get('reason',''), e.get('message',''))
"
```

### List Nodes & Conditions
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  https://10.232.173.106:6443/api/v1/nodes \
| python3 -c "
import json, sys
data = json.load(sys.stdin)
for node in data.get('items', []):
    name = node['metadata']['name']
    conditions = node['status'].get('conditions', [])
    for c in conditions:
        if c.get('type') in ('Ready', 'MemoryPressure', 'DiskPressure', 'PIDPressure'):
            print(f'{name:40} {c[\"type\"]:20} {c[\"status\"]:10} {c.get(\"message\",\"\")[:80]}')
"
```

### Node Metrics (Live Usage)
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  https://10.232.173.106:6443/apis/metrics.k8s.io/v1beta1/nodes/<NODE_NAME> \
| python3 -c "
import json, sys
item = json.load(sys.stdin)
print('Live CPU usage:', item['usage']['cpu'])
print('Live Memory usage:', item['usage']['memory'])
"
```

### Find Pod Across All Namespaces
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  'https://10.232.173.106:6443/api/v1/pods' \
| python3 -c "
import json, sys
data = json.load(sys.stdin)
target = '<POD_NAME_OR_PARTIAL>'
for pod in data.get('items', []):
    name = pod['metadata']['name']
    if target.lower() in name.lower():
        ns = pod['metadata']['namespace']
        phase = pod['status'].get('phase', 'Unknown')
        cs = pod['status'].get('containerStatuses', [{}])
        restarts = cs[0].get('restartCount', 0) if cs else 0
        ready = cs[0].get('ready', False) if cs else False
        print(f'ns={ns} name={name} phase={phase} restarts={restarts} ready={ready}')
"
```

### API Server Health Gates
```bash
echo '=== healthz ===' && curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' https://10.232.173.106:6443/healthz && echo
echo '=== readyz ===' && curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' https://10.232.173.106:6443/readyz && echo
echo '=== livez ===' && curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' https://10.232.173.106:6443/livez && echo
```

### Top Memory-Consuming Pods (Cluster-Wide)
```bash
curl -sk -H 'Authorization: Bearer $CRED_CCD_K8S_API_TOKEN' \
  https://10.232.173.106:6443/apis/metrics.k8s.io/v1beta1/pods \
| python3 -c "
import json, sys
def to_mi(s):
    if not s: return 0
    if s.endswith('Ki'): return int(s[:-2])//1024
    if s.endswith('Mi'): return int(s[:-2])
    if s.endswith('Gi'): return int(s[:-2])*1024
    return 0
data = json.load(sys.stdin)
rows = []
for item in data.get('items', []):
    name = item['metadata']['name']
    ns = item['metadata']['namespace']
    total_mem = sum(to_mi(c['usage'].get('memory','0')) for c in item.get('containers',[]))
    rows.append((total_mem, ns, name))
rows.sort(reverse=True)
print(f'{\"NAMESPACE\":<30} {\"POD\":<50} {\"MEMORY_Mi\":<10}')
for mem, ns, name in rows[:20]:
    print(f'{ns:<30} {name:<50} {mem} Mi')
"
```

---

## API Patterns — CheckMK (Host-Level VM Health)

⚠️ CheckMK monitors 130,000+ services. NEVER fetch without a server-side `query` filter.
⚠️ JSON query MUST use `--get --data-urlencode 'query=...'` — not inline JSON in URL.

### CRITICAL Services (Cluster-Wide)
```bash
curl -sk -u '$CRED_CHECKMK_API_USERNAME:$CRED_CHECKMK_API_PASSWORD' --get \
  --data-urlencode 'query={"op":"=","left":"state","right":"2"}' \
  'https://blrhcicmkmas.ad.infosys.com/BLR_MASTER/check_mk/api/1.0/domain-types/service/collections/all?columns=host_name&columns=description&columns=state&columns=plugin_output' \
| python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('value', [])
print(f'CRITICAL services: {len(items)}')
for v in items[:30]:
    e = v['extensions']
    print(f\"  {e['host_name']:35} | {e['description']:25} | {e['plugin_output'][:70]}\")
"
```

### All Services for a Specific Host
```bash
curl -sk -u '$CRED_CHECKMK_API_USERNAME:$CRED_CHECKMK_API_PASSWORD' --get \
  --data-urlencode 'query={"op":"=","left":"host_name","right":"<EXACT-HOSTNAME>"}' \
  'https://blrhcicmkmas.ad.infosys.com/BLR_MASTER/check_mk/api/1.0/domain-types/service/collections/all?columns=host_name&columns=description&columns=state&columns=plugin_output' \
| python3 -c "
import sys, json
data = json.load(sys.stdin)
for v in data.get('value', []):
    e = v['extensions']
    label = {0:'OK',1:'WARN',2:'CRIT',3:'UNKN'}.get(e['state'],'?')
    print(f\"  {label} | {e['description']:30} | {e['plugin_output'][:80]}\")
"
```

### CRITICAL Only for Specific Host
```bash
curl -sk -u '$CRED_CHECKMK_API_USERNAME:$CRED_CHECKMK_API_PASSWORD' --get \
  --data-urlencode 'query={"op":"and","expr":[{"op":"=","left":"host_name","right":"<HOSTNAME>"},{"op":"=","left":"state","right":"2"}]}' \
  'https://blrhcicmkmas.ad.infosys.com/BLR_MASTER/check_mk/api/1.0/domain-types/service/collections/all?columns=host_name&columns=description&columns=state&columns=plugin_output' \
| python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('value', [])
print(f'CRITICAL on host: {len(items)}')
for v in items:
    e = v['extensions']
    print(f\"  {e['description']:30} | {e['plugin_output'][:80]}\")
"
```

### When to Use CheckMK vs K8s API

| Scenario | Use |
|----------|-----|
| Pod OOMKilled / MemoryPressure | CheckMK → confirm host memory CRITICAL |
| Node NotReady | CheckMK → check PING + disk + memory on that host |
| CrashLoopBackOff (no clear K8s cause) | CheckMK → look for process or service failures on VM |
| ImagePullBackOff / network issues | CheckMK → verify host network reachability (PING) |
| Pod scheduling failure | K8s API first — CheckMK only if node conditions unclear |

---

## Error Reference

| HTTP | Meaning | Action |
|------|---------|--------|
| 200 | OK | Parse response |
| 401 | Unauthorized | Token expired — contact CCD team (Vinoth) for new token |
| 403 | Forbidden | Service account lacks RBAC for this resource |
| 404 | Not found | Wrong namespace or pod name |
| 503 | Service unavailable | API server down or unreachable |

---

## Confirmed Knowledge
<!-- auto-generated – do not edit this section manually -->

### [2026-04-24] Before executing file-based hooks, validate file existence and correct path.
**Type**: exception | **Skill**: — | **ID**: k_20260422_928a0ac05d46
**Applies when**: —
> Before executing file-based hooks, validate file existence and correct path.
