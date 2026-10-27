# AgentPro Skill Author — Coding Agent Reference

> Drop this file into Cursor / VSCode / GitHub Copilot / Claude as context.
> Ask: "Create a SKILL.md for a vendor onboarding agent" or
>       "Create an Enterprise_Context.md for our Accounts Payable team"
> The coding agent will follow the exact formats below.

---

## PART 1 — SKILL.md Format

Every agent in AgentPro is a single `SKILL.md` file.
**Location:** `IAF-Agent-Skills/skills/<skill_name>/SKILL.md`

Runtime loaders return the stable `agentos_contracts.Skill` descriptor. The
older `iaf_agent_skills.loader.Skill` path remains a compatibility re-export for
existing authoring tools and partner adapters.

---

## Deterministic Automations Note

If you need a no-LLM sequence of Python programs or shell commands, do not model
it as a `SKILL.md`. Create a Deterministic Automation under
`enterprise_root/tenants/<tenant_id>/automations/<automation_id>.yaml` instead.
Automations allow only `shell`, `python`, and `condition` steps and reject
`skill` actions. See `DETERMINISTIC_AUTOMATIONS.md`.

---

### Complete SKILL.md Template

For skills that process Workstream items, also see
[`WORKSTREAM_SKILL_CONTRACT_GUIDE.md`](WORKSTREAM_SKILL_CONTRACT_GUIDE.md) for
the `case_summary` and `case_insights` contract used by the Analyst Case
Workbench.

```yaml
---
name: <snake_case_name>
version: "1.0"
description: "One sentence — what this agent does, what data it touches, what actions it can take. Used by the router. Keep under 200 chars."
execution_mode: react          # react (default) | workflow | parallel | supervisor | orchestrator | rlm | graph
tools:
  - shell                      # unix commands in sandbox
  - run_sql_query              # SQL on shared databases
  - query_memory               # search knowledge records
  - write_file                 # write content to a file
  - request_human_approval     # pause for human decision
  - invoke_skill               # delegate to another skill
context_file: /shared/contexts/<skill>_context.md   # optional — injected into every call
keywords:
  - primary keyword
  - alternate phrase
  - domain term
  - entity name
business_context:
  domain: "Finance & Accounting"          # top-level domain
  tower: "Procure-to-Pay"                 # business tower
  process: "Accounts Payable"             # business process
  subprocess: "Invoice Processing"        # sub-process
  entity_type: "invoice"                  # primary entity type
  cost_per_exception: 35                  # USD cost of one exception
  sla_days: 3                             # SLA in days
  kpis:
    - name: "Invoice Cycle Time"
      unit: "days"
      target: 3
      direction: "lower_is_better"        # lower_is_better | higher_is_better
    - name: "First-Pass Match Rate"
      unit: "%"
      target: 85
  activities:
    - FetchInvoiceData
    - ValidateInvoice
    - RouteForApproval
  databases:
    ap_invoices:
      location: "/shared/databases/ap_regular.db"
approval_rules:
  default_urgency: medium                 # low | medium | high | critical
  sla_minutes: 120                        # how long approvals can wait
  thresholds:
    - field: "amount"
      operator: ">="
      value: 50000
      reason: "Invoice exceeds $50K approval limit"
      urgency: high
    - field: "discount_percent"
      operator: ">"
      value: 10
      reason: "Discount exceeds 10% policy threshold"
      urgency: medium
  conditions:
    - when: "new_vendor"
      reason: "New vendor invoices require manual review"
      urgency: high
  always_require:
    - "approve_payment"
    - "override_hold"
  never_require:
    - "read_data"
    - "generate_report"
---

# <Skill Display Name>

## Role
You are a <role>. Your job is to <primary purpose>.

## Your Capabilities
- <capability 1>
- <capability 2>

## Data Sources
- **<Database>**: `run_sql_query(database="/shared/databases/xxx.db", query="...")`
- **<Context file>**: `cat /shared/contexts/xxx_context.md`
- **<Policy>**: `cat /shared/policies/xxx_policy.md`

## How to Use Tools

### Database Queries — use run_sql_query (NOT shell + sqlite3)
```
run_sql_query(database="/shared/databases/ap_regular.db", query="SELECT * FROM invoices WHERE status='open'")
```

### File Operations — use shell
```bash
cat /shared/policies/ap_policy.md          # read a policy file
echo "# Report\n\nContent" > /me/reports/report.md   # write a report
mkdir -p /me/tasks                          # create a directory
grep -r "vendor_id" /shared/contexts/       # search context files
```
Use actual UTF-8 characters (✓ ✗ • →) — no heredoc, no printf, no unicode escapes.

### Memory Lookup — use query_memory before answering entity questions
```
query_memory(query="payment terms for Acme Corp")
```

### Human Approval — use request_human_approval for sensitive write operations
```
request_human_approval(
    operation="approve_payment",
    target="vendor INV-2026-0042",
    summary="Approve $75,000 payment to Acme Corp — exceeds $50K threshold"
)
```

### Invoke Another Skill
```
invoke_skill(skill_name="ar_ops", task="Get DSO for customer ACME")
```

## Response Format
- Use markdown tables for lists of records
- Bold key values (amounts, statuses, IDs)
- State which database/file the data came from
- End with: what was found / what action was taken / what the user should do next

## Important Rules
- Always query live data — never guess on financial figures
- Check query_memory before answering questions about specific entities
- Use request_human_approval for any write operation above approval thresholds
- Report exactly what you found; if nothing found, say so clearly
```

---

### Available Tools Reference

| Tool | Use When | Example |
|---|---|---|
| `shell` | File ops, grep, read context/policy files, write reports | `cat /shared/policies/ap_policy.md` |
| `run_sql_query` | Query any shared SQLite database | `run_sql_query(database="...", query="...")` |
| `query_memory` | Look up knowledge records about an entity or rule | `query_memory(query="vendor terms")` |
| `write_file` | Write a structured document or report | `write_file(path="/me/reports/x.md", content="...")` |
| `request_human_approval` | Pause before sensitive writes | `request_human_approval(operation="...", summary="...")` |
| `invoke_skill` | Delegate a sub-task to another skill | `invoke_skill(skill_name="general", task="...")` |

**Never** use `shell` with `sqlite3` for database queries — always use `run_sql_query`.

---

### Execution Modes

| Mode | When to Use | How to Configure |
|---|---|---|
| `react` | Default — open-ended queries, investigation, Q&A | No extra config needed |
| `workflow` | Fixed process steps (always same order) | Add `steps:` block (see below) |
| `parallel` | Fetch from multiple sources simultaneously | Add `steps:` with `depends_on:` |
| `supervisor` | Multi-domain queries needing synthesis | Add `worker_skills:` block |
| `orchestrator` | Sequential multi-skill chaining for one request | Add `worker_skills:` (+ optional `max_steps:`) |
| `rlm` | Reasoning-as-code: computation / multi-tool orchestration | Add `tools:` allow-list; body = the goal. See [RLM_EXECUTION_MODE.md](RLM_EXECUTION_MODE.md) |
| `graph` | Stored governed process (DAG + verifier + convergence) | Add `graph_ref: graph.yaml` + a `graph.yaml`. Author in **Graph Studio**. See [PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md) |

The deployment flag `DYNAMIC_ORCHESTRATOR_ENABLED=false` temporarily disables
only automatic router-selected orchestration and falls back to ReAct. Skill
authors do not add this flag to SKILL.md, and Planned mode remains available.

#### Workflow Mode (fixed steps)
```yaml
execution_mode: workflow
steps:
  - name: fetch
    action: run_sql_query
    description: Fetch open invoices from AP database
  - name: validate
    action: shell
    description: Read validation policy and check rules
    depends_on: [fetch]
  - name: approve
    action: request_human_approval
    description: Pause for manager approval if threshold exceeded
    depends_on: [validate]
  - name: log
    action: write_file
    description: Write audit log to /me/reports/
    depends_on: [approve]
```

Use `{{step_name.output}}` to reference previous step results in the task description.
For `action: skill` workflow steps, the child skill's progress callbacks are
tagged with the parent step id/name and skill name. Workstream Detail uses that
metadata to show useful live and historical execution traces instead of generic
tool rows.

**Conditional branching:**
```yaml
  - name: check_amount
    action: condition
    if: "{{fetch.output}}"
    contains: "amount > 100000"
    then: require_approval
    else: auto_process
```

#### Parallel Mode (concurrent fetches)
```yaml
execution_mode: parallel
steps:
  - name: get_ar
    action: run_sql_query
    description: Fetch AR aging data
    # no depends_on → runs immediately
  - name: get_ap
    action: run_sql_query
    description: Fetch AP outstanding balance
    # no depends_on → runs immediately (concurrent with get_ar)
  - name: combine
    action: skill
    skill: general
    task: "Summarise AR vs AP position: {{get_ar.output}} | {{get_ap.output}}"
    depends_on: [get_ar, get_ap]
```

#### Supervisor Mode (multi-agent)
```yaml
execution_mode: supervisor
worker_skills:
  - name: ar_ops
    task: "Summarise overdue AR above 90 days"
  - name: invoice_processing_ap
    task: "List invoices pending approval"
  - name: general
    # no task → receives original user query
```

---

### context_file vs context_files

Single context file (most skills):
```yaml
context_file: /shared/contexts/ap_context.md
```

Multiple context files (complex skills):
```yaml
context_files:
  - /shared/contexts/ap_context.md
  - /shared/policies/ap_regular_policy.md
  - /shared/Enterprise_Context.md
```

Knowledge Bundle entry point (curated domain wiki):
```yaml
context_file: /shared/knowledge/<bundle_id>/index.md
```

Knowledge Bundles are discovered by convention under `/shared/knowledge/*/`
when the folder contains `manifest.yaml` with `kind: knowledge_bundle` and an
`index.md` entry point. Use them when a skill needs a maintained domain wiki
(runbooks, policies, tables, metrics, APIs) rather than one flat context file.
Approved learning records can be mirrored into matching bundle pages by skill or
tags while `MEMORY.md` remains the operational memory index.

---

### MCP Connections (optional)

```yaml
mcp_connections:
  - name: sap_tools
    type: direct
    transport: streamable_http
    url: http://localhost:8083/mcp
  - name: servicenow
    type: registry
    registry_name: servicenow_tickets
```

---

### Keywords vs Triggers

`keywords` — natural language phrases the router matches:
```yaml
keywords:
  - overdue invoice
  - accounts receivable
  - ar aging
  - payment dispute
  - DSO
```

`triggers` — alternative list format (used in newer skills, same function):
```yaml
triggers:
  - invoice
  - payment
  - vendor invoice
  - three-way match
```

Use specific, domain-relevant terms. Avoid generic words: `report`, `data`, `help`, `query`.

---

### Real Examples

#### Minimal skill (no tools, pure LLM)
```yaml
---
name: policy_explainer
version: "1.0"
description: "Answers questions about company HR and finance policies in plain English"
execution_mode: react
keywords:
  - policy
  - leave policy
  - expense rules
  - hr policy
  - approval threshold
context_file: /shared/policies/hr_finance_policy.md
---

# Policy Explainer

You are an HR and finance policy assistant.

Answer policy questions based on the loaded context file.
Cite the specific policy section when you answer.
If a question is not covered by policy, say so — never guess.
```

#### Database skill (AR operations)
```yaml
---
name: ar_ops
version: "1.0"
description: "Accounts Receivable operations - aging analysis, collections follow-up"
execution_mode: react
tools:
  - run_sql_query
  - shell
  - query_memory
  - request_human_approval
context_file: /shared/contexts/ar_context.md
keywords:
  - overdue invoice
  - accounts receivable
  - ar aging
  - DSO
  - collections
business_context:
  domain: "Finance & Accounting"
  tower: "Order-to-Cash"
  process: "Accounts Receivable"
  entity_type: "receivable"
  sla_days: 5
  databases:
    ar_receivables:
      location: "/shared/databases/ar_receivables.db"
approval_rules:
  default_urgency: medium
  sla_minutes: 120
  thresholds:
    - field: "amount"
      operator: ">="
      value: 50000
      reason: "Write-off exceeds $50K limit"
      urgency: high
  always_require:
    - "write_off"
    - "waive_late_fee"
  never_require:
    - "read_data"
    - "generate_report"
---

# AR Operations Agent

You are an Accounts Receivable Operations Agent.

## Data Source
Query `/shared/databases/ar_receivables.db` using `run_sql_query`.
Read policy from `cat /shared/policies/ar_validation_rules.md`.

## Key Queries
```sql
-- Aging summary
SELECT aging_bucket, COUNT(*) as count, SUM(amount) as total
FROM receivables WHERE status='open' GROUP BY aging_bucket;

-- Overdue customers
SELECT customer_name, SUM(amount) as balance, MAX(days_overdue) as max_days
FROM receivables WHERE status='open' AND days_overdue > 0
GROUP BY customer_name ORDER BY balance DESC;
```

Always check `query_memory` before answering questions about specific customers.
Use `request_human_approval` before any write-offs or payment plan changes.
```

#### Supervisor skill (multi-domain report)
```yaml
---
name: finance_summary
version: "1.0"
description: "Combined AR and AP summary — cross-domain financial position report"
execution_mode: supervisor
keywords:
  - financial position
  - AR AP summary
  - cash flow position
  - combined finance report
worker_skills:
  - name: ar_ops
    task: "Summarise overdue AR by aging bucket, total outstanding"
  - name: invoice_processing_ap
    task: "Summarise open AP by vendor, total payables"
---

# Finance Summary Agent

You receive AR and AP summaries from worker agents.
Synthesise into a combined financial position report:
- Total receivables vs payables
- Net cash flow position
- Top risk items on both sides
- Recommended actions
```

---

## PART 2 — Enterprise_Context.md Format

**Location:** `enterprise_root/tenants/company/shared/Enterprise_Context.md`

Injected into every agent conversation as background context. Tells agents: who we are, our systems, our data, our terminology.

```markdown
# Enterprise Context — <Company Name>

## Company Overview
<Company Name> is a <industry> company.
Primary business: <what the company does in 1-2 sentences>.

## Organizational Structure
- **Finance & Accounting**: AP, AR, General Ledger, FP&A
- **Operations**: <relevant departments>
- **IT**: <relevant teams>

## Core Systems
| System | Purpose | How Agents Access |
|---|---|---|
| SAP S/4HANA | ERP — invoices, POs, GL | REST API via credentials.yaml |
| ServiceNow | IT tickets, approvals | REST API via credentials.yaml |
| <Your System> | <Purpose> | <Access method> |

## Key Entities and Terminology

### Vendors / Suppliers
- **Vendor**: External company supplying goods or services
- **Vendor Master**: Central record — details, bank info, payment terms
- **Active/Blocked/On Hold**: Vendor payment status values
- **Vendor ID format**: V-<NNNN> (e.g., V-1042)

### Invoices
- **Invoice**: Request for payment from a vendor
- **PO (Purchase Order)**: Internal authorization to purchase
- **3-Way Match**: Invoice ↔ PO ↔ Goods Receipt must align before payment
- **Invoice ID format**: INV-<REGION>-<YYYY>-<NNNN>

### Payments
- **Payment Run**: Batch payment execution (weekly, every Thursday)
- **Payment Terms**: NET30, NET60 — pay within N days of invoice date

## Data Locations
| Data | Virtual Path | Format |
|---|---|---|
| AP Invoices | /shared/databases/ap_regular.db | SQLite |
| AR Receivables | /shared/databases/ar_receivables.db | SQLite |
| Vendor Master | /shared/databases/vendor_master.db | SQLite |
| AP Policy | /shared/policies/ap_regular_policy.md | Markdown |
| AR Policy | /shared/policies/ar_validation_rules.md | Markdown |

## Business Rules and Policies

### Approval Thresholds
- Invoices < $10,000: Auto-approve if 3-way match passes
- Invoices $10,000–$50,000: Manager approval required
- Invoices > $50,000: Director + Finance approval required

### Payment Rules
- Payments run Thursday 2pm (weekly cycle)
- Blocked vendors cannot receive payment until unblocked
- Duplicate invoices (same vendor + amount + date ±3 days): auto-rejected

## Fiscal Calendar
- Fiscal year: Jan 1 – Dec 31
- Month-end close: Last 3 business days of each month

## What Agents Must Never Do
- Approve payments without HITL approval flow
- Share individual employee salary or personal data
- Modify Vendor Master without manager approval
- Execute bulk operations without explicit user confirmation
```

---

## PART 3 — Other Context Files

### Skill-Specific Context
**Location:** `enterprise_root/tenants/company/shared/contexts/<skill>_context.md`

Include only data relevant to one skill. Database schemas, business rules, SLAs for that domain.

### Policy Files
**Location:** `enterprise_root/tenants/company/shared/policies/<policy_name>.md`

```markdown
# Invoice Validation Policy

## Duplicate Check
Duplicate = same vendor_id + same amount + invoice_date within 7 days.
Action: Auto-reject and notify AP team.

## 3-Way Match Tolerance
PO amount must be within 2% of invoice amount.
GR (Goods Receipt) must exist and be dated before invoice date.

## Credit Limit Check
If vendor outstanding balance > credit_limit: hold for manual review.
```

### Entity Guide
**Location:** `enterprise_root/tenants/company/shared/entity_guide.md`

Helps the router extract entity references from user queries.

```markdown
# Entity Recognition Guide

## vendor
Examples: "Acme Corp", "TechSupplies Ltd", "V-1042"
Do NOT extract: generic words like "a vendor" or "the supplier"

## invoice
Examples: "INV-US-2026-0042", "invoice 42", "the January invoice from Acme"
Do NOT extract: "an invoice" without a specific reference

## purchase_order
Examples: "PO-2026-887", "purchase order 887"
```

---

## PART 4 — Skill Registration

After saving `SKILL.md`, register in `IAF-Agent-Skills/skills/_index.yaml`:

```yaml
  your_skill_name:
    description: "Copy description from SKILL.md frontmatter exactly"
    category: operations       # operations | implementation | discovery | itops | platform
    keywords:
      - keyword one
      - keyword two
    status: active             # active | draft | deprecated
```

Then restart the server: `python3 IAF-Agent-Studio/server.py`

**Or** use the **create_skill** agent in chat — it writes the files and registers the skill automatically.

---

## PART 5 — Coding Agent Checklist

When asked to create a SKILL.md:

1. Use `snake_case` for `name` — no spaces or hyphens
2. Keep `description` under 200 chars — the router reads this
3. List 6–12 `keywords` that users would naturally type
4. Only include tools the skill actually needs
5. Use `execution_mode: react` unless steps are truly fixed in order
6. Include `business_context` for any finance/ops/IT skill
7. Include `approval_rules` if the skill can write or modify data
8. Set `context_file` to the most relevant context markdown
9. Write the body as instructions to an LLM — not code
10. Include actual SQL queries and shell commands with correct paths
11. End with a "Response Format" or output guidance section

When asked to create an Enterprise_Context.md:

1. Fill ALL sections — no template placeholders in production
2. Use real system names, real ID formats, real approval thresholds
3. Data Locations table must have exact virtual paths for `run_sql_query`
4. Keep "What Agents Must Never Do" — it's a safety guardrail
5. Fiscal calendar and close dates matter for time-sensitive agents
