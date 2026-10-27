"""Read model for Private Learning Loop eval dashboard cards."""

from __future__ import annotations

from typing import Any

from pathlib import Path

from rl_capture.adapters.agentpro.evals_paths import eval_storage_engine, evals_dir
from rl_capture.evals.registry import list_suites
from rl_capture.store.eval_store import EvalStore
from shared.config import TENANT_ID


def dashboard_summary(tenant_id: str = TENANT_ID, *, limit: int = 10) -> dict[str, Any]:
    """Return a bounded, read-only eval dashboard summary."""
    suites = list_suites(evals_dir(tenant_id))
    engine = eval_storage_engine(tenant_id)
    sqlite_path = getattr(engine, "db_path", "")
    store = EvalStore(engine, init_schema=False) if not sqlite_path or Path(sqlite_path).exists() else None
    suite_rows: list[dict[str, Any]] = []
    all_runs: list[dict[str, Any]] = []
    regressions = 0

    for suite in suites:
        runs = _safe_list_runs(store, suite_id=suite["id"], tenant_id=tenant_id, limit=max(2, limit))
        latest = runs[0] if runs else None
        previous = runs[1] if len(runs) > 1 else None
        delta = None
        regressed = False
        if latest and previous:
            delta = round(float(latest.get("score") or 0.0) - float(previous.get("score") or 0.0), 3)
            regressed = delta < 0
            regressions += int(regressed)
        suite_rows.append({
            "id": suite["id"],
            "name": suite.get("name") or suite["id"],
            "enabled": bool(suite.get("enabled", True)),
            "golden_set": suite.get("golden_set") or "",
            "target": suite.get("target") or {},
            "latest_run": _run_preview(latest),
            "previous_run": _run_preview(previous),
            "delta": delta,
            "regressed": regressed,
            "run_count": len(runs),
        })
        all_runs.extend(runs)

    all_runs.sort(key=lambda row: str(row.get("started_at") or ""), reverse=True)
    latest_scores = [float(row.get("latest_run", {}).get("score") or 0.0) for row in suite_rows if row.get("latest_run")]
    return {
        "tenant_id": tenant_id,
        "total_suites": len(suites),
        "enabled_suites": sum(1 for suite in suites if suite.get("enabled", True)),
        "total_runs": len(all_runs),
        "regressions": regressions,
        "average_latest_score": round(sum(latest_scores) / len(latest_scores), 3) if latest_scores else 0.0,
        "suites": suite_rows,
        "trend": [_run_preview(row) for row in all_runs[:limit]],
    }


def _run_preview(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "run_id": run.get("run_id"),
        "suite_id": run.get("suite_id"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "duration_ms": run.get("duration_ms"),
        "total_cases": run.get("total_cases"),
        "passed": run.get("passed"),
        "partial": run.get("partial"),
        "failed": run.get("failed"),
        "score": run.get("score"),
        "summary": run.get("summary"),
        "trigger": run.get("trigger"),
    }


def _safe_list_runs(store: EvalStore | None, *, suite_id: str, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    if store is None:
        return []
    try:
        return store.list_runs(suite_id=suite_id, tenant_id=tenant_id, limit=limit)
    except Exception:
        return []
