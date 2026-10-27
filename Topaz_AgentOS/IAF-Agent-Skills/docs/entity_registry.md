# IAF Agent Skills — Entity Registry

## Overview

The Entity Registry is the ontology-aware entity resolution engine that powers smart routing and context-aware memory retrieval in IAF AgentPro. It maintains a hierarchical tree of business entities (vendors, customers, contracts) alongside the process taxonomy (towers, processes, activities, skills) and resolves entities from natural-language queries in under 50ms.

Every query that arrives at the agent passes through `EntityRegistryStore.collect_context()` before routing — this single call produces both the **WHO** signal (which entity is being discussed) and the **WHAT** signal (which business process domain applies), which the router and planner use to assign the correct skill.

---

## Architecture

```
Query text + optional embedding
          ↓
  EntityRegistryStore.collect_context()
          ↓
  ┌───────────────┬───────────────┐
  │ WHO signal    │ WHAT signal   │
  │ Entity lookup │ Taxonomy match│
  │ (FTS5 first,  │ (keyword →    │
  │  embedding    │  process node)│
  │  fallback)    │               │
  └───────┬───────┴───────┬───────┘
          │               │
          ↓               ↓
   skill_hint        process_hint
   (entity-based)    (process-based)
          │               │
          └───────┬───────┘
                  ↓
           signals_agree?
          ↓         ↓
       Router    Planner
    (single domain) (multi-domain)
```

---

## Ontology Structure

The registry models the business as a tree where every node has a type from the fixed vocabulary:

| Type | Level | Description | Example |
|---|---|---|---|
| `tower` | L1 | Broad organisational domain | "Finance", "Supply Chain" |
| `process` | L2 | Major process area | "Accounts Payable", "Vendor Management" |
| `activity` | L3 | Specific activity | "Invoice Processing" |
| `skill` | L4 | Leaf — maps to a skill handler | "ar_ops", "invoice" |
| `ENTITY_TYPE` | Domain bucket | Category of entities | "vendor", "customer", "contract" |
| `ENTITY` | Instance | Individual entity | "ACME Corp", "INV-2024-001" |

### Example Tree

```
tower:finance
  └─ process:accounts_payable
      └─ activity:invoice_processing
          └─ skill:ar_ops
              └─ ENTITY_TYPE:vendor
                  ├─ ENTITY:vendor_acme_corp
                  ├─ ENTITY:vendor_globex_corp
                  └─ ENTITY:vendor_initech_llc
```

### Node ID Convention

```
tower:finance
process:accounts_payable
activity:invoice_processing
skill:ar_ops
entity_type:vendor
entity:vendor_acme_corp
entity:customer_bofa
```

---

## Database Schema

### `entity_registry` table

```sql
CREATE TABLE entity_registry (
    node_id       TEXT PRIMARY KEY,    -- "vendor:acme_corp"
    node_type     TEXT NOT NULL,       -- tower|process|activity|skill|ENTITY_TYPE|ENTITY
    display_name  TEXT NOT NULL,       -- "ACME Corp"
    parent_id     TEXT,                -- FK → entity_registry.node_id
    skill_name    TEXT,                -- Routing target (leaf nodes only)
    embedding     BLOB,                -- Vector (ada-002 format)
    metadata_json TEXT DEFAULT '{}',   -- Domain context: SLAs, limits, contacts
    aliases_json  TEXT DEFAULT '[]',   -- Alternative names for exact-match lookup
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES entity_registry(node_id)
)
```

### `fts_entities` — Fast keyword search

```sql
CREATE VIRTUAL TABLE fts_entities USING fts5(
    node_id,
    display_name,
    aliases_text,        -- Space-separated aliases for BM25 ranking
    node_type,
    tokenize='porter unicode61'
)
```

### `process_relationships` table

```sql
CREATE TABLE process_relationships (
    id            TEXT PRIMARY KEY,
    from_node     TEXT NOT NULL,       -- FK → entity_registry
    relation      TEXT NOT NULL,       -- "depends_on", "feeds_into", "precedes"
    to_node       TEXT NOT NULL,       -- FK → entity_registry
    condition     TEXT,                -- When relationship applies
    metadata_json TEXT DEFAULT '{}',
    updated_at    TEXT NOT NULL
)
```

### `entity_xref` — Knowledge ↔ Entity cross-reference

```sql
CREATE TABLE entity_xref (
    entity      TEXT NOT NULL,         -- node_id from entity_registry
    record_id   TEXT NOT NULL,         -- id from knowledge_vectors or episode_vectors
    record_type TEXT NOT NULL DEFAULT 'knowledge',  -- 'knowledge' | 'episode'
    PRIMARY KEY (entity, record_id)
)
```

---

## API Reference

### Core Entry Point

**`collect_context(query_embedding=None, query_text=None, threshold=0.75, top_k=3) → Dict`**

The main method called by the agent before every routing decision. Returns a comprehensive dict with both routing signals and entity context.

```python
ctx = entity_store.collect_context(
    query_embedding=cached_embedding,
    query_text="Show overdue invoices for ACME Corp"
)
```

**Return value:**
```python
{
    "resolved_entities": [
        {
            "node_id": "entity:vendor_acme_corp",
            "display_name": "ACME Corp",
            "node_type": "ENTITY",
            "score": 0.95,
            "match_method": "fts5"   # or "alias", "cosine"
        }
    ],
    "skill_hint": "ar_ops",          # Signal 1: WHO
    "skill_confidence": 0.95,
    "process_hint": "ar_ops",        # Signal 2: WHAT
    "process_matches": [
        {
            "node_id": "skill:ar_ops",
            "display_name": "AR Operations",
            "node_type": "skill",
            "matched_alias": "accounts_receivable",
            "skill_name": "ar_ops",
            "child_skills": []
        }
    ],
    "signals_agree": True,           # True|False|None
    "tree_context": [
        {"level": "ENTITY",      "name": "ACME Corp",         "node_id": "entity:vendor_acme_corp", "metadata": {...}},
        {"level": "ENTITY_TYPE", "name": "vendor",            "node_id": "entity_type:vendor",      "metadata": {...}},
        {"level": "activity",    "name": "Invoice Processing", "node_id": "activity:invoice_processing"},
        {"level": "tower",       "name": "Finance",            "node_id": "tower:finance"}
    ],
    "entity_keys_for_xref": {"entity:vendor_acme_corp", "entity_type:vendor", "skill:ar_ops"},
    "process_relationships": [
        "ar_ops PRECEDES ap_processing (when: monthly_close)"
    ]
}
```

---

### Resolution Methods

**`resolve_entities(query_embedding=None, query_text=None, threshold=0.75, top_k=5, node_types=None) → List[Dict]`**

Two-stage resolution:
1. **FTS5 fast path** (~1ms): keyword match against aliases — tries AND (precise) first, falls back to OR (broad)
2. **Embedding fallback** (~50ms): cosine similarity — activates only when FTS5 misses

**`walk_ancestors(node_id: str) → List[Dict]`**

Recursive CTE walk from leaf → root. Returns ordered list (shallowest first):
```python
[
    {"node_id": "entity:vendor_acme_corp", "node_type": "ENTITY",   "display_name": "ACME Corp",          "depth": 0},
    {"node_id": "entity_type:vendor",      "node_type": "ENTITY_TYPE", "display_name": "vendor",          "depth": 1},
    {"node_id": "skill:ar_ops",            "node_type": "skill",    "display_name": "AR Operations",      "depth": 2},
    ...
]
```

**`list_entities(node_type=None, parent_id=None) → List[Dict]`**

List all entities with optional type/parent filter.

**`count() → Dict[str, int]`**

Returns `{"ENTITY": 42, "ENTITY_TYPE": 8, "skill": 12, ...}`

**`get_tree() → Dict`**

Full ontology tree with stats (total_nodes, by_type, skill_linked, total_aliases, total_knowledge_links).

---

### CRUD Operations

**`register_entity(node_id, node_type, display_name, parent_id=None, skill_name=None, metadata=None, aliases=None, embed=True) → bool`**

Upserts a node. Computes embedding for ENTITY and ENTITY_TYPE nodes when `embed=True`. Syncs to FTS5 table.

**`register_batch(nodes: List[Dict]) → int`**

Batch upsert. Returns count of successfully registered nodes.

**`auto_register_entities(entity_names: List[str], skill_name=None) → List[str]`**

Discovers new entities from conversation output. For each name:
1. Try alias resolution (reuse existing if matches)
2. Validate against `EntityValidator` allowlist/blocklist
3. If no match, register as new ENTITY under inferred parent type

Returns list of resolved `node_id`s (existing or newly created).

---

### Search Methods

**`_resolve_by_fts5(query: str, top_k=5) → List[Dict]`**

Fast BM25 keyword match. Returns `match_method='fts5'`, `score=1.0`.

**`_resolve_by_alias(query: str, top_k=5) → List[Dict]`**

Exact-match against `aliases_json` column — checks if query tokens/bigrams match stored aliases. Returns candidates sorted by **longest matching alias length descending** so the most specific canonical entity wins over fragment matches (e.g. "Northfield Foods Corporation" beats a short "Foods" fragment). Returns `match_method='alias'`, `score=1.0`.

**`_resolve_by_taxonomy(query: str) → List[Dict]`**

Matches query words against taxonomy nodes (L1–L4 + skills). Different from entity resolution: finds *which process domain* the query belongs to. Returns nodes ordered by specificity (skill > activity > process > tower).

---

## Integration with Memory Retrieval

### Tiered Knowledge Lookup

When `query_memory` tool is called during skill execution, the knowledge cascade
runs up to four tiers (each augments the previous, later tiers only fire when
results are still thin):

```
Tier 1 — Entity exact match (via entity_xref, fastest, highest precision)
    ↓ augment
Tier 2 — Semantic search on the full query (cosine similarity on knowledge/episode embeddings)
    ↓ when combined results are still thin (< 3)
Tier 3 — Broadened semantic search on key nouns only (lower score floor)
    ↓ only when all tiers above return nothing
Tier 4 — Keyword/FTS5 fallback (grep_context_graph over the knowledge FTS index; JSONL grep for episodes)
```

Tool exposure is still filtered before execution. If a skill also uses `run_sql_query` for tenant databases, SafeKernel now checks the linked `external:db.*` entitlement before SQL rows can be returned or captured as memory/evidence.

Tier 1 uses `entity_keys_for_xref` from `collect_context()`. TIER1 xref hit/miss is logged at INFO level via `query_memory TIER1 episode xref` and `query_memory TIER1 knowledge xref` log lines. The cross-reference join:
```sql
SELECT kv.id, kv.summary, kv.knowledge_type, ...
FROM entity_xref ex
JOIN knowledge_vectors kv ON ex.record_id = kv.id
WHERE ex.entity = ? AND ex.record_type = 'knowledge'
ORDER BY kv.ts DESC
```

### Knowledge → Entity Linking

When a knowledge record is written via `KnowledgeIndexer.upsert_knowledge()`:
1. Entity names extracted from `scope.tags`, `entities`, `entity_keys` fields
2. `auto_register_entities()` resolves or creates entity nodes
3. Record linked in `entity_xref` table for both 'knowledge' and 'episode' record types
4. Taxonomy nodes auto-linked from summary text via `_resolve_by_taxonomy()`

---

## Routing Signal Flow

```
1. Agent.run(query) begins
   ↓
2. Compute query embedding once (cached as _cached_query_embedding)
   ↓
3. entity_store.collect_context(embedding, query) → _entity_context
   ↓
4. Extract signals:
   entity_hint  = ctx["skill_hint"]          # WHO: "ar_ops"
   process_hint = ctx["process_hint"]        # WHAT: "ar_ops"
   signals_agree = ctx["signals_agree"]      # True
   ↓
5. Router uses signals to select skill
   ↓
6. If multi-domain (signals_agree==False):
   → Planner receives full ctx JSON
   → LLM assigns sub-tasks to skills based on entity + process hints
   ↓
7. Skill runs; query_memory tool uses entity_keys_for_xref for tier 1 lookup
```

---

## Routing Signal Log

Every `collect_context()` call is logged for analytics:

```sql
CREATE TABLE routing_signal_log (
    query_text              TEXT,
    entity_hint             TEXT,
    entity_confidence       REAL,
    process_hint            TEXT,
    process_matches_json    TEXT,
    signals_agree           INTEGER,    -- 1=agree, 0=conflict, NULL=incomplete
    routed_skill            TEXT,
    resolved_entities_json  TEXT
)
```

Aggregate metrics from `get_routing_stats()`:
- `process_miss_rate` — % of queries without process_hint
- `entity_miss_rate` — % of queries without entity_hint
- `agreement_rate` — % of queries where both signals matched and agreed
- `recent_misses` — last N queries with no signal match (for ontology gap analysis)

---

## Entity Validation

`EntityValidator` prevents noise from polluting the registry:

**Location:** `enterprise_root/tenants/company/shared/entity_validation.yaml`

```yaml
entity_types:
  - vendor
  - customer

allowlist:
  - "Acme Supplies"
  - "Meridian Trust Bank"

blocklist_extra: []

entity_memory:
  enabled: true
  storage_dir: "entities"
  id_patterns:
    - '^[A-Z]{2,6}-\w+'    # Matches VND-103, CUST-001, etc.
```

Rules:
- Names on allowlist are always accepted
- Names matching `blocklist_extra` or generic words are rejected
- Confidence below 0.50 is dropped — never stored
- `should_add_to_xref()` always allows taxonomy nodes (`apqc:*`, `skill:*`); validates domain entities against the validator

---

## Extending the Ontology

To add a new entity type and skill:

```python
# 1. Register the tower (if new domain)
store.register_entity(
    node_id="tower:hr",
    node_type="tower",
    display_name="Human Resources",
    aliases=["hr", "people ops"]
)

# 2. Register the process
store.register_entity(
    node_id="process:payroll",
    node_type="process",
    display_name="Payroll Processing",
    parent_id="tower:hr",
    aliases=["payroll", "salary"]
)

# 3. Register the skill (leaf)
store.register_entity(
    node_id="skill:payroll_ops",
    node_type="skill",
    display_name="Payroll Operations",
    parent_id="process:payroll",
    skill_name="payroll_ops",
    aliases=["payroll run", "salary processing", "pay cycle"]
)

# 4. Register entity type bucket
store.register_entity(
    node_id="entity_type:employee",
    node_type="ENTITY_TYPE",
    display_name="employee",
    parent_id="skill:payroll_ops",
    aliases=["emp", "staff", "worker"]
)
```

Employees encountered in conversations will then auto-register under `entity_type:employee` and link their knowledge records via `entity_xref`.

---

## Entity Guide Seeder

`EntityGuideSeeder` (`entity_guide_seeder.py`) runs as a background thread at server startup. It reads `entity_guide.md` from the tenant's shared directory and seeds the entity_registry with the declared canonical entities.

### Fragment Deduplication (`_purge_fragments`)

After every successful seed run, `_purge_fragments()` scans for non-canonical entity entries whose display name or aliases overlap with a canonical entity's alias set. For each fragment found:
1. All `entity_xref` rows pointing to the fragment are re-pointed to the canonical entity's `node_id`
2. The fragment entity row is deleted from `entity_registry`
3. FTS5 index is updated

This prevents duplicate "Foods" / "Northfield Foods" / "Northfield Foods Corporation" entries that can cause the alias resolver to return the wrong canonical entity.

### Trigger conditions
- Runs once at startup in a background thread
- Re-runs automatically when `entity_guide.md` mtime changes (detected on server restart)
- Fragment purge runs after every (re)seed. When the guide is unchanged (cached mtime matches within 1s), the worker returns before seeding, so the purge does not run that startup
