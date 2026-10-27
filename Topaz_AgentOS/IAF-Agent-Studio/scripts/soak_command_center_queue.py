#!/usr/bin/env python3
"""Run a staging Command Center queue soak against the REST API."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _request(method: str, base_url: str, path: str, *, api_key: str = "", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = Request(f"{base_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - operator-supplied staging URL
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def _list_soak_items(base_url: str, tenant_id: str, run_id: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        query = urlencode({"page": page, "limit": 100})
        payload = _request("GET", base_url, f"/api/queue/items?{query}")
        batch = [
            item for item in payload.get("items", [])
            if str(item.get("tenant_id") or tenant_id) == tenant_id
            and str(item.get("external_id") or "").startswith(f"soak:{run_id}:")
        ]
        items.extend(batch)
        if page >= int(payload.get("pages") or 1):
            return items
        page += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="Staging API base URL")
    parser.add_argument("--api-key", default="", help="QUEUE_INGEST_API_KEY for /api/queue/ingest")
    parser.add_argument("--tenant-id", default="company")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:10])
    args = parser.parse_args()

    print(f"[queue-soak] run_id={args.run_id} count={args.count}")
    for index in range(args.count):
        external_id = f"soak:{args.run_id}:{index:04d}"
        _request(
            "POST",
            args.api_url,
            "/api/queue/ingest",
            api_key=args.api_key,
            body={
                "tenant_id": args.tenant_id,
                "external_id": external_id,
                "domain": "itops",
                "entity_id": "",
                "priority": "P3",
                "title": f"Queue soak item {index:04d}",
                "description": "Staging queue soak verification item. Use an idempotent test skill or router fixture.",
            },
        )
    print("[queue-soak] ingested items; optionally terminate one queue worker now for failover injection")

    deadline = time.time() + args.timeout_seconds
    terminal = {"done", "failed"}
    while time.time() < deadline:
        items = _list_soak_items(args.api_url, args.tenant_id, args.run_id)
        statuses = {item.get("status") for item in items}
        done = sum(1 for item in items if item.get("status") in terminal)
        print(f"[queue-soak] observed={len(items)} terminal={done}/{args.count} statuses={sorted(statuses)}")
        if len(items) >= args.count and done >= args.count:
            break
        time.sleep(max(1, args.poll_seconds))
    else:
        raise SystemExit("[queue-soak] timeout waiting for terminal queue items")

    duplicate_completed = []
    for item in _list_soak_items(args.api_url, args.tenant_id, args.run_id):
        detail = _request("GET", args.api_url, f"/api/queue/items/{item['id']}")
        completed = [
            entry for entry in detail.get("executions", [])
            if (entry.get("execution") or {}).get("status") == "completed"
        ]
        if len(completed) > 1:
            duplicate_completed.append(item["id"])
    if duplicate_completed:
        raise SystemExit(f"[queue-soak] duplicate completed executions: {duplicate_completed}")

    metrics = _request("GET", args.api_url, "/api/queue/metrics")
    print(f"[queue-soak] metrics={json.dumps(metrics, sort_keys=True)}")
    if int(metrics.get("stale_claims") or 0) > 0:
        raise SystemExit("[queue-soak] stale claims remain after soak")
    print("[queue-soak] passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
