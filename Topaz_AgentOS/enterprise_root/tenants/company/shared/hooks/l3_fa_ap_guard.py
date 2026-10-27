#!/usr/bin/env python3
"""
L3 test — Hook B: skill-scoped (fa_ap, fa_ap_admin) blocking guard.

Demonstrates the `skills:` filter. This hook ONLY fires when the active
skill is fa_ap or fa_ap_admin. It denies any tool call whose tool_input
contains a forbidden destructive SQL keyword:

    DROP TABLE | TRUNCATE | DELETE FROM | UPDATE * SET

If it fires for any other skill (general, ccdops, fa_ar, …) the
`skills:` filter is broken — the test will catch that as a failure.
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

FORBIDDEN = re.compile(
    r"\b(DROP\s+TABLE|TRUNCATE\s+TABLE|DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b",
    re.IGNORECASE,
)


def main() -> int:
    skill = os.getenv("IAF_SKILL_NAME", "?")
    trace = os.getenv("IAF_TRACE_ID", "?")[:8]
    tool_input = os.getenv("IAF_TOOL_INPUT", "")
    match = FORBIDDEN.search(tool_input)

    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} HOOK_B fired\n")

    if match:
        # External hook contract: exit non-zero to block; stdout JSON's
        # `reason` field is parsed for the audit message.
        logger.debug(json.dumps({
            "reason": (
                f"L3 Hook B (skill-scoped: fa_ap) denied destructive SQL — "
                f"matched pattern: {match.group(0)!r}"
            ),
        }))
        return 1

    logger.debug(json.dumps({"blocked": False}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sys.exit(main())
