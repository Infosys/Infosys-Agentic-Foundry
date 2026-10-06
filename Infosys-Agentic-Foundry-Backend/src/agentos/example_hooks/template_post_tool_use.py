#!/usr/bin/env python3
"""
PostToolUse Hook: <HOOK_NAME>
============================================================
Description: <DESCRIBE WHAT THIS HOOK DOES WITH TOOL OUTPUT>

Exit codes:
  0 = ALLOW              (tool output passes to LLM as-is)
  1 = BLOCK              (tool output is suppressed/replaced)
  2 = APPROVAL_REQUIRED  (pause for human review of output)

Environment variables:
  IAF_HOOK_EVENT   = "PostToolUse"
  IAF_TOOL_NAME    = Name of the tool that executed
  IAF_TOOL_INPUT   = JSON string of tool arguments
  IAF_TOOL_OUTPUT  = Tool's output text (max 4KB)
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
    tool_output = os.environ.get("IAF_TOOL_OUTPUT", "")

    try:
        tool_input = json.loads(tool_input_raw)
    except json.JSONDecodeError:
        tool_input = {}

    # --- YOUR LOGIC: Inspect tool output ---
    # Example: Log the output, check for sensitive data, etc.
    #
    # if <BLOCK_CONDITION>:
    #     print(json.dumps({"reason": "<WHY_OUTPUT_BLOCKED>"}))
    #     sys.exit(1)
    #
    # if <NEEDS_REVIEW_CONDITION>:
    #     print(json.dumps({"reason": "<WHY_APPROVAL_NEEDED>"}))
    #     sys.exit(2)

    # --- DEFAULT: ALLOW ---
    sys.exit(0)


if __name__ == "__main__":
    main()