# Enterprise Root — Data Schemas

## Overview

IAF AgentPro stores data in five formats: JSONL files (append-only event logs), SQLite databases, Markdown files, JSON index files, and YAML configuration. This document describes the schema for each.

---

## JSONL Files (Append-Only Logs)

All JSONL files use newline-delimited JSON — one JSON object per line. They are append-only: old records are never modified, only new records are added.

### Conversation History (`memory/history/{YYYY-MM-DD}/{session_id}.jsonl`)

One file per session per day. Each line is one conversation turn.

```json
{
  "timestamp": "2026-04-13T09:23:41.123456",
  "user_id": "demo",
  "session_id": "demo_20260413_092341_a1b2c3",
  "skill": "ar_ops",
  "user_input": "Show overdue invoices for ACME Corp",
  "response": "Found 3 overdue invoices for ACME Corp totalling $45,200...",
  "response_summary": "3 overdue invoices totalling $45,200",
  "response_summary_llm": null,
  "tool_calls": [
    {
      "tool": "shell",
      "command": "grep -r 'ACME' /shared/contexts/p2p_context.md",
      "result_preview": "ACME Corp: Net 60 payment terms..."
    }
  ],
  "trace_id": "25cd0447d9da4ef58298751b6e887739",
  "routing": {
    "method": "keyword",
    "confidence": 0.94,
    "is_continuation": false,
    "alternatives": []
  },
  "entity": "vendor:acme_corp",
  "stakeholders": null,
  "decision": null,
  "context_used": {
    "facts_referenced": ["ACME Net 60 terms"],
    "data_sources": ["/shared/contexts/p2p_context.md"],
    "short_term_turns": 2,
    "prior_skill": null
  },
  "outcome": {
    "status": "success",
    "processing_time_ms": 3240,
    "tools_executed": 2,
    "tool_errors": 0,
    "human_intervention": false,
    "feedback": null
  },
  "learning_signals": null
}
```

| Field | Description |
|---|---|
| `session_id` | `{user_id}_{YYYYMMDD}_{HHMMSS}_{6hex}` composite key |
| `skill` | Skill that handled this turn |
| `trace_id` | Correlates with `traces.db` execution traces |
| `routing.method` | `keyword`, `semantic`, `forced`, `continuation`, `planned` |
| `routing.is_continuation` | True if this continues the previous skill |
| `context_used.data_sources` | Virtual paths of context files accessed |
| `outcome.human_intervention` | True if a HITL approval was required |
| `learning_signals` | Extracted learning signals (thumbs_down, correction, etc.) |

---

### Knowledge Records (`memory/context_graph/knowledge.jsonl`)

Layer 2 memory — facts, rules, and patterns the agent has learned.

```json
{
  "id": "k_20260413_x7y8z9",
  "ts": "2026-04-13T09:23:41.123Z",
  "type": "rule",
  "summary": "ACME Corp requires PO approval for invoices above $50,000",
  "status": "confirmed",
  "source": "user_confirmed",
  "user_query": "What is ACME's approval threshold?",
  "skill": "invoice",
  "entity_keys": ["vendor:acme_corp"],
  "applies_when": "invoice vendor is ACME Corp AND amount > 50000",
  "tags": ["approval", "vendor", "po"],
  "written_to": "/shared/contexts/p2p_context.md",
  "provenance": {
    "episode_id": "ep_20260413_a1b2c3",
    "session_id": "demo_20260413_092341_a1b2c3",
    "user_id": "demo",
    "confirmed_by": "demo",
    "confirmed_at": "2026-04-13T09:25:00Z"
  },
  "lifecycle": {
    "use_count": 12,
    "last_used": "2026-04-13T09:23:41Z",
    "expires_at": null,
    "superseded_by": null
  }
}
```

**Knowledge types:**

| `type` | When used | Example |
|---|---|---|
| `rule` | Business policy or constraint | "Net 60 payment terms for ACME" |
| `exception` | One-time override | "INV-001 approved despite policy" |
| `preference` | User working style | "Always show amounts in USD" |
| `workaround` | Known system fix | "Use manual entry when EDI fails" |
| `pattern` | Recurring behaviour | "DSO for large customers ~45 days" |
| `correction` | Agent was wrong, user corrected | "Vendor ID is V-1042 not V-1024" |
| `alias` | Abbreviation mapping | "AR = Accounts Receivable" |
| `fact` | Static reference | "Payment cutoff is 3pm ET Fridays" |
| `skill_pattern` | Routing hint | "Always use ar_ops for disputes" |
| `workflow_trace` | Captured workflow | "Month-end close: 4 steps" |

**`status` values:** `pending_review`, `confirmed`, `archived`

**`source` values:** `user_confirmed`, `user_taught`, `nightly_batch`, `thumbs_down`, `learn_command`, `inferred`

---

### Tool Execution Log (`memory/learnings/{skill}/tool_execution.jsonl`)

Per-skill tool call recording for learning and analytics.

```json
{
  "timestamp": "2026-04-13T09:23:41.844791",
  "session_id": "demo_20260413_092341_a1b2c3",
  "user_id": "demo",
  "type": "tool_execution",
  "skill": "ar_ops",
  "content": {
    "tool": "shell",
    "command": "grep -r 'overdue' /shared/databases/",
    "executed": true,
    "has_error": false,
    "result_preview": "Found 3 records..."
  }
}
```

---

### Agent Error Log (`memory/learnings/{skill}/agent_error.jsonl`)

Captured when the agent encounters an error during execution.

```json
{
  "timestamp": "2026-04-13T06:11:46.871614",
  "session_id": "scheduler_20260413_061039_97150c",
  "user_id": "scheduler",
  "type": "agent_error",
  "skill": "general",
  "content": {
    "query_preview": "Say hello with current time",
    "error_type": "APIConnectionError",
    "error_message": "Connection error."
  }
}
```

---

### Audit Log (`agents/{agent_id}/.audit/commands_{YYYY-MM-DD}.jsonl`)

Every shell command executed by SafeKernel. Not accessible via virtual paths — admin-only.

```json
{
  "timestamp": "2026-04-13T09:23:41.236116+00:00",
  "command": "cat /me/profile.md",
  "output_preview": "# Agent Profile: demo...",
  "success": true,
  "duration_ms": 7
}
```

Rotation policy: compressed to `.gz` after 1 day, deleted after 30 days.

---

## SQLite Databases

### `auth_users.db` (per tenant)

User authentication store. Tables:

**`auth_users`**
```sql
CREATE TABLE auth_users (
    user_id              TEXT PRIMARY KEY,
    email                TEXT UNIQUE NOT NULL,
    display_name         TEXT NOT NULL,
    role                 TEXT NOT NULL DEFAULT 'user',
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TEXT NOT NULL,
    last_login           TEXT,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    password_changed_at  TEXT,
    mfa_enabled          INTEGER NOT NULL DEFAULT 0,
    provider             TEXT NOT NULL DEFAULT 'local',
    groups               TEXT NOT NULL DEFAULT '[]',
    iaf_rbac_managed     INTEGER NOT NULL DEFAULT 0,
    must_change_password INTEGER NOT NULL DEFAULT 0
)
```

**`auth_passwords`** — password hashes stored separately from the user record
```sql
CREATE TABLE auth_passwords (
    user_id       TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id) ON DELETE CASCADE
)
```

---

### `knowledge_index.db` (per agent)

SQLite FTS5 index for knowledge records + entity registry + vector embeddings.

**`fts_knowledge`** — full-text search index for knowledge records
```sql
CREATE VIRTUAL TABLE fts_knowledge USING fts5(
    id,
    summary,
    knowledge_type,
    skill,
    entities_text,
    applies_when,
    user_query,
    source,
    applies_to_text,
    tokenize='porter unicode61'
)
```

The index also defines parallel FTS5 tables `fts_episodes` (episode search) and
`fts_entities` (entity alias lookup), plus `knowledge_vectors`, `episode_vectors`,
`process_relationships`, and `plan_cache` tables.

**`entity_registry`** — ontology tree
```sql
CREATE TABLE entity_registry (
    node_id       TEXT PRIMARY KEY,
    node_type     TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    parent_id     TEXT,
    skill_name    TEXT,
    embedding     BLOB,
    metadata_json TEXT DEFAULT '{}',
    aliases_json  TEXT DEFAULT '[]',
    updated_at    TEXT NOT NULL
)
```

**`entity_xref`** — knowledge ↔ entity cross-reference
```sql
CREATE TABLE entity_xref (
    entity      TEXT NOT NULL,
    record_id   TEXT NOT NULL,
    record_type TEXT NOT NULL DEFAULT 'knowledge',
    PRIMARY KEY (entity, record_id)
)
```

**`routing_signal_log`** — routing analytics
```sql
CREATE TABLE routing_signal_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT DEFAULT CURRENT_TIMESTAMP,
    query_text              TEXT,
    entity_hint             TEXT,
    entity_confidence       REAL,
    process_hint            TEXT,
    process_matches_json    TEXT,
    signals_agree           INTEGER,
    routed_skill            TEXT,
    resolved_entities_json  TEXT
)
```

---

### `traces.db` (shared, ~15 MB)

Execution traces for observability.

**`traces`**
```sql
CREATE TABLE traces (
    id          TEXT PRIMARY KEY,   -- UUID trace_id
    tenant_id   TEXT,
    user_id     TEXT,
    session_id  TEXT,
    skill       TEXT,
    query_preview TEXT,
    status      TEXT,               -- success | error | pending
    started_at  TEXT,
    ended_at    TEXT,
    duration_ms INTEGER
)
```

**`spans`**
```sql
CREATE TABLE spans (
    id          TEXT PRIMARY KEY,
    trace_id    TEXT NOT NULL,
    type        TEXT,               -- tool_call | llm_call | routing
    name        TEXT,
    started_at  TEXT,
    ended_at    TEXT,
    duration_ms INTEGER,
    input_json  TEXT,
    output_preview TEXT,
    error       TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(id)
)
```

---

### `twin_telemetry.db` (shared, ~1.5 MB)

Agent performance telemetry for the Digital Twin dashboard.

**`task_events`**
```sql
CREATE TABLE task_events (
    id          TEXT PRIMARY KEY,
    event_type  TEXT,               -- task_started | task_completed | task_error
    task_id     TEXT,
    user_id     TEXT,
    skill       TEXT,
    duration_ms INTEGER,
    success     INTEGER,
    timestamp   TEXT
)
```

**`skill_metrics`** — aggregated per-skill stats
```sql
CREATE TABLE skill_metrics (
    skill       TEXT PRIMARY KEY,
    total_calls INTEGER,
    success_count INTEGER,
    error_count INTEGER,
    avg_duration_ms REAL,
    total_cost_usd REAL,
    last_used   TEXT
)
```

---

### Business Databases (shared)

> **Note:** The business databases below are **illustrative/legacy examples** of domain data shapes. The specific files named here (`ap_regular.db`, `ar_receivables.db`, `cmdb.db`) are **not shipped** and may not exist in a given deployment — business data is seeded per engagement. For the databases actually present under `shared/databases/` (e.g. `evidence.db`, `fpna.db`, `r2r.db`, `rl.db`, `traces.db`, `twin_telemetry.db`, `command_center.db`, `automation_runtime.db`, `workstream_runtime.db`), see [directory_structure.md](directory_structure.md).

**`ap_regular.db`** — Accounts Payable
```
Tables: ap_transactions (234 rows), purchase_orders (88 rows),
        vendors (15 rows), goods_receipts (56 rows),
        ap_account_balances (6 rows), debit_balances (6 rows),
        corrections_log (17 rows)
```

**`ar_receivables.db`** — Accounts Receivable
```
Tables: customer_accounts, invoices, payments, disputes, collections
```

**`cmdb.db`** — IT Configuration Management Database
```
Tables: assets, servers, services
```

Schema documentation is auto-generated as `{db_name}_schema.md` alongside each database file.

---

## JSON Index Files

### `conversations_index.json`

Session directory for the conversations panel.

```json
{
  "sessions": [
    {
      "session_id": "demo_20260413_092341_a1b2c3",
      "title": "ACME overdue invoice analysis",
      "first_message": "Show overdue invoices for ACME Corp",
      "created_at": "2026-04-13T09:23:41Z",
      "last_active_at": "2026-04-13T09:28:15Z",
      "turn_count": 5,
      "skills_used": ["ar_ops", "invoice"],
      "status": "active"
    }
  ]
}
```

### `master_index.json`

Topic and entity index for session discovery.

```json
{
  "sessions": {},
  "topic_index": {},
  "entity_index": {},
  "last_updated": "2026-04-13T09:23:41Z"
}
```

### `context_registry.json`

Context Manager item registry. See [multitenant_design.md](multitenant_design.md) for schema.

### `context_tree_cache.json`

Cached LLM-clustered tree view of context items. Invalidated after 1 hour.

```json
{
  "tree": {
    "id": "__root__",
    "label": "Enterprise Context",
    "icon": "🗂",
    "type": "root",
    "children": [
      {
        "id": "__grp_document__",
        "label": "Documents",
        "icon": "📄",
        "children": [...]
      }
    ]
  }
}
```

---

## Markdown Files

### User Profile (`users/{user_id}/profile.md` or `agents/{agent_id}/users/{user_id}/profile.md`)

Free-form markdown with structured sections:

```markdown
# Global Profile: {user_id}

## Identity
- **User ID:** demo
- **Name:** 
- **Employer:** 
- **Role:** 
- **Timezone:** 

## Communication Style

## Technical Context

## Known Facts

## Pet Peeves

---
*Last updated: 2026-04-13*
```

### Entity Memory (`shared/entities/{entity_id}.md`)

Per-entity knowledge, rules, and status:

```markdown
# Entity: ACME Corp (VND-103)

## Status
- Active vendor
- Net 60 payment terms
- PO required for invoices > $50,000

## Key Contacts
- AP Contact: Jane Smith (jane@acme.com)

## Rules & Exceptions
- [rule] 3-way match required for all ACME invoices
- [exception] INV-001 approved manually on 2026-02-10

## History
- Onboarded: 2024-01-15
- Last invoice: 2026-04-01
```

### MEMORY.md (`agents/{agent_id}/memory/MEMORY.md`)

Auto-generated knowledge index (regenerated by `memory_md.regenerate_memory_md()`). Max 500 lines. Not for manual editing.

```markdown
# Memory Index
<!-- auto-generated — do not edit manually -->
<!-- last updated: 2026-04-13T09:23:41 -->

## Org State
**org:p2p** [org/p2p_context.md] — 3 entries
  - [rule] Always ask if I want to create PDF from mermaid
  - [fact] 3D Systems is an active P2P client
```

---

## YAML Configuration

### `entity_validation.yaml`

Controls entity auto-registration:

```yaml
entity_types:
  - vendor
  - customer

allowlist:
  - "Acme Supplies"
  - "Northbridge Bank"
  - "Ferncross Bank"

blocklist_extra: []

entity_memory:
  enabled: true
  storage_dir: "entities"
  id_patterns:
    - '^[A-Z]{2,6}-\w+'   # Matches VND-103, CUST-001
```

### `kpi_queries.yaml` (in `shared/`)

Predefined SQL queries for business KPI metrics. Format:

```yaml
kpis:
  - id: dso
    label: Days Sales Outstanding
    skill: ar_ops
    query: |
      SELECT AVG(julianday('now') - julianday(invoice_date)) as dso
      FROM invoices WHERE status = 'unpaid'
```

---

## Data Relationships

```
Conversation Turn (history/*.jsonl)
    │ trace_id
    └────────────> Execution Trace (traces.db)
    │                    │ spans
    │                    └────> Tool Call Spans

    │ episode_id (if learning signal extracted)
    └────────────> Knowledge Record (context_graph/knowledge.jsonl)
                         │ entity_keys
                         └────> Entity Registry (knowledge_index.db)
                                      │ entity_xref
                                      └────> Cross-reference to records
```

This chain enables the three-tier knowledge retrieval:
1. Entity exact match (entity_xref → knowledge records)
2. Semantic search (embedding vectors)
3. FTS5 keyword fallback (knowledge_fts)
