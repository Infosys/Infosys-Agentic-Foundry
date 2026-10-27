#!/usr/bin/env python3
"""
Hook 3 — PostToolUse: Alert when critical Kubernetes conditions appear in tool output.

Fires after every shell tool call completes. Scans the output for known
Kubernetes failure signatures. If found, appends an alert line to
/tmp/ccdops_alerts.log.

In production: replace the file write with a Slack/PagerDuty POST.
For testing: tail -f /tmp/ccdops_alerts.log while chatting.

Alert triggers:
  OOMKilled          →  pod killed by kernel OOM
  CrashLoopBackOff   →  container keeps crashing and restarting
  Error              →  general error in pod output / events
  NotReady           →  pod or node not ready
  ImagePullBackOff   →  container image cannot be pulled
  Evicted            →  pod evicted from node (usually disk/memory pressure)
  Pending (stuck)    →  pod not scheduled

Always exits 0 (fire-and-forget, never blocks the agent).

Verify:
    tail -f /tmp/ccdops_alerts.log
"""

import os
import re
import sys
import tempfile
from datetime import datetime

import logging
logger = logging.getLogger(__name__)

ALERT_FILE = os.path.join(tempfile.gettempdir(), "ccdops_alerts.log")

ALERT_PATTERNS = {
    "OOMKilled":        "Pod killed by kernel OOM — memory limit likely too low",
    "CrashLoopBackOff": "Container crash-looping — check logs for root cause",
    "ImagePullBackOff": "Image pull failing — check registry access or image tag",
    "ErrImagePull":     "Image pull error — check registry credentials",
    "Evicted":          "Pod evicted — node under disk or memory pressure",
    r"\bNotReady\b":    "Pod or node NotReady — check kubelet and node conditions",
    r"\bError\b":       "Error reported in tool output — review investigation",
}

tool_output = os.environ.get("IAF_TOOL_OUTPUT", "")
tool_name   = os.environ.get("IAF_TOOL_NAME", "")
session_id  = os.environ.get("IAF_SESSION_ID", "")
skill_name  = os.environ.get("IAF_SKILL_NAME", "")

triggered = []
for pattern, description in ALERT_PATTERNS.items():
    if re.search(pattern, tool_output, re.IGNORECASE):
        triggered.append(f"{pattern} → {description}")

if triggered:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append(f"[{ts}] CCD OPS ALERT")
    for t in triggered:
        lines.append(f"    {t}")
    lines.append("")

    try:
        with open(ALERT_FILE, "a") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        logger.debug(f"alert write failed: {e}")

sys.exit(0)
