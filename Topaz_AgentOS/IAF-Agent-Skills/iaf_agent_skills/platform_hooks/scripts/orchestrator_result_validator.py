#!/usr/bin/env python3
"""
Orchestrator Result Validator — PostStep hook

Inspects the subagent result after each step. If the result looks like an
error or is empty, returns a feedback string that gets appended to the
step_log and surfaced to the manager LLM on its next decision.

The manager LLM reads the feedback and can:
  - Retry the same skill with a differently phrased task
  - Try a different skill
  - Decide it has enough data and synthesise anyway

Env vars read:
  IAF_STEP_RESULT    — first 500 chars of subagent result
  IAF_STEP_NAME      — skill that ran
  IAF_STEP_SUCCESS   — "true" or "false"
  IAF_EXECUTION_MODE — only fires for orchestrator mode

Exit 0 always (PostStep never blocks).
Stdout JSON with "feedback" key if issue detected.
"""

import json
import os
import sys

exec_mode = os.environ.get("IAF_EXECUTION_MODE", "")
if exec_mode != "orchestrator":
    sys.exit(0)

skill   = os.environ.get("IAF_STEP_NAME", "")
result  = os.environ.get("IAF_STEP_RESULT", "").strip()
success = os.environ.get("IAF_STEP_SUCCESS", "true").lower() == "true"

# Already flagged as failed by engine — add specific guidance
if not success:
    print(json.dumps({
        "feedback": (
            f"Step failed for '{skill}'. "
            f"Consider rephrasing the task with more specific parameters, "
            f"or try a different skill to get this data."
        )
    }))
    sys.exit(0)

# Empty result
if not result or len(result) < 10:
    print(json.dumps({
        "feedback": (
            f"'{skill}' returned an empty or very short result. "
            f"The data may not exist, or the task may need more specific filters."
        )
    }))
    sys.exit(0)

# Error signatures in result text
ERROR_SIGNATURES = [
    "error:", "traceback (most recent", "exception:", "failed to",
    "could not connect", "permission denied", "no such table",
    "syntax error", "column not found",
]

result_lower = result.lower()
for sig in ERROR_SIGNATURES:
    if sig in result_lower:
        print(json.dumps({
            "feedback": (
                f"'{skill}' result contains an error indicator ('{sig}'). "
                f"The task may need different query parameters or the data source may be unavailable."
            )
        }))
        sys.exit(0)

# No issues found — silent exit
sys.exit(0)
