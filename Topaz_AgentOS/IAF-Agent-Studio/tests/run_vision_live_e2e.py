#!/usr/bin/env python3
"""Live E2E: camera event → our vision pipeline → real Workstream item (visible in UI).

Exercises the REAL enterprise code against the running server + tenant tree:
  vision_edge.build_event  →  make_vision_task  →  VisionEventHandler.execute
    →  make_platform_entitlement_check (vision_allowed policy, enforced live)
    →  WorkstreamStore.append_item (real YAML)  →  visible via GET /api/workstreams

Prereqs: server up on :8082 (agentosrlm restart) with Redis. No edge appliance
needed — this proves the materialization path (graph execution is a separate step
that needs the /decide edge on :8799).

Run:
    cd IAF_AgentOS_Harness_rlm
    PYTHONPATH="$PWD:$PWD/IAF-Agent-Skills:$PWD/IAF-Agent-Studio" \
      <venv>/bin/python3 \
      IAF-Agent-Studio/tests/run_vision_live_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from auth.tokens import create_access_token
from iaf_agent_skills.vision_edge import build_event, load_camera_registry
from iaf_agent_skills.vision_worker import (
    VisionEventHandler,
    make_platform_entitlement_check,
    make_vision_task,
)
from iaf_agent_skills.workstream_store import WorkstreamStore

BASE = os.environ.get("AGENTPRO_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
TENANT = "company"
ROOT = Path(__file__).resolve().parents[2]
TENANT_ROOT = ROOT / "enterprise_root" / "tenants" / TENANT
REGISTRY = TENANT_ROOT / "shared" / "config" / "camera_registry.yaml"
WS = "object_desk_demo"

_tok = create_access_token(user_id="e2e-admin", email="e2e@company.local", role="admin",
                           tenant_id=TENANT, groups=["physical-ai"], allowed_tenants=[TENANT])


def api(method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {_tok}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return e.code, {"raw": body[:300]}


def item_ids():
    s, body = api("GET", f"/api/workstreams/{WS}")
    assert s == 200, f"GET workstream failed: {s} {body}"
    return {it["id"] for it in body.get("items", [])}


def main():
    results = []

    # 1) server loaded our tenant content
    s, body = api("GET", "/api/workstreams")
    names = {w.get("name") for w in (body.get("workstreams") if isinstance(body, dict) else body)}
    assert WS in names, f"{WS} not loaded"
    results.append(("workstream loaded", True))

    # 2) vision_allowed policy enforced live (allow path via service principal)
    check = make_platform_entitlement_check(TENANT)
    reg = load_camera_registry(str(REGISTRY))
    spec = reg["mac-webcam"]
    event_id = f"e2e-live-{int(time.time())}"
    event = build_event(spec, event_id=event_id, observed_verdict="phone", observed_confidence=0.91)
    allowed, reason = check(_Evt(event))
    results.append(("vision_allowed enforced (allow)", allowed is True))

    # 3) save a frame where the graph would read it (optional realism)
    frame = TENANT_ROOT / "shared" / "frames" / WS / f"{event_id}.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"\xff\xd8\xff\xe0stub-jpeg")  # placeholder; real sensor writes a real frame

    # 4) OUR worker handler → real WorkstreamStore
    handler = VisionEventHandler(
        tenant_root_resolver=lambda t: TENANT_ROOT,
        entitlement_check=check,
    )
    before = item_ids()
    task = make_vision_task(event, tenant_id=TENANT)
    res = asyncio.run(handler.execute(task))
    materialized = res.output["outcome"] == "materialized" and res.output["materialized"]
    results.append(("handler materialized item", materialized))

    # 5) item visible via the API (Workstreams UI surface)
    after = item_ids()
    results.append(("item visible in workstream API", event_id in after and event_id not in before))

    # 6) idempotency: same event again → deduped, no second row
    res2 = asyncio.run(handler.execute(make_vision_task(event, tenant_id=TENANT)))
    deduped = res2.output["outcome"] == "deduped" and item_ids() == after
    results.append(("duplicate event deduped", deduped))

    print("\n=== LIVE E2E RESULTS ===")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print(f"\nevent_id={event_id}  → view at {BASE}/static/workstreams.html")
    print("ALL GREEN" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


class _Evt:
    """Adapts the event dict to the .workstream attribute the check reads."""
    def __init__(self, d: dict):
        self.workstream = d["workstream"]


if __name__ == "__main__":
    raise SystemExit(main())
