# IAF Agent Studio — Context Loading Architecture
## FILE MODE vs TABLE MODE

_Last updated: 2026-04-28_

---

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║              IAF AGENT STUDIO — CONTEXT LOADING ARCHITECTURE                        ║
║              FILE MODE  vs  TABLE MODE                                               ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

USER QUERY: "what are the collection steps if ACME invoice is overdue?"
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                         chat.py  (WS handler)                   │
│  1. Receives user message over WebSocket                        │
│  2. Reads agent.context_loading_mode  ──► "file" or "table"    │
│  3. BOTH MODES: TaxonomyRoutingCapability.find_skills(query_embedding) → taxonomy_hints │
│     FILE MODE:  skip entity pre-signal (no SQLite entity lookup)│
│     TABLE MODE: call entity_registry.collect_context()          │
│                 → entity pre-signal + taxonomy_hints for router │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     router.py  (Router LLM call)                │
│                                                                 │
│  TABLE MODE input:                                              │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  pre_signal hints from SQLite entity_registry          │    │
│  │  e.g. "ar_ops (alias:overdue, score:0.60)"            │    │
│  │  Taxonomy signal hits (from TaxonomyRoutingCapability):│    │
│  │  e.g. "fa_ar score=0.89: Accounts Receivable >        │    │
│  │        Collections > ..."                              │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  FILE MODE input:                                               │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Taxonomy signal hits (from TaxonomyRoutingCapability):│    │
│  │  e.g. "fa_ar score=0.89: Accounts Receivable >        │    │
│  │        Collections > ..."                              │    │
│  │  (No entity alias pre-signal. Raw query + taxonomy.)   │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  BOTH MODES → single LLM call → returns JSON:                  │
│  {                                                              │
│    "skill":           "ar_ops",                                 │
│    "is_confirmation": false,                                    │
│    "is_continuation": false,                                    │
│    "entity_name":     "ACME Corp",   ◄── FILE MODE only   │
│    "entity_type":     "customer"          ◄── FILE MODE only   │
│  }                                                              │
│                                                                 │
│  ► Writes to: routing_signal_log (SQLite)                       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     agent.py  run()  —  Step B                  │
│                                                                 │
│  FILE MODE:                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  MdEntityResolver.make_file_context_block(               │  │
│  │      "/shared/Enterprise_Context.md")                    │  │
│  │  Entitlement check: read context:/shared/Enterprise_     │  │
│  │      Context.md before the file is exposed in the prompt │  │
│  │  → sets self._file_context_block                         │  │
│  │  → entity_hint = "ACME Corp"  (from router)         │  │
│  │  No SQLite lookups. No entity_registry queries.          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  TABLE MODE:                                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  entity_registry.collect_context(entity_hints)           │  │
│  │  → SQLite queries: entity_registry, entity_xref,         │  │
│  │    process_relationships tables                          │  │
│  │  → builds full entity tree in memory                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  BOTH MODES (always runs):                                      │
│    A. Embedding of query  (text-embedding-ada-002)              │
│    C. Plan cache lookup   (plan_cache table, SQLite)            │
│    D. Episode search      (episode_vectors, BruteForce)         │
│    E. Knowledge search    (knowledge_vectors, BruteForce)       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              prompt_assembler.py  — _load_prompt()              │
│                                                                 │
│  FILE MODE injects at Step 10f:                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ## Enterprise Context                                   │  │
│  │  Context stored in: `/shared/Enterprise_Context.md`      │  │
│  │  MANDATORY Step 1: shell → cat "/shared/Enterprise_      │  │
│  │                            Context.md"                   │  │
│  │  MANDATORY Step 2: follow any linked file paths          │  │
│  │  Do NOT answer from memory.                              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  TABLE MODE injects:                                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Full entity tree (customers, vendors, thresholds,       │  │
│  │  policy pointers) pre-loaded into system prompt          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  BOTH MODES also inject:                                        │
│    - skill prompt  (ar_ops system instructions)                 │
│    - episode summaries  (similar past conversations)            │
│    - knowledge facts  (from knowledge_vectors)                  │
│    - approval rules  (HITL thresholds)                          │
│    - binary document guidance  (Quartz/MarkItDown via python3)  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              React Runtime  (LangGraph default, native optional) │
│                                                                  │
│  execution_mode=react chooses react_runtime=langgraph unless     │
│  a skill/config/env override requests native. Native is an       │
│  implementation path only; it is not a new execution mode.       │
│  Both runtimes pass structured tool calls through the same       │
│  tool-governance firewall before shell/SQL/MCP execution.        │
│  Native SQL tool results are captured as evidence items at the   │
│  tool-result boundary, matching the default runtime path.        │
│  After execution, chat responses include a bounded observable     │
│  reasoning_summary for the UI Why row; hidden chain-of-thought    │
│  is not exposed.                                                 │
│                                                                 │
│  FILE MODE execution trace (this session):                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Step 1:  shell("cat /shared/Enterprise_Context.md")     │  │
│  │           → reads 304 lines, finds ACME playbook ptr  │  │
│  │                                                          │  │
│  │  Step 2:  shell("cat /shared/policies/               │  │
│  │                  acme_collection_playbook.md")        │  │
│  │           → reads 45 lines, gets full escalation ladder  │  │
│  │                                                          │  │
│  │  Step 3:  Compose answer from playbook content           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  TABLE MODE execution trace (typical):                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Step 1:  run_sql_query → ar_aging_report table          │  │
│  │  Step 2:  Compose answer from DB rows                    │  │
│  │  (entity context already in prompt, no file reads)       │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DOWNSTREAM STORAGE  (verified ✓)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  AUDIT LOG  (.audit/commands_2026-03-20.jsonl)          ✓      │
│  └─ Every shell call, SQL call, HITL event logged               │
│                                                                 │
│  SESSION JSONL  (memory/history/2026-03-20/                     │
│                  demo_20260320_165148_af118e.jsonl)      ✓      │
│  └─ Full Q&A turn with skill=ar_ops, 6.8KB                      │
│                                                                 │
│  LEARNINGS  (memory/learnings/ar_ops/                           │
│              tool_execution.jsonl)                      ✓      │
│  └─ 2 entries: shell→Enterprise_Context.md                      │
│                shell→acme_collection_playbook.md            │
│                Both has_error=false                             │
│                                                                 │
│  CONVERSATION SESSIONS  (knowledge_index.db:                    │
│                          conversation_sessions)          ✓      │
│  └─ session_id=demo_20260320_165148_af118e                      │
│     skills_used=["ar_ops"], turn_count=2                        │
│                                                                 │
│  EPISODE VECTORS  (knowledge_index.db:episode_vectors)  ✓      │
│  └─ 701 rows total (this session added its episode)             │
│                                                                 │
│  KNOWLEDGE VECTORS  (knowledge_index.db:knowledge_vectors) ✓   │
│  └─ 402 rows total                                              │
│                                                                 │
│  CONTEXT GRAPH  (memory/context_graph/knowledge.jsonl)  ✓      │
│  └─ 1000 entries, 676KB, last write 14:49 today                 │
│                                                                 │
│  PLAN CACHE  (knowledge_index.db:plan_cache)            ✓      │
│  └─ 24 entries, includes ACME ar_ops plan                   │
│     fingerprint bumped on this query (use_count++)              │
│                                                                 │
│  ROUTING SIGNAL LOG  (knowledge_index.db:                       │
│                       routing_signal_log)                ✓      │
│  └─ row 299: query matched ar_ops, entity_score=0.0             │
│     (file mode — no pre-signal score, just LLM routing)         │
│                                                                 │
│  ENTERPRISE EVIDENCE  (EvidenceCollectorAdapter → evidence.db) ✓ │
│  └─ evidence_bundles + evidence_items rows for business reads   │
│     REST/WS responses include source_documents + trace id       │
│     queue_ingest cron jobs create real queue_items internally;  │
│     terminal dedup hits create a fresh item for the new fire;   │
│     no separate [CRON] done audit row is posted for the bridge   │
│     the queue execution then records trace, steps, and evidence │
│                                                                 │
│  TRACE/TWIN TELEMETRY  (local SQLite + optional provider fanout) ✓│
│  └─ traces.db and twin_telemetry.db remain local defaults;       │
│     external mirrors receive bounded redacted copies only        │
│                                                                 │
│  MEMORY EXTRACTION  (async after response)              ✓       │
│  └─ 16 entities extracted from ACME playbook content        │
│     stored to knowledge graph through direct AgentMemory by     │
│     default, or the pass-through MemoryCapability when          │
│     IAF_MEMORY_CAPABILITY_ENABLED=true                          │
└─────────────────────────────────────────────────────────────────┘

TABLE MODE vs FILE MODE — KEY DIFFERENCES
┌──────────────────────────┬─────────────────────┬──────────────────────────┐
│ Aspect                   │ TABLE MODE          │ FILE MODE                │
├──────────────────────────┼─────────────────────┼──────────────────────────┤
│ Entity resolution        │ SQLite queries      │ Router LLM (natural lang)│
│ Pre-signal to router     │ Entity alias match +│ Taxonomy vector hits     │
│                          │ taxonomy vector hits│ (no entity alias)        │
│ Taxonomy routing facade  │ Default current;    │ Default current;         │
│                          │ optional shadow     │ optional shadow          │
│ Taxonomy signal index    │ Runs in background —│ Runs in background —     │
│                          │ both modes          │ both modes               │
│ Router extra fields      │ skill only          │ + entity_name/type       │
│ Context in prompt        │ Entity tree (pre-   │ Instruction to read .md  │
│                          │ loaded from SQLite) │ at runtime               │
│ Policy/playbook access   │ Path in prompt      │ Agent reads file itself  │
│ Entity alias maintenance │ SQLite entity table │ Enterprise_Context.md    │
│ MdEntityResolver used    │ No                  │ Yes (make_file_context_  │
│                          │                     │ block only)              │
│ routing_signal_log score │ 0.6+ (alias match)  │ 0.0 (no pre-signal)      │
│ Agent shell calls        │ 0 (context in RAM)  │ 2+ (reads files)         │
│ Downstream storage       │ Identical ✓         │ Identical ✓              │
│ Telemetry fanout         │ Same provider path  │ Same provider path       │
│ Evidence highlights      │ SKILL.md optional   │ SKILL.md optional        │
│                          │ rules + generic     │ rules + generic          │
│                          │ query/tool terms    │ query/tool terms         │
└──────────────────────────┴─────────────────────┴──────────────────────────┘

NOTE: routing_signal_log shows score=0.0 in file mode (no alias match ran).
      This is expected — the LLM routed correctly to ar_ops without it.
```

---

## Key Files

| File | Role |
|------|------|
| `IAF-Agent-Studio/routers/chat.py` | WS/HTTP handler — mode branch for pre-signal |
| `IAF-Agent-Skills/iaf_agent_skills/router.py` | Router LLM — entity extraction in file mode |
| `IAF-Agent-Skills/iaf_agent_skills/agent.py` | Step B — file vs table context build |
| `IAF-Agent-Skills/iaf_agent_skills/md_entity_resolver.py` | Builds file context block (file mode only) |
| `IAF-Agent-Skills/iaf_agent_skills/prompt_assembler.py` | Injects `_file_context_block` at Step 10f |
| `enterprise_root/tenants/company/shared/Enterprise_Context.md` | Master context file (virtual path: `/shared/Enterprise_Context.md`) |
| `enterprise_root/tenants/company/shared/policies/` | Policy & playbook files (virtual path: `/shared/policies/`) |
| `enterprise_root/tenants/company/agents/*/config.yaml` | `context_loading_mode: file` + `context_file_path: /shared/Enterprise_Context.md` |

External access metadata can point to APIs and credentials, but prompt assembly no longer injects clear-text credential values. Context sources should expose `credential_ref`; the agent must call `get_credential`, receive a masked `$CRED_*` variable, and let SafeKernel enforce the linked `external:*` policy resource before substituting the secret at execution time.

## Virtual Path Resolution

The `SafeKernel` maps virtual paths to real filesystem paths:

| Virtual Path | Real Path |
|---|---|
| `/shared/` | `enterprise_root/tenants/company/shared/` |
| `/me/` | `enterprise_root/tenants/company/agents/<agent>/users/<user>/` |
| `/workspace/` | `enterprise_root/tenants/company/agents/<agent>/workspace/` |
| `/memory/` | `enterprise_root/tenants/company/agents/<agent>/memory/` (read-only) |

> **Critical**: Always use virtual paths (e.g. `/shared/Enterprise_Context.md`) in config and .md files.
> Absolute filesystem paths like `/Users/<you>/...` will cause `FILE_NOT_FOUND` because
> `SafePath.resolve()` strips the leading `/` and resolves relative to `agent_root`.
