"""Prometheus `/metrics` — dependency-free text exposition (no prometheus_client needed).

Samples current state (gauges) at scrape time and emits the Prometheus 0.0.4 text format by hand.
Public (no auth), like /health, so a scraper can poll it. Every sample is best-effort — a failing
source is simply omitted; the endpoint never errors.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# When set, /metrics requires "Authorization: Bearer <token>" matching this value.
# Leave unset to keep the endpoint open (e.g. for a Prometheus scraper on a private network).
_SCRAPE_TOKEN: str = os.getenv("METRICS_SCRAPE_TOKEN", "").strip()

_PROM_CT = "text/plain; version=0.0.4; charset=utf-8"


def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _sample_sync() -> list[str]:
    """Synchronous sampling (pool/DB/traces). Runs in a worker thread. Best-effort per metric."""
    out: list[str] = []

    def add(name, value, help_=None, labels=None, typ="gauge"):
        if help_:
            out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {typ}")
        lbl = ""
        if labels:
            lbl = "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items()) + "}"
        out.append(f"{name}{lbl} {value}")

    add("agentos_up", 1, help_="1 if the server process is serving requests")
    try:
        from shared.storage_mode import resolved_storage_backends
        _sb = resolved_storage_backends()
    except Exception:
        _sb = {}
    add("agentos_build_info", 1, help_="Active storage backends (value always 1)", labels={
        "db_backend": _sb.get("DB_BACKEND", os.getenv("DB_BACKEND", "sqlite")),
        "knowledge_backend": _sb.get("KNOWLEDGE_BACKEND", os.getenv("KNOWLEDGE_BACKEND", "sqlite")),
        "evidence_backend": _sb.get("EVIDENCE_BACKEND", os.getenv("EVIDENCE_BACKEND", "sqlite")),
        "trace_backend": _sb.get("TRACE_BACKEND", os.getenv("TRACE_BACKEND", "sqlite")),
        "vector_backend": _sb.get("VECTOR_BACKEND", os.getenv("VECTOR_BACKEND", "brute_force")),
        "cc_queue_backend": _sb.get("CC_QUEUE_STORAGE_BACKEND", os.getenv("CC_QUEUE_STORAGE_BACKEND", "sqlite")),
        "queue_backend": _sb.get("QUEUE_BACKEND", os.getenv("QUEUE_BACKEND", "memory")),
        "storage_mode": os.getenv("STORAGE_MODE", ""),
    })

    # Postgres: connection pool (in-process, free) + reachability + total backends.
    try:
        from iaf_agent_skills.storage.engine import get_engine, resolve_backend
        if resolve_backend() == "postgres":
            eng = get_engine()
            stats = getattr(eng, "pool_stats", lambda: {})() or {}
            if "pool_size" in stats:
                add("agentos_db_pool_size", stats.get("pool_size", 0), help_="current connections in the psycopg_pool")
            if "pool_available" in stats:
                add("agentos_db_pool_available", stats.get("pool_available", 0), help_="idle pooled connections")
            if "requests_waiting" in stats:
                add("agentos_db_pool_requests_waiting", stats.get("requests_waiting", 0),
                    help_="requests queued waiting for a pooled connection")
            try:
                with eng.connect() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT count(*) FROM pg_stat_activity")
                    n = cur.fetchone()[0]
                add("agentos_postgres_up", 1, help_="1 if Postgres is reachable")
                add("agentos_postgres_connections", int(n), help_="total backend connections on the PG instance")
            except Exception:
                add("agentos_postgres_up", 0, help_="1 if Postgres is reachable")
    except Exception as e:
        logger.debug("metrics: db sample failed: %s", e)

    # Execution traces in the last 24h (observability throughput).
    try:
        from shared.state import trace_emitter as _te
        if _te:
            since = (_dt.datetime.now() - _dt.timedelta(hours=24)).isoformat()
            add("agentos_traces_24h", int(_te.count_traces(since=since)),
                help_="execution traces recorded in the last 24h")
    except Exception as e:
        logger.debug("metrics: trace sample failed: %s", e)

    # Redis reachability — fresh short-lived sync client via REDIS_URL. (The shared
    # `redis_client` isn't reliably bound at module scope, so don't depend on it.)
    up = 0
    try:
        import redis as _redis
        from shared.config import REDIS_URL
        r = _redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        try:
            up = 1 if r.ping() else 0
        finally:
            try:
                r.close()
            except Exception:
                pass
    except Exception as e:
        logger.debug("metrics: redis sample failed: %s", e)
    add("agentos_redis_up", up, help_="1 if Redis is reachable")

    return out


@router.get("/metrics")
async def metrics(request: Request):
    """Prometheus scrape endpoint. Returns the text exposition of current gauges.

    Protected by METRICS_SCRAPE_TOKEN when that env var is set; open otherwise.
    """
    if _SCRAPE_TOKEN:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[len("Bearer "):].strip() != _SCRAPE_TOKEN:
            return PlainTextResponse("Unauthorized", status_code=401)
    lines = await asyncio.to_thread(_sample_sync)
    return PlainTextResponse("\n".join(lines) + "\n", media_type=_PROM_CT)
