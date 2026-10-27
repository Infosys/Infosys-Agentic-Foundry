"""Read-only smoke probes for an explicitly isolated running recovery cell."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ISOLATION_CONFIRMATION = "isolated-recovery-cell"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def _redis_endpoint(value: str) -> tuple[str, int]:
    parsed = urlparse(value)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("Recovery and production Redis URLs must be valid redis:// or rediss:// URLs")
    default_port = 6380 if parsed.scheme == "rediss" else 6379
    return parsed.hostname.lower(), parsed.port or default_port


def validate_live_isolation(
    *,
    base_url: str,
    recovery_redis_url: str,
    production_redis_url: str,
    confirmation: str,
) -> str:
    """Validate opt-in and endpoint separation without returning credentials."""
    if confirmation != ISOLATION_CONFIRMATION:
        raise ValueError(
            f"RECOVERY_LIVE_CONFIRMATION must equal '{ISOLATION_CONFIRMATION}'"
        )
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("RECOVERY_LIVE_BASE_URL must be a valid HTTP(S) URL")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "RECOVERY_LIVE_BASE_URL must be an origin without credentials, path, query, or fragment"
        )
    recovery_endpoint = _redis_endpoint(recovery_redis_url)
    production_endpoint = _redis_endpoint(production_redis_url)
    if recovery_endpoint == production_endpoint:
        raise ValueError("Recovery Redis must use a different host or port from production Redis")
    return base_url.rstrip("/") + "/"


def _fetch(
    base_url: str,
    path: str,
    *,
    token: str,
    timeout_seconds: float,
) -> tuple[int, bytes, str]:
    request = Request(urljoin(base_url, path.lstrip("/")), method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with _OPENER.open(request, timeout=timeout_seconds) as response:
            return (
                int(response.status),
                response.read(2 * 1024 * 1024),
                response.headers.get("Content-Type", ""),
            )
    except HTTPError as exc:
        return int(exc.code), exc.read(64 * 1024), exc.headers.get("Content-Type", "")
    except (URLError, TimeoutError, OSError) as exc:
        message = str(exc.reason if isinstance(exc, URLError) else exc)
        return 0, json.dumps({"error": message}).encode("utf-8"), "application/json"


def _json_get(
    base_url: str,
    path: str,
    *,
    token: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    status, payload, _content_type = _fetch(
        base_url,
        path,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    try:
        body = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


def run_live_probes(
    *,
    base_url: str,
    recovery_redis_url: str,
    production_redis_url: str,
    confirmation: str,
    tenant_id: str,
    token: str = "",
    timeout_seconds: float = 5.0,
    drill_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run non-mutating HTTP probes against a pre-started isolated cell."""
    base = validate_live_isolation(
        base_url=base_url,
        recovery_redis_url=recovery_redis_url,
        production_redis_url=production_redis_url,
        confirmation=confirmation,
    )
    timeout = max(0.5, min(float(timeout_seconds), 30.0))
    results: list[dict[str, Any]] = []

    def add(check_id: str, label: str, status: str, message: str, **evidence: Any) -> None:
        results.append({
            "id": check_id,
            "label": label,
            "status": status,
            "message": message,
            "evidence": evidence,
        })

    live_status, _ = _json_get(base, "/health/live", token=token, timeout_seconds=timeout)
    ready_status, ready = _json_get(base, "/health/ready", token=token, timeout_seconds=timeout)
    healthy = live_status == 200 and ready_status == 200 and ready.get("status") == "ready"
    add(
        "runtime_api",
        "Recovery API liveness and readiness",
        "pass" if healthy else "fail",
        f"Liveness HTTP {live_status}; readiness HTTP {ready_status}",
        liveness_status=live_status,
        readiness_status=ready_status,
        readiness=ready.get("status"),
    )

    query = urlencode({"tenant_id": tenant_id, "limit": 1})
    knowledge_status, knowledge = _json_get(
        base, f"/api/knowledge?{query}", token=token, timeout_seconds=timeout
    )
    add(
        "runtime_auth",
        "Login token, tenant authorization and knowledge read",
        "pass" if knowledge_status == 200 else "fail",
        f"Authenticated tenant knowledge read returned HTTP {knowledge_status}",
        http_status=knowledge_status,
        visible_records=len(knowledge.get("items", knowledge.get("records", [])) or []),
    )

    data_results: dict[str, int] = {}
    for name, path in (
        ("conversations", f"/api/conversations?{query}"),
        ("workstreams", f"/api/workstreams?{urlencode({'tenant_id': tenant_id})}"),
    ):
        status, _body = _json_get(base, path, token=token, timeout_seconds=timeout)
        data_results[name] = status
    add(
        "runtime_data_read",
        "Conversation and workstream reads",
        "pass" if all(status == 200 for status in data_results.values()) else "fail",
        ", ".join(f"{name}=HTTP {status}" for name, status in data_results.items()),
        endpoints=data_results,
    )

    files_status, files_body = _json_get(
        base,
        f"/api/files?{urlencode({'tenant_id': tenant_id, 'path': '/shared/'})}",
        token=token,
        timeout_seconds=timeout,
    )
    file_rows = files_body.get("files", []) if files_status == 200 else []
    serve_url = next(
        (row.get("serve_url") for row in file_rows if row.get("type") == "file" and row.get("serve_url")),
        None,
    )
    if serve_url:
        serve_status, _payload, _content_type = _fetch(
            base, str(serve_url), token=token, timeout_seconds=timeout
        )
        add(
            "signed_files",
            "Signed file and evidence rendering",
            "pass" if serve_status == 200 else "fail",
            f"Signed restored file returned HTTP {serve_status}",
            list_status=files_status,
            serve_status=serve_status,
        )
    else:
        add(
            "signed_files",
            "Signed file and evidence rendering",
            "warning" if files_status == 200 else "fail",
            "No restored /shared file was available for a signed download probe",
            list_status=files_status,
        )

    scheduler_status, scheduler = _json_get(
        base, "/api/cron/status", token=token, timeout_seconds=timeout
    )
    add(
        "scheduler_leader",
        "Single scheduler leader after restore",
        "warning" if scheduler_status == 200 else "fail",
        (
            "Scheduler status is readable; leader uniqueness requires candidate process logs"
            if scheduler_status == 200
            else f"Scheduler status returned HTTP {scheduler_status}"
        ),
        http_status=scheduler_status,
        running=scheduler.get("running", scheduler.get("is_running")),
    )

    queue_status, queue = _json_get(
        base, "/api/queue/metrics", token=token, timeout_seconds=timeout
    )
    add(
        "queue_resume",
        "Queue resumes without duplicate processing",
        "warning" if queue_status == 200 else "fail",
        (
            "Queue metrics are readable; use the drill-prefixed canary to prove exactly-once processing"
            if queue_status == 200
            else f"Queue metrics returned HTTP {queue_status}"
        ),
        http_status=queue_status,
        processor_online=queue.get("processor_online"),
    )
    if drill_evidence:
        from shared.recovery_verifier import _drill_evidence_checks, sanitize_drill_evidence

        evidence = sanitize_drill_evidence(drill_evidence)
        drill_checks, _measurements = _drill_evidence_checks(evidence)
        replacements = {row["id"]: row for row in drill_checks}
        results = [replacements.pop(row["id"], row) for row in results]
        results.extend(replacements.values())
    return results
