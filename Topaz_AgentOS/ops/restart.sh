#!/usr/bin/env bash
# Gracefully restart the server (stop via SIGTERM, wait for the port to free, start again).
# Redis + Postgres are left running.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/stop.sh"
stop_rc=$?
if [ "$stop_rc" -ne 0 ]; then
  echo "restart.sh: stop.sh failed (exit $stop_rc); aborting restart without starting." >&2
  exit "$stop_rc"
fi
"$SCRIPT_DIR/start.sh"
