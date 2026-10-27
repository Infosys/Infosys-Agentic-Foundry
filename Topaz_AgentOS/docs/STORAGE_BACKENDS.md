# Storage Backends

AgentPro stores runtime state in a relational database behind a small storage
abstraction so the same code runs on either:

| Backend | When to use | Extra installs |
|---|---|---|
| **SQLite** (default) | Single-node deployments, development, demos | None (Python stdlib) |
| **PostgreSQL** | Multi-node / HA / high-concurrency enterprise deployments | `pip install 'psycopg[binary]' pgvector psycopg-pool` |

The **authoritative** data always lives in JSONL / config files
(`context_graph/knowledge.jsonl`, `history/*.jsonl`, skills, contexts, policies,
workstreams, and standalone cron YAML). Runtime SQLite files that represent
tenant state live under `enterprise_root/tenants/<tenant_id>/shared/databases/`.
The knowledge database is a *derived, rebuildable* index/cache. This is what
makes backend migration and disaster recovery safe: you can delete the DB and
rebuild it from JSONL at any time.

## Why this exists

The knowledge index (`knowledge_index.db`) is opened by many actors at once —
per-session agent clones, the taxonomy indexer, the entity-guide seeder, and
read-only dashboard/chat pollers. Historically several of those openers used
bare `sqlite3.connect()` with no `busy_timeout`, so concurrent writes surfaced
as `sqlite3.OperationalError: database is locked`, and a crash mid-reindex could
leave the index empty (the old reindex deleted every row *before* rebuilding).

Two layers of fixes address this:

### 1. SQLite hardening (applies to the default backend)

- All SQLite openers now go through `iaf_agent_skills/sqlite_util.connect()`,
  which sets `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`
  (30s) and a 30s connect timeout. WAL allows concurrent readers with a single
  writer; `busy_timeout` makes a competing writer wait instead of erroring.
- `KnowledgeIndexer.reindex_all()` / `reindex_episodes()` are **non-destructive**:
  they upsert every current record in place and delete only records that no
  longer exist in the JSONL. The index stays continuously queryable during a
  reindex, and an interrupted reindex never empties it.

### 2. Pluggable Postgres backend (for horizontal scale)

For deployments that outgrow a single node, `DB_BACKEND=postgres` routes the
same code to PostgreSQL, whose MVCC model supports many concurrent
readers/writers across processes and nodes. Vector search uses the `pgvector`
extension (`PgVectorBackend`).

**Connection pooling for the fleet (PgBouncer).** Each app process has an in-process
`psycopg_pool` (`DB_POOL_SIZE`, default 10). Those pools *sum* across processes/servers and
would exceed Postgres `max_connections` at fleet scale, so a **PgBouncer** proxy in
**transaction** mode sits in front of Postgres and caps total real server connections. Point
`DATABASE_URL` at PgBouncer's port (6432) instead of 5432. A ready config lives at
`agent_os/pgbouncer/pgbouncer.ini` (+ `userlist.txt.example`). Requires PgBouncer ≥ 1.21
(`max_prepared_statements`, since psycopg3 auto-prepares). This codebase is transaction-pooling
safe: no `LISTEN/NOTIFY`, no PG advisory locks (Redis leases), no server-side named cursors, and
all schema selection is `SET LOCAL search_path` (transaction-scoped).

**`pgvector` per-agent isolation + cutover.** `VECTOR_BACKEND=pgvector` needs (a) the
pgvector *extension* in Postgres and (b) the pgvector *python client* (`pip install
pgvector`) — without the client the factory silently falls back to `brute_force`.
Because `VECTOR_BACKEND` is a single global flag but embeddings for all agents share one
`public.agentos_vectors` table, `PgVectorBackend` scopes every row by `tenant_id` /
`agent_id` columns (read from the `TENANT_ID` / `AGENT_ID` env vars), with a primary key of
`(collection, record_id, tenant_id)` and every read/write filtered by `tenant_id`. This
isolates tenants by the `tenant_id` column — without it, one tenant's search would return
other tenants' records (a tenant breach) and could collide on the primary key. Cutover per agent = **backfill** the existing `BYTEA` embeddings
(`knowledge_vectors`/`episode_vectors` in the `kn_*` schema) into `agentos_vectors`, then set
the flag and restart; the `BYTEA` columns keep being written, so rollback = unset the flag.
Isolation is guarded by `IAF-Agent-Skills/tests/test_pgvector_namespace_isolation.py`.

## Configuration

| Env Var | Default | Purpose |
|---|---|---|
| `DB_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `DATABASE_URL` | _(empty)_ | Postgres DSN; required for `postgres` |
| `DB_POOL_SIZE` | `10` | Max pooled Postgres connections |
| `VECTOR_BACKEND` | `brute_force` | `brute_force` \| `sqlite_vec` \| `pgvector` |
| `CC_QUEUE_DB_PATH` | tenant-root `shared/databases/command_center.db` | Override Command Center queue DB path |
| `CC_QUEUE_STORAGE_BACKEND` | `sqlite` | Command Center claim backend: `sqlite` or `postgres` |
| `CC_QUEUE_DATABASE_URL` | empty | Optional Command Center Postgres DSN; falls back to `DATABASE_URL` |
| `QUEUE_CLAIM_LEASE_SECONDS` | `360` | Queue claim lease duration for transactional workers |
| `QUEUE_CLAIM_RECLAIM_LIMIT` | `3` | Expired claim requeues before DLQ |
| `QUEUE_WORKER_HEARTBEAT_TTL_SECONDS` | `30` | Freshness window for queue worker registry metrics |
| `AGENTOS_KERNEL_BACKEND` | `local` | Execution backend for shell/file/Python tools: `local` SafeKernel or signed `remote` kernel worker |
| `AGENTOS_KERNEL_URL` | `http://127.0.0.1:18081` | Remote kernel worker URL when `AGENTOS_KERNEL_BACKEND=remote` |
| `WORKSTREAM_RUNTIME_DB_PATH` | tenant-root `shared/databases/workstream_runtime.db` | Override workstream runtime DB path |
| `AUTOMATION_RUNTIME_DB_PATH` | tenant-root `shared/databases/automation_runtime.db` | Override Deterministic Automation run/step trace DB path |
| `EVAL_RUNTIME_DB_PATH` | tenant-root `shared/databases/eval_runtime.db` | Reserved path name for Private Learning Loop eval run/case/gate traces on SQLite; Postgres uses `DB_BACKEND=postgres` |
| `RL_DB_PATH` | tenant-root `shared/databases/rl.db` | Override RL/eval capture DB path. Stores trajectories, rewards, evaluator results, exports, Trace Value assessments, and route-decision audit rows. |

`RLStore.list_trajectories_with_trace_filters()` is the read-model query used by
the Workbench. It joins trajectories to the latest Trace Value assessment and a
matching route decision, supports assessment/destination/score/status filtering,
and uses SQLite JSON extraction for optional per-destination score thresholds.
This keeps filtering in the store rather than issuing per-row lookups in the API
router; it requires no schema migration.

Example (Postgres):

```bash
export DB_BACKEND=postgres
export DATABASE_URL="postgresql://agentpro@db.internal:5432/agentpro"
export VECTOR_BACKEND=pgvector
pip install 'psycopg[binary]' pgvector psycopg-pool
```

The DSN carries no inline credential. psycopg/libpq reads the DB credential from
`PGPASSWORD` or `~/.pgpass` (injected by your credential manager), or inject the
complete `DATABASE_URL` from the credential manager at deploy time. See
[POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md).

## Architecture

```
agentos_contracts/storage.py     Protocols: StorageEngine, KnowledgeStore
iaf_agent_skills/sqlite_util.py  Hardened sqlite3.connect() (WAL + busy_timeout)
iaf_agent_skills/storage/        StorageEngine factory + SqliteEngine / PostgresEngine
iaf_agent_skills/vector_backend  BruteForce / SqliteVec / PgVector backends
```

- The engine never imports the host. Backend config is read via the runtime
  bridge (`get_provider_setting`) with an environment-variable fallback, so both
  the full Studio and standalone engine embedders work.
- `get_engine(db_path)` returns a per-file `SqliteEngine` for SQLite, or a single
  pooled `PostgresEngine` for Postgres (tenant isolation is by column, not file).
- Private Learning Loop eval run/case persistence uses
  `rl_capture/store/eval_store.py` with an injected `StorageEngine`, so it uses
  the tenant `eval_runtime.db` file on SQLite and the shared pooled connection on
  Postgres.

## Migrating SQLite → PostgreSQL

> Full step-by-step runbook: **[POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md)**.
> The summary below is the short version.

1. **Provision** PostgreSQL 14+ with the `pgvector` extension available, and
   install the client libs: `pip install 'psycopg[binary]' pgvector psycopg-pool`.
2. **Copy authoritative rows** from each SQLite file (evidence, traces, auth,
   workstream runtime, automation runtime, etc.). FTS5 and vector tables are
   skipped — they are rebuilt in step 4. For the Command Center queue, use the
   queue-specific migration helper so the Postgres claim schema is initialized
   with lease/fencing columns before rows are copied:

   ```bash
   python3 onboarding/setup/migrate_sqlite_to_postgres.py \
       --sqlite enterprise_root/tenants/company/shared/databases/evidence.db \
       --postgres "$DATABASE_URL" --dry-run     # inspect the plan first
   python3 onboarding/setup/migrate_sqlite_to_postgres.py \
       --sqlite enterprise_root/tenants/company/shared/databases/evidence.db \
       --postgres "$DATABASE_URL"
   python3 IAF-Agent-Studio/scripts/migrate_command_center_to_postgres.py \
       --sqlite enterprise_root/tenants/company/shared/databases/command_center.db \
       --postgres "$DATABASE_URL" --dry-run
   ```

3. **Point the app** at Postgres (`DB_BACKEND=postgres`, `DATABASE_URL=...`,
   `VECTOR_BACKEND=pgvector`). Set `CC_QUEUE_STORAGE_BACKEND=postgres` only
   after queue rows have been copied and one Postgres queue worker has passed
   verification.
4. **Rebuild the derived vector/keyword index from JSONL** so embeddings and
   full-text search are populated fresh:

   ```bash
   python3 onboarding/setup/reindex_knowledge.py \
       --memory-root enterprise_root/tenants/company/agents/enterprise_agent/memory \
       --with-embeddings
   ```

## Disaster recovery / corrupted index

Because the index is derived, recovery is: stop writers → delete the affected
`knowledge_index.db` (or truncate the Postgres vector table) → run
`reindex_knowledge.py`. No data is lost because the JSONL is authoritative.

For full-tenant recovery evidence, create
`.agentpro-recovery-manifest.json` in the completed backup and verify the
restored tree with
`scripts/verification/verify_enterprise_restore.py`. The verifier treats every
SQLite file as read-only, runs `PRAGMA quick_check`, compares capture-time table
inventories, validates authoritative YAML/JSON/JSONL, optionally verifies Redis
snapshot checksum/freshness, and compares checksums. The configured dashboard workflow
stores reports in the active tenant's
`shared/databases/recovery_reports/`; the restored root itself is never used as
the report store. Live drill evidence collected by
`scripts/verification/run_recovery_drill.py` is sanitized and stored beside
those reports under the same active tenant report area, not inside the restored
backup tree.

## Backup & HA

- **SQLite**: back up the whole `enterprise_root` tree (JSONL + `.db` files) with
  the server stopped, or copy WAL-checkpointed files. For recovery, JSONL is
  sufficient to rebuild the index.
- **PostgreSQL**: use standard Postgres backup/HA (streaming replication,
  `pg_dump`, managed-service snapshots). The pooled engine reconnects through the
  DSN, so a failover behind a virtual IP / PgBouncer is transparent to the app.

## Tenant isolation

SQLite isolates tenants/agents by file path
(`tenants/<tenant>/agents/<agent>/memory/...`). Postgres uses a shared schema
with `tenant_id` / `agent_id` columns; enforce isolation with query filters and,
optionally, PostgreSQL Row-Level Security policies keyed on a per-request
`SET app.tenant_id`.

## Cron and Queue Placement

- Workstream definitions and workstream crons live in
  `enterprise_root/tenants/<tenant_id>/workstreams/*.yaml`.
- Standalone (non-workstream) crons live in
  `enterprise_root/tenants/<tenant_id>/scheduler/jobs/*.yaml`; Redis is only the
  active scheduler runtime. See `STANDALONE_CRON_JOBS.md`.
- Command Center queue state lives in
  `enterprise_root/tenants/<tenant_id>/shared/databases/command_center.db` on
  SQLite. With `CC_QUEUE_STORAGE_BACKEND=postgres`, queue item claims, leases,
  worker heartbeats, DLQ, execution rows, and routing logs live in Postgres.
  The SQLite backend applies additive startup migrations before creating
  lease-related indexes so existing local queue databases can be opened after
  claim lease fields are added.
- Workstream execution runtime state lives in
  `enterprise_root/tenants/<tenant_id>/shared/databases/workstream_runtime.db`.

## Knowledge index on Postgres (`KNOWLEDGE_BACKEND`)

The per-agent knowledge index (`knowledge_index.db` — `knowledge_vectors`,
`episode_vectors`, `entity_registry`, `entity_xref`, `process_relationships`,
`plan_cache`, `routing_signal_log`) can run on Postgres, gated by its **own**
`KNOWLEDGE_BACKEND` flag (default `sqlite`), independent of the queue's `DB_BACKEND`.
This lets the Command Center run on Postgres while an agent's memory index stays on
SQLite until it is individually migrated and flipped.

- **Isolation model:** schema-per-agent (`kn_<tenant>_<agent>`), selected per operation
  via `SET LOCAL search_path` on the shared pooled engine. Existing queries stay
  unqualified — lowest parity risk.
- **FTS:** the SQLite FTS5 virtual tables become generated `tsvector` columns (`search_tsv`
  from an app-filled `fts_text` feeder, `entities_tsv` from `entities_text`) + GIN indexes.
  Reads use `@@ to_tsquery/websearch_to_tsquery` + `ts_rank_cd`; the AND/OR sanitizer bridges
  to tsquery `&`/`|`. The old delete-then-insert FTS sync does not run on Postgres.
- **Embeddings:** stay `struct.pack` float32 in `BYTEA` + Python brute-force cosine
  (`BruteForceBackend`, hydrated via the engine seam). `pgvector` is the future upgrade
  (`VECTOR_BACKEND=pgvector`), not required for parity.
- **Dialect:** `INSERT OR REPLACE/IGNORE`→`ON CONFLICT`, `AUTOINCREMENT`→`GENERATED ALWAYS AS
  IDENTITY`, `datetime('now',…)`→ISO cutoff params, `GROUP_CONCAT`→`string_agg`,
  `strftime('%Y-%m',…)`→`substr(ts,1,7)`, bytea `memoryview` wrapped in `bytes()`.
- **Consumers:** external callers reach the index only through the public seam
  (`indexer.connect()`, `indexer.placeholder`, `indexer.backend`) and accessors
  (`expand_by_entities`, `entity_lookup`, `get_episode_reasoning_row`, `get_tree`, …) — no
  raw `._db` access. The knowledge dashboard router, chat reasoning poll, agent entity-context,
  `query_memory`, and the entity-guide seeder are all backend-agnostic.
- **Cutover / rollback:** migrate one agent's data, then set `KNOWLEDGE_BACKEND=postgres`.
  Rollback = set back to `sqlite`; the original `.db` is never modified, so it stays
  authoritative. The Postgres pool is drained on server shutdown via `storage.close_engines()`.
  **Full fleet/shared-storage cutover steps + multi-instance acceptance test:** see
  `docs/SHARED_STORAGE_CUTOVER_RUNBOOK.md`.
- **Parity gate:** `IAF-Agent-Skills/tests/test_knowledge_index_parity.py` runs the same
  corpus + assertions on both backends (the Postgres run auto-skips when no `DATABASE_URL`
  is reachable).
- **Deferred:** `taxonomy_signal_index` (a rebuildable routing cache with an in-memory query
  path) still uses a local SQLite file on Postgres agents and degrades gracefully; converting
  it for full multi-process sharing is a follow-up.

## Evidence store on Postgres (`EVIDENCE_BACKEND`)

The evidence store (`evidence_bundles`, `evidence_items`, `evidence_blobs` — normalized
evidence bundles for chat/REST/cron/queue runs) can run on Postgres, gated by its **own**
`EVIDENCE_BACKEND` flag (default `sqlite`), independent of `DB_BACKEND`/`KNOWLEDGE_BACKEND`.
On SQLite it stays a per-tenant `evidence.db`, which is per-instance; on Postgres every app
instance reads/writes the same evidence.

- **Isolation model:** schema-per-**tenant** (`ev_<tenant>`), selected per operation via
  `SET LOCAL search_path` on the shared pooled engine. This is deliberately distinct from the
  per-**agent** knowledge schema (`kn_<tenant>_<agent>`) — evidence is a tenant-level artifact.
  Reads/writes stay unqualified, so the SQLite path is byte-identical.
- **Dialect / types:** `BLOB`→`BYTEA` (blob reads wrapped in `bytes()` for psycopg `memoryview`);
  placeholders `?`→`%s`; `ON CONFLICT(trace_id) DO UPDATE` is used unchanged on both backends;
  dict-row cursors (`sqlite3.Row` / psycopg `dict_row`) so `row["col"]` works everywhere.
- **FK ordering:** Postgres enforces the `evidence_blobs → evidence_items → evidence_bundles`
  foreign keys, so `store_bundle` deletes children (blobs) before parents (items) — the
  parent-first order the (FK-off) SQLite path tolerated. Whole write is one transaction under
  the scoped `search_path` (single commit; no mid-transaction commit that would reset it).
- **Consumers:** all callers go through the public API (`EvidenceStore(tenant_id)` +
  `store_bundle`/`get_bundle`/`get_item`/`get_blob`, the module wrappers, and the host
  `EvidenceSink`). No consumer reaches into the connection or tables, so nothing else changed.
- **Cutover / rollback:** set `EVIDENCE_BACKEND=postgres` (needs `DB_BACKEND=postgres` +
  `DATABASE_URL`); rollback = set back to `sqlite`. The Postgres pool is the same shared pool
  drained on shutdown via `storage.close_engines()`.
- **Parity gate:** `IAF-Agent-Studio/tests/test_evidence_backend_parity.py` runs the same
  corpus + assertions on both backends (Postgres run auto-skips without a reachable
  `DATABASE_URL`; each run uses an isolated schema dropped on teardown).

## Scope & status

- **Shipped and tested (SQLite path):** connection hardening across all openers,
  non-destructive reindex, storage engine + contracts, config wiring, migration
  and reindex scripts, `PgVectorBackend` implementation, unit + concurrency tests.
- **Knowledge index on Postgres (`KNOWLEDGE_BACKEND=postgres`):** implemented across the
  indexer, entity registry, vector-backend hydration, and all external consumers, with a
  parametrized SQLite↔Postgres parity gate (`tests/test_knowledge_index_parity.py`). Guarded
  by the default-`sqlite` flag so the SQLite default is untouched until a per-agent cutover.
- **Evidence store on Postgres (`EVIDENCE_BACKEND=postgres`):** implemented as a per-tenant
  schema (`ev_<tenant>`) via the shared engine seam, with a SQLite↔Postgres parity gate
  (`IAF-Agent-Studio/tests/test_evidence_backend_parity.py`). Default `sqlite`, so the
  per-tenant `evidence.db` path is unchanged until an operator flips the flag.
- **Requires a live Postgres to exercise end-to-end:** the queue `postgres` backend and
  `pgvector` search. Their code paths are complete and guarded by lazy imports so
  the SQLite default is never affected.
- **Redis remains runtime infrastructure:** active scheduler due indexes, locks,
  and run history stay in Redis, but workstream cron definitions and standalone
  cron definitions are now rebuildable from `enterprise_root` YAML.
- **Kernel backend is execution, not storage:** `AGENTOS_KERNEL_BACKEND=remote`
  moves `SafeKernel` shell/file/Python execution to `kernel_worker.py`, but
  tenant state still lives in the configured filesystem, SQLite/Postgres, and
  Redis stores above.

For the P0 enterprise topology, Redis also owns the scheduler leader lease.
SQLite remains the default authoritative Command Center claim backend, so
startup rejects `QUEUE_WORKER_REPLICAS>1` unless both `DB_BACKEND=postgres` and
`CC_QUEUE_STORAGE_BACKEND=postgres` are set. Redis queue transport does not make
multiple SQLite claimers safe.
