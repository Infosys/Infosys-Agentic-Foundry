# IAF AgentPro — Memory and Learning

## Overview

IAF AgentPro uses a three-layer memory architecture that gives agents persistent, evolving knowledge across sessions. Memory is not just conversation history — it includes structured knowledge records, entity relationships, and implicit learnings extracted from agent behaviour.

---

## Memory Architecture

```
Layer 1 — Episodic (What happened?)
  memory/history/{YYYY-MM-DD}/{session_id}.jsonl
  ↑ Written after every conversation turn

Layer 2 — Knowledge Records (What was learned?)
  memory/context_graph/knowledge.jsonl
  memory/context_graph/knowledge_pending.jsonl
  memory/knowledge_index.db (SQLite FTS5 + vectors)
  ↑ Written when the agent learns something new

Layer 3 — Per-Skill Learnings (How did each skill behave?)
  memory/learnings/{skill}/tool_execution.jsonl
  memory/learnings/{skill}/agent_error.jsonl
  ↑ Written after every tool call

Shared Knowledge Bundles (Curated domain wiki)
  shared/knowledge/{bundle_id}/manifest.yaml
  shared/knowledge/{bundle_id}/index.md
  shared/knowledge/{bundle_id}/log.md
  ↑ Confirmed learning can be mirrored here by bundle skill/tag match
```

---

## Layer 1: Episodic History

Conversation history is saved as newline-delimited JSON. Each file is one session; each line is one turn.

**Location:** `memory/history/{YYYY-MM-DD}/{session_id}.jsonl`

Each turn record includes:
- User query and agent response
- Which skill handled it
- Which tools were called (with commands and output previews)
- Routing method and confidence
- Context files accessed
- Processing time, tool errors, human intervention flag, including approvals raised by blocking hooks configured with `on_block: hitl`
- Learning signals extracted

The optional model-call policy pipeline (`MODEL_CALL_PIPELINE_ENABLED=true`) does
not change the episodic JSONL schema. The optional RL/eval capture layer
(`RL_CAPTURE=true`) writes a separate tenant database at
`shared/databases/rl.db` with trajectory, model-call, tool-call, raw reward, and
preference-signal tables. Chat thumbs can also be mirrored into RL
`RewardEvent` rows when the UI sends the response's RL target IDs. This keeps
training/eval datasets independent from AgentPro's operational memory.
RL capture receives neutral runtime events through
`iaf_agent_skills.capture_events`; memory/history files remain the operational
learning store and are not treated as the RL dataset store.

The Private Learning Loop adds a governed eval registry beside RL capture:
tenant eval suites live under `evals/*.yaml`, and answer-key golden sets live
under `golden_sets/*.jsonl`. Trusted Python evaluator manifests/modules live
under `eval_evaluators/{evaluator_id}/` and are invoked by suite id through a
subprocess JSON contract, not imported from arbitrary suite module paths. Golden
cases can be authored directly or promoted from captured trajectories. Confirmed
knowledge and memory remain separate from these eval assets; the eval registry
defines how quality is measured, while the knowledge store defines what the agent
remembers.

Learning Signals is a read-only triage view that summarizes pending-review
knowledge alongside captured feedback signals such as thumbs, corrections, and
eval failures. Reviewers still confirm or reject knowledge through the existing
Knowledge Manager table, so this does not create a second memory lifecycle.

The Trace Value Router adds another read-only signal source to this inbox:
completed eligible RL trajectories can receive advisory destination scores for
`skill`, `context`, `memory`, `golden_eval`, `model_training`, and `debug_only`.
Bulk promotion is the human approval boundary. `skill`/`context`/`memory`
recommendations become pending-review knowledge records; they are not written
directly into `SKILL.md` or shared context files. `model_training` only records
approval for an external training/export pool, and does not train or deploy
weights.

Runtime provider slots (`SKILL_PROVIDER`, `ROUTER_PROVIDER`, `TOOL_PROVIDER`,
`HOOK_PROVIDER`, `TRACE_PROVIDER`) do not change the memory schema. The default
providers keep using the same `AgentMemory` JSONL/SQLite paths described here.

### Session Compaction

After **30 turns** in a single session:
- Last 8 turns kept verbatim
- Older turns summarised by LLM into `session_summary`
- Summary stored in Redis under `iaf:session:{tenant}:{user}:state`

This prevents prompt overflow while preserving recent context.

### Session Continuity

When a user resumes a session (via conversation list or same `session_id`):
1. The session summary is loaded and prepended to the system prompt
2. The last 8 turns of conversation history are restored
3. If the session is a workflow HITL resume, completed workflow step outputs are
   restored so remaining steps can use prior evidence references
3. The agent continues as if the session never ended

---

## Layer 2: Knowledge Records

The knowledge store is the agent's long-term memory. It contains facts, rules, preferences, corrections, and patterns that persist across sessions.

### Writing Knowledge

Three ways knowledge gets written:

**1. User explicitly teaches (`/learn` or "Remember that..."):**
```
User: "Remember that ACME Corp always requires 3-way match"
Agent: [creates knowledge record with type=rule, source=user_taught]
```

**2. User confirms a suggested knowledge:**
```
Agent: "I noticed ACME Corp requires PO approval above $50k — should I remember this?"
User: [clicks Confirm in UI]
Agent: [status changes from pending_review to confirmed]
```

**3. Implicit learning signals:**
- User gives thumbs-down → agent extracts correction
- Agent fails then recovers → pattern captured
- User corrects an error → correction record written

### Knowledge Record Schema

```json
{
  "id": "k_20260413_x7y8z9",
  "ts": "2026-04-13T09:23:41.123Z",
  "type": "rule",
  "summary": "ACME Corp requires PO approval for invoices above $50,000",
  "status": "confirmed",
  "source": "user_confirmed",
  "skill": "invoice",
  "entity_keys": ["vendor:acme_corp"],
  "applies_when": "invoice vendor is ACME Corp AND amount > 50000",
  "tags": ["approval", "vendor", "po"],
  "provenance": {...},
  "lifecycle": {
    "use_count": 12,
    "last_used": "2026-04-13T09:23:41Z"
  }
}
```

### Knowledge Types

| Type | Example |
|---|---|
| `rule` | "Net 60 payment terms for ACME" |
| `exception` | "INV-001 approved despite policy" |
| `preference` | "Always show amounts in USD" |
| `workaround` | "Use manual entry when EDI fails" |
| `pattern` | "DSO for large customers ~45 days" |
| `correction` | "Vendor ID is V-1042 not V-1024" |
| `alias` | "AR = Accounts Receivable" |
| `fact` | "Payment cutoff is 3pm ET Fridays" |

### Knowledge Status Lifecycle

```
user teaches / LLM suggests
        ↓
  pending_review   ← source: "inferred", "nightly_batch"
        ↓
  human confirms          human rejects
        ↓                      ↓
    confirmed             archived
        ↓
  use_count++ on each retrieval
        ↓
  superseded_by set → archived
```

---

## Shared Knowledge Bundles

Knowledge Bundles are tenant-owned, domain-specific wiki folders under
`shared/knowledge/{bundle_id}/`. They are discovered by convention: a folder is
a bundle when it contains both `manifest.yaml` and `index.md` with
`kind: knowledge_bundle`.

Bundles do not replace the learning store. The learning store keeps atomic
records in `knowledge.jsonl` and `MEMORY.md`; bundles keep curated domain pages
such as runbooks, policies, table notes, metrics, and API notes.

### Required bundle files

```
shared/knowledge/{bundle_id}/
  manifest.yaml   # kind, bundle_id, skills, tags, write_targets
  index.md        # entry point used by SKILL.md context_file
  log.md          # append-only bundle changelog
  MAINTAINER.md   # agent rules for approved page maintenance
```

### Approval-gated write flow

Confirmation and publication are separate, visible outcomes. Every successful
confirmation writes the latest record to `knowledge.jsonl` and updates the
FTS/vector index. **Confirm & Write** then publishes the same record to the
selected context, memory-topic, Knowledge Bundle, or explicitly approved
`SKILL.md` target. `written_to` is persisted only after that file write succeeds.
If publication fails, the record remains confirmed but the API/UI reports a
partial result and leaves `written_to` unset.

**Confirm without writing to file** is an explicit record-only action. Bulk
Confirm & Route auto-publishes only deterministic/high-confidence routes
(entity memory, source context, and convention-matched bundles); LLM-only or
unmatched suggestions are reported as confirmed record-only instead of being
silently written to an uncertain file.

This bundle write path is additive and generic:

- No bundle id is hardcoded in platform Python.
- `Enterprise_Context.md` remains the routing map.
- `MEMORY.md` remains the always-loaded operational memory index.
- Bundles are curated wiki pages that skills can read via `context_file`.

The dashboard override picker can also expose `skills/<skill>/SKILL.md` as
`Skill Definition (Advanced)`. Selecting it is explicit only; the platform does
not auto-route ordinary learning into skill definitions. Confirmed records are
appended to `## Confirmed Operating Notes` in the selected `SKILL.md` and are
still mirrored into the normal `MEMORY.md` topic tree. The API requires explicit
advanced-target approval and an exact match between the record's skill scope and
the target skill name.

---

## Layer 3: Per-Skill Learnings

Every tool call made by every skill is recorded in `memory/learnings/{skill}/tool_execution.jsonl`. This enables:

- **Self-evolution analysis**: The evolution engine reads these logs to identify patterns and suggest improvements
- **Implicit learning signals**: Errors and corrections surface as candidates for knowledge records
- **Debugging**: Full history of what tools each skill used and whether they succeeded

---

## Knowledge Retrieval (query_memory tool)

When a skill calls `query_memory(query)`, the agent uses a three-tier search:

### Tier 1 — Entity Exact Match (fastest, highest precision)

If an entity was resolved from the current query (e.g., "ACME Corp" → `vendor:acme_corp`):
```sql
SELECT kv.*
FROM entity_xref ex
JOIN knowledge_vectors kv ON ex.record_id = kv.id
WHERE ex.entity = 'vendor:acme_corp' AND ex.record_type = 'knowledge'
ORDER BY kv.ts DESC
LIMIT 5
```

### Tier 2 — Semantic Search (embedding similarity)

Cosine similarity between query embedding and stored knowledge record embeddings. Returns top K results above a similarity threshold.

### Tier 3 — Broadened Noun Search

When the tiers above are still thin (fewer than 3 records), the query is reduced to its key nouns and re-run through semantic search with a lower score floor.

### Tier 4 — FTS5 Keyword Fallback

Only when every tier above returns nothing, a keyword/FTS5 grep over the full-text search index:
```sql
SELECT * FROM fts_knowledge
WHERE fts_knowledge MATCH 'ACME payment'
ORDER BY rank
LIMIT 10
```

### Context Injection in Prompts

Relevant knowledge is injected into the agent's context:

```
## Relevant Knowledge:
- [rule] Net 60 payment terms for ACME Corp
  ↳ Applies when: invoice vendor is ACME Corp
  ↳ Source: user_confirmed | Used 12 times

- [alias] AR = Accounts Receivable

## Recent Context (this session):
Turn 1: User asked about ACME overdue invoices → 3 items found
Turn 2: User filtered to invoices > $10,000 → 1 item found
```

---

## Implicit Learning Signals

The system automatically extracts learning signals from agent behaviour:

| Signal | Trigger | Confidence | Outcome |
|---|---|---|---|
| `correction` | User corrects agent mistake | HIGH (≥ 0.85) | Auto-confirm |
| `thumbs_down` | User gives negative feedback | HIGH (≥ 0.85) | Auto-confirm |
| `escalation` | Agent failed then recovered | MEDIUM (0.50-0.84) | Pending review |
| `exception` | Code exception + fallback | MEDIUM | Pending review |
| `pattern` | Repeated interaction → rule | MEDIUM | Pending review |

Confidence below 0.50 is **dropped** — not stored. This prevents noise from polluting the knowledge base.

---

## Managing Knowledge

### Via Chat

```
Remember that ACME Corp requires 3-way match for all invoices
```

The agent will create a knowledge record and confirm with you before saving.

### Via Knowledge Panel (Dashboard)

The Knowledge tab shows all pending and confirmed records:
- **Confirm & Write** — confirm and publish to the selected target
- **Confirm without writing to file** — confirm the record/index only
- **Bulk Confirm & Route** — confirm all selected records and publish safe,
  deterministic suggestions; report record-only and failed publications
- **Reject** — archive the record
- **Edit** — modify summary or `applies_when` condition
- **Merge** — combine duplicate records

Read-only dashboard endpoints (`/api/knowledge`, `/api/knowledge/stats`, and
`/api/knowledge/extract-status`) use a lightweight file read model over the
agent memory directory. They do not instantiate `SkillAgent` just to render the
table after restart. Mutating flows such as confirm, reject, edit, learn,
duplicate merge, and batch extraction still go through the runtime memory layer
so indexes, lifecycle updates, and side effects remain consistent.

The `DYNAMIC_ORCHESTRATOR_ENABLED` runtime rollback flag changes only execution
selection. Falling back to ReAct preserves the same knowledge, episodic memory,
and learning persistence paths.

### Via API

```http
POST /api/knowledge/learn
{"summary": "ACME Corp requires 3-way match", "type": "rule", "skill": "invoice"}

POST /api/knowledge/confirm
{"knowledge_id": "k_20260413_abc", "action": "confirm"}
```

---

## Org Memory (Markdown)

Beyond structured knowledge records, agents maintain freeform org context in markdown files:

**Location:** `memory/org/{context_name}.md`

These files are linked from skill `context_file` fields and injected as system context. They contain:
- Process-specific rules that change infrequently
- Vendor or client-specific overrides
- Team preferences and working norms

Updates to org memory take effect immediately (no cache to clear).

---

## Self-Evolution

The Self-Evolution engine analyses agent history and suggests improvements in a four-tier pipeline:

| Tier | What It Does | Runtime |
|---|---|---|
| Tier 1 | Load session history | Seconds |
| Tier 2 | Classify behaviour patterns | ~1 min |
| Tier 3a | Review SKILL.md prompts for gaps | ~2 min |
| Tier 3b | Review Python code for bugs | ~3 min |
| Tier 4 | Generate specific improvement suggestions | ~5 min |

Access via the Evolution tab in the Dashboard, or:

```http
POST /api/evolution/analyze
{"tier": 4, "days_back": 7}
```

**Output includes:**
- Session classification (which skills handled what)
- Gaps identified in skill prompts
- Suggested additions to context files
- Specific prompt improvements with before/after text

## Enterprise API scope

Knowledge and Memory dashboard routes bind tenant, agent, and user scope from
the authenticated principal and enforce resource-level read/write/use/delete
permissions. Client query values remain useful in local development but do not
override JWT tenant or user identity in authenticated deployments.

## World-model context graph

The knowledge index also holds a **directed graph** of business entities and their
relationships — `entity_registry` (nodes) and `process_relationships` (edges). It answers
*relationship / multi-hop* questions ("if this portal breaks, which ERP is exposed?") that a
single table cannot.

- **Nodes** are seeded from `entity_guide.md` (and per-turn `auto_register_entities`).
- **Edges** are written idempotently via `EntityRegistryStore.upsert_relationship` (deterministic
  edge id; FK requires both endpoints to exist, so entities seed first). Two producers:
  (1) the **seeder** parses a Relationships table in `entity_guide.md` → `status='curated'`
  (trusted); (2) with `WORLD_MODEL_LEARN` on, a **per-turn extractor** (`world_model.py`, fed by
  the existing reasoning LLM pass) proposes edges → `status='pending_review'`, confidence-gated.
- **Provenance & lifecycle:** every edge carries `status` (`curated` / `confirmed` /
  `pending_review` / `rejected`), `confidence`, `source`, `created_by`, `valid_from/to`. Reads
  return only `curated`/`confirmed`; `pending_review` is hidden until **promoted**
  (`world_model.promote_relationship`) or **rejected** via governance. Every assertion/decision is
  appended to an append-only `world_events.jsonl` (log-is-truth); `rebuild_graph_from_events`
  reprojects it. Backend chosen by `GRAPH_BACKEND` (relational default; Apache AGE opt-in).
- **Reviewing pending edges (governance UI):** the **Graph Review** surface at `/world-model`
  (`static/world_model_review.html` → `routers/world_model.py`) lists pending edges with their
  triple, confidence and provenance, and lets a reviewer **Promote** (→ `confirmed`, now visible to
  answers) or **Reject** (→ `rejected`, kept as audit). `GET /api/world-model/pending` +
  `POST /api/world-model/{promote,reject}` wrap `world_model.list_pending` /
  `promote_relationship` / `reject_relationship`.
- **Auto-confirm knob:** set `WORLD_MODEL_AUTOCONFIRM_CONFIDENCE` (e.g. `0.95`) to have per-turn
  edges at/above that confidence written directly as `confirmed` (skipping the review queue). Unset
  (default) = every learned edge stays `pending_review` — the safe governance default.
- **Reading:** the agent queries the read-only `graph` db resource with `run_sql_query`
  (1-hop or a bounded recursive CTE) after reading its schema doc
  (`/shared/knowledge/finance_ap/databases/graph.md`) — the same "read the schema, write the SQL"
  pattern used for business databases. In table mode, `collect_context` additionally surfaces
  1-hop edges to the planner automatically. See `tools_reference.md` → "Database access — the
  `run_sql_query` gateway".
- **Isolation:** on Postgres the graph shares the agent's schema with memory tables, so the
  `graph` resource is `read_only` and the gateway drops to the least-privilege role
  `agentos_graph_ro` (SELECT on the two graph tables only) — Postgres denies any attempt to read
  memory tables through the resource.
