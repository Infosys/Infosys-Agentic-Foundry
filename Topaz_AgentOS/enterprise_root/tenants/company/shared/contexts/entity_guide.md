---
name: Entity Guide — Known Entities & Aliases
type: entity_guide
description: Canonical entity reference for the router LLM — maps aliases and informal names to canonical entity names and IDs
status: active
---

# Entity Guide — Known Entities & Aliases

This file is injected into the skill router prompt at query time. Its purpose is to help the
router LLM consistently identify a named entity mentioned in a user query and output the
correct canonical `entity_name` in its JSON response.

**How to use this file:**
- When the user query mentions any alias listed below, output the corresponding `canonical_name`
  as `entity_name` in the routing JSON.
- Always normalise to the canonical name — never output an alias or shorthand.
- If the user mentions an entity not listed here, extract its name verbatim.

---

## 1. Customers (AR / Collections)

These are external companies that receive invoices from Acme Technologies. Queries about
invoice status, payment chasing, credit hold, or dispute resolution usually reference one
of these customers.

| Canonical Name | ID | Aliases | Entity Type | Skill |
|---|---|---|---|---|

> No example customers are seeded by default. Add tenant-specific customer rows here
> (Canonical Name / ID / Aliases / Entity Type / Skill) and a matching entity file under
> `contexts/entities/` to extend AR routing for real customers.

---

## 2. Legal Entities / Company Codes (GL / AP)

These are Acme Technologies' own legal entities. Queries about period close, journal entries,
intercompany, or postings to a specific company code reference these.

| Canonical Name | ID | Aliases | Entity Type | Skill |
|---|---|---|---|---|
| Acme Technologies Ltd | CC_001 | CC001, UK entity, GBP entity, UK company code, Acme UK | company_code | fa_gl |
| Acme Technologies GmbH | CC_002 | CC002, DE entity, EUR entity, German entity, Acme Germany | company_code | fa_gl |

---

## 3. Financial Systems & Platforms (AP / AR / GL)

These are the ERP and peripheral systems used in finance operations. Queries about invoice
posting errors, ERP connectivity, portal access, or document archive reference these.

| Canonical Name | ID | Aliases | Entity Type | Skill |
|---|---|---|---|---|
| SAP S/4HANA | ERP_001 | SAP, ERP, S4HANA, S/4, SAP ERP, primary ERP, SAP system | erp_system | fa_ap, fa_gl |
| Ariba Network | PORTAL_001 | Ariba, SAP Ariba, Ariba supplier portal | invoice_portal | fa_ar, fa_ap |
| Tungsten Network | PORTAL_002 | Tungsten, OB10, Tungsten/OB10, e-invoicing portal | invoice_portal | fa_ar, fa_ap |
| Basware | PORTAL_003 | Basware portal, Basware supplier | invoice_portal | fa_ar |
| Coupa Supplier Portal | PORTAL_004 | Coupa, CSP, Coupa portal | invoice_portal | fa_ar |
| SAP Business Network | PORTAL_005 | SAP Business Network, SBN, SAP supplier portal | invoice_portal | fa_ar |
| Proactis | PORTAL_006 | Proactis portal, Proactis supplier | invoice_portal | fa_ar |
| OpenText | ARCH_001 | OpenText, document archive, DMS, content server | document_archive | fa_ap, fa_gl |
| Tungsten Peppol | EINV_001 | Peppol, e-invoice platform, Tungsten Peppol, UBL 2.1 | einvoicing | fa_ap |
| SAP Concur | EXPM_001 | Concur, expense system, T&E system, expense management | expense_system | fa_ap |
| SAP Analytics Cloud | BI_001 | SAC, BI system, reporting system, analytics | bi_system | fa_gl |
| SAP BPC | CONS_001 | BPC, consolidation tool, group consolidation | consolidation | fa_gl |

---

## 4. IT Infrastructure — Cluster & Platform (CCD Ops)

This is the Infosys CCD Kubernetes cluster. Queries about pods, nodes, workloads, or
cluster health reference this environment.

| Canonical Name | ID | Aliases | Entity Type | Skill |
|---|---|---|---|---|
| CCD Kubernetes Cluster | INFRA_K8S_001 | CCD cluster, K8s cluster, RKE2 cluster, Rancher cluster, Kubernetes, 10.232.173.106 | k8s_cluster | ccdops |
| Rancher | INFRA_K8S_002 | Rancher, Rancher management plane, Rancher server, cattle-system | k8s_platform | ccdops |
| Istio Service Mesh | INFRA_K8S_003 | Istio, service mesh, istio-system, Envoy, sidecar | service_mesh | ccdops |
| Istio Ingress Gateway | INFRA_K8S_004 | Ingress gateway, istio-ingressgateway, ingress, gateway | ingress | ccdops |
| CoreDNS | INFRA_K8S_005 | CoreDNS, DNS, kube-dns, DNS resolution, service discovery | dns | ccdops |
| Calico CNI | INFRA_K8S_006 | Calico, CNI, network plugin, pod networking, calico-system | cni | ccdops |
| Longhorn Storage | INFRA_K8S_007 | Longhorn, PVC backend, distributed storage, longhorn-system | storage | ccdops |
| Cert Manager | INFRA_K8S_008 | cert-manager, TLS automation, certificate manager | tls | ccdops |
| HashiCorp Vault | INFRA_K8S_009 | Vault, vaultauth, secrets management, Vault auth | secrets | ccdops |
| Prisma Cloud | INFRA_K8S_010 | Prisma, Twistlock, container security, twistlock namespace | security | ccdops |

---

## 5. IT Monitoring Systems (CCD Ops)

Monitoring and alerting platforms used to observe the cluster and underlying VMs.

| Canonical Name | ID | Aliases | Entity Type | Skill |
|---|---|---|---|---|
| CheckMK | MON_001 | CheckMK, Check MK, CMK, host monitoring, blrhcicmkmas | monitoring | ccdops |
| Grafana | MON_002 | Grafana, Grafana dashboard, cattle-monitoring-system | monitoring | ccdops |
| Prometheus | MON_003 | Prometheus, metrics, prom, scrape | monitoring | ccdops |
| PagerDuty | MON_004 | PagerDuty, PD alert, on-call alert | alerting | ccdops |
| Chime | MON_005 | Chime, Chime alert, Grafana Chime | alerting | ccdops |

---

## 6. Kubernetes Namespaces (CCD Ops)

Namespaces in the CCD cluster. A query that names a namespace is scoped to that namespace's
workloads — always include the namespace in entity_name when the user specifies it.

| Canonical Name | ID | Aliases | Entity Type | Skill |
|---|---|---|---|---|
| ai-gateway namespace | NS_001 | ai-gateway, AI gateway, AI workloads namespace | k8s_namespace | ccdops |
| kube-system namespace | NS_002 | kube-system, Kubernetes system, core system namespace | k8s_namespace | ccdops |
| istio-system namespace | NS_003 | istio-system, Istio namespace, mesh namespace | k8s_namespace | ccdops |
| cattle-monitoring-system namespace | NS_004 | cattle-monitoring-system, monitoring namespace, Prometheus namespace | k8s_namespace | ccdops |
| cattle-system namespace | NS_005 | cattle-system, Rancher namespace | k8s_namespace | ccdops |
| checkmk-monitoring namespace | NS_006 | checkmk-monitoring, CheckMK namespace | k8s_namespace | ccdops |
| calico-system namespace | NS_007 | calico-system, Calico namespace | k8s_namespace | ccdops |
| longhorn-system namespace | NS_008 | longhorn-system, Longhorn namespace, storage namespace | k8s_namespace | ccdops |
| vaultauth namespace | NS_009 | vaultauth, Vault namespace, secrets namespace | k8s_namespace | ccdops |

---

## Notes for the Router LLM

1. **Partial matches are fine** — if the user says "Northfield" or "NF", output `entity_name: "Northfield Foods Corporation"`.
2. **Namespace vs. service** — if the user mentions a namespace by name (e.g. "ai-gateway"), output the namespace as the entity.
3. **Vendor queries in AP** — vendor names (suppliers that send invoices to Acme) are not listed here because they come from the ERP at runtime. If the user asks about a vendor not listed above, extract the name verbatim.
4. **Unknown entities** — if you cannot match to any entry above, still extract the name verbatim. Do not output null just because it isn't listed.
5. **Cross-domain queries** — a query can mention both a customer (AR) and a namespace (ccdops). Extract the most specific entity relevant to the primary question, or the one the user emphasises.

---

## Relationships (world-model edges)

> Directed edges between the entities above. Seeded into the `process_relationships`
> graph table at startup (idempotent). `From`/`To` accept a **canonical name** (slugified
> to the same `entity:<slug>` id as the tables above) or a full node_id. The agent reads
> these by querying the read-only `graph` resource with `run_sql_query` — see
> `/shared/knowledge/finance_ap/databases/graph.md`. Both endpoints must exist as an
> entity above (FK); edges to unknown nodes are skipped at seed time.

| From | Relation | To | Condition | Note |
|---|---|---|---|---|
| Ariba Network | POSTS_TO | SAP S/4HANA |  | Portal-received invoices post to the ERP |
| Acme Technologies Ltd | POSTS_TO | SAP S/4HANA |  | Company-code postings land in the ERP |

Example multi-hop the graph can answer once customer rows are seeded: *&lt;Customer&gt; → SUBMITS_VIA → Ariba Network → POSTS_TO → SAP S/4HANA* (which ERP is exposed if the customer's portal has an issue).
