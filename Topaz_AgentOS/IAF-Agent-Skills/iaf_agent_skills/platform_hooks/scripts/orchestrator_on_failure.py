#!/usr/bin/env python3
"""
Orchestrator Failure Handler — OnExecutionFailure hook (fire-and-forget)

Fires when a subagent raises an unhandled exception during a step.
Use this as the entry point for saga/compensation logic — extend with
domain-specific rollback calls (e.g. cancel a staged SAP payment).

Currently: logs the failure to the audit file and prints a warning.
Extend by adding domain-specific compensation below the TODO marker.

Env vars read:
  IAF_RUN_ID         — orchestrator run correlation ID
  IAF_STEP_NUM       — which step failed
  IAF_STEP_NAME      — which skill threw the exception
  IAF_ERROR_MSG      — exception string (first 500 chars)
  IAF_USER_ID        — who triggered the run
  IAF_TENANT_ID      — tenant
  IAF_EXECUTION_MODE — only fires for orchestrator mode

Always exits 0.
"""

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

exec_mode = os.environ.get("IAF_EXECUTION_MODE", "")
if exec_mode != "orchestrator":
    sys.exit(0)

run_id    = os.environ.get("IAF_RUN_ID", "")
step_num  = os.environ.get("IAF_STEP_NUM", "")
skill     = os.environ.get("IAF_STEP_NAME", "")
error_msg = os.environ.get("IAF_ERROR_MSG", "")
user_id   = os.environ.get("IAF_USER_ID", "")
tenant_id = os.environ.get("IAF_TENANT_ID", "")

logger.debug(
    "[orchestrator_on_failure] run=%s step=%s skill=%s error=%s",
    run_id[:8], step_num, skill, error_msg[:120],
)

# Write to failure log in a fixed tempdir location.
failure_file = Path(tempfile.gettempdir()) / "orchestrator_failures.jsonl"
entry = {
    "ts":        datetime.now(timezone.utc).isoformat() + "Z",
    "run_id":    run_id,
    "step_num":  step_num,
    "skill":     skill,
    "error_msg": error_msg,
    "user_id":   user_id,
    "tenant_id": tenant_id,
}
try:
    failure_file.parent.mkdir(parents=True, exist_ok=True)
    with open(failure_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
except Exception:
    pass

# ── TODO: Domain-specific compensation ──────────────────────────────────────
#
# If this skill wrote something to an external system that needs to be reversed,
# add the rollback logic here. Example for a payment staging skill:
#
#   if skill == "payment_processing":
#       import subprocess
#       subprocess.run(["python3", "/hooks/reverse_staged_payment.py", run_id, step_num])
#
# Each compensation script should be idempotent (safe to run twice).
# ────────────────────────────────────────────────────────────────────────────

sys.exit(0)
