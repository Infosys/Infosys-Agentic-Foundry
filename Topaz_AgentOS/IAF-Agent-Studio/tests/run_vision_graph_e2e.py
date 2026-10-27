#!/usr/bin/env python3
"""Live graph run: materialized item → object_desk_demo_graph → real vision verdict.

Ensures the item whose frame exists (graph-demo-1) is the one that runs, triggers
a synchronous run_now, and prints the run result + item trace so we can see the
actual classify → verify → record/escalate outcome.

Prereqs: server :8082, Redis, and the edge appliance on :8799 all up.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from auth.tokens import create_access_token

BASE = os.environ.get("AGENTPRO_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
TENANT = "company"
WS = "object_desk_demo"
EVENT = os.environ.get("VISION_EVENT_ID", "graph-demo-1")  # a real frame must exist for this id

_tok = create_access_token(user_id="e2e-admin", email="e2e@company.local", role="admin",
                           tenant_id=TENANT, groups=["physical-ai"], allowed_tenants=[TENANT])


def api(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {_tok}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        b = e.read().decode()
        try:
            return e.code, json.loads(b) if b else {}
        except json.JSONDecodeError:
            return e.code, {"raw": b[:300]}


def main():
    # 1) ensure our phone-frame item exists
    s, _ = api("POST", f"/api/workstreams/{WS}/items", {
        "id": EVENT,
        "description": f"[vision] camera=mac-webcam frame=graph-demo-1\nQ: What object is being held up?\noptions: phone | cup | eyeglasses | nothing",
        "acceptance_criteria": ["The object is clearly visible.", "A verifier confirms the object."],
    })
    print(f"create item {EVENT}: {s}")

    # 1b) reset it to pending (in case a prior run left it failed)
    api("POST", f"/api/workstreams/{WS}/items/{EVENT}/retry")

    # 2) skip every OTHER pending item so run_now picks graph-demo-1
    s, ws = api("GET", f"/api/workstreams/{WS}")
    for it in ws.get("items", []):
        if it["id"] != EVENT and it.get("status") in ("pending", "in_progress"):
            api("POST", f"/api/workstreams/{WS}/items/{it['id']}/skip")
    print("other pending items skipped")

    # 3) run it synchronously
    print("running graph (this loads the warm agent + calls the edge)…")
    t0 = time.time()
    s, res = api("POST", f"/api/workstreams/{WS}/run", {"count": 1, "parallel": 1})
    print(f"run status {s} in {time.time()-t0:.0f}s")
    print(json.dumps(res, indent=2)[:1500])

    # 4) read the item's final state + trace
    s, ws = api("GET", f"/api/workstreams/{WS}")
    item = next((it for it in ws.get("items", []) if it["id"] == EVENT), None)
    if item:
        print("\n=== ITEM FINAL STATE ===")
        print("status:", item.get("status"))
        print("resolution:", str(item.get("resolution"))[:300])
        for row in (item.get("execution_ledger") or [])[-6:]:
            print("  ledger:", str(row)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
