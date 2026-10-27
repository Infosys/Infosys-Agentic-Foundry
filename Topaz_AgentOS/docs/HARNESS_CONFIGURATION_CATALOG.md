# AgentOS Harness — Configuration Options Catalog

> **Purpose.** A single, exhaustive reference for every configuration knob that controls *how the
> AgentOS harness executes a task* — execution mode, verifiers, retries, memory, timeouts, model
> selection, and more. Use this when you want to know **what can be tuned**, **where it lives**, and
> **whether it can differ per use case**. It is the groundwork for building reusable *harness
> execution profiles*.
>
> **Scope.** This catalog focuses on *runtime execution behavior*. Pure infrastructure (ports, DSNs,
> pool sizes) is listed in the [env-var appendix](#appendix-a--complete-environment-variable-inventory)
> but not in the behavioral tables. For the canonical env-var reference see
> [`CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md).
>
> **How to keep this accurate.** Every row cites a `file:line`. The code is authoritative; docs may
> lag. Re-verify a citation before relying on it. Last verified: 2026-08-01.

---

## 1. The five binding layers (the key mental model)

Configuration in AgentOS is **not one surface**. Every knob is bound at one of five layers, and a
knob's layer decides whether it can vary per use case. Precedence — **left overrides right**:

```
per-request  →  per-skill (SKILL.md)  →  per-agent (config.yaml)  →  env / global (config.env)  →  hardcoded constant
 (run() args,      (frontmatter)            (agent settings)            (process environment)          (code — cannot
  UI toggles,                                                                                            vary without
  routing_info)                                                                                          a code change)
```

- **per-request** — `run()` args, UI toggles, `routing_info`, the entitlement principal. Varies every call.
- **per-skill (SKILL.md frontmatter)** — travels with the use case. The closest thing to a "profile" today, but one-per-skill, not a reusable named bundle.
- **per-agent (`config.yaml`)** — agent-wide settings (`sufficiency.*`, `skills.mode`, `tools.allowed`, `memory.*`, `context.*`).
- **env / global (`config.env`)** — process-wide. Affects every agent in the process.
- **hardcoded constant** — a wall. Cannot differ per use case without editing code.

> **Implication for profiles.** Only the first four layers are configurable. The knobs most people
> want *per profile* — retry ceiling, plan-cache threshold, max plan steps, kernel caps, cosine
> floors — are **hardcoded** today (see [§12](#12-what-this-means-for-execution-profiles)).

---

## 2. Execution mode & engine

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| `execution_mode` | SKILL.md | `react` | Engine: `react` / `workflow` / `parallel` / `supervisor` / `planned` / `orchestrator` | enum `execution.py:41-48`; resolver `execution.py:1073`; dispatch `agent.py:4798-4861` |
| `steps` (DAG) | SKILL.md | `[]` | Step graph for `workflow`/`parallel` | `loader.py:129` |
| `worker_skills` | SKILL.md | `[]` | Workers for `supervisor`/`orchestrator` | `loader.py:130,140-175` |
| `react_runtime` | request → skill → config → env `IAF_REACT_RUNTIME` | `langgraph` | `langgraph` vs provider-`native` ReAct loop | `agentos_contracts/react_runtime.py:11,52-75` |
| `native_fallback_on_error` | config / env `IAF_REACT_NATIVE_FALLBACK_ON_ERROR` | `true` | Native→LangGraph fallback on error | `agent.py:1127-1140` |
| `DYNAMIC_ORCHESTRATOR_ENABLED` | env | `true` | Auto-upgrade a `react` skill to dynamic orchestrator when router `mode_hint="orchestrator"` | `agent.py:89-107,4869-4907` |
| `context_loading_mode` | agent config | `table` | Context source: `table` (entity_registry) vs `file` (Enterprise_Context.md) | `agent.py:405-407` |
| `context_file_path` | agent config | `None` | EC.md path for `file` mode | `agent.py:410-412` |
| `light_mode` ("Fresh Mode") | per-request | `false` | Skips plan-cache, episode log, memory context, async learning, `query_memory` tool | `agent.py:4073,4154-4161,2451-2453` |
| `skip_memory` | per-request | `false` | No memory read/write this run | `agent.py:4073,4105` |

**Notes**
- `workflow`/`parallel` require `steps`; `supervisor`/`orchestrator` require `worker_skills` (enforced `agent.py:3463,3721,3819,3885`).
- Unknown `execution_mode` values silently fall back to `react` (`execution.py:1088`).

---

## 3. Iteration & retry

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| native React `max_iterations` | config → env `IAF_REACT_NATIVE_MAX_ITERATIONS` | `8` (min 1) | Max turns in the native ReAct tool loop | `agent.py:230-246,1159-1166`; `react_runtime/native.py:34,46` |
| LangGraph `recursion_limit` | **hardcoded** (instance attr, mutable) | `200` | LangGraph ReAct graph step cap | `agent.py:356,5044` |
| orchestrator `max_steps` | SKILL.md | `10` | Manager-LLM dispatch steps before forced synthesis | `loader.py:131`; `execution.py:816-863` |
| `MAX_PLAN_STEPS` | **hardcoded** | `10` | DAG plan length ceiling | `planner.py:32,254`; dup `tool_factory.py:35` |
| `MAX_INVOKE_DEPTH` | **hardcoded** | `2` | Cross-skill delegation/recursion depth | `tool_factory.py:32`; `agent.py:3102,3150` |
| 429 auto-fallback | automatic | retry **once** on fallback model role | The only *enforced* model-level retry | `agent.py:5132-5158` |
| "Maximum 3 retry attempts" | **prompt text only** | advisory | NOT an enforced counter — LLM guidance only | `agent.py:1941-1949` |
| `TRACE_VALUE_ROUTER_RETRY_LIMIT` | env | `1` (0–5) | Retry limit for the trace-value-router sidecar | `shared/config.py:182` |

---

## 4. Verification / critique / self-correction

> There is **no `verifiers:` field in SKILL.md.** Verification is the **sufficiency loop** (agent
> config) plus the **critique** passes (env / per-request UI). Per-use-case verification cannot be
> declared on the skill today — this is the biggest structural gap for profiles (see [§12](#12-what-this-means-for-execution-profiles)).

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| `sufficiency.enabled` | agent config | `false` | Master switch for the self-correction / sufficiency loop | `agent.py:423,1048` |
| `sufficiency.auto_complexity` | agent config | `false` | Loop only when the query is structurally complex (heuristic) | `agent.py:424,1048-1051,905-923` |
| `sufficiency.max_iterations` | agent config | `3` | Max self-correction iterations | `agent.py:425,1071-1085` |
| `sufficiency.threshold` | agent config | `0.85` | Confidence at/above which the answer is accepted | `agent.py:426,1111` |
| `sufficiency.skip_for_skills` | agent config | `[]` | Skills that bypass the loop | `agent.py:427,1052` |
| `sufficiency_criteria` | SKILL.md | `[]` | Skill-declared criteria injected into the evaluator prompt | `agent.py:1057-1062` |
| `enable_critique` (plan critic) | per-request (UI) | `false` | Post-plan semantic validation pass (`PlanCritic.critique()`) | `tool_factory.py:1070-1099`; set `chat.py:1940` |
| `critique_mode` (response grounding) | per-request (UI 3-state) | `off` | `off` / `sync` (blocks + revises) / `async` (WS push) | `chat.py:1274-1279,1936-1941` |
| `CRITIQUE_ENABLED` | env | `false` | Server-side critique master switch (runs even if UI toggle off) | `shared/config.py:377` |
| `CRITIQUE_MODE` | env | `async` | Server default critique mode (`sync`/`async`) | `shared/config.py:378` |
| `CRITIQUE_RECHECK` | env | `true` | 3rd LLM call re-verifies the revised answer | `shared/config.py:382`; `chat.py:1936` |
| `CONSISTENCY_CHECK` | env | `false` | Cold 2nd agent run + compare responses (async; doubles cost) | `shared/config.py:386` |
| sufficiency / critic model | follows `light_llm` | light model | Which (cheap) model runs the verifier/critic passes | `agent.py:974-976`; `plan_critic.py:48-59` |
| `_EPISODE_MIN_SCORE` / `_EPISODE_TOP_K` | **hardcoded** | `0.65` / `3` | Precedent episodes fed to the critic | `plan_critic.py:31-32` |

---

## 5. Planning & plan cache

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| plan-cache read `min_score` | **hardcoded at call site** | `0.90` | Cosine-similarity threshold for a plan-cache hit to override the router | `agent.py:4660-4664`; `knowledge_indexer.py:2773,2812` |
| plan-cache read `top_k` | **hardcoded at call site** | `1` (fn default `3`) | Cached plans considered | `agent.py:4662` |
| plan-cache override precedence | logic | caller `planned` wins | Caller-forced `planned` overrides cached mode; cache supplies skill + steps | `agent.py:4682-4710` |
| plan-cache write condition | automatic | single-skill success, not itself a hit | When a successful run is written back | `agent.py:5704-5748` |
| `build_planner_context` caps | **hardcoded** | entities 10 / relationships 15 | Bounds the taxonomy context handed to planner + critic | `planner.py:35-60` |
| planner model | follows `light_llm` | light model | Model that generates DAG plans | `planner.py:14` |

> There is **no `PLAN_CACHE` env var** — plan caching is not env-gated; it is keyed on
> `execution_mode == "planned"` and the hardcoded thresholds above.

---

## 6. Memory / knowledge / context injection

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| `knowledge_retrieval` / `knowledge_mode` | agent config + per-request | `hybrid` | Retrieval strategy: `scan` / `semantic` / `hybrid` | `agent.py:380-382,4154-4156` |
| `KNOWLEDGE_EMBEDDINGS_ENABLED` | env *(undocumented)* | `true` | Generate embeddings for the knowledge/memory index (affects recall) | `memory.py:361` |
| hybrid backfill threshold | **hardcoded** | `< 3` confirmed → backfill, cap 10 | When semantic results are supplemented by scan | `agent.py:2560-2574` |
| `COSINE_MIN_SCORE` | **hardcoded** | `0.72` | Min cosine score for a semantic knowledge hit | `knowledge_indexer.py:146` |
| episode search `min_score` / `top_k` | **hardcoded** defaults | `0.5` / varies | Episodic memory retrieval thresholds | `knowledge_indexer.py:1036-1037` |
| `SESSION_COMPACT_THRESHOLD` | **hardcoded** | `30` turns | History length that triggers LLM compaction | `agent.py:371,1690-1706` |
| `SESSION_KEEP_RECENT` | **hardcoded** | `8` turns | Recent turns kept uncompacted | `agent.py:372` |
| `_build_messages_with_history` `max_history` | method arg | `10` | Turns of history injected into the prompt | `agent.py:5972-5989` |
| `_CTX_WARN_TOKENS` / `_CTX_ERROR_TOKENS` | **hardcoded** | `60k` / `100k` | Context-size warning/error thresholds (advisory) | `agent.py:85-86,130-137` |
| `VECTOR_BACKEND` | env | `brute_force` | Recall engine: `brute_force` / `sqlite_vec` / `pgvector` | `CONFIG_REFERENCE.md` |
| `KNOWLEDGE_BACKEND` | env | `sqlite` | Per-agent knowledge/episode/entity index backend | `CONFIG_REFERENCE.md` |
| `VECTOR_DIMENSION` | env | `1536` | Embedding dimension (must match model) | `CONFIG_REFERENCE.md` |

---

## 7. World-model / learning

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| `WORLD_MODEL_LEARN` | env | `false` | Per-turn LLM relationship-triple extraction → `pending_review` edges | `world_model.py:30-32` |
| `WORLD_MODEL_MIN_CONFIDENCE` | env | `0.6` | Min triple confidence to write | `world_model.py:35-39` |
| `WORLD_MODEL_AUTOCONFIRM_CONFIDENCE` | env | unset (OFF) | Edges ≥ threshold written `confirmed` (skip review) | `world_model.py:42-52` |
| `GRAPH_BACKEND` | env | `relational` | Graph backend seam (`age` opt-in, not yet implemented) | `world_model.py:277-293` |
| `RL_CAPTURE` | env | `false` | Capture RL trajectories | `capture_events.py:23` |
| `RL_CAPTURE_REASONING` | env | `false` | Capture reasoning traces in RL | `shared/config.py:165` |
| `RL_REDACT` | env | `true` | Redact captured RL data | `shared/config.py:164` |
| `IMPLICIT_FEEDBACK` | env | `true` | Implicit-feedback learning on/off | `implicit_learning.py:161` |
| `IMPLICIT_CONFIDENCE_THRESHOLDS` | **hardcoded** | module-defined | Confidence bands for implicit-learning memory writes | `implicit_learning.py:48`; `agent.py:69` |

---

## 8. Model & sampling

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| role→model map (`primary`/`light`/`fallback`/`router`/`queue_router`) | env per provider | provider-specific | Which deployment each role uses; router→primary, queue_router→light | `model_registry.py:57-72,120-159` |
| `LLM_ACTIVE_PROVIDER` / `LLM_PRIMARY_PROVIDER` / `LLM_PRIMARY_MODEL` | env *(undocumented)* | — / — / `claude-haiku-4-5-20251001` | Active + fallback provider and primary model | `model_registry.py:384,481,531` |
| `EVAL_ROUTER_ENABLED` | env | `false` | Eval-based model redirection per role | `model_provider.py` |
| `EVAL_ROUTER_ROLE_MAP` / `EVAL_ROUTER_ROLE_<ROLE>` | env | empty | JSON role→role map / per-role override | `model_provider.py:53,71` |
| `OPENAI_TEMPERATURE` / `VERTEX_TEMPERATURE` | env | `0.7` | Sampling temperature | `model_registry.py:144,240` |
| `ANTHROPIC_MAX_TOKENS` | env | `4096` | Anthropic max output tokens | `model_registry.py:292` |
| `AZURE_REASONING_ENABLED` + `AZURE_REASONING_EFFORT` | env | disabled / `medium` | Reasoning effort on primary/router (Azure) | `model_registry.py:100-108` |
| `*_REASONING_BUDGET` / `*_REASONING_EFFORT` (Vertex/Anthropic) | env | provider default | Thinking-token budget / effort | `model_registry.py:275-295` |
| `{PREFIX}_REASONING_REPLAY` / `_EXPOSE` | env | disabled | Reasoning replay / bounded reasoning preview | `model_reasoning_meta.py:69-84` |
| model HTTP timeouts | **hardcoded** | 30s httpx / 20s–120s vertex | Per-provider request timeouts | `model_registry.py:42,46` |
| `PUBLIC_CA_BUNDLE` | env | default trust store | CA bundle for **public** LLMs reached via the intercepting corporate proxy (Azure). Must contain the proxy interception CA (e.g. Infosys-PXY). Used by Azure chat + Azure embeddings. | `model_registry.py:_get_public_ssl_verify`, `memory.py` |
| `INTERNAL_CA_BUNDLE` (falls back to `OPENAI_SSL_VERIFY`) | env | default trust store | CA bundle for **direct internal** OpenAI-compatible models (self-hosted vLLM/Gemma). Should contain the internal Infosys CA chain. `false/0/no/off` disables verification. | `model_registry.py:_get_internal_ssl_verify` |

> **Outbound TLS trust is scoped per-connection, never one global bundle.**
> Public endpoints go through the corporate (Zscaler) proxy which re-signs certs
> with its own root CA → use `PUBLIC_CA_BUNDLE`. Internal models are reached
> directly (NO_PROXY) and use the internal chain via `INTERNAL_CA_BUNDLE`. Do not
> set a global `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` to the inbound server chain —
> it breaks every outbound call.

> There is **no per-skill `model:` or `temperature:` field.** Model selection is env / agent-level only.

---

## 9. Timeouts & resource caps (kernel / tools)

Almost all kernel caps are **hardcoded class constants** (`agent_os/kernel.py`). Only the last group is configurable.

| Knob | Layer | Default | Source |
|---|---|---|---|
| `COMMAND_TIMEOUT` | **hardcoded** | `30` s | `kernel.py:310` |
| `MAX_READ_BYTES` | **hardcoded** | `50 KB` | `kernel.py:304` |
| `MAX_READ_LINES` | **hardcoded** | `100` | `kernel.py:305` |
| `MAX_LIST_ITEMS` | **hardcoded** | `100` | `kernel.py:306` |
| `MAX_GREP_RESULTS` | **hardcoded** | `50` | `kernel.py:307` |
| `MAX_FIND_RESULTS` | **hardcoded** | `100` | `kernel.py:308` |
| `MAX_RECURSIVE_DEPTH` | **hardcoded** | `5` | `kernel.py:309` |
| SQL result display cap | **hardcoded** | `50` rows / `10k` chars | `tool_factory.py:507-518` |
| `MAX_RESULT_CHARS` (invoke/plan) | **hardcoded** | `8000` | `tool_factory.py:40` |
| MCP tool / delegation timeouts | **hardcoded** | `15` s / `300` s | `agent.py:3075,3757` |
| `PENDING_ACTION_TIMEOUT_MINUTES` (HITL) | **hardcoded** | `10` min | `agent.py:389,6268-6271` |
| `AUDIT_LOG_MAX_DAYS` | **hardcoded** | `30` | `kernel.py:332` |
| **`DEFAULT_RATE_LIMIT` / window** | **constructor arg** | `60` cmds / `60` s | `kernel.py:328-329,351` |
| **`AGENTOS_SQL_STATEMENT_TIMEOUT_MS`** | env | `5000` ms | `tool_factory.py:305-320` |
| **`AGENTOS_SQL_RO_ROLE`** | env / per-resource | `agentos_graph_ro` | `tool_factory.py:310-330` |
| **`AGENT_PYTHON3_TIMEOUT`** | env | `30` s | `kernel.py:486` |
| **`AGENT_PYTHON3_MAX_MEMORY_MB`** | env | `512` MB | `kernel.py:487` |
| **`AGENTOS_KERNEL_TIMEOUT_SECONDS`** | env *(undocumented)* | `120` s | `agent_os/kernel_runtime.py:184` |
| **`QUEUE_SKILL_TIMEOUT_SEC`** | env *(undocumented)* | `300` s | `cc_queue/processor.py:33` |

---

## 10. Tool / skill gating, entitlements, HITL

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| `tools` | SKILL.md | `[]` | Permitted tool names (`shell`, `run_sql_query`, `query_memory`, `write_file`, `request_human_approval`, `invoke_skill`) | `loader.py:122`; docs `04_skill_authoring.md:218-228` |
| `sql_mode` | SKILL.md | `read_only` | SQL write gate (`read_only`/`read_write`); DDL always blocked | `loader.py:126`; `tool_factory.py:415-426`; `agent.py:2968-2969` |
| `mcp_connections` / `mcp_tools` | SKILL.md | `[]` | MCP servers / legacy per-server tool list | `loader.py:120-121` |
| `approval_rules` | SKILL.md | `{}` | HITL: `default_urgency`, `sla_minutes`, `thresholds[]`, `conditions[]`, `always/never_require[]` | `loader.py:124`; docs `AGENTPRO_SKILL_AUTHOR.md:80-103` |
| `evidence_highlights` | SKILL.md *(undocumented)* | `{}` | Evidence-highlight rules | `loader.py:125` |
| `skills.mode` + `allowed`/`denied` | agent config | `all` | Router skill filter (`all`/`allowlist`/`denylist`) | `agent.py:1488-1507` |
| `tools.allowed` | agent config | all (8-tool fallback) | Tool bind allowlist (still entitlement-checked) | `agent.py:1509-1522` |
| `ENTITLEMENTS_ENABLED` + checker | env + per-request principal | `false` | Per-action allow/deny for tools/credentials/SQL/HTTP | `kernel.py:402,1083-1237` |
| `auto_run` | per-request (UI) | `false` | Skip write confirmation (dangerous-op HITL gate still applies) | `agent.py:357,2442-2443,770-830` |
| external-access enforcement | kernel config | — | Governs credential/SQL/HTTP via `external_access.yaml` | `kernel.py:1155-1237` |
| `AGENTOS_UNTRUSTED_EXECUTION_GUARD` | env | `false` | Forces bundled tool-script `python3` OFF for tenant-authored skills | `shared/config.py:206`; `agent.py:249-254` |

---

## 11. Providers & sidecars

| Knob | Layer | Default | Controls | Source |
|---|---|---|---|---|
| `SKILL/ROUTER/TOOL/HOOK/TRACE_PROVIDER` | env | `default` | Pluggable provider selection (`module:Class`) affecting run wiring | `shared/config.py:186-190` |
| `TRACE_VALUE_ROUTER_ENABLED` | env | `false` | Async trace-value assessment after chat capture | `CONFIG_REFERENCE.md` |
| `TRACE_VALUE_ROUTER_CONCURRENCY` | env | `1` (1–8) | Trace-value sidecar concurrency | `shared/config.py:179` |
| `TRACE_VALUE_ROUTER_BATCH_LIMIT` / `_MAX_EVIDENCE_CHARS` | env | `25` / `12000` | Batch size / evidence sent to judge | `shared/config.py` |
| `CAPABILITY_HOOKS_ENABLED` | env *(undocumented)* | `true` | Capability hooks on/off | `hook_runner.py:468`; `config.py:509` |
| `MODEL_CALL_PIPELINE_ENABLED` | env *(undocumented)* | `false` | Enables the model-call pipeline | `model_call_pipeline.py:47` |
| `ENABLE_TOKEN_STREAMING` | env *(undocumented)* | `false` | Token-streaming responses | `routers/chat.py:233` |

---

## 12. What this means for execution profiles

Three structural facts fall out of this catalog and shape any future "profile" framework:

1. **Profile-able today (4 layers).** Everything tagged SKILL.md / agent-config / per-request / env
   can already be preset. A *profile* is essentially a named bundle that fills these across layers at
   once. Examples:
   - `high-assurance` → `execution_mode: planned` + `sufficiency.enabled: true, threshold: 0.9,
     max_iterations: 3` + `CRITIQUE_ENABLED` + world-model autoconfirm **off**.
   - `fast-lookup` → `execution_mode: react` + sufficiency **off** + critique **off** + `light_mode`.

2. **The blockers (hardcoded).** The knobs many profiles would want — retry ceiling
   (`recursion_limit=200`), plan-cache threshold (`0.90`), `MAX_PLAN_STEPS=10`, kernel caps,
   `COSINE_MIN_SCORE=0.72`, session compaction (`30`/`8`) — are **hardcoded**. A real profile system
   needs a first step of promoting these constants to config-resolved values (a `resolve_knob(name)`
   seam, mirroring the existing `resolve_backend` pattern for storage backends).

3. **The layering conflict.** `execution_mode` is per-skill, but `sufficiency.*` and critique are
   per-*agent* / env. So *"this skill needs two verifiers, that one needs none"* **is not expressible
   today** — verification cannot vary per skill/use-case. Closing this (e.g. a `profile:` field in
   SKILL.md that resolves to a named preset applied across all layers, with a defined precedence)
   is the highest-value change for use-case-specific harnesses.

---

## Appendix A — Complete environment-variable inventory

Grouped by concern. **Bold** = affects execution behavior (candidate profile knob). Vars marked
*(undoc)* are read in code but absent from [`CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md) as of
2026-08-01 and should be added there.

### A1. Execution behavior
`DYNAMIC_ORCHESTRATOR_ENABLED` (`true`), **`IAF_REACT_RUNTIME`**, **`IAF_REACT_NATIVE_MAX_ITERATIONS`** (`8`), `IAF_REACT_NATIVE_FALLBACK_ON_ERROR` (`true`), `IAF_EXECUTION_MODE` *(undoc — read by orchestrator platform hooks)*, `MODEL_CALL_PIPELINE_ENABLED` *(undoc, `false`)*, `CAPABILITY_HOOKS_ENABLED` *(undoc, `true`)*, `ENABLE_TOKEN_STREAMING` *(undoc, `false`)*, `CONSISTENCY_CHECK` *(undoc, `false`)*, `CONFIG_ENV_PATH` *(undoc)*.

### A2. Verification / critique
`CRITIQUE_ENABLED` *(undoc, `false`)*, `CRITIQUE_MODE` *(undoc, `async`)*, `CRITIQUE_RECHECK` *(undoc, `true`)*.

### A3. Model / LLM (mostly undocumented)
`LLM_ACTIVE_PROVIDER`, `LLM_PRIMARY_PROVIDER`, `LLM_PRIMARY_MODEL` (`claude-haiku-4-5-20251001`), `EVAL_ROUTER_ENABLED` (`false`), `EVAL_ROUTER_ROLE_MAP`, `EVAL_ROUTER_ROLE_<ROLE>`, `AZURE_OPENAI_DEPLOYMENT_LIGHT` (`gpt-5-nano`); *(undoc)* `OPENAI_MODEL_NAME`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_TEMPERATURE`, `OPENAI_SSL_VERIFY`, `AZURE_OPENAI_{API_KEY,ENDPOINT,API_VERSION,DEPLOYMENT,EMBEDDING_MODEL,WHISPER_DEPLOYMENT}`, `AZURE_REASONING_{ENABLED,EFFORT}`, `ANTHROPIC_{API_KEY,API_URL,API_VERSION,CA_BUNDLE,MAX_TOKENS,MODEL_NAME,REASONING_BUDGET,REASONING_EFFORT}`, `VERTEX_{PROJECT,PROJECT_ID,LOCATION,MODEL_NAME,TEMPERATURE,REASONING_BUDGET,SA_KEY_PATH,CA_BUNDLE,IMAGE_OUTPUT_DIR,IMAGE_RETENTION_DAYS,IMAGE_URL_PREFIX}`, `GOOGLE_APPLICATION_CREDENTIALS`, `WHISPER_MODEL`.

### A4. Memory / knowledge / world-model
**`WORLD_MODEL_LEARN`** (`false`), **`WORLD_MODEL_MIN_CONFIDENCE`** (`0.6`), **`WORLD_MODEL_AUTOCONFIRM_CONFIDENCE`** (unset), **`GRAPH_BACKEND`** (`relational`), `KNOWLEDGE_BACKEND` (`sqlite`), `VECTOR_BACKEND` (`brute_force`), `VECTOR_DIMENSION` (`1536`), `PGVECTOR_IVF_LISTS` (`100`), `KNOWLEDGE_EMBEDDINGS_ENABLED` *(undoc, `true`)*, `KNOWLEDGE_PG_SCHEMA` *(undoc)*, `EMBEDDING_CACHE_MAX_SIZE` *(undoc)*, `KNOWLEDGE_COMPACT_BLOAT_PCT` (`50`), `TRANSCRIPT_HOT_DAYS` (`0`).

### A5. RL capture / implicit learning
`RL_CAPTURE` *(undoc, `false`)*, `RL_CAPTURE_REASONING` *(undoc, `false`)*, `RL_REDACT` *(undoc, `true`)*, `RL_DB_PATH` *(undoc)*, `IMPLICIT_FEEDBACK` *(undoc, `true`)*, `REGRESSION_HOOK_LOG` *(undoc)*.

### A6. Timeouts / kernel / execution limits
**`AGENTOS_SQL_STATEMENT_TIMEOUT_MS`** (`5000`), `AGENTOS_SQL_RO_ROLE` (`agentos_graph_ro`), `AGENT_PYTHON3_ENABLED` (`false`), `AGENT_PYTHON3_TIMEOUT` (`30`), `AGENT_PYTHON3_MAX_MEMORY_MB` (`512`), `AGENT_PYTHON3_SANDBOX_USER`, `AGENTOS_UNTRUSTED_EXECUTION_GUARD` (`false`), `AGENTOS_KERNEL_TIMEOUT_SECONDS` *(undoc, `120`)*, `QUEUE_SKILL_TIMEOUT_SEC` *(undoc, `300`)*, `IAF_PYTHON_EXECUTABLE` *(undoc)*, `TELEMETRY_TIMEOUT_SECONDS` (`2.0`).

### A7. Kernel packaging / self-auth
`AGENTOS_KERNEL_BACKEND` (`local`), `AGENTOS_KERNEL_URL`, `AGENTOS_KERNEL_TOKEN_SECRET`, `AGENTOS_KERNEL_REQUIRE_REMOTE` (`false`), `AGENTOS_KERNEL_WORKER_BIND` (`127.0.0.1`), `AGENTOS_KERNEL_WORKER_PORT` (`18081`), `AGENTOS_KERNEL_SESSION_TTL_SECONDS` (`1800`), `AGENTOS_KERNEL_FILE_CACHE` (`false`), `JWT_SECRET`, `JWT_ALGORITHM` (`HS256`), `TENANT_ID` (`company`), `AGENT_ID` (`enterprise_agent`), `SERVER_LOG_PATH`.

### A8. Providers
`SKILL_PROVIDER`, `ROUTER_PROVIDER`, `TOOL_PROVIDER`, `HOOK_PROVIDER`, `TRACE_PROVIDER` (all `default`).

### A9. Trace-value router (sidecar)
`TRACE_VALUE_ROUTER_ENABLED` (`false`), `_SKILL` (`trace_value_router`), `_CONCURRENCY` (`1`), `_BATCH_LIMIT` (`25`), `_RETRY_LIMIT` (`1`), `_MAX_EVIDENCE_CHARS` (`12000`).

### A10. Storage / retention (infra)
`DB_BACKEND` (`sqlite`), `DATABASE_URL`, `DB_POOL_SIZE` (`10`), `MAINTENANCE_INTERVAL_SECONDS` (`86400`), `TRACE_RETENTION_DAYS` (`30`), `TRACE_BACKEND` (`sqlite`), `TRACE_PG_SCHEMA` (`trace`), `TRACE_DB_PATH`, `EVIDENCE_BACKEND` (`sqlite`), `EVIDENCE_PG_SCHEMA`, `EVIDENCE_DB_ROOT`, `CC_QUEUE_DB_PATH`, `WORKSTREAM_RUNTIME_DB_PATH`, `AUTOMATION_RUNTIME_DB_PATH`, `EVAL_RUNTIME_DB_PATH`, `RL_DB_PATH`.

### A11. Enterprise strict / queue / cron / security (infra + security)
`ENTERPRISE_STRICT_MODE` (`false`), `STUDIO_RUNTIME_ROLES` (`all`), `UVICORN_WORKERS` (`1`), `USE_REDIS_SESSIONS` (`false`), `QUEUE_WORKER_REPLICAS` (`1`), `CC_QUEUE_STORAGE_BACKEND` (`sqlite`), `CC_QUEUE_DATABASE_URL`, `QUEUE_CLAIM_LEASE_SECONDS` (`360`), `QUEUE_CLAIM_RECLAIM_LIMIT` (`3`), `QUEUE_WORKER_HEARTBEAT_TTL_SECONDS` (`30`), `SCHEDULER_LEADER_LOCK_TTL_SECONDS` (`45`), `SCHEDULER_LEADER_RETRY_SECONDS` (`5`), `DEMO_PUBLIC_SURFACES` (`true`), `QUEUE_INGEST_API_KEY`, `FILE_URL_SIGNING_SECRET`, `FILE_URL_TTL_SECONDS` (`300`), `ALLOW_UNSIGNED_FILE_URLS`, `CORS_ALLOWED_ORIGINS` (`*`), `TENANT_RATE_LIMIT_PER_MINUTE` (`600`), `AUTH_RATE_LIMIT_PER_MINUTE` (`60`), `AUTH_LOGIN_RATE_LIMIT` (`10`), plus the recovery-drill `RECOVERY_*` set.

### A12. Auth / entitlements / external-access (security, mostly undoc)
`AUTH_ENABLED`, `AUTH_PROVIDER`, `AUTH_BACKEND`, `AUTH_REGISTRATION_MODE`, `AUTH_SEED_ADMIN_ON_STARTUP`, `AUTH_MAX_FAILED_ATTEMPTS`, `AUTH_LOCKOUT_MINUTES`, `AUTH_PASSWORD_MIN_LENGTH`, `AUTH_REFRESH_COOKIE_NAME`, `AUTH_OIDC_*`, `KEYCLOAK_*`, `JWT_ACCESS_TTL_MINUTES`, `JWT_REFRESH_TTL_DAYS`, `ADMIN_PASSWORD`, `IAF_ADMIN_PASSWORD`, `CREDENTIAL_MASTER_KEY`, `SECRET_PROVIDER`, `MCP_KEY`, `MCP_TOKEN`, `ENTITLEMENTS_{ENABLED,PROVIDER,ENFORCEMENT_MODE,FAIL_CLOSED,AUDIT_ENABLED}`, `EXTERNAL_ACCESS_{ENABLED,REGISTRY,UNKNOWN_MODE,AUDIT_ENABLED,ENFORCE_CREDENTIALS,ENFORCE_MCP,ENFORCE_SQL}`, `AUDIT_EVIDENCE_MIRROR_{ENABLED,DIR,PREVIEW_LIMIT}`.

### A13. Networking / telemetry / misc (infra)
`HOST`, `PORT`, `BASE_URL`, `ROOT_PATH` (alias `APP_ROOT_PATH`; default `""` = root, e.g. `/qlabs` for sub-path deployments behind a gateway — sets ASGI `root_path` and injects a base-path bootstrap into served HTML so the frontend prefixes `/auth`,`/api`,`/oauth`,`/ws` calls; requires a paired gateway route), `BEHIND_PROXY`, `FORWARDED_ALLOW_IPS`, `NO_PROXY`, `SSL_CERTFILE`, `SSL_KEYFILE`, `LOG_LEVEL`, `IAF_DEBUG`, `DATA_ROOT`, `SKILLS_PATH`, `REDIS_URL`, `TELEMETRY_{EXPORTERS,OTLP_ENDPOINT,OTLP_SERVICE_NAME}`, `TRACE_TELEMETRY`, `TWIN_TELEMETRY`, `O365_{CLIENT_ID,CLIENT_SECRET,SENDER_EMAIL,TENANT_ID}`, and the `QUEUE_*` display/tuning set.

---

## Appendix B — Complete SKILL.md frontmatter field list

The **19 fields the runtime loader actually consumes** (`loader.py:113-134` → `agentos_contracts/skill.py`):

`name`, `version`, `description`, `execution_mode`, `steps`, `worker_skills`, `max_steps`,
`react_runtime`, `profile`, `sql_mode`, `approval_rules`, `evidence_highlights`, `knowledge`, `user_data`,
`business_context`, `tools`, `mcp_connections`, `mcp_tools`, `files`.

**Studio-only** (editing / registry / UI; not mapped onto the runtime `Skill`):
`keywords` (alias `triggers`), `connections`, `context_file` / `context_files`, `tool_scripts`
(disk-discovered from the skill's `tools/` dir, not parsed from frontmatter), `scope`.

**Documented but registry/config-level, NOT parsed from frontmatter:** `status`, `category`
(both live in `_index.yaml`), `hooks` (loaded by `HookRunner` from `config.yaml` / platform-hooks,
not from SKILL.md).

**Fields the authoring docs omit but the code reads** (should be documented):
`react_runtime`, `sql_mode`, `evidence_highlights`, `max_steps`, `user_data`, `mcp_tools`, `files`,
`knowledge`.

**Requested-but-nonexistent as SKILL.md fields** — these are *not* per-skill and must be set at
another layer: verifiers / critique / self-check (agent config + env/UI), confidence thresholds
(agent config `sufficiency.threshold` + hardcoded constants), retries / max_iterations (env + hardcoded),
timeouts (env + hardcoded), model / temperature (env).
