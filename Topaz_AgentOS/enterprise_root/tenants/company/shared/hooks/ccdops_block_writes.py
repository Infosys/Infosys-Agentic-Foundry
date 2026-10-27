#!/usr/bin/env python3
"""
Hook 2 — PreToolUse: Block destructive HTTP operations at the kernel level.

Checks if the shell command contains DELETE or PATCH curl calls against
the Kubernetes API or any write-intent keywords. If found → exit 1 (blocked).

This is the safety net BELOW the LLM. Even if the agent forgets to call
request_human_approval, this hook catches destructive kubectl-equivalent
curl calls before they execute.

Blocked patterns:
  -X DELETE    →  pod delete, resource delete
  -X PATCH     →  deployment patch, scale replicas
  --request DELETE / --request PATCH
  kubectl delete / kubectl patch / kubectl drain / kubectl cordon

Exits:
  0  →  safe read-only operation, allow through
  1  →  destructive operation detected, block and show reason

Verify from chat UI:
  Say "delete the applauncher pod" — you should see the block message.
"""

import json
import os
import re
import sys

tool_input = os.environ.get("IAF_TOOL_INPUT", "")

try:
    parsed = json.loads(tool_input)
    command = str(parsed.get("command", ""))
except Exception:
    command = tool_input

DESTRUCTIVE_PATTERNS = [
    r"-X\s+DELETE\b",
    r"--request\s+DELETE\b",
    r"-X\s+PATCH\b",
    r"--request\s+PATCH\b",
    r"\bkubectl\s+(delete|patch|drain|cordon|uncordon|taint|scale)\b",
    r"\bkubectl\s+rollout\s+restart\b",
]

for pattern in DESTRUCTIVE_PATTERNS:
    if re.search(pattern, command, re.IGNORECASE):
        reason = (
            f"CCD Ops safety gate: destructive operation detected "
            f"(matched: {pattern!r}). "
            f"Use request_human_approval before executing write operations on the cluster."
        )
        # Structured JSON so HookRunner shows a clean reason
        print(json.dumps({"blocked": True, "reason": reason}))
        sys.exit(1)

sys.exit(0)
