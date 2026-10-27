"""
Command Center — SQLite backend.

Single file, single responsibility:
  - Schema creation (idempotent, safe to call on every startup)
  - QueueBackend interface (swap to Redis/Postgres later without touching processor)
  - SQLiteQueueBackend implementation
  - get_db() singleton factory

Tables: queue_items, job_executions, job_steps, routing_log, dlq_items
Note: HITL is handled by the existing ApprovalStore (Redis) — we only store
      a reference row here for dashboard display.
"""

import sqlite3
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
import logging
import os
import shutil
import socket
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH: Optional[Path] = None


def init_db_path(server_dir: Path) -> Path:
    global _DB_PATH
    from shared.config import app_config
    override = (app_config.cc_queue_db_path or "").strip()
    if override:
        path = Path(override)
        _DB_PATH = (path if path.is_absolute() else server_dir / path).resolve()
    else:
        _DB_PATH = _tenant_runtime_db_path("command_center.db", server_dir)
    return _DB_PATH


def _tenant_runtime_db_path(filename: str, server_dir: Path) -> Path:
    """Default queue storage belongs to enterprise_root, not solution code."""
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
        logger.warning("Command Center: DATA_ROOT unavailable; using Studio dir: %s", exc)
        target = server_dir / filename

    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = server_dir / filename
    if legacy.exists() and not target.exists() and legacy.resolve() != target.resolve():
        shutil.copy2(legacy, target)
        logger.info("Command Center: copied legacy DB %s -> %s", legacy, target)
    return target


_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS queue_items (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT 'company',
    external_id   TEXT UNIQUE,
    domain        TEXT NOT NULL DEFAULT 'itops',
    entity_id     TEXT,
    title         TEXT NOT NULL,
    description   TEXT,
    priority      TEXT DEFAULT 'P3',
    status        TEXT DEFAULT 'queued',
    routed_skill  TEXT,
    routing_reason TEXT,
    retry_count   INTEGER DEFAULT 0,
    trace_id      TEXT,
    source        TEXT DEFAULT 'manual',
    claimed_by    TEXT,
    claim_token   TEXT,
    claimed_at    TEXT,
    lease_expires_at TEXT,
    reclaim_count INTEGER DEFAULT 0,
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS job_executions (
    id                TEXT PRIMARY KEY,
    queue_item_id     TEXT NOT NULL,
    tenant_id         TEXT,
    skill_name        TEXT,
    status            TEXT DEFAULT 'running',
    started_at        TEXT,
    completed_at      TEXT,
    result_summary    TEXT,
    evidence_trace_id TEXT,
    evidence_count    INTEGER DEFAULT 0,
    FOREIGN KEY (queue_item_id) REFERENCES queue_items(id)
);

CREATE TABLE IF NOT EXISTS job_steps (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_execution_id  TEXT NOT NULL,
    step_number       INTEGER DEFAULT 0,
    step_name         TEXT,
    action            TEXT DEFAULT 'agent_step',
    input             TEXT,
    output            TEXT,
    status            TEXT DEFAULT 'completed',
    duration_ms       INTEGER DEFAULT 0,
    timestamp         TEXT,
    FOREIGN KEY (job_execution_id) REFERENCES job_executions(id)
);

CREATE TABLE IF NOT EXISTS routing_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_item_id     TEXT,
    tenant_id         TEXT,
    input_text        TEXT,
    skills_considered TEXT,
    chosen_skill      TEXT,
    confidence        REAL DEFAULT 0.0,
    reasoning         TEXT,
    model_used        TEXT DEFAULT 'light',
    latency_ms        INTEGER DEFAULT 0,
    timestamp         TEXT
);

CREATE TABLE IF NOT EXISTS dlq_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_item_id     TEXT,
    failure_reason    TEXT,
    last_error        TEXT,
    moved_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_status   ON queue_items(status, tenant_id);
CREATE INDEX IF NOT EXISTS idx_queue_external ON queue_items(external_id);
CREATE INDEX IF NOT EXISTS idx_exec_item      ON job_executions(queue_item_id);
CREATE INDEX IF NOT EXISTS idx_steps_exec     ON job_steps(job_execution_id);

CREATE TABLE IF NOT EXISTS queue_workers (
    worker_id      TEXT PRIMARY KEY,
    hostname       TEXT,
    pid            INTEGER,
    started_at     TEXT,
    last_heartbeat TEXT,
    in_flight      INTEGER DEFAULT 0,
    claims_total   INTEGER DEFAULT 0,
    status         TEXT DEFAULT 'online'
);
"""


class QueueBackend(ABC):
    """Abstract interface — swap SQLite for Redis/RabbitMQ/Postgres without
    touching processor.py or router.py."""

    @abstractmethod
    def claim_next(
        self,
        tenant_id: str,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
    ) -> Optional[dict]:
        """Atomically claim one queued item. Returns dict or None."""

    @abstractmethod
    def update_item(self, item_id: str, claim_token: str | None = None,
                    expected_status: str | None = None, **fields) -> bool:
        """Update arbitrary fields on a queue_item.

        expected_status makes the update a compare-and-set: it only applies (returns True)
        if the row is still in that status, so exactly one concurrent caller wins.
        """

    @abstractmethod
    def create_execution(self, exec_id: str, item_id: str, tenant_id: str, skill: str) -> None:
        """Insert a job_executions row."""

    @abstractmethod
    def update_execution(self, exec_id: str, **fields) -> None:
        """Update a job_executions row."""

    @abstractmethod
    def append_step(self, exec_id: str, step_number: int, step_name: str,
                    output: str, action: str = "agent_step",
                    duration_ms: int = 0) -> None:
        """Append a step to job_steps."""

    @abstractmethod
    def log_routing(self, item_id: str, tenant_id: str, input_text: str,
                    chosen_skill: str, confidence: float, reasoning: str,
                    latency_ms: int) -> None:
        """Write a routing_log entry."""

    @abstractmethod
    def move_to_dlq(self, item_id: str, reason: str, error: str, claim_token: str | None = None) -> bool:
        """Move item to DLQ after max retries."""

    @abstractmethod
    def list_items(self, tenant_id: str, status: Optional[str],
                   page: int, limit: int) -> tuple[list, int]:
        """Return (items, total_count) with pagination."""

    @abstractmethod
    def get_item_detail(self, item_id: str) -> Optional[dict]:
        """Return item + executions + steps."""

    @abstractmethod
    def get_metrics(self, tenant_id: str) -> dict:
        """Return queue health metrics."""

    @abstractmethod
    def insert_item(self, item: dict) -> bool:
        """Insert a new queue_item row."""

    @abstractmethod
    def get_item_by_external_id(self, external_id: str) -> Optional[dict]:
        """Return a queue_item by external_id."""

    def renew_lease(self, item_id: str, claim_token: str, lease_seconds: int) -> bool:
        return True

    def heartbeat_worker(self, worker_id: str, in_flight: int = 0) -> None:
        return None

    def unregister_worker(self, worker_id: str) -> None:
        return None

    def reap_expired_claims(self, lease_reclaim_limit: int = 3) -> int:
        return 0

    def complete_item(
        self,
        item_id: str,
        exec_id: str,
        claim_token: str | None,
        *,
        item_status: str,
        execution_status: str,
        result_summary: str,
    ) -> bool:
        self.update_execution(exec_id, status=execution_status, result_summary=result_summary)
        return self.update_item(item_id, claim_token=claim_token, status=item_status)


class SQLiteQueueBackend(QueueBackend):

    def __init__(self, db_path: Path):
        self._path = str(db_path)
        self._init_schema()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            item_cols = {row["name"] for row in conn.execute("PRAGMA table_info(queue_items)").fetchall()}
            for column, ddl in {
                "claimed_by": "ALTER TABLE queue_items ADD COLUMN claimed_by TEXT",
                "claim_token": "ALTER TABLE queue_items ADD COLUMN claim_token TEXT",
                "claimed_at": "ALTER TABLE queue_items ADD COLUMN claimed_at TEXT",
                "lease_expires_at": "ALTER TABLE queue_items ADD COLUMN lease_expires_at TEXT",
                "reclaim_count": "ALTER TABLE queue_items ADD COLUMN reclaim_count INTEGER DEFAULT 0",
            }.items():
                if column not in item_cols:
                    conn.execute(ddl)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(job_executions)").fetchall()}
            if "evidence_trace_id" not in cols:
                conn.execute("ALTER TABLE job_executions ADD COLUMN evidence_trace_id TEXT")
            if "evidence_count" not in cols:
                conn.execute("ALTER TABLE job_executions ADD COLUMN evidence_count INTEGER DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_lease ON queue_items(status, lease_expires_at)")
        logger.info("Command Center DB: schema ready at %s", self._path)

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

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


    def insert_item(self, item: dict) -> bool:
        """
        Insert a queue_items row.

        Status defaults to 'queued' (item awaits processor pickup). Callers
        that already executed the work (e.g. cron audit inserts) should pass
        status='done' so the processor skips them — otherwise the same work
        runs twice.
        """
        now = self._now()
        # Default to 'queued' for normal ingestion. Cron audit rows pass 'done'
        # since the work already ran in the cron executor.
        payload = {**item, "now": now, "status": item.get("status", "queued")}
        with self._conn() as conn:
            cursor = conn.execute("""
                INSERT INTO queue_items
                  (id, tenant_id, external_id, domain, entity_id, title,
                   description, priority, status, trace_id, source, created_at, updated_at)
                VALUES
                  (:id, :tenant_id, :external_id, :domain, :entity_id, :title,
                   :description, :priority, :status, :trace_id, :source, :now, :now)
                ON CONFLICT(external_id) DO NOTHING
            """, payload)
            return cursor.rowcount > 0

    def claim_next(
        self,
        tenant_id: str,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
    ) -> Optional[dict]:
        """Atomic claim: UPDATE … WHERE status='queued', return the row."""
        worker_id = worker_id or "sqlite-worker"
        lease_seconds = int(lease_seconds or int(os.getenv("QUEUE_CLAIM_LEASE_SECONDS", "360")))
        claim_token = uuid.uuid4().hex
        now = self._now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM queue_items
                WHERE status = 'queued' AND tenant_id = ?
                ORDER BY
                    CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                    created_at ASC
                LIMIT 1
            """, (tenant_id,)).fetchone()
            if not row:
                return None
            item_id = row["id"]
            affected = conn.execute("""
                UPDATE queue_items
                   SET status = 'routing',
                       claimed_by = ?,
                       claim_token = ?,
                       claimed_at = ?,
                       lease_expires_at = ?,
                       updated_at = ?
                WHERE id = ? AND status = 'queued'
            """, (worker_id, claim_token, now, expires_at, now, item_id)).rowcount
            if affected == 0:
                return None  # Another processor claimed it first
            claimed = dict(row)
            claimed.update({
                "status": "routing",
                "claimed_by": worker_id,
                "claim_token": claim_token,
                "claimed_at": now,
                "lease_expires_at": expires_at,
            })
            conn.execute(
                """
                UPDATE queue_workers
                   SET claims_total = COALESCE(claims_total, 0) + 1,
                       last_heartbeat = ?,
                       status = 'online'
                 WHERE worker_id = ?
                """,
                (now, worker_id),
            )
            return claimed

    def update_item(self, item_id: str, claim_token: str | None = None,
                    expected_status: str | None = None, **fields) -> bool:
        status = fields.get("status")
        if status in {"queued", "done", "failed", "awaiting_human"}:
            fields.setdefault("claimed_by", None)
            fields.setdefault("claim_token", None)
            fields.setdefault("claimed_at", None)
            fields.setdefault("lease_expires_at", None)
        fields["updated_at"] = self._now()
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        where = "id = :_id"
        params = {**fields, "_id": item_id}
        if claim_token:
            where += " AND claim_token = :_claim_token"
            params["_claim_token"] = claim_token
        if expected_status:
            where += " AND status = :_expected_status"
            params["_expected_status"] = expected_status
        with self._conn() as conn:
            cursor = conn.execute(f"UPDATE queue_items SET {sets} WHERE {where}", params)
            return cursor.rowcount > 0

    def create_execution(self, exec_id: str, item_id: str, tenant_id: str, skill: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO job_executions
                  (id, queue_item_id, tenant_id, skill_name, status, started_at)
                VALUES (?, ?, ?, ?, 'running', ?)
            """, (exec_id, item_id, tenant_id, skill, self._now()))

    def update_execution(self, exec_id: str, **fields) -> None:
        if "completed_at" not in fields:
            fields["completed_at"] = self._now()
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE job_executions SET {sets} WHERE id = :_id",
                {**fields, "_id": exec_id}
            )

    def set_execution_evidence(self, exec_id: str, evidence_trace_id: str,
                               evidence_count: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE job_executions
                   SET evidence_trace_id = ?, evidence_count = ?
                 WHERE id = ?
                """,
                (evidence_trace_id, int(evidence_count or 0), exec_id),
            )

    def append_step(self, exec_id: str, step_number: int, step_name: str,
                    output: str, action: str = "agent_step",
                    duration_ms: int = 0) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO job_steps
                  (job_execution_id, step_number, step_name, action, output,
                   status, duration_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, 'completed', ?, ?)
            """, (exec_id, step_number, step_name, action, output,
                  duration_ms, self._now()))

    def log_routing(self, item_id: str, tenant_id: str, input_text: str,
                    chosen_skill: str, confidence: float, reasoning: str,
                    latency_ms: int) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO routing_log
                  (queue_item_id, tenant_id, input_text, chosen_skill,
                   confidence, reasoning, latency_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_id, tenant_id, input_text, chosen_skill,
                  confidence, reasoning, latency_ms, self._now()))

    def move_to_dlq(self, item_id: str, reason: str, error: str, claim_token: str | None = None) -> bool:
        with self._conn() as conn:
            where = "id = ?"
            params: list = [self._now(), item_id]
            if claim_token:
                where += " AND claim_token = ?"
                params.append(claim_token)
            cursor = conn.execute(f"""
                UPDATE queue_items
                   SET status = 'failed',
                       claimed_by = NULL,
                       claim_token = NULL,
                       claimed_at = NULL,
                       lease_expires_at = NULL,
                       updated_at = ?
                 WHERE {where}
            """, params)
            if cursor.rowcount == 0:
                return False
            conn.execute("""
                INSERT INTO dlq_items (queue_item_id, failure_reason, last_error, moved_at)
                VALUES (?, ?, ?, ?)
            """, (item_id, reason, error, self._now()))
            return True

    def renew_lease(self, item_id: str, claim_token: str, lease_seconds: int) -> bool:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(lease_seconds))).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE queue_items
                   SET lease_expires_at = ?, updated_at = ?
                 WHERE id = ?
                   AND claim_token = ?
                   AND status IN ('routing', 'running')
                """,
                (expires_at, self._now(), item_id, claim_token),
            )
            return cursor.rowcount > 0

    def heartbeat_worker(self, worker_id: str, in_flight: int = 0) -> None:
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO queue_workers
                  (worker_id, hostname, pid, started_at, last_heartbeat, in_flight, claims_total, status)
                VALUES (?, ?, ?, ?, ?, ?, 0, 'online')
                ON CONFLICT(worker_id) DO UPDATE SET
                  last_heartbeat = excluded.last_heartbeat,
                  in_flight = excluded.in_flight,
                  status = 'online'
                """,
                (worker_id, socket.gethostname(), os.getpid(), now, now, int(in_flight or 0)),
            )

    def unregister_worker(self, worker_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE queue_workers SET status = 'offline', last_heartbeat = ? WHERE worker_id = ?",
                (self._now(), worker_id),
            )

    def reap_expired_claims(self, lease_reclaim_limit: int = 3) -> int:
        now = self._now()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, COALESCE(reclaim_count, 0) AS reclaim_count
                  FROM queue_items
                 WHERE status IN ('routing', 'running')
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < ?
                """,
                (now,),
            ).fetchall()
            for row in rows:
                next_reclaim = int(row["reclaim_count"] or 0) + 1
                if next_reclaim >= lease_reclaim_limit:
                    conn.execute(
                        """
                        INSERT INTO dlq_items (queue_item_id, failure_reason, last_error, moved_at)
                        VALUES (?, 'lease_reclaim_limit', 'Queue claim lease expired too many times', ?)
                        """,
                        (row["id"], now),
                    )
                    status = "failed"
                else:
                    status = "queued"
                conn.execute(
                    """
                    UPDATE queue_items
                       SET status = ?,
                           reclaim_count = ?,
                           claimed_by = NULL,
                           claim_token = NULL,
                           claimed_at = NULL,
                           lease_expires_at = NULL,
                           updated_at = ?
                     WHERE id = ?
                    """,
                    (status, next_reclaim, now, row["id"]),
                )
            return len(rows)


    def list_items(self, tenant_id: str, status: Optional[str] = None,
                   page: int = 1, limit: int = 20) -> tuple:
        offset = (page - 1) * limit
        where = "WHERE qi.tenant_id = ?"
        params: list = [tenant_id]
        if status:
            where += " AND qi.status = ?"
            params.append(status)

        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM queue_items qi " + where, params
            ).fetchone()[0]

            rows = conn.execute(
                "SELECT qi.*,"
                " je.skill_name as exec_skill,"
                " je.status as exec_status,"
                " je.result_summary"
                " FROM queue_items qi"
                " LEFT JOIN job_executions je ON je.queue_item_id = qi.id"
                " AND je.id = (SELECT id FROM job_executions"
                " WHERE queue_item_id = qi.id"
                " ORDER BY started_at DESC LIMIT 1) "
                + where +
                " ORDER BY"
                " CASE qi.priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,"
                " qi.created_at DESC"
                " LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        return [dict(r) for r in rows], total

    def get_item_by_external_id(self, external_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM queue_items WHERE external_id = ?",
                (external_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_item_detail(self, item_id: str) -> Optional[dict]:
        with self._conn() as conn:
            item = conn.execute(
                "SELECT * FROM queue_items WHERE id = ?", (item_id,)
            ).fetchone()
            if not item:
                return None

            execs = conn.execute(
                "SELECT * FROM job_executions WHERE queue_item_id = ? ORDER BY started_at DESC",
                (item_id,)
            ).fetchall()

            steps = []
            for ex in execs:
                ex_steps = conn.execute(
                    "SELECT * FROM job_steps WHERE job_execution_id = ? ORDER BY step_number, id",
                    (ex["id"],)
                ).fetchall()
                steps.append({"execution": dict(ex), "steps": [dict(s) for s in ex_steps]})

            routing = conn.execute(
                "SELECT * FROM routing_log WHERE queue_item_id = ? ORDER BY id DESC LIMIT 1",
                (item_id,)
            ).fetchone()

        return {
            "item": dict(item),
            "executions": steps,
            "routing": dict(routing) if routing else None,
        }

    def get_metrics(self, tenant_id: str) -> dict:
        worker_ttl = int(os.getenv("QUEUE_WORKER_HEARTBEAT_TTL_SECONDS", "30"))
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=worker_ttl)).isoformat()
        with self._conn() as conn:
            # Single query with conditional counts instead of 6 separate queries
            row = conn.execute("""
                SELECT
                    SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='routing' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='running' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='awaiting_human' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='done' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)
                FROM queue_items WHERE tenant_id=?
            """, (tenant_id,)).fetchone()

            queued   = row[0] or 0
            routing  = row[1] or 0
            running  = row[2] or 0
            awaiting = row[3] or 0
            done     = row[4] or 0
            failed   = row[5] or 0

            dlq = conn.execute("SELECT COUNT(*) FROM dlq_items").fetchone()[0]

            avg_ms = conn.execute("""
                SELECT AVG(CAST(
                    (JULIANDAY(completed_at) - JULIANDAY(started_at)) * 86400000
                AS INTEGER))
                FROM job_executions
                WHERE status = 'completed'
                  AND completed_at IS NOT NULL
                  AND started_at IS NOT NULL
            """).fetchone()[0] or 0
            worker_rows = conn.execute(
                """
                SELECT worker_id, hostname, pid, started_at, last_heartbeat,
                       in_flight, claims_total, status
                  FROM queue_workers
                 ORDER BY last_heartbeat DESC
                """
            ).fetchall()
            workers = [dict(row) for row in worker_rows]
            workers_online = sum(
                1
                for row in workers
                if row.get("status") == "online" and str(row.get("last_heartbeat") or "") >= cutoff
            )
            expired_claims = conn.execute(
                """
                SELECT COUNT(*)
                  FROM queue_items
                 WHERE status IN ('routing', 'running')
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < ?
                """,
                (self._now(),),
            ).fetchone()[0]

        return {
            "claim_backend": "sqlite",
            "queued": queued,
            "routing": routing,
            "running": running,
            "awaiting_human": awaiting,
            "done": done,
            "failed": failed,
            "dlq": dlq,
            "avg_latency_ms": int(avg_ms),
            "total_active": queued + routing + running + awaiting,
            "workers_online": workers_online,
            "workers_expected": 1,
            "workers": workers,
            "stale_claims": expired_claims,
            "processor_online": workers_online > 0,
        }


    def list_dlq(self, limit: int = 50) -> list:
        """Return DLQ items joined with their original queue_item metadata."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT d.id          AS dlq_id,
                       d.queue_item_id,
                       d.failure_reason,
                       d.last_error,
                       d.moved_at,
                       qi.title,
                       qi.description,
                       qi.priority,
                       qi.tenant_id,
                       qi.routed_skill AS requested_skill,
                       qi.created_at AS item_created_at
                FROM dlq_items d
                LEFT JOIN queue_items qi ON qi.id = d.queue_item_id
                ORDER BY d.moved_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def requeue_from_dlq(self, dlq_id: int) -> Optional[str]:
        """Remove item from DLQ and reset it to queued for retry. Returns item_id or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT queue_item_id FROM dlq_items WHERE id = ?", (dlq_id,)
            ).fetchone()
            if not row:
                return None
            item_id = row["queue_item_id"]
            conn.execute("DELETE FROM dlq_items WHERE id = ?", (dlq_id,))
            conn.execute("""
                UPDATE queue_items
                SET status = 'queued', retry_count = 0, updated_at = ?
                WHERE id = ?
            """, (self._now(), item_id))
        return item_id


_backend: Optional[QueueBackend] = None


def queue_storage_backend() -> str:
    configured = os.getenv("CC_QUEUE_STORAGE_BACKEND", "sqlite").strip().lower()
    if configured not in {"sqlite", "postgres"}:
        logger.warning("Unknown CC_QUEUE_STORAGE_BACKEND=%r; using sqlite", configured)
        return "sqlite"
    return configured


def get_db() -> QueueBackend:
    global _backend
    if _backend is None:
        backend = queue_storage_backend()
        if backend == "postgres":
            from cc_queue.postgres import PostgresQueueBackend

            _backend = PostgresQueueBackend()
        else:
            if _DB_PATH is None:
                raise RuntimeError("Call init_db_path() before get_db()")
            _backend = SQLiteQueueBackend(_DB_PATH)
    return _backend


def reset_backend_for_tests() -> None:
    global _backend, _DB_PATH
    _backend = None
    _DB_PATH = None
