"""
Execution Trace Emitter — 3-Layer Agent Observability
======================================================

Fire-and-forget trace writer for full agent execution observability.
Records every step (span) within every request (trace) to a SQLite database,
enabling waterfall timeline views, latency analysis, and root-cause debugging.

Design principles
-----------------
* **Framework-agnostic** — zero imports from agent.py, memory.py, or server.py.
  Any agent framework (LangChain, CrewAI, AutoGen, custom) can emit traces
  using plain dicts / TypedDicts.
* **Never block** — uses an asyncio.Queue drained by a single background
  writer task, identical to twin_emitter.py.
* **Never crash** — every public method wraps in try/except so tracing
  issues can never disrupt production chat.
* **Single writer** — avoids SQLite "database is locked" contention by
  funnelling all writes through one connection in WAL mode.
* **Batch friendly** — drains the queue in bursts for I/O efficiency.
* **Pluggable exporters** — optional callback receives every span for
  forwarding to OpenTelemetry / Datadog / Kafka / etc.
* **Retention-aware** — built-in purge method for time-based cleanup.

Architecture
------------
Two tables:

* **traces** — one row per request (begin → end lifecycle)
    trace_id, session_id, tenant, agent, user_id, skill, query_preview,
    status, span_count, total_ms, created_at, ended_at, metadata

* **spans** — N rows per trace (one per execution step)
    trace_id (FK), span_type, name, start_ms (epoch millis), duration_ms,
    status, input_preview, output_preview, metadata, created_at

Usage
-----
    from trace_emitter import get_trace_emitter

    emitter = get_trace_emitter(DATA_ROOT)
    await emitter.start()

    # In agent run():
    trace_id = emitter.begin_trace(session_id=sid, user_id="u1", skill="ar")
    emitter.add_span(trace_id=trace_id, span_type="route", name="skill_router",
                     start_ms=t0, duration_ms=12.3, status="ok",
                     input_preview="reconcile invoice", output_preview="ar_ops")
    ...
    emitter.end_trace(trace_id=trace_id, status="success", span_count=7, total_ms=1200)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

from telemetry_providers import TelemetryProviderFanout

import logging
logger = logging.getLogger(__name__)


def _resolve_trace_backend() -> str:
    """Own opt-in flag (independent of DB_BACKEND). Default sqlite so the live server is
    unaffected until an operator sets TRACE_BACKEND=postgres for a shared, fleet-wide store."""
    raw = (os.getenv("TRACE_BACKEND", "sqlite") or "sqlite").strip().lower()
    return "postgres" if raw in ("postgres", "postgresql", "pg") else "sqlite"


# Portable charset for the trace DB path (mirrors agent_os.safe_path._PATH_STRING_RE;
# inlined because this module is importable without the repo's agent_os on sys.path).
_DB_PATH_RE = re.compile(r"^[\w .@+()~:/\\\-]{1,4096}$")


def _validated_db_path(raw: str) -> str:
    """Validate the trace DB path (caller arg / TRACE_DB_PATH), resolve, rebuild (CWE-22/73)."""
    value = os.fspath(raw).strip() if raw is not None else ""
    if not value or not _DB_PATH_RE.fullmatch(value):
        raise ValueError(
            "Invalid trace DB path: value is empty or contains characters outside "
            "the allowed path charset"
        )
    return str(Path(str(Path(value).expanduser().resolve())))


# Shared traces+spans tables in a `trace` schema, discriminated by tenant/agent/user columns.
TRACE_SCHEMA_PG = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.traces (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trace_id          TEXT UNIQUE NOT NULL,
    session_id        TEXT,
    tenant            TEXT DEFAULT 'default',
    agent             TEXT DEFAULT 'default',
    user_id           TEXT,
    skill             TEXT,
    query_preview     TEXT,
    status            TEXT DEFAULT 'running',
    span_count        INTEGER DEFAULT 0,
    total_ms          DOUBLE PRECISION DEFAULT 0,
    created_at        TEXT NOT NULL,
    ended_at          TEXT,
    metadata          TEXT,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_usd          DOUBLE PRECISION DEFAULT 0,
    parent_trace_id   TEXT,
    orchestrator_step INTEGER
);
CREATE TABLE IF NOT EXISTS {schema}.spans (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    span_type       TEXT NOT NULL,
    name            TEXT NOT NULL,
    start_ms        DOUBLE PRECISION NOT NULL,
    duration_ms     DOUBLE PRECISION DEFAULT 0,
    status          TEXT DEFAULT 'ok',
    input_preview   TEXT,
    output_preview  TEXT,
    metadata        TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_created ON {schema}.traces(created_at);
CREATE INDEX IF NOT EXISTS idx_traces_session ON {schema}.traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_skill   ON {schema}.traces(skill);
CREATE INDEX IF NOT EXISTS idx_traces_status  ON {schema}.traces(status);
CREATE INDEX IF NOT EXISTS idx_traces_user    ON {schema}.traces(user_id);
CREATE INDEX IF NOT EXISTS idx_traces_tenant  ON {schema}.traces(tenant);
CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON {schema}.spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_type     ON {schema}.spans(span_type);
CREATE INDEX IF NOT EXISTS idx_spans_created  ON {schema}.spans(created_at);
"""



class TraceSpan(TypedDict, total=False):
    """
    Protocol for a single execution span.

    Any agent framework can construct this dict and pass it to add_span().
    All fields are plain Python types — no framework-specific objects.
    """
    trace_id: str           # Required: parent trace
    span_type: str          # Required: route | knowledge | llm | tool | hitl | memory | response | custom
    name: str               # Required: human-readable label (e.g., "gpt-4o call")
    start_ms: float         # Required: epoch milliseconds when span started
    duration_ms: float      # Required: wall-clock duration
    status: str             # "ok" | "error" | "skipped"
    input_preview: str      # First 8192 chars of input (for debugging)
    output_preview: str     # First 8192 chars of output
    metadata: str           # JSON string for arbitrary context



TRACE_SCHEMA_SQL = """
-- Execution traces: one row per agent request
CREATE TABLE IF NOT EXISTS traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT    UNIQUE NOT NULL,
    session_id      TEXT,
    tenant          TEXT    DEFAULT 'default',
    agent           TEXT    DEFAULT 'default',
    user_id         TEXT,
    skill           TEXT,
    query_preview   TEXT,                   -- first 8192 chars of user query
    status          TEXT    DEFAULT 'running',  -- running | success | error
    span_count      INTEGER DEFAULT 0,
    total_ms        REAL    DEFAULT 0,
    created_at      TEXT    NOT NULL,
    ended_at        TEXT,
    metadata        TEXT                    -- JSON blob for extensibility
    prompt_tokens   INTEGER DEFAULT 0,      -- LLM input tokens for this trace
    completion_tokens INTEGER DEFAULT 0,    -- LLM output tokens for this trace
    cost_usd        REAL    DEFAULT 0       -- Estimated cost in USD
);

-- Execution spans: N rows per trace (one per agent step)
CREATE TABLE IF NOT EXISTS spans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT    NOT NULL,
    span_type       TEXT    NOT NULL,       -- route | knowledge | llm | tool | hitl | memory | response | custom
    name            TEXT    NOT NULL,       -- human-readable label
    start_ms        REAL    NOT NULL,       -- epoch millis when span started
    duration_ms     REAL    DEFAULT 0,      -- wall-clock duration
    status          TEXT    DEFAULT 'ok',   -- ok | error | skipped
    input_preview   TEXT,                   -- first 8192 chars of input
    output_preview  TEXT,                   -- first 8192 chars of output
    metadata        TEXT,                   -- JSON blob
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
);

-- Indexes for fast dashboard queries
CREATE INDEX IF NOT EXISTS idx_traces_created    ON traces(created_at);
CREATE INDEX IF NOT EXISTS idx_traces_session    ON traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_skill      ON traces(skill);
CREATE INDEX IF NOT EXISTS idx_traces_status     ON traces(status);
CREATE INDEX IF NOT EXISTS idx_traces_user       ON traces(user_id);
CREATE INDEX IF NOT EXISTS idx_traces_tenant     ON traces(tenant);
CREATE INDEX IF NOT EXISTS idx_spans_trace_id    ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_type        ON spans(span_type);
CREATE INDEX IF NOT EXISTS idx_spans_created     ON spans(created_at);
"""

# Model pricing: USD per 1,000 tokens (input/output); keys are lowercase substrings of the deployment name.
MODEL_PRICING = {
    "gpt-4o-mini":  {"input": 0.000150, "output": 0.000600},
    "gpt-4o":       {"input": 0.002500, "output": 0.010000},
    "gpt-4-turbo":  {"input": 0.010000, "output": 0.030000},
    "gpt-4":        {"input": 0.030000, "output": 0.060000},
    "gpt-35-turbo": {"input": 0.000500, "output": 0.001500},
    "o1-mini":      {"input": 0.003000, "output": 0.012000},
    "o1":           {"input": 0.015000, "output": 0.060000},
    # Claude (Anthropic)
    "claude-opus-4":     {"input": 0.015000, "output": 0.075000},
    "claude-sonnet-4":   {"input": 0.003000, "output": 0.015000},
    "claude-3-5-haiku":  {"input": 0.000800, "output": 0.004000},
    "claude-3-5-sonnet": {"input": 0.003000, "output": 0.015000},
    "claude-3-opus":     {"input": 0.015000, "output": 0.075000},
    "claude-3-haiku":    {"input": 0.000250, "output": 0.001250},
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated cost in USD for a single LLM call."""
    model_lower = (model or "").lower()
    pricing = None
    for key in MODEL_PRICING:
        if key in model_lower:
            pricing = MODEL_PRICING[key]
            break
    if not pricing:
        pricing = MODEL_PRICING["gpt-4o"]   # safe default
    return round(
        (prompt_tokens / 1000) * pricing["input"]
        + (completion_tokens / 1000) * pricing["output"],
        8,
    )


DB_NAME = "traces.db"

_VALID_TRACE_TABLES = frozenset({"traces", "spans"})

_TRACE_MIGRATIONS = (
    "ALTER TABLE traces ADD COLUMN prompt_tokens INTEGER DEFAULT 0",
    "ALTER TABLE traces ADD COLUMN completion_tokens INTEGER DEFAULT 0",
    "ALTER TABLE traces ADD COLUMN cost_usd REAL DEFAULT 0",
    "ALTER TABLE traces ADD COLUMN parent_trace_id TEXT",
    "ALTER TABLE traces ADD COLUMN orchestrator_step INTEGER",
)


def _sql_where(conditions: list) -> str:
    """Build a WHERE clause from validated condition strings."""
    if not conditions:
        return "1=1"
    return " AND ".join(conditions)


def _sql_in_clause(count: int, ph: str = "?") -> str:
    """Build a parameterized IN clause with the given number of placeholders.

    ``ph`` is the backend placeholder token ('?' SQLite / '%s' Postgres).
    """
    if count <= 0:
        return "(NULL)"
    return "(" + ", ".join(ph for _ in range(count)) + ")"


def _sql_set_clause(columns: list) -> str:
    """Build a SET clause from validated column=? fragments."""
    if not columns:
        raise ValueError("No columns to update")
    return ", ".join(columns)


# Fortify-safe column-name allowlist regex, shared by the SQLite and Postgres
# flush paths so untrusted column names cannot be interpolated into DDL/DML.
_SAFE_COL_RE = re.compile(r'^[a-z_][a-z0-9_]*$')


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _metadata_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _span_token_totals(spans: List[Dict[str, Any]]) -> Dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    cost_usd = 0.0
    for span in spans:
        metadata = _metadata_dict(span.get("metadata"))
        span_prompt = _safe_int(metadata.get("prompt_tokens"))
        span_completion = _safe_int(metadata.get("completion_tokens"))
        span_cost = _safe_float(metadata.get("cost_usd") or metadata.get("cost"))
        if not span_cost and (span_prompt or span_completion):
            span_cost = calculate_cost(str(metadata.get("model") or ""), span_prompt, span_completion)
        prompt_tokens += span_prompt
        completion_tokens += span_completion
        cost_usd += span_cost
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost_usd, 8),
    }


def _apply_token_fallback(trace: Dict[str, Any], spans: List[Dict[str, Any]]) -> None:
    if not _safe_int(trace.get("span_count")) and spans:
        trace["span_count"] = len(spans)
    totals = _span_token_totals(spans)
    if not _safe_int(trace.get("prompt_tokens")) and totals["prompt_tokens"]:
        trace["prompt_tokens"] = totals["prompt_tokens"]
    if not _safe_int(trace.get("completion_tokens")) and totals["completion_tokens"]:
        trace["completion_tokens"] = totals["completion_tokens"]
    if not _safe_float(trace.get("cost_usd")) and totals["cost_usd"]:
        trace["cost_usd"] = totals["cost_usd"]


# A trace stays in the DB with status='running' even if the process dies; after
# this many minutes without an ended_at we surface it as "stale" instead.
STALE_AFTER_MINUTES = 5


def _mark_stale_running(trace: Dict[str, Any], *, stale_after_minutes: int = STALE_AFTER_MINUTES) -> None:
    if trace.get("status") != "running" or trace.get("ended_at"):
        return
    raw_created = trace.get("created_at")
    if not raw_created:
        return
    try:
        created_at = datetime.fromisoformat(str(raw_created).replace("Z", "+00:00"))
        now = datetime.now(created_at.tzinfo) if created_at.tzinfo else datetime.now()
        if now - created_at > timedelta(minutes=stale_after_minutes):
            trace["status"] = "stale"
    except Exception:
        return



# Open trace ids on the current call path, innermost last, so sub-agent runs record their parent.
_ACTIVE_TRACES: ContextVar[tuple] = ContextVar("agentos_active_traces", default=())
# trace_id -> monotonic start; a parent is inherited only while open and recent.
_OPEN_TRACES: Dict[str, float] = {}
# _OPEN_TRACES is process-wide and touched from request/worker threads; guard every
# read/write/cleanup so concurrent begin/end can't mutate it mid-iteration.
_OPEN_TRACES_LOCK = threading.Lock()
_PARENT_MAX_AGE_S = 30 * 60


class TraceEmitter:
    """
    Async-safe, fire-and-forget execution trace writer.

    All writes are enqueued instantly (non-blocking).  A single background
    asyncio task drains the queue in batches and writes to SQLite in WAL mode.

    The emitter is fully framework-agnostic: it accepts plain dicts conforming
    to the TraceSpan TypedDict protocol.  No imports from any agent framework.
    """

    def __init__(
        self,
        db_path: str,
        *,
        exporters: Optional[List[Callable]] = None,
        telemetry_providers: Optional[Any] = None,
    ):
        """
        Parameters
        ----------
        db_path : str
            Full path to the SQLite database file.
        exporters : list of callables, optional
            Each callable receives (event_type: str, payload: dict) for every
            trace/span event.  Use for forwarding to OpenTelemetry, Datadog, etc.
        telemetry_providers : TelemetryProviderFanout or provider list, optional
            Bounded provider fanout for enterprise telemetry adapters. Providers
            receive sanitized copies and never run on the SQLite writer path.
        """
        self._db_path = _validated_db_path(db_path)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100_000)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._exporters: List[Callable] = exporters or []
        self._telemetry_fanout = TelemetryProviderFanout.coerce(telemetry_providers)

        # Live span tally per in-flight trace, guarded by a lock (add_span runs on worker threads).
        self._live_span_counts: Dict[str, int] = {}
        self._live_span_lock = threading.Lock()

        # Backend seam. Default sqlite (per-instance file); postgres = shared, fleet-wide
        # store via the pooled engine. Independent flag; requires DB_BACKEND=postgres too.
        self._backend = _resolve_trace_backend()
        self._ph = "%s" if self._backend == "postgres" else "?"
        self._pg_schema = os.getenv("TRACE_PG_SCHEMA", "trace")  # override for isolated tests
        self._engine = None
        if self._backend == "postgres":
            from iaf_agent_skills.storage.engine import get_engine
            self._engine = get_engine()

        self._ensure_schema()


    def _tbl(self, name: str) -> str:
        """Schema-qualify a table on Postgres (explicit, not search_path-dependent)."""
        return f"{self._pg_schema}.{name}" if self._backend == "postgres" else name

    @property
    def _rowid(self) -> str:
        """Tie-break ordering column: SQLite has an implicit `rowid`; Postgres uses `id`."""
        return "id" if self._backend == "postgres" else "rowid"

    @contextmanager
    def _connect(self):
        """Yield a connection for one operation. SQLite: fresh row-factory conn (auto-commit
        on success). Postgres: a pooled engine connection (engine commits on clean exit)."""
        if self._backend == "postgres":
            with self._engine.connect() as conn:
                yield conn
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _cursor(self, conn):
        """Dict-row cursor on both backends so dict(row)/row["col"] work unchanged."""
        if self._backend == "postgres":
            from psycopg.rows import dict_row
            return conn.cursor(row_factory=dict_row)
        return conn.cursor()


    def _ensure_schema(self) -> None:
        """Create traces + spans tables if they don't exist.  WAL mode for concurrency."""
        if self._backend == "postgres":
            self._ensure_schema_postgres()
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = _sqlite_connect(self._db_path)
        try:

            conn.executescript(TRACE_SCHEMA_SQL)
            for col_def in _TRACE_MIGRATIONS:
                try:
                    conn.execute(col_def)
                except Exception:
                    pass  # Column already exists — safe to ignore
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema_postgres(self) -> None:
        """Create the shared `trace` schema + traces/spans tables on Postgres (idempotent)."""
        ddl = TRACE_SCHEMA_PG.format(schema=self._pg_schema)
        with self._connect() as conn:
            cur = conn.cursor()
            for stmt in (s.strip() for s in ddl.split(";")):
                if stmt:
                    cur.execute(stmt)
            conn.commit()
        print(f"🔍 Trace emitter: Postgres schema '{self._pg_schema}' ready")

    async def start(self) -> None:
        """Start the background writer.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._writer_loop())
        dest = f"Postgres schema '{self._pg_schema}'" if self._backend == "postgres" else self._db_path
        logger.debug(f"🔍 Trace emitter started → {dest}")

    async def stop(self) -> None:
        """Graceful shutdown — flush remaining events then stop."""
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
        logger.debug("🔍 Trace emitter stopped")


    def begin_trace(
        self,
        *,
        session_id: str = "",
        tenant: str = "default",
        agent: str = "default",
        user_id: str = "",
        skill: str = "",
        query: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        parent_trace_id: Optional[str] = None,
        orchestrator_step: Optional[int] = None,
    ) -> str:
        """
        Start a new trace.  Returns the generated trace_id.

        Parameters
        ----------
        session_id : str
            Links to the chat session.
        tenant, agent : str
            Multi-tenant identifiers.
        user_id : str
            Who initiated the request.
        skill : str
            Routed skill (may be updated later via end_trace).
        query : str
            User query (truncated to 8192 chars).
        metadata : dict, optional
            Arbitrary context (serialized to JSON).

        Returns
        -------
        str
            The generated trace_id (UUID hex).
        """
        trace_id = uuid.uuid4().hex
        active = _ACTIVE_TRACES.get()
        now_mono = time.monotonic()
        with _OPEN_TRACES_LOCK:
            if not parent_trace_id and active:
                started = _OPEN_TRACES.get(active[-1])
                if started is not None and now_mono - started < _PARENT_MAX_AGE_S:
                    parent_trace_id = active[-1]
            _OPEN_TRACES[trace_id] = now_mono
            if len(_OPEN_TRACES) > 10_000:  # runs that never ended: keep the registry bounded
                for stale in [t for t, ts in _OPEN_TRACES.items() if now_mono - ts > _PARENT_MAX_AGE_S]:
                    _OPEN_TRACES.pop(stale, None)
        _ACTIVE_TRACES.set(active + (trace_id,))
        now = datetime.now().isoformat()
        event = {
            "_table": "traces",
            "_op": "insert",
            "trace_id": trace_id,
            "session_id": session_id,
            "tenant": tenant,
            "agent": agent,
            "user_id": user_id,
            "skill": skill,
            "query_preview": (query or "")[:8192],
            "status": "running",
            "span_count": 0,
            "total_ms": 0,
            "created_at": now,
            "metadata": json.dumps(metadata) if metadata else None,
            "parent_trace_id": parent_trace_id,
            "orchestrator_step": orchestrator_step,
        }
        export = self._exporter_payload(event)
        with self._live_span_lock:
            self._live_span_counts[trace_id] = 0
        self._enqueue(event)
        self._notify_exporters("trace_begin", export)
        return trace_id

    def end_trace(
        self,
        *,
        trace_id: str,
        status: str = "success",
        skill: str = "",
        span_count: int = 0,
        total_ms: float = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Finalize a trace with outcome metrics.

        Parameters
        ----------
        trace_id : str
            The trace to finalize.
        status : str
            "success" | "error".
        skill : str
            Final routed skill (if changed during execution).
        span_count : int
            Total spans emitted for this trace.
        total_ms : float
            Total wall-clock time in milliseconds.
        metadata : dict, optional
            Additional context to merge.
        """
        with _OPEN_TRACES_LOCK:
            _OPEN_TRACES.pop(trace_id, None)
        active = _ACTIVE_TRACES.get()
        if trace_id in active:
            _ACTIVE_TRACES.set(tuple(t for t in active if t != trace_id))
        now = datetime.now().isoformat()
        # Fall back to the live span tally when no explicit count is passed.
        with self._live_span_lock:
            tracked = self._live_span_counts.pop(trace_id, 0)
        span_count = span_count or tracked
        event = {
            "_table": "traces",
            "_op": "update_end",
            "trace_id": trace_id,
            "status": status,
            "skill": skill,
            "span_count": span_count,
            "total_ms": total_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "ended_at": now,
            "metadata": json.dumps(metadata) if metadata else None,
        }
        export = self._exporter_payload(event)
        self._enqueue(event)
        self._notify_exporters("trace_end", export)


    def add_span(
        self,
        *,
        trace_id: str,
        span_type: str,
        name: str,
        start_ms: float,
        duration_ms: float = 0,
        status: str = "ok",
        input_preview: str = "",
        output_preview: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a single execution span within a trace.

        Parameters
        ----------
        trace_id : str
            Parent trace.
        span_type : str
            One of: route, knowledge, llm, tool, hitl, memory, response, custom.
        name : str
            Human-readable label (e.g., "gpt-4o call", "search_invoices").
        start_ms : float
            Epoch milliseconds when the span started.
        duration_ms : float
            Wall-clock duration in milliseconds.
        status : str
            "ok" | "error" | "skipped".
        input_preview, output_preview : str
            Truncated to 8192 chars each.
        metadata : dict, optional
            Arbitrary context (model name, token counts, tool params, etc.)
        """
        now = datetime.now().isoformat()
        event = {
            "_table": "spans",
            "_op": "insert",
            "trace_id": trace_id,
            "span_type": span_type,
            "name": name,
            "start_ms": start_ms,
            "duration_ms": duration_ms,
            "status": status,
            "input_preview": (input_preview or "")[:8192],
            "output_preview": (output_preview or "")[:8192],
            "metadata": json.dumps(metadata) if metadata else None,
            "created_at": now,
        }
        export = self._exporter_payload(event)
        with self._live_span_lock:
            # Tally only traces opened by begin_trace(); orphan spans must not create entries that leak.
            if trace_id in self._live_span_counts:
                self._live_span_counts[trace_id] += 1
        self._enqueue(event)
        self._notify_exporters("span", export)


    @staticmethod
    def now_ms() -> float:
        """Return current epoch time in milliseconds.  Use for span start_ms."""
        return time.time() * 1000


    def register_exporter(self, callback: Callable) -> None:
        """
        Register a callback that receives every trace/span event.

        The callback signature is: callback(event_type: str, payload: dict)
        where event_type is "trace_begin", "trace_end", or "span".

        Use this to bridge to OpenTelemetry, Datadog, Kafka, etc.
        """
        self._exporters.append(callback)

    def unregister_exporter(self, callback: Callable) -> None:
        """Remove a previously registered exporter."""
        try:
            self._exporters.remove(callback)
        except ValueError:
            pass


    def _trace_filter_conditions(
        self,
        *,
        tenant: str = "",
        agent: str = "",
        user_id: str = "",
        skill: str = "",
        status: str = "",
        session_id: str = "",
        since: str = "",
        fuzzy_user: bool = False,
        skills: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
    ) -> tuple[list, List[Any]]:
        """Build the shared WHERE predicates for trace queries. Used by BOTH
        ``query_traces`` and ``count_traces`` so the reported total describes the
        exact same scoped/filtered result set (Copilot #6). Returns
        ``(conditions, params)``.

        ``skill``/``user_id`` are the legacy single free-text substring filters.
        ``skills``/``users`` are the multi-select dropdown filters: exact,
        case-insensitive for skills, matched with ``IN (...)``. Multiple values
        within one list are ORed (IN); the two lists are ANDed with each other."""
        ph = self._ph
        conditions: list = []
        params: List[Any] = []

        if tenant:
            conditions.append(f"tenant = {ph}")
            params.append(tenant)
        if agent:
            conditions.append(f"agent = {ph}")
            params.append(agent)
        if user_id:
            # Non-admin reads pin user_id and must stay an exact match; only admin free-text filters use substring matching.
            if fuzzy_user:
                conditions.append(f"LOWER(user_id) LIKE {ph}")
                params.append(f"%{user_id.lower()}%")
            else:
                conditions.append(f"user_id = {ph}")
                params.append(user_id)
        if users:
            # Multi-select user dropdown (admin only — the router pins non-admins
            # to their own id and never forwards this list). Exact match, ORed.
            _uvals = [str(u) for u in users if u]
            if _uvals:
                _uph = ", ".join([ph] * len(_uvals))
                conditions.append(f"user_id IN ({_uph})")
                params.extend(_uvals)
        if skill:
            # Free-text "Skill…" box: match as a case-insensitive substring so a
            # partial or differently-cased term behaves as the operator expects.
            conditions.append(f"LOWER(skill) LIKE {ph}")
            params.append(f"%{skill.lower()}%")
        if skills:
            # Multi-select skill dropdown: exact, case-insensitive, ORed.
            _svals = [str(s).lower() for s in skills if s]
            if _svals:
                _sph = ", ".join([ph] * len(_svals))
                conditions.append(f"LOWER(skill) IN ({_sph})")
                params.extend(_svals)
        if status == "running":
            # Mirror _mark_stale_running so the Running filter excludes stale rows.
            cutoff = (datetime.now() - timedelta(minutes=STALE_AFTER_MINUTES)).isoformat()
            conditions.append(f"status = {ph}")
            params.append("running")
            conditions.append(f"(ended_at IS NOT NULL OR created_at >= {ph})")
            params.append(cutoff)
        elif status == "stale":
            # "stale" is derived, never stored: a still-'running' trace with no
            # ended_at that is older than the staleness window.
            cutoff = (datetime.now() - timedelta(minutes=STALE_AFTER_MINUTES)).isoformat()
            conditions.append(f"status = {ph}")
            params.append("running")
            conditions.append("ended_at IS NULL")
            conditions.append(f"created_at < {ph}")
            params.append(cutoff)
        elif status:
            conditions.append(f"status = {ph}")
            params.append(status)
        if session_id:
            conditions.append(f"session_id = {ph}")
            params.append(session_id)
        if since:
            conditions.append(f"created_at >= {ph}")
            params.append(since)
        return conditions, params

    def query_traces(
        self,
        *,
        tenant: str = "",
        agent: str = "",
        user_id: str = "",
        skill: str = "",
        status: str = "",
        session_id: str = "",
        since: str = "",
        limit: int = 200,
        offset: int = 0,
        fuzzy_user: bool = False,
        skills: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query traces with optional filters.  Returns list of dicts.

        Parameters
        ----------
        tenant, agent, user_id, skill, session_id : str
            Optional equality filters.
        skills, users : list[str]
            Multi-select dropdown filters (exact match, ORed within each list).
        since : str
            ISO timestamp — only traces created after this time.
        limit : int
            Max results (default 200).
        offset : int
            Pagination offset.
        """
        try:
            ph = self._ph
            conditions, params = self._trace_filter_conditions(
                tenant=tenant, agent=agent, user_id=user_id, skill=skill,
                status=status, session_id=session_id, since=since,
                fuzzy_user=fuzzy_user, skills=skills, users=users,
            )

            where_clause = _sql_where(conditions)
            sql = (
                "SELECT trace_id, session_id, tenant, agent, user_id, skill,"
                "       query_preview, status, span_count, total_ms,"
                "       prompt_tokens, completion_tokens, cost_usd,"
                "       created_at, ended_at, metadata"
                f" FROM {self._tbl('traces')}"
                " WHERE " + where_clause +
                " ORDER BY created_at DESC"
                f" LIMIT {ph} OFFSET {ph}"
            )
            params.extend([limit, offset])
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(sql, params)
                result = [dict(r) for r in cur.fetchall()]
                trace_ids = [row["trace_id"] for row in result if not _safe_int(row.get("prompt_tokens")) or not _safe_float(row.get("cost_usd"))]
                if trace_ids:
                    in_clause = _sql_in_clause(len(trace_ids), ph)
                    cur.execute(
                        "SELECT trace_id, metadata"
                        f" FROM {self._tbl('spans')}"
                        " WHERE trace_id IN " + in_clause + " AND metadata IS NOT NULL"
                        f" ORDER BY trace_id ASC, start_ms ASC, {self._rowid} ASC",
                        trace_ids,
                    )
                    spans_by_trace: Dict[str, List[Dict[str, Any]]] = {}
                    for span_row in cur.fetchall():
                        span = dict(span_row)
                        spans_by_trace.setdefault(span["trace_id"], []).append(span)
                    for trace in result:
                        spans = spans_by_trace.get(trace["trace_id"])
                        if spans:
                            _apply_token_fallback(trace, spans)
                        _mark_stale_running(trace)
            return result
        except Exception as e:
            logger.debug(f"🔍 Trace query error (non-fatal): {e}")
            return []

    def query_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        """
        Get all spans for a single trace, ordered by start_ms.

        Returns list of dicts with all span columns.
        """
        try:
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"""SELECT trace_id, span_type, name, start_ms, duration_ms,
                              status, input_preview, output_preview, metadata, created_at
                       FROM {self._tbl('spans')}
                       WHERE trace_id = {self._ph}
                       ORDER BY start_ms ASC, {self._rowid} ASC""",
                    [trace_id],
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.debug(f"🔍 Span query error (non-fatal): {e}")
            return []

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single trace by trace_id, including its spans.

        Returns dict with trace fields + "spans" list, or None.
        """
        try:
            ph = self._ph
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"""SELECT trace_id, session_id, tenant, agent, user_id, skill,
                              query_preview, status, span_count, total_ms,
                              prompt_tokens, completion_tokens, cost_usd,
                              created_at, ended_at, metadata
                       FROM {self._tbl('traces')} WHERE trace_id = {ph}""",
                    [trace_id],
                )
                row = cur.fetchone()
                if not row:
                    return None
                trace = dict(row)
                cur.execute(
                    f"""SELECT trace_id, span_type, name, start_ms, duration_ms,
                              status, input_preview, output_preview, metadata, created_at
                       FROM {self._tbl('spans')} WHERE trace_id = {ph}
                       ORDER BY start_ms ASC, {self._rowid} ASC""",
                    [trace_id],
                )
                trace["spans"] = [dict(s) for s in cur.fetchall()]
            _apply_token_fallback(trace, trace["spans"])
            _mark_stale_running(trace)
            return trace
        except Exception as e:
            logger.debug(f"🔍 Trace detail error (non-fatal): {e}")
            return None


    def purge_old_traces(self, days: int = 30) -> int:
        """
        Delete traces (and their spans) older than `days`.

        Returns the number of traces deleted.
        """
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            if self._backend == "postgres":
                ph = self._ph
                with self._connect() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        f"DELETE FROM {self._tbl('spans')} WHERE trace_id IN "
                        f"(SELECT trace_id FROM {self._tbl('traces')} WHERE created_at < {ph})",
                        [cutoff],
                    )
                    cur.execute(f"DELETE FROM {self._tbl('traces')} WHERE created_at < {ph}", [cutoff])
                    deleted = cur.rowcount
                    conn.commit()
                # Postgres reclaims via autovacuum — no explicit VACUUM (can't run in a txn).
                logger.debug(f"🔍 Purged {deleted} traces older than {days} days (pg)")
                return deleted
            conn = _sqlite_connect(self._db_path)
            # Delete spans first (FK)
            conn.execute(
                "DELETE FROM spans WHERE trace_id IN "
                "(SELECT trace_id FROM traces WHERE created_at < ?)",
                [cutoff],
            )
            cursor = conn.execute(
                "DELETE FROM traces WHERE created_at < ?", [cutoff]
            )
            deleted = cursor.rowcount
            conn.commit()
            # Reclaim disk space
            conn.execute("VACUUM")
            conn.close()
            logger.debug(f"🔍 Purged {deleted} traces older than {days} days")
            return deleted
        except Exception as e:
            logger.debug(f"🔍 Purge error (non-fatal): {e}")
            return 0

    def count_traces(
        self,
        *,
        tenant: str = "",
        agent: str = "",
        user_id: str = "",
        skill: str = "",
        status: str = "",
        session_id: str = "",
        since: str = "",
        fuzzy_user: bool = False,
        skills: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
    ) -> int:
        """Count traces under the SAME predicates as ``query_traces`` so the total
        describes the returned (scoped + filtered) result set — not the tenant-wide
        row count, which would leak a non-admin's tenant total and break pagination
        (Copilot #6)."""
        try:
            conditions, params = self._trace_filter_conditions(
                tenant=tenant, agent=agent, user_id=user_id, skill=skill,
                status=status, session_id=session_id, since=since,
                fuzzy_user=fuzzy_user, skills=skills, users=users,
            )
            where = _sql_where(conditions)
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(f"SELECT COUNT(*) AS n FROM {self._tbl('traces')} WHERE {where}", params)
                row = cur.fetchone()
                return int(row["n"]) if row else 0
        except Exception:
            return 0

    def distinct_facets(
        self,
        *,
        tenant: str = "",
        user_id: str = "",
        fuzzy_user: bool = False,
        limit: int = 500,
    ) -> Dict[str, List[str]]:
        """Distinct skills and user_ids for the Trace Explorer filter dropdowns.

        Scoped by the SAME tenant/identity predicates as ``query_traces`` (a
        non-admin is pinned to their own ``user_id``; an admin sees all), so the
        dropdowns never expose another user's activity. The skill/status filter
        selections are intentionally NOT applied — the dropdowns must list every
        option available within the caller's scope regardless of what is
        currently selected. Capped to keep the payload small.
        """
        try:
            conditions, params = self._trace_filter_conditions(
                tenant=tenant, user_id=user_id, fuzzy_user=fuzzy_user,
            )
            where = _sql_where(conditions)
            ph = self._ph
            tbl = self._tbl("traces")
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"SELECT DISTINCT skill FROM {tbl} WHERE {where}"
                    f" AND skill IS NOT NULL AND skill <> '' ORDER BY skill LIMIT {ph}",
                    [*params, limit],
                )
                skills = [r["skill"] for r in cur.fetchall() if r["skill"]]
                cur.execute(
                    f"SELECT DISTINCT user_id FROM {tbl} WHERE {where}"
                    f" AND user_id IS NOT NULL AND user_id <> '' ORDER BY user_id LIMIT {ph}",
                    [*params, limit],
                )
                users = [r["user_id"] for r in cur.fetchall() if r["user_id"]]
            return {"skills": skills, "users": users}
        except Exception as e:
            logger.debug(f"🔍 Trace facet query error (non-fatal): {e}")
            return {"skills": [], "users": []}


    def _enqueue(self, event: Dict) -> None:
        """Add event to queue.  Non-blocking, never raises."""
        try:
            self._queue.put_nowait(event)
        except Exception:
            pass  # Queue full or shutting down — silently drop

    @staticmethod
    def _exporter_payload(event: Dict) -> Dict:
        """Copy for providers: no writer bookkeeping keys, metadata as a dict.

        The writer pops keys from `event` on the event-loop thread while add_span may run
        on a worker thread, so providers must not share it. Metadata is parsed because the
        fanout bounds every string (default 512 chars) — a JSON string would be cut mid-way.
        """
        payload = {k: v for k, v in event.items() if k not in ("_table", "_op")}
        raw = payload.get("metadata")
        if isinstance(raw, str):
            try:
                payload["metadata"] = json.loads(raw)
            except (ValueError, TypeError):
                pass
        return payload

    def _notify_exporters(self, event_type: str, payload: Dict) -> None:
        """Forward event to all registered exporters.  Never raises."""
        try:
            self._telemetry_fanout.emit(event_type, payload, source="trace")
        except Exception:
            pass
        for exporter in self._exporters:
            try:
                exporter(event_type, payload)
            except Exception:
                pass

    def telemetry_diagnostics(self) -> Dict[str, Any]:
        """Return safe provider diagnostics for capability snapshots."""
        try:
            return self._telemetry_fanout.snapshot()
        except Exception:
            return {"mode": "unknown", "provider_count": 0, "providers": []}

    def _drain_queue(self) -> List[Dict]:
        """Pull all pending events from the queue."""
        batch: List[Dict] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch


    async def _writer_loop(self) -> None:
        """Background coroutine: wait for events, batch-write to SQLite."""
        while self._running:
            batch: List[Dict] = []
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                batch.append(first)
                batch.extend(self._drain_queue())
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                batch.extend(self._drain_queue())
                if batch:
                    self._flush(batch)
                return
            except Exception:
                continue

            if batch:
                self._flush(batch)

    def _flush(self, batch: List[Dict]) -> None:
        """Write a batch of events to SQLite.  Never raises."""
        if self._backend == "postgres":
            self._flush_postgres(batch)
            return
        try:
            conn = _sqlite_connect(self._db_path)

            cursor = conn.cursor()
            for event in batch:
                table = event.pop("_table", "spans")
                op = event.pop("_op", "insert")
                if table not in _VALID_TRACE_TABLES:
                    logger.debug("Trace flush: rejecting unknown table %r", table)
                    continue
                validated_table = table
                try:
                    if op == "insert":
                        safe_cols = [c for c in event.keys() if _SAFE_COL_RE.match(c)]
                        if len(safe_cols) != len(event):
                            logger.debug("Trace flush: rejecting event with unsafe column names")
                            continue
                        cols = ", ".join(safe_cols)
                        placeholders = ", ".join(["?"] * len(safe_cols))
                        cursor.execute(
                            "INSERT INTO " + validated_table + " (" + cols + ") VALUES (" + placeholders + ")",
                            [event[c] for c in safe_cols],
                        )
                    elif op == "update_end":
                        trace_id = event.pop("trace_id")
                        set_parts = []
                        vals = []
                        for k, v in event.items():
                            if v is not None and v != "" and _SAFE_COL_RE.match(k):
                                set_parts.append(k + " = ?")
                                vals.append(v)
                        if set_parts:
                            vals.append(trace_id)
                            set_clause = _sql_set_clause(set_parts)
                            cursor.execute(
                                "UPDATE " + validated_table + " SET " + set_clause + " WHERE trace_id = ?",
                                vals,
                            )
                except sqlite3.IntegrityError:
                    pass  # Duplicate trace_id — safe to skip
                except Exception as e:
                    logger.debug(f"🔍 Trace emit row error (non-fatal): {e}")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"🔍 Trace emit flush error (non-fatal): {e}")

    def _flush_postgres(self, batch: List[Dict]) -> None:
        """Write a batch to Postgres. Per-row SAVEPOINT so one bad row can't abort the batch
        (a PG error aborts the whole transaction otherwise); the traces insert uses
        ON CONFLICT (trace_id) DO NOTHING (dup-safe). Never raises."""
        ph = self._ph
        try:
            with self._connect() as conn:
                cur = conn.cursor()
                for event in batch:
                    table = event.pop("_table", "spans")
                    op = event.pop("_op", "insert")
                    # Allowlist the table and validate column names against _SAFE_COL_RE to prevent SQL injection.
                    if table not in _VALID_TRACE_TABLES:
                        logger.debug("Trace flush (pg): rejecting unknown table %r", table)
                        continue
                    try:
                        cur.execute("SAVEPOINT sp")
                        if op == "insert":
                            safe_cols = [c for c in event.keys() if _SAFE_COL_RE.match(c)]
                            if len(safe_cols) != len(event):
                                logger.debug("Trace flush (pg): rejecting event with unsafe column names")
                                cur.execute("RELEASE SAVEPOINT sp")
                                continue
                            cols = ", ".join(safe_cols)
                            placeholders = ", ".join([ph] * len(safe_cols))
                            conflict = " ON CONFLICT (trace_id) DO NOTHING" if table == "traces" else ""
                            cur.execute(
                                f"INSERT INTO {self._tbl(table)} ({cols}) VALUES ({placeholders}){conflict}",
                                [event[c] for c in safe_cols],
                            )
                        elif op == "update_end":
                            trace_id = event.pop("trace_id")
                            set_parts, vals = [], []
                            for k, v in event.items():
                                if v is not None and v != "" and _SAFE_COL_RE.match(k):
                                    set_parts.append(f"{k} = {ph}")
                                    vals.append(v)
                            if set_parts:
                                vals.append(trace_id)
                                cur.execute(
                                    f"UPDATE {self._tbl(table)} SET {', '.join(set_parts)} WHERE trace_id = {ph}",
                                    vals,
                                )
                        cur.execute("RELEASE SAVEPOINT sp")
                    except Exception as e:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT sp")
                        except Exception:
                            pass
                        logger.debug(f"🔍 Trace emit row error (non-fatal, pg): {e}")
                conn.commit()
        except Exception as e:
            logger.debug(f"🔍 Trace emit flush error (non-fatal, pg): {e}")



_emitter: Optional[TraceEmitter] = None


def get_trace_emitter(
    data_root: str = "",
    tenant: str = "company",
    *,
    db_path: str = "",
    exporters: Optional[List[Callable]] = None,
    telemetry_providers: Optional[Any] = None,
) -> TraceEmitter:
    """
    Get (or create) the singleton TraceEmitter.

    Parameters
    ----------
    data_root : str
        Path to enterprise_root.  Used to derive db_path if not given.
    tenant : str
        Tenant directory name.  Default: "company".
    db_path : str
        Explicit full path to traces.db.  Overrides data_root/tenant derivation.
    exporters : list of callables, optional
        Forwarding callbacks for external observability systems.
    telemetry_providers : TelemetryProviderFanout or provider list, optional
        Enterprise telemetry provider fanout.

    Returns
    -------
    TraceEmitter
    """
    global _emitter
    if _emitter is None:
        if db_path:
            resolved = db_path
        else:
            # TRACE_DB_PATH pins traces.db to local disk; NFS/EFS lock/WAL fragility.
            import os as _os
            _override = _os.getenv("TRACE_DB_PATH", "").strip()
            if _override:
                resolved = _override
            else:
                resolved = str(
                    Path(data_root)
                    / "tenants"
                    / tenant
                    / "shared"
                    / "databases"
                    / DB_NAME
                )
        _emitter = TraceEmitter(resolved, exporters=exporters, telemetry_providers=telemetry_providers)
    return _emitter


def reset_trace_emitter() -> None:
    """Reset singleton — used in tests."""
    global _emitter
    _emitter = None
