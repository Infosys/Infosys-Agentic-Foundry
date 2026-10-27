"""
ConversationManager — metadata index for conversation sessions.

Maintains a lightweight index of all conversation sessions so the UI sidebar
can list, search, load, delete, and rename conversations without scanning
JSONL files on every request.

Backend-agnostic (mirrors KnowledgeIndexer): SQLite by default; Postgres when
KNOWLEDGE_BACKEND=postgres, where the `conversation_sessions` table lives in the
same per-agent schema (`kn_<tenant>_<agent>`) as the knowledge index. This lets the
whole `enterprise_root` file tree move to shared storage without a live SQLite writer
sitting on the network mount.

Usage (called from AgentMemory.log_episode):
    mgr = ConversationManager(db_path=memory_root / "knowledge_index.db")
    mgr.upsert_session(session_id=..., tenant_id=..., ...)

Usage (called from conversations.py router):
    sessions = mgr.list_sessions(tenant_id, agent_id, user_id, limit=20)
    turns = mgr.load_session_turns(session_id, history_root)
"""

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
try:
    from .sqlite_util import connect as _sqlite_connect
except ImportError:
    from sqlite_util import connect as _sqlite_connect
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DDL_LOCK = threading.Lock()


class ConversationManager:
    """
    Metadata index for conversation sessions.

    Schema: conversation_sessions table with composite index on
    (tenant_id, agent_id, user_id, last_active_at DESC) for fast sidebar queries.

    SQLite: WAL mode + check_same_thread=False. Postgres: scoped pooled connections
    with SET LOCAL search_path to the per-agent schema.
    """

    def __init__(self, db_path: Path):
        """
        Args:
            db_path: Path to the knowledge_index.db file. On SQLite the table lives in
                     that file; on Postgres it lives in the derived per-agent schema
                     (the file path is used only to derive the schema name, matching
                     KnowledgeIndexer).
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[sqlite3.Connection] = None

        try:
            from .knowledge_indexer import _resolve_knowledge_backend
        except ImportError:
            from knowledge_indexer import _resolve_knowledge_backend
        self._kbackend = _resolve_knowledge_backend()
        self._ph = "%s" if self._kbackend == "postgres" else "?"
        self._hot_days = int(os.getenv("TRANSCRIPT_HOT_DAYS", "0") or "0")
        self._engine = None
        self._pg_schema = None
        if self._kbackend == "postgres":
            try:
                from .storage.engine import get_engine
            except ImportError:
                from storage.engine import get_engine
            self._engine = get_engine()
            self._pg_schema = self._derive_pg_schema()

        self._ensure_table()

    def _derive_pg_schema(self) -> str:
        """Per-agent Postgres schema `kn_<tenant>_<agent>` derived from db_path — identical
        to KnowledgeIndexer so the conversation table co-locates with the knowledge index.
        Overridable via KNOWLEDGE_PG_SCHEMA."""
        import re
        override = os.getenv("KNOWLEDGE_PG_SCHEMA")
        if override:
            raw = override
        else:
            try:
                agent = self.db_path.parent.parent.name           # memory → <agent>
                tenant = self.db_path.parent.parent.parent.parent.name  # → <tenant>
                raw = f"kn_{tenant}_{agent}"
            except Exception:
                raw = "kn_default"
        return re.sub(r"[^a-zA-Z0-9_]", "_", raw).lower()[:63]

    @contextmanager
    def _connect(self):
        """Yield a connection for one logical operation.
        SQLite: a persistent WAL connection (byte-identical to the legacy `db` property).
        Postgres: a scoped pooled connection with search_path set to the agent schema."""
        if self._kbackend == "postgres":
            with self._engine.connect() as conn:
                conn.cursor().execute(f'SET LOCAL search_path TO "{self._pg_schema}"')
                yield conn
        else:
            if self._db is None:
                self._db = _sqlite_connect(
                    self.db_path,
                    check_same_thread=False,
                    row_factory=sqlite3.Row,
                )
            yield self._db

    def _cursor(self, conn):
        """Cursor that returns dict-like rows on BOTH backends, so callers can use
        row["col"] / dict(row) unchanged (SQLite via row_factory=Row; Postgres via dict_row)."""
        if self._kbackend == "postgres":
            from psycopg.rows import dict_row
            return conn.cursor(row_factory=dict_row)
        return conn.cursor()

    @property
    def db(self) -> sqlite3.Connection:
        """Lazy DB connection with WAL mode (SQLite shortcut for backward compatibility)."""
        if self._db is None:
            self._db = _sqlite_connect(
                self.db_path,
                check_same_thread=False,
                row_factory=sqlite3.Row,
            )
        return self._db

    def _ensure_table(self):
        """Create the conversation_sessions table + indexes if they don't exist.

        Serialized process-wide via _DDL_LOCK so concurrent agent construction
        never issues DDL against the shared knowledge_index.db simultaneously.
        A bounded retry covers the rarer case where the KnowledgeIndexer holds
        the write lock longer than busy_timeout during a first-access burst; the
        DDL is idempotent so retrying is safe.
        """
        last_exc: Optional[sqlite3.OperationalError] = None
        with _DDL_LOCK:
            for attempt in range(4):
                try:
                    self._ensure_table_once()
                    return
                except sqlite3.OperationalError as exc:
                    if "database is locked" not in str(exc).lower():
                        raise
                    last_exc = exc
                    logger.warning(
                        "conversation_manager: _ensure_table locked (attempt %d/4), retrying",
                        attempt + 1,
                    )
                    time.sleep(0.25 * (attempt + 1))
        if last_exc is not None:
            raise last_exc

    def _ensure_table_once(self):
        """Single DDL pass — see _ensure_table for concurrency handling."""
        with self._connect() as conn:
            if self._kbackend == "postgres":
                sch = self._pg_schema
                cur = conn.cursor()
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{sch}"')
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS "{sch}".conversation_sessions (
                        session_id        TEXT PRIMARY KEY,
                        tenant_id         TEXT NOT NULL,
                        agent_id          TEXT NOT NULL,
                        user_id           TEXT NOT NULL,
                        parent_session_id TEXT,
                        title             TEXT NOT NULL DEFAULT '',
                        first_message     TEXT NOT NULL DEFAULT '',
                        created_at        DOUBLE PRECISION NOT NULL,
                        last_active_at    DOUBLE PRECISION NOT NULL,
                        turn_count        INTEGER NOT NULL DEFAULT 0,
                        skills_used       TEXT NOT NULL DEFAULT '[]',
                        status            TEXT NOT NULL DEFAULT 'active',
                        jsonl_path        TEXT
                    )
                """)
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conv_sessions_user_active '
                            f'ON "{sch}".conversation_sessions (tenant_id, agent_id, user_id, last_active_at DESC)')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conv_sessions_status '
                            f'ON "{sch}".conversation_sessions (status)')
                # Full turn bodies (transcript tiering): durable copy of each history JSONL line,
                # so cold JSONL files can be pruned and load_session_turns falls back here.
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS "{sch}".conversation_turns (
                        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        session_id  TEXT NOT NULL,
                        tenant_id   TEXT NOT NULL,
                        agent_id    TEXT NOT NULL,
                        user_id     TEXT,
                        skill       TEXT,
                        ts          TEXT,
                        turn_json   TEXT NOT NULL,
                        created_at  DOUBLE PRECISION NOT NULL
                    )
                """)
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_conv_turns_session '
                            f'ON "{sch}".conversation_turns (session_id, id)')
            else:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS conversation_sessions (
                        session_id       TEXT PRIMARY KEY,
                        tenant_id        TEXT NOT NULL,
                        agent_id         TEXT NOT NULL,
                        user_id          TEXT NOT NULL,
                        parent_session_id TEXT,
                        title            TEXT NOT NULL DEFAULT '',
                        first_message    TEXT NOT NULL DEFAULT '',
                        created_at       REAL NOT NULL,
                        last_active_at   REAL NOT NULL,
                        turn_count       INTEGER NOT NULL DEFAULT 0,
                        skills_used      TEXT NOT NULL DEFAULT '[]',
                        status           TEXT NOT NULL DEFAULT 'active',
                        jsonl_path       TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_conv_sessions_user_active
                        ON conversation_sessions (tenant_id, agent_id, user_id, last_active_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_conv_sessions_status
                        ON conversation_sessions (status);

                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT NOT NULL,
                        tenant_id   TEXT NOT NULL,
                        agent_id    TEXT NOT NULL,
                        user_id     TEXT,
                        skill       TEXT,
                        ts          TEXT,
                        turn_json   TEXT NOT NULL,
                        created_at  REAL NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_conv_turns_session
                        ON conversation_turns (session_id, id);
                """)
            conn.commit()


    def upsert_session(
        self,
        session_id: str,
        tenant_id: str,
        agent_id: str,
        user_id: str,
        title: str,
        first_message: str,
        skill: str,
        parent_session_id: Optional[str] = None,
        jsonl_path: Optional[str] = None,
    ) -> None:
        """
        Insert a new session or update an existing one (increment turn_count, update skills).
        Called once per turn from log_episode().
        """
        now = time.time()
        ph = self._ph
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT session_id, skills_used FROM conversation_sessions WHERE session_id = {ph}",
                (session_id,),
            )
            row = cur.fetchone()

            if row is None:
                # First turn — create the session
                cur.execute(
                    f"""INSERT INTO conversation_sessions
                       (session_id, tenant_id, agent_id, user_id, parent_session_id,
                        title, first_message, created_at, last_active_at,
                        turn_count, skills_used, status, jsonl_path)
                       VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 1, {ph}, 'active', {ph})""",
                    (
                        session_id, tenant_id, agent_id, user_id, parent_session_id,
                        title[:80] if title else "",
                        first_message or "",
                        now, now,
                        json.dumps([skill]) if skill else "[]",
                        jsonl_path,
                    ),
                )
            else:
                # Subsequent turn — increment count, merge skills, update timestamp
                existing_skills = json.loads(row["skills_used"]) if row["skills_used"] else []
                if skill and skill not in existing_skills:
                    existing_skills.append(skill)
                cur.execute(
                    f"""UPDATE conversation_sessions
                       SET last_active_at = {ph}, turn_count = turn_count + 1,
                           skills_used = {ph}, status = 'active'
                       WHERE session_id = {ph}""",
                    (now, json.dumps(existing_skills), session_id),
                )

            conn.commit()


    def list_sessions(
        self,
        tenant_id: str,
        agent_id: str,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict]:
        """Return recent sessions for the sidebar, newest first."""
        ph = self._ph
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"""SELECT session_id, title, first_message, created_at,
                          last_active_at, turn_count, skills_used, status,
                          parent_session_id
                   FROM conversation_sessions
                   WHERE tenant_id = {ph} AND agent_id = {ph} AND user_id = {ph}
                     AND status != 'deleted'
                   ORDER BY last_active_at DESC
                   LIMIT {ph} OFFSET {ph}""",
                (tenant_id, agent_id, user_id, limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]


    def get_session(self, session_id: str) -> Optional[Dict]:
        """Return metadata for a single session, or None if not found."""
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT * FROM conversation_sessions WHERE session_id = {self._ph}",
                (session_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


    def load_session_turns(
        self,
        session_id: str,
        history_root: Path,
    ) -> List[Dict]:
        """
        Find and parse the JSONL turns for a given session_id.

        Scans ALL history_root/{date}/ directories for {session_id}.jsonl and
        merges them. A conversation that spans midnight is split across two date
        folders (the JSONL save path is keyed by the current date), so reading
        only one folder would silently drop the rest of the turns.

        Files are read oldest-date-first; within a file the append-only order is
        already chronological, so the concatenation is chronological too.
        Skips corrupted lines gracefully.

        When no JSONL files are found on disk (cold session: pruned by transcript
        tiering or living on another node's disk), falls back to the durable turn
        store (Postgres/SQLite conversation_turns).

        Returns list of turn dicts (user_input, response, skill, timestamp, etc.)
        """
        # Collect every matching JSONL across date directories (chronological).
        history_root = Path(history_root)
        jsonl_files = []

        if history_root.exists():
            for date_dir in sorted(history_root.iterdir()):
                if date_dir.is_dir():
                    candidate = date_dir / f"{session_id}.jsonl"
                    if candidate.exists():
                        jsonl_files.append(candidate)

        if not jsonl_files:
            # Cold session: the JSONL was pruned (tiering) or lives on another node's disk.
            # Fall back to the durable turn store (Postgres/SQLite conversation_turns).
            return self._load_turns_from_store(session_id)

        turns = []
        for jsonl_file in jsonl_files:
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            turns.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(
                                "Skipping corrupt line %d in %s", line_num, jsonl_file
                            )
            except Exception as e:
                logger.error("Failed to read JSONL %s: %s", jsonl_file, e)

        return turns


    def append_turn(self, session_id: str, entry: Dict, tenant_id: str, agent_id: str) -> None:
        """Persist one turn (the exact history JSONL line) to conversation_turns so cold JSONL
        files can be pruned and load_session_turns can fall back here. No-op unless tiering is on
        (TRANSCRIPT_HOT_DAYS>0). Non-fatal — never disrupts the turn."""
        if self._hot_days <= 0:
            return
        ph = self._ph
        try:
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"""INSERT INTO conversation_turns
                        (session_id, tenant_id, agent_id, user_id, skill, ts, turn_json, created_at)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                    (session_id, tenant_id, agent_id,
                     entry.get("user_id", ""), entry.get("skill", ""), entry.get("timestamp", ""),
                     json.dumps(entry), time.time()),
                )
                conn.commit()
        except Exception as e:
            logger.warning("append_turn failed (non-fatal): %s", e)

    def _load_turns_from_store(self, session_id: str) -> List[Dict]:
        """Load a session's turns from conversation_turns (insertion order), or [] if none."""
        try:
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"SELECT turn_json FROM conversation_turns WHERE session_id = {self._ph} ORDER BY id ASC",
                    (session_id,),
                )
                rows = cur.fetchall()
            out: List[Dict] = []
            for r in rows:
                try:
                    out.append(json.loads(r["turn_json"]))
                except Exception:
                    continue
            return out
        except Exception as e:
            logger.warning("load turns from store failed (non-fatal): %s", e)
            return []

    def _store_has_turns(self, session_id: str) -> bool:
        try:
            with self._connect() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"SELECT 1 FROM conversation_turns WHERE session_id = {self._ph} LIMIT 1",
                    (session_id,),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def tier_cold_files(self, history_root: Path) -> int:
        """Delete history JSONL files older than TRANSCRIPT_HOT_DAYS whose turns are safely in the
        store (so the UI still loads them via the fallback). Recent files stay for grep. Returns
        the number of files pruned. No-op unless tiering is on."""
        if self._hot_days <= 0:
            return 0
        history_root = Path(history_root)
        if not history_root.exists():
            return 0
        cutoff = time.time() - self._hot_days * 86400
        pruned = 0
        for date_dir in history_root.iterdir():
            if not date_dir.is_dir():
                continue
            for jf in date_dir.glob("*.jsonl"):
                try:
                    if jf.stat().st_mtime >= cutoff:
                        continue  # still hot — keep for grep
                    if self._store_has_turns(jf.stem):   # safety: only prune if archived
                        jf.unlink()
                        pruned += 1
                except Exception:
                    continue
        if pruned:
            logger.info("tier_cold_files: pruned %d cold transcript file(s) older than %d days",
                        pruned, self._hot_days)
        return pruned


    def delete_session(self, session_id: str) -> bool:
        """Soft-delete a session (sets status='deleted'). Returns True if a row changed."""
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"UPDATE conversation_sessions SET status = 'deleted' WHERE session_id = {self._ph} AND status != 'deleted'",
                (session_id,),
            )
            changed = cur.rowcount > 0
            conn.commit()
            return changed


    def rename_session(self, session_id: str, title: str) -> bool:
        """Rename a session's title. Returns True if updated."""
        if not title or not title.strip():
            return False

        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"UPDATE conversation_sessions SET title = {self._ph} WHERE session_id = {self._ph}",
                (title.strip()[:80], session_id),
            )
            changed = cur.rowcount > 0
            conn.commit()
            return changed


    def backfill_from_disk(
        self,
        history_root: Path,
        tenant_id: str,
        agent_id: str,
        user_id: str,
    ) -> int:
        """
        Scan existing JSONL files and populate the conversation_sessions table.
        Reads the first/last line of each JSONL to extract title + metadata.
        Returns the number of sessions indexed.
        """
        history_root = Path(history_root)
        count = 0

        if not history_root.exists():
            return 0

        ph = self._ph
        with self._connect() as conn:
            cur = self._cursor(conn)
            for date_dir in sorted(history_root.iterdir()):
                if not date_dir.is_dir():
                    continue
                for jsonl_file in date_dir.glob("*.jsonl"):
                    session_id = jsonl_file.stem
                    # Skip if already indexed
                    cur.execute(
                        f"SELECT 1 FROM conversation_sessions WHERE session_id = {ph}",
                        (session_id,),
                    )
                    if cur.fetchone():
                        continue

                    first_turn = None
                    last_turn = None
                    line_count = 0
                    skills = set()

                    try:
                        with open(jsonl_file, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    turn = json.loads(line)
                                    if first_turn is None:
                                        first_turn = turn
                                    last_turn = turn
                                    line_count += 1
                                    if turn.get("skill"):
                                        skills.add(turn["skill"])
                                except json.JSONDecodeError:
                                    continue
                    except Exception as e:
                        logger.warning("Could not read %s for backfill: %s", jsonl_file, e)
                        continue

                    if not first_turn:
                        continue

                    first_msg = first_turn.get("user_input", "")
                    title = first_msg[:80] if first_msg else session_id

                    from datetime import datetime as _dt
                    try:
                        created = _dt.fromisoformat(first_turn.get("timestamp", "")).timestamp()
                    except (ValueError, TypeError):
                        created = jsonl_file.stat().st_ctime
                    try:
                        last_active = _dt.fromisoformat(last_turn.get("timestamp", "")).timestamp()
                    except (ValueError, TypeError):
                        last_active = jsonl_file.stat().st_mtime

                    conflict = "ON CONFLICT (session_id) DO NOTHING" if self._kbackend == "postgres" else ""
                    insert_prefix = "INSERT INTO" if self._kbackend == "postgres" else "INSERT OR IGNORE INTO"
                    cur.execute(
                        f"""{insert_prefix} conversation_sessions
                           (session_id, tenant_id, agent_id, user_id, parent_session_id,
                            title, first_message, created_at, last_active_at,
                            turn_count, skills_used, status, jsonl_path)
                           VALUES ({ph}, {ph}, {ph}, {ph}, NULL, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'inactive', {ph})
                           {conflict}""",
                        (
                            session_id, tenant_id, agent_id, user_id,
                            title, first_msg,
                            created, last_active,
                            line_count, json.dumps(sorted(skills)),
                            str(jsonl_file),
                        ),
                    )
                    count += 1

            conn.commit()
        logger.info("Backfilled %d sessions from %s", count, history_root)
        return count


    def close(self):
        """Close the SQLite connection (no-op on Postgres — pooled/scoped)."""
        if self._db is not None:
            self._db.close()
            self._db = None
