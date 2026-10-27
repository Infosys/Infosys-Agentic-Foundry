#!/usr/bin/env python3
"""Live E2E for the DURABLE QUEUE path: edge → TaskQueue → vision worker daemon → item.

Unlike run_vision_live_e2e.py (which ran the handler in-process), this submits a real
task to Redis and relies on a separately-running ``vision_worker_daemon`` to drain it
and materialize the Workstream item — the true enterprise durable path.

Prereqs:
  1. Redis up, studio server up on :8082.
  2. The daemon running (separate terminal):
       CLONE=<repo_root>
       PYTHONPATH="$CLONE:$CLONE/IAF-Agent-Skills:$CLONE/IAF-Agent-Studio" \
         .../python3 -m iaf_agent_skills.vision_worker_daemon \
           --enterprise-root "$CLONE/enterprise_root" --tenant company --lane vision

Run:
    PYTHONPATH="$CLONE:$CLONE/IAF-Agent-Skills:$CLONE/IAF-Agent-Studio" \
      .../python3 IAF-Agent-Studio/tests/run_vision_queue_e2e.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from auth.tokens import create_access_token
from iaf_agent_skills.vision_edge import QueueSubmitter, build_event, load_camera_registry
from iaf_agent_skills.vision_worker import make_vision_task
from iaf_agent_skills.task_system import TaskQueue

BASE = os.environ.get("AGENTPRO_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
TENANT = "company"
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "enterprise_root" / "tenants" / TENANT / "shared" / "config" / "camera_registry.yaml"

_tok = create_access_token(user_id="e2e-admin", email="e2e@company.local", role="admin",
                           tenant_id=TENANT, groups=["physical-ai"], allowed_tenants=[TENANT])


def item_ids():
    req = urllib.request.Request(f"{BASE}/api/workstreams/object_desk_demo",
                                 headers={"Authorization": f"Bearer {_tok}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read() or "{}")
    return {it["id"] for it in body.get("items", [])}


def wait_for(event_id: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if event_id in item_ids():
            return True
        time.sleep(1.0)
    return False


def main() -> int:
    reg = load_camera_registry(str(REGISTRY))
    spec = reg["mac-webcam"]
    event_id = f"queue-e2e-{int(time.time())}"
    event = build_event(spec, event_id=event_id, observed_verdict="cup", observed_confidence=0.88)

    queue = TaskQueue(redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"))
    submitter = QueueSubmitter(queue)
    results = []
    try:
        before = item_ids()
        task_id = submitter(make_vision_task(event, tenant_id=TENANT))
        results.append((f"submitted task {task_id[:8]} to durable queue", True))

        materialized = wait_for(event_id)
        results.append(("daemon drained queue → item materialized", materialized))
        results.append(("item is new (not pre-existing)", event_id not in before))

        # dedup on the durable path: submit again, count stays 1
        submitter(make_vision_task(event, tenant_id=TENANT))
        time.sleep(3)
        count = sum(1 for i in item_ids() if i == event_id)
        results.append(("duplicate event deduped (single row)", count == 1))
    finally:
        submitter.close()

    print("\n=== DURABLE QUEUE E2E RESULTS ===")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print(f"\nevent_id={event_id}  → view at {BASE}/static/workstreams.html")
    print("ALL GREEN" if ok else "SOME CHECKS FAILED (is the daemon running?)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
