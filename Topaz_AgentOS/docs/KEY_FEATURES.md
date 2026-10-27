# IAF AgentOS — Key Features & Approaches

> Positioned for teams who already have an agent framework and want to understand
> what components and patterns from IAF AgentOS they can evaluate or plug in.

---

## 1. SafeKernel — Sandboxed Agent Execution Engine

The core of AgentOS is **SafeKernel** (`agent_os/kernel.py`), a secure shell-like execution engine that every agent runs through. It is not a thin wrapper — it is the enforcement layer that makes agent tool use safe at enterprise scale.

- **Path sandboxing via SafePath and kernel path resolution** — virtual paths (`/shared/`, `/me/`, `/workspace/`, etc.) are mapped before file I/O; `..` traversal is blocked at the string level. The standalone `SafePath.resolve()` helper also checks containment with `relative_to()` after `pathlib` resolution. The main kernel resolver (`SafeKernel._resolve_path()`) performs prefix routing and `..` blocking but **does not currently apply the same post-resolution symlink containment check on every mapped path** — review `agent_os/kernel.py` and `agent_os/safe_path.py` before treating symlink escape as fully mitigated.
- **Allowlist-controlled command execution** — only a declared set of commands (`cat`, `ls`, `grep`, `curl`, `python3`, etc.) can be invoked; any unlisted command is rejected at parse time, not at runtime
- **Python3 execution with optional OS-level sandboxing** — `AGENT_PYTHON3_ENABLED=true` unlocks inline Python execution; `AGENT_PYTHON3_SANDBOX_USER` runs code under a restricted OS user, isolating it from the server process entirely
- **Sliding-window rate limiter** — configurable max commands per minute per kernel instance; excess requests receive a structured `RATE_LIMITED` error, not a crash
- **Thread-safe file locking** — `FileLock` uses both `threading.Lock` (cross-thread) and `fcntl.flock` (cross-process on Unix) for atomic writes; prevents corruption under concurrent agent runs
- **Local mount (`/local`)** — optionally maps a real filesystem path into the sandbox at `/local`, letting agents read from enterprise data directories without escaping the sandbox boundary
- **Bundled ripgrep** — `rg` binary shipped in `vendor/bin/` for grep-acceleration; falls back to system `grep` automatically; no separate install required
- **Output truncation** — all command output is capped before it reaches the LLM; prevents context window blowout from large file reads or runaway grep results

**Further reading:** [kernel_internals.md](../agent_os/docs/kernel_internals.md), [safe_path_design.md](../agent_os/docs/safe_path_design.md)

---

## 2. Skill-Based Architecture

- Every capability is a self-contained **SKILL.md** — prompt, tools, routing keywords, context file, execution mode, MCP connections, and knowledge entries all declared in one YAML + markdown file
- **Skill files on disk with selective hot reload** — editing an existing `SKILL.md` is picked up on the next load via mtime cache (`SkillLoader`). Registering a **new** skill or changing routing metadata in `_index.yaml` updates the on-disk registry but **does not automatically refresh cached `SkillRouter` instances** in running agents — restart the server (or evict cached agents) after registry changes unless an API path explicitly reloads/evicts. See [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md).
- Personal skills per user sit alongside shared tenant skills, with automatic index merging at load time
- Skill prompts are the unit of authorship — domain experts write and maintain them without touching Python
- **Doc-to-Skill pipeline** — upload a PDF, DOCX, PPTX, XLSX, MP4, or audio file; an LLM extracts the process knowledge and generates a complete, deployable SKILL.md package automatically (`POST /api/skills/from-document`)

**Further reading:** [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) · [skill_templates/](skill_templates/)

---

## 3. Intelligent Multi-Signal Router

- One LLM call per query returns: target skill, entity name, entity type, query complexity class, and execution mode hint — all in a single JSON response
- Three pre-LLM signals feed the router prompt: **entity signal** (WHO — from ontology/FTS5 resolution), **taxonomy vector signal** (WHAT — from L5 taxonomy cosine+term-boost scoring against all indexed activities), and **keyword signal** (SKILL.md keyword match)
- Taxonomy signal runs in a background thread at startup — 272+ L5 activity nodes indexed from taxonomy markdown files; top hits injected into the router LLM prompt as informational context before the LLM makes its decision
- `TaxonomyRoutingCapability` wraps the runtime taxonomy lookup as a default-`current` facade. `TAXONOMY_ROUTING_MODE=shadow` can compare alternate taxonomy results asynchronously and record bounded drift diagnostics without changing the router-facing `process_matches` shape or selected skill; capability metadata marks authoritative taxonomy swaps as deferred until routing-quality parity is proven.
- Router LLM decides `complexity_class` (`simple` / `multi_step` / `multi_domain`) and `mode_hint` (`react` / `orchestrator` / `planned`) based on the full signal set
- `execution_mode` in the routing result is authoritative — agent.py uses it directly; no post-hoc overrides
- Keyword fallback and sticky-skill fallback (short follow-up replies stay on current skill) if LLM routing is uncertain

**Further reading:** [entity_registry.md](../IAF-Agent-Skills/docs/entity_registry.md), [context_loading_architecture.md](../IAF-Agent-Studio/docs/context_loading_architecture.md)

---

## 4. Multiple Execution Modes on One Runtime

- `react` — standard tool-calling loop; default for single-domain queries; agent decides tool sequence at each step
- `react_runtime` — implementation selector for `react` only; `langgraph` is the default/rollback path, while `native` uses Azure OpenAI native tool calls and preserves provider metadata through the same governance boundary
- `orchestrator` — router auto-selects when query is `multi_step`; manager LLM dispatches child skills sequentially with output feeding next; each child runs its own full ReAct loop; synthesises results at the end
- `planned` — router auto-selects when query is `multi_domain` (2+ unrelated business domains); PlannerEngine builds a DAG of sub-agents; no separate infrastructure required
- `workflow` / `parallel` / `supervisor` — explicitly declared in SKILL.md for deterministic pipelines, concurrent DAGs, and meta-agent patterns
- `rlm` — reasoning-as-code: the model writes Python that calls a governed tool allow-list, with an AST guard and propose-then-apply HITL holds (see §22)
- `graph` — a stored process-graph (`graph_ref: graph.yaml`) of skill-nodes with verifier nodes + a convergence loop, executed by `planner.execute_graph` (see §23)
- Mode is declared per-skill in SKILL.md OR auto-selected by the router (orchestrator / planned); explicit skill-level config always takes priority

**Further reading:** [execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md), [RLM_EXECUTION_MODE.md](RLM_EXECUTION_MODE.md), [PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md)

---

## 5. Auto-Mode Upgrade (Dynamic Orchestration)

- If the router LLM classifies a query as `multi_step` or `multi_domain` — informed by the L5 taxonomy vector signal — the agent automatically upgrades the execution mode to `orchestrator` or `planned` respectively; the SKILL.md `execution_mode` setting is overridden at runtime
- Zero SKILL.md changes needed on any skill — the worker list is constructed dynamically from the live skill index
- The orchestrator manager prompt enforces a critical rule: child skills run in a fully automated pipeline and cannot ask the user for input; the manager must make reasonable assumptions and state them in the task text
- Graceful fallback: if the dynamic orchestrator raises an exception, execution silently drops back to ReAct for the same query

---

## 6. Two Pluggable Context Loading Modes

- **File mode** — the router LLM extracts the entity name from the query; the agent reads `Enterprise_Context.md` and linked markdown files at runtime using the shell tool; zero database setup required; easiest to get started
- **Table mode** — SQLite entity registry with FTS5 keyword search + cosine similarity fallback; auto-registers new entity names seen in tool responses; full ontology tree (tower → process → activity → skill → entity)
- Both modes produce identical downstream storage (episodic memory, knowledge store, plan cache all work the same)
- Switch is a single config line: `context_loading_mode: file | table`

**Further reading:** [context_loading_architecture.md](../IAF-Agent-Studio/docs/context_loading_architecture.md), [entity_registry.md](../IAF-Agent-Skills/docs/entity_registry.md)

---

## 7. Three-Layer Memory System

- **Episodic memory** — every conversation stored as a vector-indexed episode; semantic search over past sessions fires before routing so similar prior solutions surface automatically
- **Knowledge store** — facts, patterns, and exceptions extracted asynchronously after every reply; `confirmed` entries are injected into future prompts as grounded context; `pending_review` entries wait for human approval in the Studio UI
- **Plan cache** — successful query → skill → tool sequences stored with two-layer deduplication: structural fingerprint match first, then embedding cosine similarity ≥ 0.90; approved plans replay on similar future queries without re-routing
- All three layers share the same pre-computed query embedding — one embedding API call per query, reused everywhere; no duplicate calls
- `MemoryCapability` provides a pass-through adapter boundary over the current `AgentMemory` and implicit learning write paths. It is default-off (`IAF_MEMORY_CAPABILITY_ENABLED=false`) so the direct write path remains the runtime default; memory/vector provider swaps are explicitly deferred until corpus and behavior parity are proven.

**Further reading:** [memory_schema.md](../IAF-Agent-Skills/docs/memory_schema.md)

---

## 8. Hybrid Semantic + Keyword Search

- `search_similar()` tries cosine similarity first (query embedding vs stored BLOB in SQLite), falls back to FTS5 BM25 keyword search if embedding is unavailable
- **Hybrid mode** (default): semantic first, scan backfill if fewer than 3 results returned
- System works fully without an embedding model — degrades gracefully to FTS5-only with no configuration change
- Embeddings stored as binary BLOBs in SQLite — no external vector database dependency; the same SQLite file holds structured data and vector data together
- Entity resolution uses the same pattern: FTS5 AND → FTS5 OR → cosine fallback, with configurable similarity threshold (default 0.75)

**Further reading:** [memory_schema.md](../IAF-Agent-Skills/docs/memory_schema.md), [entity_registry.md](../IAF-Agent-Skills/docs/entity_registry.md)

---

## 9. Multi-Provider LLM Registry (Bring Your Own Model)

The system is provider-agnostic and runs in four selectable modes — no code change required, only config changes.

- **Mode 1 — Per-role hybrid**: each role (`primary`, `light`, `fallback`, `router`) independently selects its provider (`azure` | `openai` | `vertex`) and model; e.g. Gemini 2.5 Flash for reasoning, a local Gemma via OpenAI-compatible API for cheap classification, Azure GPT-4o as fallback
- **Mode 2 — OpenAI-compatible server**: point the whole system at any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, local Llama) with a single `OPENAI_BASE_URL`; per-role model overrides still work
- **Mode 3 — Azure OpenAI only**: original mode, zero new config vars needed; works for teams fully on Azure
- **Mode 4 — Google Vertex AI (Gemini)**: service-account JSON auth (no API key, no `gcloud` CLI at runtime); supports `gemini-2.5-flash` and `gemini-2.5-pro`. Custom SSL context handles corporate proxy SSL inspection (Zscaler etc.). See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#using-google-vertex-ai-gemini)
- **Role separation is enforced in code**: the router always uses a fast/cheap model; the primary reasoning model is separate; the light model handles background tasks (implicit learning, queue routing); the fallback model is used on primary failure
- Model instances are cached per role — repeated calls within a request are free; no re-instantiation overhead
- Adding a new provider (e.g. Anthropic, Bedrock) requires one new branch in `ModelRegistry._create()` — no other file changes

---

## 10. AI FinOps — Cost & Token Observability

Every LLM call is tracked, attributed, and queryable — not just for debugging but for cost governance at scale.

- **Per-call attribution**: every LLM invocation records model name, role (router / agent / light), token counts (prompt + completion), USD cost, duration, skill name, and session ID — written to `traces.db`
- **Execution-mode-safe traces**: ReAct, workflow, parallel, supervisor, orchestrator, and dynamic orchestrator paths all finalize parent traces; router LLM usage is replayed into the trace budget when routing happens before `agent.run()`
- **HITL-aware trace status**: runs that pause for human approval close as `awaiting_human` with token/cost totals preserved, while old unfinished rows surface as `stale` instead of looking actively running forever
- **Cost calculation from YAML**: `model_pricing.yaml` drives pricing — substring-matched against deployment name; update pricing in one file, no code change
- **FinOps dashboard API** (`/api/finops/*`): summary, trends over time, breakdown by purpose, breakdown by skill, breakdown by model — all queryable with date range filters
- **Cross-session rollups**: daily/weekly/monthly spend totals per skill and per model; identify which skills are cost-heavy and which use cheap models efficiently
- **Zero sampling**: every call is recorded, not sampled; the system is designed to be the source of truth for LLM spend, not an approximation

---

## 11. Hook System

- Lifecycle events cover tool, step, turn, model-call, approval-resume, schedule, background-task, and queue execution boundaries. `PreToolUse` can block before execution; `PostToolUse` is the single post-tool audit point; queue lifecycle hooks are Phase 1 observe-only/fail-open and run through the per-item `SkillAgent` hook runner.
- Each hook is a shell command declared in `config.yaml` — no Python changes needed to add audit logging, circuit breakers, or validation logic
- Per-hook controls: `block_on_nonzero` (hard gate that stops execution vs fire-and-forget audit), `timeout_seconds`, `matcher` (filter hook to a specific tool name, e.g. only fire on `invoke_skill`)
- Used in production for: orchestrator circuit breakers, skill invocation audit logs, approval resume gates, result validators, failure alerters — all declarative
- **UI-authorable:** the Security Console's **Hooks** panel (admin-only) lets you create/edit hooks — including a one-click blocking-PreToolUse HITL gate — and writes only the tenant `hooks:` subtree of `config.yaml` (validated server-side, agent cache evicted so it applies with no restart, change audited). No hand-editing YAML.
- **Central Policy & Control Registry:** Dashboard V2 adds a governance-facing policy page above raw hooks. Admins define structured policies (scope, lifecycle event, matcher, conditions, decision mode, fail policy, evidence requirements), validate/simulate them, then publish active policies into the existing hooks runtime. The registry also inventories tenant hooks authored in Skill Builder V2 as read-only unmanaged hook-backed controls, with an adoption path that copies a hook into a managed policy draft. Generated hooks call the fixed `shared/hooks/policy_engine.py` evaluator, so business fields never generate arbitrary Python. `approve` decisions compile to blocking `PreToolUse` hooks and reuse the existing HITL checkpoint/resume path.
- **Platform-owned built-in governance:** the orchestrator circuit-breaker/audit/validator hooks are **framework-owned** (`iaf_agent_skills/platform_hooks/`), merged in at load time, always run **first**, and are **read-only** from the tenant UI/API — so built-in controls can't be accidentally deleted. Tenant hooks are merged additively on top.

**Further reading:** [HOOK_SYSTEM_DESIGN.md](../IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md)

---

## 12. Human-in-the-Loop (HITL)

- Four configurable mechanisms, applicable at different granularities:
  1. **`approval_rules` in SKILL.md** — regex patterns on tool arguments that pause execution (e.g. match any SQL `DELETE`)
  2. **`hitl` block in `config.yaml`** — agent-level SQL pattern detection across all skills
  3. **PreToolUse hook** — hook script returns non-zero to block a specific tool call
  4. **Prompt instructions** — agent taught to ask before acting in specific situations
- When triggered: execution suspends, user sees an approve/reject card in chat via WebSocket; agent holds state and resumes on approval or abandons on rejection
- Approval flows also surface in the queue monitor and a dedicated `#approvals` tab
- Inside queue execution: if an approval gate triggers, the job transitions to `awaiting_human` state and holds position in the queue until a decision is made; no timeout loss
- Configurable urgency and SLA per approval type

**Further reading:** [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md)

---

## 13. Implicit Learning

- After every reply, a lightweight LLM pass (cheap/fast model) analyses the exchange for learnable signals: corrections, stated preferences, clarifications, repeated patterns
- Detected signals are written as `pending_review` entries to the knowledge store — they do not affect future prompts until a human confirms them in the Studio UI
- Agent detects its own explicit `<!-- LEARN: -->` markers in responses and skips implicit learning for that turn to avoid duplicate entries
- Runs asynchronously in a background thread — zero latency impact on the response

**Further reading:** [memory_schema.md](../IAF-Agent-Skills/docs/memory_schema.md)

---

## 14. Self-Evolution Engine (4 Tiers)

- Reads past session logs and skill files; analyses gaps; generates concrete improvement suggestions — without touching the running system
- **Tier 1** — loads and indexes raw session logs
- **Tier 2** — classifies sessions by outcome, intent, and failure type using LLM
- **Tier 3a** — LLM reviews SKILL.md quality: clarity, routing keyword completeness, tool guidance, edge case handling, memory instructions, output format
- **Tier 3b** — LLM reviews Python source code for bugs, missing error handling, and architectural gaps
- **Tier 4** — generates concrete improvement suggestions with file-level and line-level changes; outputs feed directly into skill authoring and code review workflows
- Triggered on demand from the Studio Evolution tab; Tier 3a/3b can run independently (skill authors use 3a, developers use 3b)

---

## 15. Command Center Queue & Background Jobs

The queue is the backbone for all non-interactive, background, and scheduled work. It is not a bolted-on feature — it is a first-class execution path alongside the interactive chat path.

- **REST ingest** (`POST /api/queue/ingest`) — any external system, cron job, or skill can push a task; queue processor picks it up within 2 seconds
- **Configurable concurrency** — `max_concurrent` workers process jobs in parallel; per-job timeout prevents runaway tasks from blocking the queue
- **Dead-letter queue (DLQ)** — failed jobs that exceed retry policy move to DLQ for manual review; they do not silently disappear
- **Full state machine**: `queued → running → done | dlq | awaiting_human` — every transition is timestamped and queryable
- **Step-level audit trail** — every tool call, LLM response, and decision inside a queued job is stored; you can replay what happened at any point in the execution
- **Queue lifecycle audit and hooks** — received/routed records are emitted to the structured queue audit sink before a skill exists; skill execution then emits observe-only hook events for start, complete, error, retry, DLQ, and HITL-pending using the same per-item `SkillAgent.hook_runner` as chat execution
- **HITL inside queue** — approval gates work identically in queue and interactive mode; job suspends, waits, resumes — no need for a separate queue path for human-gated workflows
- **Cron scheduler (Redis-backed)** — recurring triggers with full cron expressions; jobs survive server restart via Redis persistence; configurable routing (direct skill or via queue); 9 default system jobs pre-seeded at startup; manage from Studio UI without touching config files
- **Service principal enforcement** — cron, queue, and HITL resume entry points create dedicated service `IdentityContext` objects that export as principals (`service:cron`, `service:queue`, `service:hitl_resume`) and wire entitlement context before `agent.run()`, ensuring external access gates (credential, MCP, DB, curl audit) are never bypassed in background execution
- **Policy provider boundary** — route helpers and SafeKernel gates resolve through the selected `EntitlementProvider`, which normalizes decisions into identity, tenant, action, resource, skill, tool, risk, and request-context inputs; provider failures fail closed by default, while `ENTITLEMENTS_ENFORCEMENT_MODE=observe` records would-deny decisions without blocking local rollout validation

**Further reading:** [cc_queue.md](../IAF-Agent-Studio/docs/cc_queue.md), [CRON_SCHEDULER.md](../IAF-Agent-Studio/docs/CRON_SCHEDULER.md)

---

## 16. Enterprise Credential Store

Skills often need to call external APIs — the credential store keeps secrets out of SKILL.md prompts and out of LLM context entirely.

- **Three pluggable backends** — `EnvBackend` (environment variables), `YamlFileBackend` (plain YAML for dev), `FernetFileBackend` (AES-256 Fernet encrypted YAML for production); selected automatically based on config
- **Secret provider boundary** — `SafeKernel.get_credential` resolves through `SecretProvider` after external-access entitlement checks; the local provider wraps the current `CredentialStore`, and enterprise vault adapters can be injected while preserving the normalized `Credential` contract
- **Scope-based access control** — each credential declares a `scope` list (e.g. `[itops_rca, ccdops]`); skills can only retrieve credentials whose scope matches their declared domain; cross-skill credential leakage is prevented at the store level
- **Access audit log** — every credential retrieval is recorded with timestamp, requesting skill, and purpose; queryable for compliance
- **Helper methods for injection** — `Credential.to_headers()` and `Credential.to_curl_args()` give skills a clean API to inject credentials into HTTP calls without formatting them manually
- **TTL metadata** — credentials carry an optional `token_expires` field; expiry warnings surface in the Studio admin panel before agents start getting 401s

---

## 17. Real-Time Progress Stepper & WebSocket Streaming

Users see structured, phase-by-phase progress during long-running agent calls — not just a spinner.

- **6 named phases** emitted as structured WebSocket events: `loading_context → building_prompt → generating → executing_tools → processing → saving`
- Each phase message carries: phase name, index, total phases (for % progress bar), status (`active | completed | error`), sub-step (current tool name), human-readable detail, and elapsed ms
- **Reasoning panel** — routing, tool activity, checks, and a bounded `Why` summary stream to a collapsible panel in the UI; native React turns seed the summary from observable runtime/tool metadata immediately, while deeper async episode reasoning can replace it later
- **Span-level tracing** — every tool call emits a trace span with duration, input, and output; spans are stored in `traces.db` and visible in the Studio audit tab
- The same streaming channel carries: progress phases, reasoning steps, tool results, HITL approval requests, and the final answer — one WebSocket connection per session, no polling

---

## 18. Operational Digital Twin

The twin layer captures a continuous, real-time picture of business operations across all agent activity — it is the observability layer for the processes the agents are running, not just the agents themselves.

- **Real-time telemetry** — every skill execution emits structured events to `twin_telemetry.db` asynchronously; zero impact on response latency
- **Provider fanout** — `TraceEmitter` and `TwinEmitter` keep local SQLite as the default durable store and can mirror redacted, bounded payloads to external providers such as OTLP JSON with `TELEMETRY_EXPORTERS=local,otlp`; provider errors are non-fatal and show as degraded capability diagnostics
- **Process health scoring** — `/api/twin/process_health` computes green/yellow/red health scores per tower and L2 process based on volume, exception rate, and SLA adherence
- **Drill-down APIs** — separate endpoints for AR aging, AP aging, exception counts, and activity feed; each supports date-range and entity filtering
- **Trend analysis** — `/api/twin/trends` returns time-series data for volume, exception rate, and cycle time across configurable windows
- **HITL visibility** — approval queue and HITL metrics surface in the twin dashboard alongside process metrics; human intervention patterns are part of the operational picture
- **Background optimization jobs** — `/api/twin/optimization/analyze` triggers an async LLM analysis of the twin data and returns a job ID; status polled via `/api/twin/optimization/status/{job_id}`
- **Live WebSocket push** — `/ws/twin` and `/ws/dashboard` push twin events to connected Studio clients without polling; dashboards update as events arrive

---

## 19. Multi-Tenant, Multi-Agent

- Filesystem-isolated tenant hierarchy: `enterprise_root/tenants/{tenant_id}/agents/{agent_id}/`
- Each agent has isolated config, memory DB, skill index, and credential store
- Shared read-only resources (`/shared/`) accessible across agents in the same tenant; agents cannot write to shared resources (enforced by SafePath)
- **Authentication system** — JWT access + refresh token pair for local auth plus provider-neutral `IdentityContext` resolution for local HS JWT and enterprise OIDC/JWKS access tokens; configurable TTL; registration modes (`open | approval | admin_only`); IP-based rate limiting on login; account lockout after configurable failed attempts; admin endpoints for user management and password reset
- **Entitlement layer** — optional `ENTITLEMENTS_ENABLED` policy checks bind chat identity through `IdentityContext`, enforce tenant membership, filter usable skills, gate tools/context/credentials, and protect Studio/admin operations through tenant-owned YAML policy files under `enterprise_root/tenants/{tenant_id}/security/policies.yaml`; external access governance maps credentials, MCP connections, databases, and outbound systems in `security/external_access.yaml` so admins grant business-facing `external:*` resources while the kernel enforces masked credential and DB access with risk/label context passed into provider decisions
- Redis session store with AOF persistence — sessions survive server restart; horizontal scaling ready (multiple server instances share session state via Redis)

**Further reading:** [multitenant_design.md](../enterprise_root/docs/multitenant_design.md)

---

## 20. AgentPro Studio & Skill Builder UI

- **Unified Studio/Customize surface** (`/studio`, also available as `/customize`) brings the skill lifecycle into one page: create, browse, open, test, submit for review, approve/publish, schedule, attach knowledge, inspect connectors, manage agents, and monitor outcomes
- **Skills directory** shows tenant and personal skills with category, execution mode, lifecycle scope/status, tools, context files, and schedule count; workspace filters separate `All`, `My Drafts`, `Submitted`, `Approved`, and `Published`
- **Skill detail lifecycle tabs** centralize Overview, Knowledge, Tools, Test, Schedule, Runs, and Settings so authors can iterate without hunting across modals
- **Personal draft and review workflow** reuses `/api/personal-skills/*` and `/api/skill-submissions/*` so users can save drafts, edit personal `SKILL.md` content inline with YAML validation, submit them, and admins can preview conflicts/diffs, require reject feedback, approve safely, and promote skills into the shared registry
- **Knowledge attachment** uploads skill-scoped files through `/api/skills/{skill}/knowledge/upload`, returning status, extension, size, and modified time so grounding stays visible close to the skill that consumes it
- **Studio test history** stores compact per-user test run previews from `/api/skills/{skill}/test` and shows recent Studio runs on skill detail pages
- **Schedule management** reuses the Redis-backed cron APIs so users can create, enable/disable, run-now, and inspect schedules for a selected skill
- **Per-skill observability** combines scheduled run history, trace lookup, evidence links, and FinOps summary for the selected skill
- **Connector readiness** calls `/api/agents/{agent}/connectors/health` to validate MCP connector configuration without launching arbitrary connector processes
- **Capability diagnostics** expose read-only `/api/capabilities/snapshot`, `/api/capabilities/parity`, and `/api/agents/{agent}/tool-execution/snapshot` for registry health, runtime drift, bounded redacted tool observations, sanitized telemetry provider health, sanitized secret provider health, sanitized policy provider health, and sanitized audit/evidence sink health; memory appears as a per-agent pass-through capability with no live provider object in the global snapshot
- **Telemetry E2E smoke** (`IAF-Agent-Studio/tests/run_telemetry_provider_e2e.py`) validates the provider fanout against a real local HTTP collector and local SQLite stores without requiring external collector credentials
- **Identity E2E smoke** (`IAF-Agent-Studio/tests/run_identity_provider_e2e.py`) validates local auth registration/login, protected `/auth/me`, and tenant-bound conversation identity on a live auth-enabled server; enterprise OIDC remains contract-tested until a sandbox tenant is supplied
- **Secret provider E2E smoke** (`IAF-Agent-Studio/tests/run_secret_provider_e2e.py`) validates a real temporary tenant credential file through `SafeKernel.run_shell_command("get_credential ...")`, confirming masked output, provider audit snapshot, and no secret leakage without requiring cloud vault credentials
- **Policy provider E2E smoke** (`IAF-Agent-Studio/tests/run_policy_provider_e2e.py`) validates selected YAML provider resolution through the real security dependency helper, proving deny in enforce mode, allow-with-audit in observe mode, and audit-safe decision rows without requiring OPA/Azure credentials
- **Audit/evidence sink E2E smoke** (`IAF-Agent-Studio/tests/run_audit_evidence_sink_e2e.py`) validates entitlement audit JSONL, local evidence SQLite, and optional bounded JSONL mirror fanout together without requiring Splunk/Sentinel/cloud credentials
- **Deferred provider guardrails** (`IAF-Agent-Studio/tests/test_deferred_provider_boundaries.py`) assert queue/approval providers remain direct local/Redis singletons, memory remains default-off/direct, taxonomy shadow mode never changes authoritative results, and model provider hardening stays routed through `default_model_provider.get(role)`; Phase 8 React runtime tests keep native mode reversible behind `react_runtime` with LangGraph as default
- **Adapter authoring lifecycle** ([ADAPTER_AUTHORING_GUIDE.md](ADAPTER_AUTHORING_GUIDE.md)) documents provider-backed replaceability: extend the current abstraction, route a real call site, keep local rollback, expose safe diagnostics, add contract/E2E tests, and state sandbox/customer validation limits
- **Security Console** lets admins validate and save tenant entitlement policies, inspect external access inventory, simulate access decisions for roles/groups/resources, view a user's effective access across live agents/skills/tools/context files/external systems/databases/MCP connections, see a **consolidated Users & Access matrix** (every user joined with what they can reach per resource type, with click-through to per-resource allow/deny — composed from the user roster and the effective-access endpoint), and inspect recent entitlement audit decisions from Studio; the **External Access Registry Manager** provides a dual-view (Form + YAML) editor to create, validate, and save external resource declarations; the **Credential Manager** panel lists encrypted credentials (secrets never exposed in API responses), supports create/delete via Form view, and shows a read-only masked YAML view for auditing
- **Playwright smoke coverage** (`IAF-Agent-Studio/tests/run_studio_playwright_smoke.sh`) exercises the no-build Studio page with mocked APIs by default, and can run an authenticated navigation smoke with `STUDIO_USE_MOCKS=false` plus auth env vars
- **Business-friendly chat polish** keeps the existing chat layout and controls intact while improving the `/` surface with an executive header treatment, an empty-state executive briefing panel, richer prompt cards, refined response cards, and an `Execution Trace` label for routing/tool progress
- **Advanced editor remains Skill Builder v2** (`/skill-builder/v2`) for SKILL.md, execution modes, workflow/parallel/supervisor internals, tools, and YAML-level authoring
- **Doc-to-Skill flow** (`/skill-creator`) remains the guided path for turning business documents into deployable skill packages

---

## 21. MCP Tool Integration

Skills can connect to any MCP-compatible tool server — the bridge handles protocol differences transparently.

- **Three connection types** declared in SKILL.md `mcp_connections`:
  - `direct+stdio` — local MCP server launched as a subprocess (e.g. a custom Python tool server)
  - `direct+http` — remote MCP server via streamable HTTP
  - `registry` — Enterprise MCP Registry: tools are discovered via REST, calls are proxied through the registry (auth, rate-limiting, and routing handled centrally)
- **Sync wrapper for async tools** — MCP tools from `langchain-mcp-adapters` are async-only; the bridge wraps them in a fresh event loop so the ReAct agent can call them synchronously without architectural changes
- **Env var interpolation in auth tokens** — `${MCP_TOKEN}` in connection configs is resolved from environment at load time; secrets never appear in SKILL.md files
- Per-skill MCP connections — each skill declares only the tool servers it needs; no global tool list that every agent sees

**Further reading:** [05_agent_config.md](05_agent_config.md) (MCP connections section)

---

## 22. RLM Execution Mode (Reasoning-as-Code)

- `execution_mode: rlm` — the model writes small Python snippets that call a **governed** tool
  allow-list in a loop, instead of the free-form React tool loop. Best for computation, data
  crunching, and multi-tool orchestration.
- **Same governance, not a bypass** — every tool call goes through `govern_tool_call(..., source="rlm_repl")`; an **AST guard** rejects imports, dunder-attribute access, and escape names before any code runs.
- **Propose-then-apply** — side effects call `propose_action(...)` (a *hold*) that does not execute; holds become real **HITL approval cards** in Command Center and only run on Approve (with an idempotency guard).

**Further reading:** [RLM_EXECUTION_MODE.md](RLM_EXECUTION_MODE.md)

---

## 23. Process Graphs & Graph Studio

- **Process graph** — a *stored*, versioned DAG of skill-nodes (`execution_mode: graph` + `graph_ref: graph.yaml`) with **verifier nodes** and a **convergence loop** (iterate a scope until the verifier passes; escalate to a human on exhaustion). Runs on the same planner engine as plan mode (`compile_to_plan` → `execute_graph`).
- **Graph Studio** — an admin-only **🕸 Graphs** tab in `/skill-builder/v2`: a gallery of graphs plus a **structured visual editor** (node/edge/convergence forms ⇄ synced YAML ⇄ live Mermaid diagram), **Draft with AI**, templates, inline **Validate**, and **Run ▸** (streams live in chat).
- Plan mode = *discovery* (ephemeral, LLM-built DAG); graph = *codification* (governed, reusable).

**Further reading:** [PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md)

---

## 24. Skill Designer (NL Authoring, Dev Mode)

- Describe a capability in English → the platform **drafts** a skill (any mode), graph, workstream, or cron, shows it in an editable canvas, and saves it via the **existing governed creators**.
- **Isolated & draft-only** — a `tools: []` authoring skill invoked with a forced `skill_name` server-side, so it never reaches the runtime router and never executes business actions.
- **Governed save** — skills/graphs route through the existing **personal → review-queue → admin-approve** flow (Command Center ▸ Skill Review); workstream/cron save via their creators. Role-gated (developer/admin/owner).

**Further reading:** [SKILL_DESIGNER.md](SKILL_DESIGNER.md)

---

## 25. Live "Thinking Box"

- Every chat turn shows a per-turn **🧠 thinking box** between the question and the answer: a live status line + **ticking elapsed**, phase dots, and an expandable timeline (tools, reasoning, RLM code cards). It collapses to **"Thought for Ns"** when the answer lands.
- Driven by a **contextual heartbeat** (`chat.py`, ~1.5s: narrates the current step + per-activity elapsed) plus per-turn reasoning/tool activity emitted by the native React runtime — so long, silent steps still narrate roughly every second.

---

## 26. RL / Eval Capture (opt-in, framework-neutral)

- An **opt-in capture layer** (`rl_capture/`) records raw agent **trajectories** and judgment signals
  for evaluation, SFT, rejection-SFT, DPO/KTO/RFT, and model-migration workflows. It **does not train
  models or assign shaped rewards during capture** — it's a sidecar, decoupled from execution.
- **Flags:** `RL_CAPTURE` (default `false`) turns it on for REST/WebSocket chat turns + selected
  operational outcomes; `RL_REDACT` (default `true`) masks secret-looking values; `RL_CAPTURE_REASONING`
  (default `false`); `RL_DB_PATH` overrides the store path.
- **Store:** per-tenant SQLite at `enterprise_root/tenants/{tenant}/shared/databases/rl.db` with tables
  for `trajectories`, `trajectory_steps`, `model_calls`, `tool_calls`, `observations`,
  `candidate_outputs`, `reward_events`, `preference_signals`, `evaluator_results`, `shadow_runs`.
- **How it's fed:** neutral events emitted via `iaf_agent_skills.capture_events` are mirrored into the
  RL store (incremental model-call / tool-call / observation rows, hook outcomes, evaluator results)
  without leaking RL-schema imports into execution-mode code; when `MODEL_CALL_PIPELINE_ENABLED=true`,
  provider calls run through `PolicyChatModel`'s Before/Around/After phases.
- **Trace Value Router** (`/api/trace-value/*`) — advisory assessment of which captured traces are worth
  learning from, with **governed human promotion** to learning destinations (nothing auto-trains).
- **Private Learning Loop** (`/api/evals/*`, `routers/evals.py`) — eval **suites**, **golden sets**,
  pluggable **evaluators**, promotion **gates**, dashboard summaries + recommendations; there is an
  **Eval** tab inside the skill builder. Weighted suite runner + registry under `rl_capture/evals/`.
- **Dataset exporters** — `sft`, `rejection_sft`, `dpo`, `kto`, `rft`, `eval_jsonl` (`rl_capture/exporters/`);
  SQLite default, optional Postgres backend + migration script.
- **UI:** Agent Training **Studio** (`static/rl_capture.html`) and **Workbench** (`static/rl_workbench.html`).

**Further reading:** [RL_EVAL_CAPTURE.md](RL_EVAL_CAPTURE.md), [RL_CAPTURE_PHASE1_PLAN.md](RL_CAPTURE_PHASE1_PLAN.md), [PRIVATE_LEARNING_LOOP.md](PRIVATE_LEARNING_LOOP.md)

---

## 27. Workstreams & Mission Mode (recurring autonomous operations)

- **Workstreams** turn a skill into a **recurring operation over a backlog of items** — process N items
  per run, track per-item state, retry, and escalate. Defined as YAML (`workstream_store.py`), executed
  by the **Mission Mode** engine (`mission_engine.py`); high-churn execution/step rows live in
  `workstream_runtime.db` while the YAML stays the portable business definition.
- **Cron-backed schedules** — a workstream with `cron_schedule`/`cron_user_id` is reconciled into the
  Redis-backed scheduler on startup, so restored workstreams keep running after Redis resets or branch
  restores. Per-item **HITL** and evidence bundles are supported.
- `/api/workstreams/*` + `/ws/workstreams/{name}` for live item execution; authored in the skill builder.

**Further reading:** [MISSION_MODE_GUIDE.md](MISSION_MODE_GUIDE.md), [WORKSTREAMS_AS_RECURRING_OPERATIONS.md](WORKSTREAMS_AS_RECURRING_OPERATIONS.md), [WORKSTREAM_SKILL_CONTRACT_GUIDE.md](WORKSTREAM_SKILL_CONTRACT_GUIDE.md)

---

## 28. World Model (entity/relation graph)

- A **World Model** graph store (`world_model.py`) accumulates entities and relations the agent learns,
  with a **human review + promote/reject** surface (`/api/world-model/*`, `static/world_model_review.html`)
  so the graph grows under governance rather than automatically.
- Pluggable graph backend via `GRAPH_BACKEND` — `relational` (default) or **Apache AGE** (`age`) for
  native graph queries.

---

## 29. Deterministic Automations (no-LLM pipelines)

- **Automations** are declarative **shell/python pipelines that run without an LLM** — for fixed,
  auditable operational tasks. Defined as YAML under `enterprise_root/tenants/<tenant>/automations/`,
  run from REST, cron, or Workstreams (`automation.py`, `/api/automations/*`); step traces persist in
  `automation_runtime.db`.

**Further reading:** [DETERMINISTIC_AUTOMATIONS.md](DETERMINISTIC_AUTOMATIONS.md)

---

## 30. Skill Packs (import / export)

- **Skill Packs** bundle skills (prompt, tools, context, components) for **export and import across
  tenants/environments** (`routers/skill_packs.py`, `/api/skill-packs/*`) — the portability unit for
  sharing capabilities.

**Further reading:** [SKILL_PACK_SPEC.md](SKILL_PACK_SPEC.md)

---

## What Can Be Plugged In Independently

These components are loosely coupled — most can be adopted without taking the full stack:

| Component | Can plug in standalone | What you get |
|---|---|---|
| SafeKernel | Yes | Sandboxed agent shell with path enforcement and rate limiting |
| Multi-signal router | Yes | Smarter skill/tool selection with WHO + WHAT signals |
| Hook system | Yes | Declarative audit, circuit-break, validation at each step |
| Episodic memory | Yes | Past conversation retrieval before each query |
| Knowledge store | Yes | Confirmed fact injection into prompts |
| Plan cache | Yes | Replay successful query patterns without re-routing |
| Hybrid search (FTS5 + cosine) | Yes | No vector DB dependency; works with any SQLite |
| Self-evolution engine | Yes | Offline skill-gap detection from session logs |
| HITL approval flow | Yes | Human gate on any tool call or SQL pattern |
| Implicit learning | Yes | Continuous improvement signal extraction from usage |
| Skill YAML format | Yes | Declarative capability management without code changes |
| Context loading modes | Yes | File-based or DB-based entity resolution, switchable |
| ModelRegistry | Yes | Provider-agnostic LLM factory; swap models without code changes |
| Credential store | Yes | Scoped secret management with audit log |
| FinOps tracker | Yes | Per-call LLM cost attribution with no external dependency |
| Command Center Queue | Yes | Background job execution with DLQ, HITL, and cron |
| MCP bridge | Yes | Connect any MCP tool server to any agent skill |

---

## Documentation Map

| Feature | Primary doc |
|---|---|
| SafeKernel & sandbox | [kernel_internals.md](../agent_os/docs/kernel_internals.md) |
| Skill authoring | [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) · [skill_templates/](skill_templates/) |
| Execution modes | [execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md) |
| Memory & learning | [memory_schema.md](../IAF-Agent-Skills/docs/memory_schema.md) |
| Hook system | [HOOK_SYSTEM_DESIGN.md](../IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md) |
| Entity registry & routing signals | [entity_registry.md](../IAF-Agent-Skills/docs/entity_registry.md) |
| Context loading (file vs table) | [context_loading_architecture.md](../IAF-Agent-Studio/docs/context_loading_architecture.md) |
| HITL | [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md) |
| Queue & cron | [cc_queue.md](../IAF-Agent-Studio/docs/cc_queue.md), [CRON_SCHEDULER.md](../IAF-Agent-Studio/docs/CRON_SCHEDULER.md) |
| Multi-tenant | [multitenant_design.md](../enterprise_root/docs/multitenant_design.md) |
| MCP integration | [05_agent_config.md](05_agent_config.md) |
| Taxonomy signal index | [TAXONOMY_AUTHORING.md](TAXONOMY_AUTHORING.md) |
| Overall architecture | [03_architecture.md](03_architecture.md) |
