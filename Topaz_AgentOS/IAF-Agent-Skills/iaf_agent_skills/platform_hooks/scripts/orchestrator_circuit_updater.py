#!/usr/bin/env python3
"""
Circuit State Updater — PostStep (orchestrator) + PostToolUse/invoke_skill (react)

Updates the per-run/session circuit breaker state after each skill invocation.
Resets consecutive count on success, increments on failure.

Orchestrator: success from IAF_STEP_SUCCESS, skill from IAF_STEP_NAME.
React:        success inferred from IAF_TOOL_OUTPUT (error prefix check),
              skill from IAF_TOOL_INPUT JSON target_skill.

Always exits 0.
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

exec_mode = os.environ.get("IAF_EXECUTION_MODE", "")
_run_id_match = _SAFE_RUN_ID_RE.fullmatch(os.environ.get("IAF_RUN_ID", ""))
run_id = _run_id_match.group(0) if _run_id_match else ""

if exec_mode not in ("orchestrator", "react") or not run_id:
    sys.exit(0)

if exec_mode == "react":
    try:
        tool_input = _parse_tool_input(os.environ.get("IAF_TOOL_INPUT", "{}"))
        skill = tool_input.get("target_skill", "").strip()
    except Exception:
        skill = ""
    tool_output = os.environ.get("IAF_TOOL_OUTPUT", "")
    success = not tool_output.lstrip().startswith("Error:")
else:
    skill   = os.environ.get("IAF_STEP_NAME", "")
    success = os.environ.get("IAF_STEP_SUCCESS", "true").lower() == "true"

if not skill:
    sys.exit(0)

state_file = _confined_state_file(run_id)
if state_file is None:
    sys.exit(0)

try:
    state = json.loads(open(state_file, encoding="utf-8").read()) if os.path.exists(state_file) else {}
except Exception:
    state = {}

entry = state.get(skill, {"consecutive": 0, "total": 0})

if success:
    entry["consecutive"] = 0
else:
    entry["consecutive"] = entry["consecutive"] + 1
    entry["total"]       = entry.get("total", 0) + 1

state[skill] = entry

try:
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f)
except Exception:
    pass

sys.exit(0)
