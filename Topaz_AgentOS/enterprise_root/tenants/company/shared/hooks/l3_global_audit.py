#!/usr/bin/env python3
"""
L3 test — Hook A: global PreToolUse audit (observe-only, all skills).

Logs every tool invocation to /tmp/l3_audit.log so we can prove
the hook plumbing fires regardless of active skill.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import logging
logger = logging.getLogger(__name__)

LOG = os.path.join(tempfile.gettempdir(), "l3_audit.log")


def main() -> int:
    skill = os.getenv("IAF_SKILL_NAME", "?")
    tool = os.getenv("IAF_TOOL_NAME", "?")
    user = os.getenv("IAF_USER_ID", "?")
    trace = os.getenv("IAF_TRACE_ID", "?")[:8]
    tool_input_preview = os.getenv("IAF_TOOL_INPUT", "")[:160]

    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} HOOK_A fired\n")

    logger.debug(json.dumps({"blocked": False}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sys.exit(main())
