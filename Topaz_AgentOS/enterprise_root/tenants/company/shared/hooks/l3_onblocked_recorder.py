#!/usr/bin/env python3
"""
L3 test — OnBlocked observer.

Fires AFTER any blocking-capable hook denies. Records every deny to
/tmp/l3_audit.log so we can verify the single OnBlocked seam catches
denies from Hook B, Hook C, the fail_policy=closed timeout path, and
the Batch 1 credential fail-closed gate — without us having to wrap
each of those individually.
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
    trace = os.getenv("IAF_TRACE_ID", "?")[:8]
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        ctx = json.loads(raw) if raw else {}
    except Exception:
        ctx = {}

    blocked_event = ctx.get("blocked_event") or os.getenv("IAF_BLOCKED_EVENT", "?")
    blocked_hook_id = ctx.get("blocked_hook_id") or os.getenv("IAF_BLOCKED_HOOK_ID", "?")
    blocked_reason = (ctx.get("blocked_reason") or os.getenv("IAF_BLOCKED_REASON", "?"))[:160]

    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} ON_BLOCKED fired\n")

    # OnBlocked is observe-only — return value is ignored, but be polite.
    logger.debug(json.dumps({"blocked": False}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sys.exit(main())
