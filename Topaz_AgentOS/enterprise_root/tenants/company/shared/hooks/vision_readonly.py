#!/usr/bin/env python3
"""PreToolUse hook — vision_readonly (on_block: deny).

The safety net BELOW the LLM for physical-AI graphs: while a vision *read* node
is active (classify / verify / capture), the agent may look but must not touch.
Any write / side-effecting tool call is blocked so a mis-behaving read node can
never mutate stock, payments, tickets, or the database. The graph's *act* node
runs under a different (non-read) skill name, so it is NOT blocked here — writes
happen only after the confidence gate, in the act step.

Scope: self-limiting. It only enforces when the active skill looks like a vision
read node (name ends in _classify / _verify / _capture, or contains 'vision_read',
or IAF_VISION_READONLY=1). Everywhere else it is a no-op (exit 0).

Env (provided by hook_runner): IAF_SKILL_NAME, IAF_TOOL_NAME, IAF_TOOL_INPUT.
Exit 0 → allow. Exit 1 + {"blocked": true, "reason": ...} → deny.
"""

import json
import os
import re
import sys

skill = os.environ.get("IAF_SKILL_NAME", "")
tool = os.environ.get("IAF_TOOL_NAME", "")
tool_input = os.environ.get("IAF_TOOL_INPUT", "")

# Only guard vision read/verify nodes. Act/close nodes write legitimately.
READONLY_MARKERS = ("_classify", "_verify", "_capture", "vision_read")
in_scope = os.environ.get("IAF_VISION_READONLY", "") == "1" or any(
    skill.endswith(m) or m in skill for m in READONLY_MARKERS
)
if not in_scope or not tool:
    sys.exit(0)

# Read-only tools a vision node legitimately uses (allow-list wins).
READ_ONLY_TOOLS = {
    "jev_see", "jev_vision_verify", "jev_decide", "jev_verify",
    "query_memory", "fetch_canonical", "request_human_approval",
}
if tool in READ_ONLY_TOOLS:
    sys.exit(0)

WRITE_TOOL_PATTERNS = [
    r"create", r"update", r"delete", r"insert", r"remove", r"write",
    r"post_to", r"\bpay\b", r"release", r"send_email", r"execute", r"upsert",
]
WRITE_SQL = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|REPLACE|TRUNCATE)\b", re.IGNORECASE)
# Read-intent tool names; unrecognised tools are default-denied below.
READ_INTENT = re.compile(
    r"(?:^|[_-])(get|read|list|query|fetch|see|search|lookup|view|show|count|describe|"
    r"inspect|verify|decide|classify|capture|detect|scan|observe)(?:$|[_-])",
    re.IGNORECASE,
)

blocked_reason = None
for pat in WRITE_TOOL_PATTERNS:
    if re.search(pat, tool, re.IGNORECASE):
        blocked_reason = f"write-intent tool {tool!r} called inside vision read node {skill!r}"
        break
if blocked_reason is None and WRITE_SQL.search(tool_input):
    blocked_reason = f"write-intent SQL inside vision read node {skill!r}"
if blocked_reason is None and not READ_INTENT.search(tool):
    blocked_reason = (
        f"unrecognised (non read-only) tool {tool!r} inside vision read node {skill!r} "
        f"— vision read nodes are default-deny except explicit read tools"
    )

if blocked_reason:
    reason = (
        f"vision_readonly gate: {blocked_reason}. A vision read/verify node may only "
        f"observe — writes must happen in the act node after the confidence gate."
    )
    print(json.dumps({"blocked": True, "reason": reason}))
    sys.exit(1)

sys.exit(0)
