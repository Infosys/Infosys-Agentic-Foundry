"""
Operational Digital Twin – Telemetry Emitter
=============================================

Fire-and-forget telemetry writer for the IAF Agent Studio.

Design principles
-----------------
* **Never block** the main request path – uses an asyncio.Queue drained
  by a single background writer task.
* **Never crash** – every public method wraps in try/except:pass so
  telemetry issues can never disrupt production chat.
* **Single writer** – avoids SQLite "database is locked" contention by
  funnelling all writes through one connection.
* **Batch friendly** – drains the queue in bursts for I/O efficiency.

Usage (in server.py)
--------------------
    from twin_emitter import get_twin_emitter

    emitter = get_twin_emitter(DATA_ROOT)
    await emitter.start()                     # once, at startup

    emitter.emit("task_events",               # fire-and-forget
        event_id=uuid4().hex,
        event_type="task_completed",
        timestamp=datetime.now().isoformat(),
        user_id="madhan",
        skill="ar_ops",
        latency_ms=1230.5,
    )
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from telemetry_providers import TelemetryProviderFanout

import logging
logger = logging.getLogger(__name__)



SCHEMA_SQL = """
-- Task lifecycle events (one row per chat turn)
CREATE TABLE IF NOT EXISTS task_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT    UNIQUE NOT NULL,
    event_type      TEXT    NOT NULL,           -- task_started | task_completed | task_error
    timestamp       TEXT    NOT NULL,
    user_id         TEXT,
    skill           TEXT,
    latency_ms      REAL,
    token_count     INTEGER,
    has_pending     INTEGER DEFAULT 0,          -- 1 = triggered HITL
    error_message   TEXT,
    metadata        TEXT                        -- JSON blob for extensibility
);

-- Per-skill invocation log (lighter than task_events, easier to aggregate)
CREATE TABLE IF NOT EXISTS skill_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    skill           TEXT    NOT NULL,
    user_id         TEXT,
    success         INTEGER DEFAULT 1,
    latency_ms      REAL,
    tool_calls      INTEGER DEFAULT 0
);

-- HITL approval / rejection tracking
CREATE TABLE IF NOT EXISTS hitl_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    user_id         TEXT,
    skill           TEXT,
    action_type     TEXT,                       -- approve | reject | escalate | timeout
    urgency         TEXT,                       -- low | medium | high | critical
    wait_time_ms    REAL,                       -- creation → resolution
    amount          REAL,                       -- transaction amount if applicable
    metadata        TEXT
);

-- Pre-aggregated daily snapshot for fast dashboard rendering
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date        TEXT    NOT NULL UNIQUE,
    total_tasks          INTEGER DEFAULT 0,
    completed_tasks      INTEGER DEFAULT 0,
    error_tasks          INTEGER DEFAULT 0,
    avg_latency_ms       REAL,
    p95_latency_ms       REAL,
    unique_users         INTEGER DEFAULT 0,
    top_skill            TEXT,
    hitl_count           INTEGER DEFAULT 0,
    hitl_approval_rate   REAL,
    -- Cross-domain business KPIs (pulled from operational DBs)
    ar_total_outstanding REAL,
    ar_overdue           REAL,
    ar_dso_days          REAL,
    ap_open_amount       REAL,
    ap_overdue           REAL,
    metadata             TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_events_ts   ON task_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_task_events_skill ON task_events(skill);
CREATE INDEX IF NOT EXISTS idx_skill_usage_ts   ON skill_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_hitl_events_ts   ON hitl_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_date   ON daily_snapshots(snapshot_date);
"""

DB_NAME = "twin_telemetry.db"



class TwinEmitter:
    """
    Async-safe, fire-and-forget telemetry writer.

    All writes are enqueued instantly (non-blocking).  A single background
    asyncio task drains the queue in batches and writes to SQLite.
    """

    def __init__(
        self,
        db_path: str,
        *,
        exporters: Optional[List[Callable]] = None,
        telemetry_providers: Optional[Any] = None,
    ):
        self._db_path = db_path
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._exporters: List[Callable] = exporters or []
        self._telemetry_fanout = TelemetryProviderFanout.coerce(telemetry_providers)
        self._ensure_schema()


    def _ensure_schema(self):
        """Create twin_telemetry tables if they don't exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = _sqlite_connect(self._db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    async def start(self):
        """Start the background writer.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._writer_loop())
        logger.debug(f"⚡ Twin emitter started → {self._db_path}")

    async def stop(self):
        """Graceful shutdown – flush remaining events."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Final drain
        remaining = self._drain_queue()
        if remaining:
            self._flush(remaining)


    def emit(self, table: str, **kwargs: Any) -> None:
        """
        Enqueue a telemetry event.  Non-blocking, never raises.

        Parameters
        ----------
        table : str
            Target table name (task_events | skill_usage | hitl_events).
        **kwargs
            Column=value pairs matching the target table schema.
        """
        try:
            event = {"_table": table, **kwargs}
            self._queue.put_nowait(event)
            self._notify_exporters("twin_event", event)
        except Exception:
            pass  # Queue full or shutting down – silently drop

    def register_exporter(self, callback: Callable) -> None:
        """Register a legacy callback exporter for twin telemetry events."""
        self._exporters.append(callback)

    def unregister_exporter(self, callback: Callable) -> None:
        """Remove a previously registered twin telemetry exporter."""
        try:
            self._exporters.remove(callback)
        except ValueError:
            pass

    def telemetry_diagnostics(self) -> Dict[str, Any]:
        """Return safe provider diagnostics for capability snapshots."""
        try:
            return self._telemetry_fanout.snapshot()
        except Exception:
            return {"mode": "unknown", "provider_count": 0, "providers": []}

    def emit_task_started(self, *, user_id: str, skill: str = "", **extra):
        """Convenience: emit a task_started event."""
        self.emit(
            "task_events",
            event_id=uuid.uuid4().hex,
            event_type="task_started",
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            skill=skill,
            **extra,
        )

    def emit_task_completed(
        self,
        *,
        user_id: str,
        skill: str = "",
        latency_ms: float = 0,
        has_pending: bool = False,
        token_count: int = 0,
        **extra,
    ):
        """Convenience: emit task_completed + skill_usage in one call."""
        now = datetime.now().isoformat()
        self.emit(
            "task_events",
            event_id=uuid.uuid4().hex,
            event_type="task_completed",
            timestamp=now,
            user_id=user_id,
            skill=skill,
            latency_ms=latency_ms,
            has_pending=1 if has_pending else 0,
            token_count=token_count,
            **extra,
        )
        if skill:
            self.emit(
                "skill_usage",
                timestamp=now,
                skill=skill,
                user_id=user_id,
                success=1,
                latency_ms=latency_ms,
            )

    def emit_task_error(self, *, user_id: str, skill: str = "", error: str = "", **extra):
        """Convenience: emit a task_error event."""
        self.emit(
            "task_events",
            event_id=uuid.uuid4().hex,
            event_type="task_error",
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            skill=skill,
            error_message=error[:500],
            **extra,
        )
        if skill:
            self.emit(
                "skill_usage",
                timestamp=datetime.now().isoformat(),
                skill=skill,
                user_id=user_id,
                success=0,
            )

    def emit_hitl(
        self,
        *,
        user_id: str,
        skill: str = "",
        action_type: str = "approve",
        urgency: str = "medium",
        wait_time_ms: float = 0,
        amount: float = 0,
        **extra,
    ):
        """Convenience: emit a HITL approval/rejection event."""
        self.emit(
            "hitl_events",
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            skill=skill,
            action_type=action_type,
            urgency=urgency,
            wait_time_ms=wait_time_ms,
            amount=amount,
            **extra,
        )


    def _drain_queue(self) -> List[Dict]:
        """Pull all pending events from the queue."""
        batch = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def _notify_exporters(self, event_type: str, payload: Dict) -> None:
        """Forward event to registered exporters. Never raises."""
        try:
            self._telemetry_fanout.emit(event_type, payload, source="twin")
        except Exception:
            pass
        for exporter in self._exporters:
            try:
                exporter(event_type, payload)
            except Exception:
                pass

    async def _writer_loop(self):
        """Background coroutine: wait for events, batch-write to SQLite."""
        while self._running:
            batch: List[Dict] = []
            try:
                # Block until at least one event arrives (with timeout for shutdown)
                first = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                batch.append(first)
                # Non-blocking drain of anything else queued
                batch.extend(self._drain_queue())
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                # Shutting down – flush whatever we have
                batch.extend(self._drain_queue())
                if batch:
                    self._flush(batch)
                return
            except Exception:
                continue

            if batch:
                self._flush(batch)

    _VALID_TWIN_TABLES = frozenset({"task_events", "skill_usage", "hitl_events"})

    def _flush(self, batch: List[Dict]) -> None:
        """Write a batch of events to SQLite.  Never raises."""
        import re as _re
        _SAFE_COL_RE = _re.compile(r'^[a-z_][a-z0-9_]*$')
        try:
            conn = _sqlite_connect(self._db_path)
            cursor = conn.cursor()
            for event in batch:
                table = event.pop("_table", "task_events")
                if table not in self._VALID_TWIN_TABLES:
                    logger.debug("Twin flush: rejecting unknown table %r", table)
                    continue
                validated_table = table
                safe_cols = [c for c in event.keys() if _SAFE_COL_RE.match(c)]
                if len(safe_cols) != len(event):
                    logger.debug("Twin flush: rejecting event with unsafe column names")
                    continue
                cols = ", ".join(safe_cols)
                placeholders = ", ".join(["?"] * len(safe_cols))
                try:
                    cursor.execute(
                        "INSERT INTO " + validated_table + " (" + cols + ") VALUES (" + placeholders + ")",
                        [event[c] for c in safe_cols],
                    )
                except sqlite3.IntegrityError:
                    pass  # Duplicate event_id – safe to skip
                except Exception as e:
                    logger.debug(f"Twin emit row error (non-fatal): {e}")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Twin emit flush error (non-fatal): {e}")



_emitter: Optional[TwinEmitter] = None


def get_twin_emitter(
    data_root: str,
    tenant: str = "company",
    *,
    exporters: Optional[List[Callable]] = None,
    telemetry_providers: Optional[Any] = None,
) -> TwinEmitter:
    """
    Get (or create) the singleton TwinEmitter.

    Parameters
    ----------
    data_root : str
        Path to enterprise_root (from DATA_ROOT env / config).
    tenant : str
        Tenant directory name.  Default: "company".
    exporters : list of callables, optional
        Legacy callback exporters for operational telemetry events.
    telemetry_providers : TelemetryProviderFanout or provider list, optional
        Enterprise telemetry provider fanout.

    Returns
    -------
    TwinEmitter
    """
    global _emitter
    if _emitter is None:
        db_path = str(
            Path(data_root)
            / "tenants"
            / tenant
            / "shared"
            / "databases"
            / DB_NAME
        )
        _emitter = TwinEmitter(db_path, exporters=exporters, telemetry_providers=telemetry_providers)
    return _emitter


def reset_twin_emitter() -> None:
    """Reset singleton – used in tests."""
    global _emitter
    _emitter = None
