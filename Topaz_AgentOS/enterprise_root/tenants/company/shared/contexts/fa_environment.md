---
name: Finance & Accounting Environment
type: environment
description: ERP system configuration, chart of accounts structure, fiscal calendar, customer portal registry, email inbox config, customer-specific rules, and system integrations for F&A processes
status: active
skills:
  - fa_ap
  - fa_ar
  - fa_gl
---

# Finance & Accounting — Environment & System Configuration
_Last updated: 2026-04-24_

This file is the **first file the agent reads** on every F&A query. It contains system endpoints, credentials patterns, customer portal registry, AR email inbox configuration, and all customer/vendor-specific policy overrides.

> **Configuration:** All URLs, IBANs, and credentials below are environment-specific values. Replace with live tenant values before production activation.

---

## ⚡ ACTIVE SYSTEMS IN THIS ENVIRONMENT — USE THESE

> **READ THIS FIRST.** The SAP/ERP table further down is *reference architecture* and is **NOT reachable** in this environment (those `192.168.29.109:9091` URLs will time out — do not attempt them). The systems below are the **only live, reachable** data sources. For any invoice / AP / AR lookup, use these.

### Finance API (live mock — invoices, vendors, POs, payments)

- **Base URL:** `http://localhost:9092`
- **Auth:** header `X-API-Key: read_demo_key_abc123` (required on every call)
- **Endpoints:**
  - `GET /invoices` — list all invoices
  - `GET /invoices/<INVOICE_ID>` — single invoice (e.g. `INV-3040`); also returns linked purchase order
  - `POST /payments/release` — destructive payment release; requires admin key and HITL approval before execution
  - `GET /health` — service health

```bash
# Look up one invoice (amount, vendor, status, PO)
curl -s -H "X-API-Key: read_demo_key_abc123" http://localhost:9092/invoices/INV-3040
```

For JSON POST requests, always send a JSON object body with an explicit `Content-Type: application/json` header. Do not send JSON payloads as plain form data.

```bash
# Release payment after explicit human approval only
curl -s -X POST -H "X-API-Key: <admin-key>" -H "Content-Type: application/json" \
  http://localhost:9092/payments/release -d '{"invoice_id":"INV-3040"}'
```

### AP / AR databases (read-only via run_sql_query)

Use the `run_sql_query` tool. See `/shared/databases/_index.md` for the full catalogue and schemas.

- **AP (accounts payable):** `run_sql_query(database="/shared/databases/ap_regular.db", query="SELECT ...")`
  - Tables: `vendors`, `purchase_orders`, `goods_receipts`, `invoices`, `payments`
  - `invoices` columns: `invoice_id, vendor_id, po_number, amount_eur, currency, invoice_date, due_date, status, exception_code, has_po`
- **AR (accounts receivable):** `run_sql_query(database="/shared/databases/ar_receivables.db", query="SELECT ...")`

> Databases are **read-only** (SELECT only). To change an invoice's state, use the approval workflow (`request_human_approval`) — not a SQL write.

---

## ERP & Core Financial Systems

> ⚠️ **Reference only — not reachable in this environment.** See the ACTIVE SYSTEMS section above for the live endpoints to actually use.

| System | Role | Instance / URL | API Base | Auth Method | Notes |
|---|---|---|---|---|---|
| **Primary ERP** | AP, AR, GL, Fixed Assets, Purchasing | `http://192.168.29.109:9091` (SAP S/4HANA 2023) | `/sap/opu/odata/sap/` | No auth required | Multi-company code: CC_001, CC_002 |
| **Banking Portal** | Payment file upload, bank statement download | `http://192.168.29.109:9091` | `/api/v2/` | No auth required | Bank statement at `/sap/opu/odata/sap/API_BANKSTATEMENT_SRV/` |
| **Treasury System** | Cash positioning, FX deals, debt management | `http://192.168.29.109:9091` | `/api/treasury/v1/` | No auth required | Integrated with ERP via daily sync |
| **Expense Management** | T&E claims submission and approval | `http://192.168.29.109:9091` (SAP Concur) | `/api/v3.0/` | No auth required | Feeds approved claims to AP payment run nightly |
| **BI / Reporting** | Management reporting, consolidation data extract | `http://192.168.29.109:9091` (SAP Analytics Cloud) | `/api/v1/dataimport/` | No auth required | GL data replicated nightly at 02:00 UTC |
| **Consolidation Tool** | Group accounts consolidation | `http://192.168.29.109:9091` (SAP BPC) | `/xmla/` | No auth required | Entity submission by close day 4; IFRS reporting model |
| **Tax Filing Portal** | VAT, CIT, Intrastat submission | Per jurisdiction — see tax table below | — | Per jurisdiction | |
| **Document Archive** | Invoice and JE document storage | `http://192.168.29.109:9091` (OpenText) | `/otcs/cs.exe/api/v1/` | No auth required | Retention per `fa_judgment.md`; 7-year default |
| **E-Invoicing Platform** | Inbound/outbound e-invoice processing | `http://192.168.29.109:9091` (Tungsten/Peppol) | `/api/invoices/v2/` | No auth required | Peppol BIS 3.0 compliant; UBL 2.1 |
| **API Server** | All F&A endpoints | `http://192.168.29.109:9091` | `/health`, `/ar/aging` | None | Run: `python3 fa_api.py` from IAF_AgentOS_8081 root |

### ERP API Quick Patterns

```bash
# AP: Get open invoices for a vendor
GET /sap/opu/odata/sap/API_SUPPLIER_INVOICE_SRV/A_SuplrInvcItemPurOrdRef
  ?$filter=CompanyCode eq 'CC_001' and SupplierInvoiceStatus eq 'PARKED'
  -H 'Authorization: Bearer $CRED_ERP_API_TOKEN'

# AR: Get open customer invoices
GET /sap/opu/odata/sap/API_CUSTOMER_INVOICE_SRV/A_CustomerInvoice
  ?$filter=CompanyCode eq 'CC_001' and ClearingDate eq ''
  -H 'Authorization: Bearer $CRED_ERP_API_TOKEN'

# GL: Get trial balance for period
GET /sap/opu/odata/sap/API_GLACCOUNTLINEITEM_SRV/A_GLAccountLineItem
  ?$filter=CompanyCode eq 'CC_001' and FiscalYear eq '2026' and FiscalPeriod eq '004'
  -H 'Authorization: Bearer $CRED_ERP_API_TOKEN'

# GL: Check posting period status
GET /sap/opu/odata/sap/API_FI_PERIOD_LOCK_SRV/A_PeriodLock
  ?$filter=CompanyCode eq 'CC_001'
  -H 'Authorization: Bearer $CRED_ERP_API_TOKEN'
```

---

## Company Codes / Legal Entities

| Company Code | Legal Entity Name | Country | Currency | Reporting Standard | VAT Registration |
|---|---|---|---|---|---|
| `CC_001` | Acme Technologies Ltd | United Kingdom | GBP | IFRS + UK GAAP | GB123456789 |
| `CC_002` | Acme Technologies GmbH | Germany | EUR | IFRS + HGB | DE987654321 |

---

## Chart of Accounts

| Account Range | Category | Examples |
|---|---|---|
| 1xxxxx | Assets | 10xxxx = Current assets; 15xxxx = Fixed assets; 19xxxx = Intercompany receivables |
| 2xxxxx | Liabilities | 20xxxx = Accounts payable; 21xxxx = Accruals; 25xxxx = Long-term debt |
| 3xxxxx | Equity | 30xxxx = Share capital; 35xxxx = Retained earnings |
| 4xxxxx | Revenue | 40xxxx = Product revenue; 42xxxx = Service revenue; 45xxxx = Intercompany revenue |
| 5xxxxx | Cost of Sales | 50xxxx = Direct materials; 52xxxx = Direct labour; 55xxxx = Overhead allocated |
| 6xxxxx | Operating Expenses | 60xxxx = Payroll; 62xxxx = T&E; 65xxxx = Professional fees |
| 7xxxxx | Finance items | 70xxxx = Finance income; 71xxxx = Finance costs; 72xxxx = FX gain/loss |
| 8xxxxx | Tax | 80xxxx = Current tax; 81xxxx = Deferred tax |
| 9xxxxx | Internal/statistical | 90xxxx = Intercompany clearing; 95xxxx = Cost allocations |

**Key clearing accounts:**
- AP clearing: `200100`
- AR clearing: `110100`
- GR/IR clearing: `191100`
- Bank clearing: `100200`
- Intercompany AP: `200900`
- Intercompany AR: `110900`
- VAT output: `220100`
- VAT input: `154100`
- CIT payable: `230100`
- Deferred tax: `154200`

---

## Fiscal Calendar

| Item | Value |
|---|---|
| Fiscal year | Calendar year (Jan–Dec) |
| Number of posting periods | 12 regular + 4 special (periods 13–16 for year-end adjustments) |
| Quarter ends | Q1: 31 March · Q2: 30 June · Q3: 30 September · Q4: 31 December |
| Hard close dates | See `fa_benchmarks.md` → Close Calendar |
| System maintenance windows | Sundays 02:00–05:00 UTC — no ERP posting during window |

### Period Open/Close Schedule

| Period | Opens | Hard Close Deadline |
|---|---|---|
| Jan (P01) | 1 Jan | 7 Feb |
| Feb (P02) | 1 Feb | 7 Mar |
| Mar (P03 — Q1) | 1 Mar | 7 Apr |
| Apr (P04) | 1 Apr | 7 May |
| May (P05) | 1 May | 7 Jun |
| Jun (P06 — Q2) | 1 Jun | 7 Jul |
| Jul (P07) | 1 Jul | 7 Aug |
| Aug (P08) | 1 Aug | 7 Sep |
| Sep (P09 — Q3) | 1 Sep | 7 Oct |
| Oct (P10) | 1 Oct | 7 Nov |
| Nov (P11) | 1 Nov | 7 Dec |
| Dec (P12 — YE) | 1 Dec | 15 Jan (following year) |
| Special periods P13–P16 | Open on request | 31 Jan (following year) |

---

## Tax Configuration

| Jurisdiction | VAT / GST Rate (standard) | VAT Filing Frequency | VAT Portal | CIT Rate | CIT Filing Deadline |
|---|---|---|---|---|---|
| United Kingdom (CC_001) | 20% | Quarterly (MTD) | `https://tax.service.gov.uk/vat-through-software` | 25% | 12 months after year-end |
| Germany (CC_002) | 19% | Monthly (Umsatzsteuer-Voranmeldung) | `https://www.elster.de/eportal/` | 15% + 5.5% solidarity surcharge | 31 July (following year) |

---

## Currency Configuration

| Item | Value |
|---|---|
| Group reporting currency | EUR |
| FX rate source | ECB daily rates — loaded to ERP table `TCURR` each morning at 07:00 UTC |
| FX rate type used for posting | Month-average rate for P&L (type `AVG`); closing rate for Balance Sheet (type `CLG`) |
| FX revaluation run | Monthly — after subledger close Day 1, before GL close Day 2 |
| Hedge accounting | Not active |

---

## Payment Configuration

| Item | Value |
|---|---|
| Primary payment method | SEPA Credit Transfer (CC_001: BACS for GBP; CC_002: SEPA XML PAIN.001) |
| Payment run frequency | Tuesday and Thursday each week + on-demand for urgent/rush |
| Bank cut-off time for same-day processing | 14:00 local time |
| Duplicate invoice detection window | 365 days (vendor + amount + invoice date combination) |
| Late payment interest rate | ECB base rate + 8% (EU Late Payment Directive) |

---

## Banking & Cash Configuration

| Item | Value |
|---|---|
| Primary operating account (CC_001 — GBP) | Northbridge Bank UK · IBAN: GB29NBUK40127612345678 · BIC: NBUKGB4B |
| Primary operating account (CC_002 — EUR) | Ferncross Bank · IBAN: DE89370400440532013000 · BIC: FCDBDEFR |
| Bank statement format | camt.053 (CC_002) / BACS input report (CC_001) |
| Automated bank statement import | Daily at 08:00 via SFTP — credential key: `BANK_SFTP_KEY` |
| Cash concentration / pooling | Active — CC_001 and CC_002 pool into group EUR notional pool at Ferncross Bank |

---

## Customer Entity Registry

> For any customer-specific query, find the customer in this table and **read their full entity file** before applying any rules. Each entity file holds portal config, API curl patterns, credential keys, commercial terms, collections overrides, and risk flags. Do NOT apply generic defaults from `fa_judgment.md` without first checking if an entity file override exists.

| Customer ID | Customer Name | Risk Tier | Portal | Entity File |
|---|---|---|---|---|

> No example customers are seeded by default. Add a row per tenant customer plus a matching
> entity file under `contexts/entities/CUST_00x_<name>.md` to activate customer-specific
> overrides (portal, credential key, commercial terms, risk flags).

### How to Load an Entity File

1. Identify the customer from the query (by name, ID, or ERP account number)
2. Look up the entity file path in the registry above
3. Read the full entity file — it contains portal URL, credential key, API curl pattern, commercial terms, collections overrides, and risk flags
4. Apply entity-specific overrides in preference to `fa_judgment.md` defaults

### Portal Status Code Mapping (all portals)

| Portal Raw Status | Normalised Meaning | AR Agent Action |
|---|---|---|
| `APPROVED`, `APPROVED_FOR_PAYMENT`, `PAYMENT_APPROVED` | Approved for payment — not yet paid | Monitor; follow up if past portal ETA |
| `UNDER_REVIEW`, `IN_PROCESS`, `PROCESSING` | Under review at customer AP | Contact customer AP to confirm timeline if overdue |
| `ON_HOLD`, `HELD`, `QUERY_RAISED` | On hold — likely dispute or query | Register dispute in ERP; contact customer to resolve |
| `REJECTED`, `INVALID`, `REJECTED_BY_AP` | Rejected by customer | Identify rejection reason; correct and resubmit |
| `PAID`, `PAYMENT_MADE`, `SETTLED` | Customer records as paid | Cross-reference bank statement; apply if found |
| `NOT_FOUND`, `UNKNOWN` | Invoice not on portal | Verify submission; resubmit via correct channel |

---

## AR Email Inbox Configuration

> The AR agent uses this section to locate and search remittance advice and dispute emails from customers.

| Inbox | Purpose | Connection | Credential Key | Search Approach |
|---|---|---|---|---|
| `ar.remittances@company.com` | Inbound remittance advice from all customers | Microsoft 365 / Graph API | `MS365_AR_INBOX_TOKEN` | Search by invoice number in subject/body; sender domain filter |
| `ar.disputes@company.com` | Customer dispute notifications and billing queries | Microsoft 365 / Graph API | `MS365_AR_INBOX_TOKEN` | Search by customer name or invoice ref in subject |
| `ar.portal-notifications@company.com` | Automated notifications from customer portals (portal rejections, hold alerts) | Microsoft 365 / Graph API | `MS365_AR_INBOX_TOKEN` | Filter by sender domain of known portals; search by invoice ref |

### Email API Shell Patterns (Microsoft Graph)

```bash
# Load token
TOKEN=$(get_credential ms365_ar_inbox token)

# Search ar.remittances inbox for a specific invoice number
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/users/ar.remittances@company.com/messages?\$search=\"INV-2026-0042\"&\$select=subject,from,receivedDateTime,bodyPreview&\$top=10" \
  | python3 -c "
import json,sys
msgs = json.load(sys.stdin).get('value', [])
for m in msgs:
    print(m['receivedDateTime'], '|', m['from']['emailAddress']['address'], '|', m['subject'])
"

# Search ar.disputes inbox for a customer name
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/users/ar.disputes@company.com/messages?\$search=\"GlobalTech\"&\$select=subject,from,receivedDateTime,bodyPreview&\$top=10" \
  | python3 -c "
import json,sys
msgs = json.load(sys.stdin).get('value', [])
for m in msgs:
    print(m['receivedDateTime'], '|', m['from']['emailAddress']['address'], '|', m['subject'], '|', m['bodyPreview'][:80])
"
```

---

## Integration Landscape

| Integration | Direction | Frequency | Format | Credential Key |
|---|---|---|---|---|
| ERP → Bank (payment file) | Outbound | Each payment run (Tue/Thu) | PAIN.001 / SEPA XML | `ERP_API_TOKEN` |
| Bank → ERP (bank statement) | Inbound | Daily 08:00 via SFTP | camt.053 / BACS | `BANK_SFTP_KEY` |
| E-invoice platform → ERP | Inbound | Real-time | UBL 2.1 / Peppol BIS 3.0 | `EINVOICE_API_KEY` |
| Concur (T&E) → ERP (AP) | Inbound | Daily batch 23:00 | Internal API | `CONCUR_API_TOKEN` |
| ERP → SAC (BI Reporting) | Outbound | Nightly 02:00 | Delta extract | `SAC_API_KEY` |
| ERP → SAP BPC (Consolidation) | Outbound | Monthly close day 4 | CSV / XML | `BPC_API_CREDS` |
| ERP → Tax portal (VAT/CIT) | Outbound | Per filing schedule | Jurisdiction-specific | Per jurisdiction |
| ERP → OpenText (Archive) | Outbound | Real-time on posting | PDF / TIFF | `OPENTEXT_API_TOKEN` |

---

## Customer-Specific Rules & Policies

> Customer-specific rules have moved to individual entity files under `contexts/entities/`. See the **Customer Entity Registry** section above for the file index. Read the relevant entity file for any customer-specific commercial terms, collections overrides, portal config, or risk flags.

---

## Tenant-Specific Policy Overrides (Enterprise-Wide)

> These override the generic defaults in `fa_judgment.md` for all customers/vendors unless a customer-specific rule above takes precedence.

| Policy Area | Generic Default | Tenant Override | Effective Date |
|---|---|---|---|
| Invoice approval — ≤ €5,000 | Cost Centre Manager | **£3,000 / €3,500 threshold** — lower limit applied for both company codes | 2024-01-01 |
| DPO target | 35–45 days | **40 days** — group treasury target | 2024-01-01 |
| DSO target | ≤ 35 days | **30 days** — tighter target set by CFO for FY2026 | 2025-12-01 |
| Materiality threshold | 0.5% revenue or €50,000 | **£40,000 / €45,000** (lower of two company codes) | 2024-01-01 |
| Credit hold trigger | 30 days overdue | **30 days** — standard applies (no override) | — |
| Bad debt write-off ≤ €1,000 | AR Manager | **AR Manager** — standard applies | — |
| VAT return frequency (UK) | Monthly | **Quarterly (MTD)** — HMRC MTD quarterly obligation for CC_001 | 2022-04-01 |
| VAT return frequency (DE) | Monthly | **Monthly** — German Umsatzsteuer-Voranmeldung (no override) | — |
| Close hard deadline | Day 5 (management pack) | **Day 4 (management pack)** — CFO requirement, one day earlier than benchmark | 2025-01-01 |
| AP payment run days | Tue + Thu | **Tuesday and Thursday** — standard applies | — |
