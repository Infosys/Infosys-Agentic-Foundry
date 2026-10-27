#!/usr/bin/env bash
# Start the IAF AgentOS stack: ensure Postgres + Redis are up, then launch the server.
# Order matters — the server needs Postgres and Redis first.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTPRO="$(cd "$HARNESS/.." && pwd)"
REDIS_DIR="$AGENTPRO/software/redis-stable"
PORT=8081

echo "== Postgres =="
if /Library/PostgreSQL/18/bin/pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
  echo "  UP"
else
  echo "  DOWN. Postgres is a system service (auto-starts at boot). To start it manually:"
  echo "    sudo -u postgres /Library/PostgreSQL/18/bin/pg_ctl -D /Library/PostgreSQL/18/data start"
  echo "  (needs the admin account). Continuing — the server will fail if it stays down."
fi

echo "== Redis =="
if lsof -nP -iTCP:6379 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "  UP — PID $(lsof -nP -iTCP:6379 -sTCP:LISTEN -t | head -1)"
else
  echo "  starting (loads existing AOF/RDB — non-destructive)..."
  nohup "$REDIS_DIR/src/redis-server" "$REDIS_DIR/redis-iaf.conf" > /tmp/redis-iaf.log 2>&1 &
  sleep 2
  lsof -nP -iTCP:6379 -sTCP:LISTEN -t >/dev/null 2>&1 && echo "  UP" || { echo "  FAILED — see /tmp/redis-iaf.log"; }
fi

echo "== Server =="
if lsof -nP -iTCP:$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "  Already running on $PORT. Use ops/restart.sh to restart."
  exit 0
fi
cd "$HARNESS/IAF-Agent-Studio"
nohup ../.venv/bin/python3 server.py > /tmp/studio.log 2>&1 &
echo "  launched (PID $!), waiting for health..."
for _ in $(seq 1 30); do
  sleep 1
  if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:$PORT/health/ready 2>/dev/null)" = "200" ]; then
    echo "  READY → http://localhost:$PORT/dashboard/v2  (logs: tail -f /tmp/studio.log)"
    exit 0
  fi
done
echo "  NOT ready after 30s — check /tmp/studio.log"
exit 1
