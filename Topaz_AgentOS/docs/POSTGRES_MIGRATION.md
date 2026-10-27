# Migrating AgentPro from SQLite to PostgreSQL

A practical, step-by-step runbook for moving a deployment from the default
SQLite backend to PostgreSQL. Follow it top to bottom; each step is safe to stop
and resume.

> **Do you actually need this?** SQLite is fine for single-node deployments,
> dev, and demos. Move to Postgres only when you need **multiple app
> processes/nodes**, **HA/failover**, or **high write concurrency**. If you just
> hit occasional `database is locked` errors on one node, the Phase 0 hardening
> (WAL + `busy_timeout`) already fixes that on SQLite — see
> [STORAGE_BACKENDS.md](STORAGE_BACKENDS.md).

---

## 0. Key idea: what is authoritative vs derived

| Data | Authoritative source | Migrate how |
|---|---|---|
| Knowledge / episodes (`knowledge_index.db`) | **JSONL** (`context_graph/knowledge.jsonl`, `history/*.jsonl`) | **Rebuild** with `reindex_knowledge.py` — do **not** copy the .db |
| Evidence, traces, auth audit, RL capture, twin telemetry | The `.db` files themselves | **Copy** with `migrate_sqlite_to_postgres.py` |
| Business data DBs (invoices, AP/AR, etc.) | The `.db` files themselves | Separate decision — usually keep as-is or migrate independently |
| Cron / queue state | **Redis** | Not part of DB migration (see [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) → *Workstream Cron Reconciliation*) |

Because the knowledge index is derived, you never risk losing knowledge during
migration — worst case you rebuild it from JSONL.

---

## 1. Provision PostgreSQL + pgvector

Requires **PostgreSQL 14+** with the `pgvector` extension available.

> **Credentials never go inline in a URL.** Every DSN in this guide has the form
> `postgresql://agentpro@<host>:5432/agentpro` (user, no credential). Before
> running the commands below, load the DB credential from your credential
> manager into the standard libpq environment variable `PGPASSWORD` (or use a
> `~/.pgpass` file). `psql` and psycopg (which the engine uses) read it
> automatically. In deployed environments you may instead inject the complete
> `DATABASE_URL` from the credential manager; never commit it to a file.

```bash
# Example: local Postgres via Docker (DB credential taken from $PGPASSWORD)
docker run -d --name agentpro-pg \
  -e POSTGRES_USER=agentpro \
  -e POSTGRES_PASSWORD="$PGPASSWORD" \
  -e POSTGRES_DB=agentpro \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

Confirm the extension can be created:

```bash
psql "postgresql://agentpro@localhost:5432/agentpro" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## 2. Install the Postgres client libraries

These are **optional installs** — the default SQLite path needs none of them.

```bash
pip install 'psycopg[binary]>=3.1' pgvector>=0.2.5 psycopg-pool>=3.2
```

Use the same Python you run the server with (system Python 3.13 per
`server-runtime` rules — **not** the venv).

---

## 3. Stop the server (quiesce writers)

```bash
for pid in $(lsof -ti tcp:8081 2>/dev/null); do kill "$pid"; done
```

Stopping writers guarantees a consistent copy in step 4.

---

## 4. Copy the runtime stores into Postgres

Set the DSN once (the credential comes from `PGPASSWORD` / `~/.pgpass`, see step 1):

```bash
export DATABASE_URL="postgresql://agentpro@localhost:5432/agentpro"
```

For **each runtime `.db`**, first inspect the plan with `--dry-run`, then run it
for real. FTS/virtual tables and the vector index are skipped automatically
(rebuilt in step 6).

```bash
cd IAF_AgentOS_Harness_latest
BASE=enterprise_root/tenants/company

# Evidence store
python3 onboarding/setup/migrate_sqlite_to_postgres.py \
  --sqlite "$BASE/shared/databases/evidence.db" --postgres "$DATABASE_URL" --dry-run
python3 onboarding/setup/migrate_sqlite_to_postgres.py \
  --sqlite "$BASE/shared/databases/evidence.db" --postgres "$DATABASE_URL"

# Traces
python3 onboarding/setup/migrate_sqlite_to_postgres.py \
  --sqlite "$BASE/shared/databases/traces.db" --postgres "$DATABASE_URL"

# Auth audit
python3 onboarding/setup/migrate_sqlite_to_postgres.py \
  --sqlite "$BASE/config/auth_audit.db" --postgres "$DATABASE_URL"

# Digital twin telemetry
python3 onboarding/setup/migrate_sqlite_to_postgres.py \
  --sqlite "$BASE/shared/databases/twin_telemetry.db" --postgres "$DATABASE_URL"

# RL capture (if you use it — pick the DB your deployment points at)
python3 onboarding/setup/migrate_sqlite_to_postgres.py \
  --sqlite "$BASE/shared/databases/rl.db" --postgres "$DATABASE_URL"
```

> **Do NOT** run the migration on `knowledge_index.db` — it is rebuilt in step 6.
> **Business data DBs** (`invoices_*.db`, `ap_ops.db`, `ar_receivables.db`, …)
> are the agent's external SQL sources, not platform state. Migrate those only if
> your data strategy calls for it, and treat them independently.

Useful flags: `--only table1,table2`, `--skip tableX`, `--batch 1000`.

---

## 5. Point the app at Postgres

Set these in your environment / process manager:

```bash
export DB_BACKEND=postgres
export DATABASE_URL="postgresql://agentpro@localhost:5432/agentpro"
export DB_POOL_SIZE=10
export VECTOR_BACKEND=pgvector
```

The engine reads these through the runtime bridge (registered by
`IAF-Agent-Studio/shared/config.py`), so no code changes are needed. The server
process also needs the DB credential: have the process manager inject
`PGPASSWORD` (or a `~/.pgpass` / `PGPASSFILE`) from the credential manager, or
inject the complete `DATABASE_URL` there instead of the credential-free form above.

---

## 6. Rebuild the knowledge/vector index from JSONL

This populates the pgvector table and keyword search with fresh embeddings.

```bash
python3 onboarding/setup/reindex_knowledge.py \
  --memory-root "$BASE/agents/enterprise_agent/memory" \
  --with-embeddings
```

Notes:
- `--with-embeddings` needs your model provider + credentials configured in the
  environment. Without it, structure + keyword search rebuild, but semantic
  search stays empty until an embedding-backed reindex runs.
- Repeat per agent if you run more than one agent memory root.

---

## 7. Start the server and verify

```bash
cd IAF-Agent-Studio && DB_BACKEND=postgres DATABASE_URL="$DATABASE_URL" \
  VECTOR_BACKEND=pgvector PORT=8081 python3 server.py
```

Verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8081/docs        # 200
psql "$DATABASE_URL" -c "SELECT count(*) FROM agentos_vectors;"            # > 0 after reindex
psql "$DATABASE_URL" -c "\dt"                                              # migrated tables present
```

In the app: run a chat that retrieves knowledge, open the evidence/traces
dashboards, and confirm data shows up.

---

## 8. Rollback

Rollback is trivial because SQLite files are untouched by this process:

```bash
unset DB_BACKEND DATABASE_URL VECTOR_BACKEND   # or set DB_BACKEND=sqlite
# restart the server
```

Keep the SQLite files until you've validated Postgres in production for a while.

---

## Tenant isolation on Postgres

SQLite isolates tenants by file path. Postgres uses a **shared schema** with
`tenant_id` / `agent_id` columns. Enforce isolation with query filters and,
optionally, PostgreSQL **Row-Level Security**:

```sql
ALTER TABLE evidence_bundles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON evidence_bundles
  USING (tenant_id = current_setting('app.tenant_id', true));
-- the app sets: SET app.tenant_id = '<tenant>' per request/connection
```

---

## Backup & HA (after migration)

- Use standard Postgres tooling: `pg_dump`, streaming replication, or managed
  snapshots.
- The app connects through `DATABASE_URL`, so a failover behind a virtual IP or
  PgBouncer is transparent — no app change needed.
- You can still rebuild the knowledge index from JSONL at any time, independent
  of Postgres backups.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `psycopg is required` | Run step 2 with the same Python as the server |
| `DB_BACKEND=postgres requires DATABASE_URL` | Export `DATABASE_URL` before starting |
| `extension "vector" is not available` | Use a Postgres image/build with pgvector; run `CREATE EXTENSION vector` |
| Semantic search empty after cutover | Re-run step 6 **with** `--with-embeddings` and valid model credentials |
| Falls back to `BruteForceBackend` in logs | `VECTOR_BACKEND=pgvector` requires `DB_BACKEND=postgres` **and** pgvector installed |

See also: [STORAGE_BACKENDS.md](STORAGE_BACKENDS.md) (architecture) and
[CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) (all env vars).
