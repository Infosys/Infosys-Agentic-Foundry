---
name: Finance & Accounting Judgment Rules
type: judgment
description: Approval thresholds, DOA limits, escalation rules, and materiality guidelines for AP, AR, and GL processes
status: active
skills: []
---

# Finance & Accounting — Judgment Rules & Approval Authority
_Last updated: 2026-04-24_

This file defines **judgment rules** — approval authorities, materiality thresholds, escalation logic, and policy decisions — that govern how the agent should route transactions, approve actions, and escalate exceptions. When a decision is needed, consult this file before acting.

> Values shown are **standard benchmark defaults**. Actual customer-specific DOA values are in `fa_environment.md`. Always prefer the tenant-specific value if configured.

---

## L1: Enterprise Governance

### Accounting Standards

| Rule | Default |
|---|---|
| Reporting standard | IFRS (default); switch to US GAAP or Local GAAP if configured in `fa_environment.md` |
| Materiality threshold (individual transaction) | 0.5% of total revenue OR €50,000 — whichever is lower |
| Materiality threshold (aggregated) | 5% of net profit OR €500,000 — whichever is lower |
| Accounting policy change | Requires CFO approval + disclosure in financial statements |
| Prior period restatement | Requires CFO + Audit Committee approval |

### Delegation of Authority (DOA) — Principle

The DOA matrix defines who can approve what. The general principle:
- **Agent auto-action:** Only where explicitly permitted below (Wave1 autonomous actions)
- **Single approver:** Transaction within that role's limit
- **Dual control:** Transactions above single approver limit require two signatories
- **Board/CFO:** Required above defined thresholds

### Segregation of Duties (SoD) — Hard Rules

| Rule | Enforcement |
|---|---|
| Creator ≠ Approver (all transactions) | Block — agent must never approve what it creates |
| Payment proposer ≠ Payment releaser | Block — two separate roles required |
| Vendor master creator ≠ Invoice processor for that vendor | Flag for review |
| Journal entry preparer ≠ Journal entry approver | Block for JEs above €10,000 |

### Data Retention Policy

| Document Type | Minimum Retention | Action on Breach |
|---|---|---|
| Invoices (AP and AR) | 7 years | Block deletion; escalate to compliance |
| Journal entries + supporting docs | 7 years | Block deletion; escalate |
| Bank statements | 7 years | Block deletion; escalate |
| Tax returns and supporting schedules | 10 years | Block deletion; escalate |
| Payroll records | 7 years | Block deletion; escalate |

---

## L2: Accounts Payable

### L2 AP: Vendor Onboarding Approval Rules

| Condition | Required Action |
|---|---|
| New vendor — standard onboarding | AP Manager approval after document verification |
| New vendor — amount > €100,000 expected annual spend | Finance Director approval + procurement sign-off |
| Vendor bank detail change request | Independent verification (phone call to registered number) + AP Manager sign-off. **Never approve based on email alone.** |
| Vendor on watch list (OFAC / EU sanctions) | Block immediately; escalate to compliance — do not create |
| Vendor already exists under different ID | MDM team merge decision required; do not create duplicate |

### L2 AP: Payment Terms

| Condition | Standard Terms | Override Authority |
|---|---|---|
| Default vendor payment terms | Net 30 days from invoice date | Procurement Manager |
| Extended terms requested by vendor | Up to Net 60 — AP Manager; > Net 60 — Finance Director | — |
| Early payment discount | Auto-accept if APR equivalent > 12% annualised | AP Manager can override |
| Prepayment to new vendor | Requires Finance Director approval + deposit guarantee where possible | — |

### L2 AP: Invoice Matching Policy

| Condition | Required Match | Exception Waiver Authority |
|---|---|---|
| Invoice with PO | 3-way match (PO + GR + invoice) | AP Manager for one-time waiver |
| Services invoice with PO | 2-way match (PO + invoice) | AP Manager |
| Invoice without PO (maverick spend) | Retrospective PO or written approval from cost centre owner | Finance Director for amounts > €10,000 |
| Price variance within tolerance | Auto-approve (≤ 2% or ≤ €100, whichever is lower) | — |
| Price variance above tolerance | Route to buyer for PO amendment or explicit approval | Finance Director for amounts > €10,000 |

### L2 AP: Invoice Approval Authority

| Invoice Amount | Approver |
|---|---|
| ≤ €5,000 | Cost Centre Manager |
| €5,001 – €25,000 | Department Head |
| €25,001 – €100,000 | Finance Manager |
| €100,001 – €500,000 | Finance Director |
| > €500,000 | CFO |
| Any contract commitment > 1 year | CFO + Legal |

> Agent rule: always check amount against this matrix before routing. If approver is unavailable, route to the next level up — never reduce approval level.

### L2 AP: Payment Authorisation Limits

| Payment Amount | Release Authority |
|---|---|
| ≤ €25,000 | AP Supervisor (single signatory) |
| €25,001 – €100,000 | Finance Manager + AP Supervisor (dual control) |
| €100,001 – €500,000 | Finance Director + Finance Manager (dual control) |
| > €500,000 | CFO + Finance Director (dual control) |
| Any international wire > €50,000 | Requires treasury confirmation of beneficiary details |

---

## L2: Accounts Receivable

### L2 AR: Customer Onboarding Approval Rules

| Condition | Required Action |
|---|---|
| New customer — credit limit ≤ €10,000 | AR Manager automatic approval after credit check |
| New customer — credit limit €10,001 – €50,000 | Credit Manager approval |
| New customer — credit limit > €50,000 | Finance Director approval |
| Customer on external watch list | Block; escalate to credit manager and compliance |
| Proforma / cash-on-delivery terms only | AR Manager decision; no credit limit required |

### L2 AR: Credit Policy

| Rule | Default |
|---|---|
| Credit limit review frequency | Annually for all customers; quarterly for customers > €50,000 exposure |
| Credit hold trigger — overdue threshold | Invoice ≥ 30 days past due with no agreed payment plan |
| Credit hold release | Confirmed payment received + no other overdue invoices |
| Credit limit increase request (existing customer) | Up to 20% increase — AR Manager; > 20% — Credit Manager |
| Credit limit reduction | AR Manager decision; customer must be notified with 30-day notice |

### L2 AR: Collections Escalation Ladder

| Days Overdue | Action | Authorisation |
|---|---|---|
| Day 1–5 | Automated statement / reminder email | Agent autonomous |
| Day 6–15 | Personal email from AR team | AR team autonomous |
| Day 16–30 | Phone call — record outcome | AR Supervisor |
| Day 31–60 | Senior collections contact; negotiate payment plan | AR Manager |
| Day 61–90 | Final demand letter; consider credit hold | Finance Manager |
| Day 91+ | Refer to external collections or legal | Finance Director approval required |
| Any point | Bankruptcy notification received | Escalate to legal immediately |

### L2 AR: Write-Off Policy

| Write-Off Amount | Approval Required |
|---|---|
| ≤ €1,000 | AR Manager |
| €1,001 – €10,000 | Finance Manager |
| €10,001 – €50,000 | Finance Director |
| > €50,000 | CFO |
| Any write-off related to active dispute | Legal sign-off also required |

### L2 AR: Invoice Dispute Resolution Rules

| Dispute Type | Initial Handler | Escalation Path | Resolution SLA |
|---|---|---|---|
| Pricing dispute | AR team → Sales team | Sales Director → Finance Manager | 10 business days |
| Quantity / delivery dispute | AR team → Warehouse/logistics | Operations Manager → Finance Manager | 10 business days |
| Tax dispute | AR team → Tax team | Tax Director | 15 business days |
| Duplicate invoice | AR team | AR Manager if customer disputes finding | 5 business days |
| Service quality dispute | AR team → Service Delivery Manager | Customer Director | 20 business days |

---

## L2: General Ledger

### L2 GL: Journal Entry Policy

| Rule | Default |
|---|---|
| Standard JE approval threshold | JEs > €10,000 require second approver |
| JEs ≤ €10,000 | Preparer + system auto-approval (no manual sign-off required) |
| Manual JE to revenue/expense accounts | Always requires supporting documentation |
| Top-side / consolidation adjustment JEs | Controller sign-off required regardless of amount |
| Recurring JE review | Monthly — preparer verifies accuracy before posting; changes require Controller approval |
| Reversing JE | Auto-reversal preferred; manual reversal requires same approval as original |
| Prior period JE (posting to closed period) | Finance Manager approval; closed fiscal year requires CFO |

### L2 GL: Journal Entry Approval Authority

| JE Amount | Approver |
|---|---|
| ≤ €10,000 | GL Accountant (self-approve where SoD allows) |
| €10,001 – €100,000 | Finance Manager |
| €100,001 – €500,000 | Finance Director |
| > €500,000 | CFO |
| Any prior-year restatement JE | CFO + Audit Committee notification |

### L2 GL: Reconciliation Requirements

| Account Type | Reconciliation Frequency | Sign-Off Required |
|---|---|---|
| Bank accounts | Daily (or at minimum, monthly close) | Finance Manager |
| Intercompany accounts | Monthly — before GL close | Controller |
| AP subledger to GL | Monthly close | AP Manager |
| AR subledger to GL | Monthly close | AR Manager |
| Fixed asset register to GL | Monthly close | Fixed Assets Accountant |
| GR/IR clearing account | Monthly close | Procurement Finance |
| Payroll accounts | Monthly close | Payroll Manager |
| Tax accounts (VAT, CIT) | Monthly close | Tax Accountant |
| All other BS accounts | Monthly close | GL Accountant |

### L2 GL: GL Master Data Approval Rules

| Change | Approval Required |
|---|---|
| New GL account creation | Finance Manager; Group Controller for accounts affecting consolidation |
| GL account closure / deactivation | Finance Manager; confirm no open items |
| New cost centre | Department Head + Finance Manager |
| Cost centre budget increase | Department Head + Finance Manager |
| New profit centre | Finance Director |
| Chart of accounts restructuring | CFO + Group Controller |

### L2 GL: Close Escalation Rules

| Situation | Action |
|---|---|
| Blocking item preventing subledger close at Day 1 | Escalate to respective L2 lead (AP/AR Manager) immediately |
| Unreconciled difference > materiality at Day 3 | Escalate to Finance Manager; consider posting provisional entry |
| Any IC balance not agreed by Day 3 | Escalate to Finance Director; force-agree with best estimate |
| Trial balance out of balance at any point | Stop close; escalate to Controller immediately |
| Missed hard close deadline | Notify CFO and Group Controller within 1 hour |

### Hard-Close vs. Soft-Close Policy

| Period | Type | Rule |
|---|---|---|
| Month 1, 2, 4, 5, 7, 8, 10, 11 | Soft close | Adjustments allowed up to 5 business days post close with Finance Manager approval |
| Quarter-end (Month 3, 6, 9) | Hard close | No adjustments after Day 5 without CFO approval |
| Year-end (Month 12) | Hard close | No adjustments after Day 7 without CFO + Audit Committee approval |

---

## Tax Judgment Rules

### Tax Deductibility Assessment

| Expenditure Type | Default Treatment | Override Authority |
|---|---|---|
| Business travel & entertainment | Deductible up to local statutory limit | Tax Director for amounts above limit |
| Fines and penalties | Non-deductible | Tax Director confirmation required |
| Depreciation | Per local tax depreciation schedules | Tax Director |
| Intercompany service charges | Deductible if at arm's length transfer price | Tax Director review for amounts > €100,000 |
| Capital expenditure | Capitalise; do not expense | Finance Manager + CFO for policy changes |

### Tax Filing Sign-Off

| Return Type | Sign-Off Required |
|---|---|
| Domestic VAT return | Finance Manager |
| Foreign VAT return | Tax Accountant + Finance Manager |
| CIT return | CFO + Tax Director |
| Deferred tax calculation | Finance Director |
| Any amended filing | CFO |

### Unmatched Payment Handling Rules (Cash Application)

| Situation | Agent Action |
|---|---|
| Unmatched payment ≤ €500 | Agent may apply to oldest open invoice as provisional match; flag for review |
| Unmatched payment > €500 | Park as unidentified receipt; contact customer; do not apply without confirmation |
| Overpayment ≤ €100 | Apply as credit to customer account; notify customer |
| Overpayment > €100 | Contact customer for preference — refund or credit note |
| Payment from unknown counterparty | Do not apply; flag to AR Manager; check against new customer pipeline |

### Cost Accounting — Allocation Rules

| Rule | Default |
|---|---|
| Distribution cycle frequency | Monthly — run after subledger close (Day 2) |
| Allocation basis | Per allocation key defined in ERP (headcount, floor space, revenue, or agreed split) |
| Allocation key change | Requires Finance Director approval; effective from next full month |
| Manual PCA adjustment threshold requiring approval | > €50,000 requires Finance Manager sign-off |
