#!/usr/bin/env python3
"""
Audit Log — PostStep (orchestrator) + PostToolUse/invoke_skill (react)

Writes one JSONL entry per skill invocation to orchestrator_audit.jsonl.

Orchestrator: all fields from IAF_STEP_* env vars.
React:        skill from IAF_TOOL_INPUT JSON, success inferred from
              IAF_TOOL_OUTPUT, run_id from IAF_RUN_ID (= session_id).

Always exits 0.
"""

import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

def _parse_tool_input(raw: str) -> dict:
    """Parse IAF_TOOL_INPUT — handles both JSON and Python repr (single-quoted)."""
    try:
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            return {}

exec_mode = os.environ.get("IAF_EXECUTION_MODE", "")

if exec_mode not in ("orchestrator", "react"):
    sys.exit(0)

agent_root = str(Path(__file__).resolve().parents[4])
audit_file = Path(__file__).resolve().parents[4] / "shared" / "databases" / "orchestrator_audit.jsonl"

if exec_mode == "react":
    tool_input = _parse_tool_input(os.environ.get("IAF_TOOL_INPUT", "{}"))
    skill      = tool_input.get("target_skill", "").strip()
    tool_output = os.environ.get("IAF_TOOL_OUTPUT", "")
    success     = "false" if tool_output.lstrip().startswith("Error:") else "true"
    run_id      = os.environ.get("IAF_RUN_ID", "")
    # Derive step_num by counting existing entries for this run
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            step_num = str(sum(1 for line in f if run_id and run_id in line) + 1)
    except FileNotFoundError:
        step_num = "1"
    entry = {
        "ts":          datetime.now(timezone.utc).isoformat() + "Z",
        "run_id":      run_id,
        "step_num":    step_num,
        "skill":       skill,
        "success":     success,
        "duration_ms": "",
        "trace_id":    "",
        "user_id":     os.environ.get("IAF_USER_ID", ""),
        "tenant_id":   os.environ.get("IAF_TENANT_ID", ""),
        "mode":        "react",
    }
else:
    entry = {
        "ts":          datetime.now(timezone.utc).isoformat() + "Z",
        "run_id":      os.environ.get("IAF_RUN_ID", ""),
        "step_num":    os.environ.get("IAF_STEP_NUM", ""),
        "skill":       os.environ.get("IAF_STEP_NAME", ""),
        "success":     os.environ.get("IAF_STEP_SUCCESS", ""),
        "duration_ms": os.environ.get("IAF_STEP_DURATION_MS", ""),
        "trace_id":    os.environ.get("IAF_STEP_TRACE_ID", ""),
        "user_id":     os.environ.get("IAF_USER_ID", ""),
        "tenant_id":   os.environ.get("IAF_TENANT_ID", ""),
        "mode":        "orchestrator",
    }

if not entry.get("skill"):
    sys.exit(0)

try:
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
except Exception as e:
    logger.debug(f"audit_log warning: {e}")

sys.exit(0)
