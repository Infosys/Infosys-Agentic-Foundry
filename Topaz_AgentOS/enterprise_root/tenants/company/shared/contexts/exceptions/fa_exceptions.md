---
name: Finance & Accounting Exceptions
type: exceptions
description: Common exception patterns, failure scenarios, and escalation paths for AP, AR, and GL processes
status: active
skills: []
---

# Finance & Accounting — Exception Patterns
_Last updated: 2026-04-24_

This file documents **exception patterns** — what can go wrong at each subprocess level, the typical root cause, the recovery action, and when to escalate. Used by the agent as the first reference when a process step fails or produces an unexpected result.

---

## L1: Finance & Accounting — Enterprise Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Duplicate transaction detected (AP or AR) | System or human re-entry; ERP auto-pay failure | Block processing; raise duplicate flag; present evidence to reviewer | Amount > materiality threshold or vendor/customer disputes it |
| SoD (Segregation of Duties) violation | Same user creating and approving | Block action; log violation; notify compliance team | Any SoD breach — zero tolerance |
| Data retention policy breach | Document purged before retention period expires | Halt deletion; restore from archive if available; notify compliance | Always escalate — potential audit risk |
| System unavailability (ERP / banking portal) | Planned/unplanned downtime | Switch to manual workaround log; queue transactions for catch-up | If downtime > 4 hours during close period |

---

## L2: Accounts Payable

### AP Master Data Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Duplicate vendor master detected | Same vendor created twice with different IDs | Flag both records; present comparison to MDM team for merge decision | Vendor already has live transactions on both records |
| Vendor bank details changed | Potential fraud — vendor impersonation | Block payment; freeze vendor record; trigger verification call to known vendor contact | Always escalate — high fraud risk |
| Missing mandatory field on vendor master | Incomplete onboarding form | Return request to requestor with specific missing fields listed | Vendor is needed for imminent payment run |
| Sanctioned entity match on vendor name | Vendor name matches OFAC/sanctions list | Block vendor creation immediately; do not process any payments | Always escalate to compliance |
| Tax ID already used on another vendor | Duplicate tax ID — potential fraud or data error | Flag conflict; do not create; refer to tax/compliance team | Always escalate |

---

### Invoice Receipt Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Invoice received without PO reference | Maverick spend or vendor not following process | Park invoice; request PO from requestor; notify procurement | Invoice amount > AP policy threshold for no-PO invoices |
| Invoice in unsupported format / unreadable scan | Poor scan quality or non-standard document | Return to scanning for re-scan; if original is unreadable, contact vendor for reissue | Vendor is unable to reissue |
| Invoice addressed to wrong legal entity | Vendor sent to wrong company code | Return to vendor for correction; do not process | Payment deadline is imminent |
| Duplicate invoice received | Vendor re-sent already paid invoice | Block; cross-reference payment history; notify vendor | Vendor disputes the duplicate flag |

---

### Invoice Processing Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Vendor not found in ERP | New vendor or vendor name mismatch | Park invoice; initiate vendor master creation; do not process until resolved | Payment due date is within 5 days |
| PO not found / PO closed | PO number on invoice is wrong, expired, or fully received | Park invoice; contact requestor for valid PO or 3-way match waiver | Invoice amount > policy threshold for PO waiver |
| 3-way match failure — price variance | Invoice price differs from PO by > tolerance | Route to buyer for PO amendment or price approval | Variance > 5% or > €500 (whichever is lower); refer to `fa_judgment.md` → Invoice Approval |
| 3-way match failure — quantity variance | Invoice quantity differs from goods receipt | Route to warehouse/requestor to confirm delivery; park invoice | Goods receipt pending for > 10 days |
| Tax code mismatch | Incorrect tax code applied vs. invoice content | Flag for tax team review; do not post until tax code confirmed | Cross-border supply with reverse charge implications |
| Invoice in foreign currency with no exchange rate | Missing FX rate in ERP for invoice date | Check ERP FX table; load rate if missing; escalate if rate cannot be sourced | Rate missing for > 1 business day |
| Account coding missing or rejected | Cost centre/GL account not assigned or not valid | Return to account owner for correction | Account owner unresponsive for > 2 business days |
| Goods / services not yet received | Invoice received before delivery | Park invoice as accrual; do not pay until GR confirmed | Supplier is threatening stop-supply |

---

### E-Invoice Processing Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| E-invoice format validation failure | Mandatory XML/EDI fields missing or malformed | Reject with error code; notify vendor of specific field failures | Vendor cannot correct within 2 business days |
| E-invoice duplicate (same invoice ID) | Vendor re-transmitted already processed invoice | Block; cross-reference processed invoices; notify vendor | Vendor disputes the duplicate |
| Tax schema validation error | Tax fields do not match country e-invoicing schema | Flag for tax team; do not post | Affects VAT reporting period |

---

### Invoice Authorization Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Approver unavailable (OOO, departed) | Approver has no delegate set | Identify next approver in DOA hierarchy; notify AP supervisor | Invoice payment deadline within 48 hours |
| Approval SLA breached | Invoice pending approval beyond threshold (see `fa_benchmarks.md`) | Send escalation reminder; flag in overdue report | SLA breached by > 2 days; escalate to approver's manager |
| Invoice rejected by approver — no reason given | Approver clicked reject without comment | Return to approver requesting reason; do not abandon invoice | Approver unresponsive for > 1 business day |
| Invoice amount exceeds approver's DOA | Invoice routed to wrong approval level | Re-route to correct approver per `fa_judgment.md` → Invoice Approval Authority | Amount exceeds even highest DOA level — requires board/CFO |

---

### Invoice Payment Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Duplicate payment detected in payment proposal | Same invoice in proposal twice; manual + auto-pay overlap | Remove duplicate from proposal; flag for root cause analysis | Duplicate has already been released to bank |
| Vendor bank account does not match master data | Bank details changed or mismatch | Block payment; verify bank details via independent channel (phone/signed letter) | Always escalate — fraud risk |
| Payment file rejected by bank | Format error, account closed, insufficient funds | Pull rejection reason; correct or re-route; re-submit | Rejection due to insufficient funds — escalate to treasury |
| Payment released past due date | Late approval, system delay | Document reason; proceed with payment; log SLA breach | Vendor applies late payment interest — refer to `fa_benchmarks.md` |
| Netting offset blocked by system | Vendor also a customer; netting configuration missing | Set up netting agreement in ERP; process net amount | Customer balance disputed |

---

## L2: Accounts Receivable

### AR Master Data Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Duplicate customer detected | Same customer created with different IDs | Flag; present comparison to MDM team for merge decision | Customer has live AR balance on both records |
| Customer bank details changed | Potential fraud — refund redirection | Block refund; freeze bank detail change; verify via known contact | Always escalate — fraud risk |
| Customer credit limit set to zero | New customer with no credit history | Route for credit assessment before allowing orders | Customer is placing a large first order |

---

### Credit Risk Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Customer exceeded credit limit | Sales order would breach approved limit | Block order; notify sales team; route to credit manager for limit review | Customer is a key account; escalate to credit manager same day |
| Credit rating agency data unavailable | New customer or rating service outage | Use internal credit scoring model as proxy; flag as provisional | Proposed credit limit > €50,000 |
| Customer on external watch list (D&B / Experian) | Financial distress signal | Flag to credit manager; reduce limit; tighten payment terms | Any watch list flag — escalate immediately |
| Credit hold applied — customer disputes it | Customer claims payment was made | Check bank reconciliation; if payment confirmed, release hold within 24h | Payment not traceable after 24h — escalate to AR manager |

---

### Customer Billing Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Invoice disputed by customer | Price/quantity/service disagreement | Log dispute; park invoice from collection; route to dispute resolution per `fa_judgment.md` | Dispute value > €10,000 or customer is key account |
| Invoice sent to wrong address / contact | Outdated customer master data | Re-send to correct contact; update customer master | Invoice is > 30 days old and unpaid |
| Tax treatment incorrect on issued invoice | Wrong tax code applied | Issue credit note for original; reissue with correct tax code | Tax authority has already assessed the period |
| Intercompany invoice not matched by counterpart | Transfer price disagreement or timing difference | Contact counterpart finance team; agree correction | Difference > materiality threshold; refer to `fa_judgment.md` |

---

### Collections Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Customer unresponsive to all contact attempts | Customer in financial difficulty or dispute | Escalate to senior AR / legal per `fa_judgment.md` → Collections Escalation | Balance > €5,000 and unresponsive for > 30 days |
| Customer made partial payment — no explanation | Partial remittance with no advice | Apply payment to oldest invoice; contact customer for balance | Pattern of partial payments for > 3 consecutive months |
| Promise to pay broken | Customer committed but did not pay | Escalate collection method; consider credit hold | Second broken promise in same quarter |
| Bankruptcy / insolvency notification received | Customer enters administration | Freeze account; notify legal; file proof of debt within deadline | Always escalate — potential write-off |
| Customer requests extended payment terms | Cash flow difficulty | Route to credit manager for assessment; do not agree without approval | Extension > 30 days or amount > €20,000 |

---

### Cash Application Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Payment received with no remittance advice | Customer did not provide payment details | Search open AR for likely match by amount/date; contact customer for remittance | Unmatched for > 5 business days |
| Payment amount does not match any open invoice | Customer deducted charges or paid wrong amount | Park as unidentified receipt; contact customer | Unresolved for > 10 business days |
| Overpayment received | Customer paid more than invoiced amount | Apply to account; contact customer — refund or credit note per preference | Customer demands refund > €5,000 — escalate for treasury approval |
| Bank file format error | Bank changed file format or transmission error | Contact bank; request re-transmission; apply manual workaround | Bank unable to re-transmit within same business day |
| Bank reconciliation difference | Timing difference or unposted transaction | Identify specific difference item; post missing entry | Difference unexplained after 2 business days — escalate to GL |

---

### AR Regular Activity Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| AR subledger does not reconcile to GL | Posting error or interface failure | Identify difference items; post correction JE | Difference > materiality threshold or month-end approaching |
| Customer reconciliation dispute | Customer records differ from internal AR | Review transaction-by-transaction; agree corrections | Disputed amount > €10,000 |

---

## L2: General Ledger

### GL Master Data Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| New GL account requested outside chart of accounts policy | Business unit wants non-standard account | Return request; explain policy; suggest closest existing account | Business unit insists — escalate to Group Controller |
| Cost centre with no budget assigned | New cost centre without budget setup | Flag to FP&A team; warn that postings will exceed budget | Postings about to be made to unbudgeted cost centre |
| Duplicate GL account detected | Similar account exists under different code | Present both accounts to GL team for rationalisation decision | Live transactions exist on both accounts |

---

### GL Accounting Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Journal entry posted to closed period | System allowed posting to wrong period | Reverse JE; repost to correct open period | Closed period is a prior fiscal year — requires restatement |
| Recurring journal entry failed to post | System job failure or period not open | Investigate job log; manually post if job cannot re-run | Close deadline within 24 hours |
| Balance sheet account reconciliation — unexplained difference | Posting error, missing subledger entry, or interface gap | Identify specific difference items; prepare correction JE | Difference > materiality threshold at month-end |
| GR/IR open item aged > 90 days | PO/GR mismatch; cancelled PO not reversed | Escalate to procurement to confirm goods receipt or cancel PO | Aged item > €10,000 |
| Intercompany balance does not agree | Transfer pricing dispute or timing difference | Present reconciliation to counterpart; agree correction | Difference > €50,000 or not resolved before close |
| Accrual significantly different from actual | Estimation error | Post true-up JE; document basis; notify FP&A | Variance > 10% of line and > materiality threshold |

---

### Period Close Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| Subledger close blocking GL close | Open transactions in AP/AR/MM preventing GL period lock | Identify blocking items; route to respective team for resolution | < 4 hours to hard close deadline |
| Forex revaluation produced unexpected large variance | Rate source error or high FX movement | Verify rate source; compare to market rate; document if rate is correct | Variance > materiality — escalate to treasury |
| Trial balance out of balance | Interface error or manual posting without offsetting entry | Identify debit/credit imbalance; trace to source posting | Any out-of-balance at hard close — stop close; escalate immediately |
| Consolidation submission rejected | Validation rule failure in group reporting tool | Review validation errors; correct source data; re-submit | Cannot resolve before group consolidation deadline |
| Period close missed hard deadline | Resource issue, system failure, or unresolved exception | Document reason; notify Group Controller; complete close ASAP | Always notify on missed hard close |

---

### Tax & Statutory Exceptions

| Exception | Root Cause | Agent Action | Escalate When |
|---|---|---|---|
| VAT return calculation does not match control account | Posting to VAT account without proper tax code; manual override | Reconcile to identify specific posting differences; correct or document | Difference > €1,000 or VAT filing deadline within 5 days |
| Missing tax invoice for input VAT claim | Invoice not received or not compliant | Do not claim VAT; request compliant invoice from supplier | Invoice cannot be obtained before filing deadline |
| CIT expenditure category classification dispute | Business unit disagrees with tax deductibility assessment | Document agent's assessment with legal basis; route for tax advisor review | Amount > €50,000 deductibility difference |
| Tax filing deadline missed | Preparation delay or system issue | File immediately with penalty acknowledgement; notify tax advisor | Always escalate missed filing to CFO/tax director |
| Tax audit query received | Tax authority requests documentation | Gather requested documents from archive; prepare structured response | Query relates to prior period restatement risk |
