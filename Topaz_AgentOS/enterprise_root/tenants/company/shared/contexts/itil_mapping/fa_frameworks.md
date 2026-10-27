---
name: Finance & Accounting Framework Mapping
type: framework_mapping
description: APQC PCF process IDs mapped to internal F&A process codes, industry equivalents, and compliance frameworks
status: active
skills: []
---

# Finance & Accounting — Framework Mapping
_Last updated: 2026-04-24_

This file maps the **APQC PCF (Process Classification Framework)** identifiers used in the taxonomy to internal process codes, and cross-references relevant compliance and reporting frameworks. Use this when the agent needs to translate between external framework terminology and internal process names.

---

## APQC PCF — Finance & Accounting Reference

APQC PCF Category 9: **Manage Financial Resources**
APQC PCF Category 11: **Manage Enterprise Risk, Compliance, Remediation, and Resiliency**

| APQC ID | APQC Process Name | Internal L2 Domain | Internal L3 Label | Notes |
|---|---|---|---|---|
| **9.1.1** | Perform planning/budgeting/forecasting | FP&A | Budgeting, Planning & Forecasting | Future domain — not yet active in 8081 |
| **9.1.2** | Perform cost accounting and control | GL | Cost Accounting | Active — Profit Centre Accounting |
| **9.1.3** | Perform cost management | GL | Cost Accounting | Active — allocation cycles |
| **9.1.4** | Evaluate and manage financial performance | FP&A | Decision Support | Future domain |
| **9.2.1** | Process customer credit | AR | Credit Risk | Active |
| **9.2.2** | Invoice customer | AR | Customer Billing | Active |
| **9.2.3** | Process accounts receivable (AR) | AR | AR Regular Activities / Cash Application | Active |
| **9.2.4** | Manage and process collections | AR | Collections | Active |
| **9.2.5** | Manage and process adjustments/deductions | AR | Deductions Accounting | Active |
| **9.3.1** | Manage policies and procedures | GL | Accounting Policy | Active — GL Regular Activities |
| **9.3.2** | Perform general accounting | GL | General Ledger Accounting / Closing | Active |
| **9.3.3** | Perform fixed-asset accounting | GL | Fixed Assets | Partial — covered under GL Accounting / FA Processing |
| **9.3.4** | Perform financial reporting | GL | Period End Reporting / Consolidation | Active |
| **9.4.1** | Perform capital planning and project approval | GL | Revenue Recognition (Projects) | Active — Project Accounting |
| **9.4.2** | Perform capital project accounting | GL | Revenue Recognition (Products/Services) | Active |
| **9.6.1** | Process accounts payable (AP) | AP | Invoice Processing / Payment | Active |
| **9.6.2** | Process expense reimbursements | AP | T&E Processing | Active |
| **9.7.1** | Manage treasury policies and procedures | GL | Treasury & Cash Transactions | Active — policy layer |
| **9.7.2** | Manage cash | GL | Treasury & Cash Transactions | Active |
| **9.7.3** | Manage in-house bank accounts | GL | Treasury & Cash Transactions | Active |
| **9.8.1** | Establish internal controls, policies, procedures | GL/Compliance | Control / Internal Audit | Future domain |
| **9.8.2** | Operate controls and monitor compliance | GL/Compliance | Audit | Future domain |
| **9.8.3** | Report on internal controls compliance | GL/Compliance | Compliance Reporting | Future domain |
| **9.9.1** | Develop tax strategy and plan | Tax | Tax Strategy | Future domain |
| **9.9.2** | Process taxes | GL | Tax & Statutory Accounting | Active |
| **11.1** | Manage enterprise risk | Risk | Enterprise Risk | Future domain |

---

## Internal Process Code Mapping

> Replace these placeholders with your organisation's internal process reference codes (e.g. SAP Solution Manager IDs, SharePoint process library codes, or internal procedure document numbers).

| Internal Code | Process Name | APQC ID | Owner Role |
|---|---|---|---|
| FA-AP-001 | Vendor Master Management | 9.6.1 | AP Manager |
| FA-AP-002 | Invoice Receipt & Scanning | 9.6.1 | AP Team |
| FA-AP-003 | Invoice Processing & Matching | 9.6.1 | AP Team |
| FA-AP-004 | E-Invoice Processing | 9.6.1 | AP Team / IT |
| FA-AP-005 | Invoice Authorization & Approval | 9.6.1 | Cost Centre Managers / AP Manager |
| FA-AP-006 | Invoice Payment & Disbursement | 9.6.1 | Treasury / AP Manager |
| FA-AP-007 | T&E Processing | 9.6.2 | AP Team / HR |
| FA-AP-008 | Vendor Query Management | 9.6.1 | AP Team |
| FA-AR-001 | Customer Master Management | 9.2.3 | AR Manager |
| FA-AR-002 | Credit Risk Management | 9.2.1 | Credit Manager |
| FA-AR-003 | Customer Billing & Invoicing | 9.2.2 | AR Team / Billing |
| FA-AR-004 | Collections | 9.2.4 | Collections Team |
| FA-AR-005 | Cash Application | 9.2.3 | AR Team |
| FA-AR-006 | Deductions Accounting | 9.2.5 | AR Team |
| FA-GL-001 | GL Master Data Management | 9.3.2 | GL Team / Finance Manager |
| FA-GL-002 | Journal Entry Processing | 9.3.2 | GL Accountants |
| FA-GL-003 | Balance Sheet Reconciliation | 9.3.2 | GL Accountants |
| FA-GL-004 | GR/IR Clearing | 9.3.2 | GL / Procurement Finance |
| FA-GL-005 | Intercompany Processing | 9.3.2 | GL / Controller |
| FA-GL-006 | Fixed Asset Accounting | 9.3.3 | Fixed Assets Accountant |
| FA-GL-007 | Month/Quarter/Year End Close | 9.3.2 | Controller |
| FA-GL-008 | Period End Reporting | 9.3.4 | Finance Manager / Controller |
| FA-GL-009 | Consolidation Reporting | 9.3.4 | Group Controller |
| FA-GL-010 | Tax & Statutory Accounting | 9.9.2 | Tax Accountant |
| FA-GL-011 | Treasury & Cash Management | 9.7.2 | Treasurer |

---

## Compliance & Regulatory Framework Cross-Reference

| Standard / Regulation | Relevance to F&A | Applicable Process |
|---|---|---|
| **IFRS (International Financial Reporting Standards)** | Primary reporting standard — recognition, measurement, disclosure | GL Accounting, Close, Consolidation |
| **US GAAP** | Alternative reporting standard (if applicable) | GL Accounting, Revenue Recognition |
| **Local GAAP** | Statutory reporting in each jurisdiction | Tax & Statutory, Statutory Close |
| **SOX (Sarbanes-Oxley)** | Internal controls over financial reporting | JE approvals, reconciliations, segregation of duties |
| **EU VAT Directive** | VAT compliance across EU member states | AP tax coding, AR invoicing, VAT returns |
| **GDPR** | Data protection for customer/vendor personal data in financial records | Customer/vendor master data, invoice archive |
| **BEPS (Base Erosion & Profit Shifting — OECD)** | Transfer pricing, country-by-country reporting | Intercompany invoicing, CIT return |
| **IFRS 15 (Revenue Recognition)** | 5-step model for revenue from contracts with customers | Customer Billing, Revenue Recognition |
| **IFRS 9 (Financial Instruments)** | ECL model for bad debt provisioning | Collections, Credit Risk, AR write-offs |
| **IFRS 16 (Leases)** | On-balance-sheet treatment for leases | Fixed Assets, GL Accounting |
| **Intrastat / Extrastat (EU)** | Statistical reporting of goods trade within/outside EU | Tax & Statutory |

---

## Glossary — Key F&A Terms Used in This Taxonomy

| Term | Definition |
|---|---|
| **3-Way Match** | Matching of purchase order, goods receipt, and vendor invoice before payment |
| **2-Way Match** | Matching of purchase order and vendor invoice (no goods receipt — services) |
| **DOA** | Delegation of Authority — defines who can approve transactions up to what value |
| **SoD** | Segregation of Duties — ensures no single person controls an entire process end-to-end |
| **DPO** | Days Payable Outstanding — average days to pay suppliers |
| **DSO** | Days Sales Outstanding — average days to collect from customers |
| **GR/IR** | Goods Receipt / Invoice Receipt — clearing account reconciling goods received vs. invoices processed |
| **PCA** | Profit Centre Accounting — allocation of costs/revenues to profit centres |
| **ECL** | Expected Credit Loss — IFRS 9 model for provisioning AR doubtful debts |
| **VSOE** | Vendor-Specific Objective Evidence — US GAAP concept for software revenue recognition |
| **Hard Close** | Period lock — no further postings allowed without CFO approval |
| **Soft Close** | Preliminary close — adjustments still permitted within defined window |
| **Top-Side JE** | Journal entry posted at group consolidation level, not in entity ledger |
| **IC** | Intercompany — transactions between entities within the same group |
| **T&E** | Travel & Expenses — employee reimbursement process |
| **PBC** | Prepared By Client — documents provided to external auditors |
| **CIT** | Corporate Income Tax |
| **VAT** | Value Added Tax (equivalent: GST in some jurisdictions) |
| **APQC PCF** | APQC Process Classification Framework — industry-standard process taxonomy for benchmarking |
