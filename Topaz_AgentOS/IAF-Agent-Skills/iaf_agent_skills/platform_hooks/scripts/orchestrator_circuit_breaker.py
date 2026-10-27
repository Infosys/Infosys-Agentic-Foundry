#!/usr/bin/env python3
"""
Circuit Breaker — PreStep (orchestrator) + PreToolUse/invoke_skill (react)

Tracks consecutive failures per skill within one run/session.
Opens the circuit after CIRCUIT_OPEN_AFTER consecutive failures.

State stored in /tmp/iaf_circuit_{run_id}.json — one file per run/session.

Orchestrator: reads IAF_STEP_NAME directly.
React:        reads target_skill from IAF_TOOL_INPUT JSON (invoke_skill args).

Exit 0 → allow
Exit 1 → block (orchestrator records in step_log; react hook blocks the tool call)
"""

import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Only alphanumerics, hyphens, and underscores — no slashes or dots that
# could escape the tempdir via path traversal when embedded in a filename.
_SAFE_RUN_ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,127}$')


def _confined_state_file(safe_run_id: str):
    """Return the per-run state path confined to the tempdir, or None if it escapes.

    Standalone hook process: ``agent_os`` may not be importable, so this inlines the
    resolve + is_relative_to + rebuild steps of ``agent_os.safe_path.confine_to_root``.
    """
    temp_root = Path(tempfile.gettempdir()).resolve()
    candidate = (temp_root / f"iaf_circuit_{safe_run_id}.json").resolve()
    if not candidate.is_relative_to(temp_root):
        return None
    return Path(str(candidate).encode("utf-8").decode("utf-8"))


def _parse_tool_input(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            return {}

CIRCUIT_OPEN_AFTER = 2

exec_mode = os.environ.get("IAF_EXECUTION_MODE", "")
_run_id_match = _SAFE_RUN_ID_RE.fullmatch(os.environ.get("IAF_RUN_ID", ""))
run_id = _run_id_match.group(0) if _run_id_match else ""

if exec_mode not in ("orchestrator", "react") or not run_id:
    sys.exit(0)

# Resolve skill name — differs by mode
if exec_mode == "react":
    try:
        tool_input = _parse_tool_input(os.environ.get("IAF_TOOL_INPUT", "{}"))
        skill = tool_input.get("target_skill", "").strip()
    except Exception:
        skill = ""
else:
    skill = os.environ.get("IAF_STEP_NAME", "")

if not skill:
    sys.exit(0)

state_file = _confined_state_file(run_id)
if state_file is None:
    sys.exit(0)

try:
    state = json.loads(open(state_file, encoding="utf-8").read()) if os.path.exists(state_file) else {}
except Exception:
    state = {}

consecutive_fails = state.get(skill, {}).get("consecutive", 0)

if consecutive_fails >= CIRCUIT_OPEN_AFTER:
    total_fails = state.get(skill, {}).get("total", consecutive_fails)
    msg = (
        f"Circuit open for '{skill}': {consecutive_fails} consecutive failures "
        f"({total_fails} total this run). Skipping to let agent route elsewhere."
    )
    print(json.dumps({"blocked": True, "reason": msg}))
    sys.exit(1)

sys.exit(0)
