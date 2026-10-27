# Configuration Reference

This harness-level reference records runtime environment variables that affect
`IAF_AgentOS_Harness_latest`.

## Runtime Provider Slots

All provider slots default to `default`, which preserves the built-in AgentPro
behavior. Custom values use `module:Class` import paths.

| Env Var | Default | Default Implementation | Purpose |
|---|---|---|---|
| `SKILL_PROVIDER` | `default` | `FileSystemSkillProvider` | Skill registry and prompt loading |
| `ROUTER_PROVIDER` | `default` | `DefaultRouterProvider` | Query-to-skill routing |
| `TOOL_PROVIDER` | `default` | `BuiltinToolProvider` | Tool construction for shell, SQL, memory, delegation, code execution, and bundled tools |
| `HOOK_PROVIDER` | `default` | `DefaultHookProvider` | HookRunner construction, kernel attach, background hook registration, model-call policy hooks |
| `TRACE_PROVIDER` | `default` | `DefaultTraceProvider` | Trace emitter resolution |

See `docs/PROVIDER_ARCHITECTURE.md` for provider contracts and partner adapter
examples.

Provider Protocols and the stable `Skill` descriptor are exported by the
dependency-free `agentos-contracts` SDK package under
`IAF-Agent-Skills/agentos_contracts/`. Existing
`iaf_agent_skills.providers.*` imports remain compatibility shims.

## Router Shortlist (taxonomy-narrowed skill catalogue)

The router asks one LLM to pick a skill from the whole catalogue. At ~183 skills,
several descriptions read almost identically and there is no "none of these"
option, so look-alike entries win on phrasing. When the L5 semantic taxonomy
signal is confident about a domain, the catalogue sent to the router is narrowed
to that domain first.

Narrowing is **category-wide**, not "just the hinted skills": the hints name
domain anchors (e.g. `fa_ap`), not the executable skill, so keeping only the hits
would discard the skill that should win. Recall inside the chosen domain is
preserved, the default skill is always kept, and the prompt states that it was
narrowed. If the shortlist would be smaller than `ROUTER_SHORTLIST_MIN_SKILLS`,
or would not meaningfully reduce the list, the full catalogue is used instead.

| Env Var | Default | Purpose |
|---|---|---|
| `ROUTER_SHORTLIST_ENABLED` | `true` | Set `false` to always send the full catalogue |
| `ROUTER_SHORTLIST_MIN_SCORE` | `0.90` | Minimum taxonomy score for a hint to define the domain |
| `ROUTER_SHORTLIST_MIN_SKILLS` | `8` | Floor below which narrowing is refused as too aggressive |

Implemented in `SkillRouter._shortlist_by_taxonomy` (`IAF-Agent-Skills/iaf_agent_skills/router.py`).
Look for `Router shortlist ACTIVE:` / `Router shortlist skipped` and the
`Pre-router taxonomy signal` lines in the server log to see what the router saw.

> The hints only reach the router because `TaxonomyRoutingCapability` now proxies
> the inner index's `_ready` Event. Previously `chat.py` probed `_ready` on the
> wrapper, which did not define it, so `getattr(..., None)` made the pre-router
> lookup dead in both the REST and WebSocket paths and every query routed with no
> semantic signal. Prefer `is_ready()` for new callers.

## Execution Mode Controls

| Env Var | Default | Purpose |
|---|---|---|
| `DYNAMIC_ORCHESTRATOR_ENABLED` | `true` | Enables automatic upgrade of router-classified `multi_step` ReAct requests to the dynamic Orchestrator. Set `false` to fall back to ReAct. Planned mode and explicitly declared skill modes are unchanged. |

The value is read at request execution time, but deployments using
`agent_os/config.env` should restart Studio after changing that file.

## Sample Tenant Entitlements

The sample company tenant policy lives at
`enterprise_root/tenants/company/security/policies.yaml`. It grants normal
authenticated demo users access to the default agent plus the bundled
`send_email` skill because finance workstreams render `send_email`
`skill_component` cards and allow users to discuss the generated communication.
Finance groups can also use the `policy_authoring` skill to draft approval or
governance policy YAML from natural language; saving and publishing those drafts
remain separate governed actions.

Authenticated demo users can also use the `finance_agents` agent and BP finance
skill pack via the `authenticated-users-can-use-finance-agents-pack` policy
(`agent:finance_agents`, `skill:*-agent`). Finance groups inherit the same
`skill:*-agent` wildcard for hyphenated finance agent skills.

Authenticated demo users can use tenant-owned Private Learning Loop assets via
`authenticated-users-can-use-private-evals` (`eval:*`) for read/write/use/test
actions. Managers additionally get `approve` on `eval:*` so the Workbench Eval
Builder can record manual promotion-gate decisions without granting deployment
or fine-tuning authority.

Authenticated demo users can use the advisory Trace Value Router via
`authenticated-users-can-use-trace-value-router` (`trace_value:*`,
`skill:trace_value_router`, and governed pending-review `knowledge:*` writes).
Destination-specific checks still apply for golden-set promotion and knowledge
review.

## Trace Value Router

The router is an opt-in LLM-backed sidecar for RL/eval capture. Manual API
backfill is available regardless of the background flag; automatic post-capture
assessment only runs when enabled.

| Env Var | Default | Purpose |
|---|---|---|
| `TRACE_VALUE_ROUTER_ENABLED` | `false` | When true, completed captured chat trajectories schedule asynchronous trace-value assessment. |
| `TRACE_VALUE_ROUTER_SKILL` | `trace_value_router` | Tenant skill used for semantic destination scoring. |
| `TRACE_VALUE_ROUTER_CONCURRENCY` | `1` | Max concurrent background/batch routing workers (semaphore-bound). |
| `TRACE_VALUE_ROUTER_BATCH_LIMIT` | `25` | Max trajectories processed by manual/reconciliation batches by default. |
| `TRACE_VALUE_ROUTER_RETRY_LIMIT` | `1` | Best-effort retry count for automatic background assessment. |
| `TRACE_VALUE_ROUTER_MAX_EVIDENCE_CHARS` | `12000` | Max redacted evidence-packet size sent to the judge skill. |

The router judge invokes `SkillAgent.run(..., light_mode=True)` with the **light**
model role (`AZURE_OPENAI_DEPLOYMENT_LIGHT`, defaulting to `gpt-5-nano` in this
deployment). `light_mode` only skips heavy memory/context loading; the explicit
light-model swap is what keeps routing off the primary deployment (`gpt-5.2-chat`).

## AgentOS Kernel Packaging & Self-Auth

`agent_os` is packaged as the installable distribution `agentos-kernel`. The
full Studio source-tree runtime still imports `agent_os` from the repository
root, but embedders can install the kernel independently.

`agent_os.self_auth` now reads JWT settings from environment variables instead
of importing Studio configuration:

| Env Var | Default / Source | Purpose |
|---|---|---|
| `JWT_SECRET` | Must be set for standalone self-auth; Studio exports its resolved value at boot | Signs service JWTs for agent self-calls |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `TENANT_ID` | `company` | Default tenant used when a principal omits tenant_id |
| `AGENT_ID` | `enterprise_agent` | Deployment's fallback agent id (personal-skills workspace, capture events) when none is supplied |
| `SERVER_LOG_PATH` | Falls back to `IAF-Agent-Studio/logs/server.log`, then `logs/server.log` | Server log location that self-evolution Tier 3b runtime-error enrichment reads |

AgentOS kernel execution can run locally inside the API/worker process or
through a signed kernel worker boundary. `AGENTOS_KERNEL_BACKEND=local`
preserves the historical `SafeKernel` behavior. `AGENTOS_KERNEL_BACKEND=remote`
sends `run_shell_command` and `write_file` calls to `IAF-Agent-Studio/kernel_worker.py`;
the worker owns the real `SafeKernel`, credential handles, Python subprocesses,
and kernel audit writes.

Start a local worker with:

```bash
cd "IAF-Agent-Studio" && AGENTOS_KERNEL_TOKEN_SECRET=<32+ chars> python3 kernel_worker.py
```

Remote mode requires the API and worker to share
`AGENTOS_KERNEL_TOKEN_SECRET`. In strict deployments, set
`AGENTOS_KERNEL_REQUIRE_REMOTE=true` to fail startup unless the remote backend is
selected.

## Model Package Boundary

`agentos-model` is the model package being extracted from `iaf_agent_skills`.
It owns provider-neutral reasoning metadata, `ModelRegistry`,
`ModelProviderAdapter`, and the Azure Responses, Vertex/Gemini, and Anthropic
chat adapters under `IAF-Agent-Skills/agentos_model/`. Existing
`iaf_agent_skills.model_*` and provider chat adapter imports remain
compatibility shims.

`agentos-engine` is available under `IAF-Agent-Skills/agentos_engine/` as a
facade over the historical `iaf_agent_skills` runtime. Use it for the target
composable import surface without changing full-product behavior.

## Eval-Based Model Routing

Private Learning Loop model recommendations are advisory by default. Runtime
model routing changes only when explicitly enabled:

| Env Var | Default | Purpose |
|---|---|---|
| `EVAL_ROUTER_ENABLED` | `false` | When true, `ModelProviderAdapter.get(role)` may redirect the requested model role through the eval router map. |
| `EVAL_ROUTER_ROLE_MAP` | _(empty)_ | JSON object mapping requested roles to selected roles, for example `{"primary":"fallback"}`. |
| `EVAL_ROUTER_ROLE_<ROLE>` | _(empty)_ | Direct per-role override, for example `EVAL_ROUTER_ROLE_PRIMARY=fallback`; this takes precedence over `EVAL_ROUTER_ROLE_MAP`. |

## Storage Backend

AgentPro persists runtime state (knowledge index, evidence, traces, queues,
auth, RL capture) in a relational store. The backend is selected by
configuration; the default is single-node SQLite and requires no extra
dependencies. See `docs/STORAGE_BACKENDS.md` for the full guide, migration
steps, and HA notes.

| Env Var | Default | Purpose |
|---|---|---|
| `STORAGE_MODE` | _(unset)_ | **Single umbrella knob.** When set (`postgres` or `sqlite`), it cascades a coherent backend to every store — `DB_BACKEND`, `KNOWLEDGE_BACKEND`, `EVIDENCE_BACKEND`, `TRACE_BACKEND`, `VECTOR_BACKEND`, `CC_QUEUE_STORAGE_BACKEND`, `QUEUE_BACKEND` — filling only the ones you did **not** set explicitly (per-store overrides still win). `postgres` implies `pgvector` + `redis` queue. Applied in `shared/config.py` after dotenv, before any backend var is read, so it works end-to-end. A startup validator rejects incoherent mixes (e.g. `pgvector` on a non-Postgres store). **Unset = byte-identical to before** (each var keeps its own default below). Resolved values are surfaced on `agentos_build_info` in `/metrics`. |
| `DB_BACKEND` | `sqlite` | Relational backend: `sqlite` (single-node/dev) or `postgres` (multi-node/HA). |
| `DATABASE_URL` | _(empty)_ | Postgres DSN (`postgresql://<user>@<host>:5432/<db>`; supply the credential via `PGPASSWORD` or `~/.pgpass`). **Required** when `DB_BACKEND=postgres`. |
| `DB_POOL_SIZE` | `10` | Max Postgres pool connections (used when `psycopg_pool` is installed). |
| `VECTOR_BACKEND` | `brute_force` | Vector similarity backend: `brute_force`, `sqlite_vec`, or `pgvector`. `pgvector` requires `DB_BACKEND=postgres`, the pgvector **extension** in Postgres, and the pgvector **python client** (`pip install pgvector`) — without the client `create_vector_backend` silently falls back to `brute_force`. **Per-agent isolation:** the shared `public.agentos_vectors` table is keyed by a namespaced collection (`kn_<tenant>_<agent>:knowledge|episodes`), so a single global flag keeps every agent's vectors separate. Flipping to `pgvector` reads the `agentos_vectors` table (not the `BYTEA` embeddings), so an agent's existing embeddings must be **backfilled** first or recall degrades. Rollback = unset (the `BYTEA` embeddings in the `kn_*` schemas stay authoritative and are still written on every upsert). |
| `VECTOR_DIMENSION` | `1536` | Embedding dimension. Must match the model producing embeddings (`text-embedding-ada-002` / `text-embedding-3-small` = 1536; `text-embedding-3-large` = 3072). |
| `PGVECTOR_IVF_LISTS` | `100` | IVFFlat cluster count for the pgvector ANN index. Rule of thumb: `sqrt(expected_row_count)`. Raise for larger datasets and recreate the index after changing. Only used when `VECTOR_BACKEND=pgvector`. |
| `KNOWLEDGE_BACKEND` | `sqlite` | Per-agent knowledge/episode/entity index backend. Independent of `DB_BACKEND` (the queue's flag): defaults to `sqlite` so the memory index stays on the per-agent file even when the queue is on Postgres. Set to `postgres` **per agent, after migrating that agent's `knowledge_index.db`** — the agent then uses a schema-per-agent (`kn_<tenant>_<agent>`) in the shared Postgres via the pooled engine. Also moves the same-file `conversation_sessions` and `taxonomy_signal_index` tables into that schema. Postgres requires `DATABASE_URL`. Rollback = set back to `sqlite` (the original `.db` is untouched and authoritative). |
| `MAINTENANCE_INTERVAL_SECONDS` | `86400` | Interval for the leader-gated maintenance loop (server lifespan) that runs transcript pruning + trace retention. First pass ~2 min after boot, then this interval. Fleet-safe via a Redis NX day-key (one instance per window). |
| `TRACE_RETENTION_DAYS` | `30` | Age after which the maintenance loop purges execution traces (calls `trace_emitter.purge_old_traces`). |
| `KNOWLEDGE_COMPACT_BLOAT_PCT` | `50` | The maintenance loop compacts an agent's append-only `knowledge.jsonl` (collapses superseded/duplicate lines, archives first) when its bloat ≥ this % **and** it has ≥200 lines. `0` disables. Compaction is on-demand-safe (also a dashboard button); this just schedules it so the file doesn't grow unbounded between manual runs. |
| `TRANSCRIPT_HOT_DAYS` | `0` (off) | Transcript tiering. `0` = off: chat history lives only as per-session `history/<date>/<id>.jsonl` files (current behavior, zero overhead). When `> 0`: every turn is also written to a `conversation_turns` table (in `ConversationManager`'s backend — the `kn_<tenant>_<agent>` PG schema when `KNOWLEDGE_BACKEND=postgres`), history JSONL files **older than N days** become eligible for pruning (via `tier_cold_files`, which only deletes a file whose turns are safely in the store), and `load_session_turns` falls back to the store for pruned/cold sessions. Recent files stay for `grep`/`cat`. Solves the millions-of-files growth at scale. |
| `TRACE_BACKEND` | `sqlite` | Execution-trace store (the observability/audit path `GET /api/audit` reads). `sqlite` = per-instance `traces.db`; `postgres` = shared `trace` schema (tables `traces`+`spans`, tenant-discriminated) in the `agentos` DB via the pooled engine — fleet-wide, queryable, no per-instance silo. Requires `DB_BACKEND=postgres`. Independent flag; rollback = unset (falls back to SQLite). |
| `TRACE_PG_SCHEMA` | `trace` | Postgres schema for traces when `TRACE_BACKEND=postgres` (override mainly for isolated tests). |
| `TRACE_DB_PATH` | _(derived)_ | **SQLite backend only.** Absolute path override for `traces.db`. Pin to **local** disk when `enterprise_root` is on a shared network mount — high-volume trace writes must not run on NFS/EFS. For fleet-wide traces use `TRACE_BACKEND=postgres` instead; cross-instance aggregation is otherwise via the OTLP telemetry provider. |
| `EVIDENCE_BACKEND` | `sqlite` | Evidence store backend. Independent of `DB_BACKEND`/`KNOWLEDGE_BACKEND`, default `sqlite` so the live path is unchanged. Set to `postgres` for **cross-instance** evidence sharing: the three evidence tables (`evidence_bundles`, `evidence_items`, `evidence_blobs`) move to a per-tenant schema (`ev_<tenant>`) on the shared pooled engine, selected per operation via `SET LOCAL search_path`. Requires `DB_BACKEND=postgres` + `DATABASE_URL`. Rollback = set back to `sqlite` (the per-tenant `evidence.db` is untouched). |
| `EVIDENCE_PG_SCHEMA` | `ev_<tenant>` | Override the derived per-tenant Postgres schema name for evidence (only when `EVIDENCE_BACKEND=postgres`). Mainly for tests / isolated schemas. |
| `EVIDENCE_DB_ROOT` | _(derived)_ | **SQLite backend only.** Absolute base-dir override for the per-tenant `evidence.db` (keeps the `tenants/<id>/shared/databases/` layout under this root). Pin to **local** disk when `enterprise_root` is on a shared mount; local pinning makes evidence per-instance. For true multi-instance sharing use `EVIDENCE_BACKEND=postgres` instead (then this path is unused). |

Notes:
- SQLite connections are opened WAL-mode with `busy_timeout=30000` and a 30s
  connect timeout everywhere (see `iaf_agent_skills/sqlite_util.py`), which
  eliminates the previous `database is locked` errors on the shared knowledge
  index under session/dashboard/indexer concurrency.
- The Postgres backend and `pgvector` are optional installs:
  `pip install 'psycopg[binary]' pgvector psycopg-pool`. The SQLite default path
  installs none of these.
- Config values are registered into the engine runtime bridge by
  `IAF-Agent-Studio/shared/config.py`, so the engine (`iaf_agent_skills`) never
  imports Studio to read them.

## Workstream Cron Reconciliation

No new environment variable is required. When Redis-backed cron scheduling is
available, Studio startup scans tenant Workstream YAML files for
`cron_schedule` and `cron_user_id`, creates or updates the matching `ws_<name>`
cron job, and writes the current `cron_job_id` back to YAML. If Redis is not
available, the existing scheduler startup warning still applies and core chat
continues without scheduled jobs.

Standalone (non-workstream) cron jobs are declared under
`enterprise_root/tenants/<tenant_id>/scheduler/jobs/*.yaml` and reconciled into
Redis on startup. See `docs/STANDALONE_CRON_JOBS.md`. Existing Redis-only
standalone jobs can be exported with
`python3 IAF-Agent-Studio/scripts/export_standalone_crons.py`.

## Tenant Runtime State Placement

By default, tenant runtime SQLite files that represent enterprise state live
under `enterprise_root/tenants/<tenant_id>/shared/databases/`:

| Env Var | Default | Purpose |
|---|---|---|
| `CC_QUEUE_DB_PATH` | `enterprise_root/tenants/<tenant_id>/shared/databases/command_center.db` | Override Command Center queue DB path. Relative paths resolve from `IAF-Agent-Studio/`. |
| `WORKSTREAM_RUNTIME_DB_PATH` | `enterprise_root/tenants/<tenant_id>/shared/databases/workstream_runtime.db` | Override durable workstream execution runtime DB path. Relative paths resolve from `IAF-Agent-Studio/`. |
| `AUTOMATION_RUNTIME_DB_PATH` | `enterprise_root/tenants/<tenant_id>/shared/databases/automation_runtime.db` | Override durable Deterministic Automation run/step trace DB path. Relative paths resolve from `IAF-Agent-Studio/`. |
| `EVAL_RUNTIME_DB_PATH` | `enterprise_root/tenants/<tenant_id>/shared/databases/eval_runtime.db` | Override Private Learning Loop eval run/case trace DB path for SQLite deployments. Relative paths resolve from `IAF-Agent-Studio/`; Postgres deployments use `DB_BACKEND=postgres`. |

On first startup after the path change, if a legacy DB exists in
`IAF-Agent-Studio/` and the tenant-root DB does not exist yet, Studio copies the
legacy file into the tenant-root location.

Existing SQLite Command Center databases are upgraded additively at startup
before lease-related indexes are created, so local deployments do not need
Postgres just to pick up new queue claim columns.

Deterministic Automation definitions are stored as YAML under
`enterprise_root/tenants/<tenant_id>/automations/*.yaml`. Python automation
steps run scripts from `/shared/scripts`, backed by
`enterprise_root/tenants/<tenant_id>/shared/scripts/`.

Private Learning Loop eval suites are stored as YAML under
`enterprise_root/tenants/<tenant_id>/evals/*.yaml`; golden sets are JSONL files
under `enterprise_root/tenants/<tenant_id>/golden_sets/*.jsonl`.

## Domain Dashboards

Domain-specific dashboards built as a solution module (see
[SOLUTION_MODULES.md](SOLUTION_MODULES.md)) read existing workstream runtime
data, trace telemetry, and HITL history, and require no additional
module-specific env var beyond what the module itself documents.

## Dedicated Enterprise P0 Profile

`agent_os/config.enterprise.env.example` is the production baseline for one
enterprise per deployment. Strict mode validates closed security defaults at
startup instead of allowing a partially secured process to serve traffic.

| Env Var | Development Default | Enterprise Requirement |
|---|---|---|
| `ENTERPRISE_STRICT_MODE` | `false` | `true`; validates the settings below |
| `STUDIO_RUNTIME_ROLES` | `all` | `api`, `scheduler`, or `queue` per process |
| `UVICORN_WORKERS` | `1` | API may use multiple workers; background roles must not be embedded |
| `USE_REDIS_SESSIONS` | `false` | Must be `true` for every strict `api` process |
| `QUEUE_WORKER_REPLICAS` | `1` | Values above `1` require `DB_BACKEND=postgres` and `CC_QUEUE_STORAGE_BACKEND=postgres` |
| `CC_QUEUE_STORAGE_BACKEND` | `sqlite` | Command Center claim backend; set to `postgres` only after migration and one-worker verification |
| `CC_QUEUE_DATABASE_URL` | empty | Optional queue-specific Postgres DSN; otherwise uses `DATABASE_URL` |
| `QUEUE_CLAIM_LEASE_SECONDS` | `360` | Queue claim lease duration, clamped to 30–3600 seconds |
| `QUEUE_CLAIM_RECLAIM_LIMIT` | `3` | Expired claim requeues before DLQ, clamped to 1–20 |
| `QUEUE_WORKER_HEARTBEAT_TTL_SECONDS` | `30` | Queue worker heartbeat freshness window, clamped to 10–300 seconds |
| `SCHEDULER_LEADER_LOCK_TTL_SECONDS` | `45` | Redis scheduler lease TTL, 15–300 seconds |
| `SCHEDULER_LEADER_RETRY_SECONDS` | `5` | Standby acquisition interval, 1–60 seconds |
| `DEMO_PUBLIC_SURFACES` | `true` | `false` |
| `QUEUE_INGEST_API_KEY` | empty | Secret of at least 32 characters |
| `FILE_URL_SIGNING_SECRET` | empty | Secret of at least 32 characters |
| `FILE_URL_TTL_SECONDS` | `300` | Signed URL lifetime, clamped to 30–3600 seconds |
| `ALLOW_UNSIGNED_FILE_URLS` | `true` outside strict mode | `false` |
| `CORS_ALLOWED_ORIGINS` | *(empty — deny)* | Comma-separated explicit enterprise UI origins; empty emits no CORS headers (same-origin UI needs none) |
| `JWT_SECRET` | per-process random if unset | **Must be explicitly set (≥32 chars).** In strict mode the server refuses to boot without it — an unset value uses a per-process random secret, so tokens minted by one replica fail on another (random 401s behind a load balancer) |
| `TENANT_RATE_LIMIT_PER_MINUTE` | `600` | Global per-tenant API rate limit: max requests/minute across **all** of a tenant's users, enforced in `AuthMiddleware` on authenticated requests and shared across instances via Redis (in-process fallback if Redis is down). Stops one tenant/customer from starving others; over-limit requests get **HTTP 429 + `Retry-After`**. Fail-open on limiter errors. `0` disables it. Tune per plan; only applies when `AUTH_ENABLED=true`. |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `60` | Per-IP request limit for auth endpoints (login/register). |
| `AUTH_LOGIN_RATE_LIMIT` | `10` | Stricter per-IP limit on login attempts (credential-stuffing guard). |
| `SESSION_IDLE_LOGOUT_MINUTES` | `60` | SEC-7 client-side idle timeout: minutes of inactivity before the browser force-logs-out. Served to the browser via `GET /auth/session-policy`, consumed by `static/session-controls.js` and `static/index.html`'s idle timer. Invalid pairs (warn not strictly less than logout) silently fall back to 60/55. |
| `SESSION_IDLE_WARN_MINUTES` | `55` | Minutes of inactivity before the idle-logout warning banner appears; must be less than `SESSION_IDLE_LOGOUT_MINUTES`. |
| `AGENTOS_UNTRUSTED_EXECUTION_GUARD` | `false` (**`true` in this repo's `config.env`**) | When `true` (untrusted multi-tenant / SaaS), forces agent-shell `python3` execution OFF regardless of `AGENT_PYTHON3_ENABLED`; also blocks bundled tool scripts for personal skills and local stdio MCP. Pure-Python commands (`ls`/`cat`/`grep`/…) unaffected |
| `AGENT_PYTHON3_ENABLED` | `false` (**`false` in this repo's `config.env`**) | Allow `python3` in agent shell commands. **Never enable without `AGENT_PYTHON3_SANDBOX_USER`** — model-generated code then runs as the server OS user with full filesystem access, and the AST denylist is bypassable (`from os import system`). See `docs/OPENSHELL_INTEGRATION_DESIGN.md` §1A |
| `AGENTOS_KERNEL_BACKEND` | `local` | `local` uses in-process `SafeKernel`; `remote` uses the signed kernel worker; `openshell` runs commands in an NVIDIA OpenShell sandbox (`agent_os/openshell_runtime.py`). **Fail-closed** — an unknown value raises rather than falling back to `local` |
| `AGENTOS_SANDBOX_URL` | empty | OpenShell gateway endpoint. Required when `AGENTOS_KERNEL_BACKEND=openshell`; empty ⇒ the backend refuses to execute (fail-closed) |
| `AGENTOS_SANDBOX_TOKEN` | empty | Bearer token for the OpenShell gateway (never logged; excluded from `health()`/`snapshot()`) |
| `AGENTOS_SANDBOX_WORKSPACE` | `default` | OpenShell workspace holding the sandbox |
| `AGENTOS_SANDBOX_ROOT` | `/workspace` | Sandbox-side root that virtual paths map onto |
| `AGENTOS_SANDBOX_TIMEOUT_SECONDS` | `120` | Per-exec timeout inside the sandbox |
| `AGENTOS_KERNEL_URL` | `http://127.0.0.1:18081` | Internal URL for the kernel worker when `AGENTOS_KERNEL_BACKEND=remote` |
| `AGENTOS_KERNEL_TOKEN_SECRET` | empty | HMAC secret shared by API/worker; at least 32 characters for remote mode |
| `AGENTOS_KERNEL_REQUIRE_REMOTE` | `false` | When `true`, strict mode rejects non-remote kernel execution |
| `AGENTOS_KERNEL_WORKER_BIND` | `127.0.0.1` | Bind address for `kernel_worker.py` |
| `AGENTOS_KERNEL_WORKER_PORT` | `18081` | Worker port, clamped to 1024–65535 |
| `AGENTOS_KERNEL_SESSION_TTL_SECONDS` | `1800` | Idle remote kernel cache TTL in the worker |
| `AGENTOS_KERNEL_FILE_CACHE` | `false` (off) | When truthy (`1`/`true`/`on`/`yes`), enables an in-process, per-kernel read-through cache for whole-file reads (`cat`/`grep`/`wc`/`semgrep`). Entries are validated against file `mtime` on every hit (never serves stale content) and invalidated on any write through the kernel (`write_file`/`echo>`/`semgrep` autofix). Intended to cut repeat reads of hot `.md`/profile files on higher-latency **shared/network filesystems** (EFS/Azure Files/NFS). Bounded (≤512 entries, ≤1 MB/file); `ls`/`find`/`head`/`tail` are **not** cached. Default off = byte-identical to pre-cache behavior. |
| `AGENT_PYTHON3_SANDBOX_USER` | empty | Required when Python is enabled in strict mode |
| `AGENT_PYTHON3_TIMEOUT` | `30` | Python subprocess wall/CPU bound |
| `AGENT_PYTHON3_MAX_MEMORY_MB` | `512` | Python subprocess address-space bound |
| `RECOVERY_VERIFICATION_ROOT` | empty | Separately restored data root available to the admin Recovery Readiness verifier; must not overlap `DATA_ROOT` |
| `RECOVERY_RUNTIME_RPO_TARGET_MINUTES` | `15` | Redis snapshot freshness target when capture metadata is present |
| `RECOVERY_RPO_TARGET_MINUTES` | `60` | Tenant backup freshness target shown and evaluated in recovery reports |
| `RECOVERY_RTO_TARGET_MINUTES` | `240` | Service recovery target evaluated when the backup manifest contains `restore_started_at` |
| `RECOVERY_LIVE_BASE_URL` | empty | Optional URL of a separately started isolated recovery cell for non-mutating HTTP probes |
| `RECOVERY_REDIS_URL` | empty | Dedicated recovery Redis DSN; its host/port must differ from `REDIS_URL` and is never returned in reports |
| `RECOVERY_LIVE_TOKEN` | empty | Secret-manager supplied bearer token used only for recovery-cell read probes |
| `RECOVERY_LIVE_CONFIRMATION` | empty | Must equal `isolated-recovery-cell` before live probes are allowed |
| `RECOVERY_LIVE_TIMEOUT_SECONDS` | `5` | Per-probe HTTP timeout, clamped to 1–30 seconds |
| `AGENTOS_SQL_STATEMENT_TIMEOUT_MS` | `5000` | Per-query Postgres `statement_timeout` (ms) applied by the `run_sql_query` gateway to Postgres-backed db resources — runaway-query guard |
| `AGENTOS_SQL_RO_ROLE` | `agentos_graph_ro` | Least-privilege Postgres role the gateway drops to (`SET LOCAL ROLE`) for `read_only` db resources (e.g. the world-model `graph`); it holds SELECT only on `entity_registry`/`process_relationships`, so an agent cannot read memory tables through the resource. Bootstrap once with `scripts/bootstrap_graph_ro_role.py` |
| `WORLD_MODEL_LEARN` | `false` | When truthy (`1`/`true`/`on`/`yes`), the per-turn reasoning LLM pass also extracts relationship triples and writes them as **`pending_review`** edges in the world-model graph (`process_relationships`). Pending edges are hidden from graph reads until promoted. Default off = no extra extraction, no writes, byte-identical behaviour |
| `WORLD_MODEL_MIN_CONFIDENCE` | `0.6` | Minimum triple confidence (0–1) for a per-turn edge to be written; below this the candidate is dropped (logged, never silently). Only consulted when `WORLD_MODEL_LEARN` is on |
| `WORLD_MODEL_AUTOCONFIRM_CONFIDENCE` | _(unset)_ | Auto-confirm knob. When set to a value `0–1`, a per-turn edge whose confidence is **at or above** it is written directly as **`confirmed`** (immediately visible to graph reads, skips human review) instead of `pending_review`. Unset (default) = OFF → every learned edge stays `pending_review` (the safe governance default; nothing reaches answers unvetted). Only consulted when `WORLD_MODEL_LEARN` is on. Set e.g. `0.95` to auto-trust only very-high-confidence edges |
| `HARNESS_PROFILE` | _(unset)_ | Process-level fallback harness execution profile (`fast-lookup`/`standard`/`high-assurance`/`autonomous`/`deep-research`). Lowest precedence — overridden by a per-request `profile`, a skill's `profile:` frontmatter, and the agent `config.yaml` `default_profile`. See [`HARNESS_PROFILES.md`](HARNESS_PROFILES.md) |
| `GRAPH_BACKEND` | `relational` | World-model graph backend seam. `relational` (default) = recursive-CTE reads over `process_relationships`. `age` = opt-in Apache AGE / openCypher — requires the AGE Postgres extension (infra); not yet implemented, so it logs a warning and falls back to `relational` |

`AUTH_ENABLED=true` is also mandatory in strict mode. Queue and signing secrets
must come from a secret manager. See `docs/ENTERPRISE_OPERATIONS_PROFILE.md` for
topology, policy rollout, sandbox provisioning, provisional SLO/RPO/RTO, and
rollback procedures.

Strict API startup connects and pings the shared Redis session store. It fails
closed when Redis is unavailable rather than silently creating replica-local
conversation or approval state. `/health/live` checks only the process;
`/health/ready` returns 503 when the API session dependency is unavailable.
Non-strict development may continue with the existing in-memory fallback.

When `RECOVERY_VERIFICATION_ROOT` is configured, Dashboard V2 exposes an
admin-only Recovery Readiness tab. The API accepts a configured root identifier,
not a client filesystem path, and refuses a root equal to, inside, or containing
the active `DATA_ROOT`. Reports are written under the live tenant's
`shared/databases/recovery_reports/` directory. Offline checks validate the
capture manifest, required tenant assets, structured files, and SQLite
integrity; live-cell checks remain `not_run` until they are executed against an
isolated running recovery cell.

If all live settings are present, the same Run action adds read-only liveness,
readiness, tenant-data, scheduler-status, queue-metrics, and signed-file probes.
The verifier rejects reuse of the production Redis host/port. Scheduler
leader uniqueness and queue exactly-once canary execution remain warnings until
the deployment drill submits sanitized evidence. The drill evidence API and
`scripts/verification/run_recovery_drill.py` use the same existing live settings;
no additional secret-bearing environment variable is required.

## App Version

The app version has a single source of truth: the repo-root `Version` file
(currently `1.0.0`). It is read at startup by `shared/config.py`
(`resolve_app_version()` → `APP_VERSION`) and served publicly at `GET
/auth/version`, which the login screen renders as `AgentOS v<version>` (header +
footer). Nothing is hardcoded; the path is anchored to the app root.

| Env Var | Default | Purpose |
|---|---|---|
| `APP_VERSION` | _(unset)_ | Optional override of the `Version` file for ephemeral/CI builds. When unset, the version is read from `<repo>/Version`. A missing or empty file falls back to `"dev"` (no crash). |

## Data Privacy — first-login notice + acknowledgement gate

PIA Data Privacy controls 1 (Transparency) & 3 (Declaration/Acknowledgement). A
first-login privacy notice + declaration gate that a user must accept before
access. Acceptance is persisted to the **existing** auth audit sink
(`auth/audit.py`, event `PRIVACY_ACK_ACCEPTED`). **Everything defaults OFF /
fail-open**, so the live login + SSO flow is byte-for-byte unchanged unless a
deployment explicitly opts in. The gate never blocks the endpoints needed to read
the notice, accept, inspect yourself (`/auth/me`), refresh, or log out, and
`PRIVACY_ACK_EXEMPT_ROLES` is an extra break-glass valve — admins are never
locked out.

To enable: set `PRIVACY_ACK_REQUIRED=true`. Edit the notice body at
`enterprise_root/tenants/<tenant>/config/privacy_notice.md` (or point
`PRIVACY_NOTICE_PATH` elsewhere) and bump `PRIVACY_NOTICE_VERSION` to re-prompt
everyone.

| Env Var | Default | Purpose |
|---|---|---|
| `PRIVACY_ACK_REQUIRED` | `false` | Master switch. `false` = middleware gate is a no-op and `/auth/privacy/*` report `required: false` (no behavior change). `true` = authenticated users must accept the current notice before `/api/*` calls succeed. |
| `PRIVACY_NOTICE_VERSION` | `1.0.0` | Version of the active notice. Bumping it re-prompts every user on next login even if they accepted a previous version. |
| `PRIVACY_NOTICE_TITLE` | `AgentOS-V1.0.0 — Data Privacy Notice & Declaration` | Title shown at the top of the acknowledgement modal. |
| `PRIVACY_NOTICE_PATH` | _(empty)_ | Notice/declaration body path. Empty resolves the tenant default `tenants/<tenant>/config/privacy_notice.md`. A relative path resolves against the tenant config dir; absolute is used as-is (anchored to `DATA_ROOT`, never a raw env value into `open()`). |
| `PRIVACY_ACK_EXEMPT_ROLES` | _(empty)_ | Comma-separated roles never blocked by the gate (break-glass safety valve). |

**Frontend coverage.** Two client surfaces surface the same server-driven gate:

- `login.html` runs the gate during the post-login redirect (`gateThenRedirect`),
  covering password + SSO logins and the "Already logged in?" fast-path.
- `static/privacy-gate.js` is a shared, dependency-free **app-shell gate**
  included at the end of `<body>` on the authenticated shells (`index.html`,
  `dashboard_v2.html`, `skill-builder-v2.html`, `twin.html`, `finops.html`,
  `rl_capture.html`). It covers users who reach the app **without** going through
  login.html — e.g. a deep-link, bookmark, or refresh straight into the app root
  or any authed page — who would otherwise get opaque `403
  {"detail":"PRIVACY_ACK_REQUIRED"}` from `/api/*` with no way to accept. On load
  it reads `iaf_access_token`; if present it calls `GET /auth/privacy/status`
  (base-path aware via `window.__BASE_PATH__`) and renders a blocking overlay
  **only** on `{required:true, accepted:false}`. It is fail-open (any error,
  `required:false`, or `accepted:true` → no-op) and OFF by default: the overlay
  can only appear when `PRIVACY_ACK_REQUIRED=true` server-side, so with the flag
  off there is no behavior change.
