#!/usr/bin/env bash
# Gracefully stop the server. NEVER kill -9 — a hard kill corrupts the SQLite WAL (SIGBUS outage).
# Leaves Redis + Postgres running (they hold persistent state used across restarts).
set -uo pipefail
PORT=8081

PID=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | head -1)
if [ -z "$PID" ]; then
  echo "Server not running on $PORT."
  exit 0
fi
echo "Stopping server PID $PID (SIGTERM)..."
kill -TERM "$PID"
for _ in $(seq 1 30); do
  lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 || { echo "Stopped (port $PORT freed)."; exit 0; }
  sleep 1
done
echo "WARNING: port $PORT still busy after 30s."
echo "Do NOT kill -9 (WAL corruption risk). Check /tmp/studio.log and retry SIGTERM."
exit 1
