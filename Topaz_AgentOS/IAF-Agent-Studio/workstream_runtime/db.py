"""Durable runtime storage for Workstream item executions.

YAML remains the source of truth for workstream business state. This module
stores high-churn execution attempts and step traces so late UI connections can
reconstruct a running trace the same way Queue Monitor does.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DB_PATH: Optional[Path] = None
_backend: Optional["SQLiteWorkstreamRuntimeBackend"] = None


def init_db_path(server_dir: Path) -> Path:
    """Set the runtime DB path and return it."""
    global _DB_PATH
    from shared.config import app_config
    override = (app_config.workstream_runtime_db_path or "").strip()
    if override:
        path = Path(override)
        _DB_PATH = (path if path.is_absolute() else server_dir / path).resolve()
    else:
        _DB_PATH = _tenant_runtime_db_path("workstream_runtime.db", server_dir)
    return _DB_PATH


def _tenant_runtime_db_path(filename: str, server_dir: Path) -> Path:
    """Default runtime storage belongs to enterprise_root, not solution code."""
    try:
        from shared.config import DATA_ROOT_PATH, TENANT_ID

        target = (
            DATA_ROOT_PATH
            / "tenants"
            / TENANT_ID
            / "shared"
            / "databases"
            / filename
        )
    except Exception as exc:  # pragma: no cover - import-time fallback
        logger.warning("Workstream Runtime DB: DATA_ROOT unavailable; using Studio dir: %s", exc)
        target = server_dir / filename

    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = server_dir / filename
    if legacy.exists() and not target.exists() and legacy.resolve() != target.resolve():
        shutil.copy2(legacy, target)
        logger.info("Workstream Runtime DB: copied legacy DB %s -> %s", legacy, target)
    return target


_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS workstream_executions (
    execution_id       TEXT PRIMARY KEY,
    workstream_name    TEXT NOT NULL,
    item_id            TEXT NOT NULL,
    tenant_id          TEXT NOT NULL DEFAULT 'company',
    skill_name         TEXT,
    attempt            INTEGER DEFAULT 0,
    status             TEXT DEFAULT 'running',
    started_at         TEXT,
    completed_at       TEXT,
    duration_ms        INTEGER DEFAULT 0,
    result_summary     TEXT,
    error_summary      TEXT,
    trace_id           TEXT,
    evidence_trace_id  TEXT,
    evidence_count     INTEGER DEFAULT 0,
    approval_id        TEXT
);

CREATE TABLE IF NOT EXISTS workstream_steps (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id   TEXT NOT NULL,
    step_number    INTEGER DEFAULT 0,
    step_name      TEXT,
    action         TEXT DEFAULT 'agent_step',
    input          TEXT,
    output         TEXT,
    status         TEXT DEFAULT 'completed',
    duration_ms    INTEGER DEFAULT 0,
    timestamp      TEXT,
    phase          TEXT,
    skill          TEXT,
    FOREIGN KEY (execution_id) REFERENCES workstream_executions(execution_id)
);

CREATE INDEX IF NOT EXISTS idx_ws_exec_item
    ON workstream_executions(workstream_name, item_id, started_at);
CREATE INDEX IF NOT EXISTS idx_ws_exec_status
    ON workstream_executions(workstream_name, status);
CREATE INDEX IF NOT EXISTS idx_ws_steps_exec
    ON workstream_steps(execution_id, step_number, id);
"""


class SQLiteWorkstreamRuntimeBackend:
    def __init__(self, db_path: Path):
        self._path = str(db_path)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = _sqlite_connect(self._path, row_factory=sqlite3.Row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        logger.info("Workstream runtime DB: schema ready at %s", self._path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_execution(
        self,
        *,
        execution_id: str,
        workstream_name: str,
        item_id: str,
        tenant_id: str,
        skill_name: str,
        attempt: int,
        status: str = "running",
        started_at: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO workstream_executions
                  (execution_id, workstream_name, item_id, tenant_id, skill_name,
                   attempt, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    workstream_name,
                    item_id,
                    tenant_id,
                    skill_name,
                    int(attempt or 0),
                    status,
                    started_at or self._now(),
                ),
            )

    def append_step(
        self,
        *,
        execution_id: str,
        step_number: int,
        step_name: str,
        action: str,
        output: str = "",
        input_value: str = "",
        status: str = "completed",
        duration_ms: int = 0,
        phase: str = "",
        skill: str = "",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        ts = timestamp or self._now()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workstream_steps
                  (execution_id, step_number, step_name, action, input, output,
                   status, duration_ms, timestamp, phase, skill)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    int(step_number or 0),
                    step_name,
                    action,
                    input_value,
                    output,
                    status,
                    int(duration_ms or 0),
                    ts,
                    phase,
                    skill,
                ),
            )
            step_id = int(cursor.lastrowid)
        return {
            "id": step_id,
            "step_id": step_id,
            "execution_id": execution_id,
            "step_number": int(step_number or 0),
            "step_index": int(step_number or 0),
            "step_name": step_name,
            "tool_name": step_name,
            "action": action,
            "input": input_value,
            "input_preview": input_value,
            "output": output,
            "output_preview": output,
            "status": status,
            "duration_ms": int(duration_ms or 0),
            "timestamp": ts,
            "phase": phase,
            "skill": skill,
        }

    def update_execution(self, execution_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "completed_at",
            "duration_ms",
            "result_summary",
            "error_summary",
            "trace_id",
            "evidence_trace_id",
            "evidence_count",
            "approval_id",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return
        if "completed_at" not in clean and clean.get("status") not in {None, "running"}:
            clean["completed_at"] = self._now()
        sets = ", ".join(f"{k} = :{k}" for k in clean)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE workstream_executions SET {sets} WHERE execution_id = :execution_id",
                {**clean, "execution_id": execution_id},
            )

    def get_item_executions(
        self,
        workstream_name: str,
        item_id: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            exec_rows = conn.execute(
                """
                SELECT * FROM workstream_executions
                 WHERE workstream_name = ? AND item_id = ?
                 ORDER BY started_at DESC
                 LIMIT ?
                """,
                (workstream_name, item_id, int(limit or 10)),
            ).fetchall()
            executions: list[dict[str, Any]] = []
            for ex in exec_rows:
                step_rows = conn.execute(
                    """
                    SELECT * FROM workstream_steps
                     WHERE execution_id = ?
                     ORDER BY step_number, id
                    """,
                    (ex["execution_id"],),
                ).fetchall()
                executions.append({
                    "execution": dict(ex),
                    "steps": [self._step_row_to_dict(row) for row in step_rows],
                })
            return executions

    def get_execution(self, execution_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            ex = conn.execute(
                "SELECT * FROM workstream_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if not ex:
                return None
            steps = conn.execute(
                """
                SELECT * FROM workstream_steps
                 WHERE execution_id = ?
                 ORDER BY step_number, id
                """,
                (execution_id,),
            ).fetchall()
            return {
                "execution": dict(ex),
                "steps": [self._step_row_to_dict(row) for row in steps],
            }

    def _step_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["step_id"] = data.get("id")
        data["step_index"] = data.get("step_number")
        data["tool_name"] = data.get("step_name")
        data["input_preview"] = data.get("input") or ""
        data["output_preview"] = data.get("output") or ""
        data["error_preview"] = ""
        return data


def get_db() -> SQLiteWorkstreamRuntimeBackend:
    global _backend
    if _backend is None:
        if _DB_PATH is None:
            raise RuntimeError("Call init_db_path() before get_db()")
        _backend = SQLiteWorkstreamRuntimeBackend(_DB_PATH)
    return _backend


def reset_backend_for_tests() -> None:
    global _backend
    _backend = None
