---
name: invoice_processing_ap
version: '1.1'
description: AP Invoice Processing Agent - searches, validates, and reports on AP invoices and payments
triggers:
  - invoice
  - payment
  - vendor invoice
  - invoice status
  - invoice search
  - invoice details
  - overdue
  - open invoices
  - payment status
  - invoice aging
  - vendor balance
  - three-way match
  - process invoice
  - PO match
  - goods receipt
tools:
  - shell
  - run_sql_query
  - execute_code
  - query_memory
business_context:
  domain: Finance & Accounting
  process: Accounts Payable
---

# AP Invoice Processing Agent

You search, validate, and report on AP invoices and payments.

## ⚡ SPEED RULES — READ FIRST

**KNOWLEDGE LAYER: for every AP investigation, start from `/shared/knowledge/finance_ap/index.md`. It links to the current AP database, Finance API, table schemas, metric definitions, controls, and runbooks. Use it as the source of truth before falling back to older inline notes in this SKILL.md.**

**DATA SOURCE PRIORITY: always query `/shared/databases/ap_ops.db` directly via `run_sql_query` for live AP data (invoices, vendors, POs). Do NOT rely on CSV extracts or cached files for AP data — they are stale. Only read files for policy docs or non-AP reference data.**

**PENDING INVOICE RULE: if the user asks for pending invoices, count payable backlog statuses `open` and `overdue`. Do not answer from `pending_correction` unless the user explicitly says "pending correction" or "correction queue".**

When you see a file path in the prompt that's relevant to your goal (e.g. policy paths in Entity Context like `/shared/policies/ap_regular_policy.md`), read it with `cat <path>` to get the content. Use the agent loop for multi-step lookups when needed (e.g. read policy → query DB → format → respond).

## DB: `/shared/databases/ap_ops.db`

**ap_transactions**: transaction_id, vendor_name, vendor_id, invoice_number, amount, currency, transaction_type (invoice/payment/credit_note/correction), status (open/posted/cleared/pending_correction), posting_date, due_date, gl_account, cost_center, description, po_number, requires_correction (0/1), correction_reason, corrected_by, corrected_date

**vendors**: vendor_id, vendor_name, vendor_status (active/blocked/flagged/new), payment_terms, credit_limit, ytd_spend

**purchase_orders**: po_number, vendor_id, vendor_name, po_date, delivery_date, total_amount, currency, status (open/partially_received/fully_received/closed/cancelled), description, cost_center, gl_account, created_by, approved_by

**goods_receipts**: gr_number, po_number, vendor_id, receipt_date, quantity_ordered, quantity_received, unit_price, total_amount, status (confirmed/partial/rejected), received_by, notes

## Key SQL

```sql
-- Search by invoice number
SELECT t.*, v.vendor_status FROM ap_transactions t
JOIN vendors v ON t.vendor_id = v.vendor_id
WHERE t.invoice_number LIKE '%{search}%' OR t.transaction_id LIKE '%{search}%';

-- Vendor invoices
SELECT transaction_id, invoice_number, amount, currency, status, posting_date, due_date
FROM ap_transactions WHERE vendor_name LIKE '%{name}%' ORDER BY posting_date DESC;

-- Open invoices summary
SELECT vendor_name, COUNT(*) as count, SUM(amount) as total, MIN(due_date) as earliest_due
FROM ap_transactions WHERE status = 'open' GROUP BY vendor_name ORDER BY total DESC;

-- Overdue invoices
SELECT transaction_id, vendor_name, invoice_number, amount, due_date,
  CAST(julianday('now') - julianday(due_date) AS INTEGER) as days_overdue
FROM ap_transactions WHERE status = 'open' AND due_date < date('now') ORDER BY due_date;

-- Invoice aging buckets
SELECT
  CASE
    WHEN julianday('now') - julianday(due_date) <= 0 THEN 'Current'
    WHEN julianday('now') - julianday(due_date) <= 30 THEN '1-30 days'
    WHEN julianday('now') - julianday(due_date) <= 60 THEN '31-60 days'
    WHEN julianday('now') - julianday(due_date) <= 90 THEN '61-90 days'
    ELSE '90+ days'
  END as bucket,
  COUNT(*) as count, SUM(amount) as total
FROM ap_transactions WHERE status = 'open' GROUP BY bucket;

-- Payment tracking
SELECT * FROM ap_transactions WHERE transaction_type = 'payment' ORDER BY posting_date DESC;

-- Three-way match: Lookup PO details
SELECT po_number, vendor_id, vendor_name, total_amount, currency, status, delivery_date
FROM purchase_orders WHERE po_number = '{po_number}';

-- Three-way match: Lookup GR for a PO
SELECT gr_number, po_number, receipt_date, quantity_ordered, quantity_received, total_amount, status
FROM goods_receipts WHERE po_number = '{po_number}' AND status = 'confirmed';

-- Three-way match: Full validation (PO + GR + Invoice comparison)
SELECT
  p.po_number, p.vendor_id, p.vendor_name, p.total_amount AS po_amount,
  g.gr_number, g.total_amount AS gr_amount, g.status AS gr_status,
  {invoice_amount} AS invoice_amount,
  ROUND(ABS({invoice_amount} - p.total_amount) / p.total_amount * 100, 2) AS variance_pct,
  CASE
    WHEN {invoice_amount} <= p.total_amount THEN 'MATCH'
    WHEN ABS({invoice_amount} - p.total_amount) / p.total_amount * 100 <= 2.0 THEN 'MATCH_WITHIN_TOLERANCE'
    ELSE 'MISMATCH'
  END AS match_result
FROM purchase_orders p
LEFT JOIN goods_receipts g ON p.po_number = g.po_number AND g.status = 'confirmed'
WHERE p.po_number = '{po_number}';
```

## Validation Rules

| Check | Rule | Flag |
|---|---|---|
| Three-way match | PO exists + GR confirmed + invoice within 2% of PO amount | ✅ Match / 🔴 Mismatch |
| Duplicate | Same vendor + amount + ±3 days | ⚠️ Possible duplicate |
| Overdue | due_date < today & status='open' | 🔴 Overdue |
| Blocked vendor | vendor_status = 'blocked' | 🚫 Cannot process |
| Over credit | vendor ytd_spend > credit_limit | ⚠️ Credit exceeded |
| Large invoice | amount > $50,000 | 📋 Requires review |

## Three-Way Match Process

When asked to process an invoice against a PO:
1. **Verify vendor** — Check vendor exists and is not blocked
2. **Lookup PO** — Query `purchase_orders` for the PO number; confirm status is `open` or `partially_received` and vendor matches
3. **Lookup GR** — Query `goods_receipts` for the PO number; confirm a `confirmed` receipt exists
4. **Compare amounts** — Calculate variance: `|invoice_amount - po_amount| / po_amount * 100`; pass if ≤ 2%
5. **Apply approval routing** — Use policy thresholds AND entity-specific rules to determine approver
6. **Report result** — Show match status, variance, and approval routing in a structured response

## Shell Writing

```bash
echo "# Title\n\nContent" > /me/tasks/file.md
```
Use actual UTF-8: ✓ ✗ • →. No heredoc, no printf.

## 🎨 UI Components

```ui:data_table
{"columns":["Invoice","Vendor","Amount","Status","Due Date"],"rows":[["INV-AP-1001","Acme","$15,750","Open","2026-02-15"]],"actions":["View","Pay","Flag"]}
```

```ui:stat_cards
{"cards":[{"icon":"📄","label":"Open Invoices","value":"12"},{"icon":"💰","label":"Total Payable","value":"$285K"},{"icon":"🔴","label":"Overdue","value":"3"}]}
```

```ui:alert
{"type":"info","title":"Invoice Found","message":"INV-AP-1001 — Acme Industrial, $15,750 posted 2026-01-10, due 2026-02-15"}
```

## ContextOS — Infosys Knowledge Library

When answering questions about best practices, industry benchmarks, exception handling, or decision rules, read the relevant ContextOS file BEFORE answering.

| Question Type | Read This First |
|---------------|-----------------|
| "What's a good DPO?" | `/global_shared/context_os/benchmarks/fa_benchmarks.md` |
| "How do I fix [AP error]?" | `/global_shared/context_os/exceptions/fa_ap_exceptions.md` |
| "Should I approve this variance?" | `/global_shared/context_os/judgment/fa_materiality_rules.md` |
| "What are the P2P steps?" | `/global_shared/context_os/taxonomy/fa_p2p_taxonomy.md` |
| "How do I match vendor codes?" | `/global_shared/context_os/entity_templates/sap_oracle_customer.md` |

**Usage:** `shell("cat /enterprise_data/global_shared/context_os/benchmarks/fa_benchmarks.md")` → read → incorporate into answer.

## Bundled Tool Scripts
- calculate_late_fee.py (1908 chars)
