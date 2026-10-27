#!/usr/bin/env python3
"""
VectorBackend — Pluggable backend for vector similarity search.

Architecture:
  KnowledgeIndexer owns SQLite metadata (knowledge_vectors, episode_vectors,
  entity_xref, FTS5). VectorBackend ONLY handles the embedding store + ANN search.
  This clean separation means swapping the vector engine requires ZERO changes
  to metadata, FTS5, entity xref, or any business logic.

Implementations:
  - BruteForceBackend:  Pure Python cosine over in-memory dict.
                        Zero dependencies, exact results. Default.
  - SqliteVecBackend:   sqlite-vec extension for in-DB ANN search.
                        10-50x faster at scale. pip install sqlite-vec.
  - PgVectorBackend:    PostgreSQL + pgvector for multi-node / HA deployments.
                        Requires DB_BACKEND=postgres and pgvector installed.

Selection via environment variable:
  VECTOR_BACKEND=brute_force   (default)
  VECTOR_BACKEND=sqlite_vec
  VECTOR_BACKEND=pgvector

Collections:
  Each backend manages two collections: "knowledge" and "episodes".
  These map 1:1 to the KnowledgeIndexer tables of the same name.
"""
import logging
import struct
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)



class VectorBackend(ABC):
    """Abstract interface for vector similarity search backends.

    All implementations must:
      - Support two collections: "knowledge" and "episodes"
      - Accept embeddings as List[float]
      - Return search results as [(record_id, score)] sorted by score desc
      - Be safe for concurrent reads (writes may serialize via caller's lock)
    """

    @abstractmethod
    def upsert(self, collection: str, record_id: str,
               embedding: List[float]) -> None:
        """Store or update a vector in the given collection.

        Args:
            collection: "knowledge" or "episodes"
            record_id: Unique string ID (e.g., knowledge UUID or ep_hash)
            embedding: Float list of dimension D (typically 1536)
        """

    @abstractmethod
    def search(
        self,
        collection: str,
        query_embedding: List[float],
        top_k: int = 10,
        min_score: float = 0.0,
        candidate_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Find the top-K most similar vectors by cosine similarity.

        Args:
            collection: "knowledge" or "episodes"
            query_embedding: Query vector (same dimension as stored vectors)
            top_k: Maximum results to return
            min_score: Minimum cosine similarity threshold (0.0–1.0)
            candidate_ids: If provided, restrict search to only these IDs.
                           When None, search all vectors in the collection.

        Returns:
            List of (record_id, score) tuples, sorted by score descending.
        """

    @abstractmethod
    def delete(self, collection: str, record_id: str) -> None:
        """Remove a single vector from a collection. No-op if ID not found."""

    @abstractmethod
    def clear(self, collection: str) -> None:
        """Remove ALL vectors from a collection."""

    @abstractmethod
    def count(self, collection: str) -> int:
        """Return the number of vectors stored in a collection."""



class BruteForceBackend(VectorBackend):
    """In-memory brute-force cosine similarity search.

    This is the reference implementation — produces exact results and requires
    zero external dependencies. Suitable for small-to-medium datasets
    (< ~5K vectors). Beyond that, switch to SqliteVecBackend for performance.

    Storage: Dict[collection, Dict[record_id, List[float]]]
    Search: O(n × d) per query where n=vectors, d=dimension
    """

    def __init__(self, db_connection=None, scoped_connect=None):
        """Initialize BruteForceBackend.

        Args:
            db_connection: Optional SQLite connection. If provided, loads
                existing embeddings from knowledge_vectors/episode_vectors
                tables on first search (lazy hydration). This ensures
                backward compatibility — vectors stored as BLOBs in SQLite
                are still searchable without re-indexing.
            scoped_connect: Optional contextmanager factory (KnowledgeIndexer._scoped_connect)
                for the Postgres backend. When provided, hydration reads embeddings via a
                scoped engine connection instead of a raw sqlite3 handle. This is what makes
                vectors written by *other* processes visible in a shared multi-user store.
        """
        # collection → {record_id: embedding}
        self._store: Dict[str, Dict[str, List[float]]] = {
            "knowledge": {},
            "episodes": {},
        }
        self._db = db_connection
        self._scoped_connect = scoped_connect
        self._hydrated: Dict[str, bool] = {
            "knowledge": False,
            "episodes": False,
        }

    def _hydrate_from_db(self, collection: str) -> None:
        """Lazy-load existing embeddings from the DB BLOBs into memory.

        Called once per collection on first search. Ensures that vectors written by other
        processes (or before VectorBackend existed) are still searchable. Works on both
        SQLite (self._db) and Postgres (self._scoped_connect); psycopg returns embeddings
        as memoryview, so wrap in bytes() before struct.unpack.
        """
        if self._hydrated.get(collection):
            return
        if not self._db and not self._scoped_connect:
            return

        _ALLOWED = {"knowledge_vectors", "episode_vectors"}
        table = "knowledge_vectors" if collection == "knowledge" else "episode_vectors"
        if table not in _ALLOWED:
            return
        # `table` is validated against the _ALLOWED allowlist above, so the
        # f-string below cannot be influenced by untrusted input (SAST guard kept).
        sql = f"SELECT id, embedding FROM {table} WHERE embedding IS NOT NULL"
        try:
            if self._scoped_connect is not None:
                with self._scoped_connect() as conn:
                    cur = conn.cursor()
                    cur.execute(sql)
                    rows = cur.fetchall()
            else:
                cur = self._db.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
            for rec_id, emb_blob in rows:
                if emb_blob:
                    emb_bytes = bytes(emb_blob)  # memoryview (PG) or bytes (SQLite) → bytes
                    n = len(emb_bytes) // 4
                    emb = list(struct.unpack(f"{n}f", emb_bytes))
                    self._store[collection][rec_id] = emb
            logger.info("BruteForceBackend: hydrated %d vectors for '%s'",
                        len(rows), collection)
        except Exception as e:
            logger.warning("BruteForceBackend: hydration failed for '%s': %s",
                           collection, e)
        finally:
            self._hydrated[collection] = True

    def upsert(self, collection: str, record_id: str,
               embedding: List[float]) -> None:
        """Store or update a vector in memory."""
        if collection not in self._store:
            self._store[collection] = {}
        self._store[collection][record_id] = embedding

    def search(
        self,
        collection: str,
        query_embedding: List[float],
        top_k: int = 10,
        min_score: float = 0.0,
        candidate_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Brute-force cosine scan over all vectors in the collection."""
        # Lazy hydration from SQLite on first search
        self._hydrate_from_db(collection)

        store = self._store.get(collection, {})
        if not store or not query_embedding:
            return []

        # Pre-check: zero-vector query → undefined cosine → return empty
        norm_q = sum(x * x for x in query_embedding) ** 0.5
        if norm_q == 0.0:
            return []

        scored: List[Tuple[str, float]] = []
        for rec_id, emb in store.items():
            if candidate_ids is not None and rec_id not in candidate_ids:
                continue

            score = self._cosine_similarity(query_embedding, emb, norm_q)
            if score >= min_score:
                scored.append((rec_id, round(score, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def delete(self, collection: str, record_id: str) -> None:
        """Remove a vector from memory. No-op if not found."""
        store = self._store.get(collection, {})
        store.pop(record_id, None)

    def clear(self, collection: str) -> None:
        """Drop all vectors in a collection."""
        self._store[collection] = {}
        # Reset hydration flag so next search re-loads from DB if needed
        self._hydrated[collection] = False

    def count(self, collection: str) -> int:
        """Number of vectors in a collection (memory only, not DB)."""
        return len(self._store.get(collection, {}))

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float],
                           precomputed_norm_a: float = 0.0) -> float:
        """Pure-Python cosine similarity. Returns 0.0 on degenerate input."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = precomputed_norm_a if precomputed_norm_a > 0 else (
            sum(x * x for x in a) ** 0.5
        )
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)



class SqliteVecBackend(VectorBackend):
    """Vector search using the sqlite-vec extension (in-DB ANN).

    sqlite-vec provides virtual tables with cosine distance search,
    executing entirely within SQLite. This avoids the Python-loop bottleneck
    of BruteForceBackend and scales to 100K+ vectors.

    Requires: pip install sqlite-vec
    Docs: https://github.com/asg017/sqlite-vec

    Schema:
      - vec_id_map: Maps text record_id ↔ integer rowid (vec0 requires int PK)
      - vec_knowledge: vec0 virtual table for knowledge embeddings
      - vec_episodes:  vec0 virtual table for episode embeddings
    """

    # Default embedding dimension (text-embedding-ada-002 / text-embedding-3-small)
    DEFAULT_DIMENSION = 1536

    def __init__(self, db_connection, dimension: int = DEFAULT_DIMENSION):
        """Initialize SqliteVecBackend.

        Args:
            db_connection: An existing sqlite3.Connection (shared with KnowledgeIndexer).
            dimension: Embedding dimension. Must match the embedding model output.

        Raises:
            ImportError: If sqlite-vec is not installed.
        """
        self._db = db_connection
        self._dimension = dimension
        self._load_extension()
        self._init_tables()

    def _load_extension(self) -> None:
        """Load the sqlite-vec extension into the database connection."""
        try:
            import sqlite_vec
            self._db.enable_load_extension(True)
            sqlite_vec.load(self._db)
            self._db.enable_load_extension(False)
            logger.info("SqliteVecBackend: sqlite-vec extension loaded successfully")
        except ImportError:
            raise ImportError(
                "sqlite-vec is required for SqliteVecBackend. "
                "Install with: pip install sqlite-vec"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load sqlite-vec extension: {e}")

    def _init_tables(self) -> None:
        """Create vec0 virtual tables and the ID mapping table."""
        cur = self._db.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS vec_id_map (
                rowid       INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id   TEXT    NOT NULL,
                collection  TEXT    NOT NULL,
                UNIQUE(record_id, collection)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vim_lookup "
            "ON vec_id_map(record_id, collection)"
        )

        for coll in ("knowledge", "episodes"):
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_" + coll +
                " USING vec0(embedding float[" + str(int(self._dimension)) + "])"
            )

        self._db.commit()
        logger.info("SqliteVecBackend: tables initialized (dim=%d)", self._dimension)

    def _get_or_create_rowid(self, collection: str, record_id: str) -> int:
        """Get existing rowid or insert a new mapping. Returns integer rowid."""
        cur = self._db.cursor()
        cur.execute(
            "SELECT rowid FROM vec_id_map WHERE record_id = ? AND collection = ?",
            (record_id, collection),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute(
            "INSERT INTO vec_id_map (record_id, collection) VALUES (?, ?)",
            (record_id, collection),
        )
        return cur.lastrowid

    def _get_rowid(self, collection: str, record_id: str) -> Optional[int]:
        """Get existing rowid or None."""
        cur = self._db.cursor()
        cur.execute(
            "SELECT rowid FROM vec_id_map WHERE record_id = ? AND collection = ?",
            (record_id, collection),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def upsert(self, collection: str, record_id: str,
               embedding: List[float]) -> None:
        """Store or update a vector in the sqlite-vec index."""
        if len(embedding) != self._dimension:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self._dimension}, "
                f"got {len(embedding)}"
            )

        emb_blob = struct.pack(f"{len(embedding)}f", *embedding)
        rowid = self._get_or_create_rowid(collection, record_id)

        cur = self._db.cursor()
        table = f"vec_{collection}"

        # vec0 uses INSERT OR REPLACE with explicit rowid
        try:
            cur.execute(
                f"INSERT OR REPLACE INTO {table}(rowid, embedding) VALUES (?, ?)",
                (rowid, emb_blob),
            )
            self._db.commit()
        except Exception as e:
            logger.warning("SqliteVecBackend.upsert failed for %s/%s: %s",
                           collection, record_id, e)
            self._db.rollback()

    def search(
        self,
        collection: str,
        query_embedding: List[float],
        top_k: int = 10,
        min_score: float = 0.0,
        candidate_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Search for similar vectors using sqlite-vec's KNN query.

        sqlite-vec vec0 returns cosine DISTANCE (0 = identical, 2 = opposite).
        We convert to cosine SIMILARITY: score = 1 - (distance / 2).
        """
        if not query_embedding:
            return []

        # Zero-vector check
        if all(x == 0.0 for x in query_embedding):
            return []

        query_blob = struct.pack(f"{len(query_embedding)}f", *query_embedding)
        table = f"vec_{collection}"
        cur = self._db.cursor()

        # When candidate_ids is provided, we need to filter by rowid.
        # Strategy: resolve candidate text IDs → rowids, pass as WHERE clause.
        rowid_filter = None
        if candidate_ids is not None:
            if not candidate_ids:
                return []  # Empty candidate set → no results
            # Batch-resolve text IDs → rowids
            placeholders = ", ".join("?" for _ in candidate_ids)
            cur.execute(
                f"SELECT rowid FROM vec_id_map "
                f"WHERE record_id IN ({placeholders}) AND collection = ?",
                list(candidate_ids) + [collection],
            )
            rowid_filter = {row[0] for row in cur.fetchall()}
            if not rowid_filter:
                return []

        # sqlite-vec KNN query — fetch extra to allow post-filtering
        fetch_k = top_k * 3 if rowid_filter else top_k
        try:
            # vec0 KNN syntax: WHERE embedding MATCH ? AND k = ?
            cur.execute(
                f"SELECT rowid, distance FROM {table} "
                f"WHERE embedding MATCH ? AND k = ?",
                (query_blob, fetch_k),
            )
            rows = cur.fetchall()
        except Exception as e:
            logger.warning("SqliteVecBackend.search failed for '%s': %s",
                           collection, e)
            return []

        # Convert distance → similarity and resolve rowid → record_id
        results: List[Tuple[str, float]] = []
        for vec_rowid, distance in rows:
            if rowid_filter is not None and vec_rowid not in rowid_filter:
                continue

            # Cosine distance → cosine similarity
            # vec0 cosine distance is in [0, 2]; similarity = 1 - distance/2
            score = 1.0 - (distance / 2.0)
            if score < min_score:
                continue

            # Resolve rowid → text record_id
            cur.execute(
                "SELECT record_id FROM vec_id_map WHERE rowid = ? AND collection = ?",
                (vec_rowid, collection),
            )
            id_row = cur.fetchone()
            if not id_row:
                continue

            results.append((id_row[0], round(score, 4)))

            if len(results) >= top_k:
                break

        return results

    def delete(self, collection: str, record_id: str) -> None:
        """Remove a vector from the sqlite-vec index and ID map."""
        rowid = self._get_rowid(collection, record_id)
        if rowid is None:
            return  # Not found — no-op

        cur = self._db.cursor()
        table = "vec_" + collection
        if collection not in ("knowledge", "episodes"):
            return
        try:
            cur.execute("DELETE FROM " + table + " WHERE rowid = ?", (rowid,))
            cur.execute(
                "DELETE FROM vec_id_map WHERE rowid = ?", (rowid,)
            )
            self._db.commit()
        except Exception as e:
            logger.warning("SqliteVecBackend.delete failed for %s/%s: %s",
                           collection, record_id, e)
            self._db.rollback()

    def clear(self, collection: str) -> None:
        """Drop all vectors in a collection from vec0 + id map."""
        cur = self._db.cursor()
        table = "vec_" + collection
        if collection not in ("knowledge", "episodes"):
            return
        try:
            cur.execute("DELETE FROM " + table)
            cur.execute(
                "DELETE FROM vec_id_map WHERE collection = ?", (collection,)
            )
            self._db.commit()
            logger.info("SqliteVecBackend: cleared collection '%s'", collection)
        except Exception as e:
            logger.warning("SqliteVecBackend.clear failed for '%s': %s",
                           collection, e)
            self._db.rollback()

    def count(self, collection: str) -> int:
        """Number of vectors indexed for a collection."""
        cur = self._db.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM vec_id_map WHERE collection = ?",
                (collection,),
            )
            return cur.fetchone()[0]
        except Exception:
            return 0



class PgVectorBackend(VectorBackend):
    """Vector search backed by PostgreSQL + the pgvector extension.

    Unlike the SQLite backends this is a client-server store: multiple app
    processes / nodes can read and write concurrently (Postgres MVCC), which is
    the whole point of the enterprise backend. Embeddings live in a single
    ``agentos_vectors`` table keyed by (collection, record_id, tenant_id);
    cosine distance search uses pgvector's ``<=>`` operator with an
    IVFFlat/HNSW index.

    Requires (installed only when DB_BACKEND=postgres):
        pip install 'psycopg[binary]' pgvector

    Args:
        engine: a storage ``PostgresEngine`` (provides pooled connections).
        dimension: embedding dimension (default 1536).
        tenant_id: tenant scope for all reads/writes. Falls back to the
            TENANT_ID env var, then empty string (single-tenant mode).
        agent_id: agent scope stored alongside each vector for diagnostics.
            Falls back to AGENT_ID env var.

    Tuning:
        PGVECTOR_IVF_LISTS (env, int): number of IVFFlat lists for the ANN
            index. Rule of thumb: sqrt(expected_row_count). Default 100.
    """

    DEFAULT_DIMENSION = 1536
    TABLE = "agentos_vectors"

    def __init__(self, engine, dimension: int = DEFAULT_DIMENSION,
                 tenant_id: str = "", agent_id: str = "", namespace: str = ""):
        import os
        self._engine = engine
        self._dimension = dimension
        self._tenant_id = tenant_id or os.getenv("TENANT_ID", "")
        self._agent_id = agent_id or os.getenv("AGENT_ID", "")
        self._ns = namespace
        self._ensure_extension_and_table()

    def _c(self, collection: str) -> str:
        """Namespace a collection for per-agent isolation in the shared table."""
        return f"{self._ns}:{collection}" if self._ns else collection

    def _register_vector(self, conn):
        from pgvector.psycopg import register_vector  # type: ignore
        register_vector(conn)

    def _ensure_extension_and_table(self) -> None:
        import os
        # IVFFlat lists: tunable via env. Rule of thumb: sqrt(N_rows).
        # Default 100 is reasonable up to ~10k rows; raise for larger datasets.
        ivf_lists = max(1, int(os.getenv("PGVECTOR_IVF_LISTS", "100")))
        with self._engine.connect() as conn:
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    collection  TEXT NOT NULL,
                    record_id   TEXT NOT NULL,
                    tenant_id   TEXT NOT NULL DEFAULT '',
                    agent_id    TEXT NOT NULL DEFAULT '',
                    embedding   vector({self._dimension}),
                    PRIMARY KEY (collection, record_id, tenant_id)
                )
                """
            )
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint c
                        JOIN pg_class t ON t.oid = c.conrelid
                        WHERE t.relname = 'agentos_vectors' AND c.contype = 'p'
                          AND array_length(c.conkey, 1) = 2
                    ) THEN
                        ALTER TABLE agentos_vectors DROP CONSTRAINT agentos_vectors_pkey;
                        ALTER TABLE agentos_vectors ADD PRIMARY KEY (collection, record_id, tenant_id);
                    END IF;
                END $$;
                """
            )
            # Cosine-distance ANN index (IVFFlat needs ANALYZE to be effective
            # and at least `lists` rows of data before it outperforms seq scan).
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.TABLE}_ann "
                f"ON {self.TABLE} USING ivfflat (embedding vector_cosine_ops) "
                f"WITH (lists = {ivf_lists})"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.TABLE}_tenant "
                f"ON {self.TABLE} (tenant_id, collection)"
            )
            logger.info(
                "PgVectorBackend: table + extension ready (dim=%d, tenant=%r, ivf_lists=%d)",
                self._dimension, self._tenant_id, ivf_lists,
            )

    def upsert(self, collection: str, record_id: str, embedding: List[float]) -> None:
        collection = self._c(collection)
        with self._engine.connect() as conn:
            self._register_vector(conn)
            conn.cursor().execute(
                f"""
                INSERT INTO {self.TABLE} (collection, record_id, tenant_id, agent_id, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (collection, record_id, tenant_id)
                DO UPDATE SET embedding = EXCLUDED.embedding,
                              agent_id  = EXCLUDED.agent_id
                """,
                (collection, record_id, self._tenant_id, self._agent_id,
                 _to_pg_vector(embedding)),
            )

    def search(
        self,
        collection: str,
        query_embedding: List[float],
        top_k: int = 10,
        min_score: float = 0.0,
        candidate_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, float]]:
        if not query_embedding:
            return []

        collection = self._c(collection)
        vec = _to_pg_vector(query_embedding)

        fetch_k = top_k if min_score == 0.0 else top_k * 4

        sql = (
            f"SELECT record_id, 1 - (embedding <=> %s) AS score "
            f"FROM {self.TABLE} "
            f"WHERE collection = %s AND tenant_id = %s"
        )
        params: List = [vec, collection, self._tenant_id]

        if candidate_ids:
            placeholders = ", ".join(["%s"] * len(candidate_ids))
            sql += f" AND record_id IN ({placeholders})"
            params.extend(list(candidate_ids))

        sql += " ORDER BY embedding <=> %s LIMIT %s"
        params.extend([vec, fetch_k])

        with self._engine.connect() as conn:
            self._register_vector(conn)
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = [
            (r[0], round(float(r[1]), 4))
            for r in rows
            if float(r[1]) >= min_score
        ]
        return results[:top_k]

    def delete(self, collection: str, record_id: str) -> None:
        collection = self._c(collection)
        with self._engine.connect() as conn:
            conn.cursor().execute(
                f"DELETE FROM {self.TABLE} "
                f"WHERE collection = %s AND record_id = %s AND tenant_id = %s",
                (collection, record_id, self._tenant_id),
            )

    def clear(self, collection: str) -> None:
        collection = self._c(collection)
        with self._engine.connect() as conn:
            conn.cursor().execute(
                f"DELETE FROM {self.TABLE} WHERE collection = %s AND tenant_id = %s",
                (collection, self._tenant_id),
            )

    def count(self, collection: str) -> int:
        collection = self._c(collection)
        with self._engine.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM {self.TABLE} "
                f"WHERE collection = %s AND tenant_id = %s",
                (collection, self._tenant_id),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _to_pg_vector(embedding: List[float]):
    """Adapt a python float list to a pgvector parameter.

    Uses ``pgvector``'s numpy/list adapter when available; falls back to the
    textual ``[..]`` literal pgvector accepts.
    """
    try:
        import numpy as np  # type: ignore
        return np.asarray(embedding, dtype="float32")
    except Exception:
        return "[" + ",".join(str(float(x)) for x in embedding) + "]"



def create_vector_backend(
    db_connection=None,
    dimension: int = SqliteVecBackend.DEFAULT_DIMENSION,
    scoped_connect=None,
    namespace: str = "",
) -> VectorBackend:
    """Factory: instantiate the correct VectorBackend based on VECTOR_BACKEND env var.

    Environment variables:
      VECTOR_BACKEND: "brute_force" (default) | "sqlite_vec" | "pgvector"
      PGVECTOR_IVF_LISTS: IVFFlat list count for pgvector ANN index (default 100)
      VECTOR_DIMENSION: Override default embedding dimension (default: 1536)

    Args:
        db_connection: SQLite connection (required for brute_force and sqlite_vec).
        dimension: Embedding dimension. Can be overridden via VECTOR_DIMENSION env var.
        scoped_connect: Postgres seam (KnowledgeIndexer._scoped_connect). When set, the
            BruteForceBackend hydrates embeddings via a scoped engine connection instead
            of a raw sqlite3 handle. Ignored by the pgvector backend (uses its own engine).

    Returns:
        An instance of VectorBackend.
    """
    import os

    backend_name = os.getenv("VECTOR_BACKEND", "brute_force").lower().strip()
    dim = int(os.getenv("VECTOR_DIMENSION", str(dimension)))

    if backend_name == "sqlite_vec":
        try:
            backend = SqliteVecBackend(db_connection=db_connection, dimension=dim)
            logger.info("VectorBackend: using SqliteVecBackend (dim=%d)", dim)
            return backend
        except ImportError:
            logger.warning(
                "VectorBackend: sqlite-vec not installed. "
                "Install with 'pip install sqlite-vec'. "
                "Falling back to BruteForceBackend."
            )
            return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)
        except Exception as e:
            logger.warning(
                "VectorBackend: SqliteVecBackend init failed: %s. "
                "Falling back to BruteForceBackend.", e
            )
            return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)

    elif backend_name == "pgvector":
        try:
            from .storage import get_engine, resolve_backend
            if resolve_backend() != "postgres":
                logger.warning(
                    "VectorBackend: VECTOR_BACKEND=pgvector requires DB_BACKEND=postgres. "
                    "Falling back to BruteForceBackend."
                )
                return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)
            engine = get_engine()
            tenant_id = os.getenv("TENANT_ID", "")
            agent_id = os.getenv("AGENT_ID", "")
            backend = PgVectorBackend(engine=engine, dimension=dim,
                                      tenant_id=tenant_id, agent_id=agent_id,
                                      namespace=namespace)
            logger.info("VectorBackend: using PgVectorBackend (dim=%d, tenant=%r, namespace=%r)",
                        dim, tenant_id, namespace)
            return backend
        except ImportError:
            logger.warning(
                "VectorBackend: pgvector/psycopg not installed. "
                "Install with \"pip install 'psycopg[binary]' pgvector\". "
                "Falling back to BruteForceBackend."
            )
            return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)
        except Exception as e:
            logger.warning(
                "VectorBackend: PgVectorBackend init failed: %s. "
                "Falling back to BruteForceBackend.", e
            )
            return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)

    elif backend_name == "brute_force":
        logger.info("VectorBackend: using BruteForceBackend")
        return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)

    else:
        logger.warning(
            "VectorBackend: unknown backend '%s'. "
            "Valid options: brute_force, sqlite_vec, pgvector. "
            "Falling back to BruteForceBackend.", backend_name
        )
        return BruteForceBackend(db_connection=db_connection, scoped_connect=scoped_connect)
