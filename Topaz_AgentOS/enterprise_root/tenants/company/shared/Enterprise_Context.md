---
name: Enterprise Context
type: root
description: Master routing index for Finance & Accounting and IT Operations ContextOS
status: active
skills:
  - fa_ap
  - fa_ar
  - fa_gl
  - ccdops
  - general
---

# Enterprise Context
Governance: Finance & Accounting · CCD Operations | Compliance: IFRS, SOX, ITIL v4, CAB
_Last updated: 2026-04-24_

This is the **master index**. Read this file first, then follow the pointers to the
relevant context files based on the user's query. Do NOT answer from memory.

All knowledge lives under `/shared/contexts/`. This file sits outside as the root router.
OKF-style agent knowledge bundles live under `/shared/knowledge/`; start with
`/shared/knowledge/finance_ap/index.md` for Accounts Payable invoice, vendor,
PO, payment, and three-way-match investigations.
Knowledge bundles are discovered by convention: any `/shared/knowledge/<bundle_id>/`
folder with `manifest.yaml` (`kind: knowledge_bundle`) and `index.md` can receive
approved learning records by skill/tag match. This file remains the routing map;
bundle manifests own domain wiki write targets.

---

## ⚡ ACTIVE RUNTIME ENVIRONMENT — authoritative live endpoints (use these; ignore memorized URLs)

> These are the **only reachable** data systems in THIS environment. If past
> tool-call memory suggests a different host/port (e.g. `:8080`, `192.168.x.x:9091`,
> SAP OData), it is **stale — ignore it.** Always use the endpoints below.

- **Finance API (invoices, vendors, POs, payments):** `http://localhost:9092`
  - Auth header (required): `X-API-Key: read_demo_key_abc123`
  - Single invoice: `GET /invoices/<INVOICE_ID>` · all: `GET /invoices` · health: `GET /health`
  - Example: `curl -s -H "X-API-Key: read_demo_key_abc123" http://localhost:9092/invoices/INV-3040`
- **AP / AR databases (read-only):** use `run_sql_query` with virtual paths
  `/shared/databases/ap_regular.db` (AP) and `/shared/databases/ar_receivables.db` (AR).
  Full schemas in `/shared/databases/_index.md`.
- To **change** an invoice's state (approve/pay/hold), use `request_human_approval` — the databases are read-only.

For full F&A system detail see the **ACTIVE SYSTEMS** section of `contexts/fa_environment.md`.
For AP-specific agent knowledge see [`knowledge/finance_ap/index.md`](knowledge/finance_ap/index.md).

---

## L1: Finance & Accounting

### L2 Process Map

| Process | Aliases | Skill | Environment | Taxonomy | Exceptions | Benchmarks | Judgment | Framework |
|---------|---------|-------|-------------|----------|------------|------------|----------|-----------|
| Accounts Payable | AP, invoice processing, vendor invoice, PO matching, 3-way match, GR/IR, vendor master, vendor onboarding, payment run, payment authorisation, DPO, duplicate invoice, maverick spend, T&E, expense reimbursement, e-invoice, SEPA, payment terms, AP close, procure to pay, PtP, APQC 9.6 | fa_ap | `contexts/fa_environment.md` | `contexts/taxonomy/fa_taxonomy.md` | `contexts/exceptions/fa_exceptions.md` | `contexts/benchmarks/fa_benchmarks.md` | `contexts/judgment/fa_judgment.md` | `contexts/itil_mapping/fa_frameworks.md` |
| Accounts Receivable | AR, invoice status, customer invoice, customer payment, customer portal, remittance advice, DSO, collections, dunning, credit hold, cash application, unmatched payment, customer dispute, next best action, NBA, AR aging, overdue invoice, bad debt, write-off, customer billing, deductions, order to cash, OtC, APQC 9.2 | fa_ar | `contexts/fa_environment.md` | `contexts/taxonomy/fa_taxonomy.md` | `contexts/exceptions/fa_exceptions.md` | `contexts/benchmarks/fa_benchmarks.md` | `contexts/judgment/fa_judgment.md` | `contexts/itil_mapping/fa_frameworks.md` |
| General Ledger / Record-to-Report | GL, RtR, period close, month end, year end, hard close, soft close, journal entry, JE, balance sheet reconciliation, trial balance, intercompany, IC reconciliation, GR/IR clearing, accruals, forex revaluation, consolidation, VAT return, CIT return, deferred tax, chart of accounts, cost centre, profit centre, close calendar, management pack, APQC 9.3, APQC 9.9 | fa_gl | `contexts/fa_environment.md` | `contexts/taxonomy/fa_taxonomy.md` | `contexts/exceptions/fa_exceptions.md` | `contexts/benchmarks/fa_benchmarks.md` | `contexts/judgment/fa_judgment.md` | `contexts/itil_mapping/fa_frameworks.md` |

---

### F&A Routing Instructions

#### Step 1: Identify the F&A subdomain

| If the query mentions… | Subdomain | Skill |
|------------------------|-----------|-------|
| invoice processing, vendor invoice, PO matching, 3-way match, payment run, vendor master, T&E, DPO | Accounts Payable | `fa_ap` |
| invoice status, customer portal, customer payment, overdue invoice, collections, cash application, DSO, next best action | Accounts Receivable | `fa_ar` |
| period close, month end, journal entry, reconciliation, trial balance, intercompany, accruals, VAT return, CIT return | General Ledger | `fa_gl` |
| who approves? DOA? approval authority? | Any F&A | `contexts/judgment/fa_judgment.md` → DOA matrix |
| SLA breach? KPI below target? close day? | Any F&A | `contexts/benchmarks/fa_benchmarks.md` |

#### Step 2: Load F&A context files in order

1. **Environment** → `contexts/fa_environment.md` (ERP config, company codes, chart of accounts, fiscal calendar)
2. **Taxonomy** → `contexts/taxonomy/fa_taxonomy.md` (find the L3→L5 activity; APQC PCF tag)
3. **Exceptions** → `contexts/exceptions/fa_exceptions.md` (exception patterns, root causes, escalation triggers)
4. **Benchmarks** → `contexts/benchmarks/fa_benchmarks.md` (SLA targets, KPI thresholds, close calendar)
5. **Judgment** → `contexts/judgment/fa_judgment.md` (approval authority, DOA matrix, escalation rules)
6. **Frameworks** → `contexts/itil_mapping/fa_frameworks.md` (APQC PCF mapping, IFRS/SOX, glossary)

#### Step 3: AR multi-source investigation (fa_ar only)

When handling invoice status queries, always check **all four sources** before recommending action:
1. ERP AR subledger — open/cleared status, days overdue, credit hold flag
2. Customer portal — portal status, expected payment date, rejection reason
3. Email / remittance inbox — remittance advice, dispute notifications
4. Bank statement — payment received but unmatched

---

### F&A Context File Inventory

| File | Type | Description |
|------|------|-------------|
| `knowledge/finance_ap/index.md` | Knowledge bundle | OKF-style AP entry point linking databases, APIs, tables, metrics, policies, and runbooks |
| `contexts/fa_environment.md` | Environment | ERP config, company codes, chart of accounts, fiscal calendar, payment and banking config |
| `contexts/taxonomy/fa_taxonomy.md` | Taxonomy | L1→L5 F&A process hierarchy (AP/AR/GL) with APQC PCF tags and pillar file links |
| `contexts/exceptions/fa_exceptions.md` | Exceptions | AP, AR, GL exception patterns: root cause, agent action, escalation trigger |
| `contexts/benchmarks/fa_benchmarks.md` | Benchmarks | DPO/DSO targets, invoice SLAs, close calendar, KPI alert thresholds |
| `contexts/judgment/fa_judgment.md` | Judgment | DOA approval matrix, SoD rules, collections escalation ladder, hard/soft close policy |
| `contexts/itil_mapping/fa_frameworks.md` | Framework | APQC PCF mapping, internal process codes, IFRS/SOX/GDPR cross-reference, F&A glossary |

---

## L1: IT Operations

### L2 Process Map

| Process | Aliases | Skills | Context | Taxonomy | Exceptions | Benchmarks | Judgment | ITIL Map |
|---------|---------|--------|---------|----------|------------|------------|----------|----------|
| Container Orchestration (K8s) | CCD, CCD ops, Kubernetes, K8s, cluster, pod, kubelet, node, namespace, service mesh, Rancher, RKE2, Istio, container, pod crash, OOM, CrashLoopBackOff, node not ready, pod pending, KaaS, cluster issue, pod logs, worker node, hypervisor, Grafana, Prometheus, Chime, CheckMK | ccdops | `contexts/ccdops_context.md` | `contexts/taxonomy/it_ops_taxonomy.md` | `contexts/exceptions/k8s_pod_exceptions.md`, `contexts/exceptions/k8s_node_exceptions.md`, `contexts/exceptions/k8s_network_exceptions.md` | `contexts/benchmarks/k8s_health_benchmarks.md` | `contexts/judgment/k8s_escalation_rules.md` | `contexts/itil_mapping/it_ops_itil_mapping.md` |
| Cloud Infrastructure | AWS, Azure, GCP, VM, EC2, S3, IaaS, cloud infra | — | _Future_ | — | — | — | — | — |
| Network Operations | firewall, DNS, load balancer, VPN, routing, switching | — | _Future_ | — | — | — | — | — |
| Database Operations | Oracle DB, PostgreSQL, MySQL, backup, replication, DBA | — | _Future_ | — | — | — | — | — |

---

### IT Operations Routing Instructions

#### Step 1: Identify the L2 domain

| If the query mentions… | L2 Domain | Start with… |
|------------------------|-----------|-------------|
| pod, cluster, namespace, kubelet, node, K8s, Kubernetes | Container Orchestration | `contexts/ccdops_context.md` |
| CrashLoopBackOff, OOMKilled, ImagePullBackOff, pod pending, node not ready | Container Orchestration | `contexts/ccdops_context.md` + relevant exception file |
| service mesh, Istio, Envoy, sidecar, mTLS, ingress gateway | Container Orchestration | `contexts/ccdops_context.md` + `contexts/exceptions/k8s_network_exceptions.md` |
| Rancher, RKE2, cluster upgrade, node drain | Container Orchestration | `contexts/ccdops_context.md` |
| CCD team, CCD ops, KaaS, Infosys cluster | Container Orchestration | `contexts/ccdops_context.md` |
| CheckMK, host check, PING CRITICAL | Container Orchestration | `contexts/ccdops_context.md` (CheckMK API section) |
| health check, cluster health, capacity review | Container Orchestration | `contexts/benchmarks/k8s_health_benchmarks.md` |
| escalation, severity, approval, should I fix this | Container Orchestration | `contexts/judgment/k8s_escalation_rules.md` |
| ITIL, incident count, change count, practice report | Any | `contexts/itil_mapping/it_ops_itil_mapping.md` |

#### Step 2: Load IT Ops context files in order

1. **Environment context** → `contexts/ccdops_context.md` (cluster config, creds, API patterns)
2. **Taxonomy** → `contexts/taxonomy/it_ops_taxonomy.md` (find the L3→L5 activity)
3. **Exception playbook** → `contexts/exceptions/k8s_*.md` (if it's a known error pattern)
4. **Benchmarks** → `contexts/benchmarks/k8s_health_benchmarks.md` (thresholds, MTTR targets)
5. **Judgment** → `contexts/judgment/k8s_escalation_rules.md` (approve/escalate/auto-fix decision)
6. **ITIL mapping** → `contexts/itil_mapping/it_ops_itil_mapping.md` (only for ITIL-oriented reports)

#### Step 3: If unsure
- Read the aliases column in the L2 Process Map above
- Match the most aliases to determine the domain
- When in doubt, start with `contexts/ccdops_context.md` — it covers the only active L2

---

### IT Operations Context File Inventory

| File | Type | Description |
|------|------|-------------|
| `contexts/ccdops_context.md` | Environment | Cluster config, credentials, namespaces, API patterns, baselines |
| `contexts/taxonomy/it_ops_taxonomy.md` | Taxonomy | L1→L5 hierarchy with ITIL tags, MTTR targets, severity |
| `contexts/exceptions/k8s_pod_exceptions.md` | Exceptions | Pod failure patterns: CrashLoop, OOM, ImagePull, Pending, Evicted |
| `contexts/exceptions/k8s_node_exceptions.md` | Exceptions | Node failure patterns: NotReady, MemoryPressure, DiskPressure, PIDPressure |
| `contexts/exceptions/k8s_network_exceptions.md` | Exceptions | Network/mesh patterns: Istio, DNS, mTLS, ingress, service discovery |
| `contexts/benchmarks/k8s_health_benchmarks.md` | Benchmarks | Alert thresholds, MTTR targets, capacity baselines, availability SLAs |
| `contexts/judgment/k8s_escalation_rules.md` | Judgment | Severity classification, approval gates, escalation tree, auto-fix rules |
| `contexts/itil_mapping/it_ops_itil_mapping.md` | ITIL Mapping | L5 activities cross-referenced to ITIL v4 practices |
