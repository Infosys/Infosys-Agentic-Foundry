#!/usr/bin/env python3
"""
Hook 1 — PreToolUse: Audit every shell tool call to a log file.

Fires before every shell command the ccdops agent runs.
Writes one timestamped line to /tmp/ccdops_audit.log.
Always exits 0 (non-blocking — audit only).

Verify after chatting:
    cat /tmp/ccdops_audit.log
"""

import os
import sys
import tempfile
from datetime import datetime

LOG_FILE = os.path.join(tempfile.gettempdir(), "ccdops_audit.log")

tool_name   = os.environ.get("IAF_TOOL_NAME", "")
tool_input  = os.environ.get("IAF_TOOL_INPUT", "")
session_id  = os.environ.get("IAF_SESSION_ID", "")
agent_id    = os.environ.get("IAF_AGENT_ID", "")
skill_name  = os.environ.get("IAF_SKILL_NAME", "")
user_id     = os.environ.get("IAF_USER_ID", "")

# Trim command for readability — first 120 chars (mask bearer tokens)
import re as _re

import logging
logger = logging.getLogger(__name__)
try:
    import json
    parsed = json.loads(tool_input)
    raw_cmd = str(parsed.get("command", tool_input))
except Exception:
    raw_cmd = tool_input
cmd_preview = _re.sub(
    r'(Bearer\s+)[A-Za-z0-9\-_\.]+', r'\1[REDACTED]', raw_cmd, flags=_re.IGNORECASE
)[:120]

ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
line = f"[{ts}] ccdops_audit hook fired\n"

try:
    with open(LOG_FILE, "a") as f:
        f.write(line)
except Exception as e:
    # Never fail — just print warning and continue
    logger.debug(f"audit write failed: {e}")

sys.exit(0)
