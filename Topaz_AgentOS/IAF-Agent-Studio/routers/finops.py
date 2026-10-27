"""
IAF Agent Studio — FinOps Router

Financial observability and cost optimisation endpoints for the
AI FinOps dashboard. Supports both SQLite (default) and Postgres
backends, matching whichever backend TRACE_BACKEND selects.

Prefix  : /api/finops
Tag     : finops
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request

from shared.config import AUTH_ENABLED, DATA_ROOT, TENANT_ID
from shared.state import trace_emitter
from security.dependencies import bind_request_identity, principal_from_request

logger = logging.getLogger(__name__)


_PG_SCHEMA_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,47}")
_KNOWN_TABLES = {"traces": "traces", "spans": "spans"}

# Per-backend constant SQL fragments, keyed by _trace_backend().
_PLACEHOLDER = {"postgres": "%s", "sqlite": "?"}
_DATE_EXPR = {
    "postgres": "created_at::timestamp::date",
    "sqlite": "date(created_at)",
}
_SKILL_LABEL_SQL = "COALESCE(NULLIF(TRIM(skill), ''), 'Unattributed')"
_RANGE_CONDITIONS = {
    "postgres": (
        "created_at::timestamp >= %s::timestamp",
        "created_at::timestamp < %s::timestamp",
    ),
    "sqlite": (
        "datetime(created_at) >= datetime(?)",
        "datetime(created_at) < datetime(?)",
    ),
}
# "Today" = current calendar day since midnight, not a rolling 24-hour window.
_TODAY_CONDITION = {
    "postgres": "created_at::timestamp >= date_trunc('day', NOW())",
    "sqlite": "datetime(created_at) >= date('now')",
}
_ROLLING_CONDITION = {
    "postgres": "created_at::timestamp >= NOW() - make_interval(days => %s)",
    "sqlite": "datetime(created_at) >= datetime('now', ?)",
}
_SKILL_CONDITION = {"postgres": "skill = %s", "sqlite": "skill = ?"}
_MATCH_NOTHING = "1=0"
_MATCH_ALL = "1=1"

_READ_ONLY_SQL_RE = re.compile(r"\s*(SELECT|WITH)\s", re.IGNORECASE)


def _finops_where(conditions: list) -> str:
    """Build WHERE clause from validated condition fragments."""
    if not conditions:
        return _MATCH_ALL
    return " AND ".join(conditions)

router = APIRouter(prefix="/api/finops", tags=["finops"])


def _trace_backend() -> str:
    raw = (os.getenv("TRACE_BACKEND", "sqlite") or "sqlite").strip().lower()
    return "postgres" if raw in ("postgres", "postgresql", "pg") else "sqlite"


def _pg_schema() -> str:
    """Validated trace schema name, used only as the bound search_path value."""
    schema = os.getenv("TRACE_PG_SCHEMA", "trace")
    if not _PG_SCHEMA_RE.fullmatch(schema or ""):
        raise ValueError("TRACE_PG_SCHEMA is not a valid SQL identifier")
    return schema


def _tbl(name: str) -> str:
    """Return the constant name of an allowlisted trace table.

    Names are never schema-qualified: on Postgres the schema is resolved via a
    transaction-local ``search_path`` (see ``_executed``).
    """
    table = _KNOWN_TABLES.get(name)
    if table is None:
        raise ValueError("unknown FinOps table")
    return table


def _ph() -> str:
    return _PLACEHOLDER[_trace_backend()]


def _date_expr() -> str:
    return _DATE_EXPR[_trace_backend()]


def _checked_sql(sql: str, params: list) -> str:
    """Final guard before ``cursor.execute`` — FinOps is read-only.

    Rejects anything that is not a single SELECT/WITH statement (no ``;``,
    ``--`` or ``/*``) and requires the number of value placeholders to match
    the bound parameters, so values can only ever travel as parameters. The
    validated string is rebuilt before it is returned to the sink.
    """
    if not isinstance(sql, str):
        raise TypeError("FinOps SQL must be a string")
    if ";" in sql or "--" in sql or "/*" in sql:
        raise ValueError("FinOps SQL rejected: statement separators/comments are not allowed")
    if not _READ_ONLY_SQL_RE.match(sql):
        raise ValueError("FinOps SQL rejected: only SELECT/WITH queries are allowed")
    if sql.count(_ph()) != len(params):
        raise ValueError("FinOps SQL rejected: placeholder/parameter count mismatch")
    return "".join(ch for ch in sql)


def _db_path() -> str:
    if trace_emitter is not None and hasattr(trace_emitter, "_db_path"):
        return trace_emitter._db_path
    return str(
        Path(DATA_ROOT)
        / "tenants"
        / TENANT_ID
        / "shared"
        / "databases"
        / "traces.db"
    )


def _get_conn():
    if _trace_backend() == "postgres":
        import psycopg
        from psycopg.rows import dict_row
        database_url = os.getenv("DATABASE_URL", "")
        return psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


# Transaction-local schema selection: must run in the same transaction (PgBouncer drops startup options).
_SET_SEARCH_PATH_SQL = "SELECT set_config('search_path', %s, true)"


@contextmanager
def _executed(conn, sql: str, params: list):
    """Run a checked FinOps query and yield the cursor holding its result."""
    safe_sql = _checked_sql(sql, params)
    cur = conn.cursor()
    if _trace_backend() != "postgres":
        cur.execute(safe_sql, params)
        yield cur
        return
    # Trace tables live in TRACE_PG_SCHEMA (created by trace_emitter).
    with conn.transaction():
        cur.execute(_SET_SEARCH_PATH_SQL, (_pg_schema(),))
        cur.execute(safe_sql, params)
        yield cur


def _fetchall(conn, sql: str, params: list) -> list[dict]:
    """Execute and return rows as plain dicts regardless of backend."""
    with _executed(conn, sql, params) as cur:
        rows = cur.fetchall()
    if _trace_backend() == "postgres":
        return rows  # psycopg dict_row already returns dicts
    return [dict(r) for r in rows]


def _fetchone(conn, sql: str, params: list) -> dict:
    with _executed(conn, sql, params) as cur:
        row = cur.fetchone()
    if _trace_backend() == "postgres":
        return row or {}  # psycopg dict_row returns dict or None
    return dict(row) if row else {}


def _tenant_scope(request: Request, tenant_id: Optional[str]) -> Optional[list]:
    """Resolve which tenants the caller may read, refusing unentitled ones.

    Returns ``None`` when no tenant filter should be applied at all — that is
    only ever the case with auth disabled, where local development keeps the
    unscoped view. Otherwise returns an explicit list of tenant ids; an empty
    list means "match nothing" rather than "match everything".

    Naming a tenant outside the caller's entitlements raises 403 through
    ``bind_request_identity``, the same check the rest of the app uses. Omitting
    the tenant means "all tenants I am entitled to" — matching the dashboard's
    "All tenants" option — not "every tenant in the database".

    Call this from the request handler *before* its ``try``/``except``. The
    endpoints deliberately swallow query failures into empty 200 payloads so a
    FinOps panel never breaks the page; raising inside that block would convert
    a 403 into a misleading "no spend" response.
    """
    if not AUTH_ENABLED:
        return [tenant_id] if tenant_id else None

    if tenant_id:
        # Raises HTTPException(403) when the tenant is not entitled.
        bind_request_identity(request, requested_tenant=tenant_id)
        return [tenant_id]

    principal = principal_from_request(request)
    return [t for t in (principal.allowed_tenants or ()) if t]


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validated_range(start: Optional[str], end: Optional[str]) -> Optional[tuple[str, str]]:
    """Return (inclusive start, exclusive end) ISO dates, or None if unused.

    Both ends must be YYYY-MM-DD. The span is capped at 366 days so a custom
    range cannot scan an unbounded history. Values are returned for bound
    parameters only — never interpolated into SQL.
    """
    if not start or not end:
        return None
    if not _DATE_RE.match(start) or not _DATE_RE.match(end):
        return None
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
        end_d = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return None
    if end_d < start_d:
        start_d, end_d = end_d, start_d
    if (end_d - start_d).days >= 366:
        start_d = end_d - timedelta(days=365)
    exclusive = end_d + timedelta(days=1)
    return start_d.isoformat(), exclusive.isoformat()


def _window_days(period: int, start: Optional[str] = None, end: Optional[str] = None) -> int:
    rng = _validated_range(start, end)
    if rng and start and end and _DATE_RE.match(start) and _DATE_RE.match(end):
        start_d = datetime.strptime(rng[0], "%Y-%m-%d").date()
        end_excl = datetime.strptime(rng[1], "%Y-%m-%d").date()
        return max(1, (end_excl - start_d).days)
    return int(period)


def _skill_label_sql() -> str:
    """Blank, whitespace, and NULL skills collapse to one named bucket."""
    return _SKILL_LABEL_SQL


def _base_conditions(
    period: int,
    tenants: Optional[list],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> tuple[list, list]:
    """Return (conditions, params) for the common period + tenant filters.

    ``tenants`` is the resolved scope from :func:`_tenant_scope`, never a raw
    caller-supplied value. A validated ``start``/``end`` pair replaces the
    rolling ``period`` window.
    """
    backend = _trace_backend()
    ph = _PLACEHOLDER[backend]
    rng = _validated_range(start, end)
    conditions: list[str]
    params: list
    if rng:
        start_iso, end_excl = rng
        conditions = list(_RANGE_CONDITIONS[backend])
        params = [start_iso, end_excl]
    elif int(period) == 1:
        conditions = [_TODAY_CONDITION[backend]]
        params = []
    else:
        # Rolling N-day window; N is always a bound parameter.
        conditions = [_ROLLING_CONDITION[backend]]
        if backend == "postgres":
            params = [int(period)]
        else:
            params = [f"-{int(period)} days"]
    if tenants is not None:
        if not tenants:
            # Entitled to nothing: match no rows. An absent predicate here would
            # silently widen the query to every tenant.
            conditions.append(_MATCH_NOTHING)
        else:
            placeholders = ", ".join([ph] * len(tenants))
            conditions.append("tenant IN (" + placeholders + ")")
            params.extend(tenants)
    return conditions, params


def _parse_metadata_calls(rows: list[dict]) -> tuple[dict, dict, dict, float]:
    """
    Parse llm_budget.calls out of metadata rows in a single pass.
    Returns (purpose_map, model_map, model_purposes_map, total_cost).
    Sharing this across /kpis, /by-purpose, /by-model, and insights avoids
    redundant full-table scans and redundant JSON parsing.
    """
    purpose_map: dict[str, dict] = {}
    model_map: dict[str, dict] = {}
    model_purposes: dict[str, set] = {}
    total_cost = 0.0
    for row in rows:
        total_cost += row.get("cost_usd") or 0.0
        try:
            meta = json.loads(row.get("metadata") or "{}")
            for call in meta.get("llm_budget", {}).get("calls", []):
                purpose = call.get("purpose") or "unknown"
                model = call.get("model") or "unknown"
                pt = call.get("prompt_tokens", 0)
                ct = call.get("completion_tokens", 0)
                cost = call.get("cost_usd", 0.0)

                p = purpose_map.setdefault(purpose, {
                    "purpose": purpose, "prompt_tokens": 0,
                    "completion_tokens": 0, "cost_usd": 0.0,
                })
                p["prompt_tokens"] += pt
                p["completion_tokens"] += ct
                p["cost_usd"] += cost

                m = model_map.setdefault(model, {
                    "model": model, "prompt_tokens": 0,
                    "completion_tokens": 0, "cost_usd": 0.0, "calls": 0,
                })
                m["prompt_tokens"] += pt
                m["completion_tokens"] += ct
                m["cost_usd"] += cost
                m["calls"] += 1

                model_purposes.setdefault(model, set()).add(purpose)
        except Exception:
            pass
    return purpose_map, model_map, model_purposes, total_cost


@router.get("/tenants")
async def finops_tenants(request: Request):
    """Distinct tenant ids that have cost/trace data, for the filter dropdown.

    Data-driven so the dropdown only offers tenants the filter can actually
    match. The configured default ``TENANT_ID`` is always included so the
    list is never empty on a fresh deployment.

    Tenant-scoped: the result is restricted to the caller's ``allowed_tenants``
    (when auth is enabled) so an authenticated user cannot enumerate the tenant
    identifiers of tenants they have no access to.
    """
    principal = principal_from_request(request)

    def _query():
        sql = (
            f"SELECT DISTINCT tenant FROM {_tbl('traces')}"
            " WHERE tenant IS NOT NULL AND tenant <> ''"
            " ORDER BY tenant ASC"
        )
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, [])
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        tenants = [r["tenant"] for r in rows if r.get("tenant")]
    except Exception as exc:
        logger.warning("finops/tenants error (non-fatal): %s", exc)
        tenants = []

    # Always surface the configured default tenant so the dropdown is usable
    # even before any traces have been recorded.
    if TENANT_ID and TENANT_ID not in tenants:
        tenants.append(TENANT_ID)

    if AUTH_ENABLED:
        allowed = set(principal.allowed_tenants or ())
        tenants = [t for t in tenants if t in allowed]

    tenants = sorted(set(tenants))
    return {"tenants": tenants}


@router.get("/summary")
async def finops_summary(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
    skill: Optional[str] = None,
):
    """Aggregate cost/token totals for the requested period."""
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        if skill:
            conditions.append(_SKILL_CONDITION[_trace_backend()])
            params.append(skill)
        where = _finops_where(conditions)
        sql = (
            "SELECT"
            " COALESCE(SUM(cost_usd), 0) AS total_cost_usd,"
            " COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,"
            " COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,"
            " COUNT(*) AS total_requests"
            f" FROM {_tbl('traces')}"
            " WHERE " + where
        )
        conn = _get_conn()
        try:
            return _fetchone(conn, sql, params)
        finally:
            conn.close()

    try:
        row = await asyncio.to_thread(_query)
        total_cost = row["total_cost_usd"] or 0.0
        total_req = row["total_requests"] or 0
        avg_cost = round(total_cost / total_req, 6) if total_req else 0.0
        return {
            "total_cost_usd": round(total_cost, 4),
            "total_prompt_tokens": row["total_prompt_tokens"],
            "total_completion_tokens": row["total_completion_tokens"],
            "total_requests": total_req,
            "avg_cost_per_request": avg_cost,
            "period_days": period,
        }
    except Exception as exc:
        logger.warning("finops/summary error (non-fatal): %s", exc)
        return {
            "total_cost_usd": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_requests": 0,
            "avg_cost_per_request": 0,
            "period_days": period,
        }


@router.get("/trends")
async def finops_trends(
    request: Request,
    period: int = 30,
    tenant_id: Optional[str] = None,
):
    """Daily cost breakdown for the last N days."""
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        where = _finops_where(conditions)
        date_expr = _date_expr()
        sql = (
            f"SELECT {date_expr} AS date,"
            " COALESCE(SUM(cost_usd), 0) AS cost_usd,"
            " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
            " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
            " COUNT(*) AS requests"
            f" FROM {_tbl('traces')}"
            " WHERE " + where +
            f" GROUP BY {date_expr}"
            f" ORDER BY {date_expr} ASC"
        )
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, params)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        days = [
            {
                "date": str(r["date"]),
                "cost_usd": round(r["cost_usd"], 6),
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "requests": r["requests"],
            }
            for r in rows
        ]
        return {"days": days}
    except Exception as exc:
        logger.warning("finops/trends error (non-fatal): %s", exc)
        return {"days": []}


@router.get("/kpis")
async def finops_kpis(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
):
    """
    Combined purpose + model breakdown from a single metadata fetch.
    Replaces separate /by-purpose and /by-model calls on the dashboard,
    halving the metadata scan cost and saving one Postgres connection.
    """
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        where = _finops_where(conditions)
        sql = (
            f"SELECT metadata, cost_usd FROM {_tbl('traces')}"
            " WHERE " + where + " AND metadata IS NOT NULL"
        )
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, params)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        purpose_map, model_map, _, total_cost = _parse_metadata_calls(rows)

        purposes = sorted(purpose_map.values(), key=lambda x: x["cost_usd"], reverse=True)
        for p in purposes:
            p["cost_usd"] = round(p["cost_usd"], 6)
            p["pct_cost"] = round(p["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0

        # Filter "unknown" entries with zero tokens — historical noise before model tracking was fixed.
        models_raw = sorted(model_map.values(), key=lambda x: x["cost_usd"], reverse=True)
        models = []
        for m in models_raw:
            if m["model"] == "unknown" and m["prompt_tokens"] == 0 and m["completion_tokens"] == 0:
                continue
            m["cost_usd"] = round(m["cost_usd"], 6)
            m["pct_cost"] = round(m["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0
            models.append(m)

        return {"purposes": purposes, "models": models}
    except Exception as exc:
        logger.warning("finops/kpis error (non-fatal): %s", exc)
        return {"purposes": [], "models": []}


@router.get("/by-purpose")
async def finops_by_purpose(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
):
    """Cost breakdown by LLM call purpose from metadata JSON."""
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        where = _finops_where(conditions)
        sql = f"SELECT metadata, cost_usd FROM {_tbl('traces')} WHERE " + where + " AND metadata IS NOT NULL"
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, params)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        purpose_map, _, _mp, total_cost = _parse_metadata_calls(rows)

        purposes = sorted(purpose_map.values(), key=lambda x: x["cost_usd"], reverse=True)
        for p in purposes:
            p["cost_usd"] = round(p["cost_usd"], 6)
            p["pct_cost"] = round(p["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0

        return {"purposes": purposes}
    except Exception as exc:
        logger.warning("finops/by-purpose error (non-fatal): %s", exc)
        return {"purposes": []}


@router.get("/by-skill")
async def finops_by_skill(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
):
    """Cost breakdown grouped by skill."""
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        where = _finops_where(conditions)
        sql = (
            f"SELECT {_skill_label_sql()} AS skill,"
            " COALESCE(SUM(cost_usd), 0) AS cost_usd,"
            " COUNT(*) AS requests"
            f" FROM {_tbl('traces')}"
            " WHERE " + where +
            f" GROUP BY {_skill_label_sql()}"
            " ORDER BY cost_usd DESC"
        )
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, params)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        total_cost = sum(r["cost_usd"] for r in rows)
        skills = [
            {
                "skill": r["skill"],
                "cost_usd": round(r["cost_usd"], 6),
                "requests": r["requests"],
                "avg_cost": round(r["cost_usd"] / r["requests"], 6) if r["requests"] else 0.0,
                "pct_cost": round(r["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0,
            }
            for r in rows
        ]
        return {"skills": skills}
    except Exception as exc:
        logger.warning("finops/by-skill error (non-fatal): %s", exc)
        return {"skills": []}


@router.get("/by-model")
async def finops_by_model(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
):
    """Cost breakdown by model from metadata JSON."""
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        where = _finops_where(conditions)
        sql = f"SELECT metadata, cost_usd FROM {_tbl('traces')} WHERE " + where + " AND metadata IS NOT NULL"
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, params)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        _, model_map, _mp, total_cost = _parse_metadata_calls(rows)

        models = sorted(model_map.values(), key=lambda x: x["cost_usd"], reverse=True)
        for m in models:
            m["cost_usd"] = round(m["cost_usd"], 6)
            m["pct_cost"] = round(m["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0

        return {"models": models}
    except Exception as exc:
        logger.warning("finops/by-model error (non-fatal): %s", exc)
        return {"models": []}


@router.get("/by-user")
async def finops_by_user(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
    limit: int = 10,
):
    """Cost breakdown grouped by user_id, top-N by spend."""
    tenants = _tenant_scope(request, tenant_id)

    def _query():
        conditions, params = _base_conditions(period, tenants)
        where = _finops_where(conditions)
        sql = (
            "SELECT COALESCE(user_id, 'unknown') AS user_id,"
            " COALESCE(SUM(cost_usd), 0) AS cost_usd,"
            " COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
            " COALESCE(SUM(completion_tokens), 0) AS completion_tokens"
            f" FROM {_tbl('traces')}"
            " WHERE " + where +
            " GROUP BY user_id"
            " ORDER BY cost_usd DESC"
            f" LIMIT {_ph()}"
        )
        params.append(int(limit))
        conn = _get_conn()
        try:
            return _fetchall(conn, sql, params)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_query)
        users = [
            {
                "user_id": r["user_id"],
                "cost_usd": round(r["cost_usd"], 6),
                "requests": r["requests"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
            }
            for r in rows
        ]
        return {"users": users}
    except Exception as exc:
        logger.warning("finops/by-user error (non-fatal): %s", exc)
        return {"users": []}


def _daily_avgs_from_trends(trend_rows: list[dict]) -> tuple[float, float]:
    """Recent 2-day vs prior 5-day average daily cost from pre-fetched trend rows."""
    ordered = sorted(trend_rows, key=lambda r: str(r.get("date", "")), reverse=True)
    recent = ordered[:2]
    prior = ordered[2:7]
    recent_avg = sum(float(r.get("cost_usd") or 0.0) for r in recent) / len(recent) if recent else 0.0
    prior_avg = sum(float(r.get("cost_usd") or 0.0) for r in prior) / len(prior) if prior else 0.0
    return recent_avg, prior_avg


def _run_insights_queries(
    period: int,
    tenants: Optional[list],
    start: Optional[str] = None,
    end: Optional[str] = None,
    *,
    conn=None,
    meta_rows: Optional[list] = None,
    trend_rows: Optional[list] = None,
    summary_row: Optional[dict] = None,
) -> dict:
    """Run raw queries needed for rule evaluation. Returns a data bag.

    When called from :func:`_dashboard_payload`, pass the open connection plus
    rows already fetched for the dashboard to avoid a second connect and duplicate
    summary/metadata scans.
    """
    conditions, base_params = _base_conditions(period, tenants, start, end)
    where = _finops_where(conditions)
    ph = _ph()
    date_expr = _date_expr()
    traces = _tbl("traces")
    spans = _tbl("spans")
    own_conn = conn is None
    if own_conn:
        conn = _get_conn()
    data: dict = {}

    try:
        if summary_row is not None:
            data["total_cost"] = summary_row.get("total_cost_usd") or 0.0
            data["total_req"] = summary_row.get("total_requests") or 0
            data["avg_tokens"] = summary_row.get("avg_tokens") or 0.0
        else:
            row = _fetchone(conn,
                "SELECT COALESCE(SUM(cost_usd),0) AS total_cost,"
                " COALESCE(SUM(prompt_tokens),0) AS total_pt,"
                " COALESCE(SUM(completion_tokens),0) AS total_ct,"
                " COUNT(*) AS total_req,"
                " COALESCE(AVG(prompt_tokens + completion_tokens), 0) AS avg_tokens"
                f" FROM {traces} WHERE " + where,
                base_params,
            )
            data["total_cost"] = row["total_cost"] or 0.0
            data["total_req"] = row["total_req"] or 0
            data["avg_tokens"] = row["avg_tokens"] or 0.0

        threshold = 0.10
        runaway = _fetchone(conn,
            f"SELECT COUNT(*) AS cnt, COALESCE(SUM(cost_usd),0) AS total FROM {traces} WHERE " + where + f" AND cost_usd > {ph}",
            base_params + [threshold],
        )
        data["runaway_count"] = runaway["cnt"] or 0
        data["runaway_total"] = runaway["total"] or 0.0
        data["runaway_threshold"] = threshold

        if trend_rows is not None:
            recent_avg, prior_avg = _daily_avgs_from_trends(trend_rows)
            data["recent_daily_avg"] = recent_avg
            data["prior_daily_avg"] = prior_avg
        else:
            recent_row = _fetchone(conn,
                f"SELECT COALESCE(AVG(daily_cost),0) AS avg FROM ("
                f" SELECT {date_expr} AS d, SUM(cost_usd) AS daily_cost"
                f" FROM {traces} WHERE " + where +
                f" GROUP BY {date_expr}"
                f" ORDER BY {date_expr} DESC LIMIT 2"
                ")",
                base_params,
            )
            prior_row = _fetchone(conn,
                f"SELECT COALESCE(AVG(daily_cost),0) AS avg FROM ("
                f" SELECT {date_expr} AS d, SUM(cost_usd) AS daily_cost"
                f" FROM {traces} WHERE " + where +
                f" GROUP BY {date_expr}"
                f" ORDER BY {date_expr} DESC LIMIT 5 OFFSET 2"
                ")",
                base_params,
            )
            data["recent_daily_avg"] = recent_row["avg"] or 0.0
            data["prior_daily_avg"] = prior_row["avg"] or 0.0

        where_aliased = where.replace("created_at", "t.created_at")
        tool_row = _fetchone(conn,
            "SELECT COALESCE(AVG(tool_count),0) AS avg_tools FROM ("
            " SELECT t.trace_id, COUNT(s.id) AS tool_count"
            f" FROM {traces} t"
            f" LEFT JOIN {spans} s ON s.trace_id = t.trace_id AND s.span_type = 'tool'"
            " WHERE " + where_aliased +
            " GROUP BY t.trace_id"
            ")",
            base_params,
        )
        data["avg_tools"] = tool_row["avg_tools"] or 0.0

        if meta_rows is None:
            meta_rows = _fetchall(conn,
                f"SELECT metadata, cost_usd FROM {traces} WHERE " + where + " AND metadata IS NOT NULL",
                base_params,
            )
    finally:
        if own_conn:
            conn.close()

    purpose_map, model_map, model_purposes, _ = _parse_metadata_calls(meta_rows or [])
    data["purpose_cost"] = {k: v["cost_usd"] for k, v in purpose_map.items()}
    data["model_calls"] = {k: v["calls"] for k, v in model_map.items()}
    data["model_purposes"] = model_purposes
    return data


def _evaluate_insights(d: dict) -> list[dict]:
    """Apply the rule set to a data bag from :func:`_run_insights_queries`."""
    total_cost = d["total_cost"]
    purpose_cost = d["purpose_cost"]
    insights: list[dict] = []

    mem_cost = (
        purpose_cost.get("memory_summary", 0.0)
        + purpose_cost.get("memory_analysis", 0.0)
        + purpose_cost.get("memory", 0.0)
    )
    if total_cost > 0 and mem_cost / total_cost > 0.25:
        pct = round(mem_cost / total_cost * 100, 1)
        saving = round(mem_cost * 0.4, 4)
        insights.append({
            "rule": "heavy_memory",
            "severity": "warning",
            "title": "Memory summarisation is expensive",
            "detail": f"Memory summarisation and analysis is {pct}% of spend (${round(mem_cost,4)} this period).",
            "recommendation": "Reduce frequency or trim context window before summarisation.",
            "saving_usd_per_week": saving,
        })

    router_cost = purpose_cost.get("router", 0.0)
    if total_cost > 0 and router_cost / total_cost > 0.10:
        pct = round(router_cost / total_cost * 100, 1)
        saving = round(router_cost * 0.9, 4)
        insights.append({
            "rule": "expensive_router",
            "severity": "warning",
            "title": "Router using expensive model",
            "detail": f"Router calls are {pct}% of spend (${round(router_cost,4)} this period) — it is a classification task.",
            "recommendation": "Switch router LLM to gpt-5-nano.",
            "saving_usd_per_week": saving,
        })

    if d["runaway_count"] > 0:
        excess = round(d["runaway_total"] - d["runaway_count"] * d["runaway_threshold"], 4)
        insights.append({
            "rule": "runaway_request",
            "severity": "warning",
            "title": "Runaway requests detected",
            "detail": (
                f"Found {d['runaway_count']} request(s) costing more than "
                f"${d['runaway_threshold']} each (${round(d['runaway_total'],4)} total)."
            ),
            "recommendation": "Cap max context length per request to prevent token runaway.",
            "saving_usd_per_week": max(excess, 0),
        })

    evo_cost = purpose_cost.get("evolution", 0.0)
    if total_cost > 0 and evo_cost / total_cost > 0.05:
        pct = round(evo_cost / total_cost * 100, 1)
        saving = round(evo_cost * 0.6, 4)
        insights.append({
            "rule": "evolution_overdrive",
            "severity": "info",
            "title": "Self-evolution LLM calls are frequent",
            "detail": f"Evolution calls are {pct}% of spend (${round(evo_cost,4)} this period).",
            "recommendation": "Raise the evolution trigger threshold to reduce call frequency.",
            "saving_usd_per_week": saving,
        })

    recent = d["recent_daily_avg"]
    prior = d["prior_daily_avg"]
    if prior > 0 and recent > 2 * prior:
        insights.append({
            "rule": "cost_spike",
            "severity": "warning",
            "title": "Cost spike detected",
            "detail": (
                f"Recent 2-day daily average ${round(recent,4)} is "
                f"{round(recent/prior,1)}x higher than prior 5-day avg ${round(prior,4)}."
            ),
            "recommendation": "Review recent skill changes and prompt updates for token inflation.",
            "saving_usd_per_week": 0,
        })

    model_calls = d["model_calls"]
    model_purposes = d["model_purposes"]
    total_calls = sum(model_calls.values()) or 1
    heavy_model = "gpt-5.2-chat"
    heavy_calls = model_calls.get(heavy_model, 0)
    heavy_purposes = model_purposes.get(heavy_model, set())
    lightweight_in_heavy = heavy_purposes & {"router", "memory_summary", "memory_analysis", "memory"}
    if heavy_calls / total_calls > 0.80 and lightweight_in_heavy:
        insights.append({
            "rule": "model_mismatch",
            "severity": "warning",
            "title": "Lightweight tasks on heavy model",
            "detail": (
                f"{heavy_model} handles {round(heavy_calls/total_calls*100,1)}% of calls, "
                f"including {', '.join(sorted(lightweight_in_heavy))} purposes."
            ),
            "recommendation": "Route router and memory calls to gpt-5-nano for significant savings.",
            "saving_usd_per_week": 0,
        })

    if d["avg_tokens"] > 8000 and d["avg_tools"] < 1:
        insights.append({
            "rule": "high_token_low_tool",
            "severity": "info",
            "title": "High token count with low tool use",
            "detail": (
                f"Avg {int(d['avg_tokens'])} tokens/request but only "
                f"{round(d['avg_tools'],2)} tool calls/request — suggests prompt verbosity or agent looping."
            ),
            "recommendation": "Trim system prompts, enable early exit, or audit for looping traces.",
            "saving_usd_per_week": 0,
        })

    return insights


@router.get("/insights")
async def finops_insights(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
):
    """Rule-based optimisation insights — no LLM calls, pure logic."""
    tenants = _tenant_scope(request, tenant_id)
    try:
        d = await asyncio.to_thread(_run_insights_queries, period, tenants)
    except Exception as exc:
        logger.warning("finops/insights data-fetch error (non-fatal): %s", exc)
        return {"insights": []}

    return {"insights": _evaluate_insights(d)}


def _shape_summary(row: dict, period: int, start: Optional[str], end: Optional[str]) -> dict:
    total_cost = row.get("total_cost_usd") or 0.0
    total_req = row.get("total_requests") or 0
    avg_cost = round(total_cost / total_req, 6) if total_req else 0.0
    return {
        "total_cost_usd": round(total_cost, 4),
        "total_prompt_tokens": row.get("total_prompt_tokens") or 0,
        "total_completion_tokens": row.get("total_completion_tokens") or 0,
        "total_requests": total_req,
        "avg_cost_per_request": avg_cost,
        "period_days": _window_days(period, start, end),
    }


def _empty_summary(period: int, start: Optional[str], end: Optional[str]) -> dict:
    return _shape_summary({}, period, start, end)


def _dashboard_payload(
    period: int,
    tenants: Optional[list],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """Load every FinOps panel from one connection, then attach insights."""
    conditions, params = _base_conditions(period, tenants, start, end)
    where = _finops_where(conditions)
    ph = _ph()
    date_expr = _date_expr()
    traces = _tbl("traces")
    skill_key = _skill_label_sql()
    conn = _get_conn()
    try:
        summary_row = _fetchone(
            conn,
            "SELECT"
            " COALESCE(SUM(cost_usd), 0) AS total_cost_usd,"
            " COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,"
            " COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,"
            " COUNT(*) AS total_requests,"
            " COALESCE(AVG(prompt_tokens + completion_tokens), 0) AS avg_tokens"
            f" FROM {traces} WHERE " + where,
            params,
        )
        trend_rows = _fetchall(
            conn,
            f"SELECT {date_expr} AS date,"
            " COALESCE(SUM(cost_usd), 0) AS cost_usd,"
            " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
            " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
            " COUNT(*) AS requests"
            f" FROM {traces} WHERE " + where +
            f" GROUP BY {date_expr} ORDER BY {date_expr} ASC",
            params,
        )
        meta_rows = _fetchall(
            conn,
            f"SELECT metadata, cost_usd FROM {traces} WHERE " + where + " AND metadata IS NOT NULL",
            params,
        )
        skill_rows = _fetchall(
            conn,
            f"SELECT {skill_key} AS skill,"
            " COALESCE(SUM(cost_usd), 0) AS cost_usd,"
            " COUNT(*) AS requests"
            f" FROM {traces} WHERE " + where +
            f" GROUP BY {skill_key} ORDER BY cost_usd DESC",
            params,
        )
        user_rows = _fetchall(
            conn,
            "SELECT COALESCE(user_id, 'unknown') AS user_id,"
            " COALESCE(SUM(cost_usd), 0) AS cost_usd,"
            " COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
            " COALESCE(SUM(completion_tokens), 0) AS completion_tokens"
            f" FROM {traces} WHERE " + where +
            " GROUP BY user_id ORDER BY cost_usd DESC"
            f" LIMIT {ph}",
            params + [10],
        )
        insight_bag = _run_insights_queries(
            period,
            tenants,
            start,
            end,
            conn=conn,
            meta_rows=meta_rows,
            trend_rows=trend_rows,
            summary_row=summary_row,
        )
    finally:
        conn.close()

    purpose_map, model_map, _, total_cost = _parse_metadata_calls(meta_rows)
    purposes = sorted(purpose_map.values(), key=lambda x: x["cost_usd"], reverse=True)
    for p in purposes:
        p["cost_usd"] = round(p["cost_usd"], 6)
        p["pct_cost"] = round(p["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0

    models = []
    for m in sorted(model_map.values(), key=lambda x: x["cost_usd"], reverse=True):
        if m["model"] == "unknown" and m["prompt_tokens"] == 0 and m["completion_tokens"] == 0:
            continue
        m["cost_usd"] = round(m["cost_usd"], 6)
        m["pct_cost"] = round(m["cost_usd"] / total_cost * 100, 1) if total_cost else 0.0
        models.append(m)

    skill_total = sum(r["cost_usd"] for r in skill_rows)
    skills = [
        {
            "skill": r["skill"],
            "cost_usd": round(r["cost_usd"], 6),
            "requests": r["requests"],
            "avg_cost": round(r["cost_usd"] / r["requests"], 6) if r["requests"] else 0.0,
            "pct_cost": round(r["cost_usd"] / skill_total * 100, 1) if skill_total else 0.0,
        }
        for r in skill_rows
    ]
    users = [
        {
            "user_id": r["user_id"],
            "cost_usd": round(r["cost_usd"], 6),
            "requests": r["requests"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
        }
        for r in user_rows
    ]
    days = [
        {
            "date": str(r["date"]),
            "cost_usd": round(r["cost_usd"], 6),
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "requests": r["requests"],
        }
        for r in trend_rows
    ]
    return {
        "summary": _shape_summary(summary_row, period, start, end),
        "trends": {"days": days},
        "purposes": purposes,
        "models": models,
        "skills": skills,
        "users": users,
        "insights": _evaluate_insights(insight_bag),
    }


@router.get("/dashboard")
async def finops_dashboard(
    request: Request,
    period: int = 7,
    tenant_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """Every FinOps panel in one response.

    The page used to fan out to summary, trends, kpis, by-skill, by-user, and
    insights. This endpoint keeps those routes for compatibility and gives the
    dashboard a single read.
    """
    tenants = _tenant_scope(request, tenant_id)
    try:
        return await asyncio.to_thread(_dashboard_payload, period, tenants, start, end)
    except Exception as exc:
        logger.warning("finops/dashboard error (non-fatal): %s", exc)
        return {
            "summary": _empty_summary(period, start, end),
            "trends": {"days": []},
            "purposes": [],
            "models": [],
            "skills": [],
            "users": [],
            "insights": [],
        }
