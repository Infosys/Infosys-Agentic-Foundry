#!/usr/bin/env python3
"""
PreToolUse Hook: <HOOK_NAME>
============================================================
Description: <DESCRIBE WHAT THIS HOOK CHECKS BEFORE TOOL RUNS>

Exit codes:
  0 = ALLOW              (tool executes normally)
  1 = BLOCK              (tool call is rejected)
  2 = APPROVAL_REQUIRED  (pause for human approval)

Environment variables:
  IAF_HOOK_EVENT   = "PreToolUse"
  IAF_TOOL_NAME    = Name of the tool about to execute
  IAF_TOOL_INPUT   = JSON string of tool arguments
  IAF_SESSION_ID   = Chat session ID
  IAF_AGENT_ID     = Agent ID
  IAF_QUERY        = User's original query
"""
import os
import sys
import json


def main():
    tool_name = os.environ.get("IAF_TOOL_NAME", "")
    tool_input_raw = os.environ.get("IAF_TOOL_INPUT", "{}")

    try:
        tool_input = json.loads(tool_input_raw)
    except json.JSONDecodeError:
        tool_input = {}

    # --- YOUR LOGIC: Inspect tool_name and tool_input ---
    # Example: Block if a specific dangerous pattern is found
    #
    # if <BLOCK_CONDITION>:
    #     print(json.dumps({"reason": "<WHY_BLOCKED>"}))
    #     sys.exit(1)
    #
    # if <NEEDS_REVIEW_CONDITION>:
    #     print(json.dumps({"reason": "<WHY_APPROVAL_NEEDED>"}))
    #     sys.exit(2)

    # --- DEFAULT: ALLOW ---
    sys.exit(0)


if __name__ == "__main__":
    main()
