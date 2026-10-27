---
name: Finance & Accounting Benchmarks
type: benchmarks
description: SLA targets, KPI thresholds, and close day targets for AP, AR, and GL processes
status: active
skills: []
---

# Finance & Accounting — Benchmarks & SLA Targets
_Last updated: 2026-04-24_

This file defines **benchmark targets** — SLA cycle times, KPI thresholds, and close day targets — for each F&A subprocess. The agent uses these to assess whether a process is within normal operating range, flag SLA breaches, and prioritise actions during close periods.

> All targets represent **standard operational benchmarks**. Actual customer-specific targets are configured in the tenant environment file (`fa_environment.md`).

---

## L1: Finance & Accounting — Enterprise KPIs

| KPI | Definition | Target | Alert Threshold |
|---|---|---|---|
| Month-end close cycle | Calendar days from period end to management accounts issued | ≤ 5 business days | > 6 business days |
| Year-end close cycle | Calendar days from year end to audited financials signed | ≤ 90 calendar days | > 100 calendar days |
| Financial restatement rate | Restatements as % of periods reported | 0% | Any restatement triggers review |
| Audit findings — high severity | Number of high-severity audit findings per year | 0 | ≥ 1 |

---

## L2: Accounts Payable

### AP KPIs

| KPI | Definition | Target | Alert Threshold |
|---|---|---|---|
| DPO (Days Payable Outstanding) | Avg days to pay invoices from receipt | 35–45 days | < 20 days (early payment leakage) or > 60 days (late payment risk) |
| Invoice processing cycle time | Hours from invoice receipt to ready-for-payment | ≤ 48 hours | > 72 hours |
| First-pass match rate | % invoices matched to PO/GR without exception | ≥ 85% | < 75% |
| On-time payment rate | % invoices paid within agreed vendor terms | ≥ 95% | < 90% |
| Duplicate invoice rate | % invoices flagged as duplicates | < 0.5% | > 1% |
| Invoice exception rate | % invoices requiring manual intervention | < 15% | > 25% |
| Vendor query resolution time | Hours to resolve a vendor query | ≤ 24 hours | > 48 hours |

---

### Master Data SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| New vendor master creation | 2 business days from approved request | > 3 business days |
| Vendor master update (bank details) | Same business day — high security priority | > 4 hours |
| Vendor master deactivation | 1 business day from approved request | > 2 business days |

---

### Invoice Receipt SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Physical invoice to scanning queue | Same business day as receipt | > 1 business day |
| Invoice scan to ERP queue | Same business day as scanning | > 1 business day |
| E-invoice receipt to processing queue | Within 1 hour (automated) | > 4 hours |

---

### Invoice Processing SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Invoice indexed and vendor confirmed | ≤ 4 hours from entry to queue | > 8 hours |
| 2/3-way matching completed | ≤ 24 hours from indexing | > 48 hours |
| Invoice exception resolved | ≤ 48 hours from exception raised | > 72 hours |
| Account coding assigned | ≤ 24 hours from routing to cost centre owner | > 48 hours |
| Invoice released for payment | ≤ 48 hours from coding approval | > 72 hours |

---

### Invoice Authorization SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Invoice approval (standard) | ≤ 48 hours from routing to approver | > 72 hours |
| Invoice approval (urgent / close period) | ≤ 4 hours from routing | > 8 hours |
| Chasing overdue approver — first reminder | 24 hours after SLA breach | — |
| Chasing overdue approver — escalation | 48 hours after first reminder | — |

---

### Payment Processing SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Payment proposal to payment release | ≤ 1 business day | > 2 business days |
| Urgent/rush payment processing | ≤ 4 hours from approval | > 6 hours |
| Bank rejection resolution | Same business day as rejection received | > 1 business day |
| Prepayment processing | ≤ 1 business day from approval | > 2 business days |

---

### AP Regular Activity SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| AP subledger review (monthly) | By close day 2 | After close day 3 |
| Debit balance report to customer | Monthly within 5 business days of period end | > 7 business days |

---

## L2: Accounts Receivable

### AR KPIs

| KPI | Definition | Target | Alert Threshold |
|---|---|---|---|
| DSO (Days Sales Outstanding) | Avg days from invoice issue to cash receipt | ≤ 35 days | > 45 days |
| Collection rate | % of invoiced value collected within payment terms | ≥ 95% | < 90% |
| Cash application rate | % payments matched automatically | ≥ 90% | < 80% |
| Overdue AR as % of total AR | Value of invoices past due / total AR balance | < 10% | > 15% |
| Bad debt write-off rate | Write-offs as % of revenue | < 0.5% | > 1% |
| Credit note rate | Credit notes issued as % of invoices | < 3% | > 5% |

---

### Master Data SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| New customer master creation | 2 business days from approved request + credit check | > 3 business days |
| Customer credit limit review (periodic) | Quarterly | > 4 months since last review |
| Customer master deactivation | 1 business day from approved request | > 2 business days |

---

### Credit Management SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Credit limit assessment — new customer | 2 business days from application | > 3 business days |
| Credit hold application | Same business day as trigger condition met | > 4 hours |
| Credit hold release (payment confirmed) | Within 4 hours of payment confirmation | > 1 business day |
| Annual credit limit review | Completed by Q1 each fiscal year | > 1 month past due |

---

### Billing SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Invoice generation from despatch/delivery | ≤ 1 business day | > 2 business days |
| Invoice transmission to customer | ≤ 4 hours from generation | > 1 business day |
| Credit note issuance from approved request | ≤ 1 business day | > 2 business days |
| Intercompany invoice — counterpart receipt to posting | ≤ 2 business days | > 3 business days |

---

### Collections SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| First collection contact (overdue day 1) | Within 2 business days of invoice due date | > 5 business days past due |
| Promise to pay — follow-up check | 1 business day after promised date | — |
| Dispute registration | Same business day as customer contact | > 1 business day |
| Dispute resolution | ≤ 10 business days from registration | > 15 business days |
| Escalation to legal collections | 60 days overdue with no agreed plan | > 90 days |

---

### Cash Application SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Bank statement download and processing | By 9:00 AM each business day | > 12:00 noon |
| Auto-match rate target | ≥ 90% of payments matched automatically | < 80% |
| Manual match completion | ≤ 4 hours from statement processing | > 1 business day |
| Unmatched item resolution | ≤ 5 business days | > 10 business days |
| Refund processing | ≤ 3 business days from approval | > 5 business days |

---

### AR Regular Activity SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| AR subledger review (monthly) | By close day 2 | After close day 3 |
| Customer reconciliation (on request) | ≤ 5 business days from request | > 7 business days |
| AR aging report distribution | By business day 3 after period end | > business day 5 |

---

## L2: General Ledger / Record-to-Report

### GL KPIs

| KPI | Definition | Target | Alert Threshold |
|---|---|---|---|
| Reconciliation completion by close day 3 | % of assigned accounts reconciled by day 3 | 100% | < 95% |
| Journal entry same-day processing | % of JEs posted same business day as preparation | ≥ 95% | < 90% |
| Intercompany agreement rate | % IC balances agreed with counterpart by close day 3 | 100% | < 98% |
| Accrual accuracy | Variance of actual vs. estimated accrual | < 5% | > 10% |

---

### Master Data SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| New GL account creation | 2 business days from approved request | > 3 business days |
| Cost centre / profit centre creation | 2 business days from approved request | > 3 business days |
| GL master data deactivation | 1 business day from approved request | > 2 business days |

---

### GL Accounting SLAs

| Activity | SLA Target | Breach Threshold |
|---|---|---|
| Manual journal entry — preparation to posting | ≤ 4 hours (standard) | > 1 business day |
| Recurring journal entry posting (period start) | By business day 1 of each period | > business day 2 |
| Balance sheet reconciliation — completion | By close day 3 | After close day 4 |
| GR/IR clearing run | Monthly by close day 2 | After close day 3 |
| Intercompany balance agreement | By close day 3 | After close day 4 — escalate immediately |

---

### Close Calendar & Day Targets

| Close Task | Target Day | Hard Deadline |
|---|---|---|
| Subledger close (AP/AR/MM) | Day 1 | Day 2 |
| Recurring and standard JEs posted | Day 1 | Day 2 |
| Forex revaluation | Day 1 | Day 2 |
| GR/IR clearing | Day 2 | Day 3 |
| Intercompany agreement | Day 2 | Day 3 |
| Balance sheet reconciliations complete | Day 3 | Day 4 |
| Accruals and adjustments | Day 3 | Day 4 |
| Trial balance review | Day 3 | Day 4 |
| GL period lock | Day 4 | Day 5 |
| Management pack distributed | Day 5 | Day 6 |
| Consolidation data submitted to group | Day 4 | Day 5 |
| Group consolidated accounts | Day 8 | Day 10 |

> **Hard close = no postings accepted after this date without CFO approval.**

---

### Tax Reporting Deadlines

| Filing | Typical Frequency | Benchmark Lead Time (preparation) |
|---|---|---|
| Domestic VAT return | Monthly or quarterly | 5 business days before filing deadline |
| Foreign VAT return | Per jurisdiction (monthly/quarterly) | 7 business days before jurisdiction deadline |
| CIT (Corporate Income Tax) return | Annual | 30 business days before statutory deadline |
| Intrastat / Extrastat | Monthly | 5 business days before deadline |
| Deferred tax calculation | Quarterly (interim) / Annual | By close day 5 of quarter-end period |
| Withholding tax return | Per jurisdiction | 5 business days before deadline |

> Filing deadlines vary by jurisdiction. Check `fa_environment.md` for entity-specific statutory deadlines.
