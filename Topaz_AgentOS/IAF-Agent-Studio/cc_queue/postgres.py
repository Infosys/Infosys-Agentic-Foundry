"""Postgres Command Center queue backend with fenced claim leases."""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Optional

from cc_queue.db import QueueBackend
from iaf_agent_skills.storage.engine import PostgresEngine


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(cursor) -> list[dict]:
    columns = [col.name if hasattr(col, "name") else col[0] for col in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one(cursor) -> Optional[dict]:
    rows = _rows(cursor)
    return rows[0] if rows else None


class PostgresQueueBackend(QueueBackend):
    """Queue backend that uses Postgres row locks and claim leases."""

    def __init__(self, dsn: str | None = None):
        self.engine = PostgresEngine(
            dsn=dsn or os.getenv("CC_QUEUE_DATABASE_URL") or None,
            pool_size=int(os.getenv("CC_QUEUE_DB_POOL_SIZE", os.getenv("DB_POOL_SIZE", "10"))),
        )
        self._init_schema()

    def _init_schema(self) -> None:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_items (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'company',
                    external_id TEXT UNIQUE,
                    domain TEXT NOT NULL DEFAULT 'itops',
                    entity_id TEXT,
                    title TEXT NOT NULL,
                    description TEXT,
                    priority TEXT DEFAULT 'P3',
                    status TEXT DEFAULT 'queued',
                    routed_skill TEXT,
                    routing_reason TEXT,
                    retry_count INTEGER DEFAULT 0,
                    trace_id TEXT,
                    source TEXT DEFAULT 'manual',
                    claimed_by TEXT,
                    claim_token TEXT,
                    claimed_at TIMESTAMPTZ,
                    lease_expires_at TIMESTAMPTZ,
                    reclaim_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ
                )
                """
            )
            for ddl in (
                "ALTER TABLE queue_items ADD COLUMN IF NOT EXISTS claimed_by TEXT",
                "ALTER TABLE queue_items ADD COLUMN IF NOT EXISTS claim_token TEXT",
                "ALTER TABLE queue_items ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ",
                "ALTER TABLE queue_items ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ",
                "ALTER TABLE queue_items ADD COLUMN IF NOT EXISTS reclaim_count INTEGER DEFAULT 0",
            ):
                cur.execute(ddl)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS job_executions (
                    id TEXT PRIMARY KEY,
                    queue_item_id TEXT NOT NULL REFERENCES queue_items(id),
                    tenant_id TEXT,
                    skill_name TEXT,
                    status TEXT DEFAULT 'running',
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    result_summary TEXT,
                    evidence_trace_id TEXT,
                    evidence_count INTEGER DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS job_steps (
                    id BIGSERIAL PRIMARY KEY,
                    job_execution_id TEXT NOT NULL REFERENCES job_executions(id),
                    step_number INTEGER DEFAULT 0,
                    step_name TEXT,
                    action TEXT DEFAULT 'agent_step',
                    input TEXT,
                    output TEXT,
                    status TEXT DEFAULT 'completed',
                    duration_ms INTEGER DEFAULT 0,
                    timestamp TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS routing_log (
                    id BIGSERIAL PRIMARY KEY,
                    queue_item_id TEXT,
                    tenant_id TEXT,
                    input_text TEXT,
                    skills_considered TEXT,
                    chosen_skill TEXT,
                    confidence DOUBLE PRECISION DEFAULT 0.0,
                    reasoning TEXT,
                    model_used TEXT DEFAULT 'light',
                    latency_ms INTEGER DEFAULT 0,
                    timestamp TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS dlq_items (
                    id BIGSERIAL PRIMARY KEY,
                    queue_item_id TEXT,
                    failure_reason TEXT,
                    last_error TEXT,
                    moved_at TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_workers (
                    worker_id TEXT PRIMARY KEY,
                    hostname TEXT,
                    pid INTEGER,
                    started_at TIMESTAMPTZ,
                    last_heartbeat TIMESTAMPTZ,
                    in_flight INTEGER DEFAULT 0,
                    claims_total INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'online'
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_items(status, tenant_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_external ON queue_items(external_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_lease ON queue_items(status, lease_expires_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_exec_item ON job_executions(queue_item_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_steps_exec ON job_steps(job_execution_id)")

    def insert_item(self, item: dict) -> bool:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO queue_items
                  (id, tenant_id, external_id, domain, entity_id, title,
                   description, priority, status, trace_id, source, created_at, updated_at)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT(external_id) DO NOTHING
                """,
                (
                    item["id"],
                    item.get("tenant_id") or "company",
                    item.get("external_id"),
                    item.get("domain") or "itops",
                    item.get("entity_id"),
                    item.get("title"),
                    item.get("description"),
                    item.get("priority") or "P3",
                    item.get("status") or "queued",
                    item.get("trace_id"),
                    item.get("source") or "manual",
                ),
            )
            return cur.rowcount > 0

    def claim_next(
        self,
        tenant_id: str,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
    ) -> Optional[dict]:
        worker_id = worker_id or "postgres-worker"
        lease_seconds = int(lease_seconds or os.getenv("QUEUE_CLAIM_LEASE_SECONDS", "360"))
        claim_token = uuid.uuid4().hex
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                WITH candidate AS (
                    SELECT id
                      FROM queue_items
                     WHERE tenant_id = %s
                       AND status = 'queued'
                     ORDER BY
                       CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                       created_at ASC
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                )
                UPDATE queue_items qi
                   SET status = 'routing',
                       claimed_by = %s,
                       claim_token = %s,
                       claimed_at = NOW(),
                       lease_expires_at = NOW() + (%s * interval '1 second'),
                       updated_at = NOW()
                  FROM candidate
                 WHERE qi.id = candidate.id
                 RETURNING qi.*
                """,
                (tenant_id, worker_id, claim_token, lease_seconds),
            )
            item = _one(cur)
            if item:
                cur.execute(
                    """
                    INSERT INTO queue_workers
                      (worker_id, hostname, pid, started_at, last_heartbeat, in_flight, claims_total, status)
                    VALUES (%s, %s, %s, NOW(), NOW(), 0, 1, 'online')
                    ON CONFLICT(worker_id) DO UPDATE SET
                      last_heartbeat = NOW(),
                      claims_total = queue_workers.claims_total + 1,
                      status = 'online'
                    """,
                    (worker_id, socket.gethostname(), os.getpid()),
                )
            return item

    def update_item(self, item_id: str, claim_token: str | None = None,
                    expected_status: str | None = None, **fields) -> bool:
        status = fields.get("status")
        if status in {"queued", "done", "failed", "awaiting_human"}:
            fields.setdefault("claimed_by", None)
            fields.setdefault("claim_token", None)
            fields.setdefault("claimed_at", None)
            fields.setdefault("lease_expires_at", None)
        assignments = [f"{key} = %s" for key in fields]
        values = list(fields.values())
        assignments.append("updated_at = NOW()")
        where = "id = %s"
        values.append(item_id)
        if claim_token:
            where += " AND claim_token = %s"
            values.append(claim_token)
        if expected_status:
            where += " AND status = %s"
            values.append(expected_status)
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE queue_items SET {', '.join(assignments)} WHERE {where}",
                tuple(values),
            )
            return cur.rowcount > 0

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
        with self.engine.connect() as conn:
            cur = conn.cursor()
            where = "id = %s"
            params: list = [item_status, item_id]
            if claim_token:
                where += " AND claim_token = %s"
                params.append(claim_token)
            cur.execute(
                f"""
                UPDATE queue_items
                   SET status = %s,
                       claimed_by = NULL,
                       claim_token = NULL,
                       claimed_at = NULL,
                       lease_expires_at = NULL,
                       updated_at = NOW()
                 WHERE {where}
                """,
                tuple(params),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                """
                UPDATE job_executions
                   SET status = %s,
                       result_summary = %s,
                       completed_at = NOW()
                 WHERE id = %s
                """,
                (execution_status, result_summary, exec_id),
            )
            return True

    def create_execution(self, exec_id: str, item_id: str, tenant_id: str, skill: str) -> None:
        with self.engine.connect() as conn:
            conn.cursor().execute(
                """
                INSERT INTO job_executions
                  (id, queue_item_id, tenant_id, skill_name, status, started_at)
                VALUES (%s, %s, %s, %s, 'running', NOW())
                """,
                (exec_id, item_id, tenant_id, skill),
            )

    def update_execution(self, exec_id: str, **fields) -> None:
        if "completed_at" not in fields:
            fields["completed_at"] = _utc_iso()
        assignments = [f"{key} = %s" for key in fields]
        values = list(fields.values()) + [exec_id]
        with self.engine.connect() as conn:
            conn.cursor().execute(
                f"UPDATE job_executions SET {', '.join(assignments)} WHERE id = %s",
                tuple(values),
            )

    def set_execution_evidence(self, exec_id: str, evidence_trace_id: str, evidence_count: int) -> None:
        with self.engine.connect() as conn:
            conn.cursor().execute(
                """
                UPDATE job_executions
                   SET evidence_trace_id = %s, evidence_count = %s
                 WHERE id = %s
                """,
                (evidence_trace_id, int(evidence_count or 0), exec_id),
            )

    def append_step(
        self,
        exec_id: str,
        step_number: int,
        step_name: str,
        output: str,
        action: str = "agent_step",
        duration_ms: int = 0,
    ) -> None:
        with self.engine.connect() as conn:
            conn.cursor().execute(
                """
                INSERT INTO job_steps
                  (job_execution_id, step_number, step_name, action, output,
                   status, duration_ms, timestamp)
                VALUES (%s, %s, %s, %s, %s, 'completed', %s, NOW())
                """,
                (exec_id, step_number, step_name, action, output, duration_ms),
            )

    def log_routing(
        self,
        item_id: str,
        tenant_id: str,
        input_text: str,
        chosen_skill: str,
        confidence: float,
        reasoning: str,
        latency_ms: int,
    ) -> None:
        with self.engine.connect() as conn:
            conn.cursor().execute(
                """
                INSERT INTO routing_log
                  (queue_item_id, tenant_id, input_text, chosen_skill,
                   confidence, reasoning, latency_ms, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (item_id, tenant_id, input_text, chosen_skill, confidence, reasoning, latency_ms),
            )

    def move_to_dlq(self, item_id: str, reason: str, error: str, claim_token: str | None = None) -> bool:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            where = "id = %s"
            params: list = [item_id]
            if claim_token:
                where += " AND claim_token = %s"
                params.append(claim_token)
            cur.execute(
                f"""
                UPDATE queue_items
                   SET status = 'failed',
                       claimed_by = NULL,
                       claim_token = NULL,
                       claimed_at = NULL,
                       lease_expires_at = NULL,
                       updated_at = NOW()
                 WHERE {where}
                """,
                tuple(params),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                """
                INSERT INTO dlq_items (queue_item_id, failure_reason, last_error, moved_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (item_id, reason, error),
            )
            return True

    def renew_lease(self, item_id: str, claim_token: str, lease_seconds: int) -> bool:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE queue_items
                   SET lease_expires_at = NOW() + (%s * interval '1 second'),
                       updated_at = NOW()
                 WHERE id = %s
                   AND claim_token = %s
                   AND status IN ('routing', 'running')
                """,
                (int(lease_seconds), item_id, claim_token),
            )
            return cur.rowcount > 0

    def heartbeat_worker(self, worker_id: str, in_flight: int = 0) -> None:
        with self.engine.connect() as conn:
            conn.cursor().execute(
                """
                INSERT INTO queue_workers
                  (worker_id, hostname, pid, started_at, last_heartbeat, in_flight, claims_total, status)
                VALUES (%s, %s, %s, NOW(), NOW(), %s, 0, 'online')
                ON CONFLICT(worker_id) DO UPDATE SET
                  last_heartbeat = NOW(),
                  in_flight = excluded.in_flight,
                  status = 'online'
                """,
                (worker_id, socket.gethostname(), os.getpid(), int(in_flight or 0)),
            )

    def unregister_worker(self, worker_id: str) -> None:
        with self.engine.connect() as conn:
            conn.cursor().execute(
                "UPDATE queue_workers SET status = 'offline', last_heartbeat = NOW() WHERE worker_id = %s",
                (worker_id,),
            )

    def reap_expired_claims(self, lease_reclaim_limit: int = 3) -> int:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, COALESCE(reclaim_count, 0) AS reclaim_count
                  FROM queue_items
                 WHERE status IN ('routing', 'running')
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < NOW()
                 FOR UPDATE SKIP LOCKED
                """
            )
            rows = _rows(cur)
            for row in rows:
                next_reclaim = int(row.get("reclaim_count") or 0) + 1
                if next_reclaim >= lease_reclaim_limit:
                    cur.execute(
                        """
                        INSERT INTO dlq_items (queue_item_id, failure_reason, last_error, moved_at)
                        VALUES (%s, 'lease_reclaim_limit', 'Queue claim lease expired too many times', NOW())
                        """,
                        (row["id"],),
                    )
                    status = "failed"
                else:
                    status = "queued"
                cur.execute(
                    """
                    UPDATE queue_items
                       SET status = %s,
                           reclaim_count = %s,
                           claimed_by = NULL,
                           claim_token = NULL,
                           claimed_at = NULL,
                           lease_expires_at = NULL,
                           updated_at = NOW()
                     WHERE id = %s
                    """,
                    (status, next_reclaim, row["id"]),
                )
            return len(rows)

    def list_items(self, tenant_id: str, status: Optional[str] = None, page: int = 1, limit: int = 20) -> tuple:
        offset = (page - 1) * limit
        where = "WHERE qi.tenant_id = %s"
        params: list = [tenant_id]
        if status:
            where += " AND qi.status = %s"
            params.append(status)
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM queue_items qi {where}", tuple(params))
            total = cur.fetchone()[0]
            cur.execute(
                f"""
                SELECT qi.*,
                       je.skill_name as exec_skill,
                       je.status as exec_status,
                       je.result_summary
                FROM queue_items qi
                LEFT JOIN job_executions je ON je.queue_item_id = qi.id
                  AND je.id = (SELECT id FROM job_executions
                                WHERE queue_item_id = qi.id
                                ORDER BY started_at DESC LIMIT 1)
                {where}
                ORDER BY
                    CASE qi.priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                    qi.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [limit, offset]),
            )
            return _rows(cur), total

    def get_item_by_external_id(self, external_id: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM queue_items WHERE external_id = %s", (external_id,))
            return _one(cur)

    def get_item_detail(self, item_id: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM queue_items WHERE id = %s", (item_id,))
            item = _one(cur)
            if not item:
                return None
            cur.execute(
                "SELECT * FROM job_executions WHERE queue_item_id = %s ORDER BY started_at DESC",
                (item_id,),
            )
            execs = _rows(cur)
            steps = []
            for execution in execs:
                cur.execute(
                    "SELECT * FROM job_steps WHERE job_execution_id = %s ORDER BY step_number, id",
                    (execution["id"],),
                )
                steps.append({"execution": execution, "steps": _rows(cur)})
            cur.execute(
                "SELECT * FROM routing_log WHERE queue_item_id = %s ORDER BY id DESC LIMIT 1",
                (item_id,),
            )
            return {"item": item, "executions": steps, "routing": _one(cur)}

    def get_metrics(self, tenant_id: str) -> dict:
        worker_ttl = int(os.getenv("QUEUE_WORKER_HEARTBEAT_TTL_SECONDS", "30"))
        expected = int(os.getenv("QUEUE_WORKER_REPLICAS", "1"))
        with self.engine.connect() as conn:
            cur = conn.cursor()

            def count(status: str) -> int:
                cur.execute(
                    "SELECT COUNT(*) FROM queue_items WHERE tenant_id = %s AND status = %s",
                    (tenant_id, status),
                )
                return int(cur.fetchone()[0])

            queued = count("queued")
            routing = count("routing")
            running = count("running")
            awaiting = count("awaiting_human")
            done = count("done")
            failed = count("failed")
            cur.execute("SELECT COUNT(*) FROM dlq_items")
            dlq = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000)
                  FROM job_executions
                 WHERE status = 'completed'
                   AND completed_at IS NOT NULL
                   AND started_at IS NOT NULL
                """
            )
            avg_ms = cur.fetchone()[0] or 0
            cur.execute(
                """
                SELECT worker_id, hostname, pid, started_at, last_heartbeat,
                       in_flight, claims_total, status
                  FROM queue_workers
                 ORDER BY last_heartbeat DESC
                """
            )
            workers = _rows(cur)
            cur.execute(
                """
                SELECT COUNT(*)
                  FROM queue_workers
                 WHERE status = 'online'
                   AND last_heartbeat >= NOW() - (%s * interval '1 second')
                """,
                (worker_ttl,),
            )
            workers_online = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*)
                  FROM queue_items
                 WHERE status IN ('routing', 'running')
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < NOW()
                """
            )
            stale_claims = int(cur.fetchone()[0])

        return {
            "claim_backend": "postgres",
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
            "workers_expected": expected,
            "workers": workers,
            "stale_claims": stale_claims,
            "processor_online": workers_online > 0,
        }

    def list_dlq(self, limit: int = 50) -> list:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT d.id AS dlq_id,
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
                 LIMIT %s
                """,
                (limit,),
            )
            return _rows(cur)

    def requeue_from_dlq(self, dlq_id: int) -> Optional[str]:
        with self.engine.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT queue_item_id FROM dlq_items WHERE id = %s", (dlq_id,))
            row = cur.fetchone()
            if not row:
                return None
            item_id = row[0]
            cur.execute("DELETE FROM dlq_items WHERE id = %s", (dlq_id,))
            cur.execute(
                """
                UPDATE queue_items
                   SET status = 'queued',
                       retry_count = 0,
                       claimed_by = NULL,
                       claim_token = NULL,
                       claimed_at = NULL,
                       lease_expires_at = NULL,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (item_id,),
            )
            return item_id
