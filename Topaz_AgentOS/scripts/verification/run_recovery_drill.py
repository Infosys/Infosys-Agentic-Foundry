#!/usr/bin/env python3
"""Collect live recovery drill evidence from an isolated AgentPro recovery cell."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


def _request(
    method: str,
    base_url: str,
    path: str,
    *,
    token: str = "",
    api_key: str = "",
    body: dict | None = None,
    timeout: float = 10,
) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied recovery URL
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw[:500]}
        return int(exc.code), payload
    except (URLError, TimeoutError, OSError) as exc:
        return 0, {"error": str(getattr(exc, "reason", exc))}


def _list_queue_items(base_url: str, token: str, tenant_id: str, run_id: str, timeout: float) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        query = urlencode({"page": page, "limit": 100})
        status, payload = _request("GET", base_url, f"/api/queue/items?{query}", token=token, timeout=timeout)
        if status != 200:
            break
        batch = [
            item for item in payload.get("items", [])
            if str(item.get("tenant_id") or tenant_id) == tenant_id
            and str(item.get("external_id") or "").startswith(f"drill:{run_id}:")
        ]
        items.extend(batch)
        if page >= int(payload.get("pages") or 1):
            break
        page += 1
    return items


def _queue_canary(args, run_id: str) -> dict:
    if args.skip_queue_canary:
        status, metrics = _request("GET", args.api_url, "/api/queue/metrics", token=args.token, timeout=args.timeout)
        return {
            "run_id": run_id,
            "expected_items": 0,
            "observed_items": 0,
            "terminal_items": 0,
            "duplicate_completed_items": 0,
            "stale_claims": int(metrics.get("stale_claims") or 0) if status == 200 else None,
            "processor_online": metrics.get("processor_online"),
            "workers_online": metrics.get("workers_online"),
            "metrics_status": status,
        }

    for index in range(args.queue_count):
        body = {
            "tenant_id": args.tenant_id,
            "external_id": f"drill:{run_id}:{index:04d}",
            "domain": "itops",
            "entity_id": "",
            "priority": "P3",
            "title": f"Recovery drill canary {index:04d}",
            "description": "Recovery drill queue canary. Use only against an isolated recovery cell.",
        }
        status, payload = _request(
            "POST",
            args.api_url,
            "/api/queue/ingest",
            token=args.token,
            api_key=args.queue_api_key,
            body=body,
            timeout=args.timeout,
        )
        if status not in {200, 201}:
            return {
                "run_id": run_id,
                "expected_items": args.queue_count,
                "observed_items": index,
                "terminal_items": 0,
                "duplicate_completed_items": 0,
                "stale_claims": None,
                "processor_online": None,
                "ingest_error": payload,
                "ingest_status": status,
            }

    deadline = time.time() + args.queue_timeout_seconds
    terminal_statuses = {"done", "failed"}
    items: list[dict] = []
    while time.time() < deadline:
        items = _list_queue_items(args.api_url, args.token, args.tenant_id, run_id, args.timeout)
        terminal = sum(1 for item in items if item.get("status") in terminal_statuses)
        if len(items) >= args.queue_count and terminal >= args.queue_count:
            break
        time.sleep(max(1, args.poll_seconds))

    duplicate_ids: list[str] = []
    for item in items:
        status, detail = _request(
            "GET",
            args.api_url,
            f"/api/queue/items/{item['id']}",
            token=args.token,
            timeout=args.timeout,
        )
        if status != 200:
            continue
        completed = [
            entry for entry in detail.get("executions", [])
            if (entry.get("execution") or {}).get("status") == "completed"
        ]
        if len(completed) > 1:
            duplicate_ids.append(str(item["id"]))

    metrics_status, metrics = _request("GET", args.api_url, "/api/queue/metrics", token=args.token, timeout=args.timeout)
    terminal = sum(1 for item in items if item.get("status") in terminal_statuses)
    return {
        "run_id": run_id,
        "expected_items": args.queue_count,
        "observed_items": len(items),
        "terminal_items": terminal,
        "duplicate_completed_items": len(duplicate_ids),
        "duplicate_item_ids": duplicate_ids,
        "stale_claims": int(metrics.get("stale_claims") or 0) if metrics_status == 200 else None,
        "processor_online": metrics.get("processor_online"),
        "workers_online": metrics.get("workers_online"),
        "workers_expected": metrics.get("workers_expected"),
        "metrics_status": metrics_status,
    }


def collect_evidence(args) -> dict:
    run_id = args.run_id or uuid.uuid4().hex[:10]
    started = time.time()
    evidence: dict = {
        "schema_version": "agentpro.recovery_drill_evidence.v1",
        "evidence_id": f"drill_{run_id}",
        "drill_id": run_id,
        "tenant_id": args.tenant_id,
        "root_id": args.root_id,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    scheduler_status, scheduler = _request("GET", args.api_url, "/api/cron/status", token=args.token, timeout=args.timeout)
    running = bool(scheduler.get("running", scheduler.get("is_running"))) if scheduler_status == 200 else False
    evidence["scheduler_leader"] = {
        "active_leaders": args.active_leaders if args.active_leaders is not None else (1 if running else 0),
        "candidates_observed": args.scheduler_candidates_observed,
        "leader_ids": [args.scheduler_leader_id] if args.scheduler_leader_id else [],
        "status_http": scheduler_status,
        "running": running,
    }

    files_status, files = _request(
        "GET",
        args.api_url,
        f"/api/files?{urlencode({'tenant_id': args.tenant_id, 'path': '/shared/'})}",
        token=args.token,
        timeout=args.timeout,
    )
    serve_url = next(
        (
            row.get("serve_url") for row in files.get("files", [])
            if row.get("type") == "file" and row.get("serve_url")
        ),
        None,
    )
    serve_status = None
    if serve_url:
        serve_status, _payload = _request("GET", args.api_url, str(serve_url), token=args.token, timeout=args.timeout)
    evidence["signed_files"] = {
        "list_status": files_status,
        "serve_status": serve_status,
        "file_available": bool(serve_url),
    }

    evidence["queue_resume"] = _queue_canary(args, run_id)
    elapsed_minutes = max(0.0, (time.time() - started) / 60)
    evidence["slo"] = {
        "service_rto_minutes": args.service_rto_minutes if args.service_rto_minutes is not None else elapsed_minutes,
        "load_p95_ms": args.load_p95_ms,
        "failover_recovery_seconds": args.failover_recovery_seconds,
        "error_rate": args.error_rate,
    }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="Isolated recovery cell origin")
    parser.add_argument("--token", default="", help="Bearer token for recovery-cell API reads")
    parser.add_argument("--queue-api-key", default="", help="QUEUE_INGEST_API_KEY for queue canary ingest")
    parser.add_argument("--tenant-id", default="company")
    parser.add_argument("--root-id", default="configured_restore")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--queue-count", type=int, default=1)
    parser.add_argument("--queue-timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--skip-queue-canary", action="store_true")
    parser.add_argument("--active-leaders", type=int)
    parser.add_argument("--scheduler-candidates-observed", type=int, default=1)
    parser.add_argument("--scheduler-leader-id", default="")
    parser.add_argument("--service-rto-minutes", type=float)
    parser.add_argument("--load-p95-ms", type=float)
    parser.add_argument("--failover-recovery-seconds", type=float)
    parser.add_argument("--error-rate", type=float)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--submit", action="store_true", help="Submit evidence to /api/recovery-readiness/evidence")
    parser.add_argument("--verify", action="store_true", help="Run recovery verification with submitted evidence")
    args = parser.parse_args()

    evidence = collect_evidence(args)
    text = json.dumps(evidence, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.submit:
        status, payload = _request(
            "POST",
            args.api_url,
            "/api/recovery-readiness/evidence",
            token=args.token,
            body={"tenant_id": args.tenant_id, "root_id": args.root_id, "evidence": evidence},
            timeout=args.timeout,
        )
        if status not in {200, 201}:
            raise SystemExit(f"evidence submit failed: HTTP {status} {payload}")
        print(json.dumps({"submitted_evidence_id": payload.get("evidence_id")}, sort_keys=True))
        if args.verify:
            verify_status, verify_payload = _request(
                "POST",
                args.api_url,
                "/api/recovery-readiness/verify",
                token=args.token,
                body={
                    "tenant_id": args.tenant_id,
                    "root_id": args.root_id,
                    "evidence_id": payload.get("evidence_id"),
                },
                timeout=args.timeout,
            )
            if verify_status not in {200, 201}:
                raise SystemExit(f"verification failed: HTTP {verify_status} {verify_payload}")
            print(json.dumps({"report_id": verify_payload.get("report_id"), "status": verify_payload.get("status")}, sort_keys=True))
    elif args.verify:
        raise SystemExit("--verify requires --submit so the API can reference the sanitized evidence id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
