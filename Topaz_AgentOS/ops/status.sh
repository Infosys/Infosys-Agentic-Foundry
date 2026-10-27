#!/usr/bin/env bash
# Show the status of the IAF AgentOS stack (Postgres, Redis, server).
set -uo pipefail

PORT=${PORT:-8081}

echo "Postgres (5432):"
if /Library/PostgreSQL/18/bin/pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
  echo "  UP — accepting connections"
else
  echo "  DOWN — not accepting connections"
fi

echo "Redis (6379):"
RPID=$(lsof -nP -iTCP:6379 -sTCP:LISTEN -t 2>/dev/null | head -1)
[ -n "$RPID" ] && echo "  UP — PID $RPID" || echo "  DOWN"

echo "Server ($PORT):"
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:$PORT/health/ready 2>/dev/null)
if [ "$CODE" = "200" ]; then
  echo "  UP — ready (http://localhost:$PORT/dashboard/v2)"
else
  SPID=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | head -1)
  [ -n "$SPID" ] && echo "  LISTENING (PID $SPID) but health=${CODE:-none}" || echo "  DOWN"
fi
