#!/usr/bin/env python3
"""
KnowledgeIndexer — SQLite-backed semantic index for knowledge and episode files.

Provides:
  1. Semantic search via embeddings (Azure OpenAI / local fallback)
  2. FTS5 keyword search as graceful fallback when embeddings unavailable
  3. Entity cross-reference for fast entity → record lookups
  4. File-path pointers so callers can grep the exact JSONL line
"""
import logging

logger = logging.getLogger(__name__)

"""

Design Principles:
  - Separate from AgentMemory to keep concerns clean
  - Accepts embedding function as injectable dependency (testable)
  - Degrades gracefully: embeddings → FTS5 → empty results
  - Thread-safe SQLite (WAL mode, check_same_thread=False)
  - Idempotent: upsert semantics, safe to call repeatedly

Usage:
    from iaf_agent_skills.knowledge_indexer import KnowledgeIndexer

    indexer = KnowledgeIndexer(
        db_path=Path("memory/knowledge_index.db"),
        get_embedding_fn=my_embedding_function,  # or None for FTS5-only
    )

    # Index a knowledge record
    indexer.upsert_knowledge(record_dict)

    # Semantic search
    results = indexer.search_similar("payment processing rules", top_k=5)

    # Entity lookup
    results = indexer.entity_lookup("vendor_master")

    # Rebuild from scratch
    indexer.reindex_all(Path("memory/context_graph/knowledge.jsonl"))
"""

import json
import hashlib
import os
import re
import sqlite3
import struct
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable, Set

# Knowledge record IDs must contain only word chars, hyphens, and dots.
_SAFE_RECORD_ID_RE = re.compile(r'^[\w][\w\-\.]{0,255}$')



_VALID_KI_TABLES = frozenset({
    "knowledge_vectors", "episode_vectors", "entity_xref", "plan_cache",
})

_EPISODE_MIGRATIONS = (
    "ALTER TABLE episode_vectors ADD COLUMN session_id TEXT",
    "ALTER TABLE episode_vectors ADD COLUMN user_input TEXT",
    "ALTER TABLE episode_vectors ADD COLUMN trace_id TEXT",
    "ALTER TABLE episode_vectors ADD COLUMN entities TEXT",
    "ALTER TABLE episode_vectors ADD COLUMN reasoning TEXT",
)

_KNOWLEDGE_MIGRATIONS = (
    "ALTER TABLE knowledge_vectors ADD COLUMN source TEXT",
    "ALTER TABLE knowledge_vectors ADD COLUMN applies_when TEXT",
    "ALTER TABLE knowledge_vectors ADD COLUMN raw_json TEXT",
    "ALTER TABLE knowledge_vectors ADD COLUMN written_to TEXT",
)


def _sql_in_clause(count: int, ph: str = "?") -> str:
    """Build a parameterized IN clause with the given number of placeholders.

    ``ph`` is the backend placeholder token ('?' SQLite / '%s' Postgres).
    """
    if count <= 0:
        return "(NULL)"
    return "(" + ", ".join(ph for _ in range(count)) + ")"


def _sql_where(conditions: list) -> str:
    """Build a WHERE clause from validated condition strings."""
    if not conditions:
        return ""
    return "WHERE " + " AND ".join(conditions)


def _sql_set_clause(columns: list) -> str:
    """Build a SET clause from validated column=? fragments."""
    if not columns:
        raise ValueError("No columns to update")
    return ", ".join(columns)


def _validated_ki_table(name: str) -> str:
    """Validate table name against allowlist."""
    if name not in _VALID_KI_TABLES:
        raise ValueError("Invalid table name: %s" % name)
    return name


def _resolve_knowledge_backend() -> str:
    """Backend for the knowledge index — its OWN flag, independent of the global
    DB_BACKEND (which the Command Center queue already uses for Postgres). Defaults
    to 'sqlite' so the knowledge index stays on SQLite until its migration is
    complete and KNOWLEDGE_BACKEND=postgres is explicitly set. This prevents the
    live server (DB_BACKEND=postgres) from routing knowledge to a not-yet-built PG
    schema on restart."""
    raw = (os.getenv("KNOWLEDGE_BACKEND", "sqlite") or "sqlite").strip().lower()
    return "postgres" if raw == "postgres" else "sqlite"


# VectorBackend — pluggable similarity search (brute_force | sqlite_vec | pgvector)
try:
    from .vector_backend import VectorBackend, BruteForceBackend
except ImportError:
    from vector_backend import VectorBackend, BruteForceBackend


class KnowledgeIndexer:
    """
    SQLite-backed semantic index for knowledge records and episodes.

    Tables:
      - knowledge_vectors: id, summary, embedding, metadata, source file path
      - episode_vectors:   id, summary, embedding, file path (Phase 5d)
      - entity_xref:       entity → record_id cross-reference
      - fts_knowledge:     FTS5 virtual table for keyword fallback
    """

    # Embedding dimension for text-embedding-3-small = 1536
    # But we don't hardcode — we infer from first embedding
    COSINE_MIN_SCORE = 0.72  # ada-002 baseline noise is ~0.65-0.70; below 0.72 = noise

    def __init__(
        self,
        db_path: Path,
        get_embedding_fn: Optional[Callable[[str], List[float]]] = None,
        vector_backend: Optional[VectorBackend] = None,
    ):
        """
        Args:
            db_path: Path to SQLite database file (created if missing).
            get_embedding_fn: Callable that takes text → List[float].
                              If None, only FTS5 keyword search is available.
            vector_backend: Pluggable VectorBackend for similarity search.
                            If None, a BruteForceBackend is created automatically
                            (same behavior as before — zero breaking change).
                            Set VECTOR_BACKEND env var to switch backends.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._get_embedding = get_embedding_fn
        # Backend seam (Phase 1). Independent of the global DB_BACKEND — see
        # _resolve_knowledge_backend(). Defaults to sqlite → legacy behavior unchanged.
        self._kbackend = _resolve_knowledge_backend()
        self._engine = None
        self._pg_schema = None
        if self._kbackend == "postgres":
            try:
                from .storage.engine import get_engine
            except ImportError:
                from storage.engine import get_engine
            self._engine = get_engine()  # Postgres: shared pooled engine (DSN from env)
            self._pg_schema = self._derive_pg_schema()
        # Param placeholder for the active backend: '?' (sqlite) / '%s' (psycopg).
        self._ph = "%s" if self._kbackend == "postgres" else "?"
        self._db: Optional[sqlite3.Connection] = None
        self._init_db()

        # Initialize vector backend (pluggable: brute_force, sqlite_vec, pgvector)
        if vector_backend is not None:
            self._vector_backend = vector_backend
        elif self._kbackend == "postgres":
            # Postgres: hydrate embeddings via the scoped engine connection (self._db is None)
            self._vector_backend = BruteForceBackend(scoped_connect=self._scoped_connect)
        else:
            # Default: BruteForceBackend with SQLite DB hydration (backward compatible)
            self._vector_backend = BruteForceBackend(db_connection=self._db)
        logger.info("KnowledgeIndexer: vector_backend=%s", type(self._vector_backend).__name__)

        # Entity ontology registry (shares DB connection, zero new files)
        try:
            from .entity_registry import EntityRegistryStore
        except ImportError:
            from entity_registry import EntityRegistryStore
        # Config path: enterprise_root/tenants/company/shared/entity_validation.yaml
        config_path = self.db_path.parent.parent.parent.parent / "shared" / "entity_validation.yaml"
        self.entity_registry = EntityRegistryStore(
            db=self._db,
            get_embedding_fn=self._get_embedding,
            config_path=config_path,
            scoped_connect=self._scoped_connect,
            ph=self._ph,
            backend=self._kbackend,
        )

    def connect(self):
        """Public alias for the scoped-connection seam (SQLite persistent conn / PG scoped)."""
        return self._scoped_connect()

    @property
    def placeholder(self) -> str:
        """SQL param placeholder for the active backend: '?' (sqlite) / '%s' (postgres)."""
        return self._ph

    @property
    def backend(self) -> str:
        """Active knowledge backend: 'sqlite' | 'postgres'."""
        return self._kbackend

    @contextmanager
    def _scoped_connect(self):
        """Yield a DB connection for one logical operation.

        SQLite (default): yields the persistent ``self._db`` and does NOT close it —
        byte-identical to legacy behavior; the connection stays shared with
        EntityRegistryStore/vector backend. Postgres: yields a scoped/pooled engine
        connection (committed/closed by the engine's context manager).

        Composite writes (upsert_knowledge/upsert_episode/…) MUST open ONE
        _scoped_connect() and thread `conn` into sub-operations so the whole write is
        one transaction on Postgres (on SQLite they already share self._db).
        """
        if self._kbackend == "postgres" and self._engine is not None:
            with self._engine.connect() as conn:
                # transaction-scoped: a pooled connection never leaks a stale search_path
                conn.cursor().execute(f'SET LOCAL search_path TO "{self._pg_schema}"')
                yield conn
        else:
            yield self._db

    def _derive_pg_schema(self) -> str:
        """Per-agent Postgres schema name derived from the db_path
        (.../tenants/<tenant>/agents/<agent>/memory/knowledge_index.db). Overridable via
        KNOWLEDGE_PG_SCHEMA. Sanitized to a safe identifier."""
        import re
        override = os.getenv("KNOWLEDGE_PG_SCHEMA")
        if override:
            raw = override
        else:
            try:
                agent = self.db_path.parent.parent.name          # memory → <agent>
                tenant = self.db_path.parent.parent.parent.parent.name  # → <tenant>
                raw = f"kn_{tenant}_{agent}"
            except Exception:
                raw = "kn_default"
        return re.sub(r"[^a-zA-Z0-9_]", "_", raw).lower()[:63]

    def _pg_ddl(self) -> str:
        import sys as _sys
        scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        from knowledge_pg_schema import knowledge_schema_ddl
        return knowledge_schema_ddl(self._pg_schema)

    def _init_db_postgres(self):
        """Create the per-agent schema + tables in Postgres (idempotent DDL).
        Statements split on ';' (the generated DDL contains no in-statement semicolons)."""
        ddl = self._pg_ddl()
        with self._engine.connect() as conn:
            cur = conn.cursor()
            for stmt in (s.strip() for s in ddl.split(";")):
                if stmt:
                    cur.execute(stmt)
        try:
            with self._engine.connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'agentos_graph_ro'")
                if cur.fetchone():
                    s = self._pg_schema
                    cur.execute(f'GRANT USAGE ON SCHEMA "{s}" TO agentos_graph_ro')
                    cur.execute(f'GRANT SELECT ON "{s}".entity_registry TO agentos_graph_ro')
                    cur.execute(f'GRANT SELECT ON "{s}".process_relationships TO agentos_graph_ro')
        except Exception as _ge:
            logger.debug("KnowledgeIndexer(postgres): graph RO grant skipped (non-fatal): %s", _ge)
        logger.info("KnowledgeIndexer(postgres): schema '%s' ready", self._pg_schema)


    def _init_db(self):
        """Create tables and indexes if they don't exist (backend-aware)."""
        if self._kbackend == "postgres":
            self._init_db_postgres()
            return
        try:
            from .sqlite_util import connect as _sqlite_connect
        except ImportError:
            from sqlite_util import connect as _sqlite_connect
        self._db = _sqlite_connect(
            self.db_path,
            check_same_thread=False,
            isolation_level="DEFERRED",
        )
        cur = self._db.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_vectors (
                id            TEXT PRIMARY KEY,
                summary       TEXT NOT NULL,
                knowledge_type TEXT,
                skill         TEXT,
                status        TEXT,
                source_file   TEXT,
                embedding     BLOB,
                ts            TEXT,
                entities_json TEXT,
                tags_json     TEXT,
                written_to    TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS episode_vectors (
                id          TEXT PRIMARY KEY,
                file_path   TEXT NOT NULL,
                session_id  TEXT,
                user_input  TEXT,
                summary     TEXT,
                embedding   BLOB,
                ts          TEXT,
                skill       TEXT,
                trace_id    TEXT,
                entities    TEXT,
                reasoning   TEXT
            )
        """)

        for col_def in _EPISODE_MIGRATIONS:
            try:
                cur.execute(col_def)
            except sqlite3.OperationalError:
                pass  # Column already exists

        for col_def in _KNOWLEDGE_MIGRATIONS:
            try:
                cur.execute(col_def)
            except sqlite3.OperationalError:
                pass  # Column already exists

        cur.execute("""
            CREATE TABLE IF NOT EXISTS entity_xref (
                entity      TEXT NOT NULL,
                record_id   TEXT NOT NULL,
                record_type TEXT NOT NULL DEFAULT 'knowledge',
                PRIMARY KEY (entity, record_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS entity_registry (
                node_id       TEXT PRIMARY KEY,
                node_type     TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                parent_id     TEXT,
                skill_name    TEXT,
                embedding     BLOB,
                metadata_json TEXT DEFAULT '{}',
                aliases_json  TEXT DEFAULT '[]',
                updated_at    TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES entity_registry(node_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_er_parent ON entity_registry(parent_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_er_type ON entity_registry(node_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_er_skill ON entity_registry(skill_name)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS process_relationships (
                id            TEXT PRIMARY KEY,
                from_node     TEXT NOT NULL,
                relation      TEXT NOT NULL,
                to_node       TEXT NOT NULL,
                condition     TEXT,
                metadata_json TEXT DEFAULT '{}',
                updated_at    TEXT NOT NULL,
                confidence    REAL DEFAULT 1.0,
                status        TEXT DEFAULT 'curated',
                source        TEXT,
                created_by    TEXT,
                valid_from    TEXT,
                valid_to      TEXT,
                FOREIGN KEY (from_node) REFERENCES entity_registry(node_id),
                FOREIGN KEY (to_node)   REFERENCES entity_registry(node_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pr_from ON process_relationships(from_node)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pr_to   ON process_relationships(to_node)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pr_status ON process_relationships(status)")

        for _pr_col, _pr_decl in (
            ("confidence", "REAL DEFAULT 1.0"),
            ("status",     "TEXT DEFAULT 'curated'"),
            ("source",     "TEXT"),
            ("created_by", "TEXT"),
            ("valid_from", "TEXT"),
            ("valid_to",   "TEXT"),
        ):
            try:
                cur.execute(f"SELECT {_pr_col} FROM process_relationships LIMIT 1")
            except sqlite3.OperationalError:
                cur.execute(f"ALTER TABLE process_relationships ADD COLUMN {_pr_col} {_pr_decl}")

        # Migrate: add aliases_json if missing (for existing DBs)
        try:
            cur.execute("SELECT aliases_json FROM entity_registry LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE entity_registry ADD COLUMN aliases_json TEXT DEFAULT '[]'")

        # ── FTS5 for keyword fallback (knowledge) ────────────────────────
        # Migrate old narrow FTS5 schema → wider schema (FTS5 can't ALTER)
        try:
            cur.execute("SELECT applies_when FROM fts_knowledge LIMIT 0")
        except sqlite3.OperationalError:
            cur.execute("DROP TABLE IF EXISTS fts_knowledge")

        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_knowledge
            USING fts5(
                id,
                summary,
                knowledge_type,
                skill,
                entities_text,
                applies_when,
                user_query,
                source,
                applies_to_text,
                tokenize='porter unicode61'
            )
        """)

        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_episodes
            USING fts5(
                id,
                user_input,
                summary,
                skill,
                tokenize='porter unicode61'
            )
        """)

        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_entities
            USING fts5(
                node_id,
                display_name,
                aliases_text,
                node_type,
                tokenize='porter unicode61'
            )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_kv_skill ON knowledge_vectors(skill)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kv_status ON knowledge_vectors(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kv_type ON knowledge_vectors(knowledge_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kv_ts ON knowledge_vectors(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kv_source ON knowledge_vectors(source)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ex_entity ON entity_xref(entity)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ex_record ON entity_xref(record_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ev_skill ON episode_vectors(skill)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ev_ts ON episode_vectors(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ev_session ON episode_vectors(session_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ev_trace ON episode_vectors(trace_id)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS plan_cache (
                plan_id          TEXT PRIMARY KEY,
                goal             TEXT NOT NULL,
                embedding        BLOB,
                fingerprint      TEXT,
                detected_domains TEXT,
                entity_types     TEXT,
                process_nodes    TEXT,
                plan_steps       TEXT NOT NULL,
                critique_json    TEXT,
                execution_mode   TEXT DEFAULT 'react',
                status           TEXT DEFAULT 'pending_review',
                session_id       TEXT,
                tenant_id        TEXT,
                agent_id         TEXT,
                created_at       TEXT NOT NULL,
                approved_at      TEXT,
                approved_by      TEXT,
                executed_at      TEXT,
                use_count        INTEGER DEFAULT 0,
                last_used_at     TEXT,
                context_hints    TEXT DEFAULT '[]'
            )
        """)
        # Migration for existing DBs that lack context_hints column
        try:
            cur.execute("ALTER TABLE plan_cache ADD COLUMN context_hints TEXT DEFAULT '[]'")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pc_fingerprint ON plan_cache(fingerprint) WHERE fingerprint IS NOT NULL"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pc_status ON plan_cache(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pc_tenant ON plan_cache(tenant_id, agent_id)")

        self._db.commit()

    def close(self) -> None:
        """Close the SQLite connection and release the WAL reader slot."""
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    def __del__(self) -> None:
        self.close()

    def _checkpoint(self) -> None:
        """Run a passive WAL checkpoint — returns immediately if writers are active."""
        if self._db is not None:
            try:
                self._db.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception:
                pass


    @staticmethod
    def _serialize_embedding(embedding: List[float]) -> bytes:
        """Pack float list into compact binary for BLOB storage."""
        return struct.pack(f"{len(embedding)}f", *embedding)

    @staticmethod
    def _deserialize_embedding(data: bytes) -> List[float]:
        """Unpack BLOB back to float list."""
        n = len(data) // 4
        return list(struct.unpack(f"{n}f", data))

    @staticmethod
    def _plan_fingerprint(plan_steps: list) -> str:
        """Return a 16-char SHA-256 hex digest of normalized step structure."""
        import hashlib, json as _json
        normalized = [
            {"skill": s.get("skill", ""), "action": s.get("action", "")}
            for s in sorted(plan_steps, key=lambda x: x.get("step", 0))
        ]
        raw = _json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Pure-Python cosine similarity. Returns 0.0 on degenerate input."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _safe_get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding with error handling. Returns None on failure."""
        if not self._get_embedding or not text:
            return None
        try:
            emb = self._get_embedding(text[:8000])  # Truncate to model limit
            return emb if emb else None
        except Exception as e:
            logger.warning("KnowledgeIndexer: embedding failed: %s", e)
            return None


    def upsert_knowledge(self, record: Dict[str, Any]) -> bool:
        """
        Insert or update a knowledge record in the index.

        Expects a record dict with at minimum: id, summary.
        Typical fields: id, summary, type, status, scope.skill, scope.tags,
                        source, ts, entities.

        Returns True on success.
        """
        rec_id = record.get("id")
        if not rec_id or not isinstance(rec_id, str):
            return False
        if not _SAFE_RECORD_ID_RE.match(rec_id):
            logger.warning("upsert_knowledge: rejected record with malformed id %r", rec_id)
            return False

        summary = record.get("summary", "")
        if not summary:
            # Build searchable text from content if no summary
            summary = record.get("content", record.get("rule", ""))
        if not summary:
            return False

        knowledge_type = record.get("type", "unknown")
        scope = record.get("scope", {})
        skill = scope.get("skill", "")
        status = record.get("status", "unknown")
        source = record.get("source", "unknown")
        applies_when = scope.get("applies_when", "")
        ts = record.get("ts", datetime.now().isoformat())
        tags = scope.get("tags", [])
        source_file = record.get("_source_file", "knowledge.jsonl")
        written_to = record.get("written_to")

        entities = self._extract_entities(record)
        entities_json = json.dumps(entities)
        tags_json = json.dumps(tags)

        # Extract additional searchable fields for wider FTS5
        user_query = record.get("user_query", "")
        applies_to = record.get("applies_to", {})
        applies_to_text = ""
        if isinstance(applies_to, dict):
            applies_to_text = " ".join(str(v) for v in applies_to.values() if v)

        # Store full record as raw JSON (exclude internal keys)
        raw_record = {k: v for k, v in record.items() if not k.startswith("_")}
        raw_json_str = json.dumps(raw_record, default=str)

        embedding_blob = None
        emb = self._safe_get_embedding(summary)
        if emb:
            embedding_blob = self._serialize_embedding(emb)

        entities_text = " ".join(entities)
        # Postgres generated tsvector feeder (mirrors the fts_knowledge searchable fields)
        fts_text = " ".join(str(x) for x in [
            summary, knowledge_type, skill, entities_text,
            applies_when, user_query, source, applies_to_text,
        ] if x)

        resolved_ids = []
        try:
            resolved_ids = self.entity_registry.auto_register_entities(
                entity_names=entities, skill_name=skill
            )
        except Exception as reg_err:
            logger.warning("auto_register_entities (knowledge) failed: %s", reg_err)

        xref_keys = set()
        for nid in resolved_ids:
            xref_keys.add(nid.lower().strip())
        try:
            for tm in self.entity_registry._resolve_by_taxonomy(summary):
                xref_keys.add(tm["node_id"])
        except Exception:
            pass

        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                if self._kbackend == "postgres":
                    _vals = ", ".join([self._ph] * 16)
                    cur.execute(f"""
                        INSERT INTO knowledge_vectors
                            (id, summary, knowledge_type, skill, status,
                             source_file, embedding, ts, entities_json, tags_json,
                             source, applies_when, raw_json, written_to, fts_text, entities_text)
                        VALUES ({_vals})
                        ON CONFLICT (id) DO UPDATE SET
                            summary        = excluded.summary,
                            knowledge_type = excluded.knowledge_type,
                            skill          = excluded.skill,
                            status         = excluded.status,
                            source_file    = excluded.source_file,
                            embedding      = excluded.embedding,
                            ts             = excluded.ts,
                            entities_json  = excluded.entities_json,
                            tags_json      = excluded.tags_json,
                            source         = excluded.source,
                            applies_when   = excluded.applies_when,
                            raw_json       = excluded.raw_json,
                            written_to     = COALESCE(excluded.written_to, knowledge_vectors.written_to),
                            fts_text       = excluded.fts_text,
                            entities_text  = excluded.entities_text
                    """, (rec_id, summary, knowledge_type, skill, status,
                          source_file, embedding_blob, ts, entities_json, tags_json,
                          source, applies_when, raw_json_str, written_to, fts_text, entities_text))
                else:
                    cur.execute("""
                        INSERT INTO knowledge_vectors
                            (id, summary, knowledge_type, skill, status,
                             source_file, embedding, ts, entities_json, tags_json,
                             source, applies_when, raw_json, written_to)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            summary        = excluded.summary,
                            knowledge_type = excluded.knowledge_type,
                            skill          = excluded.skill,
                            status         = excluded.status,
                            source_file    = excluded.source_file,
                            embedding      = excluded.embedding,
                            ts             = excluded.ts,
                            entities_json  = excluded.entities_json,
                            tags_json      = excluded.tags_json,
                            source         = excluded.source,
                            applies_when   = excluded.applies_when,
                            raw_json       = excluded.raw_json,
                            written_to     = COALESCE(excluded.written_to, knowledge_vectors.written_to)
                    """, (rec_id, summary, knowledge_type, skill, status,
                          source_file, embedding_blob, ts, entities_json, tags_json,
                          source, applies_when, raw_json_str, written_to))

                    # ── Upsert FTS5 (wider: 9 searchable fields) ── SQLite only
                    # (Postgres auto-maintains search_tsv from the fts_text column above)
                    cur.execute("DELETE FROM fts_knowledge WHERE id = ?", (rec_id,))
                    cur.execute("""
                        INSERT INTO fts_knowledge
                            (id, summary, knowledge_type, skill, entities_text,
                             applies_when, user_query, source, applies_to_text)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (rec_id, summary, knowledge_type, skill, entities_text,
                          applies_when, user_query, source, applies_to_text))

                # ── Upsert entity_xref (entities + taxonomy resolved pre-transaction) ──
                cur.execute(
                    f"DELETE FROM entity_xref WHERE record_id = {self._ph} AND record_type = 'knowledge'",
                    (rec_id,))

                if self._kbackend == "postgres":
                    for xk in xref_keys:
                        cur.execute(f"""
                            INSERT INTO entity_xref (entity, record_id, record_type)
                            VALUES ({self._ph}, {self._ph}, 'knowledge')
                            ON CONFLICT DO NOTHING
                        """, (xk, rec_id))
                else:
                    for xk in xref_keys:
                        cur.execute("""
                            INSERT OR IGNORE INTO entity_xref (entity, record_id, record_type)
                            VALUES (?, ?, 'knowledge')
                        """, (xk, rec_id))

                conn.commit()

            if emb:
                try:
                    self._vector_backend.upsert("knowledge", rec_id, emb)
                except Exception as ve:
                    logger.warning("VectorBackend.upsert(knowledge) failed for %s: %s",
                                   rec_id, ve)

            return True

        except Exception as e:
            logger.warning("KnowledgeIndexer.upsert_knowledge failed: %s", e)
            if self._kbackend != "postgres" and self._db:
                self._db.rollback()
            return False

    def _extract_entities(self, record: Dict) -> List[str]:
        """
        Extract entity names from a knowledge record.
        Looks in: scope.tags, entities field, and parses summary for @-mentions.
        """
        entities = set()

        # From scope.tags
        scope = record.get("scope", {})
        for tag in scope.get("tags", []):
            entities.add(tag.lower().strip())

        # From explicit entities field
        for ent in record.get("entities", []):
            if isinstance(ent, str):
                entities.add(ent.lower().strip())
            elif isinstance(ent, dict):
                name = ent.get("name", ent.get("entity", ""))
                if name:
                    entities.add(name.lower().strip())

        # From structured entity_keys (e.g. "vendor:ACME", "invoice:INV-001")
        for ek in record.get("entity_keys", []):
            if isinstance(ek, str) and ek.strip():
                entities.add(ek.lower().strip())

        skill = scope.get("skill", "")
        if skill:
            entities.add(skill.lower().strip())

        return [e for e in entities if e]


    def search_similar(
        self,
        query: str,
        top_k: int = 10,
        status: Optional[str] = None,
        skill: Optional[str] = None,
        knowledge_type: Optional[str] = None,
        min_score: Optional[float] = None,
        _precomputed_embedding: Optional[List[float]] = None,
    ) -> List[Dict]:
        """
        Semantic search over indexed knowledge records.

        Strategy:
          1. If embedding function available → compute query embedding,
             brute-force cosine similarity against all matching rows.
          2. If no embeddings → fall back to FTS5 keyword search.

        Args:
            _precomputed_embedding: Optional pre-computed query embedding to avoid
                                    duplicate API calls. When provided, skips _safe_get_embedding.

        Returns list of dicts:
          [{"id": ..., "summary": ..., "score": 0.87, "skill": ..., ...}]
        sorted by descending score.
        """
        threshold = min_score if min_score is not None else self.COSINE_MIN_SCORE

        # Try semantic search first (reuse cached embedding if provided)
        query_emb = _precomputed_embedding or self._safe_get_embedding(query)
        if query_emb:
            return self._search_by_embedding(query_emb, top_k, status, skill,
                                             knowledge_type, threshold)

        # Fallback: FTS5 keyword search
        return self._search_by_fts(query, top_k, status, skill, knowledge_type)

    def search_by_entity(
        self,
        entity_name: str,
        top_k: int = 5,
        status: Optional[str] = None,
        exclude_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Retrieve knowledge records for a specific entity, newest first.

        Strategy:
          1. entity_xref JOIN knowledge_vectors — exact match on normalised node_id
             (e.g. "vendor:fastship", "fastship")
          2. FTS5 fallback on entities_text — fuzzy keyword match when xref has no rows.

        Args:
            entity_name:  Raw entity name from router (e.g. "FastShip", "INV-050").
                          Normalised to lowercase before lookup.
            top_k:        Max records to return.
            status:       Optional status filter (e.g. "active", "confirmed").
            exclude_ids:  Record IDs to skip (avoids duplicates when combining with
                          query-similarity results).

        Returns list of dicts matching search_similar() shape:
          [{"id": ..., "summary": ..., "knowledge_type": ..., "skill": ...,
            "ts": ..., "source": ..., "entities": [...], "match_method": "entity_xref"}]
        sorted by ts DESC (most recent first).
        """
        if not entity_name:
            return []

        normalised = entity_name.lower().strip()
        exclude = set(exclude_ids or [])
        results: List[Dict] = []

        with self._scoped_connect() as conn:
            cur = conn.cursor()

            # ── Strategy 1: entity_xref exact lookup ─────────────────────────────
            # Try both raw name and common prefixed forms (vendor:name, customer:name, etc.)
            candidates = {normalised}
            for prefix in ("vendor", "customer", "invoice", "employee", "transaction", "entity"):
                candidates.add(f"{prefix}:{normalised}")

            in_clause = _sql_in_clause(len(candidates), self._ph)
            status_clause = f"AND kv.status = {self._ph}" if status else ""
            sql = f"""
                SELECT DISTINCT kv.id, kv.summary, kv.knowledge_type, kv.skill,
                                kv.ts, kv.source, kv.entities_json, kv.status
                FROM entity_xref x
                JOIN knowledge_vectors kv ON x.record_id = kv.id
                WHERE x.entity IN {in_clause}
                {status_clause}
                ORDER BY kv.ts DESC
                LIMIT {self._ph}
            """
            params = list(candidates)
            if status:
                params.append(status)
            params.append(top_k + len(exclude))

            try:
                rows = cur.execute(sql, params).fetchall()
                for row in rows:
                    rid, summary, ktype, skill, ts, source, ents_json, kstatus = row
                    if rid in exclude:
                        continue
                    results.append({
                        "id": rid,
                        "summary": summary or "",
                        "knowledge_type": ktype or "knowledge",
                        "skill": skill or "",
                        "ts": ts or "",
                        "source": source or "",
                        "entities": json.loads(ents_json) if ents_json else [],
                        "status": kstatus or "",
                        "match_method": "entity_xref",
                    })
                    if len(results) >= top_k:
                        break
            except Exception as e:
                logger.warning("search_by_entity xref lookup failed: %s", e)

            if len(results) >= top_k:
                return results

            already = exclude | {r["id"] for r in results}
            needed = top_k - len(results)
            try:
                if self._kbackend == "postgres":
                    # entities_tsv is the generated tsvector on entities_text ('simple')
                    fts_params = [normalised]
                    if status:
                        fts_params.append(status)
                    fts_params.append(needed + len(already))
                    fts_rows = cur.execute(
                        f"""
                        SELECT kv.id, kv.summary, kv.knowledge_type, kv.skill,
                               kv.ts, kv.source, kv.entities_json, kv.status
                        FROM knowledge_vectors kv
                        WHERE kv.entities_tsv @@ plainto_tsquery('simple', {self._ph})
                        {status_clause}
                        ORDER BY kv.ts DESC
                        LIMIT {self._ph}
                        """,
                        fts_params,
                    ).fetchall()
                else:
                    # Build query: match entity name in entities_text column only
                    fts_query = f'entities_text : "{normalised}"'
                    fts_params = [fts_query]
                    if status:
                        fts_params.append(status)
                    fts_params.append(needed + len(already))
                    fts_rows = cur.execute(
                        f"""
                        SELECT kv.id, kv.summary, kv.knowledge_type, kv.skill,
                               kv.ts, kv.source, kv.entities_json, kv.status
                        FROM fts_knowledge fts
                        JOIN knowledge_vectors kv ON kv.id = fts.id
                        WHERE fts_knowledge MATCH ?
                        {'AND kv.status = ?' if status else ''}
                        ORDER BY kv.ts DESC
                        LIMIT ?
                        """,
                        fts_params,
                    ).fetchall()

                for row in fts_rows:
                    rid, summary, ktype, skill, ts, source, ents_json, kstatus = row
                    if rid in already:
                        continue
                    results.append({
                        "id": rid,
                        "summary": summary or "",
                        "knowledge_type": ktype or "knowledge",
                        "skill": skill or "",
                        "ts": ts or "",
                        "source": source or "",
                        "entities": json.loads(ents_json) if ents_json else [],
                        "status": kstatus or "",
                        "match_method": "fts5_entities",
                    })
                    if len(results) >= top_k:
                        break
            except Exception as e:
                logger.warning("search_by_entity FTS5 fallback failed: %s", e)

        return results

    def search_similar_episodes(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
        success_only: bool = True,
    ) -> List[Dict]:
        """
        Find episodes with similar user queries (procedural memory).
        
        Used for:
        - Routing hints: which skill worked for similar queries
        - Tool hints: which tools were used successfully
        
        Returns list of dicts sorted by similarity:
        {
            "user_input": "What licenses for ACME?",
            "skill": "vendor_api",
            "entities": ["vendor:acme"],
            "tools": "shell,curl",
            "outcome_status": "success",
            "score": 0.87
        }
        """
        # 1. Embed the query
        emb = self._safe_get_embedding(query)
        if not emb:
            logger.debug("search_similar_episodes: no embedding available")
            return []
        
        # 2. Use vector backend to search episode embeddings
        try:
            id_scores = self._vector_backend.search(
                collection="episodes",
                query_embedding=emb,
                top_k=top_k * 2,  # Fetch extra to filter by success
                min_score=min_score,
                candidate_ids=None,  # Search all
            )
        except Exception as e:
            logger.warning("Episode vector search failed: %s", e)
            return []
        
        if not id_scores:
            return []
        
        # 3. Fetch metadata for matched episodes
        results = []
        fetched = []
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            for record_id, score in id_scores:
                cur.execute(f"""
                    SELECT user_input, skill, entities, reasoning
                    FROM episode_vectors WHERE id = {self._ph}
                """, (record_id,))
                row = cur.fetchone()
                if row:
                    fetched.append((score, row))
        for score, row in fetched:
            user_input, skill, entities_json, reasoning = row

            # Parse outcome status and tools from reasoning
            # Format: "routed:forced(1.0) | outcome:success | tools:shell,query_memory | 14891ms"
            outcome_status = "unknown"
            tools = ""
            if reasoning:
                for part in reasoning.split(" | "):
                    part = part.strip()
                    if part.startswith("outcome:"):
                        outcome_status = part.split(":", 1)[1]
                    elif part.startswith("tools:"):
                        tools = part.split(":", 1)[1]
            
            if success_only and outcome_status != "success":
                continue
            
            results.append({
                "user_input": user_input or "",
                "skill": skill or "",
                "entities": json.loads(entities_json) if entities_json else [],
                "tools": tools,
                "outcome_status": outcome_status,
                "score": score,
            })
            
            if len(results) >= top_k:
                break
        
        logger.debug("search_similar_episodes: found %d matches (success_only=%s)", 
                    len(results), success_only)
        return results

    def _search_by_embedding(
        self,
        query_emb: List[float],
        top_k: int,
        status: Optional[str],
        skill: Optional[str],
        knowledge_type: Optional[str],
        min_score: float,
    ) -> List[Dict]:
        """Vector similarity search over knowledge records.

        Strategy:
          1. Pre-filter candidate IDs by metadata (status, skill, type)
             using B-tree indexes — fast O(log n) SQL query.
          2. Delegate vector similarity search to the VectorBackend,
             passing candidate_ids to restrict the search scope.
          3. Enrich top-K results with full metadata from SQL.

        This replaces the previous brute-force Python loop with a
        pluggable backend (BruteForce, sqlite-vec, or pgvector).
        """
        # Step 1: Pre-filter by metadata to get candidate IDs
        candidate_ids = self._get_candidate_ids(
            "knowledge", status=status, skill=skill, knowledge_type=knowledge_type
        )
        # If metadata filters returned no candidates, skip vector search
        if candidate_ids is not None and not candidate_ids:
            return []

        # Step 2: Vector similarity search via backend
        id_scores = self._vector_backend.search(
            collection="knowledge",
            query_embedding=query_emb,
            top_k=top_k,
            min_score=min_score,
            candidate_ids=candidate_ids,
        )

        # Step 3: Enrich with full metadata from SQLite
        results = []
        for record_id, score in id_scores:
            result = self._build_knowledge_search_result(record_id, score)
            if result:
                results.append(result)

        return results

    def _get_candidate_ids(
        self,
        table_type: str,
        status: Optional[str] = None,
        skill: Optional[str] = None,
        knowledge_type: Optional[str] = None,
    ) -> Optional[Set[str]]:
        """Pre-filter record IDs by metadata using B-tree indexes.

        Returns:
            Set of matching IDs, or None if no filters applied (search all).
        """
        conditions: List[str] = []
        params: List[Any] = []

        if status:
            conditions.append(f"status = {self._ph}")
            params.append(status)
        if skill:
            conditions.append(f"(skill = {self._ph} OR skill IS NULL OR skill = '')")
            params.append(skill)
        if knowledge_type:
            conditions.append(f"knowledge_type = {self._ph}")
            params.append(knowledge_type)

        # No filters → return None (meaning: search all vectors)
        if not conditions:
            return None

        table = "knowledge_vectors" if table_type == "knowledge" else "episode_vectors"
        validated_table = _validated_ki_table(table)
        where_clause = _sql_where(conditions)
        sql = "SELECT id FROM " + validated_table + " " + where_clause

        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {row[0] for row in cur.fetchall()}

    def _build_knowledge_search_result(
        self, record_id: str, score: float
    ) -> Optional[Dict]:
        """Fetch full metadata for a knowledge record and build result dict."""
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT id, summary, knowledge_type, skill, status,
                       source_file, ts, entities_json, tags_json, raw_json, written_to
                FROM knowledge_vectors WHERE id = {self._ph}
            """, (record_id,))
            row = cur.fetchone()
        if not row:
            return None

        (rid, summary, ktype, sk, st, src, ts, ent_json, tags_json, raw_json, written_to) = row
        result = {
            "id": rid,
            "summary": summary,
            "knowledge_type": ktype,
            "skill": sk or "",
            "status": st,
            "source_file": src,
            "written_to": written_to,
            "score": score,
            "ts": ts,
            "entities": json.loads(ent_json) if ent_json else [],
            "tags": json.loads(tags_json) if tags_json else [],
            "match_method": "semantic",
        }
        if raw_json:
            try:
                full = json.loads(raw_json)
                for key in ("provenance", "lifecycle", "user_query",
                            "confidence", "decision_id", "applies_to", "scope"):
                    if key in full:
                        result.setdefault(key, full[key])
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def _search_by_fts(
        self,
        query: str,
        top_k: int,
        status: Optional[str],
        skill: Optional[str],
        knowledge_type: Optional[str],
    ) -> List[Dict]:
        """FTS5 keyword search as fallback when no embeddings available."""
        # Clean query for FTS5 (remove special chars that break FTS syntax)
        fts_query = self._sanitize_fts_query(query)
        if not fts_query:
            return []

        fts_rows = []
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            try:
                if self._kbackend == "postgres":
                    # tsvector fallback; the sanitizer emits "w1 OR w2" → bridge to tsquery "|"
                    tsq = fts_query.replace(" OR ", " | ").replace(" AND ", " & ")
                    cur.execute(f"""
                        SELECT id, summary, knowledge_type, skill,
                               ts_rank_cd(search_tsv, to_tsquery('english', {self._ph})) AS rank
                        FROM knowledge_vectors
                        WHERE search_tsv @@ to_tsquery('english', {self._ph})
                        ORDER BY rank DESC
                        LIMIT {self._ph}
                    """, (tsq, tsq, top_k * 3))
                    fts_rows = cur.fetchall()
                else:
                    # FTS5 match with BM25 ranking
                    sql = """
                        SELECT f.id, f.summary, f.knowledge_type, f.skill,
                               rank
                        FROM fts_knowledge f
                        WHERE fts_knowledge MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """
                    cur.execute(sql, (fts_query, top_k * 3))  # Fetch extra for post-filter
                    fts_rows = cur.fetchall()
            except sqlite3.OperationalError:
                # FTS5 query syntax error — retry with simpler query (SQLite only)
                words = query.split()[:5]
                simple_query = " OR ".join(w for w in words if w.isalnum())
                if not simple_query:
                    return []
                try:
                    cur.execute("""
                        SELECT f.id, f.summary, f.knowledge_type, f.skill, rank
                        FROM fts_knowledge f
                        WHERE fts_knowledge MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (simple_query, top_k * 3))
                    fts_rows = cur.fetchall()
                except Exception:
                    return []
            except Exception:
                # Postgres tsquery parse error or other — degrade to no FTS results
                return []

        # Enrich FTS results with metadata from knowledge_vectors
        results = []
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            for fid, fsummary, fktype, fskill, frank in fts_rows:
                # Apply post-filters (FTS5 doesn't know about status)
                if status or skill or knowledge_type:
                    cur.execute(f"""
                        SELECT status, skill, knowledge_type, source_file, ts,
                               entities_json, tags_json, raw_json
                        FROM knowledge_vectors WHERE id = {self._ph}
                    """, (fid,))
                    meta = cur.fetchone()
                    if not meta:
                        continue
                    m_status, m_skill, m_ktype, m_src, m_ts, m_ent, m_tags, m_raw = meta
                    if status and m_status != status:
                        continue
                    if skill and m_skill and m_skill != skill:
                        continue
                    if knowledge_type and m_ktype != knowledge_type:
                        continue
                    result = {
                        "id": fid,
                        "summary": fsummary,
                        "knowledge_type": m_ktype,
                        "skill": m_skill or "",
                        "status": m_status,
                        "source_file": m_src,
                        "score": round(abs(frank) * 0.1, 4) if frank else 0.5,
                        "ts": m_ts,
                        "entities": json.loads(m_ent) if m_ent else [],
                        "tags": json.loads(m_tags) if m_tags else [],
                        "match_method": "fts5",
                    }
                    if m_raw:
                        try:
                            full = json.loads(m_raw)
                            for key in ("provenance", "lifecycle", "user_query",
                                        "confidence", "decision_id", "applies_to", "scope"):
                                if key in full:
                                    result.setdefault(key, full[key])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append(result)
                else:
                    # No post-filter needed — lightweight path
                    results.append({
                        "id": fid,
                        "summary": fsummary,
                        "knowledge_type": fktype,
                        "skill": fskill or "",
                        "status": None,
                        "source_file": None,
                        "score": round(abs(frank) * 0.1, 4) if frank else 0.5,
                        "ts": None,
                        "entities": [],
                        "tags": [],
                        "match_method": "fts5",
                    })

                if len(results) >= top_k:
                    break

        return results

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize user query for FTS5 MATCH syntax."""
        # Remove FTS5 special characters
        cleaned = query.replace('"', '').replace("'", "").replace("*", "")
        cleaned = cleaned.replace("(", "").replace(")", "")
        cleaned = cleaned.replace(":", "").replace("-", " ")
        # Split into words, keep only alphanumeric
        words = [w.strip() for w in cleaned.split() if w.strip() and len(w.strip()) > 1]
        if not words:
            return ""
        # Join with OR for broader matching
        return " OR ".join(words)


    def entity_lookup(
        self,
        entity: str,
        record_type: Optional[str] = None,
        top_k: int = 20,
    ) -> List[Dict]:
        """
        Look up knowledge records by entity name.

        Args:
            entity: Entity name to search (case-insensitive).
            record_type: Optional filter — 'knowledge' or 'episode'.
            top_k: Max results.

        Returns list of dicts with record info + source_file.
        """
        entity_lower = entity.lower().strip()
        if not entity_lower:
            return []

        results: List[Dict] = []
        with self._scoped_connect() as conn:
            cur = conn.cursor()

            if record_type is None or record_type == "knowledge":
                if record_type is None:
                    kv_where = f"ex.entity = {self._ph} AND ex.record_type = 'knowledge'"
                    kv_params: List[Any] = [entity_lower]
                else:
                    kv_where = f"ex.entity = {self._ph} AND ex.record_type = {self._ph}"
                    kv_params = [entity_lower, record_type]
                sql_kv = f"""
                    SELECT kv.id, kv.summary, kv.knowledge_type, kv.skill,
                           kv.status, kv.source_file, kv.ts, kv.entities_json,
                           kv.tags_json, kv.raw_json, kv.written_to
                    FROM entity_xref ex
                    JOIN knowledge_vectors kv ON ex.record_id = kv.id
                    WHERE {kv_where}
                    ORDER BY kv.ts DESC
                    LIMIT {self._ph}
                """
                kv_params.append(top_k)
                cur.execute(sql_kv, kv_params)
                for r in cur.fetchall():
                    result = {
                        "id": r[0],
                        "summary": r[1],
                        "knowledge_type": r[2],
                        "skill": r[3] or "",
                        "status": r[4],
                        "source_file": r[5],
                        "ts": r[6],
                        "entities": json.loads(r[7]) if r[7] else [],
                        "tags": json.loads(r[8]) if r[8] else [],
                        "match_method": "entity_xref",
                        "written_to": r[10],
                    }
                    if r[9]:
                        try:
                            full = json.loads(r[9])
                            for key in ("provenance", "lifecycle", "user_query",
                                        "confidence", "decision_id", "applies_to", "scope"):
                                if key in full:
                                    result.setdefault(key, full[key])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append(result)

            if record_type is None or record_type == "episode":
                ep_where = f"ex.entity = {self._ph} AND ex.record_type = 'episode'"
                ep_params: List[Any] = [entity_lower]
                sql_ep = f"""
                    SELECT ev.id, ev.summary, ev.skill, ev.ts,
                           ev.file_path, ev.session_id, ev.user_input,
                           ev.trace_id, ev.entities, ev.reasoning
                    FROM entity_xref ex
                    JOIN episode_vectors ev ON ex.record_id = ev.id
                    WHERE {ep_where}
                    ORDER BY ev.ts DESC
                    LIMIT {self._ph}
                """
                ep_params.append(top_k)
                cur.execute(sql_ep, ep_params)
                for r in cur.fetchall():
                    results.append({
                        "id": r[0],
                        "summary": r[1] or "",
                        "skill": r[2] or "",
                        "ts": r[3],
                        "source_file": r[4] or "",
                        "session_id": r[5] or "",
                        "user_input": r[6] or "",
                        "trace_id": r[7] or "",
                        "entities": json.loads(r[8]) if r[8] else [],
                        "reasoning": r[9] or "",
                        "match_method": "entity_xref",
                    })

        return results[:top_k]

    def get_episode_reasoning_row(self, trace_id: str):
        """Return the raw (reasoning, entities_json) tuple for the episode with this
        trace_id, or None if not found. Backend-agnostic accessor used by the Studio
        chat reasoning-poll endpoint so it never opens a raw sqlite3 handle to the
        index file (which would miss data on a Postgres-backed agent)."""
        if not trace_id:
            return None
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT reasoning, entities FROM episode_vectors WHERE trace_id = {self._ph} LIMIT 1",
                (trace_id,),
            )
            return cur.fetchone()


    def expand_by_entities(
        self,
        entity_keys: set,
        record_type: Optional[str] = None,
        exclude_ids: Optional[set] = None,
        top_k: int = 20,
    ) -> List[Dict]:
        """
        Given entity keys extracted from semantic search results (Lane 1),
        find ALL additional records linked to those entities via entity_xref.

        This is the "follow the links" step — no embedding, no LLM call.
        Just indexed SQL JOINs on entity_xref.

        Args:
            entity_keys: Set of entity keys e.g. {"vendor:acme", "invoice:inv-99"}.
                         Typically extracted from Lane 1 search results' entities field.
            record_type: Optional filter — "knowledge", "episode", or None for both.
            exclude_ids: Record IDs already found by Lane 1 (for deduplication).
            top_k: Maximum additional records to return.

        Returns:
            List of dicts with record info. Only records NOT in exclude_ids.
        """
        if not entity_keys:
            return []

        exclude = exclude_ids or set()
        normalized_keys = [k.lower().strip() for k in entity_keys if k and k.strip()]
        if not normalized_keys:
            return []

        results: List[Dict] = []
        in_clause = _sql_in_clause(len(normalized_keys), self._ph)

        if record_type is None or record_type == "knowledge":
            sql_kv = f"""
                SELECT DISTINCT kv.id, kv.summary, kv.knowledge_type, kv.skill,
                       kv.status, kv.source_file, kv.ts, kv.entities_json,
                       kv.tags_json, kv.raw_json
                FROM entity_xref ex
                JOIN knowledge_vectors kv ON ex.record_id = kv.id
                WHERE ex.entity IN {in_clause}
                  AND ex.record_type = 'knowledge'
                ORDER BY kv.ts DESC
                LIMIT {self._ph}
            """
            params_kv = normalized_keys + [top_k + len(exclude)]
            try:
                with self._scoped_connect() as conn:
                    cur = conn.cursor()
                    cur.execute(sql_kv, params_kv)
                    kv_rows = cur.fetchall()
                for r in kv_rows:
                    rid = r[0]
                    if rid in exclude:
                        continue
                    result = {
                        "id": rid,
                        "summary": r[1],
                        "knowledge_type": r[2],
                        "skill": r[3] or "",
                        "status": r[4],
                        "source_file": r[5],
                        "ts": r[6],
                        "entities": json.loads(r[7]) if r[7] else [],
                        "tags": json.loads(r[8]) if r[8] else [],
                        "match_method": "entity_xref",
                    }
                    # Enrich with full metadata from raw_json
                    if r[9]:
                        try:
                            full = json.loads(r[9])
                            for key in ("provenance", "lifecycle", "user_query",
                                        "confidence", "decision_id", "applies_to", "scope"):
                                if key in full:
                                    result.setdefault(key, full[key])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append(result)
                    if len(results) >= top_k:
                        return results
            except Exception as e:
                logger.warning("Entity expansion (knowledge) failed: %s", e)

        if record_type is None or record_type == "episode":
            remaining = top_k - len(results)
            if remaining <= 0:
                return results
            sql_ep = f"""
                SELECT DISTINCT ev.id, ev.summary, ev.skill, ev.ts,
                       ev.file_path, ev.session_id, ev.user_input,
                       ev.trace_id, ev.entities, ev.reasoning
                FROM entity_xref ex
                JOIN episode_vectors ev ON ex.record_id = ev.id
                WHERE ex.entity IN {in_clause}
                  AND ex.record_type = 'episode'
                ORDER BY ev.ts DESC
                LIMIT {self._ph}
            """
            params_ep = normalized_keys + [remaining + len(exclude)]
            try:
                with self._scoped_connect() as conn:
                    cur = conn.cursor()
                    cur.execute(sql_ep, params_ep)
                    ep_rows = cur.fetchall()
                for r in ep_rows:
                    rid = r[0]
                    if rid in exclude:
                        continue
                    results.append({
                        "id": rid,
                        "summary": r[1] or "",
                        "skill": r[2] or "",
                        "ts": r[3],
                        "source_file": r[4] or "",
                        "session_id": r[5] or "",
                        "user_input": r[6] or "",
                        "trace_id": r[7] or "",
                        "entities": json.loads(r[8]) if r[8] else [],
                        "reasoning": r[9] or "",
                        "match_method": "entity_xref",
                    })
                    if len(results) >= top_k:
                        return results
            except Exception as e:
                logger.warning("Entity expansion (episodes) failed: %s", e)

        return results


    def upsert_episode(self, episode: Dict[str, Any], file_path: str = "") -> bool:
        """
        Insert or update an episode record in the index.

        Builds a searchable text from user_input + response_summary,
        embeds it, and stores in episode_vectors + fts_episodes.

        Args:
            episode: Dict with at minimum user_input + response (or response_summary).
                     Typical keys: timestamp, session_id, skill, user_input,
                     response, response_summary, tool_calls.
            file_path: Path to the source JSONL file (for drill-down).

        Returns True on success.
        """
        user_input = episode.get("user_input", "")
        if not user_input:
            return False

        # Build stable ID from timestamp + session + user_input hash
        ts = episode.get("timestamp", datetime.now().isoformat())
        session_id = episode.get("session_id", "")
        input_hash = hashlib.sha256(f"{ts}|{session_id}|{user_input}".encode()).hexdigest()[:12]
        ep_id = f"ep_{input_hash}"

        # Build searchable text: user query + summarized response
        response_summary = episode.get("response_summary", "")
        if not response_summary:
            response_summary = episode.get("response", "")[:500]
        searchable = f"{user_input} | {response_summary[:300]}"

        skill = episode.get("skill", "")

        # DecisionTrace fields (Phase 6)
        trace_id = episode.get("trace_id") or None

        # Entities: explicit list > auto-extract from skill + entity fields
        entities_raw = episode.get("entities", [])
        if not entities_raw:
            auto_ents: list[str] = []
            if skill:
                auto_ents.append(skill.lower().strip())
            # singular "entity" field — also fallback to routing.entity_hint for older records
            ent_val = episode.get("entity") or (episode.get("routing") or {}).get("entity_hint")
            if ent_val and isinstance(ent_val, str):
                auto_ents.append(ent_val.lower().strip())
            entities_raw = auto_ents
        entities_json = json.dumps(entities_raw) if entities_raw else None

        # Reasoning: explicit > auto-build from routing + outcome + tool names
        reasoning = episode.get("reasoning") or None
        if not reasoning:
            routing = episode.get("routing")
            outcome = episode.get("outcome")
            parts: list[str] = []
            if routing and isinstance(routing, dict):
                method = routing.get("method", "")
                conf = routing.get("confidence", 0)
                if method:
                    parts.append(f"routed:{method}({conf})")
            if outcome and isinstance(outcome, dict):
                status = outcome.get("status", "")
                t_ms = outcome.get("processing_time_ms", 0)
                if status:
                    parts.append(f"outcome:{status}")
                
                # Enhanced: Extract tool NAMES from tool_calls (not just count)
                tool_calls = episode.get("tool_calls", [])
                if tool_calls and isinstance(tool_calls, list):
                    # Dedupe while preserving order, limit to 10
                    seen_tools = set()
                    unique_tools = []
                    for tc in tool_calls:
                        tool_name = tc.get("tool", "") if isinstance(tc, dict) else ""
                        if tool_name and tool_name not in seen_tools:
                            seen_tools.add(tool_name)
                            unique_tools.append(tool_name)
                    if unique_tools:
                        parts.append(f"tools:{','.join(unique_tools[:10])}")
                else:
                    # Fallback to count if tool_calls not available
                    tools_count = outcome.get("tools_executed", 0)
                    if tools_count:
                        parts.append(f"tools:{tools_count}")
                
                if t_ms:
                    parts.append(f"{t_ms}ms")
            if parts:
                reasoning = " | ".join(parts)

        embedding_blob = None
        emb = self._safe_get_embedding(searchable)
        if emb:
            embedding_blob = self._serialize_embedding(emb)

        # Postgres generated tsvector feeder (mirrors the fts_episodes fields)
        fts_text = " ".join(str(x) for x in [user_input, response_summary[:500], skill] if x)

        xref_keys = set()
        if entities_raw:
            resolved_ids = []
            try:
                resolved_ids = self.entity_registry.auto_register_entities(
                    entity_names=list(entities_raw), skill_name=skill
                )
            except Exception as reg_err:
                logger.warning("auto_register_entities (episode) failed: %s", reg_err)
            for nid in resolved_ids:
                xref_keys.add(nid.lower().strip())
            try:
                for tm in self.entity_registry._resolve_by_taxonomy(
                    user_input or response_summary or ""
                ):
                    xref_keys.add(tm["node_id"])
            except Exception:
                pass

        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                if self._kbackend == "postgres":
                    _vals = ", ".join([self._ph] * 12)
                    cur.execute(f"""
                        INSERT INTO episode_vectors
                            (id, file_path, session_id, user_input, summary, embedding,
                             ts, skill, trace_id, entities, reasoning, fts_text)
                        VALUES ({_vals})
                        ON CONFLICT (id) DO UPDATE SET
                            file_path  = excluded.file_path,
                            session_id = excluded.session_id,
                            user_input = excluded.user_input,
                            summary    = excluded.summary,
                            embedding  = excluded.embedding,
                            ts         = excluded.ts,
                            skill      = excluded.skill,
                            trace_id   = excluded.trace_id,
                            entities   = excluded.entities,
                            reasoning  = excluded.reasoning,
                            fts_text   = excluded.fts_text
                    """, (ep_id, file_path, session_id, user_input, response_summary[:500],
                          embedding_blob, ts, skill, trace_id, entities_json, reasoning, fts_text))
                else:
                    cur.execute("""
                        INSERT INTO episode_vectors
                            (id, file_path, session_id, user_input, summary, embedding,
                             ts, skill, trace_id, entities, reasoning)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            file_path  = excluded.file_path,
                            session_id = excluded.session_id,
                            user_input = excluded.user_input,
                            summary    = excluded.summary,
                            embedding  = excluded.embedding,
                            ts         = excluded.ts,
                            skill      = excluded.skill,
                            trace_id   = excluded.trace_id,
                            entities   = excluded.entities,
                            reasoning  = excluded.reasoning
                    """, (ep_id, file_path, session_id, user_input, response_summary[:500],
                          embedding_blob, ts, skill, trace_id, entities_json, reasoning))

                # ── Entity xref for episode entities (resolved pre-transaction) ──
                if xref_keys:
                    if self._kbackend == "postgres":
                        for xk in xref_keys:
                            cur.execute(f"""
                                INSERT INTO entity_xref (entity, record_id, record_type)
                                VALUES ({self._ph}, {self._ph}, 'episode')
                                ON CONFLICT DO NOTHING
                            """, (xk, ep_id))
                    else:
                        for xk in xref_keys:
                            cur.execute("""
                                INSERT OR IGNORE INTO entity_xref (entity, record_id, record_type)
                                VALUES (?, ?, 'episode')
                            """, (xk, ep_id))

                # ── Upsert FTS5 (episodes) ── SQLite only (PG uses generated search_tsv)
                if self._kbackend != "postgres":
                    cur.execute("DELETE FROM fts_episodes WHERE id = ?", (ep_id,))
                    cur.execute("""
                        INSERT INTO fts_episodes (id, user_input, summary, skill)
                        VALUES (?, ?, ?, ?)
                    """, (ep_id, user_input, response_summary[:500], skill))

                conn.commit()

            if emb:
                try:
                    self._vector_backend.upsert("episodes", ep_id, emb)
                except Exception as ve:
                    logger.warning("VectorBackend.upsert(episodes) failed for %s: %s",
                                   ep_id, ve)

            return True

        except Exception as e:
            logger.warning("KnowledgeIndexer.upsert_episode failed: %s", e)
            if self._kbackend != "postgres" and self._db:
                self._db.rollback()
            return False

    def update_episode_reasoning(
        self,
        episode: Dict,
        reasoning: Optional[str] = None,
        entities: Optional[List[str]] = None,
    ) -> bool:
        """
        Update an existing episode's reasoning and entities after LLM extraction.
        
        Called as a second pass after upsert_episode — the initial upsert stores
        auto-extracted fallback values; this overwrites with LLM-quality data.
        
        PRESERVES: The `tools:` metadata from auto-extraction is appended to
        LLM reasoning to enable procedural pattern retrieval.
        
        Args:
            episode: The same episode dict passed to upsert_episode (for ID generation).
            reasoning: LLM-extracted reasoning string.
            entities: LLM-extracted entity list.
        """
        if self._db is None and self._kbackend != "postgres":
            return False

        user_input = episode.get("user_input", "")
        ts = episode.get("timestamp", "")
        session_id = episode.get("session_id", "")
        ep_id = f"ep_{hashlib.sha256(f'{ts}|{session_id}|{user_input}'.encode()).hexdigest()[:12]}"
        
        entities_json = json.dumps(entities) if entities else None
        
        xref_keys = set()
        if entities:
            _skill = episode.get("skill", "")
            resolved_ids = []
            try:
                resolved_ids = self.entity_registry.auto_register_entities(
                    entity_names=entities, skill_name=_skill
                )
            except Exception as reg_err:
                logger.warning("auto_register_entities failed (non-fatal): %s", reg_err)
            for nid in resolved_ids:
                xref_keys.add(nid.lower().strip())
            try:
                for tm in self.entity_registry._resolve_by_taxonomy(user_input or reasoning or ""):
                    xref_keys.add(tm["node_id"])
            except Exception:
                pass

        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                # Preserve tool metadata from auto-extracted reasoning
                # Format: "routed:X | outcome:Y | tools:shell,query_memory | Nms"
                tools_suffix = ""
                cur.execute(f"SELECT reasoning FROM episode_vectors WHERE id = {self._ph}", (ep_id,))
                row = cur.fetchone()
                if row and row[0]:
                    old_reasoning = row[0]
                    # Extract tools: and timing metadata to preserve
                    for part in old_reasoning.split(" | "):
                        part = part.strip()
                        if part.startswith("tools:") or part.endswith("ms"):
                            tools_suffix += f" | {part}"

                # Combine LLM reasoning with preserved tool metadata
                if reasoning and tools_suffix:
                    reasoning = reasoning.rstrip() + tools_suffix

                # Update reasoning + entities (overwrite auto-extracted values)
                cur.execute(f"""
                    UPDATE episode_vectors
                    SET reasoning = COALESCE({self._ph}, reasoning),
                        entities  = COALESCE({self._ph}, entities)
                    WHERE id = {self._ph}
                """, (reasoning, entities_json, ep_id))

                # Update entity_xref with LLM-extracted entities (resolved pre-transaction).
                # Refresh xrefs whenever new entities were extracted, even if none resolved.
                if entities:
                    cur.execute(
                        f"DELETE FROM entity_xref WHERE record_id = {self._ph} AND record_type = 'episode'",
                        (ep_id,))
                    if self._kbackend == "postgres":
                        for xk in xref_keys:
                            cur.execute(f"""
                                INSERT INTO entity_xref (entity, record_id, record_type)
                                VALUES ({self._ph}, {self._ph}, 'episode')
                                ON CONFLICT DO NOTHING
                            """, (xk, ep_id))
                    else:
                        for xk in xref_keys:
                            cur.execute("""
                                INSERT OR IGNORE INTO entity_xref (entity, record_id, record_type)
                                VALUES (?, ?, 'episode')
                            """, (xk, ep_id))

                conn.commit()
            return True
        except Exception as e:
            logger.warning("update_episode_reasoning failed: %s", e)
            if self._kbackend != "postgres" and self._db:
                self._db.rollback()
            return False

    def search_episodes(
        self,
        query: str,
        top_k: int = 5,
        skill: Optional[str] = None,
        min_score: Optional[float] = None,
        _precomputed_embedding: Optional[List[float]] = None,
    ) -> List[Dict]:
        """
        Semantic search over indexed episodes.

        Strategy:
          1. If embedding function available → cosine similarity scan.
          2. If no embeddings → FTS5 keyword fallback.

        Args:
            _precomputed_embedding: Optional pre-computed query embedding to avoid
                                    duplicate API calls. When provided, skips _safe_get_embedding.

        Returns list of dicts sorted by descending score:
          [{"id", "user_input", "summary", "skill", "ts", "score", "file_path", "match_method"}]
        """
        threshold = min_score if min_score is not None else self.COSINE_MIN_SCORE

        # Try semantic search first (reuse cached embedding if provided)
        query_emb = _precomputed_embedding or self._safe_get_embedding(query)
        if query_emb:
            return self._search_episodes_by_embedding(query_emb, top_k, skill, threshold)

        # Fallback: FTS5 keyword search
        return self._search_episodes_by_fts(query, top_k, skill)

    def _search_episodes_by_embedding(
        self,
        query_emb: List[float],
        top_k: int,
        skill: Optional[str],
        min_score: float,
    ) -> List[Dict]:
        """Vector similarity search over episode records.

        Strategy (same as _search_by_embedding for knowledge):
          1. Pre-filter candidate IDs by skill using B-tree index.
          2. Delegate vector similarity to VectorBackend.
          3. Enrich top-K results with full metadata from SQL.
        """
        # Step 1: Pre-filter by skill
        candidate_ids = None
        if skill:
            candidate_ids = self._get_candidate_ids(
                "episodes", skill=skill
            )
            if candidate_ids is not None and not candidate_ids:
                return []

        # Step 2: Vector similarity search via backend
        id_scores = self._vector_backend.search(
            collection="episodes",
            query_embedding=query_emb,
            top_k=top_k,
            min_score=min_score,
            candidate_ids=candidate_ids,
        )

        # Step 3: Enrich with full metadata from SQLite
        scored = []
        for record_id, score in id_scores:
            result = self._build_episode_search_result(record_id, score)
            if result:
                scored.append(result)

        # Sort by score desc; when scores are within 0.05, prefer newest first
        scored.sort(
            key=lambda x: (round(x["score"] / 0.05) * 0.05, x.get("ts", "")),
            reverse=True,
        )
        return scored[:top_k]

    def _build_episode_search_result(
        self, record_id: str, score: float
    ) -> Optional[Dict]:
        """Fetch full metadata for an episode record and build result dict."""
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT id, file_path, session_id, user_input, summary,
                       ts, skill, trace_id, entities, reasoning
                FROM episode_vectors WHERE id = {self._ph}
            """, (record_id,))
            row = cur.fetchone()
        if not row:
            return None

        (eid, fpath, sid, uinput, summary, ts, sk,
         trace_id, entities_json, reasoning) = row
        return {
            "id": eid,
            "user_input": uinput or "",
            "summary": summary or "",
            "skill": sk or "",
            "ts": ts,
            "file_path": fpath or "",
            "session_id": sid or "",
            "score": round(score, 4),
            "match_method": "semantic",
            "trace_id": trace_id or "",
            "entities": json.loads(entities_json) if entities_json else [],
            "reasoning": reasoning or "",
        }

    def _search_episodes_by_fts(
        self,
        query: str,
        top_k: int,
        skill: Optional[str],
    ) -> List[Dict]:
        """FTS5 keyword search as fallback for episodes."""
        fts_query = self._sanitize_fts_query(query)
        if not fts_query:
            return []

        with self._scoped_connect() as conn:
            cur = conn.cursor()
            try:
                if self._kbackend == "postgres":
                    # Postgres: generated tsvector on episode_vectors (no fts_episodes table).
                    # websearch_to_tsquery accepts raw user text safely; ts_rank_cd is positive.
                    cur.execute(f"""
                        SELECT id, user_input, summary, skill,
                               ts_rank_cd(search_tsv, websearch_to_tsquery('english', {self._ph})) AS rank
                        FROM episode_vectors
                        WHERE search_tsv @@ websearch_to_tsquery('english', {self._ph})
                        ORDER BY rank DESC
                        LIMIT {self._ph}
                    """, (query, query, top_k * 3))
                else:
                    cur.execute("""
                        SELECT f.id, f.user_input, f.summary, f.skill, rank
                        FROM fts_episodes f
                        WHERE fts_episodes MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (fts_query, top_k * 3))
                fts_rows = cur.fetchall()
            except Exception as e:
                logger.warning("Episode FTS search failed: %s", e)
                return []

            results = []
            for (fts_id, uinput, summary, sk, fts_rank) in fts_rows:
                # Apply skill filter with same global-skill logic
                if skill and sk and sk != skill:
                    continue

                # Look up full record from episode_vectors for file_path/ts + new fields
                cur.execute(
                    f"SELECT file_path, session_id, ts, trace_id, entities, reasoning FROM episode_vectors WHERE id = {self._ph}",
                    (fts_id,)
                )
                ev_row = cur.fetchone()
                fpath = ev_row[0] if ev_row else ""
                sid = ev_row[1] if ev_row else ""
                ts = ev_row[2] if ev_row else ""
                _trace_id = ev_row[3] if ev_row else ""
                _entities_json = ev_row[4] if ev_row else None
                _reasoning = ev_row[5] if ev_row else ""

                # PG ts_rank_cd is positive (higher=better); SQLite bm25 rank is negative.
                score = (round(float(fts_rank), 4) if self._kbackend == "postgres"
                         else round(1.0 / (1.0 + abs(fts_rank)), 4))
                results.append({
                    "id": fts_id,
                    "user_input": uinput or "",
                    "summary": summary or "",
                    "skill": sk or "",
                    "ts": ts,
                    "file_path": fpath,
                    "session_id": sid,
                    "score": score,
                    "match_method": "fts",
                    "trace_id": _trace_id or "",
                    "entities": json.loads(_entities_json) if _entities_json else [],
                    "reasoning": _reasoning or "",
                })

                if len(results) >= top_k:
                    break

            return results

    def reindex_episodes(
        self,
        history_path: Path,
        batch_size: int = 50,
        progress_fn: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, int]:
        """
        Rebuild episode index by walking all JSONL files under history_path.

        Directory structure: history_path/{date}/{session_id}.jsonl

        Returns:
            {"total": N, "indexed": M, "skipped": S, "errors": E}
        """
        stats = {"total": 0, "indexed": 0, "skipped": 0, "errors": 0}

        if not history_path.exists():
            return stats

        jsonl_files = sorted(history_path.glob("**/*.jsonl"))
        if not jsonl_files:
            return stats

        # Non-destructive: snapshot existing ids, upsert in place, then delete
        # only stale ones. Keeps the episode index queryable during a reindex.
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id FROM episode_vectors")
                existing_ep_ids = {row[0] for row in cur.fetchall()}
        except Exception as e:
            logger.warning("reindex_episodes: could not read existing ids: %s", e)
            existing_ep_ids = set()

        episodes = []
        for jsonl_file in jsonl_files:
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        stats["total"] += 1
                        try:
                            episode = json.loads(line)
                            episode["_source_file"] = str(jsonl_file)
                            episodes.append(episode)
                        except json.JSONDecodeError:
                            stats["errors"] += 1
            except Exception as e:
                logger.warning("Failed to read %s: %s", jsonl_file, e)
                stats["errors"] += 1

        # Index each episode (in place) and track which ids are still current
        new_ep_ids: Set[str] = set()
        for i, episode in enumerate(episodes):
            user_input = episode.get("user_input", "")
            if user_input:
                ts = episode.get("timestamp", datetime.now().isoformat())
                session_id = episode.get("session_id", "")
                input_hash = hashlib.sha256(
                    f"{ts}|{session_id}|{user_input}".encode()
                ).hexdigest()[:12]
                new_ep_ids.add(f"ep_{input_hash}")

            ok = self.upsert_episode(episode, file_path=episode.get("_source_file", ""))
            if ok:
                stats["indexed"] += 1
            else:
                stats["skipped"] += 1

            if progress_fn and (i + 1) % batch_size == 0:
                progress_fn(i + 1, len(episodes))

        stale_ep_ids = existing_ep_ids - new_ep_ids
        if stale_ep_ids:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                for rid in stale_ep_ids:
                    try:
                        cur.execute(f"DELETE FROM episode_vectors WHERE id = {self._ph}", (rid,))
                        if self._kbackend != "postgres":
                            cur.execute("DELETE FROM fts_episodes WHERE id = ?", (rid,))
                        try:
                            self._vector_backend.delete("episodes", rid)
                        except Exception:
                            pass
                    except Exception as e:
                        logger.warning("reindex_episodes: stale delete failed for %s: %s", rid, e)
                conn.commit()
            stats["deleted"] = len(stale_ep_ids)

        if progress_fn:
            progress_fn(len(episodes), len(episodes))

        self._checkpoint()

        return stats


    def reindex_all(
        self,
        knowledge_jsonl_path: Path,
        batch_size: int = 50,
        progress_fn: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, int]:
        """
        Rebuild the entire index from the knowledge JSONL file.

        Reads all records, deduplicates by ID (last-write-wins),
        then upserts each into the index.

        Args:
            knowledge_jsonl_path: Path to knowledge.jsonl
            batch_size: Commit every N records (for progress reporting)
            progress_fn: Optional callback(indexed_count, total_count)

        Returns:
            {"total": N, "indexed": M, "skipped": S, "errors": E}
        """
        stats = {"total": 0, "indexed": 0, "skipped": 0, "errors": 0}

        if not knowledge_jsonl_path.exists():
            return stats

        # Phase 1: Read all records, deduplicate by ID (last-write-wins)
        records_by_id: Dict[str, Dict] = {}
        try:
            with open(knowledge_jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    stats["total"] += 1
                    try:
                        record = json.loads(line)
                        rid = record.get("id")
                        if rid:
                            record["_source_file"] = str(knowledge_jsonl_path)
                            records_by_id[rid] = record
                    except json.JSONDecodeError:
                        stats["errors"] += 1
        except Exception as e:
            logger.warning("KnowledgeIndexer.reindex_all: read error: %s", e)
            return stats

        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id FROM knowledge_vectors")
                existing_ids = {row[0] for row in cur.fetchall()}
        except Exception as e:
            logger.warning("KnowledgeIndexer.reindex_all: could not read existing ids: %s", e)
            existing_ids = set()

        new_ids = set(records_by_id.keys())

        # Phase 3: Upsert each unique record (in place — no empty window)
        unique_records = list(records_by_id.values())
        for i, record in enumerate(unique_records):
            ok = self.upsert_knowledge(record)
            if ok:
                stats["indexed"] += 1
            else:
                stats["skipped"] += 1

            if progress_fn and (i + 1) % batch_size == 0:
                progress_fn(i + 1, len(unique_records))

        # Phase 4: Delete only stale records (present in index, gone from JSONL)
        stale_ids = existing_ids - new_ids
        if stale_ids:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                for rid in stale_ids:
                    try:
                        cur.execute(f"DELETE FROM knowledge_vectors WHERE id = {self._ph}", (rid,))
                        if self._kbackend != "postgres":
                            cur.execute("DELETE FROM fts_knowledge WHERE id = ?", (rid,))
                        cur.execute(
                            f"DELETE FROM entity_xref WHERE record_id = {self._ph} AND record_type = 'knowledge'",
                            (rid,),
                        )
                        try:
                            self._vector_backend.delete("knowledge", rid)
                        except Exception:
                            pass
                    except Exception as e:
                        logger.warning("reindex_all: stale delete failed for %s: %s", rid, e)
                conn.commit()
            stats["deleted"] = len(stale_ids)

        if progress_fn:
            progress_fn(len(unique_records), len(unique_records))

        self._checkpoint()

        return stats


    def get_record_by_id(self, record_id: str) -> Optional[Dict]:
        """
        Fetch a single knowledge record by ID.
        Returns the full record dict or None if not found.
        """
        if not record_id:
            return None
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT id, summary, knowledge_type, skill, status, source,
                       applies_when, ts, entities_json, tags_json, source_file,
                       raw_json
                FROM knowledge_vectors WHERE id = {self._ph}
            """, (record_id,))
            row = cur.fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def query_records(
        self,
        status: Optional[str] = "confirmed",
        knowledge_type: Optional[str] = None,
        skill: Optional[str] = None,
        tag: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> Dict:
        """
        Structured query over knowledge records using B-tree indexes.
        Returns same shape as AgentMemory.query_knowledge() for drop-in use.
        """
        safe_limit = max(1, limit)
        safe_offset = max(0, offset)
        empty_result = {"items": [], "total": 0, "offset": safe_offset, "limit": safe_limit}

        conditions: List[str] = []
        params: List[Any] = []

        if not include_archived:
            conditions.append("status != 'archived'")

        if status and status != "all":
            conditions.append(f"status = {self._ph}")
            params.append(status)

        if knowledge_type:
            conditions.append(f"knowledge_type = {self._ph}")
            params.append(knowledge_type)

        if skill:
            conditions.append(f"(skill = {self._ph} OR skill IS NULL OR skill = '')")
            params.append(skill)

        if source:
            conditions.append(f"source = {self._ph}")
            params.append(source)

        where = _sql_where(conditions)

        # Fetch paginated rows (over-fetch slightly if tag filter needed)
        fetch_limit = safe_limit * 3 if tag else safe_limit
        fetch_offset = safe_offset if not tag else 0
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM knowledge_vectors {where}", params)
            total_before_tag = cur.fetchone()[0]
            cur.execute(f"""
                SELECT id, summary, knowledge_type, skill, status, source,
                       applies_when, ts, entities_json, tags_json, source_file,
                       raw_json, written_to
                FROM knowledge_vectors
                {where}
                ORDER BY ts DESC
                LIMIT {self._ph} OFFSET {self._ph}
            """, params + [fetch_limit, fetch_offset])
            rows = cur.fetchall()

        items = []
        skipped = 0
        for row in rows:
            record = self._row_to_record(row)

            # Tag post-filter (tags stored as JSON, can't efficiently index)
            if tag:
                tags = record.get("scope", {}).get("tags", [])
                if tag.lower() not in [t.lower() for t in tags]:
                    continue
                skipped_before_page = skipped
                if skipped < safe_offset:
                    skipped += 1
                    continue

            items.append(record)
            if len(items) >= safe_limit:
                break

        # For tag-filtered queries, total is approximate
        total = total_before_tag if not tag else total_before_tag

        return {"items": items, "total": total, "offset": safe_offset, "limit": safe_limit}

    def get_summaries_by_status(self, statuses: List[str]) -> List[str]:
        """
        Fetch summaries for records matching any of the given statuses.
        Used for dedup checking during knowledge extraction.
        """
        if not statuses:
            return []
        in_clause = _sql_in_clause(len(statuses), self._ph)
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT summary FROM knowledge_vectors
                WHERE status IN {in_clause} AND summary IS NOT NULL
            """, list(statuses))
            return [row[0] for row in cur.fetchall()]

    def get_records_for_dedup(
        self,
        status: Optional[str] = "all",
        max_records: int = 200,
    ) -> List[Dict]:
        """
        Fetch records for duplicate detection (excludes archived).
        Returns list of record dicts with id, summary, status, type, skill.
        """
        conditions = ["status != 'archived'"]
        params: List[Any] = []

        if status and status != "all":
            conditions.append(f"status = {self._ph}")
            params.append(status)

        where = _sql_where(conditions)
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT id, summary, knowledge_type, skill, status, source,
                       applies_when, ts, entities_json, tags_json, source_file,
                       raw_json
                FROM knowledge_vectors
                {where}
                ORDER BY ts DESC
                LIMIT {self._ph}
            """, params + [max_records])
            return [self._row_to_record(row) for row in cur.fetchall()]

    def _row_to_record(self, row: tuple) -> Dict:
        """Convert a knowledge_vectors row tuple to the standard record dict shape.

        Supports 11-col (legacy), 12-col (with raw_json), and 13-col (with written_to) shapes.
        When raw_json is available, returns the full original record with all
        fields (provenance, lifecycle, user_query, confidence, etc.).
        written_to is always taken from the DB column (not raw_json) as it is set post-confirm.
        """
        # written_to is always the last column (index 12) when present
        written_to = row[12] if len(row) >= 13 else None

        # New path: raw_json column present and populated → full record
        if len(row) >= 12 and row[11]:
            try:
                record = json.loads(row[11])
                record.setdefault("type", record.get("knowledge_type", "unknown"))
                record.setdefault("status", "unknown")
                record.setdefault("source", "unknown")
                record.setdefault("ts", "")
                if "scope" not in record:
                    record["scope"] = {}
                record["scope"].setdefault("skill", "")
                record["scope"].setdefault("tags", [])
                record["scope"].setdefault("applies_when", "")
                record["scope"].setdefault("recommended_tools", [])
                record.setdefault("entity_keys", record.get("entities", []))
                record.setdefault("provenance", {})
                record.setdefault("lifecycle", {})
                # Always use DB column for written_to (set after confirm, not in raw_json)
                if written_to:
                    record["written_to"] = written_to
                return record
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: column-based reconstruction (legacy DBs without raw_json)
        (rid, summary, ktype, skill, status, source,
         applies_when, ts, ent_json, tags_json, source_file) = row[:11]

        entities = json.loads(ent_json) if ent_json else []
        tags = json.loads(tags_json) if tags_json else []

        return {
            "id": rid,
            "type": ktype or "unknown",
            "summary": summary or f"[{ktype or 'unknown'} record — no summary]",
            "status": status or "unknown",
            "source": source or "unknown",
            "ts": ts or "",
            "scope": {
                "skill": skill or "",
                "tags": tags,
                "applies_when": applies_when or "",
                "recommended_tools": [],
            },
            "entity_keys": entities,
            "provenance": {},
            "lifecycle": {},
        }


    def get_stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        with self._scoped_connect() as conn:
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM knowledge_vectors")
            total_knowledge = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM knowledge_vectors WHERE embedding IS NOT NULL")
            with_embeddings = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM episode_vectors")
            total_episodes = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT entity) FROM entity_xref")
            unique_entities = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM entity_xref")
            total_xrefs = cur.fetchone()[0]

            cur.execute("SELECT status, COUNT(*) FROM knowledge_vectors GROUP BY status")
            status_counts = dict(cur.fetchall())

            cur.execute("SELECT knowledge_type, COUNT(*) FROM knowledge_vectors GROUP BY knowledge_type")
            type_counts = dict(cur.fetchall())

            cur.execute("SELECT source, COUNT(*) FROM knowledge_vectors WHERE source IS NOT NULL GROUP BY source")
            source_counts = dict(cur.fetchall())

            if self._kbackend == "postgres":
                try:
                    cur.execute(
                        "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        f"WHERE n.nspname = {self._ph} AND c.relkind IN ('r', 'm')",
                        (self._pg_schema,),
                    )
                    storage_size_bytes = int(cur.fetchone()[0] or 0)
                except Exception as e:
                    logger.warning("get_stats: postgres schema size query failed: %s", e)
                    storage_size_bytes = 0
            else:
                storage_size_bytes = 0
                for suffix in ("", "-wal", "-shm"):
                    sidecar = Path(f"{self.db_path}{suffix}")
                    if sidecar.exists():
                        storage_size_bytes += sidecar.stat().st_size

        return {
            "knowledge_records": total_knowledge,
            "with_embeddings": with_embeddings,
            "without_embeddings": total_knowledge - with_embeddings,
            "episode_records": total_episodes,
            "unique_entities": unique_entities,
            "entity_xrefs": total_xrefs,
            "by_status": status_counts,
            "by_type": type_counts,
            "by_source": source_counts,
            "db_path": str(self.db_path),
            "storage_size_bytes": storage_size_bytes,
            "has_embedding_fn": self._get_embedding is not None,
        }

    def record_count(self) -> int:
        """Quick count of indexed knowledge records."""
        with self._scoped_connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM knowledge_vectors")
            return cur.fetchone()[0]


    def upsert_plan_cache(self, plan_id: str, goal: str, plan_steps: list,
                           execution_mode: str = "react",
                           detected_domains: list = None,
                           entity_types: list = None,
                           process_nodes: list = None,
                           critique_json: dict = None,
                           session_id: str = None,
                           tenant_id: str = None,
                           agent_id: str = None,
                           executed_at: str = None,
                           embedding: list = None,
                           context_hints: str = None) -> bool:
        """
        Insert a successful query pattern into plan_cache with two-layer dedup:
        Layer 1 — structural fingerprint (same step structure)
        Layer 2 — embedding cosine similarity >= 0.90 (same intent, different words)
        If match found: bump use_count on existing row, skip insert.
        If no match: insert as pending_review.
        """
        import json as _json
        from datetime import datetime as _dt
        try:
            fingerprint = self._plan_fingerprint(plan_steps)
            now = _dt.now().isoformat()
            with self._scoped_connect() as conn:
                cur = conn.cursor()

                # Layer 1: fingerprint match
                row = cur.execute(
                    f"SELECT plan_id, status FROM plan_cache WHERE fingerprint = {self._ph}",
                    (fingerprint,)
                ).fetchone()
                if row:
                    cur.execute(
                        f"UPDATE plan_cache SET use_count=use_count+1, last_used_at={self._ph} WHERE fingerprint={self._ph}",
                        (now, fingerprint)
                    )
                    conn.commit()
                    logger.info("plan_cache: fingerprint match for '%s', bumped use_count", goal[:60])
                    return False  # not a new entry

                # Layer 2: embedding similarity if embedding provided
                if embedding:
                    import struct as _struct
                    emb_blob = _struct.pack(f"{len(embedding)}f", *embedding)
                    existing = cur.execute(
                        "SELECT plan_id, embedding FROM plan_cache WHERE status != 'rejected' AND embedding IS NOT NULL"
                    ).fetchall()
                    for ex_row in existing:
                        ex_emb_blob = ex_row[1]
                        if not ex_emb_blob:
                            continue
                        ex_emb_bytes = bytes(ex_emb_blob)  # memoryview (PG) → bytes
                        n = len(ex_emb_bytes) // 4
                        ex_emb = list(_struct.unpack(f"{n}f", ex_emb_bytes))
                        # cosine similarity
                        dot = sum(a * b for a, b in zip(embedding, ex_emb))
                        mag_a = sum(a * a for a in embedding) ** 0.5
                        mag_b = sum(b * b for b in ex_emb) ** 0.5
                        score = dot / (mag_a * mag_b) if mag_a and mag_b else 0.0
                        if score >= 0.90:
                            cur.execute(
                                f"UPDATE plan_cache SET use_count=use_count+1, last_used_at={self._ph} WHERE plan_id={self._ph}",
                                (now, ex_row[0])
                            )
                            conn.commit()
                            logger.info("plan_cache: embedding match (%.2f) for '%s', bumped use_count", score, goal[:60])
                            return False

                # New entry
                emb_blob = None
                if embedding:
                    import struct as _struct
                    emb_blob = _struct.pack(f"{len(embedding)}f", *embedding)

                # Ensure context_hints column exists (SQLite migration for old DBs; the PG
                # schema already defines it, and a failed ALTER would abort the PG transaction).
                if self._kbackend != "postgres":
                    try:
                        cur.execute("ALTER TABLE plan_cache ADD COLUMN context_hints TEXT DEFAULT '[]'")
                        conn.commit()
                    except Exception:
                        pass  # column already exists

                _vals = ",".join([self._ph] * 16) + ",1," + self._ph
                cur.execute(f"""
                    INSERT INTO plan_cache
                      (plan_id, goal, embedding, fingerprint, detected_domains, entity_types,
                       process_nodes, plan_steps, critique_json, execution_mode, status,
                       session_id, tenant_id, agent_id, created_at, executed_at, use_count,
                       context_hints)
                    VALUES ({_vals})
                """, (
                    plan_id,
                    goal,
                    emb_blob,
                    fingerprint,
                    _json.dumps(detected_domains or []),
                    _json.dumps(entity_types or []),
                    _json.dumps(process_nodes or []),
                    _json.dumps(plan_steps),
                    _json.dumps(critique_json) if critique_json else None,
                    execution_mode,
                    "pending_review",
                    session_id,
                    tenant_id,
                    agent_id,
                    now,
                    executed_at,
                    context_hints or "[]",
                ))
                conn.commit()
                logger.info("plan_cache: new entry plan_id=%s mode=%s goal='%s'", plan_id, execution_mode, goal[:60])
                return True
        except Exception as e:
            logger.warning("plan_cache upsert failed (non-fatal): %s", e)
            return False

    def search_plan_cache(self, embedding: list = None, top_k: int = 3, min_score: float = 0.90) -> list:
        """
        Search approved plan_cache entries by embedding similarity.
        Returns list of dicts sorted by score descending.
        Only returns status='approved' entries.
        """
        import json as _json, struct as _struct
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT plan_id, goal, plan_steps, detected_domains, execution_mode, use_count, embedding, "
                    "COALESCE(context_hints, '[]') "
                    "FROM plan_cache WHERE status='approved' AND embedding IS NOT NULL"
                ).fetchall()

                if not rows or not embedding:
                    return []

                results = []
                for row in rows:
                    emb_blob = row[6]
                    if not emb_blob:
                        continue
                    emb_blob = bytes(emb_blob)  # memoryview (PG) → bytes
                    # Guard against corrupted blobs — length must be a multiple of 4
                    if len(emb_blob) % 4 != 0:
                        logger.warning("plan_cache: corrupted embedding blob for plan_id=%s (len=%d), skipping", row[0], len(emb_blob))
                        continue
                    try:
                        n = len(emb_blob) // 4
                        ex_emb = list(_struct.unpack(f"{n}f", emb_blob))
                    except _struct.error as _se:
                        logger.warning("plan_cache: failed to unpack embedding for plan_id=%s: %s", row[0], _se)
                        continue
                    dot = sum(a * b for a, b in zip(embedding, ex_emb))
                    mag_a = sum(a * a for a in embedding) ** 0.5
                    mag_b = sum(b * b for b in ex_emb) ** 0.5
                    score = dot / (mag_a * mag_b) if mag_a and mag_b else 0.0
                    if score >= min_score:
                        results.append({
                            "plan_id":          row[0],
                            "goal":             row[1],
                            "plan_steps":       _json.loads(row[2]) if row[2] else [],
                            "detected_domains": _json.loads(row[3]) if row[3] else [],
                            "execution_mode":   row[4],
                            "use_count":        row[5],
                            "score":            round(score, 3),
                            "context_hints":    _json.loads(row[7]) if row[7] else [],
                        })

                results.sort(key=lambda x: -x["score"])
                top = results[:top_k]

                # Increment use_count for every plan returned — tracks real cache hits in analytics
                if top:
                    hit_in = _sql_in_clause(len(top), self._ph)
                    cur.execute(
                        f"UPDATE plan_cache SET use_count = use_count + 1 WHERE plan_id IN {hit_in}",
                        [r["plan_id"] for r in top]
                    )
                    conn.commit()

                return top
        except Exception as e:
            logger.warning("plan_cache search failed (non-fatal): %s", e)
            return []

    def list_plan_cache(self, status: str = None, tenant_id: str = None,
                         agent_id: str = None, limit: int = 100) -> list:
        """List plan_cache entries for the dashboard."""
        import json as _json
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                conditions = []
                params = []
                if status:
                    conditions.append(f"status = {self._ph}")
                    params.append(status)
                if tenant_id:
                    conditions.append(f"tenant_id = {self._ph}")
                    params.append(tenant_id)
                if agent_id:
                    conditions.append(f"agent_id = {self._ph}")
                    params.append(agent_id)
                where = _sql_where(conditions)
                rows = cur.execute(f"""
                    SELECT plan_id, goal, detected_domains, plan_steps, critique_json,
                           execution_mode, status, use_count, created_at, approved_at,
                           approved_by, executed_at, session_id, entity_types, process_nodes,
                           COALESCE(context_hints, '[]') as context_hints
                    FROM plan_cache {where}
                    ORDER BY created_at DESC LIMIT {self._ph}
                """, params + [limit]).fetchall()

            result = []
            for r in rows:
                steps = _json.loads(r[3]) if r[3] else []
                result.append({
                    "plan_id":          r[0],
                    "goal":             r[1],
                    "detected_domains": _json.loads(r[2]) if r[2] else [],
                    "plan_steps":       steps,
                    "step_count":       len(steps),
                    "critique":         _json.loads(r[4]) if r[4] else None,
                    "execution_mode":   r[5],
                    "status":           r[6],
                    "use_count":        r[7],
                    "created_at":       r[8],
                    "approved_at":      r[9],
                    "approved_by":      r[10],
                    "executed_at":      r[11],
                    "session_id":       r[12],
                    "entity_types":     _json.loads(r[13]) if r[13] else [],
                    "process_nodes":    _json.loads(r[14]) if r[14] else [],
                    "context_hints":    _json.loads(r[15]) if r[15] else [],
                })
            return result
        except Exception as e:
            logger.warning("list_plan_cache failed: %s", e)
            return []

    def update_plan_cache_status(self, plan_id: str, status: str, approved_by: str = None) -> bool:
        """Approve or reject a plan cache entry."""
        from datetime import datetime as _dt
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                now = _dt.now().isoformat()
                cur.execute(
                    f"UPDATE plan_cache SET status={self._ph}, approved_at={self._ph}, approved_by={self._ph} WHERE plan_id={self._ph}",
                    (status, now if status == "approved" else None, approved_by, plan_id)
                )
                rc = cur.rowcount
                conn.commit()
                logger.info("plan_cache: plan_id=%s status→%s by=%s", plan_id, status, approved_by)
                return rc > 0
        except Exception as e:
            logger.warning("update_plan_cache_status failed: %s", e)
            return False

    def edit_plan_cache(self, plan_id: str, goal: str, plan_steps: list,
                        execution_mode: str = None, detected_domains: list = None,
                        context_hints: list = None) -> bool:
        """Direct UPDATE of plan_cache fields — bypasses dedup, used by dashboard edit."""
        import json as _json
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                fingerprint = self._plan_fingerprint(plan_steps)
                sets = [f"goal={self._ph}", f"plan_steps={self._ph}", f"fingerprint={self._ph}"]
                params = [goal, _json.dumps(plan_steps), fingerprint]
                if execution_mode is not None:
                    sets.append(f"execution_mode={self._ph}"); params.append(execution_mode)
                if detected_domains is not None:
                    sets.append(f"detected_domains={self._ph}"); params.append(_json.dumps(detected_domains))
                if context_hints is not None:
                    sets.append(f"context_hints={self._ph}"); params.append(_json.dumps(context_hints))
                params.append(plan_id)
                set_clause = _sql_set_clause(sets)
                cur.execute(f"UPDATE plan_cache SET {set_clause} WHERE plan_id={self._ph}", params)
                rc = cur.rowcount
                conn.commit()
                return rc > 0
        except Exception as e:
            logger.warning("edit_plan_cache failed: %s", e)
            return False

    def insert_plan_cache(self, plan_id: str, goal: str, plan_steps: list,
                          execution_mode: str = "planned", detected_domains: list = None,
                          tenant_id: str = None, agent_id: str = None) -> bool:
        """Direct INSERT into plan_cache — used for manual new entries from the dashboard."""
        import json as _json
        from datetime import datetime as _dt
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                fingerprint = self._plan_fingerprint(plan_steps)
                now = _dt.now().isoformat()
                _params = (plan_id, goal, fingerprint, _json.dumps(detected_domains or []),
                           _json.dumps(plan_steps), execution_mode, "pending_review", now,
                           tenant_id, agent_id)
                if self._kbackend == "postgres":
                    _vals = ",".join([self._ph] * 10) + ",0"
                    cur.execute(f"""
                        INSERT INTO plan_cache
                          (plan_id, goal, fingerprint, detected_domains, plan_steps, execution_mode,
                           status, created_at, tenant_id, agent_id, use_count)
                        VALUES ({_vals})
                        ON CONFLICT (plan_id) DO NOTHING
                    """, _params)
                else:
                    cur.execute("""
                        INSERT OR IGNORE INTO plan_cache
                          (plan_id, goal, fingerprint, detected_domains, plan_steps, execution_mode,
                           status, created_at, tenant_id, agent_id, use_count)
                        VALUES (?,?,?,?,?,?,?,?,?,?,0)
                    """, _params)
                rc = cur.rowcount
                conn.commit()
                return rc > 0
        except Exception as e:
            logger.warning("insert_plan_cache failed: %s", e)
            return False

    def get_plan_cache_stats(self, tenant_id: str = None, agent_id: str = None) -> dict:
        """Return counts by status for the dashboard badge."""
        try:
            with self._scoped_connect() as conn:
                cur = conn.cursor()
                conditions = []
                params = []
                if tenant_id:
                    conditions.append(f"tenant_id = {self._ph}")
                    params.append(tenant_id)
                if agent_id:
                    conditions.append(f"agent_id = {self._ph}")
                    params.append(agent_id)
                where = _sql_where(conditions)
                rows = cur.execute(
                    f"SELECT status, COUNT(*) FROM plan_cache {where} GROUP BY status", params
                ).fetchall()
            counts = {r[0]: r[1] for r in rows}
            return {
                "pending_review": counts.get("pending_review", 0),
                "approved":       counts.get("approved", 0),
                "rejected":       counts.get("rejected", 0),
                "total":          sum(counts.values()),
            }
        except Exception as e:
            logger.warning("get_plan_cache_stats failed: %s", e)
            return {"pending_review": 0, "approved": 0, "rejected": 0, "total": 0}

    def close(self):
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    def __del__(self):
        self.close()

    def __repr__(self):
        try:
            count = self.record_count()
        except Exception:
            count = "?"
        has_emb = "✓" if self._get_embedding else "✗"
        return f"<KnowledgeIndexer records={count} embeddings={has_emb} db={self.db_path.name}>"
