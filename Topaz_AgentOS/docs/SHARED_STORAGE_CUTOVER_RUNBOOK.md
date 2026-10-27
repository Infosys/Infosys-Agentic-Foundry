# Shared-Storage + Multi-Instance Cutover Runbook

**Goal:** run IAF AgentOS across a fleet of servers (horizontal scale toward 100K users) by
putting the `enterprise_root` file tree on shared storage that every instance can reach, with
all concurrent state on Postgres/Redis and per-instance operational SQLite pinned to local disk.

**Status of the code prerequisites (all done + verified in-repo):**
- Knowledge/episode/entity index → Postgres (`KNOWLEDGE_BACKEND=postgres`, schema-per-agent).
- `conversation_sessions` + `taxonomy_signal_index` → same per-agent Postgres schema.
- Command Center queue → Postgres; sessions/auth/approvals/scheduler-lease → Redis.
- `traces.db` / `evidence.db` / runtime SQLite → local-disk env overrides (off the shared mount).
- `ls`/`grep`/`cat` unchanged — they read the same virtual paths, now resolving onto the mount.

**Validated this session (single machine):** two server processes on the **same** local
`enterprise_root` + same Postgres + same Redis both served the same agent, cron leader-election
elected one leader (the other went STANDBY), both used the same PG knowledge schema, and there
were **zero `database is locked` errors**. The only remaining variable in production is swapping
the local `enterprise_root` for a real network mount.

> ⚠️ **NEVER `kill -9` the server** — graceful `SIGTERM` only (a hard kill corrupted the SQLite
> WAL and caused a SIGBUS outage). **NEVER `redis-cli flushall`** — Redis holds persistent users + cron.

---

## 0. Pre-flight (all environments)

```bash
HARNESS=/…/AgentPro/IAF_AgentOS_Harness_latest        # repo root
VENV="$HARNESS/.venv/bin/python3"                     # MUST use this venv (has psycopg + libpq)

# Postgres reachable?
"$VENV" - <<'PY'
import os; from pathlib import Path; from dotenv import load_dotenv
load_dotenv(Path("agent_os/config.env")); import psycopg
c=psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5); c.cursor().execute("SELECT 1"); print("PG OK")
PY

# Redis reachable? (start it if not — see Appendix A)
"$VENV" - <<'PY'
import os,redis; from pathlib import Path; from dotenv import load_dotenv
load_dotenv(Path("agent_os/config.env")); print("REDIS", redis.from_url(os.environ["REDIS_URL"]).ping())
PY

# Back up the authoritative tree + DBs BEFORE cutover
tar czf /backup/enterprise_root_$(date +%F).tgz -C "$HARNESS" enterprise_root
# (Postgres is backed up by your normal pg_dump / snapshot process)
```

---

## 1. Provision shared storage + copy the tree  *(infra — one time)*

1. Create a shared **POSIX** filesystem all app servers mount read-write: AWS **EFS**, Azure
   **Files**, GCP **Filestore**, or NFS. (Object stores like S3/Blob are **not** POSIX — do not use
   them here; `ls`/`grep`/`cat` need real file semantics.)
2. **Name the mounted leaf directory exactly `enterprise_root`** — internal walk-up fallbacks
   look for that name (`agent.py`, `agent_os/kernel.py`, `hook_runner.py`).
3. Copy the current tree onto it, preserving structure:
   ```bash
   rsync -a "$HARNESS/enterprise_root/" /mnt/shared/enterprise_root/
   ```
4. Mount `/mnt/shared/enterprise_root` on **every** app server (and on the kernel worker host if
   `AGENTOS_KERNEL_BACKEND=remote`).

**Pre-cutover FS check (important):** the JSONL append writers use an `O_CREAT|O_EXCL` `.lock`
sidecar (`iaf_agent_skills/file_lock.py`), not `fcntl.flock`. That is portable on modern
NFSv4.1 / EFS / Azure Files. Confirm your chosen FS honors `O_EXCL` atomic create + that a test
`cat`/`grep` of a `.md` file works from two mounts before going live.

---

## 2. Configure env  *(each app server — `agent_os/config.env` or process env)*

```bash
# Point BOTH roots at the shared mount (SKILLS_PATH is an INDEPENDENT knob — set it too)
DATA_ROOT=/mnt/shared/enterprise_root
SKILLS_PATH=/mnt/shared/enterprise_root/tenants/company/skills

# Shared state (already set today)
DB_BACKEND=postgres
DATABASE_URL=postgresql://…@<pg-host>:5432/agentos
CC_QUEUE_STORAGE_BACKEND=postgres
KNOWLEDGE_BACKEND=postgres
AUTH_BACKEND=redis
REDIS_URL=redis://…@<redis-host>:6379

# Per-instance SQLite → LOCAL disk (keep off the shared mount; SQLite-over-NFS corrupts)
TRACE_DB_PATH=/var/lib/agentos-local/traces.db
EVIDENCE_DB_ROOT=/var/lib/agentos-local           # per-tenant evidence.db lives under here (SQLite backend only)
WORKSTREAM_RUNTIME_DB_PATH=/var/lib/agentos-local/workstream_runtime.db
AUTOMATION_RUNTIME_DB_PATH=/var/lib/agentos-local/automation_runtime.db
RL_DB_PATH=/var/lib/agentos-local/rl.db
EVAL_RUNTIME_DB_PATH=/var/lib/agentos-local/eval_runtime.db

# Must NOT overlap DATA_ROOT
RECOVERY_VERIFICATION_ROOT=/var/lib/agentos-recovery

# Multi-worker HTTP (optional, per host)
UVICORN_WORKERS=4

# Optional: cut repeat reads of hot files on the network mount (transparent, mtime-validated)
AGENTOS_KERNEL_FILE_CACHE=1

# Optional: share the evidence store across instances (instead of the local EVIDENCE_DB_ROOT pin)
EVIDENCE_BACKEND=postgres                          # per-tenant schema ev_<tenant>; needs DB_BACKEND=postgres
```

> `AGENTOS_KERNEL_FILE_CACHE=1` turns on a per-kernel read-through cache for whole-file reads
> (`cat`/`grep`/`wc`/`semgrep`) — useful once `enterprise_root` is on EFS/Azure Files/NFS. It is
> `mtime`-validated on every hit and invalidated on write, so it never serves stale content;
> `ls`/`find`/`head`/`tail` are not cached. Off = byte-identical to today. See
> `agent_os/docs/kernel_internals.md` → "File Read Cache".

> `DATA_ROOT`/`SKILLS_PATH` accept absolute paths (`resolve_server_path`). An absolute
> `DATA_ROOT` propagates everywhere (kernel, memory, hooks, audit, config, workstreams).

---

## 3. Migrate the last per-agent tables into Postgres  *(once per already-cutover agent)*

The knowledge index for `enterprise_agent` + `finance_agents` is already on Postgres. Copy the
same-file `conversation_sessions` into their PG schema so chat history survives (taxonomy is
rebuilt from taxonomy files automatically on first load, so it needs no copy):

```bash
cd "$HARNESS/IAF-Agent-Skills"
../.venv/bin/python3 scripts/migrate_knowledge_index_to_pg.py \
  ../enterprise_root/tenants/company/agents/enterprise_agent/memory/knowledge_index.db \
  ../enterprise_root/tenants/company/agents/finance_agents/memory/knowledge_index.db
```

- **No `--force`.** The script has a **clobber guard**: for an agent already live on Postgres it
  **skips** the knowledge tables (so it won't overwrite live PG data with the stale SQLite) and
  copies **only** `conversation_sessions`. `--force` is only for a first-time full migration.
- For a **brand-new** agent (never cut over), run the same command — it copies everything.

---

## 4. Graceful restart

```bash
# Stop (graceful — never -9). Find the real listener PID (the launch wrapper is a different PID):
PID=$(lsof -nP -iTCP:8081 -sTCP:LISTEN -t | head -1); kill -TERM "$PID"
# wait until the port frees
while lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; do sleep 1; done

# Start (from IAF-Agent-Studio, under the harness venv):
cd "$HARNESS/IAF-Agent-Studio"
nohup ../.venv/bin/python3 server.py > /var/log/agentos/studio.log 2>&1 &
```

---

## 5. Verify single instance on the mount

```bash
curl -s http://127.0.0.1:8081/health/ready          # → {"status":"ready", ...}
grep -aE "Loaded env|KnowledgeIndexer\(postgres\)|LEADER STARTED|ERROR|locked" /var/log/agentos/studio.log
```
Expect: `Loaded env` from your config, `KnowledgeIndexer(postgres): schema 'kn_…' ready`,
`Cron Scheduler: LEADER STARTED`, and **no** `database is locked`. Drive one real chat turn and
confirm the agent `cat`/`grep`s a context file (`FileMode entity resolved …` in the log).

---

## 6. Scale out + multi-instance verification  *(the acceptance test)*

Bring up a second server (different host, or same host different port) with the **same**
`DATA_ROOT`/Postgres/Redis but **its own local** `*_DB_PATH`/`EVIDENCE_DB_ROOT`/`TRACE_DB_PATH`.

```bash
# 2nd instance example (same machine, port 8082, isolated local SQLite):
cd "$HARNESS/IAF-Agent-Studio"
PORT=8082 TRACE_DB_PATH=/tmp/i2/traces.db EVIDENCE_DB_ROOT=/tmp/i2/ev \
  WORKSTREAM_RUNTIME_DB_PATH=/tmp/i2/ws.db AUTOMATION_RUNTIME_DB_PATH=/tmp/i2/auto.db \
  RL_DB_PATH=/tmp/i2/rl.db EVAL_RUNTIME_DB_PATH=/tmp/i2/eval.db \
  nohup ../.venv/bin/python3 server.py > /tmp/studio_i2.log 2>&1 &
```

**Acceptance checks (all must pass — validated this session):**
1. Both `/health/ready` → `ready`, `sessions: ready` (shared Redis).
2. **Leader election:** exactly one log says `Cron Scheduler: LEADER STARTED`; the other says
   `Cron Scheduler: STANDBY (another leader owns the lease)`. (Cron must NOT double-fire.)
3. Both logs: `KnowledgeIndexer(postgres): schema 'kn_company_<agent>' ready` — **same** schema.
4. `grep -aic "database is locked" <both logs>` → **0**.
5. A chat turn routed to each instance for the **same** agent returns consistent memory/knowledge.

Tear down the extra instance with `kill -TERM <its listener PID>` (never `-9`, never `pkill -f
server.py` if another instance shares the host).

---

## 7. Rollback (per agent / whole instance)

- **Knowledge/conversation/taxonomy:** set `KNOWLEDGE_BACKEND=sqlite` and restart. The original
  per-agent `knowledge_index.db` is **untouched and authoritative** — you're back on SQLite.
- **Files:** point `DATA_ROOT`/`SKILLS_PATH` back at the local copy and restart. The shared-mount
  copy and the local copy are independent.
- **Queue:** `CC_QUEUE_STORAGE_BACKEND=sqlite` (single-instance only) — but multi-instance requires
  Postgres, so only roll back the queue if collapsing to one node.

---

## Appendix A — Start Redis

```bash
# Uses the shipped config (its requirepass matches REDIS_URL; loads existing AOF/RDB — non-destructive)
/…/AgentPro/software/redis-stable/src/redis-server /…/AgentPro/software/redis-stable/redis-iaf.conf
# verify:
"$VENV" -c "import os,redis;from dotenv import load_dotenv;load_dotenv('agent_os/config.env');print(redis.from_url(os.environ['REDIS_URL']).ping())"
```
Note `redis-iaf.conf` has `appendonly yes` and `dir=…/AgentPro/IAF-Agent-Studio`. Confirm that
directory is the Redis dataset you intend before starting.

---

## Known follow-ups (not blockers for the mount move)

- **evidence → Postgres (tenant-scoped).** ✅ **Done.** Set `EVIDENCE_BACKEND=postgres` (needs
  `DB_BACKEND=postgres` + `DATABASE_URL`) to move the evidence tables to a per-tenant schema
  (`ev_<tenant>`) on the shared engine — every instance then shares evidence instead of the
  local `EVIDENCE_DB_ROOT` pin. Default stays `sqlite`. Parity gate:
  `IAF-Agent-Studio/tests/test_evidence_backend_parity.py`. See `docs/STORAGE_BACKENDS.md` →
  "Evidence store on Postgres". (No historical-data copy script is shipped: evidence bundles are
  per-execution artifacts regenerated on each run, so a cutover simply starts writing to PG;
  copy old rows manually only if you need pre-cutover bundles retained.)
- **credentials → a secrets manager** (Vault/KMS) instead of the encrypted file store.
- **Cleanup** superseded SQLite files after cutover: `command_center.db` (queue on PG),
  `auth_*.db` (auth on Redis).
- **pgvector** for vector search + **schema-per-agent → discriminator columns** at very large agent
  counts (post-cutover scale work).

## Config reference
See `docs/CONFIG_REFERENCE.md` for every env var above (`DATA_ROOT`, `SKILLS_PATH`,
`KNOWLEDGE_BACKEND`, `TRACE_DB_PATH`, `EVIDENCE_DB_ROOT`, the `*_RUNTIME_DB_PATH` overrides,
`UVICORN_WORKERS`, `RECOVERY_VERIFICATION_ROOT`) and `docs/STORAGE_BACKENDS.md` for the backend
architecture.
