# Start / Stop / Restart — IAF AgentOS (local dev)

The stack has three parts that must come up **in order**: **Postgres → Redis → server**.
The server (IAF-Agent-Studio, port **8081**) needs Postgres and Redis already running.

| Component | Port | How it runs | Auto-starts at boot? |
|---|---|---|---|
| **Postgres** (EnterpriseDB 18) | 5432 | System service (`postgresql-18.plist`), runs as the `postgres` OS user | ✅ yes |
| **Redis** | 6379 | Started manually from `software/redis-stable` | ❌ no — start it |
| **Server** (IAF-Agent-Studio) | 8081 | `../.venv/bin/python3 server.py` from `IAF-Agent-Studio/` | ❌ no — start it |

> `lsof -iTCP:5432` shows nothing even when Postgres is up — it runs as the `postgres` user,
> so a non-admin can't see its socket. Use `pg_isready` (below) to check Postgres, not `lsof`.

## Easiest way — the `ops/` scripts

```bash
cd IAF_AgentOS_Harness_latest
./ops/status.sh     # show Postgres / Redis / server state
./ops/start.sh      # ensure Postgres + Redis up, then start the server
./ops/restart.sh    # graceful restart of the server (SIGTERM + relaunch)
./ops/stop.sh       # graceful stop of the server
```

`start.sh` starts Redis if it's down and waits for the server's health check. `restart.sh`/`stop.sh`
use **SIGTERM only** and leave Redis + Postgres running.

## Manual commands (what the scripts do)

Set these once per terminal:
```bash
AGENTPRO=/path/to/your/workspace
HARNESS="$AGENTPRO/IAF_AgentOS_Harness"
```

**1. Check:**
```bash
/Library/PostgreSQL/18/bin/pg_isready -h localhost -p 5432     # Postgres → "accepting connections"
lsof -nP -iTCP:6379 -sTCP:LISTEN -t                            # Redis → a PID = up
curl -s http://127.0.0.1:8081/health/ready                     # Server → {"status":"ready",...}
```

**2. Postgres** (rarely needed — auto-starts; needs the admin account if truly down):
```bash
sudo -u postgres /Library/PostgreSQL/18/bin/pg_ctl -D /Library/PostgreSQL/18/data start
```

**3. Redis** (start if down):
```bash
nohup "$AGENTPRO/software/redis-stable/src/redis-server" \
      "$AGENTPRO/software/redis-stable/redis-iaf.conf" > /tmp/redis-iaf.log 2>&1 &
```

**4. Start the server:**
```bash
cd "$HARNESS/IAF-Agent-Studio"
nohup ../.venv/bin/python3 server.py > /tmp/studio.log 2>&1 &
sleep 14 && curl -s http://127.0.0.1:8081/health/ready
```

**5. Restart the server (graceful):**
```bash
PID=$(lsof -nP -iTCP:8081 -sTCP:LISTEN -t | head -1); kill -TERM "$PID"
while lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; do sleep 1; done
cd "$HARNESS/IAF-Agent-Studio" && nohup ../.venv/bin/python3 server.py > /tmp/studio.log 2>&1 &
```

**6. Logs / UI:**
```bash
tail -f /tmp/studio.log
# http://localhost:8081/dashboard/v2
```

## ⚠️ Critical rules

- **NEVER `kill -9` the server.** A hard kill corrupted the SQLite WAL and caused a SIGBUS outage.
  Always `kill -TERM` and wait for the port to free (the scripts do this).
- **NEVER `redis-cli flushall`.** Redis holds persistent users + cron jobs.
- **Always use `../.venv/bin/python3`** (not system Python) — that venv has `psycopg` + `psycopg_pool` + `pgvector`.
- **Order on a fresh boot:** Postgres is back automatically; **you start Redis then the server** (`./ops/start.sh` does both).
