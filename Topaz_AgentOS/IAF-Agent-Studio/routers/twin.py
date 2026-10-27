"""
IAF Agent Studio — Digital Twin Router

Operational Digital Twin endpoints:
  - /api/twin/summary, /api/twin/skills, /api/twin/hitl, /api/twin/trends
  - /api/twin/ar, /api/twin/ap, /api/twin/exceptions, /api/twin/feed
  - /api/twin/drill/ar, /api/twin/drill/ap, /api/twin/drill/exceptions, /api/twin/drill/task
  - /api/twin/process_health
  - /api/twin/optimization, /api/twin/optimization/analyze, /api/twin/optimization/status/{job_id}

/ws/dashboard and /ws/twin are implemented in routers/approvals.py (see note below).
"""

import asyncio
import difflib
import logging
import re
import sqlite3 as _sql
import time as _time
import uuid
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks

from shared.config import SERVER_DIR, DATA_ROOT, TENANT_ID, AGENT_ID, SKILLS_PATH

logger = logging.getLogger("iaf_server")
router = APIRouter()

_process_health_cache: dict = {"data": None, "ts": 0.0}
_PROCESS_HEALTH_TTL = 15.0  # seconds

_esaa_cache: dict = {"data": None, "ts": 0.0}
_ESAA_TTL = 15.0  # seconds — Tier 1 cache
_esaa_tier2_cache: dict = {"data": None, "ts": 0.0}
_ESAA_TIER2_TTL = 14400.0  # 4 hours — Tier 2 LLM cache
_esaa_jobs: Dict[str, dict] = {}  # {job_id: {"status": "...", "result": ...}}

_entity_match_cache: Dict[str, dict] = {}   # "(name|type)" → match result
_ENTITY_MATCH_TTL = 3600.0                  # 1 hour

_MEMORY_ROOT = str(
    SERVER_DIR / DATA_ROOT / "tenants" / TENANT_ID / "agents" / AGENT_ID / "memory"
)


def _get_twin_db() -> str:
    """Resolve path to twin_telemetry.db."""
    return str(SERVER_DIR / DATA_ROOT / "tenants" / TENANT_ID / "shared" / "databases" / "twin_telemetry.db")


def _get_ar_db() -> str:
    """Resolve path to ar_receivables.db."""
    return str(SERVER_DIR / DATA_ROOT / "tenants" / TENANT_ID / "shared" / "databases" / "ar_receivables.db")


def _get_ap_db() -> str:
    """Resolve path to ap_regular.db."""
    return str(SERVER_DIR / DATA_ROOT / "tenants" / TENANT_ID / "shared" / "databases" / "ap_regular.db")


# /ws/dashboard and /ws/twin live in routers/approvals.py (included first); do not duplicate them here.


@router.get("/api/twin/summary")
async def twin_summary(days: int = 30):
    """
    Executive summary: KPI cards, sparklines, and period comparisons.
    Returns the last N days of daily snapshots plus computed deltas.
    """
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        rows = cur.execute(
            "SELECT * FROM daily_snapshots ORDER BY snapshot_date DESC LIMIT ?",
            (days,),
        ).fetchall()
        conn.close()

        if not rows:
            return {"snapshots": [], "kpis": {}, "period": days}

        snapshots = [dict(r) for r in rows]  # newest first

        latest = snapshots[0]
        # Comparison: average of previous 7 days (or whatever is available)
        prev_days = snapshots[1:8]

        def avg(field):
            vals = [d[field] for d in prev_days if d.get(field) is not None]
            return sum(vals) / len(vals) if vals else None

        def delta(current, previous):
            if previous is None or previous == 0:
                return None
            return round((current - previous) / abs(previous) * 100, 1)

        kpis = {
            "total_tasks": latest["total_tasks"],
            "completed_tasks": latest["completed_tasks"],
            "error_rate": round(latest["error_tasks"] / max(latest["total_tasks"], 1) * 100, 1),
            "avg_latency_ms": latest["avg_latency_ms"],
            "p95_latency_ms": latest["p95_latency_ms"],
            "unique_users": latest["unique_users"],
            "top_skill": latest["top_skill"],
            "hitl_count": latest["hitl_count"],
            "hitl_approval_rate": latest["hitl_approval_rate"],
            "ar_total_outstanding": latest["ar_total_outstanding"],
            "ar_overdue": latest["ar_overdue"],
            "ar_dso_days": latest["ar_dso_days"],
            "ap_open_amount": latest["ap_open_amount"],
            "ap_overdue": latest["ap_overdue"],
            # Deltas vs prior 7-day average
            "tasks_delta": delta(latest["total_tasks"], avg("total_tasks")),
            "latency_delta": delta(latest["avg_latency_ms"], avg("avg_latency_ms")),
            "error_rate_delta": delta(
                latest["error_tasks"] / max(latest["total_tasks"], 1),
                avg("error_tasks") / max(avg("total_tasks") or 1, 1) if avg("total_tasks") else None,
            ),
            "ar_overdue_delta": delta(latest["ar_overdue"], avg("ar_overdue")),
            "dso_delta": delta(latest["ar_dso_days"], avg("ar_dso_days")),
        }

        return {
            "kpis": kpis,
            "snapshots": list(reversed(snapshots)),  # chronological for charts
            "period": days,
            "as_of": latest["snapshot_date"],
        }
    except Exception as e:
        logger.error("twin_summary failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred", "snapshots": [], "kpis": {}}


@router.get("/api/twin/skills")
async def twin_skill_breakdown(days: int = 30):
    """Skill usage heatmap data: invocations, success rate, avg latency per skill."""
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        rows = cur.execute("""
            SELECT skill,
                   COUNT(*)                        as invocations,
                   SUM(success)                    as successes,
                   ROUND(AVG(latency_ms), 0)       as avg_latency_ms,
                   ROUND(SUM(success)*100.0/COUNT(*), 1) as success_rate,
                   SUM(tool_calls)                 as total_tool_calls
            FROM skill_usage
            WHERE timestamp >= date('now', ? || ' days')
            GROUP BY skill
            ORDER BY invocations DESC
        """, (f"-{days}",)).fetchall()
        conn.close()

        return {"skills": [dict(r) for r in rows], "period": days}
    except Exception as e:
        logger.error("twin_skill_breakdown failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred", "skills": []}


@router.get("/api/twin/hitl")
async def twin_hitl_stats(days: int = 30):
    """HITL analytics: approval/rejection rates, avg wait time, by urgency & skill."""
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        overall = cur.execute("""
            SELECT action_type,
                   COUNT(*)                     as count,
                   ROUND(AVG(wait_time_ms), 0)  as avg_wait_ms,
                   ROUND(AVG(amount), 2)        as avg_amount
            FROM hitl_events
            WHERE timestamp >= date('now', ? || ' days')
            GROUP BY action_type
        """, (f"-{days}",)).fetchall()

        by_urgency = cur.execute("""
            SELECT urgency, COUNT(*) as count,
                   ROUND(AVG(wait_time_ms), 0) as avg_wait_ms
            FROM hitl_events
            WHERE timestamp >= date('now', ? || ' days')
            GROUP BY urgency
            ORDER BY CASE urgency
                WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                WHEN 'medium' THEN 3 ELSE 4 END
        """, (f"-{days}",)).fetchall()

        by_skill = cur.execute("""
            SELECT skill, COUNT(*) as count,
                   SUM(CASE WHEN action_type='approve' THEN 1 ELSE 0 END) as approved,
                   ROUND(AVG(wait_time_ms), 0) as avg_wait_ms
            FROM hitl_events
            WHERE timestamp >= date('now', ? || ' days')
            GROUP BY skill
            ORDER BY count DESC
        """, (f"-{days}",)).fetchall()

        conn.close()

        return {
            "overall": [dict(r) for r in overall],
            "by_urgency": [dict(r) for r in by_urgency],
            "by_skill": [dict(r) for r in by_skill],
            "period": days,
        }
    except Exception as e:
        logger.error("twin_hitl_stats failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/trends")
async def twin_trends(days: int = 60):
    """Time-series data for charts: daily volume, latency, error rate, business KPIs."""
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        rows = cur.execute("""
            SELECT snapshot_date, total_tasks, completed_tasks, error_tasks,
                   avg_latency_ms, p95_latency_ms, unique_users, hitl_count,
                   ar_total_outstanding, ar_overdue, ar_dso_days,
                   ap_open_amount, ap_overdue
            FROM daily_snapshots
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (days,)).fetchall()
        conn.close()

        return {
            "series": [dict(r) for r in reversed(rows)],  # chronological
            "period": days,
        }
    except Exception as e:
        logger.error("twin_trends failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred", "series": []}


@router.get("/api/twin/ar")
async def twin_ar_snapshot():
    """Live AR snapshot: aging breakdown, top overdue customers, DSO."""
    try:
        conn = _sql.connect(_get_ar_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        aging = cur.execute("""
            SELECT aging_bucket, COUNT(*) as count, ROUND(SUM(amount), 2) as total
            FROM receivables WHERE status != 'closed'
            GROUP BY aging_bucket
            ORDER BY aging_bucket
        """).fetchall()

        statuses = cur.execute("""
            SELECT status, COUNT(*) as count, ROUND(SUM(amount), 2) as total
            FROM receivables GROUP BY status ORDER BY total DESC
        """).fetchall()

        top_overdue = cur.execute("""
            SELECT r.customer_name, c.risk_rating, COUNT(*) as invoices,
                   ROUND(SUM(r.amount), 2) as total_overdue,
                   MAX(r.days_overdue) as max_days
            FROM receivables r
            JOIN customers c ON r.customer_id = c.customer_id
            WHERE r.status != 'closed' AND r.days_overdue > 0
            GROUP BY r.customer_id
            ORDER BY total_overdue DESC
            LIMIT 10
        """).fetchall()

        dso_row = cur.execute("""
            SELECT ROUND(
                SUM(CASE WHEN status != 'closed' THEN amount ELSE 0 END) /
                NULLIF(SUM(amount) / 365.0, 0), 1
            ) as dso_days FROM receivables
        """).fetchone()

        totals = cur.execute("""
            SELECT ROUND(SUM(CASE WHEN status != 'closed' THEN amount ELSE 0 END), 2) as outstanding,
                   ROUND(SUM(CASE WHEN status != 'closed' AND days_overdue > 0 THEN amount ELSE 0 END), 2) as overdue
            FROM receivables
        """).fetchone()

        conn.close()

        return {
            "aging": [dict(r) for r in aging],
            "statuses": [dict(r) for r in statuses],
            "top_overdue": [dict(r) for r in top_overdue],
            "dso_days": dso_row["dso_days"] if dso_row else None,
            "total_outstanding": totals["outstanding"] if totals else 0,
            "total_overdue": totals["overdue"] if totals else 0,
        }
    except Exception as e:
        logger.error("twin_ar_snapshot failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/ap")
async def twin_ap_snapshot():
    """Live AP snapshot: open amounts, overdue, vendor distribution."""
    try:
        conn = _sql.connect(_get_ap_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        totals = cur.execute("""
            SELECT
                ROUND(SUM(CASE WHEN status='open' AND transaction_type='invoice' THEN amount ELSE 0 END), 2) as open_amount,
                ROUND(SUM(CASE WHEN status='open' AND transaction_type='invoice'
                    AND julianday('now') > julianday(due_date) THEN amount ELSE 0 END), 2) as overdue_amount,
                COUNT(CASE WHEN status='open' AND transaction_type='invoice' THEN 1 END) as open_count,
                COUNT(CASE WHEN requires_correction=1 THEN 1 END) as corrections_pending
            FROM ap_transactions
        """).fetchone()

        aging = cur.execute("""
            SELECT
                CASE
                    WHEN julianday('now') - julianday(due_date) <= 30 THEN '0-30'
                    WHEN julianday('now') - julianday(due_date) <= 60 THEN '30-60'
                    WHEN julianday('now') - julianday(due_date) <= 90 THEN '60-90'
                    ELSE '90+'
                END as aging_bucket,
                COUNT(*) as count,
                ROUND(SUM(amount), 2) as total
            FROM ap_transactions
            WHERE status = 'open' AND transaction_type = 'invoice'
            GROUP BY aging_bucket
        """).fetchall()

        top_vendors = cur.execute("""
            SELECT vendor_name, COUNT(*) as invoices,
                   ROUND(SUM(amount), 2) as open_amount
            FROM ap_transactions
            WHERE status = 'open' AND transaction_type = 'invoice'
            GROUP BY vendor_id
            ORDER BY open_amount DESC
            LIMIT 5
        """).fetchall()

        discrepancies = cur.execute("""
            SELECT account_code, account_name, balance, discrepancy_detail
            FROM ap_account_balances
            WHERE discrepancy_flag = 1
        """).fetchall()

        conn.close()

        return {
            "open_amount": totals["open_amount"] if totals else 0,
            "overdue_amount": totals["overdue_amount"] if totals else 0,
            "open_count": totals["open_count"] if totals else 0,
            "corrections_pending": totals["corrections_pending"] if totals else 0,
            "aging": [dict(r) for r in aging],
            "top_vendors": [dict(r) for r in top_vendors],
            "discrepancies": [dict(r) for r in discrepancies],
        }
    except Exception as e:
        logger.error("twin_ap_snapshot failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/exceptions")
async def twin_exceptions():
    """Combined exception view across AP corrections, debit balances, AR disputes."""
    try:
        items = []

        try:
            conn = _sql.connect(_get_ap_db())
            conn.row_factory = _sql.Row
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT c.correction_id, c.original_transaction_id, c.correction_type,
                       c.original_value, c.corrected_value, c.status, c.created_date,
                       c.reason
                FROM corrections_log c
                ORDER BY c.created_date DESC LIMIT 30
            """).fetchall()
            for r in rows:
                try:
                    amt = abs(float(r["original_value"]) - float(r["corrected_value"]))
                except (ValueError, TypeError) as e:
                    logger.warning("AP correction amount parse failed for correction_id %s: %s", r["correction_id"], e)
                    amt = 0
                items.append({
                    "source": "AP",
                    "type": "correction",
                    "subtype": r["correction_type"],
                    "amount": amt,
                    "status": r["status"],
                    "date": r["created_date"],
                    "entity": r["reason"] or r["original_transaction_id"],
                    "id": r["correction_id"],
                })

            debits = cur.execute("""
                SELECT d.id, d.customer_name, d.vendor_id, d.debit_amount,
                       d.status, d.invoice_date, d.notes, d.aging_bucket
                FROM debit_balances d
                ORDER BY d.debit_amount DESC LIMIT 20
            """).fetchall()
            for r in debits:
                items.append({
                    "source": "AP",
                    "type": "debit_balance",
                    "subtype": r["aging_bucket"] or r["notes"],
                    "amount": r["debit_amount"],
                    "status": r["status"],
                    "date": r["invoice_date"],
                    "entity": r["customer_name"] or r["vendor_id"],
                    "id": str(r["id"]),
                })
            conn.close()
        except Exception as e:
            logger.warning("twin_exceptions: AP corrections/debit fetch failed: %s", e)

        try:
            arconn = _sql.connect(_get_ar_db())
            arconn.row_factory = _sql.Row
            arcur = arconn.cursor()
            disputes = arcur.execute("""
                SELECT r.invoice_number, r.amount_usd, r.days_overdue,
                       r.aging_bucket, c.customer_name, c.risk_rating
                FROM receivables r
                JOIN customers c ON r.customer_id = c.customer_id
                WHERE r.days_overdue > 60 OR c.risk_rating = 'high'
                ORDER BY r.days_overdue DESC LIMIT 20
            """).fetchall()
            for r in disputes:
                items.append({
                    "source": "AR",
                    "type": "overdue_risk",
                    "subtype": r["aging_bucket"],
                    "amount": r["amount_usd"],
                    "status": r["risk_rating"],
                    "date": None,
                    "entity": r["customer_name"],
                    "id": r["invoice_number"],
                })
            arconn.close()
        except Exception as e:
            logger.warning("twin_exceptions: AR disputes fetch failed: %s", e)

        items.sort(key=lambda x: abs(x.get("amount") or 0), reverse=True)
        summary = {
            "ap_corrections": len([i for i in items if i["type"] == "correction"]),
            "ap_debits": len([i for i in items if i["type"] == "debit_balance"]),
            "ar_risks": len([i for i in items if i["type"] == "overdue_risk"]),
            "total": len(items),
        }
        return {"summary": summary, "items": items[:50]}
    except Exception as e:
        logger.error("twin_exceptions failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/feed")
async def twin_feed():
    """Real-time process telemetry feed — latest task events + HITL events."""
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()
        tasks = cur.execute("""
            SELECT event_type, skill, latency_ms,
                   user_id, error_message, timestamp
            FROM task_events
            ORDER BY timestamp DESC LIMIT 30
        """).fetchall()
        hitls = cur.execute("""
            SELECT action_type, urgency, skill, wait_time_ms,
                   user_id, timestamp
            FROM hitl_events
            ORDER BY timestamp DESC LIMIT 15
        """).fetchall()
        conn.close()

        feed = []
        for t in tasks:
            feed.append({
                "kind": "task",
                "event": t["event_type"],
                "agent": t["user_id"],
                "skill": t["skill"],
                "status": t["event_type"],
                "latency_ms": t["latency_ms"],
                "user": t["user_id"],
                "error": t["error_message"],
                "ts": t["timestamp"],
            })
        for h in hitls:
            feed.append({
                "kind": "hitl",
                "event": h["action_type"],
                "agent": h["user_id"],
                "skill": h["skill"],
                "status": h["action_type"],
                "latency_ms": h["wait_time_ms"],
                "user": h["user_id"],
                "error": None,
                "ts": h["timestamp"],
            })
        feed.sort(key=lambda x: x["ts"] or "", reverse=True)
        return {"feed": feed[:40]}
    except Exception as e:
        logger.error("twin_feed failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/drill/ar")
async def twin_drill_ar(metric: str = "outstanding"):
    """Drill-down detail for AR KPI cards — aging, customers, invoices."""
    try:
        conn = _sql.connect(_get_ar_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        aging = cur.execute("""
            SELECT aging_bucket, COUNT(*) as count, SUM(amount_usd) as total,
                   AVG(amount_usd) as avg_amount, MAX(days_overdue) as max_days
            FROM receivables GROUP BY aging_bucket ORDER BY MIN(days_overdue)
        """).fetchall()

        if metric in ("overdue", "ar_overdue"):
            customers = cur.execute("""
                SELECT c.customer_name, c.risk_rating, c.credit_limit,
                       SUM(r.amount_usd) as total, COUNT(*) as invoices,
                       MAX(r.days_overdue) as max_days
                FROM receivables r JOIN customers c ON r.customer_id = c.customer_id
                WHERE r.days_overdue > 0
                GROUP BY c.customer_id ORDER BY total DESC LIMIT 15
            """).fetchall()
        elif metric == "dso":
            customers = cur.execute("""
                SELECT c.customer_name, c.risk_rating,
                       AVG(r.days_overdue) as avg_days, SUM(r.amount_usd) as total,
                       COUNT(*) as invoices
                FROM receivables r JOIN customers c ON r.customer_id = c.customer_id
                GROUP BY c.customer_id ORDER BY avg_days DESC LIMIT 15
            """).fetchall()
        else:
            customers = cur.execute("""
                SELECT c.customer_name, c.risk_rating, c.credit_limit,
                       SUM(r.amount_usd) as total, COUNT(*) as invoices,
                       MAX(r.days_overdue) as max_days
                FROM receivables r JOIN customers c ON r.customer_id = c.customer_id
                GROUP BY c.customer_id ORDER BY total DESC LIMIT 15
            """).fetchall()

        invoices = cur.execute("""
            SELECT r.invoice_number, r.amount_usd, r.days_overdue, r.aging_bucket,
                   r.status, c.customer_name, c.risk_rating
            FROM receivables r JOIN customers c ON r.customer_id = c.customer_id
            ORDER BY r.amount_usd DESC LIMIT 20
        """).fetchall()

        conn.close()
        return {
            "metric": metric,
            "aging": [dict(r) for r in aging],
            "customers": [dict(r) for r in customers],
            "invoices": [dict(r) for r in invoices],
        }
    except Exception as e:
        logger.error("twin_drill_ar failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/drill/ap")
async def twin_drill_ap(metric: str = "open"):
    """Drill-down detail for AP KPI cards — aging, vendors, transactions."""
    try:
        conn = _sql.connect(_get_ap_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        aging = cur.execute("""
            SELECT aging_bucket, COUNT(*) as count, SUM(amount) as total,
                   AVG(amount) as avg_amount
            FROM ap_transactions WHERE status IN ('open','overdue')
            GROUP BY aging_bucket ORDER BY MIN(aging_days)
        """).fetchall()

        if metric in ("overdue", "ap_overdue"):
            vendors = cur.execute("""
                SELECT v.vendor_name, v.vendor_id, SUM(t.amount) as total,
                       COUNT(*) as invoices, MAX(t.aging_days) as max_days
                FROM ap_transactions t JOIN vendors v ON t.vendor_id = v.vendor_id
                WHERE t.status = 'overdue'
                GROUP BY t.vendor_id ORDER BY total DESC LIMIT 15
            """).fetchall()
        else:
            vendors = cur.execute("""
                SELECT v.vendor_name, v.vendor_id, SUM(t.amount) as total,
                       COUNT(*) as invoices, MAX(t.aging_days) as max_days
                FROM ap_transactions t JOIN vendors v ON t.vendor_id = v.vendor_id
                WHERE t.status IN ('open','overdue')
                GROUP BY t.vendor_id ORDER BY total DESC LIMIT 15
            """).fetchall()

        transactions = cur.execute("""
            SELECT t.transaction_id, t.invoice_number, t.amount, t.aging_days,
                   t.aging_bucket, t.status, v.vendor_name
            FROM ap_transactions t JOIN vendors v ON t.vendor_id = v.vendor_id
            WHERE t.status IN ('open','overdue')
            ORDER BY t.amount DESC LIMIT 20
        """).fetchall()

        discrepancies = cur.execute("""
            SELECT account_code, account_name, balance, discrepancy_detail
            FROM ap_account_balances WHERE discrepancy_flag = 1
        """).fetchall()

        conn.close()
        return {
            "metric": metric,
            "aging": [dict(r) for r in aging],
            "vendors": [dict(r) for r in vendors],
            "transactions": [dict(r) for r in transactions],
            "discrepancies": [dict(r) for r in discrepancies],
        }
    except Exception as e:
        logger.error("twin_drill_ap failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/drill/exceptions")
async def twin_drill_exceptions(type: str = "all"):
    """Drill-down for exception details by type."""
    try:
        items = []
        if type in ("all", "correction"):
            try:
                conn = _sql.connect(_get_ap_db())
                conn.row_factory = _sql.Row
                rows = conn.execute("""
                    SELECT correction_id, original_transaction_id, correction_type,
                           original_value, corrected_value, reason, status,
                           created_by, approved_by, created_date, posted_date
                    FROM corrections_log ORDER BY created_date DESC
                """).fetchall()
                for r in rows:
                    items.append({**dict(r), "source": "AP", "category": "correction"})
                conn.close()
            except Exception as e:
                logger.warning("twin_drill_exceptions: AP corrections fetch failed: %s", e)

        if type in ("all", "debit"):
            try:
                conn = _sql.connect(_get_ap_db())
                conn.row_factory = _sql.Row
                rows = conn.execute("""
                    SELECT id, customer_name, vendor_id, debit_amount, invoice_number,
                           invoice_date, due_date, aging_days, aging_bucket, status, notes
                    FROM debit_balances ORDER BY debit_amount DESC
                """).fetchall()
                for r in rows:
                    items.append({**dict(r), "source": "AP", "category": "debit_balance"})
                conn.close()
            except Exception as e:
                logger.warning("twin_drill_exceptions: AP debit balances fetch failed: %s", e)

        if type in ("all", "ar_risk"):
            try:
                conn = _sql.connect(_get_ar_db())
                conn.row_factory = _sql.Row
                rows = conn.execute("""
                    SELECT r.invoice_number, r.amount_usd, r.days_overdue,
                           r.aging_bucket, r.status, c.customer_name,
                           c.risk_rating, c.credit_limit
                    FROM receivables r JOIN customers c ON r.customer_id = c.customer_id
                    WHERE r.days_overdue > 60 OR c.risk_rating = 'high'
                    ORDER BY r.amount_usd DESC
                """).fetchall()
                for r in rows:
                    items.append({**dict(r), "source": "AR", "category": "overdue_risk"})
                conn.close()
            except Exception as e:
                logger.warning("twin_drill_exceptions: AR risk fetch failed: %s", e)

        return {"type": type, "count": len(items), "items": items}
    except Exception as e:
        logger.error("twin_drill_exceptions failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/twin/drill/task")
async def twin_drill_task(agent: str = None, skill: str = None, status: str = None):
    """Drill-down for task telemetry — filter by agent, skill, or status."""
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        params = [agent, agent, skill, skill, status, status]

        tasks = cur.execute("""
            SELECT event_type, skill, latency_ms,
                   user_id, error_message, timestamp
            FROM task_events
            WHERE (? IS NULL OR user_id = ?)
              AND (? IS NULL OR skill = ?)
              AND (? IS NULL OR event_type = ?)
            ORDER BY timestamp DESC LIMIT 50
        """, params).fetchall()

        stats = cur.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN event_type='task_completed' THEN 1 ELSE 0 END) as completed,
                   SUM(CASE WHEN event_type='task_error' THEN 1 ELSE 0 END) as errors,
                   AVG(latency_ms) as avg_latency,
                   MIN(timestamp) as first_event,
                   MAX(timestamp) as last_event
            FROM task_events
            WHERE (? IS NULL OR user_id = ?)
              AND (? IS NULL OR skill = ?)
              AND (? IS NULL OR event_type = ?)
        """, params).fetchone()

        conn.close()
        return {
            "filter": {"agent": agent, "skill": skill, "status": status},
            "stats": dict(stats) if stats else {},
            "tasks": [dict(t) for t in tasks],
        }
    except Exception as e:
        logger.error("twin_drill_task failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


def _load_kpi_yaml() -> list:
    """Load kpi_queries.yaml from the tenant shared directory. Returns list of KPI defs."""
    try:
        kpi_path = SERVER_DIR / DATA_ROOT / "tenants" / TENANT_ID / "shared" / "kpi_queries.yaml"
        if kpi_path.exists():
            with open(kpi_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            return data.get("kpi_queries") or []
    except Exception as exc:
        logger.warning("Could not load kpi_queries.yaml: %s", exc)
    return []


def _kpi_actuals_registry() -> dict:
    """
    Returns a dict keyed by (skill_name, kpi_name) -> callable(dbs) -> (value, source).
    Built dynamically from kpi_queries.yaml — no domain hardcoding in code.
    `dbs` is a dict with open sqlite3 connections: {"ar": conn, "ap": conn, "twin": conn}.
    """
    def _q(conn, sql):
        """Run query, return first column of first row or None."""
        try:
            row = conn.execute(sql).fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.warning("KPI registry query failed: %s", e)
            return None

    # Named compound functions referenced by kpi_queries.yaml `function` field
    _compound_functions = {
        "period_close_checklist": _period_close_checklist,
        "period_close_open_items": _period_close_open_items,
    }

    registry = {}

    for entry in _load_kpi_yaml():
        skill = entry.get("skill")
        name = entry.get("name")
        db_key = entry.get("db_key")
        sql = entry.get("sql")
        fn_name = entry.get("function")

        if not skill or not name:
            continue

        if fn_name and fn_name in _compound_functions:
            registry[(skill, name)] = _compound_functions[fn_name]
        elif sql and db_key and db_key != "compound":
            _sql_str = sql.strip()
            _db = db_key
            registry[(skill, name)] = lambda dbs, _s=_sql_str, _d=_db: (
                _q(dbs[_d], _s), f"{_d}.db"
            )
        else:
            registry[(skill, name)] = lambda dbs: (None, "N/A")

    return registry

    return registry


def _period_close_checklist(dbs) -> tuple:
    """Run 7 period-close checks, return (completion %, source)."""
    checks_passed = 0
    total_checks = 7
    try:
        ap = dbs["ap"]
        ar = dbs["ar"]
        # 1. No pending AP corrections
        if (ap.execute("SELECT COUNT(*) FROM corrections_log WHERE status = 'pending_approval'").fetchone()[0] or 0) == 0:
            checks_passed += 1
        # 2. All AP accounts reconciled (no discrepancies)
        if (ap.execute("SELECT COUNT(*) FROM ap_account_balances WHERE discrepancy_flag = 1").fetchone()[0] or 0) == 0:
            checks_passed += 1
        # 3. No unposted AP transactions requiring correction
        if (ap.execute("SELECT COUNT(*) FROM ap_transactions WHERE requires_correction = 1 AND status != 'posted'").fetchone()[0] or 0) == 0:
            checks_passed += 1
        # 4. AP overdue amount below threshold ($50K)
        overdue = ap.execute("SELECT COALESCE(SUM(amount), 0) FROM ap_transactions WHERE status='open' AND transaction_type='invoice' AND julianday('now') > julianday(due_date)").fetchone()[0]
        if (overdue or 0) < 50000:
            checks_passed += 1
        # 5. No high-risk AR overdue > 90 days
        if (ar.execute("SELECT COUNT(*) FROM receivables r JOIN customers c ON r.customer_id = c.customer_id WHERE r.days_overdue > 90 AND c.risk_rating = 'high'").fetchone()[0] or 0) == 0:
            checks_passed += 1
        # 6. AR DSO within target (< 45 days)
        dso = ar.execute("SELECT ROUND(SUM(CASE WHEN status != 'closed' THEN amount ELSE 0 END) / NULLIF(SUM(amount) / 365.0, 0), 1) FROM receivables").fetchone()[0]
        if dso is not None and dso < 45:
            checks_passed += 1
        # 7. No disputed AR amounts > $100K
        disputed = ar.execute("SELECT COALESCE(SUM(amount), 0) FROM receivables WHERE status = 'disputed'").fetchone()[0]
        if (disputed or 0) < 100000:
            checks_passed += 1
    except Exception as e:
        logger.warning("_period_close_checklist query error: %s", e)
    pct = round(checks_passed * 100.0 / total_checks, 1) if total_checks > 0 else None
    return (pct, "ap_regular.db + ar_receivables.db")


def _period_close_open_items(dbs) -> tuple:
    """Count total open items across AP and AR databases."""
    try:
        ap_open = dbs["ap"].execute("SELECT COUNT(*) FROM ap_transactions WHERE status = 'open'").fetchone()[0] or 0
        ar_open = dbs["ar"].execute("SELECT COUNT(*) FROM receivables WHERE status != 'closed'").fetchone()[0] or 0
        return (ap_open + ar_open, "ap_regular.db + ar_receivables.db")
    except Exception as e:
        logger.warning("_period_close_open_items query error: %s", e)
        return (None, "error")


def _compute_kpi_actuals(skill_name: str, kpis: list, dbs: dict) -> list:
    """
    Enrich a list of KPI dicts with 'actual', 'status', 'source' fields.
    Status: 'green' = on target, 'amber' = within 25%, 'red' = >25% off, 'na' = no data.
    """
    registry = _kpi_actuals_registry()
    enriched = []
    for kpi in kpis:
        kpi_copy = dict(kpi)
        key = (skill_name, kpi["name"])
        compute_fn = registry.get(key)
        if compute_fn is None:
            kpi_copy["actual"] = None
            kpi_copy["status"] = "na"
            kpi_copy["source"] = "unmapped"
            enriched.append(kpi_copy)
            continue

        try:
            actual, source = compute_fn(dbs)
        except Exception as e:
            logger.warning("KPI compute failed for %s: %s", key, e)
            actual, source = None, "error"

        kpi_copy["actual"] = actual
        kpi_copy["source"] = source

        target = kpi.get("target")
        direction = kpi.get("direction", "lower_is_better" if kpi.get("unit") in ("days", "count", "minutes") else "higher_is_better")

        if actual is None or source == "N/A":
            kpi_copy["status"] = "na"
        elif target is not None and target > 0:
            if direction == "lower_is_better":
                ratio = actual / target
                if ratio <= 1.0:
                    kpi_copy["status"] = "green"
                elif ratio <= 1.25:
                    kpi_copy["status"] = "amber"
                else:
                    kpi_copy["status"] = "red"
            else:  # higher_is_better
                ratio = actual / target
                if ratio >= 1.0:
                    kpi_copy["status"] = "green"
                elif ratio >= 0.75:
                    kpi_copy["status"] = "amber"
                else:
                    kpi_copy["status"] = "red"
        else:
            # No target — just mark as measured
            kpi_copy["status"] = "measured"

        enriched.append(kpi_copy)
    return enriched


def _parse_skill_business_context() -> list[dict]:
    """Parse business_context from all SKILL.md files with YAML frontmatter."""
    import re
    skills_dir = SERVER_DIR / SKILLS_PATH
    results = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding='utf-8')
            clean = re.sub(r'`{3,}skill\s*', '', text)   # strip ```skill / ````skill
            clean = re.sub(r'`{3,}\s*', '', clean)        # strip closing ``` / ````
            clean = clean.strip().lstrip('`').strip()     # remove any leftover backticks
            m = re.search(r'^---\s*\n(.+?)\n---', clean, re.DOTALL)
            if not m:
                continue
            meta = yaml.safe_load(m.group(1)) or {}
            bc = meta.get("business_context")
            if not bc or not isinstance(bc, dict):
                continue
            if not bc.get("tower"):
                continue  # skip skills without tower classification
            results.append({
                "skill": meta.get("name", skill_dir.name),
                "description": meta.get("description", ""),
                "execution_mode": meta.get("execution_mode", "react"),
                "tower": bc.get("tower", "Other"),
                "process": bc.get("process", ""),
                "subprocess": bc.get("subprocess", ""),
                "entity_type": bc.get("entity_type", ""),
                "cost_per_exception": bc.get("cost_per_exception", 0),
                "sla_days": bc.get("sla_days", 0),
                "kpis": bc.get("kpis", []),
            })
        except Exception as e:
            logger.warning("_parse_skill_business_context: failed to parse %s: %s", skill_dir.name, e)
            continue
    return results


@router.get("/api/twin/process_health")
async def twin_process_health(days: int = 30):
    """
    Process Health by Tower — joins SKILL.md business_context with live telemetry.
    Returns tower-grouped skills with KPI targets, telemetry actuals, and health scores.
    """
    import time as _time

    now = _time.time()
    if (_process_health_cache["data"] is not None
            and (now - _process_health_cache["ts"]) < _PROCESS_HEALTH_TTL):
        return _process_health_cache["data"]

    skill_contexts = _parse_skill_business_context()

    dbs = {}
    try:
        dbs["ar"] = _sql.connect(_get_ar_db())
        dbs["ar"].row_factory = _sql.Row
    except Exception as e:
        logger.warning("process_health: could not open AR database: %s", e)
    try:
        dbs["ap"] = _sql.connect(_get_ap_db())
        dbs["ap"].row_factory = _sql.Row
    except Exception as e:
        logger.warning("process_health: could not open AP database: %s", e)
    try:
        dbs["twin"] = _sql.connect(_get_twin_db())
        dbs["twin"].row_factory = _sql.Row
    except Exception as e:
        logger.warning("process_health: could not open twin telemetry database: %s", e)

    telemetry_map = {}
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        rows = conn.execute("""
            SELECT skill,
                   COUNT(*)                              as invocations,
                   SUM(success)                          as successes,
                   ROUND(AVG(latency_ms), 0)             as avg_latency_ms,
                   ROUND(SUM(success)*100.0/COUNT(*), 1) as success_rate,
                   SUM(tool_calls)                       as total_tool_calls
            FROM skill_usage
            WHERE timestamp >= date('now', ? || ' days')
            GROUP BY skill
        """, (f"-{days}",)).fetchall()
        conn.close()
        for r in rows:
            telemetry_map[r["skill"]] = dict(r)
    except Exception as e:
        logger.warning("process_health: telemetry map query failed: %s", e)

    error_map = {}
    try:
        conn = _sql.connect(_get_twin_db())
        conn.row_factory = _sql.Row
        rows = conn.execute("""
            SELECT skill,
                   SUM(CASE WHEN event_type='task_error' THEN 1 ELSE 0 END) as errors,
                   COUNT(*) as total
            FROM task_events
            WHERE timestamp >= date('now', ? || ' days')
              AND skill IS NOT NULL AND skill != ''
            GROUP BY skill
        """, (f"-{days}",)).fetchall()
        conn.close()
        for r in rows:
            error_map[r["skill"]] = {"errors": r["errors"], "total": r["total"]}
    except Exception as e:
        logger.warning("process_health: error map query failed: %s", e)

    # 5. Merge and group by tower (now with KPI actuals)
    towers = {}  # tower -> { skills: [], totals }
    for sc in skill_contexts:
        sname = sc["skill"]
        tel = telemetry_map.get(sname, {})
        err = error_map.get(sname, {})

        enriched_kpis = _compute_kpi_actuals(sname, sc.get("kpis", []), dbs)

        # KPI compliance score (% of KPIs at green status)
        scorable = [k for k in enriched_kpis if k["status"] in ("green", "amber", "red")]
        kpi_green = sum(1 for k in scorable if k["status"] == "green")
        kpi_compliance = round(kpi_green * 100.0 / len(scorable)) if scorable else 100

        # Health score (0-100): success_rate 40%, latency penalty 20% (0-10s scale), KPI compliance 40%.
        sr = tel.get("success_rate", 100) if tel.get("success_rate") is not None else 100
        lat = tel.get("avg_latency_ms", 0) or 0
        lat_score = max(0, min(100, 100 - ((lat - 1000) / 9000) * 100)) if lat > 0 else 100
        health = round(sr * 0.4 + lat_score * 0.2 + kpi_compliance * 0.4)
        health = max(0, min(100, health))

        skill_entry = {
            **sc,
            "kpis": enriched_kpis,
            "invocations": tel.get("invocations", 0),
            "success_rate": tel.get("success_rate", None),
            "avg_latency_ms": tel.get("avg_latency_ms", None),
            "errors": err.get("errors", 0),
            "total_tasks": err.get("total", 0),
            "health_score": health,
            "kpi_compliance": kpi_compliance,
            "kpis_green": kpi_green,
            "kpis_scorable": len(scorable),
        }

        tower = sc["tower"]
        if tower not in towers:
            towers[tower] = {
                "tower": tower,
                "skills": [],
                "total_invocations": 0,
                "total_errors": 0,
                "total_cost_exposure": 0,
                "avg_health": 0,
                "kpis_on_target": 0,
                "kpis_total": 0,
            }
        towers[tower]["skills"].append(skill_entry)
        towers[tower]["total_invocations"] += skill_entry["invocations"]
        towers[tower]["total_errors"] += skill_entry["errors"]
        towers[tower]["total_cost_exposure"] += skill_entry["errors"] * sc["cost_per_exception"]
        towers[tower]["kpis_on_target"] += kpi_green
        towers[tower]["kpis_total"] += len(scorable)

    for conn in dbs.values():
        try:
            conn.close()
        except Exception as e:
            logger.warning("process_health: error closing DB connection: %s", e)

    for tw in towers.values():
        if tw["skills"]:
            tw["avg_health"] = round(
                sum(s["health_score"] for s in tw["skills"]) / len(tw["skills"])
            )
        tw["skill_count"] = len(tw["skills"])

    order = {"Procure-to-Pay": 0, "Order-to-Cash": 1, "Record-to-Report": 2}
    sorted_towers = sorted(towers.values(), key=lambda t: order.get(t["tower"], 99))

    result = {"towers": sorted_towers, "period": days}
    _process_health_cache["data"] = result
    _process_health_cache["ts"] = now
    return result


def _check_eliminate_rules(ap_db: str, twin_db: str) -> List[dict]:
    """Identify waste/rework/unnecessary steps from AP + telemetry data."""
    recs = []
    try:
        conn = _sql.connect(ap_db)
        # E1: Pending corrections = rework
        row = conn.execute(
            "SELECT COUNT(*) FROM corrections_log WHERE status IN ('pending_approval','approved')"
        ).fetchone()
        pending = row[0] if row else 0
        if pending > 0:
            recs.append({
                "category": "eliminate",
                "rule_id": "E1_CORRECTIONS",
                "title": f"Eliminate AP correction rework ({pending} pending)",
                "detail": (f"{pending} corrections awaiting processing. Each correction costs ~$85 in rework. "
                           f"Root-cause analysis can prevent {int(pending*0.6)} future corrections."),
                "impact": "high" if pending >= 5 else "medium",
                "evidence_ids": [f"corrections_log:{pending}"],
                "evidence_type": "ap_regular.db",
                "estimated_savings_desc": f"${pending * 85}/cycle in rework cost",
                "source": "tier1",
            })

        # E2: Low-value invoices processed manually
        row = conn.execute(
            "SELECT COUNT(*) FROM ap_transactions WHERE transaction_type='invoice' AND amount < 500 AND status='open'"
        ).fetchone()
        low_val = row[0] if row else 0
        if low_val > 3:
            recs.append({
                "category": "eliminate",
                "rule_id": "E2_LOWVAL_REVIEW",
                "title": f"Eliminate manual review of {low_val} low-value invoices (<$500)",
                "detail": (f"{low_val} invoices under $500 are open and being manually processed. "
                           f"Auto-approve or batch-process to remove human touchpoints."),
                "impact": "medium",
                "evidence_ids": [f"ap_transactions:low_val:{low_val}"],
                "evidence_type": "ap_regular.db",
                "estimated_savings_desc": f"{low_val * 15} min manual effort saved/cycle",
                "source": "tier1",
            })

        # E3: Duplicate vendor reconciliation check
        row = conn.execute("""
            SELECT vendor_id, COUNT(*) as cnt FROM ap_transactions
            WHERE transaction_type='invoice' AND status='open'
            GROUP BY vendor_id HAVING cnt >= 3
        """).fetchall()
        if row:
            multi_vendors = len(row)
            total_dupes = sum(r[1] for r in row)
            recs.append({
                "category": "eliminate",
                "rule_id": "E3_VENDOR_DUPES",
                "title": f"Consolidate {total_dupes} invoices across {multi_vendors} multi-invoice vendors",
                "detail": (f"{multi_vendors} vendors have 3+ open invoices each. "
                           f"Batch processing and vendor statement reconciliation can eliminate duplicate handling."),
                "impact": "medium",
                "evidence_ids": [f"ap_transactions:multi_vendor:{multi_vendors}"],
                "evidence_type": "ap_regular.db",
                "estimated_savings_desc": f"{multi_vendors * 20} min reconciliation time saved",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_eliminate_rules: AP rules query failed: %s", e)

    # E4: Rubber-stamp HITL approvals (>90% approval rate on low urgency)
    try:
        conn = _sql.connect(twin_db)
        row = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN action='approved' THEN 1 ELSE 0 END) as approved
            FROM hitl_events
            WHERE urgency IN ('low','informational')
        """).fetchone()
        if row and row[0] and row[0] >= 3:
            total, approved = row[0], row[1] or 0
            rate = round(approved / total * 100, 1) if total > 0 else 0
            if rate >= 80:
                recs.append({
                    "category": "eliminate",
                    "rule_id": "E4_RUBBER_STAMP",
                    "title": f"Remove rubber-stamp approvals ({rate}% auto-approved, low urgency)",
                    "detail": (f"{approved}/{total} low-urgency HITL events were approved without changes. "
                               f"Convert to auto-approve with audit trail."),
                    "impact": "high" if rate >= 95 else "medium",
                    "evidence_ids": [f"hitl_events:low_urgency:{total}"],
                    "evidence_type": "twin_telemetry.db",
                    "estimated_savings_desc": f"{approved * 3} min approval wait time eliminated",
                    "source": "tier1",
                })
        conn.close()
    except Exception as e:
        logger.warning("_check_eliminate_rules: twin HITL rubber-stamp query failed: %s", e)

    impact_order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: (impact_order.get(r.get("impact", "medium"), 1), r.get("rule_id", "")))
    return recs[:3]  # Max 3 per category


def _check_standardize_rules(ar_db: str, ap_db: str) -> List[dict]:
    """Identify inconsistent processes that need standardization."""
    recs = []

    # S1: AR collection inconsistency across customer segments
    try:
        conn = _sql.connect(ar_db)
        rows = conn.execute("""
            SELECT risk_rating, COUNT(*) as cnt,
                   ROUND(AVG(CASE WHEN julianday('now') > julianday(due_date) THEN julianday('now') - julianday(due_date) ELSE 0 END), 1) as avg_overdue_days
            FROM ar_invoices
            WHERE status = 'open'
            GROUP BY risk_rating
            HAVING cnt >= 2
        """).fetchall()
        if len(rows) >= 2:
            lines = [f"{r[0]}: {r[1]} invoices, avg {r[2]}d overdue" for r in rows[:4]]
            recs.append({
                "category": "standardize",
                "rule_id": "S1_AR_SEGMENTS",
                "title": f"Standardize AR collection across {len(rows)} risk segments",
                "detail": (f"Different risk segments show different overdue patterns: "
                           f"{'; '.join(lines)}. Unify collection escalation rules."),
                "impact": "high" if len(rows) >= 3 else "medium",
                "evidence_ids": [f"ar_invoices:risk_segments:{len(rows)}"],
                "evidence_type": "ar_receivables.db",
                "estimated_savings_desc": "5-10 day DSO reduction from unified escalation",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_standardize_rules: S1 AR segments query failed: %s", e)

    # S2: AP matching threshold inconsistency
    try:
        conn = _sql.connect(ap_db)
        row_2way = conn.execute(
            "SELECT COUNT(*) FROM ap_transactions WHERE transaction_type='invoice' AND po_number IS NOT NULL"
        ).fetchone()
        row_no_po = conn.execute(
            "SELECT COUNT(*) FROM ap_transactions WHERE transaction_type='invoice' AND po_number IS NULL"
        ).fetchone()
        with_po = row_2way[0] if row_2way else 0
        without_po = row_no_po[0] if row_no_po else 0
        if with_po > 0 and without_po > 0:
            recs.append({
                "category": "standardize",
                "rule_id": "S2_MATCH_RULES",
                "title": f"Standardize invoice matching ({with_po} PO-backed, {without_po} non-PO)",
                "detail": (f"Mixed matching approaches: {with_po} invoices with PO (3-way match eligible), "
                           f"{without_po} without PO (manual review). Create tiered auto-match rules."),
                "impact": "medium",
                "evidence_ids": [f"ap_transactions:match_mix:{with_po}:{without_po}"],
                "evidence_type": "ap_regular.db",
                "estimated_savings_desc": f"Reduce {without_po} manual match reviews",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_standardize_rules: S2 AP matching query failed: %s", e)

    # S3: HITL urgency distribution skew
    try:
        conn = _sql.connect(_get_twin_db())
        rows = conn.execute("""
            SELECT urgency, COUNT(*) as cnt FROM hitl_events
            GROUP BY urgency
        """).fetchall()
        if rows:
            dist = {r[0]: r[1] for r in rows}
            total = sum(dist.values())
            high_pct = round(dist.get('high', 0) / max(total, 1) * 100)
            low_pct = round(dist.get('low', 0) / max(total, 1) * 100)
            if high_pct > 50 or low_pct > 60:
                recs.append({
                    "category": "standardize",
                    "rule_id": "S3_HITL_THRESHOLDS",
                    "title": f"Re-calibrate HITL urgency ({high_pct}% high, {low_pct}% low)",
                    "detail": (f"HITL urgency distribution is skewed: {dict(dist)}. "
                               f"Standardize threshold criteria to ensure consistent routing."),
                    "impact": "medium",
                    "evidence_ids": [f"hitl_events:urgency_dist:{total}"],
                    "evidence_type": "twin_telemetry.db",
                    "estimated_savings_desc": "Balanced workload, faster critical response",
                    "source": "tier1",
                })
        conn.close()
    except Exception as e:
        logger.warning("_check_standardize_rules: S3 HITL urgency query failed: %s", e)

    return recs[:3]


def _check_augment_rules(ar_db: str, twin_db: str) -> List[dict]:
    """Identify tasks where AI can assist humans (not replace)."""
    recs = []

    # A1: AR aging commentary — high-value overdue needs CFO reporting
    try:
        conn = _sql.connect(ar_db)
        row = conn.execute("""
            SELECT COUNT(*), ROUND(SUM(amount), 2) FROM ar_invoices
            WHERE status = 'open' AND julianday('now') - julianday(due_date) > 30
        """).fetchone()
        aging_count = row[0] if row else 0
        aging_amount = row[1] if row and row[1] else 0
        if aging_count > 0:
            recs.append({
                "category": "augment",
                "rule_id": "A1_AGING_COMMENTARY",
                "title": f"AI-draft aging commentary ({aging_count} invoices, ${aging_amount:,.0f})",
                "detail": (f"{aging_count} invoices over 30 days past due totaling "
                           f"${aging_amount:,.2f}. LLM can auto-draft CFO-ready aging commentaries "
                           f"with customer context and collection status."),
                "impact": "high" if aging_amount > 50000 else "medium",
                "evidence_ids": [f"ar_invoices:aging_30d:{aging_count}"],
                "evidence_type": "ar_receivables.db",
                "estimated_savings_desc": f"{aging_count * 20} min report preparation saved",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_augment_rules: A1 AR aging commentary query failed: %s", e)

    # A2: Smart dunning — LLM-drafted collection emails
    try:
        conn = _sql.connect(ar_db)
        row = conn.execute("""
            SELECT COUNT(*), COUNT(DISTINCT customer_id) FROM ar_invoices
            WHERE status = 'open' AND julianday('now') - julianday(due_date) > 15
        """).fetchone()
        overdue_count = row[0] if row else 0
        customer_count = row[1] if row else 0
        if overdue_count > 2:
            recs.append({
                "category": "augment",
                "rule_id": "A2_SMART_DUNNING",
                "title": f"Smart dunning for {customer_count} customers ({overdue_count} overdue)",
                "detail": (f"{overdue_count} invoices overdue across {customer_count} customers. "
                           f"LLM can draft personalized collection emails with payment links, "
                           f"tone-adjusted per customer relationship and amount."),
                "impact": "medium",
                "evidence_ids": [f"ar_invoices:overdue_15d:{overdue_count}"],
                "evidence_type": "ar_receivables.db",
                "estimated_savings_desc": f"{customer_count * 10} min drafting saved per cycle",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_augment_rules: A2 smart dunning query failed: %s", e)

    # A3: Exception root-cause analysis assisted by AI
    try:
        conn = _sql.connect(twin_db)
        row = conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE event_type = 'task_error'"
        ).fetchone()
        errors = row[0] if row else 0
        if errors >= 3:
            recs.append({
                "category": "augment",
                "rule_id": "A3_EXCEPTION_RCA",
                "title": f"AI-powered exception root-cause analysis ({errors} errors)",
                "detail": (f"{errors} task errors recorded. LLM can analyze error patterns, "
                           f"cluster root causes, and suggest preventive actions per skill."),
                "impact": "medium",
                "evidence_ids": [f"task_events:errors:{errors}"],
                "evidence_type": "twin_telemetry.db",
                "estimated_savings_desc": f"{errors * 5} min manual investigation saved",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_augment_rules: A3 exception RCA query failed: %s", e)

    return recs[:3]


def _check_automate_rules(ap_db: str, ar_db: str, twin_db: str) -> List[dict]:
    """Identify tasks suitable for full end-to-end automation."""
    recs = []

    try:
        conn = _sql.connect(ap_db)
        row = conn.execute("""
            SELECT COUNT(*), ROUND(SUM(amount), 2) FROM ap_transactions
            WHERE transaction_type='invoice' AND status='open' AND amount < 5000
              AND requires_correction = 0
        """).fetchone()
        auto_count = row[0] if row else 0
        auto_amount = row[1] if row and row[1] else 0
        if auto_count > 0:
            recs.append({
                "category": "automate",
                "rule_id": "T1_AUTO_INVOICE",
                "title": f"Auto-process {auto_count} clean invoices (<$5K, ${auto_amount:,.0f} total)",
                "detail": (f"{auto_count} invoices under $5K with no corrections needed. "
                           f"These are straight-through candidates for full automation "
                           f"with post-processing audit sampling."),
                "impact": "high" if auto_count >= 5 else "medium",
                "evidence_ids": [f"ap_transactions:auto_eligible:{auto_count}"],
                "evidence_type": "ap_regular.db",
                "estimated_savings_desc": f"{auto_count * 12} min manual processing eliminated",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_automate_rules: T1 auto-invoice query failed: %s", e)

    try:
        conn = _sql.connect(ar_db)
        row = conn.execute("""
            SELECT COUNT(*) FROM ar_invoices
            WHERE status = 'open' AND julianday(due_date) - julianday('now') BETWEEN 0 AND 7
        """).fetchone()
        upcoming = row[0] if row else 0
        if upcoming > 0:
            recs.append({
                "category": "automate",
                "rule_id": "T2_PAYMENT_NOTIFY",
                "title": f"Auto-send {upcoming} payment reminders (due within 7 days)",
                "detail": (f"{upcoming} invoices due within the next 7 days. "
                           f"Automate reminder notifications with payment portal links "
                           f"and escalation scheduling."),
                "impact": "medium",
                "evidence_ids": [f"ar_invoices:due_7d:{upcoming}"],
                "evidence_type": "ar_receivables.db",
                "estimated_savings_desc": f"{upcoming * 5} min notification effort saved",
                "source": "tier1",
            })
        conn.close()
    except Exception as e:
        logger.warning("_check_automate_rules: T2 payment notify query failed: %s", e)

    # T3: High-success skill candidates for full automation
    try:
        conn = _sql.connect(twin_db)
        rows = conn.execute("""
            SELECT skill, COUNT(*) as total,
                   SUM(CASE WHEN event_type='task_completed' THEN 1 ELSE 0 END) as ok
            FROM task_events GROUP BY skill HAVING total >= 5
        """).fetchall()
        for row in (rows or []):
            skill_name, total, ok = row[0], row[1], row[2] or 0
            rate = round(ok / total * 100, 1)
            if rate >= 90 and total >= 5:
                recs.append({
                    "category": "automate",
                    "rule_id": "T3_HIGH_SUCCESS",
                    "title": f"Full-auto '{skill_name}' ({rate}% success, {total} runs)",
                    "detail": (f"Skill '{skill_name}' has {rate}% success rate across {total} executions. "
                               f"Candidate for scheduled, unattended automation with exception-only HITL."),
                    "impact": "high" if rate >= 95 else "medium",
                    "evidence_ids": [f"task_events:{skill_name}:{total}"],
                    "evidence_type": "twin_telemetry.db",
                    "estimated_savings_desc": f"{total * 5} min human oversight removed",
                    "source": "tier1",
                })
        conn.close()
    except Exception as e:
        logger.warning("_check_automate_rules: T3 high-success skill query failed: %s", e)

    return recs[:3]


def _compute_esaa_recommendations() -> dict:
    """Run all Tier 1 ESAA rules and return merged recommendations."""
    import time as _time
    now = _time.time()

    if _esaa_cache["data"] is not None and (now - _esaa_cache["ts"]) < _ESAA_TTL:
        return _esaa_cache["data"]

    ap_db = _get_ap_db()
    ar_db = _get_ar_db()
    twin_db = _get_twin_db()

    eliminate = _check_eliminate_rules(ap_db, twin_db)
    standardize = _check_standardize_rules(ar_db, ap_db)
    augment = _check_augment_rules(ar_db, twin_db)
    automate = _check_automate_rules(ap_db, ar_db, twin_db)

    all_recs = eliminate + standardize + augment + automate

    # Sort: high > medium > low, then by rule_id for determinism
    impact_order = {"high": 0, "medium": 1, "low": 2}
    all_recs.sort(key=lambda r: (impact_order.get(r.get("impact", "medium"), 1), r.get("rule_id", "")))

    summary = {
        "eliminate": len(eliminate),
        "standardize": len(standardize),
        "augment": len(augment),
        "automate": len(automate),
        "total": len(all_recs),
    }

    result = {
        "recommendations": all_recs,
        "summary": summary,
        "tier": "tier1",
        "computed_at": datetime.now().isoformat(),
    }

    _esaa_cache["data"] = result
    _esaa_cache["ts"] = now
    return result


@router.get("/api/twin/optimization")
async def twin_optimization():
    """
    GET ESAA recommendations. If Tier 2 is cached, merges LLM recs
    into the main recommendations list (Tier 2 priority, deduped).
    """
    try:
        result = _compute_esaa_recommendations()

        import time as _time
        now = _time.time()
        if (_esaa_tier2_cache["data"] is not None
                and (now - _esaa_tier2_cache["ts"]) < _ESAA_TIER2_TTL):
            tier2 = _esaa_tier2_cache["data"]
            tier2_recs = tier2.get("recommendations", [])
            tier1_recs = result.get("recommendations", [])

            # Merge: Tier 2 priority, dedup by title prefix, max 3 per cat
            merged = {}
            seen = set()
            for rec in tier2_recs + tier1_recs:
                cat = rec.get("category", "")
                title_key = rec.get("title", "").lower()[:30]
                if cat not in merged:
                    merged[cat] = []
                if len(merged[cat]) < 3 and title_key not in seen:
                    merged[cat].append(rec)
                    seen.add(title_key)

            impact_order = {"high": 0, "medium": 1, "low": 2}
            all_recs = []
            for cat in ("eliminate", "standardize", "augment", "automate"):
                items = sorted(merged.get(cat, []),
                               key=lambda r: impact_order.get(r.get("impact", "medium"), 1))
                all_recs.extend(items)

            summary = {}
            for cat in ("eliminate", "standardize", "augment", "automate"):
                summary[cat] = len(merged.get(cat, []))
            summary["total"] = len(all_recs)

            result = {
                "recommendations": all_recs,
                "summary": summary,
                "tier": "tier1+tier2",
                "tier2_patterns": tier2.get("patterns", {}),
                "tier2_status": tier2.get("tier2_status", "unknown"),
                "computed_at": datetime.now().isoformat(),
            }

        return result
    except Exception as e:
        logger.error("twin_optimization failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred", "recommendations": [], "summary": {}}


@router.post("/api/twin/optimization/analyze")
async def twin_optimization_analyze(background_tasks: BackgroundTasks):
    """
    Trigger Tier 2 LLM-enriched ESAA analysis.
    Runs asynchronously in background. Returns a job_id for polling.
    """
    job_id = str(uuid.uuid4())[:8]
    _esaa_jobs[job_id] = {"status": "running", "started_at": datetime.now().isoformat(), "result": None}

    async def _run_tier2(jid: str):
        try:
            from esaa_enricher import ESAAEnricher
            llm = None
            try:
                from langchain_openai import AzureChatOpenAI
                llm = AzureChatOpenAI(
                    model="gpt-4o-mini",
                    temperature=0.2,
                    max_tokens=2000,
                )
            except Exception as e:
                logger.warning("Tier 2 ESAA: LLM initialization failed, proceeding without LLM: %s", e)

            enricher = ESAAEnricher(_MEMORY_ROOT, llm=llm)
            result = await enricher.analyze()

            _esaa_jobs[jid]["status"] = "completed"
            _esaa_jobs[jid]["result"] = result
            _esaa_jobs[jid]["completed_at"] = datetime.now().isoformat()

            import time as _time
            _esaa_tier2_cache["data"] = result
            _esaa_tier2_cache["ts"] = _time.time()
        except Exception as e:
            logger.error("Tier 2 ESAA analysis job %s failed: %s", jid, e, exc_info=True)
            _esaa_jobs[jid]["status"] = "error"
            _esaa_jobs[jid]["error"] = str(e)[:500]

    background_tasks.add_task(asyncio.to_thread, asyncio.run, _run_tier2(job_id))

    return {"job_id": job_id, "status": "running", "message": "Tier 2 ESAA analysis started"}


@router.get("/api/twin/optimization/status/{job_id}")
async def twin_optimization_status(job_id: str):
    """Poll Tier 2 analysis job status."""
    job = _esaa_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.get("/api/twin/entity/customer/{name}")
async def twin_entity_customer(name: str):
    """Return business detail for a single AR customer: profile + open invoices."""
    try:
        conn = _sql.connect(_get_ar_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        profile = cur.execute("""
            SELECT c.customer_id, c.customer_name, c.risk_rating,
                   c.credit_limit, c.payment_terms,
                   ROUND(SUM(r.amount), 2) as total_outstanding,
                   ROUND(SUM(CASE WHEN r.days_overdue > 0 THEN r.amount ELSE 0 END), 2) as total_overdue,
                   MAX(r.days_overdue) as max_days_overdue,
                   COUNT(r.id) as open_invoices
            FROM customers c
            LEFT JOIN receivables r ON c.customer_id = r.customer_id
            WHERE LOWER(c.customer_name) = LOWER(?)
            GROUP BY c.customer_id
        """, (name,)).fetchone()

        if not profile:
            # fuzzy fallback — partial name match on first word
            profile = cur.execute("""
                SELECT c.customer_id, c.customer_name, c.risk_rating,
                       c.credit_limit, c.payment_terms,
                       ROUND(SUM(r.amount), 2) as total_outstanding,
                       ROUND(SUM(CASE WHEN r.days_overdue > 0 THEN r.amount ELSE 0 END), 2) as total_overdue,
                       MAX(r.days_overdue) as max_days_overdue,
                       COUNT(r.id) as open_invoices
                FROM customers c
                LEFT JOIN receivables r ON c.customer_id = r.customer_id
                WHERE LOWER(c.customer_name) LIKE LOWER(?)
                GROUP BY c.customer_id
                LIMIT 1
            """, (f"%{name.split()[0]}%",)).fetchone()

        invoices = cur.execute("""
            SELECT r.invoice_number, r.amount, r.days_overdue,
                   r.aging_bucket, r.status, r.due_date
            FROM receivables r
            JOIN customers c ON r.customer_id = c.customer_id
            WHERE LOWER(c.customer_name) LIKE LOWER(?)
            ORDER BY r.days_overdue DESC, r.amount DESC
            LIMIT 10
        """, (f"%{name.split()[0]}%",)).fetchall()

        conn.close()
        return {
            "entity_type": "customer",
            "profile": dict(profile) if profile else None,
            "invoices": [dict(r) for r in invoices],
        }
    except Exception as e:
        logger.error("twin entity customer: %s", e)
        return {"entity_type": "customer", "profile": None, "invoices": [], "error": "An internal error occurred"}


@router.get("/api/twin/entity/vendor/{name}")
async def twin_entity_vendor(name: str):
    """Return business detail for a single AP vendor: profile + open invoices."""
    try:
        conn = _sql.connect(_get_ap_db())
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        profile = cur.execute("""
            SELECT v.vendor_id, v.vendor_name, v.vendor_status, v.payment_terms,
                   v.credit_limit, v.ytd_spend, v.category, v.contact_email,
                   ROUND(SUM(CASE WHEN t.status='open' AND t.transaction_type='invoice'
                             THEN t.amount ELSE 0 END), 2) as open_amount,
                   ROUND(SUM(CASE WHEN t.status='overdue' THEN t.amount ELSE 0 END), 2) as overdue_amount,
                   COUNT(CASE WHEN t.status='open' AND t.transaction_type='invoice' THEN 1 END) as open_invoices,
                   COUNT(CASE WHEN t.requires_correction=1 THEN 1 END) as pending_corrections
            FROM vendors v
            LEFT JOIN ap_transactions t ON v.vendor_id = t.vendor_id
            WHERE LOWER(v.vendor_name) LIKE LOWER(?)
            GROUP BY v.vendor_id
            LIMIT 1
        """, (f"%{name.split()[0]}%",)).fetchone()

        invoices = cur.execute("""
            SELECT t.transaction_id, t.invoice_number, t.amount, t.currency,
                   t.status, t.posting_date, t.due_date, t.description,
                   t.requires_correction,
                   CAST(julianday('now') - julianday(t.due_date) AS INTEGER) as days_overdue
            FROM ap_transactions t
            JOIN vendors v ON t.vendor_id = v.vendor_id
            WHERE LOWER(v.vendor_name) LIKE LOWER(?)
              AND t.transaction_type = 'invoice'
              AND t.status IN ('open', 'overdue')
            ORDER BY t.due_date ASC
            LIMIT 10
        """, (f"%{name.split()[0]}%",)).fetchall()

        conn.close()
        return {
            "entity_type": "vendor",
            "profile": dict(profile) if profile else None,
            "invoices": [dict(r) for r in invoices],
        }
    except Exception as e:
        logger.error("twin entity vendor: %s", e)
        return {"entity_type": "vendor", "profile": None, "invoices": [], "error": "An internal error occurred"}


def _slug(s: str) -> str:
    """Normalise a display name to a slug: lowercase, strip punctuation, underscores."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = s.strip()
    s = re.sub(r"\s+", "_", s)
    return s


def _load_entity_keys(entity_type: str) -> List[str]:
    """
    Return all DISTINCT entity keys of the given type from entity_xref.
    Queries the agent memory knowledge_index.db directly.
    """
    db_path = str(Path(_MEMORY_ROOT) / "knowledge_index.db")
    try:
        with _sql.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT entity FROM entity_xref WHERE entity LIKE ?",
                (f"{entity_type}:%",),
            ).fetchall()
        return [r[0] for r in rows]
    except Exception as exc:
        logger.warning("entity-match: could not load entity_xref: %s", exc)
        return []


async def _llm_match(name: str, candidates: List[str]) -> Optional[str]:
    """
    Ask the light LLM to pick the best matching entity key for a display name.
    Returns the matched key, or None if the LLM finds no good match.
    """
    try:
        from iaf_agent_skills.model_provider import default_model_provider
        llm = default_model_provider.get("light")
        if llm is None:
            return None

        options_str = "\n".join(f"  - {k}" for k in candidates[:25])
        prompt = (
            f'Match the business entity name "{name}" to the best key from this list.\n'
            f"Keys:\n{options_str}\n\n"
            f'Reply with just the key (e.g. "customer:bank_of_america"), '
            f'or "none" if no key is a reasonable match. No explanation.'
        )
        response = await asyncio.to_thread(llm.invoke, [("human", prompt)])
        matched = response.content.strip().strip('"').strip("'").lower()
        return matched if matched in candidates else None
    except Exception as exc:
        logger.warning("entity-match LLM call failed: %s", exc)
        return None


@router.get("/api/twin/entity-match")
async def twin_entity_match(name: str, type: str = "customer"):
    """
    Resolve a business display name (e.g. "Meridian Trust Bank") to an agent
    memory entity key (e.g. "customer:meridian_trust") using a 3-layer strategy:

      Layer 1 — exact slug match        (free, instant)
      Layer 2 — fuzzy string match      (free, <1 ms)
      Layer 3 — light LLM confirmation  (only when fuzzy score 0.45–0.84)

    Response:
      {
        "entity_key":  "customer:meridian_trust",
        "confidence":  0.97,
        "method":      "fuzzy",   // "slug" | "fuzzy" | "llm" | "none"
        "name":        "Meridian Trust Bank"
      }
    """
    entity_type = type.strip().lower()
    cache_key   = f"{name.lower()}|{entity_type}"

    cached = _entity_match_cache.get(cache_key)
    if cached and (_time.time() - cached["cached_at"]) < _ENTITY_MATCH_TTL:
        return {**cached, "cached": True}

    all_keys = _load_entity_keys(entity_type)
    if not all_keys:
        return {"entity_key": None, "confidence": 0.0, "method": "none",
                "name": name, "reason": "no entity_xref entries for this type"}

    name_slug = _slug(name)

    slug_key = f"{entity_type}:{name_slug}"
    if slug_key in all_keys:
        result = {"entity_key": slug_key, "confidence": 1.0,
                  "method": "slug", "name": name, "cached": False,
                  "cached_at": _time.time()}
        _entity_match_cache[cache_key] = result
        logger.info("entity-match [slug] %s → %s", name, slug_key)
        return result

    name_norm = name_slug.replace("_", " ")
    best_key, best_score = None, 0.0
    for key in all_keys:
        key_norm = key.split(":", 1)[-1].replace("_", " ")
        score = difflib.SequenceMatcher(None, name_norm, key_norm).ratio()
        if score > best_score:
            best_score = score
            best_key = key

    if best_score >= 0.85:
        result = {"entity_key": best_key, "confidence": round(best_score, 3),
                  "method": "fuzzy", "name": name, "cached": False,
                  "cached_at": _time.time()}
        _entity_match_cache[cache_key] = result
        logger.info("entity-match [fuzzy %.2f] %s → %s", best_score, name, best_key)
        return result

    if best_score >= 0.35:
        # Pass top-5 fuzzy candidates to LLM for disambiguation
        scored = sorted(
            [(difflib.SequenceMatcher(None, name_norm, k.split(":")[-1].replace("_", " ")).ratio(), k)
             for k in all_keys],
            reverse=True,
        )
        candidates = [k for _, k in scored[:8]]
        llm_key = await _llm_match(name, candidates)
        if llm_key:
            result = {"entity_key": llm_key, "confidence": 0.92,
                      "method": "llm", "name": name, "cached": False,
                      "cached_at": _time.time()}
            _entity_match_cache[cache_key] = result
            logger.info("entity-match [llm] %s → %s", name, llm_key)
            return result

    result = {"entity_key": None, "confidence": round(best_score, 3),
              "method": "none", "name": name,
              "closest": best_key, "cached": False,
              "cached_at": _time.time()}
    _entity_match_cache[cache_key] = result
    logger.info("entity-match [none %.2f] %s — closest: %s", best_score, name, best_key)
    return result
