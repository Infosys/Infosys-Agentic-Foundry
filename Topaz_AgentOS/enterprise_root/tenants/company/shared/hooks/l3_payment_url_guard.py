#!/usr/bin/env python3
"""
L3 test — Hook C: content-based, skill-agnostic blocking guard.

`skills:` is empty (all skills) and `matcher:` is .* — this hook inspects
tool_input regardless of skill or tool name and DENIES any HTTP call
targeting destructive payment endpoints on the secure mock API:

    /payments/release    /vendors/*/bank_details

Demonstrates content-aware gating: even if a skill is entitled to the
admin key and the kernel allowlist permits the host, this hook can still
veto specific URL paths.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time

import logging
logger = logging.getLogger(__name__)

LOG = os.path.join(tempfile.gettempdir(), "l3_audit.log")

DESTRUCTIVE = re.compile(
    r"(?:/payments/release\b|/vendors/[^/\s\"']+/bank_details\b)",
    re.IGNORECASE,
)


def main() -> int:
    skill = os.getenv("IAF_SKILL_NAME", "?")
    tool = os.getenv("IAF_TOOL_NAME", "?")
    trace = os.getenv("IAF_TRACE_ID", "?")[:8]
    tool_input = os.getenv("IAF_TOOL_INPUT", "")
    match = DESTRUCTIVE.search(tool_input)

    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} HOOK_C fired\n")

    if match:
        # External hook contract: exit non-zero to block.
        logger.debug(json.dumps({
            "reason": (
                f"L3 Hook C (skill-agnostic URL guard) denied destructive "
                f"endpoint {match.group(0)!r} — requires explicit HITL approval"
            ),
        }))
        return 1

    logger.debug(json.dumps({"blocked": False}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sys.exit(main())
