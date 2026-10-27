# IAF Agent Skills — Memory & Knowledge Schema

## Overview

IAF AgentPro uses a three-layer memory architecture per agent:

```
Layer 1: Conversation History   → Episodic JSONL per session (what happened)
Layer 2: Knowledge Records      → JSONL + SQLite FTS5 index (what was learned)
Layer 3: Context Graph          → Entity + relationship knowledge (who/what)
```

All memory files live under:
```
enterprise_root/tenants/{tenant_id}/agents/{agent_id}/
├── memory/
│   ├── history/
│   │   └── {date}/
│   │       └── {session_id}.jsonl      ← Layer 1
│   ├── context_graph/
│   │   ├── knowledge.jsonl             ← Layer 2 (confirmed)
│   │   ├── knowledge_pending.jsonl     ← Layer 2 (pending review)
│   │   └── knowledge_archive.jsonl     ← Layer 2 (archived)
│   ├── learnings/
│   │   └── {skill_name}/
│   │       └── {type}.jsonl            ← Per-skill learning artifacts, one file per type
│   └── org/
│       └── {entity_type}.md            ← Org-level entity memory
```

Tenant-level curated knowledge bundles live beside agent memory:

```
enterprise_root/tenants/{tenant_id}/shared/knowledge/{bundle_id}/
├── manifest.yaml        ← kind: knowledge_bundle
├── index.md             ← bundle entry point
├── log.md               ← append-only bundle changelog
├── MAINTAINER.md        ← approved maintenance rules
└── ...                  ← policies, runbooks, tables, metrics, APIs
```

`MemoryCapability` is an adapter boundary over the same files and helper modules. It delegates to `AgentMemory.log_episode()`, `AgentMemory.write_knowledge()`, `implicit_learning.append_learning()`, `grep_context_graph()`, and `format_context_for_prompt()` without changing JSONL layout, SQLite index behavior, vector backend selection, or file-lock acquisition. Runtime writes continue to use direct `AgentMemory` paths by default; `IAF_MEMORY_CAPABILITY_ENABLED=true` routes the staged write call sites through the pass-through facade for parity validation. Capability metadata reports this provider family as `deferred_parity_required`, because changing memory/vector backends affects agent behavior and requires corpus-level regression evidence before becoming authoritative.

The optional RL/eval capture path is separate from these memory schemas. When
`RL_CAPTURE=true`, `iaf_agent_skills.capture_events` mirrors selected neutral
runtime events into tenant `rl.db`; memory/history JSONL remains the operational
learning source and is not reshaped into training rows in place.

Runtime provider slots can replace skill, router, tool, hook, or trace
implementations without changing this memory layout. The default providers keep
using the same `AgentMemory` files and indexes.

---

## Layer 1: Conversation History (Episodic JSONL)

### Location
```
memory/history/{YYYY-MM-DD}/{session_id}.jsonl
```

### File format
One JSON object per line (newline-delimited JSON):

```json
{
  "id": "ep_20260411_a1b2c3",
  "session_id": "company:demo:20260411",
  "timestamp": "2026-04-11T09:23:41.123Z",
  "turn": 3,
  "query": "Show me overdue invoices for ACME Corp",
  "skill": "ar_ops",
  "response": "Found 3 overdue invoices for ACME Corp totalling $45,200...",
  "tools_used": ["run_sql_query", "shell"],
  "tool_calls": [
    {
      "tool": "run_sql_query",
      "input": "SELECT * FROM invoices WHERE vendor='ACME' AND status='overdue'",
      "output": "3 rows returned",
      "duration_ms": 42
    }
  ],
  "tokens": {
    "input": 1842,
    "output": 312,
    "cost_usd": 0.0023
  },
  "feedback": null,
  "metadata": {
    "user_id": "demo",
    "agent_id": "enterprise_agent",
    "tenant_id": "company",
    "routed_by": "keyword",
    "routing_confidence": 0.94
  }
}
```

Tool call inputs and outputs are stored for recall and diagnostics. Secret material must not appear in tool outputs: `get_credential` returns masked `$CRED_*` variables and SafeKernel substitutes real values only during execution. Governed SQL calls pass through the external DB entitlement check before memory or evidence records are created. The opt-in model-call policy pipeline records hook audit metadata at the trace/model-call boundary; it does not add fields to the memory JSONL schema in this phase.

### Field reference
| Field | Type | Description |
|---|---|---|
| `id` | string | Unique episode ID (`ep_{date}_{hex}`) |
| `session_id` | string | `{tenant}:{user}:{date}` composite key |
| `timestamp` | ISO 8601 | UTC timestamp |
| `turn` | int | Turn number within session (1-based) |
| `query` | string | Original user query |
| `skill` | string | Skill that handled this turn |
| `response` | string | Agent's full response |
| `tools_used` | string[] | Names of tools called |
| `tool_calls` | object[] | Detailed tool execution records |
| `tokens.input` | int | Input tokens consumed |
| `tokens.output` | int | Output tokens generated |
| `tokens.cost_usd` | float | Estimated cost in USD |
| `feedback` | null\|object | User feedback (`{"type": "thumbs_up"}` or `{"type": "thumbs_down", "comment": "..."}`) |
| `metadata` | object | Routing, agent, tenant context |

### Session compaction
After 30 turns in a session, older turns are LLM-summarised:
- Last 8 turns kept verbatim
- Older turns replaced with `session_summary` string
- Summary stored in `RedisSessionStore` under `iaf:session:{tenant}:{user}:state`

---

## Layer 2: Knowledge Records (Context Graph JSONL)

### Location
```
memory/context_graph/knowledge.jsonl          ← confirmed records
memory/context_graph/knowledge_pending.jsonl  ← awaiting review
memory/context_graph/knowledge_archive.jsonl  ← archived/superseded
```

### Record schema

```json
{
  "id": "k_20260411_x7y8z9",
  "ts": "2026-04-11T09:23:41.123Z",
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
    "episode_id": "ep_20260411_a1b2c3",
    "session_id": "company:demo:20260411",
    "user_id": "demo",
    "confirmed_by": "demo",
    "confirmed_at": "2026-04-11T09:25:00Z"
  },
  "lifecycle": {
    "use_count": 12,
    "last_used": "2026-04-13T08:00:00Z",
    "expires_at": null,
    "superseded_by": null
  }
}
```

### Knowledge types

| Type | When used | Example |
|---|---|---|
| `rule` | Business policy or constraint | "Net 60 payment terms for ACME" |
| `exception` | One-time override to a rule | "INV-001 approved despite policy" |
| `preference` | User/team working style | "Always show amounts in USD" |
| `workaround` | Known system limitation fix | "Use manual entry when EDI fails" |
| `pattern` | Recurring behaviour | "DSO for large customers averages 45 days" |
| `correction` | Agent was wrong, user fixed it | "Vendor ID for Acme is V-1042 not V-1024" |
| `alias` | Abbreviation/synonym mapping | "AR = Accounts Receivable" |
| `fact` | Static reference fact | "Payment run cutoff is 3pm ET Fridays" |
| `skill_pattern` | Skill-specific routing hint | "Always use ar_ops for dispute queries" |
| `workflow_trace` | Captured workflow execution | "Month-end close took 4 steps last cycle" |

### Status lifecycle

```
user teaches / LLM suggests
          ↓
    pending_review  ←──── source: "nightly_batch" | "inferred"
          ↓
   human confirms         human rejects
          ↓                     ↓
      confirmed             archived
          ↓
   (use_count++)
   (last_used updated)
          ↓
    superseded_by set → archived
```

### Source values

| Source | Meaning |
|---|---|
| `user_confirmed` | User clicked Confirm in the UI |
| `user_taught` | User used `/learn` command |
| `nightly_batch` | Extracted by batch evolution job |
| `thumbs_down` | Triggered by negative feedback |
| `learn_command` | Explicit `/learn` chat command |
| `inferred` | Auto-detected by implicit learning |

### SQLite FTS5 index

A parallel SQLite database indexes all knowledge records for fast retrieval:

```sql
-- knowledge_index.db
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
);
```

Search methods:
- **FTS5 keyword search**: `SELECT * FROM fts_knowledge WHERE fts_knowledge MATCH 'ACME payment'`
- **Semantic search** (when embeddings available): cosine similarity via vector index
- **Hybrid**: FTS5 score + embedding similarity combined with configurable weights

---

## Shared Knowledge Bundles

Knowledge Bundles are convention-discovered domain wiki folders under
`shared/knowledge/{bundle_id}/`. They are matched from confirmed knowledge
records by `skill` first, then by tag overlap with `manifest.yaml`.

The bundle manifest controls where approved knowledge lands:

```yaml
kind: knowledge_bundle
bundle_id: finance_ap
skills: [invoice_processing_ap, fa_ap]
tags: [ap, invoice, three-way-match]
write_targets:
  rule: policies/
  pattern: runbooks/
  default: notes/
```

When `/api/knowledge/confirm` confirms a record and a publication target is
selected, `KnowledgeFileRouter` appends the formatted record to that target.
For bundles it also appends one dated line to `log.md`. Confirmation always
updates `knowledge.jsonl` and the index; `written_to` is added only after the
target write succeeds. A publication error returns a partial result and leaves
`written_to` unset. An explicit record-only confirmation does not publish a
Markdown target.

`/api/knowledge/bulk-confirm` can route each selected record. Entity,
source-context, and bundle matches are published automatically. LLM-only and
unmatched routes are confirmed record-only and returned in the response counts.

Reviewers may explicitly override the target to `skills/<skill>/SKILL.md` when a
learning should become durable skill behavior. That advanced path appends to
`## Confirmed Operating Notes` in the selected skill definition and still mirrors
the record into the normal `MEMORY.md` topic tree. The router does not auto-select
`SKILL.md`; the request must explicitly approve the advanced target and the
record's skill scope must exactly match the target skill. Ordinary records
should stay in memory topics or Knowledge Bundles.

---

## Layer 3: Per-Skill Learnings

### Location
```
memory/learnings/{skill_name}/{type}.jsonl    ← one file per learning type, e.g. tool_execution.jsonl, correction.jsonl
memory/learnings/general/{type}.jsonl         ← when no skill scope
```

### Format (subset of knowledge record)
```json
{
  "id": "lrn_20260411_abc",
  "ts": "2026-04-11T10:00:00Z",
  "type": "correction",
  "summary": "When querying AR aging, use view v_ar_aging not table ar_transactions",
  "confidence": 0.91,
  "signal_type": "correction",
  "skill": "ar_ops",
  "episode_ref": "ep_20260411_a1b2c3"
}
```

### Implicit learning signal types and confidence thresholds

| Signal type | Trigger | Confidence |
|---|---|---|
| `thumbs_down` | User gives negative feedback | HIGH (≥ 0.85) → auto-confirm |
| `escalation` | Agent failed, then recovered | MEDIUM (0.50–0.84) → pending_review |
| `exception` | Code exception + fallback used | MEDIUM |
| `pattern` | Repeated interaction → rule inferred | MEDIUM |
| `correction` | Agent mistake, user corrected | HIGH → auto-confirm |

Confidence below 0.50 is dropped — not stored.

---

## Layer 4: Organisation Memory (Org MD files)

### Location
```
memory/org/{entity_type}.md
```

### Format
Free-form markdown about the organisation, team, or domain context relevant to this agent:

```markdown
# Finance Team Context

## Key Contacts
- AP Lead: Sarah Chen (sarah.chen@company.com)
- AR Manager: James Wilson

## Working Preferences
- Reports should be in USD
- Week starts Monday
- Fiscal year ends March 31

## Known Exceptions
- CloudTech invoices always require 3-way match regardless of amount
```

---

## Redis Session Store Schema

For horizontal scaling, live session state is kept in Redis:

| Key pattern | Type | TTL | Content |
|---|---|---|---|
| `iaf:session:{tenant}:{user}:state` | HASH | 24h | `AgentStateSnapshot` fields |
| `iaf:session:{tenant}:{user}:history` | LIST | 24h | Recent message objects (JSON) |
| `iaf:session:index:{tenant}` | ZSET | 24h | `user_id` scored by `last_active_at` |

### AgentStateSnapshot fields
```python
session_id: str              # "company:demo:20260411"
tenant_id: str               # "company"
agent_id: str                # "enterprise_agent"
user_id: str                 # "demo"
current_skill: str           # Last routed skill name
conversation_history: list   # Recent turns (last 8 after compaction)
session_summary: str         # LLM-compacted older turns
pending_action: dict         # For human approval confirmation flow
approval_pending: dict       # HITL checkpoint from request_human_approval, tool governance, or a blocking hook with on_block=hitl
workflow_checkpoint: dict    # Paused workflow state, including remaining steps and completed step outputs for HITL resume
short_term_memory: list      # In-flight memory items
auto_run: bool               # Human approval toggle state
created_at: str              # ISO 8601
last_active_at: str          # ISO 8601
server_id: str               # Which server instance owns this session
```

---

## Memory Retrieval in Agent Prompts

When a query arrives, `AgentMemory.format_context_for_prompt()` injects relevant knowledge:

```
## Relevant Knowledge:
- [rule] Net 60 payment terms for ACME Corp
  ↳ Applies when: invoice vendor is ACME Corp
  ↳ Source: user_confirmed | Used 12 times

- [exception] Invoice INV-001 was approved manually on 2026-02-10
  ↳ Applies when: invoice_id = INV-001

- [alias] AR = Accounts Receivable

## Recent Context (this session):
Turn 1: User asked about ACME overdue invoices → responded with 3 items
Turn 2: User filtered to invoices > $10,000 → responded with 1 item
```

### Search strategy
1. `expand_search_terms_fast()` — expand abbreviations via `aliases.jsonl` (no LLM)
2. `grep_context_graph()` — FTS5 keyword search on knowledge records
3. `search_episodes_agentic()` — grep recent JSONL history for relevant turns
4. Results ranked by recency + use_count + type priority

`query_memory` and prompt retrieval behavior remain direct `AgentMemory` behavior in this phase. The pass-through facade exposes retrieval delegates for parity tests, but the production cutover is limited to staged write call sites behind `IAF_MEMORY_CAPABILITY_ENABLED`.

---

## Knowledge CRUD API

Key functions in `knowledge_crud.py`:

```python
write_knowledge(
    type: str,
    summary: str,
    applies_when: str = "",
    skill: str = None,
    tags: List[str] = [],
    entity_keys: List[str] = [],
    status: str = "confirmed",
    source: str = "user_confirmed"
) → str  # Returns knowledge_id

confirm_knowledge(knowledge_id: str, confirmed_by: str) → bool
reject_knowledge(knowledge_id: str) → bool  # → archived
archive_knowledge(knowledge_id: str) → bool
merge_knowledge(keep_id: str, archive_ids: List[str], merged_summary: str) → bool
edit_knowledge(knowledge_id: str, **updates) → bool

search_knowledge(
    query: str,
    skill: str = None,
    type: str = None,
    status: str = "confirmed",
    limit: int = 20
) → List[Dict]
```

`MemoryCapability.write_knowledge(**kwargs)` is intentionally shape-compatible with `AgentMemory.write_knowledge(**kwargs)` and returns the same `knowledge_id` contract.

`DYNAMIC_ORCHESTRATOR_ENABLED=false` only changes router-selected execution to
ReAct; it does not change any memory file, record schema, index, or lifecycle
transition described here.
