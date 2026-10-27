"""Dashboard V2 operations summary composition.

This module keeps the command-center overview contract in one place. It composes
existing Studio capabilities and adapters into a bounded read-only summary for
Dashboard V2 without creating a separate control-plane subsystem.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
import time
from collections.abc import Callable
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


Provider = Callable[[], Any]

_SEVERITY_RANK = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4, "info": 5}
_TYPE_RANK = {
    "approval": 0,
    "queue": 1,
    "workstream": 2,
    "cron": 3,
    "system": 4,
    "error": 5,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value: Any, limit: int = 140) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    data: dict[str, Any] = {}
    for key in ("id", "reason", "urgency", "created_at", "user_id", "agent_id", "tenant_id", "skill"):
        if hasattr(value, key):
            data[key] = getattr(value, key)
    return data


def build_trace_finops_provider(
    db_path: str | Path,
    *,
    tenant_id: str,
    period_days: int = 7,
) -> Callable[[], dict[str, Any]]:
    """Return a provider that summarizes trace token/cost data from SQLite."""
    db_path = Path(db_path)
    bounded_period_days = max(1, min(int(period_days), 90))

    def provider() -> dict[str, Any]:
        empty = {
            "total_cost_usd": 0.0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_requests": 0,
            "avg_cost_per_request": 0.0,
        }
        if not db_path.exists():
            return empty

        since = (datetime.now(timezone.utc) - timedelta(days=bounded_period_days)).isoformat()
        with _sqlite_connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(cost_usd), 0),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0),
                    COUNT(*)
                FROM traces
                WHERE tenant = ? AND created_at >= ?
                """,
                (tenant_id, since),
            ).fetchone()

        total_cost = _safe_float(row[0] if row else 0.0)
        total_requests = _safe_int(row[3] if row else 0)
        return {
            "total_cost_usd": total_cost,
            "total_prompt_tokens": _safe_int(row[1] if row else 0),
            "total_completion_tokens": _safe_int(row[2] if row else 0),
            "total_requests": total_requests,
            "avg_cost_per_request": total_cost / total_requests if total_requests else 0.0,
        }

    return provider


def build_trace_activity_provider(
    emitter: Any, *, tenant_id: str, user_id: str | None = None
) -> Callable[[], dict[str, Any]]:
    """Return a provider for the Control Plane Snapshot's activity counters.

    ``traces_today`` must reflect the LIVE trace store (Postgres when
    ``TRACE_BACKEND=postgres``, SQLite otherwise) — not a hardcoded 0 and not a
    stale on-disk file. It uses the shared ``TraceEmitter`` so it always reads
    whatever backend the running server writes to. ``active_rules`` /
    ``blocked_actions`` / ``policy_decisions_today`` stay 0 until the policy
    subsystem is wired (tracked separately); this provider only makes the
    trace-derived counter honest.

    ``user_id`` scopes the count for non-admin callers: the ops-summary endpoint
    passes the caller's own id for non-admins (``None`` for admins), mirroring
    the trace APIs which pin a non-admin to their own ``user_id``. When set, the
    count is an exact-match (``fuzzy_user=False``) of that user's own traces so a
    regular user's snapshot reflects their activity, not the whole tenant's.
    """

    def provider() -> dict[str, Any]:
        base = {
            "active_rules": 0,
            "blocked_actions": 0,
            "policy_decisions_today": 0,
            "traces_today": 0,
        }
        if emitter is None:
            return base
        # `count_traces` compares created_at >= since as a string; a date-only
        # prefix ("YYYY-MM-DD") captures everything stamped on today's date.
        since = datetime.now().strftime("%Y-%m-%dT00:00:00")
        try:
            base["traces_today"] = _safe_int(emitter.count_traces(
                tenant=tenant_id,
                since=since,
                user_id=user_id or "",
                fuzzy_user=False,
            ))
        except Exception:
            pass
        return base

    return provider


def build_recent_trace_errors_provider(
    emitter: Any, *, tenant_id: str, user_id: str | None = None, limit: int = 10
) -> Callable[[], list[dict[str, Any]]]:
    """Return a provider that surfaces real error traces for Needs Attention.

    Reads the live trace store for the most recent ``status='error'`` traces so
    the Overview stops rendering an always-empty Needs Attention error list.

    ``user_id`` scopes the feed for non-admin callers (``None`` for admins). A
    tenant-only query would leak other users' ``query_preview`` text into the
    Overview title; the trace APIs pin non-admins to their own ``user_id``
    (exact match, ``fuzzy_user=False``), so this provider does the same when the
    endpoint supplies a scoped user (Copilot #1).
    """

    def provider() -> list[dict[str, Any]]:
        if emitter is None:
            return []
        try:
            rows = emitter.query_traces(
                tenant=tenant_id,
                status="error",
                limit=limit,
                user_id=user_id or "",
                fuzzy_user=False,
            ) or []
        except Exception:
            return []
        errors: list[dict[str, Any]] = []
        for row in rows:
            data = _as_dict(row)
            errors.append({
                "title": _bounded_text(
                    data.get("query_preview") or data.get("skill") or "Trace ended in error"
                ),
                "source": _bounded_text(data.get("skill") or data.get("agent") or "trace", 80),
                "severity": "high",
                "created_at": data.get("created_at"),
            })
        return errors

    return provider


def _agent_count(agents: Any) -> int:
    if isinstance(agents, dict):
        return len(agents)
    if isinstance(agents, (list, tuple, set)):
        return len(agents)
    try:
        return len(list(agents))
    except Exception:
        return 0


def _status_counts_from_workstreams(workstreams: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(workstreams),
        "active": 0,
        "completed": 0,
        "failed": 0,
        "awaiting_human": 0,
        "failed_items": 0,
        "total_items": 0,
    }
    for ws in workstreams:
        status = str(ws.get("status") or "").lower()
        if status in {"active", "running", "in_progress"}:
            counts["active"] += 1
        if status in {"completed", "done"}:
            counts["completed"] += 1
        if status == "failed":
            counts["failed"] += 1

        items = ws.get("items")
        if isinstance(items, list):
            counts["total_items"] += len(items)
            counts["awaiting_human"] += sum(1 for item in items if item.get("status") == "awaiting_human")
            counts["failed_items"] += sum(1 for item in items if item.get("status") == "failed")
            continue

        counts["total_items"] += _safe_int(ws.get("items_total") or ws.get("total_items"))
        counts["awaiting_human"] += _safe_int(
            ws.get("items_awaiting_human")
            or ws.get("awaiting_human")
            or ws.get("awaiting_human_items")
        )
        counts["failed_items"] += _safe_int(ws.get("items_failed") or ws.get("failed_items"))
    return counts


@dataclass(slots=True)
class ProviderResult:
    value: Any
    error: str | None = None


class DashboardOpsSummaryService:
    """Compose a bounded operations summary from existing providers."""

    def __init__(
        self,
        *,
        agents_provider: Provider,
        approval_provider: Provider,
        queue_metrics_provider: Provider,
        cron_status_provider: Provider,
        workstreams_provider: Provider,
        finops_provider: Provider,
        recent_errors_provider: Provider,
        rules_provider: Provider,
    ) -> None:
        self.agents_provider = agents_provider
        self.approval_provider = approval_provider
        self.queue_metrics_provider = queue_metrics_provider
        self.cron_status_provider = cron_status_provider
        self.workstreams_provider = workstreams_provider
        self.finops_provider = finops_provider
        self.recent_errors_provider = recent_errors_provider
        self.rules_provider = rules_provider

    async def build(self, *, tenant_id: str, user_id: str | None = None) -> dict[str, Any]:
        # Run all providers concurrently instead of sequentially
        keys = ["agents", "approvals", "queue", "cron", "workstreams", "finops", "recent_errors", "rules"]
        providers = [
            self.agents_provider, self.approval_provider,
            self.queue_metrics_provider, self.cron_status_provider,
            self.workstreams_provider, self.finops_provider,
            self.recent_errors_provider, self.rules_provider,
        ]
        values = await asyncio.gather(*(self._call(k, p) for k, p in zip(keys, providers)))
        results = dict(zip(keys, values))
        degraded_sources = [name for name, result in results.items() if result.error]

        approvals_raw = results["approvals"].value or []
        if isinstance(approvals_raw, dict):
            approvals_raw = approvals_raw.get("approvals") or []
        approvals = [_as_dict(item) for item in approvals_raw]

        queue = self._queue_summary(results["queue"])
        cron = self._cron_summary(results["cron"])
        workstreams = self._workstream_summary(results["workstreams"])
        finops = self._finops_summary(results["finops"])
        rules = self._rules_summary(results["rules"])
        recent_errors = self._recent_errors(results["recent_errors"])

        attention = self._needs_attention(
            approvals=approvals,
            queue=queue,
            cron=cron,
            workstreams=workstreams,
            recent_errors=recent_errors,
            degraded_sources=degraded_sources,
        )
        health = self._health(attention=attention, degraded_sources=degraded_sources)

        return {
            "schema_version": "dashboard_ops_summary.v1",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "generated_at": _now_iso(),
            "health": health,
            "degraded_sources": degraded_sources,
            "active_sessions": _agent_count(results["agents"].value),
            "pending_approvals": len(approvals),
            "queue": queue,
            "cron": cron,
            "workstreams": workstreams,
            "recent_errors": recent_errors,
            "finops": finops,
            "control_plane": {
                "status": health,
                "approvals_pending": len(approvals),
                "blocked_actions": rules.get("blocked_actions", 0),
                "policy_decisions_today": rules.get("policy_decisions_today", 0),
                "traces_today": rules.get("traces_today", 0),
                "rules_active": rules.get("active_rules", 0),
                "queue_failures": queue.get("failed", 0) + queue.get("dlq", 0),
                "paused_actions": queue.get("awaiting_human", 0) + workstreams.get("awaiting_human", 0),
            },
            "needs_attention": attention,
        }

    async def _call(self, name: str, provider: Provider) -> ProviderResult:
        try:
            if inspect.iscoroutinefunction(provider):
                value = await provider()
            else:
                # Run synchronous/blocking providers in a thread
                # so they don't freeze the event loop
                value = await asyncio.to_thread(provider)
            return ProviderResult(value=value)
        except Exception as exc:  # defensive composition boundary for dashboards
            return ProviderResult(value=None, error=f"{name}: {_bounded_text(exc, 180)}")

    def _queue_summary(self, result: ProviderResult) -> dict[str, Any]:
        if result.error:
            return self._degraded_section("queue", result.error, {
                "queued": 0,
                "routing": 0,
                "running": 0,
                "awaiting_human": 0,
                "done": 0,
                "failed": 0,
                "dlq": 0,
                "avg_latency_ms": 0,
                "total_active": 0,
            })
        raw = result.value or {}
        return {
            "status": "ok",
            "queued": _safe_int(raw.get("queued")),
            "routing": _safe_int(raw.get("routing")),
            "running": _safe_int(raw.get("running")),
            "awaiting_human": _safe_int(raw.get("awaiting_human")),
            "done": _safe_int(raw.get("done")),
            "failed": _safe_int(raw.get("failed")),
            "dlq": _safe_int(raw.get("dlq")),
            "avg_latency_ms": _safe_int(raw.get("avg_latency_ms")),
            "total_active": _safe_int(raw.get("total_active")),
            "processor_online": bool(raw.get("processor_online", True)),
            "processor_heartbeat": raw.get("processor_heartbeat"),
            "claim_backend": raw.get("claim_backend", "sqlite"),
            "workers_online": _safe_int(raw.get("workers_online")),
            "workers_expected": _safe_int(raw.get("workers_expected"), 1),
            "stale_claims": _safe_int(raw.get("stale_claims")),
        }

    def _cron_summary(self, result: ProviderResult) -> dict[str, Any]:
        if result.error:
            return self._degraded_section("cron", result.error, {
                "total": 0,
                "enabled": 0,
                "disabled": 0,
                "running": 0,
                "scheduler_running": False,
            })
        raw = result.value or {}
        running = _safe_int(raw.get("active_executions", raw.get("running_jobs")))
        return {
            "status": "ok",
            "total": _safe_int(raw.get("total_jobs")),
            "enabled": _safe_int(raw.get("enabled_jobs")),
            "disabled": _safe_int(raw.get("disabled_jobs")),
            "running": running,
            "scheduler_running": bool(raw.get("running", True)),
        }

    def _workstream_summary(self, result: ProviderResult) -> dict[str, Any]:
        if result.error:
            return self._degraded_section("workstreams", result.error, {
                "total": 0,
                "active": 0,
                "completed": 0,
                "failed": 0,
                "awaiting_human": 0,
                "failed_items": 0,
                "total_items": 0,
            })
        raw = result.value or []
        if isinstance(raw, dict):
            raw = raw.get("workstreams") or []
        workstreams = [item for item in raw if isinstance(item, dict)]
        return {"status": "ok", **_status_counts_from_workstreams(workstreams)}

    def _finops_summary(self, result: ProviderResult) -> dict[str, Any]:
        if result.error:
            return self._degraded_section("finops", result.error, {
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "total_requests": 0,
            })
        raw = result.value or {}
        prompt_tokens = _safe_int(raw.get("total_prompt_tokens"))
        completion_tokens = _safe_int(raw.get("total_completion_tokens"))
        return {
            "status": "ok",
            "total_cost_usd": round(_safe_float(raw.get("total_cost_usd")), 4),
            "total_tokens": prompt_tokens + completion_tokens,
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_requests": _safe_int(raw.get("total_requests") or raw.get("requests")),
            "avg_cost_per_request": round(_safe_float(raw.get("avg_cost_per_request")), 6),
        }

    def _rules_summary(self, result: ProviderResult) -> dict[str, int]:
        if result.error:
            return {"active_rules": 0, "blocked_actions": 0, "policy_decisions_today": 0, "traces_today": 0}
        raw = result.value or {}
        return {
            "active_rules": _safe_int(raw.get("active_rules")),
            "blocked_actions": _safe_int(raw.get("blocked_actions")),
            "policy_decisions_today": _safe_int(raw.get("policy_decisions_today")),
            "traces_today": _safe_int(raw.get("traces_today")),
        }

    def _recent_errors(self, result: ProviderResult) -> list[dict[str, Any]]:
        if result.error:
            return []
        raw = result.value or []
        if isinstance(raw, dict):
            raw = raw.get("errors") or []
        errors = []
        for item in raw[:10]:
            data = _as_dict(item)
            errors.append({
                "title": _bounded_text(data.get("title") or data.get("message") or data.get("error") or "Runtime issue"),
                "source": _bounded_text(data.get("source") or "system", 80),
                "severity": str(data.get("severity") or "medium").lower(),
                "created_at": data.get("created_at") or data.get("timestamp"),
            })
        return errors

    def _needs_attention(
        self,
        *,
        approvals: list[dict[str, Any]],
        queue: dict[str, Any],
        cron: dict[str, Any],
        workstreams: dict[str, Any],
        recent_errors: list[dict[str, Any]],
        degraded_sources: list[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for approval in approvals[:8]:
            urgency = str(approval.get("urgency") or "high").lower()
            severity = "critical" if urgency == "critical" else "high" if urgency == "high" else "warning"
            items.append({
                "type": "approval",
                "severity": severity,
                "title": _bounded_text(approval.get("reason") or approval.get("action_description") or "Approval required"),
                "source": _bounded_text(approval.get("user_id") or approval.get("agent_id") or "HITL", 80),
                "created_at": approval.get("created_at"),
                "action": {"type": "navigate", "page": "approvals"},
            })

        queue_available = queue.get("status") != "degraded"
        cron_available = cron.get("status") != "degraded"
        workstreams_available = workstreams.get("status") != "degraded"

        if queue_available and queue.get("dlq", 0) > 0:
            items.append(self._attention("queue", "critical", f"{queue['dlq']} item(s) in dead-letter queue", "Queue Monitor", "command-center"))
        if queue_available and queue.get("failed", 0) > 0:
            items.append(self._attention("queue", "critical", f"{queue['failed']} failed queue item(s)", "Queue Monitor", "command-center"))
        if queue_available and queue.get("awaiting_human", 0) > 0:
            items.append(self._attention("queue", "high", f"{queue['awaiting_human']} queue item(s) awaiting human input", "Queue Monitor", "command-center"))
        if queue_available and not queue.get("processor_online", True):
            items.append(self._attention("queue", "critical", "Queue processor heartbeat is missing", "Queue Processor", "command-center"))
        if queue_available and queue.get("workers_expected", 1) > 1 and queue.get("workers_online", 0) < queue.get("workers_expected", 1):
            items.append(self._attention("queue", "critical", "One or more queue workers are offline", "Queue Monitor", "command-center"))
        if queue_available and queue.get("stale_claims", 0) > 0:
            items.append(self._attention("queue", "high", f"{queue['stale_claims']} stale queue claim(s)", "Queue Monitor", "command-center"))

        if workstreams_available and workstreams.get("failed_items", 0) > 0:
            items.append(self._attention("workstream", "critical", f"{workstreams['failed_items']} failed workstream item(s)", "Workstreams", "workstreams"))
        if workstreams_available and workstreams.get("awaiting_human", 0) > 0:
            items.append(self._attention("workstream", "critical", f"{workstreams['awaiting_human']} workstream item(s) awaiting approval", "Workstreams", "workstreams"))
        if workstreams_available and workstreams.get("failed", 0) > 0:
            items.append(self._attention("workstream", "critical", f"{workstreams['failed']} failed workstream(s)", "Workstreams", "workstreams"))

        if cron_available and not cron.get("scheduler_running", True):
            items.append(self._attention("cron", "critical", "Cron scheduler is not running", "Cron Jobs", "cron"))
        if cron_available and cron.get("running", 0) > 0:
            items.append(self._attention("cron", "info", f"{cron['running']} cron job(s) currently running", "Cron Jobs", "cron"))

        for err in recent_errors[:5]:
            items.append({
                "type": "error",
                "severity": err.get("severity") or "medium",
                "title": _bounded_text(err.get("title") or "Runtime issue"),
                "source": _bounded_text(err.get("source") or "system", 80),
                "created_at": err.get("created_at"),
                "action": {"type": "navigate", "page": "audit"},
            })

        for source in degraded_sources:
            if source == "recent_errors":
                continue
            items.append(self._attention("system", "warning", f"{source} summary is degraded", source, "overview"))

        items.sort(key=lambda item: (_SEVERITY_RANK.get(item.get("severity", "info"), 9), _TYPE_RANK.get(item.get("type", ""), 9), item.get("title", "")))
        return items[:12]

    def _attention(self, item_type: str, severity: str, title: str, source: str, page: str) -> dict[str, Any]:
        return {
            "type": item_type,
            "severity": severity,
            "title": _bounded_text(title),
            "source": _bounded_text(source, 80),
            "created_at": None,
            "action": {"type": "navigate", "page": page},
        }

    def _health(self, *, attention: list[dict[str, Any]], degraded_sources: list[str]) -> str:
        if degraded_sources and not any(item.get("severity") == "critical" for item in attention):
            return "degraded"
        severities = {item.get("severity") for item in attention}
        if "critical" in severities:
            return "critical"
        if "high" in severities or "warning" in severities:
            return "warning"
        if degraded_sources:
            return "degraded"
        return "healthy"

    def _degraded_section(self, section: str, error: str, defaults: dict[str, Any]) -> dict[str, Any]:
        return {"status": "degraded", "error": _bounded_text(error, 180), **defaults}


# Short-TTL single-flight cache keyed by (tenant_id, user_id); the result is identity-scoped.
_OPS_SUMMARY_TTL = 5.0
_ops_summary_cache: dict = {}      # (tenant_id, user_id) -> (monotonic_ts, result)
_ops_summary_inflight: dict = {}   # (tenant_id, user_id) -> asyncio.Future
# No lock: the bookkeeping never awaits on the single event loop, so single-flight holds.

# Workstream summaries: re-parse the on-disk YAML only when a file is
# added/removed/edited, not on every poll. Signature is stat-only (cheap).
_ws_summary_cache: dict = {}       # tenant_id -> (signature, [summary])


def _load_workstream_summaries(tenant_root: Path, tenant_id: str) -> list[dict[str, Any]]:
    """Enriched workstream summaries, re-parsed only when the YAML on disk changes.

    The previous provider globbed + ``yaml.safe_load``ed every workstream file on
    every 15s ops-summary call. Here a cheap stat-only signature (name, mtime,
    size per file) gates the parse, so an unchanged workstreams dir is served from
    cache. (PERF_NAVIGATION_INVESTIGATION Evidence 5.)
    """
    from iaf_agent_skills.workstream_store import WorkstreamStore
    import yaml as _yaml

    store = WorkstreamStore(tenant_root)
    ws_dir = store.workstreams_dir
    if not ws_dir.exists():
        return []
    files = sorted(ws_dir.glob("*.yaml"))
    try:
        signature = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    except OSError:
        signature = None
    cached = _ws_summary_cache.get(tenant_id)
    if cached and signature is not None and cached[0] == signature:
        return cached[1]

    enriched: list[dict[str, Any]] = []
    for p in files:
        try:
            data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            summary = store._summarize(data)
            summary["items"] = data.get("items") or []
            enriched.append(summary)
        except Exception:
            pass
    if signature is not None:
        _ws_summary_cache[tenant_id] = (signature, enriched)
    return enriched


def _purge_expired_ops_entries() -> None:
    """Drop expired ops-summary entries so the cache is bounded by TTL, not by the
    number of distinct (tenant_id, user_id) identities. Without this a large
    multi-tenant deployment would retain one full result per identity forever."""
    now = time.monotonic()
    expired = [
        k for k, (ts, _) in _ops_summary_cache.items()
        if (now - ts) >= _OPS_SUMMARY_TTL
    ]
    for k in expired:
        _ops_summary_cache.pop(k, None)


async def build_default_ops_summary(*, tenant_id: str = "company", user_id: str | None = None) -> dict[str, Any]:
    """Cached, single-flight wrapper over the live ops-summary build.

    Collapses the every-15s-per-tab polling of N concurrent tabs into one
    recompute per short TTL window. On a cache miss, one caller computes while
    the rest await the same in-flight result (no thundering herd). Errors are not
    cached. See ``_OPS_SUMMARY_TTL`` for the freshness/cost trade-off.

    The in-flight slot is cleared in a ``finally`` so a build that raises OR is
    **cancelled** (client disconnect mid-turn) never strands the future — otherwise
    every later request for that identity would await the same cancelled future and
    fail forever. Expired entries are purged on write so the cache stays bounded.
    """
    key = (tenant_id, user_id)
    hit = _ops_summary_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _OPS_SUMMARY_TTL:
        return hit[1]
    fut = _ops_summary_inflight.get(key)
    creator = fut is None
    if creator:
        fut = asyncio.ensure_future(
            _build_default_ops_summary_uncached(tenant_id=tenant_id, user_id=user_id)
        )
        _ops_summary_inflight[key] = fut
    try:
        result = await fut
    finally:
        # Owner clears the slot on success/error/cancellation — never poison the key.
        if creator and _ops_summary_inflight.get(key) is fut:
            _ops_summary_inflight.pop(key, None)
    if creator:
        _purge_expired_ops_entries()
        _ops_summary_cache[key] = (time.monotonic(), result)
    return result


async def _build_default_ops_summary_uncached(*, tenant_id: str = "company", user_id: str | None = None) -> dict[str, Any]:
    """Build the live Dashboard V2 ops summary from existing Studio state."""
    from cc_queue.db import get_db
    from cc_queue.processor import get_processor
    from shared.config import DATA_ROOT_PATH
    from shared.state import approval_store, cron_scheduler, state, trace_emitter

    from shared.approval_scoping import scope_approval_records
    from security.models import Principal as PrincipalModel

    async def approvals_provider() -> list[dict[str, Any]]:
        approvals = await approval_store.get_pending(tenant_id)
        cards = [_as_dict(item) for item in approvals]
        if user_id:
            principal = PrincipalModel(
                user_id=user_id,
                email=user_id,
                tenant_id=tenant_id,
                roles=("user",),
                allowed_tenants=(tenant_id,),
            )
            cards = scope_approval_records(cards, principal=principal, tenant_id=tenant_id)
        return cards

    def queue_provider() -> dict[str, Any]:
        metrics = get_db().get_metrics(tenant_id)
        processor = get_processor()
        metrics["processor_online"] = bool(metrics.get("processor_online") or getattr(processor, "heartbeat", None))
        metrics["processor_heartbeat"] = getattr(processor, "heartbeat", None)
        return metrics

    def workstreams_provider() -> list[dict[str, Any]]:
        tenant_root = Path(DATA_ROOT_PATH) / "tenants" / tenant_id
        # Stat-gated cache: re-parses the YAML only when a workstream file
        # changes, instead of globbing + parsing on every 15s poll.
        return _load_workstream_summaries(tenant_root, tenant_id)

    trace_db_path = Path(DATA_ROOT_PATH) / "tenants" / tenant_id / "shared" / "databases" / "traces.db"

    # Reuse the shared cron read model: fetch once and pass a constant provider.
    from shared import cron_read_cache
    cron_status = await cron_read_cache.get_status(cron_scheduler.get_status)

    service = DashboardOpsSummaryService(
        agents_provider=lambda: state.agents,
        approval_provider=approvals_provider,
        queue_metrics_provider=queue_provider,
        cron_status_provider=lambda: cron_status,
        workstreams_provider=workstreams_provider,
        finops_provider=build_trace_finops_provider(trace_db_path, tenant_id=tenant_id),
        # user_id scopes non-admin callers (None for admins) so trace previews stay private.
        recent_errors_provider=build_recent_trace_errors_provider(
            trace_emitter, tenant_id=tenant_id, user_id=user_id
        ),
        rules_provider=build_trace_activity_provider(
            trace_emitter, tenant_id=tenant_id, user_id=user_id
        ),
    )
    return await service.build(tenant_id=tenant_id, user_id=user_id)
