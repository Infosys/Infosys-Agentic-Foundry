#!/usr/bin/env python3
"""
PreResponse Hook: <HOOK_NAME>
============================================================
Description: <DESCRIBE WHAT THIS HOOK FILTERS IN THE RESPONSE>

Exit codes:
  0 = ALLOW   (response passes to user as-is, OR stdout = replacement text)
  1 = BLOCK   (response is suppressed entirely)

NOTE: PreResponse does NOT support exit code 2 (approval).
      To provide a modified/redacted response, exit 0 and write
      the replacement text to stdout.

Environment variables:
  IAF_HOOK_EVENT   = "PreResponse"
  IAF_RESPONSE     = Full agent response text
  IAF_SESSION_ID   = Chat session ID
  IAF_AGENT_ID     = Agent ID
  IAF_QUERY        = User's original query
"""
import os
import sys
import json


def main():
    response = os.environ.get("IAF_RESPONSE", "")

    if not response:
        sys.exit(0)

    # --- YOUR LOGIC: Inspect or modify the response ---
    # Example: Check for sensitive patterns, redact, or block
    #
    # if <BLOCK_CONDITION>:
    #     print(json.dumps({"reason": "<WHY_RESPONSE_BLOCKED>"}))
    #     sys.exit(1)
    #
    # To REDACT/MODIFY the response (exit 0 + stdout = replacement):
    #     modified = response.replace("<SENSITIVE>", "[REDACTED]")
    #     sys.stdout.write(modified)
    #     sys.exit(0)

    # --- DEFAULT: ALLOW (pass response unchanged) ---
    sys.exit(0)


if __name__ == "__main__":
    main()