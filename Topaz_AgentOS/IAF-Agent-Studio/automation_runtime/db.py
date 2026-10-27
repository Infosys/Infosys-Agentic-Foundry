"""Durable runtime storage for deterministic automation runs.

Automation YAML files remain the source of truth. This module stores high-churn
run attempts and step traces under enterprise_root so tenant business state and
operational history stay separate from solution code.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DB_PATH: Optional[Path] = None
_backend: Optional["SQLiteAutomationRuntimeBackend"] = None
_DB_PATH_RE = re.compile(r'^[A-Za-z0-9 _/\\:.\-]+$')


def init_db_path(server_dir: Path) -> Path:
    """Set the runtime DB path and return it."""
    global _DB_PATH
    override = os.getenv("AUTOMATION_RUNTIME_DB_PATH", "").strip()
    if override:
        if not _DB_PATH_RE.fullmatch(override):
            raise ValueError("AUTOMATION_RUNTIME_DB_PATH contains disallowed characters")
        clean_override = override.encode("utf-8").decode("utf-8")
        path = Path(clean_override)
        _DB_PATH = path if path.is_absolute() else server_dir / path
    else:
        _DB_PATH = _tenant_runtime_db_path("automation_runtime.db", server_dir)
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
        logger.warning("Automation Runtime DB: DATA_ROOT unavailable; using Studio dir: %s", exc)
        target = server_dir / filename

    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = server_dir / filename
    if legacy.exists() and not target.exists() and legacy.resolve() != target.resolve():
        shutil.copy2(legacy, target)
        logger.info("Automation Runtime DB: copied legacy DB %s -> %s", legacy, target)
    return target


_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS automation_runs (
    run_id          TEXT PRIMARY KEY,
    automation_id   TEXT NOT NULL,
    automation_name TEXT,
    tenant_id       TEXT NOT NULL DEFAULT 'company',
    agent_id        TEXT NOT NULL DEFAULT 'enterprise_agent',
    user_id         TEXT NOT NULL DEFAULT 'automation',
    trigger         TEXT NOT NULL DEFAULT 'manual',
    status          TEXT NOT NULL DEFAULT 'running',
    started_at      TEXT,
    completed_at    TEXT,
    duration_ms     INTEGER DEFAULT 0,
    summary         TEXT,
    error_summary   TEXT
);

CREATE TABLE IF NOT EXISTS automation_steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    step_number   INTEGER DEFAULT 0,
    step_name     TEXT,
    action        TEXT,
    input         TEXT,
    output        TEXT,
    error         TEXT,
    status        TEXT DEFAULT 'completed',
    duration_ms   INTEGER DEFAULT 0,
    timestamp     TEXT,
    FOREIGN KEY (run_id) REFERENCES automation_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_auto_runs_lookup
    ON automation_runs(automation_id, started_at);
CREATE INDEX IF NOT EXISTS idx_auto_runs_status
    ON automation_runs(status, started_at);
CREATE INDEX IF NOT EXISTS idx_auto_steps_run
    ON automation_steps(run_id, step_number, id);
"""


class SQLiteAutomationRuntimeBackend:
    def __init__(self, db_path: Path):
        self._path = str(db_path)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = _sqlite_connect(self._path, row_factory=sqlite3.Row)
        conn.execute("PRAGMA busy_timeout=30000")
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
        logger.info("Automation runtime DB: schema ready at %s", self._path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_run(
        self,
        *,
        run_id: str,
        automation_id: str,
        automation_name: str = "",
        tenant_id: str,
        agent_id: str,
        user_id: str,
        trigger: str = "manual",
        status: str = "running",
        started_at: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "run_id": run_id,
            "automation_id": automation_id,
            "automation_name": automation_name,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "trigger": trigger,
            "status": status,
            "started_at": started_at or self._now(),
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO automation_runs
                  (run_id, automation_id, automation_name, tenant_id, agent_id,
                   user_id, trigger, status, started_at)
                VALUES
                  (:run_id, :automation_id, :automation_name, :tenant_id,
                   :agent_id, :user_id, :trigger, :status, :started_at)
                """,
                row,
            )
        return row

    def append_step(
        self,
        *,
        run_id: str,
        step_number: int,
        step_name: str,
        action: str,
        input_value: str = "",
        output: str = "",
        error: str = "",
        status: str = "completed",
        duration_ms: int = 0,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        ts = timestamp or self._now()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO automation_steps
                  (run_id, step_number, step_name, action, input, output,
                   error, status, duration_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(step_number or 0),
                    step_name,
                    action,
                    input_value,
                    output,
                    error,
                    status,
                    int(duration_ms or 0),
                    ts,
                ),
            )
            step_id = int(cursor.lastrowid)
        return {
            "id": step_id,
            "step_id": step_id,
            "run_id": run_id,
            "step_number": int(step_number or 0),
            "step_name": step_name,
            "action": action,
            "input": input_value,
            "output": output,
            "error": error,
            "status": status,
            "duration_ms": int(duration_ms or 0),
            "timestamp": ts,
        }

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "completed_at",
            "duration_ms",
            "summary",
            "error_summary",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return
        if "completed_at" not in clean and clean.get("status") not in {None, "running"}:
            clean["completed_at"] = self._now()
        sets = ", ".join(f"{key} = :{key}" for key in clean)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE automation_runs SET {sets} WHERE run_id = :run_id",
                {**clean, "run_id": run_id},
            )

    def list_runs(
        self,
        automation_id: str | None = None,
        *,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if automation_id:
                rows = conn.execute(
                    """
                    SELECT * FROM automation_runs
                     WHERE automation_id = ?
                     ORDER BY started_at DESC
                     LIMIT ?
                    """,
                    (automation_id, int(limit or 25)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM automation_runs
                     ORDER BY started_at DESC
                     LIMIT ?
                    """,
                    (int(limit or 25),),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            run = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not run:
                return None
            steps = conn.execute(
                """
                SELECT * FROM automation_steps
                 WHERE run_id = ?
                 ORDER BY step_number, id
                """,
                (run_id,),
            ).fetchall()
        return {
            "run": dict(run),
            "steps": [dict(row) for row in steps],
        }


def get_db() -> SQLiteAutomationRuntimeBackend:
    global _backend
    if _backend is None:
        if _DB_PATH is None:
            raise RuntimeError("Call init_db_path() before get_db()")
        _backend = SQLiteAutomationRuntimeBackend(_DB_PATH)
    return _backend


def reset_backend_for_tests() -> None:
    global _backend
    _backend = None
