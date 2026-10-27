"""StorageEngine-backed eval run/case persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS eval_runs (
        run_id TEXT PRIMARY KEY,
        suite_id TEXT NOT NULL,
        suite_name TEXT,
        tenant_id TEXT NOT NULL,
        agent_id TEXT,
        trigger TEXT,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        duration_ms INTEGER DEFAULT 0,
        total_cases INTEGER DEFAULT 0,
        passed INTEGER DEFAULT 0,
        partial INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        score REAL DEFAULT 0,
        summary TEXT,
        error_summary TEXT,
        suite_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_case_results (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        suite_id TEXT NOT NULL,
        status TEXT NOT NULL,
        verdict TEXT,
        score REAL DEFAULT 0,
        target_type TEXT,
        target_name TEXT,
        output_text TEXT,
        error TEXT,
        duration_ms INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        case_json TEXT NOT NULL,
        assertion_json TEXT NOT NULL,
        evaluator_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_runs_suite ON eval_runs(tenant_id, suite_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_eval_runs_status ON eval_runs(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_eval_cases_run ON eval_case_results(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_eval_cases_suite ON eval_case_results(tenant_id, suite_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS eval_gate_decisions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        suite_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        target_type TEXT,
        target_name TEXT,
        decision TEXT NOT NULL,
        reviewer TEXT,
        reason TEXT,
        score REAL DEFAULT 0,
        thresholds_json TEXT NOT NULL,
        evaluator_versions_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_gates_suite ON eval_gate_decisions(tenant_id, suite_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_eval_gates_run ON eval_gate_decisions(run_id)",
]


class EvalStore:
    """Persist eval runs/case rows through an injected StorageEngine."""

    def __init__(self, engine: Any, *, init_schema: bool = True):
        self.engine = engine
        if init_schema:
            self._init_schema()

    def create_run(
        self,
        *,
        run_id: str,
        suite: dict[str, Any],
        tenant_id: str,
        agent_id: str = "",
        trigger: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        row = {
            "run_id": run_id,
            "suite_id": suite.get("id") or "",
            "suite_name": suite.get("name") or suite.get("id") or "",
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "trigger": trigger,
            "status": "running",
            "started_at": now,
            "ended_at": "",
            "duration_ms": 0,
            "total_cases": 0,
            "passed": 0,
            "partial": 0,
            "failed": 0,
            "score": 0.0,
            "summary": "",
            "error_summary": "",
            "suite_json": _json(suite),
            "metadata_json": _json(metadata or {}),
        }
        self._execute(
            """
            INSERT INTO eval_runs (
                run_id, suite_id, suite_name, tenant_id, agent_id, trigger, status,
                started_at, ended_at, duration_ms, total_cases, passed, partial,
                failed, score, summary, error_summary, suite_json, metadata_json
            ) VALUES ({})
            """.format(self._placeholders(19)),
            tuple(row.values()),
        )
        return row

    def append_case(
        self,
        *,
        run_id: str,
        case_id: str,
        tenant_id: str,
        suite_id: str,
        status: str,
        verdict: str = "",
        score: float = 0.0,
        target_type: str = "",
        target_name: str = "",
        output_text: str = "",
        error: str = "",
        duration_ms: int = 0,
        case: dict[str, Any] | None = None,
        assertions: dict[str, Any] | None = None,
        evaluator: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": f"{run_id}:{case_id}",
            "run_id": run_id,
            "case_id": case_id,
            "tenant_id": tenant_id,
            "suite_id": suite_id,
            "status": status,
            "verdict": verdict,
            "score": float(score or 0.0),
            "target_type": target_type,
            "target_name": target_name,
            "output_text": output_text,
            "error": error,
            "duration_ms": int(duration_ms or 0),
            "created_at": _now(),
            "case_json": _json(case or {}),
            "assertion_json": _json(assertions or {}),
            "evaluator_json": _json(evaluator or {}),
            "metadata_json": _json(metadata or {}),
        }
        self._execute(
            """
            INSERT INTO eval_case_results (
                id, run_id, case_id, tenant_id, suite_id, status, verdict, score,
                target_type, target_name, output_text, error, duration_ms,
                created_at, case_json, assertion_json, evaluator_json, metadata_json
            ) VALUES ({})
            """.format(self._placeholders(18)),
            tuple(row.values()),
        )
        return row

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        duration_ms: int,
        total_cases: int,
        passed: int,
        partial: int,
        failed: int,
        score: float,
        summary: str = "",
        error_summary: str = "",
    ) -> None:
        ph = [self.engine.placeholder(i) for i in range(10)]
        self._execute(
            f"""
            UPDATE eval_runs
            SET status = {ph[0]}, ended_at = {ph[1]}, duration_ms = {ph[2]},
                total_cases = {ph[3]}, passed = {ph[4]}, partial = {ph[5]},
                failed = {ph[6]}, score = {ph[7]}, summary = {ph[8]}, error_summary = {ph[9]}
            WHERE run_id = {self.engine.placeholder(10)}
            """,
            (
                status,
                _now(),
                int(duration_ms or 0),
                int(total_cases or 0),
                int(passed or 0),
                int(partial or 0),
                int(failed or 0),
                float(score or 0.0),
                summary,
                error_summary,
                run_id,
            ),
        )

    def list_runs(self, *, suite_id: str | None = None, tenant_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if tenant_id:
            where.append(f"tenant_id = {self.engine.placeholder(len(params))}")
            params.append(tenant_id)
        if suite_id:
            where.append(f"suite_id = {self.engine.placeholder(len(params))}")
            params.append(suite_id)
        sql = "SELECT * FROM eval_runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY started_at DESC LIMIT {self.engine.placeholder(len(params))}"
        params.append(int(limit))
        return [self._decode_run(row) for row in self._query(sql, tuple(params))]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._query_one(
            f"SELECT * FROM eval_runs WHERE run_id = {self.engine.placeholder(0)}",
            (run_id,),
        )
        if row is None:
            return None
        cases = self._query(
            f"SELECT * FROM eval_case_results WHERE run_id = {self.engine.placeholder(0)} ORDER BY created_at ASC",
            (run_id,),
        )
        return {"run": self._decode_run(row), "cases": [self._decode_case(case) for case in cases]}

    def record_gate_decision(
        self,
        *,
        decision_id: str,
        tenant_id: str,
        suite_id: str,
        run_id: str,
        target_type: str = "",
        target_name: str = "",
        decision: str,
        reviewer: str = "",
        reason: str = "",
        score: float = 0.0,
        thresholds: dict[str, Any] | None = None,
        evaluator_versions: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": decision_id,
            "tenant_id": tenant_id,
            "suite_id": suite_id,
            "run_id": run_id,
            "target_type": target_type,
            "target_name": target_name,
            "decision": decision,
            "reviewer": reviewer,
            "reason": reason,
            "score": float(score or 0.0),
            "thresholds_json": _json(thresholds or {}),
            "evaluator_versions_json": _json(evaluator_versions or {}),
            "metadata_json": _json(metadata or {}),
            "created_at": _now(),
        }
        self._execute(
            """
            INSERT INTO eval_gate_decisions (
                id, tenant_id, suite_id, run_id, target_type, target_name,
                decision, reviewer, reason, score, thresholds_json,
                evaluator_versions_json, metadata_json, created_at
            ) VALUES ({})
            """.format(self._placeholders(14)),
            tuple(row.values()),
        )
        return self._decode_gate(row)

    def list_gate_decisions(
        self,
        *,
        suite_id: str | None = None,
        tenant_id: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if tenant_id:
            where.append(f"tenant_id = {self.engine.placeholder(len(params))}")
            params.append(tenant_id)
        if suite_id:
            where.append(f"suite_id = {self.engine.placeholder(len(params))}")
            params.append(suite_id)
        sql = "SELECT * FROM eval_gate_decisions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY created_at DESC LIMIT {self.engine.placeholder(len(params))}"
        params.append(int(limit))
        return [self._decode_gate(row) for row in self._query(sql, tuple(params))]

    def _init_schema(self) -> None:
        with self.engine.connect() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self.engine.connect() as conn:
            conn.execute(sql, params)

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            return [_row_to_dict(cur, row) for row in rows]

    def _query_one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            return _row_to_dict(cur, row) if row else None

    def _placeholders(self, count: int) -> str:
        return ", ".join(self.engine.placeholder(i) for i in range(count))

    @staticmethod
    def _decode_run(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "suite": _loads(row.get("suite_json")),
            "metadata": _loads(row.get("metadata_json")),
        }

    @staticmethod
    def _decode_case(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "case": _loads(row.get("case_json")),
            "assertions": _loads(row.get("assertion_json")),
            "evaluator": _loads(row.get("evaluator_json")),
            "metadata": _loads(row.get("metadata_json")),
        }

    @staticmethod
    def _decode_gate(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "thresholds": _loads(row.get("thresholds_json")),
            "evaluator_versions": _loads(row.get("evaluator_versions_json")),
            "metadata": _loads(row.get("metadata_json")),
        }


def _row_to_dict(cursor: Any, row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    names = [column[0] for column in cursor.description]
    return dict(zip(names, row))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: Any) -> Any:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
