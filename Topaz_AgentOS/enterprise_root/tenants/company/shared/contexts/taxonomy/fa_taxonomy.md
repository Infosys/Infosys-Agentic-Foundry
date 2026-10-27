---
name: Finance & Accounting Taxonomy
type: taxonomy
description: L1-L5 process hierarchy for Finance & Accounting — Accounts Payable (PtP), Accounts Receivable (OtC), General Ledger / Record-to-Report (RtR)
status: active
skills: [fa_ar, fa_ap, fa_gl]
source: L3_Productivity_Model_N.xlsx
---

# Finance & Accounting — Process Taxonomy (L1→L5)
_Last updated: 2026-04-24_

This taxonomy defines the **process hierarchy** for Finance & Accounting.
Each node (L1/L2/L3) carries links to the relevant ContextOS pillar files — exceptions, benchmarks, judgment, and framework mapping — so the agent knows where to look for rules and constraints at every level of the process tree.

---

## Quick Index — All L3 Subprocesses

| L3 Subprocess | L2 Domain | APQC PCF | Exceptions | Benchmarks | Judgment |
|---|---|---|---|---|---|
| Master Data Management | Accounts Payable | 9.6.1 | `fa_exceptions.md` → AP Master Data | `fa_benchmarks.md` → AP MDM | `fa_judgment.md` → Vendor Onboarding |
| Invoice Receipt | Accounts Payable | 9.6.1 | `fa_exceptions.md` → Invoice Receipt | `fa_benchmarks.md` → Invoice Receipt | — |
| Invoice Processing | Accounts Payable | 9.6.1 | `fa_exceptions.md` → Invoice Processing | `fa_benchmarks.md` → Invoice Processing | `fa_judgment.md` → Invoice Approval |
| Electronic Invoice Processing | Accounts Payable | 9.6.1 | `fa_exceptions.md` → E-Invoice Processing | `fa_benchmarks.md` → Invoice Processing | — |
| Invoice Authorization | Accounts Payable | 9.6.1 | `fa_exceptions.md` → Invoice Authorization | — | `fa_judgment.md` → Invoice Approval |
| Invoice Payment | Accounts Payable | 9.6.1 | `fa_exceptions.md` → Invoice Payment | `fa_benchmarks.md` → Payment Processing | `fa_judgment.md` → Payment Authorisation |
| AP Regular Activities | Accounts Payable | 9.6.1 | `fa_exceptions.md` → AP Regular | `fa_benchmarks.md` → AP Regular | — |
| Vendor / Employee Queries | Accounts Payable | 9.6.1 | `fa_exceptions.md` → Vendor Queries | `fa_benchmarks.md` → Query Resolution | — |
| Master Data Management | Accounts Receivable | 9.2.3 | `fa_exceptions.md` → AR Master Data | `fa_benchmarks.md` → AR MDM | `fa_judgment.md` → Customer Onboarding |
| Credit Risk | Accounts Receivable | 9.2.1 | `fa_exceptions.md` → Credit Risk | `fa_benchmarks.md` → Credit Management | `fa_judgment.md` → Credit Limits |
| Customer Billing | Accounts Receivable | 9.2.2 | `fa_exceptions.md` → Customer Billing | `fa_benchmarks.md` → Billing | `fa_judgment.md` → Invoice Disputes |
| Collection | Accounts Receivable | 9.2.4 | `fa_exceptions.md` → Collections | `fa_benchmarks.md` → Collections | `fa_judgment.md` → Collections Escalation |
| Cash Application | Accounts Receivable | 9.2.3 | `fa_exceptions.md` → Cash Application | `fa_benchmarks.md` → Cash Application | `fa_judgment.md` → Unmatched Payments |
| AR Regular Activities | Accounts Receivable | 9.2.3 | `fa_exceptions.md` → AR Regular | `fa_benchmarks.md` → AR Regular | — |
| Deductions Accounting | Accounts Receivable | 9.2.5 | `fa_exceptions.md` → Deductions | `fa_benchmarks.md` → Deductions | `fa_judgment.md` → Deductions Approval |
| GL Master Data Management | General Ledger | 9.3.2 | `fa_exceptions.md` → GL Master Data | `fa_benchmarks.md` → GL MDM | `fa_judgment.md` → GL Master Data |
| General Ledger Accounting | General Ledger | 9.3.2 | `fa_exceptions.md` → GL Accounting | `fa_benchmarks.md` → GL Accounting | `fa_judgment.md` → Journal Entry Approval |
| Cost Accounting | General Ledger | 9.3.2 | — | `fa_benchmarks.md` → Cost Accounting | `fa_judgment.md` → Cost Allocation |
| Closing & Consolidation | General Ledger | 9.3.2/9.3.4 | `fa_exceptions.md` → Period Close | `fa_benchmarks.md` → Close Calendar | `fa_judgment.md` → Close Escalation |
| Tax & Statutory Accounting | General Ledger | 9.9.2 | `fa_exceptions.md` → Tax & Statutory | `fa_benchmarks.md` → Tax Reporting | `fa_judgment.md` → Tax Judgment |

---

## L1: Finance & Accounting

> **Enterprise Policies**
> _DOA & SoD:_ `fa_judgment.md` → L1: Enterprise Governance
> _Group Accounting Policy:_ `fa_judgment.md` → L1: Accounting Standards
> _Data Retention & Audit:_ `fa_environment.md` → Retention Policy
> _APQC Framework Mapping:_ `fa_frameworks.md`
> _Environment & Systems:_ `fa_environment.md`

---

### L2: Accounts Payable (PtP)

> **AP Domain Policies**
> _Payment Terms Policy:_ `fa_judgment.md` → L2 AP: Payment Terms
> _Vendor Onboarding Policy:_ `fa_judgment.md` → L2 AP: Vendor Onboarding
> _Three-Way Match Policy:_ `fa_judgment.md` → L2 AP: Invoice Matching
> _AP DOA Limits:_ `fa_judgment.md` → L2 AP: Approval Authority Matrix
> _AP Benchmarks (DSO, DPO, cycle times):_ `fa_benchmarks.md` → L2: Accounts Payable
> _AP Exception Patterns:_ `fa_exceptions.md` → L2: Accounts Payable

---

#### L3: Master Data Management `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → AP Master Data Exceptions
> _Judgment:_ `fa_judgment.md` → Vendor Onboarding Approval Rules
> _Benchmarks:_ `fa_benchmarks.md` → Master Data SLAs

##### L4: AP Master Data
| L5 Activity | Description |
|---|---|
| Fill in vendor/item/other master request form | Capture new vendor details and populate master data request form |
| Approve request | Authorise vendor master creation/change per DOA |
| Provide request with underlying documentation | Attach supporting docs — bank details, company registration, tax ID |
| Check for completeness & internal policy compliance | Validate vendor master request against all policy fields |
| Create / update / delete vendor master | Execute vendor master create/update/deactivate in ERP |
| Archive as per archiving policies | Move processed request to archive per retention schedule |
| Review for unused master data and follow up | Identify and flag inactive/duplicate vendor records for cleanup |

---

#### L3: Invoice Receipt `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → Invoice Receipt Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Invoice Receipt SLAs

##### L4: Document Handling / Mailroom
| L5 Activity | Description |
|---|---|
| Receive post from providers | Collect inbound mail and packages from providers |
| Sort documents from post | Classify inbound documents — invoices, statements, queries |
| Provide invoices for scanning | Route physical invoices to scanning station |
| Provide other documents to respective departments | Forward non-invoice documents to correct team or return to sender |

##### L4: Invoice Scanning
| L5 Activity | Description |
|---|---|
| Receive invoice for scanning | Accept physical invoice at scanning station |
| Verify against internal policies | Check invoice format and completeness before scanning |
| Send back invoice to supplier if improperly issued | Return non-compliant invoices with rejection reason |
| Scan invoice and check readability of image | Execute scan; verify OCR quality and image legibility |
| Prepare documents for archive | Package scanned invoice images for archiving |
| Archive/store as per archiving policies | Store scanned images per retention policy |

---

#### L3: Invoice Processing `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → Invoice Processing Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Invoice Processing SLAs
> _Judgment:_ `fa_judgment.md` → Invoice Approval Thresholds & Tax Coding Rules

##### L4: Invoice Processing
| L5 Activity | Description |
|---|---|
| Check invoice for legal, fiscal & internal compliance | Verify invoice against tax rules, internal policy, and completeness requirements |
| Index or check OCR indexing of document | Validate OCR extraction of invoice fields; correct mis-reads |
| Check vendor data existence in system | Look up vendor master — confirm vendor is registered and active |
| Check related purchase order (PO) | Search for and validate related PO; handle missing PO exception |
| Attach image to document in system | Link scanned invoice image to document record in ERP |
| Assign or send invoice for tax coding | Route invoice to tax team for appropriate tax code assignment |
| Perform data entry & 2 or 3-way matching | Match invoice against PO, goods receipt, and contract |
| Send invoice for account coding | Route to cost centre / account owner for GL account assignment |
| Assign invoice account coding details | Apply GL account codes to invoice line items |
| Resolve invoice discrepancy in case of PO mismatch | Investigate and resolve quantity/price variance between invoice and PO |
| Release invoice for payment | Final release of approved invoice into payment queue |

---

#### L3: Electronic Invoice Processing & Verification `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → E-Invoice Processing Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Invoice Processing SLAs

##### L4: Electronic Invoice Processing (semi-automated)
| L5 Activity | Description |
|---|---|
| Check invoice for legal, fiscal & internal compliance | Automated compliance check for e-invoice; handle exceptions manually |
| Assign adequate tax code | Map e-invoice to correct tax jurisdiction and rate |
| Process electronic invoice in system | Load validated e-invoice into ERP for posting |
| Check system for errors | Scan processing queue for failed or errored e-invoice records |
| Investigate root cause and make correction | Diagnose e-invoice processing error and apply fix |

##### L4: Electronic Invoice Processing (fully automated)
| L5 Activity | Description |
|---|---|
| Check system for errors | Monitor automated e-invoice queue for processing failures |
| Investigate root cause and make correction | Resolve automated processing error requiring manual intervention |

---

#### L3: Invoice Authorization `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → Invoice Authorization Exceptions
> _Judgment:_ `fa_judgment.md` → Invoice Approval Authority (DOA Matrix)

##### L4: Invoice Approval
| L5 Activity | Description |
|---|---|
| Assign approver(s) as per internal policy | Determine correct approver based on amount, cost centre, and DOA matrix |
| Send invoice for approval | Route invoice to assigned approver via workflow |
| Approve invoice | Human approval — agent pre-populates recommendation and routes |

##### L4: Chasing Approvers
| L5 Activity | Description |
|---|---|
| Generate and analyse weekly/monthly overdue approvals report | Extract invoices pending approval beyond SLA threshold |
| Define approvers to be chased | Identify approvers with overdue items using aging data |
| Contact approvers regarding missing invoice approval | Send automated or drafted reminder to overdue approvers |
| Provide explanation | Relay approver response/explanation to requesting team |
| Register reason of unapproved invoice | Log approver response and reason code for audit trail |

---

#### L3: Invoice Payment `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → Invoice Payment Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Payment Processing SLAs
> _Judgment:_ `fa_judgment.md` → Payment Authorisation Limits

##### L4: Invoice Payment / Disbursement
| L5 Activity | Description |
|---|---|
| Cash disbursement forecasting | Aggregate upcoming payment obligations and forecast cash outflow |
| Check for compensations or netting of balances | Identify offsetting AP/AR balances eligible for netting |
| Process outgoing cheques | Prepare and issue cheque payments where required |
| Create payment proposal | Generate payment run proposal from approved invoices due for payment |
| Perform vendor reconciliation / verification of payment proposal | Reconcile payment proposal against vendor statement; detect duplicates |
| Sign off payment file over prescribed limit | Human authorisation for payment batches above DOA threshold |
| Create payment run in accounting system | Execute payment run in ERP for approved payment proposal |
| Upload payment file to banking system | Transfer payment file from ERP to bank portal |
| Release payment from banking system | Final authorisation and release of payment in bank portal |
| Direct debit invoice verification | Confirm direct debit amounts against approved invoice list |
| Allocate direct debit amount on vendor account | Post direct debit receipt to vendor account in ERP |

##### L4: Prepayment / Advanced / Rush Payment
| L5 Activity | Description |
|---|---|
| Prepare prepayment/rush payment request | Draft special payment request with supporting documentation |
| Obtain approval for prepayment over prescribed limit | Route to approver per DOA for above-threshold prepayments |
| Approve request | Authorise prepayment/rush payment |
| Process request in ERP system | Record prepayment in ERP against vendor account |
| Process request in bank system | Initiate prepayment transfer in banking portal |
| Release payment from banking system | Confirm and release prepayment in bank portal |
| Cash application (if not automated) and returns/rejections | Apply prepayment receipt against invoice; handle bank rejects |

---

#### L3: AP Regular Activities `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → AP Regular Activity Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → AP Regular Activity SLAs

##### L4: AP Regular Activities
| L5 Activity | Description |
|---|---|
| Review and maintain AP accounts | Periodic AP subledger review — open items, aged balances, anomalies |
| Book corrections if needed | Post corrective journal entries for mis-posted AP transactions |
| Prepare debit balance report and provide to customer | Extract and distribute report of vendor accounts with debit balances |

---

#### L3: Vendor / Employee Queries `[APQC 9.6.1]`
<!-- skill: fa_ap -->

> _Exceptions:_ `fa_exceptions.md` → Vendor Query Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Query Resolution SLAs

##### L4: Vendor / Employee Queries
| L5 Activity | Description |
|---|---|
| Receive & register incoming query by email or phone | Log inbound vendor/employee query into ticketing system |
| Resolve the query | Investigate and resolve query against AP records |
| Provide resolution to vendor / employee | Communicate resolution and close the ticket |

---

### L2: Accounts Receivable (OtC)

> **AR Domain Policies**
> _Credit Policy:_ `fa_judgment.md` → L2 AR: Credit Policy
> _Collection Escalation Ladder:_ `fa_judgment.md` → L2 AR: Collections Policy
> _Revenue Recognition Policy:_ `fa_judgment.md` → L2 AR: Revenue Recognition
> _AR DOA Limits:_ `fa_judgment.md` → L2 AR: Approval Authority
> _AR Benchmarks (DSO, collection rate):_ `fa_benchmarks.md` → L2: Accounts Receivable
> _AR Exception Patterns:_ `fa_exceptions.md` → L2: Accounts Receivable

---

#### L3: Master Data Management `[APQC 9.2.3]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → AR Master Data Exceptions
> _Judgment:_ `fa_judgment.md` → Customer Onboarding Approval Rules
> _Benchmarks:_ `fa_benchmarks.md` → Master Data SLAs

##### L4: Customer Master Data
| L5 Activity | Description |
|---|---|
| Fill in customer master request form | Capture new customer details and populate master data request |
| Approve request | Authorise customer master creation/change per DOA |
| Provide request with underlying documentation | Attach supporting docs — company registration, bank details, credit application |
| Check for completeness & internal policy compliance | Validate customer master request against all policy fields |
| Create / update / delete customer master | Execute customer master create/update/deactivate in ERP |
| Archive as per archiving policies | Move processed request to archive per retention schedule |
| Review for unused master data and follow up | Identify and flag inactive/duplicate customer records for cleanup |

---

#### L3: Credit Risk `[APQC 9.2.1]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → Credit Risk Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Credit Management SLAs
> _Judgment:_ `fa_judgment.md` → Credit Limit Setting Rules & Credit Hold Policy

##### L4: Credit Management
| L5 Activity | Description |
|---|---|
| Maintain credit internal standards / policies | Review and update credit policy; communicate changes to team |
| Obtain rating analysis of new customers | Retrieve credit score/rating from rating agencies for new customers |
| Define credit limit for new customer per policy | Calculate and propose credit limit based on rating and policy |
| Approve defined credit limit | Authorise proposed credit limit per DOA |
| Application of credit limit for new customer | Set approved credit limit in ERP customer master |
| Verification of credit limits for all accounts | Periodic review of all customer credit limits for policy compliance |
| Adjust credit limits in system | Update customer credit limits following periodic review |
| Review credit hold for customers per aging | Identify customers eligible for credit hold based on aging threshold |
| Approve and remove credit hold | Authorise removal of credit hold after payment received |
| Report credit risk receivables | Generate credit risk exposure report for management |

---

#### L3: Customer Billing `[APQC 9.2.2]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → Customer Billing Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Billing SLAs
> _Judgment:_ `fa_judgment.md` → Invoice Dispute Resolution Rules

##### L4: Invoicing
| L5 Activity | Description |
|---|---|
| Provide invoicing details | Gather order/delivery data required for invoice generation |
| Extract invoicing details from system | Pull billing-relevant data from ERP/order management system |
| Assign adequate tax code | Determine applicable tax rate and jurisdiction for invoice |
| Raise invoice in system | Create customer invoice record in ERP |
| Post invoice in financial ledger | Post AR invoice entry to GL |
| Send invoice to customer | Transmit invoice to customer via email, portal, or EDI |

##### L4: Intercompany Invoicing
| L5 Activity | Description |
|---|---|
| Provide invoicing details | Gather intercompany transaction details for billing |
| Extract invoicing details from system | Pull intercompany billing data from ERP |
| Assign adequate tax code | Apply correct transfer pricing / tax treatment |
| Raise invoice in system | Create intercompany invoice in ERP |
| Post invoice in financial ledger | Post intercompany AR entry to GL |
| Send invoice to intercompany customer | Transmit invoice to counterpart entity |

##### L4: Returns & Credits
| L5 Activity | Description |
|---|---|
| Receive Credit / Return Request | Log customer request for credit note or goods return |
| Manage physical inventory of returns | Coordinate warehouse to receive and inspect returned goods |
| Customer interaction and follow up | Communicate status of return/credit to customer |
| Approve Credit / Return request | Authorise credit/return per DOA after validation |
| Process Credit / Return request | Apply approved credit or return in ERP |
| Release Return / Credit Note | Issue approved credit note in ERP |
| Credit Note generation and despatch | Generate and send credit note to customer |

---

#### L3: Collection `[APQC 9.2.4]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → Collections Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Collections SLAs
> _Judgment:_ `fa_judgment.md` → Collections Escalation Ladder & Write-Off Policy

##### L4: Collection
| L5 Activity | Description |
|---|---|
| Maintain collection internal standards / policies | Review and update collection policy; communicate to team |
| Extract aging report and analyse positions | Pull AR aging report; identify overdue accounts requiring action |
| Decide on collection method per internal policy | Select approach — written/verbal/legal — based on aging and risk profile |
| Send statement to debtors (written collection) | Generate and send overdue balance statement to customer |
| Contact customer for missing payment (verbal collection) | Call customer to negotiate payment; human judgment required |
| Register promise to pay and monitor | Log customer payment commitment; track compliance and follow up |
| Put account on hold (non-payment) | Apply credit hold to customer account per policy |
| Record dispute and contact relevant department | Log billing dispute; route to finance/legal/sales team |
| Resolve dispute | Investigate and resolve customer invoice dispute |
| Manage non-collectables — provision, write-offs, reclassification | Calculate bad debt provision; initiate write-off or legal referral |

---

#### L3: Cash Application `[APQC 9.2.3]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → Cash Application Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Cash Application SLAs
> _Judgment:_ `fa_judgment.md` → Unmatched Payment Handling Rules

##### L4: Cash Application
| L5 Activity | Description |
|---|---|
| Maintain cash application internal standards / policies | Review and update cash application policy |
| Download bank statement from website | Retrieve bank statement file from banking portal |
| Post payments to customer account | Record matched payments in AR subledger |
| Check completeness of payments | Verify all expected payments are reflected in bank statement |
| Match the invoices and payments | Apply received payments against open invoices using remittance data |
| Request remittance advice | Contact customer or bank to obtain missing remittance information |
| Provide coding for unmatched items | Assign provisional GL coding to unmatched payment items |
| Reconcile the bank-related accounts | Reconcile AR postings against bank statement and GL cash accounts |
| Process refunds | Initiate and process customer refund transactions |

---

#### L3: AR Regular Activities `[APQC 9.2.3]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → AR Regular Activity Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → AR Regular Activity SLAs

##### L4: AR Regular Activities
| L5 Activity | Description |
|---|---|
| Review and maintain AR accounts | Periodic AR subledger review — open items, reconciling items, anomalies |
| Book corrections if needed | Post corrective AR entries for mis-applied payments or coding errors |
| Perform AR reconciliation with customer | Reconcile internal AR records against customer statement |
| AR Reporting & Analysis | Prepare AR performance reports — DSO, aging, cash forecast |

---

#### L3: Deductions Accounting `[APQC 9.2.5]`
<!-- skill: fa_ar -->

> _Exceptions:_ `fa_exceptions.md` → Deductions Exceptions
> _Judgment:_ `fa_judgment.md` → Deductions Approval Rules

##### L4: Deductions Accounting
| L5 Activity | Description |
|---|---|
| Maintain deductions / claims internal standards / policies | Review and update deductions policy |
| Research deductions / claims | Investigate basis and validity of customer deductions |
| Resolve deductions / claims | Negotiate resolution with customer; post approved adjustments |
| Deductions accounting | Record approved deductions as adjustments to AR |

---

### L2: General Ledger / Record-to-Report (RtR)

> **GL Domain Policies**
> _Journal Entry Policy:_ `fa_judgment.md` → L2 GL: Journal Entry Policy
> _Reconciliation Policy:_ `fa_judgment.md` → L2 GL: Reconciliation Requirements
> _Close Calendar & Hard Deadlines:_ `fa_benchmarks.md` → L2: Close Calendar
> _Accounting Standards (GAAP/IFRS):_ `fa_judgment.md` → L1: Accounting Standards
> _GL Benchmarks:_ `fa_benchmarks.md` → L2: General Ledger
> _GL Exception Patterns:_ `fa_exceptions.md` → L2: General Ledger

---

#### L3: GL Master Data Management `[APQC 9.3.2]`
<!-- skill: fa_gl -->

> _Exceptions:_ `fa_exceptions.md` → GL Master Data Exceptions
> _Judgment:_ `fa_judgment.md` → GL Master Data Approval Rules
> _Benchmarks:_ `fa_benchmarks.md` → Master Data SLAs

##### L4: GL Master Data (account, cost centre, profit centre, fixed asset)
| L5 Activity | Description |
|---|---|
| Fill in request form | Populate GL master data request — account, cost centre, or profit centre |
| Approve request | Authorise GL master data creation/change per DOA |
| Provide request with underlying documentation | Attach business justification and supporting docs |
| Check for completeness & internal policy compliance | Validate request against chart of accounts policy |
| Create / update / delete GL master data | Execute master data change in ERP |
| Archive as per archiving policies | Store processed request per retention schedule |
| Review for unused master data and follow up | Identify and flag dormant accounts or cost centres for cleanup |

---

#### L3: General Ledger Accounting `[APQC 9.3.2]`
<!-- skill: fa_gl -->

> _Exceptions:_ `fa_exceptions.md` → GL Accounting Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → GL Accounting SLAs
> _Judgment:_ `fa_judgment.md` → Journal Entry Approval Thresholds

##### L4: GL Regular Activities
| L5 Activity | Description |
|---|---|
| Define / maintain internal accounting policies (GAAP/IFRS/Local) | Review and update accounting policies in line with standards |
| Communicate / share accounting policy knowledge | Distribute policy updates to finance team |
| Review / maintain GL accounts and report issues | Scan GL accounts for posting errors, open items, or policy violations |
| Monitor batch input sessions and background jobs | Check ERP batch job status; investigate and resolve failed jobs |
| Monitor and clear items on GL accounts | Clear matched open items on clearing accounts |

##### L4: Journal Entry Processing
| L5 Activity | Description |
|---|---|
| Extract data for journal entry | Pull source data — reports, subledger extracts — needed to prepare JE |
| Provide data for journal entry | Gather supporting data from business units or systems |
| Calculate / fill JE template per internal policy | Compute amounts and populate standard JE template |
| Approve the journal entry | Human approval — agent pre-validates and prepares recommendation |
| Post journal entry (manual/automated) | Post approved journal entry to financial ledger |
| Archive journal entries per internal policy | Store approved JEs with supporting docs per retention schedule |
| Process reverse journal entries | Auto-reverse prior period accruals or adjustments |
| Provide data for accruals | Gather data to support period-end accrual calculation |
| Validate and calculate accruals | Verify accrual basis and compute accrual amounts |
| Post accruals | Post period-end accrual journal entries |
| Provide data for reclassification entries | Source data required for reclassification JEs |
| Validate and post reclassification entries | Confirm reclassification basis and post entries |
| Provide data for adjustment entries | Gather data for period-end corrections or adjustments |
| Validate and post adjustment entries | Confirm adjustment basis and post correcting entries |
| Set up / review recurring journal entries | Ensure standing recurring entries are correct and posting on schedule |

##### L4: Balance Sheet Accounts Reconciliation
| L5 Activity | Description |
|---|---|
| Extract trial balance and select accounts for reconciliation | Pull trial balance; identify accounts requiring period-end reconciliation |
| Analyse amounts and variances on BS accounts | Review balance movements; identify unexplained variances |
| Collect backup documentation | Gather invoices, contracts, statements as reconciliation support |
| Reconcile per internal policies | Match subledger to GL; document differences |
| Identify missing entries and post adjustments | Post correcting JEs for items identified in reconciliation |
| Review and approve reconciliations | Human sign-off on completed reconciliation workpapers |
| Archive reconciliations for audit | Store completed reconciliations per audit retention schedule |

##### L4: GR/IR Clearing and Reconciliation
| L5 Activity | Description |
|---|---|
| Prepare and analyse GR/IR open item report | Extract GR/IR clearing account; identify long-open items by age |
| Follow up on long open items | Contact procurement/warehouse for items open beyond tolerance |
| Resolve long open items | Post adjustment or reversal entries to clear stale GR/IR items |
| Clear GR/IR account | Execute GR/IR clearing run to match goods receipts against invoices |

##### L4: Intercompany Processing
| L5 Activity | Description |
|---|---|
| Process AP and AR intercompany invoices and payments | Record intercompany transactions per intercompany policy |
| Perform netting process | Net offsetting intercompany balances before settlement |
| Confirm balances between counterparties | Agree intercompany balances with counterpart entity |
| Contact counterparties for discrepancies | Chase counterpart to resolve intercompany balance differences |
| Report intercompany disputes | Escalate unresolved intercompany differences to management |
| Resolve intercompany disputes | Agree correction entries with counterpart; post adjustments |
| Perform needed adjustments | Post approved intercompany correction entries |

---

#### L3: Closing & Consolidation `[APQC 9.3.2 / 9.3.4]`
<!-- skill: fa_gl -->

> _Exceptions:_ `fa_exceptions.md` → Period Close Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Close Calendar & Day Targets
> _Judgment:_ `fa_judgment.md` → Close Escalation Rules & Hard-Close vs Soft-Close Policy

##### L4: Month / Quarter End Closing Activities
| L5 Activity | Description |
|---|---|
| Provide period end schedule / month end calendar | Publish close calendar with task owners, deadlines, and system windows |
| Process opening and closing of financial system (AP/AR/FA/MM/GL) | Execute subledger open/close steps in ERP for period-end |
| Perform Forex revaluation and check for errors | Run FX revaluation on foreign currency balances; validate output |
| Analyse profit & loss for missing entries | Review P&L accounts for gaps vs. prior period and budget |
| Review trial balance to ensure balances tally | Validate that trial balance is complete and in balance |
| Perform final reconciliations | Complete all outstanding GL reconciliations before close |
| Set data ready for reporting | Prepare and validate GL data extracts for management reporting |

##### L4: Year End Closing Activities
| L5 Activity | Description |
|---|---|
| Close subledgers and GL period 12 | Execute final close sequence for all subledgers and GL |
| Open year end closing specific periods (13/14/15/16) | Open special periods in ERP for year-end audit adjustments |
| Carry forward vendor & customer balances | Transfer AP/AR closing balances to opening balances in new fiscal year |
| General ledger balance carry forward | Execute GL balance carry-forward to open new fiscal year |
| Balance carry forward — special purpose ledger | Carry forward special purpose ledger balances |
| Balance carry forward — profit centre accounting | Carry forward profit centre balances |
| Carry forward cost centres / commitments | Transfer cost centre budget/commitment balances to new year |
| Carry forward budget internal orders / commitments | Transfer internal order budget balances |
| Carry forward budget projects / commitment projects | Transfer project budget and commitment balances |
| Update PCA distribution cycles | Revise profit centre allocation cycles for new fiscal year |

##### L4: Period End Reporting
| L5 Activity | Description |
|---|---|
| Report financial and non-financial data (monthly/quarterly/yearly) | Generate and distribute standard management reporting pack |
| Perform reconciliations between ERP and reporting systems | Validate ERP GL data matches BI/consolidation tool figures |
| Prepare and post adjustments if needed | Post period-end adjusting entries from reporting review |
| Perform variance analysis | Analyse actual vs. budget/forecast variances; draft commentary |
| Set data ready for consolidation | Prepare and validate entity data files for group consolidation |

##### L4: Consolidation Reporting
| L5 Activity | Description |
|---|---|
| Pull data from reporting tool | Extract consolidated entity data from group reporting tool |
| Contact departments for clarifications | Chase business units for missing data during consolidation |
| Perform group adjustments | Post inter-entity adjustments at group level |
| Perform validation / sanity checks | Run automated validation rules on consolidated data |
| Perform currency translation | Apply period FX rates to translate local balances to group currency |
| Perform reclassifications | Apply group chart of accounts reclassifications to entity submissions |
| Perform eliminations | Eliminate intercompany transactions and balances |
| Submit the consolidated data | Upload finalised consolidated data to reporting/filing system |

---

#### L3: Tax & Statutory Accounting `[APQC 9.9.2]`
<!-- skill: fa_gl -->

> _Exceptions:_ `fa_exceptions.md` → Tax & Statutory Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Tax Filing Deadlines
> _Judgment:_ `fa_judgment.md` → Tax Deductibility Rules & Filing Sign-Off Policy

##### L4: Domestic VAT Return
| L5 Activity | Description |
|---|---|
| Pull VAT data from accounting system and verify with invoices | Extract input/output VAT postings; cross-reference to source invoices |
| Identify and prepare VAT accruals / adjustments | Compute accruals for period-cut invoices and partial exemption adjustments |
| Perform VAT reconciliations | Reconcile VAT control accounts to VAT return figures |
| Approve the calculations | Human sign-off on VAT return before submission |
| Sign and submit VAT return to tax authorities | File VAT return via government portal |
| Perform the VAT payment | Execute payment of VAT liability to tax authority |

##### L4: Foreign VAT Return
| L5 Activity | Description |
|---|---|
| Pull data from accounting system and verify with invoices | Extract foreign VAT postings; verify against source invoices |
| Identify and prepare VAT accruals / adjustments | Calculate foreign VAT adjustments for period cut |
| Perform VAT reconciliations | Reconcile foreign VAT accounts |
| Sign and submit VAT return to tax authorities | File foreign VAT return in relevant jurisdiction |
| Allocate incoming payment to claimed invoices | Apply VAT refund receipt to relevant invoices |

##### L4: CIT Return
| L5 Activity | Description |
|---|---|
| Pull data per each expenditure category | Extract P&L data categorised by tax-deductible expense class |
| Retrieve underlying documentation | Gather invoices, contracts, and supporting docs for CIT schedules |
| Decide on cost deductibility per fiscal regulations | Assess deductibility of each expenditure category — tax judgment required |
| Calculate actual tax amount | Compute CIT liability from taxable income and applicable rate |
| Approve the calculations | Human sign-off on CIT computation before filing |
| Submit the CIT return with fiscal authorities | File corporate tax return via government tax portal |
| Perform tax payment | Execute CIT payment to tax authority |

##### L4: Deferred Tax Calculation
| L5 Activity | Description |
|---|---|
| Extract data from system | Pull temporary timing differences data from GL/tax systems |
| Perform deferred tax calculation | Compute deferred tax asset/liability movements |
| Provide calculation for approval | Package deferred tax workings for controller/auditor review |
| Book deferred tax journal entry | Post deferred tax movement to GL |

##### L4: VAT — Intrastat & Extrastat Reporting
| L5 Activity | Description |
|---|---|
| Pull the required data | Extract trade data for statistical reporting |
| Perform calculation | Compute Intrastat/Extrastat values |
| Approve the calculations | Human sign-off before submission |
| Submit report to tax authorities | File Intrastat/Extrastat report |

---

## Future L2 Domains (placeholder — not yet active)

| L2 | Scope | Status |
|---|---|---|
| FP&A | Budgeting, planning, forecasting, decision support | Future |
| Treasury | Cash management, debt, FX risk, in-house banking | Future |
| Tax | Tax strategy, advisory, compliance beyond VAT/CIT | Future |
| Fixed Assets | Capex, depreciation, physical count | Future |
| Cost Accounting | Profit centre, allocation cycles, product costing | Future |
