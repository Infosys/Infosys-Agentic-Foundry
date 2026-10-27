"""
EntityRegistryStore: Ontology-aware entity resolution and context collection.

Manages the entity_registry table inside the existing agent_knowledge.db.
Provides:
  1. register_entity()    — Upsert entity nodes into the APQC ontology tree
  2. resolve_entities()   — Alias exact-match FIRST, then cosine fallback (threshold 0.75)
  3. walk_ancestors()     — Recursive CTE from leaf → root to collect skill_name + metadata
  4. collect_context()    — One-call composite: resolve + walk + gather metadata at every level

Design constraints:
  - Shares DB connection with KnowledgeIndexer (same WAL pool)
  - Embeddings only on ENTITY and ENTITY_TYPE nodes (L1-L3 are structural)
  - skill_name only on L3_SUBPROCESS nodes (children inherit via tree walk)
  - Empty table = no-op (all callers short-circuit on empty results)
"""

import hashlib
import json
import struct
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)



def _sql_in_clause(count: int, ph: str = "?") -> str:
    """Build a parameterized IN clause with the given number of placeholders.

    ``ph`` is the backend placeholder token ('?' for SQLite, '%s' for Postgres)
    so the same Fortify-safe wrapper works on both backends.
    """
    if count <= 0:
        return "(NULL)"
    return "(" + ", ".join(ph for _ in range(count)) + ")"


def _sql_where(conditions: list) -> str:
    """Build a WHERE clause from validated condition strings."""
    if not conditions:
        return ""
    return "WHERE " + " AND ".join(conditions)


class EntityRegistryStore:
    """
    Manages the entity_registry table inside the existing agent_knowledge.db.

    This class does NOT own the DB connection — it receives one from KnowledgeIndexer
    to share the same WAL-mode connection pool.
    """

    # Minimum cosine similarity for entity resolution (tuned for ada-002)
    RESOLVE_THRESHOLD = 0.75

    def __init__(
        self,
        db=None,
        get_embedding_fn: Optional[Callable[[str], List[float]]] = None,
        config_path: Optional[Path] = None,
        *,
        scoped_connect=None,
        ph: str = "?",
        backend: str = "sqlite",
    ):
        """
        Args:
            db: Shared sqlite3 connection (SQLite backend) — legacy. On Postgres this is None
                and `scoped_connect` provides connections instead.
            get_embedding_fn: Same embedding function used by KnowledgeIndexer.
            config_path: Optional path to entity_validation.yaml for allowlist/blocklist.
            scoped_connect: Parent KnowledgeIndexer._scoped_connect (a contextmanager factory).
                            When provided, all DB work goes through it (backend-agnostic).
            ph: Param placeholder for the active backend ('?' sqlite / '%s' postgres).
            backend: 'sqlite' | 'postgres'.
        """
        self._db = db
        self._scoped_connect_ext = scoped_connect
        self._ph = ph
        self._kbackend = backend
        self._get_embedding = get_embedding_fn
        self._config_path = config_path
        self._entity_validator: Optional[Any] = None

    @contextmanager
    def _connect(self):
        """Yield a connection for one operation, matching KnowledgeIndexer's seam.
        SQLite: the shared persistent connection (self._db). Postgres: a scoped engine
        connection via the parent's _scoped_connect. An explicit `conn` passed to a method
        (composite writes) should be used directly instead of calling this."""
        if self._scoped_connect_ext is not None:
            with self._scoped_connect_ext() as conn:
                yield conn
        else:
            yield self._db


    @staticmethod
    def _serialize_embedding(emb: List[float]) -> bytes:
        return struct.pack(f"{len(emb)}f", *emb)

    @staticmethod
    def _deserialize_embedding(data: bytes) -> List[float]:
        data = bytes(data)  # psycopg returns memoryview on Postgres; struct wants bytes
        n = len(data) // 4
        return list(struct.unpack(f"{n}f", data))

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


    def register_entity(
        self,
        node_id: str,
        node_type: str,
        display_name: str,
        parent_id: Optional[str] = None,
        skill_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        aliases: Optional[List[str]] = None,
        embed: bool = True,
    ) -> bool:
        """
        Upsert a single node into the entity_registry.

        Args:
            node_id:      Stable key, e.g. "vendor:acme_corp"
            node_type:    One of: L1_PROCESS, L2_KEY_PROCESS, L3_SUBPROCESS, ENTITY_TYPE, ENTITY
            display_name: Human-readable name, e.g. "ACME Corp"
            parent_id:    FK to parent node_id (None for root L1 nodes)
            skill_name:   Routing target. Typically only set on L3_SUBPROCESS nodes.
            metadata:     Dict of static context (profiles, SLAs, thresholds). Stored as JSON.
            aliases:      List of alternative names for exact-match lookup, e.g. ["acme", "acme corporation"].
            embed:        Whether to compute embedding for this node.
                          Default True for ENTITY/ENTITY_TYPE, callers can disable for L1-L3 tree nodes.

        Returns:
            True on success.
        """
        if not node_id or not display_name:
            return False

        # ── Guard: normalize domain bucket labels to node_type='ENTITY' ─────────
        # The six values below are the schema's structural vocabulary — they define
        # the ontology *shape* and are genuinely fixed (equivalent to SQL keywords).
        # Any other node_type is treated as a domain bucket label (e.g. 'customer',
        # 'vendor', 'contract', 'employee').  We do NOT hardcode those domain labels
        # here; instead we look up whether 'entity_type:<node_type>' exists in the
        # registry as an ENTITY_TYPE row.  This means adding a new domain only
        # requires seeding one ENTITY_TYPE row — no code changes needed.
        _SCHEMA_NODE_TYPES = {"tower", "process", "activity", "skill", "ENTITY_TYPE", "ENTITY"}
        if node_type not in _SCHEMA_NODE_TYPES:
            bucket_parent = f"entity_type:{node_type}"
            with self._connect() as conn:
                _bc = conn.cursor()
                _bc.execute(
                    f"SELECT 1 FROM entity_registry WHERE node_id = {self._ph} AND node_type = 'ENTITY_TYPE'",
                    (bucket_parent,),
                )
                bucket_row = _bc.fetchone()
            if bucket_row:
                # Caller used bucket label as node_type (e.g. 'customer') → coerce.
                if not parent_id:
                    parent_id = bucket_parent
                logger.warning(
                    "register_entity: node_type='%s' is a domain bucket label, not a schema type. "
                    "Coercing to node_type='ENTITY' with parent_id='%s' for node '%s'. "
                    "Pass node_type='ENTITY' explicitly to suppress this warning.",
                    node_type, parent_id, node_id,
                )
                node_type = "ENTITY"
            else:
                # Completely unknown type — no matching ENTITY_TYPE in the registry.
                logger.error(
                    "register_entity: unknown node_type='%s' for node '%s'. "
                    "It is not a schema type and no 'entity_type:%s' row exists in the registry. "
                    "Seed the ENTITY_TYPE row first, then retry.",
                    node_type, node_id, node_type,
                )
                return False

        # Structural validation: enforce tree conventions
        if parent_id:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT node_type FROM entity_registry WHERE node_id = {self._ph}", (parent_id,))
                parent_row = cur.fetchone()
            if parent_row:
                parent_node_type = parent_row[0]
                if node_type == "ENTITY_TYPE" and parent_node_type not in ("process", "tower"):
                    logger.warning(
                        "Structural violation: ENTITY_TYPE '%s' must be under a process node, "
                        "not '%s' (%s). Reparenting to nearest process ancestor.",
                        node_id, parent_id, parent_node_type,
                    )
                    ancestors = self.walk_ancestors(parent_id)
                    for a in ancestors:
                        if a["node_type"] == "process":
                            parent_id = a["node_id"]
                            logger.info("Reparented ENTITY_TYPE '%s' to process '%s'", node_id, parent_id)
                            break
                if node_type == "skill" and parent_node_type == "process":
                    logger.warning(
                        "Structural violation: skill '%s' should be under an activity node, "
                        "not process '%s'. Allowing but logging.",
                        node_id, parent_id,
                    )
                if node_type == "ENTITY" and parent_node_type != "ENTITY_TYPE":
                    logger.warning(
                        "Structural violation: ENTITY '%s' parent '%s' is '%s', expected ENTITY_TYPE.",
                        node_id, parent_id, parent_node_type,
                    )

        embedding_blob = None
        if embed and self._get_embedding and node_type in ("ENTITY", "ENTITY_TYPE"):
            try:
                emb = self._get_embedding(display_name[:8000])
                if emb:
                    embedding_blob = self._serialize_embedding(emb)
            except Exception as e:
                logger.warning("EntityRegistry: embedding failed for '%s': %s", display_name, e)

        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata or {}, default=str)
        aliases_json = json.dumps([a.lower().strip() for a in (aliases or []) if a and a.strip()])

        try:
            with self._connect() as conn:
                if self._kbackend == "postgres":
                    # Generated tsvector (search_tsv) auto-syncs from fts_text, so fill it
                    # here for ENTITY/ENTITY_TYPE nodes (mirrors _sync_to_fts5 on SQLite).
                    fts_text = ""
                    if node_type in ("ENTITY", "ENTITY_TYPE"):
                        _alias_text = " ".join(a.lower().strip() for a in (aliases or []) if a and a.strip())
                        fts_text = f"{display_name.lower()} {_alias_text}".strip()
                    _vals = ", ".join([self._ph] * 10)
                    conn.execute(f"""
                        INSERT INTO entity_registry (node_id, node_type, display_name, parent_id,
                                                     skill_name, embedding, metadata_json, aliases_json,
                                                     updated_at, fts_text)
                        VALUES ({_vals})
                        ON CONFLICT (node_id) DO UPDATE SET
                            node_type     = excluded.node_type,
                            display_name  = excluded.display_name,
                            parent_id     = excluded.parent_id,
                            skill_name    = COALESCE(excluded.skill_name, entity_registry.skill_name),
                            embedding     = COALESCE(excluded.embedding, entity_registry.embedding),
                            metadata_json = excluded.metadata_json,
                            aliases_json  = excluded.aliases_json,
                            updated_at    = excluded.updated_at,
                            fts_text      = excluded.fts_text
                    """, (node_id, node_type, display_name, parent_id,
                          skill_name, embedding_blob, meta_json, aliases_json, now, fts_text))
                    conn.commit()
                else:
                    conn.execute("""
                        INSERT INTO entity_registry (node_id, node_type, display_name, parent_id,
                                                     skill_name, embedding, metadata_json, aliases_json, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(node_id) DO UPDATE SET
                            node_type     = excluded.node_type,
                            display_name  = excluded.display_name,
                            parent_id     = excluded.parent_id,
                            skill_name    = COALESCE(excluded.skill_name, entity_registry.skill_name),
                            embedding     = COALESCE(excluded.embedding, entity_registry.embedding),
                            metadata_json = excluded.metadata_json,
                            aliases_json  = excluded.aliases_json,
                            updated_at    = excluded.updated_at
                    """, (node_id, node_type, display_name, parent_id,
                          skill_name, embedding_blob, meta_json, aliases_json, now))
                    conn.commit()

            # ── Sync to FTS5 for fast keyword lookup (SQLite only; PG generated column) ──
            self._sync_to_fts5(node_id, display_name, aliases or [], node_type)

            return True
        except Exception as e:
            logger.error("EntityRegistry: register_entity failed for '%s': %s", node_id, e)
            return False

    # Edge status vocabulary (free-string, but these are the framework-recognised values).
    STATUS_CURATED = "curated"          # tenant-authored ontology (seeder) — trusted
    STATUS_CONFIRMED = "confirmed"      # agent-inferred + promoted (human/eval)
    STATUS_PENDING = "pending_review"   # agent-inferred, not yet promoted — hidden from reads
    _ACTIVE_STATUSES = ("curated", "confirmed")

    def upsert_relationship(
        self,
        from_node: str,
        relation: str,
        to_node: str,
        condition: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        confidence: float = 1.0,
        status: str = "curated",
        source: Optional[str] = None,
        created_by: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> bool:
        """Upsert a directed edge into ``process_relationships`` (the world-model graph).

        Idempotent: ``id`` is a deterministic SHA-1 of ``(from_node|relation|to_node|condition)``,
        so re-asserting the same edge updates in place rather than duplicating. Mirrors
        ``register_entity``'s ``_connect``/``_ph``/``_kbackend`` seam (byte-identical on SQLite/PG).

        NOTE (FK): both endpoints MUST already exist in ``entity_registry`` (Postgres enforces it),
        so seed entities BEFORE relationships (the seeder orders this).

        Provenance (world-model framework): ``status`` gates visibility — ``curated`` (seeder) and
        ``confirmed`` (promoted) are returned by reads; ``pending_review`` (agent-inferred, unvetted)
        is hidden until promoted. ``confidence`` in [0,1]; ``source``/``created_by``/``valid_from``/
        ``valid_to`` record where/when the edge came from. Defaults keep existing callers = curated/1.0.

        Returns True on success, False on any error (non-fatal — logged).
        """
        if not from_node or not relation or not to_node:
            return False
        from_node = from_node.strip()
        relation = relation.strip()
        to_node = to_node.strip()
        cond = (condition or "").strip() or None
        rel_id = hashlib.sha256(
            f"{from_node}|{relation}|{to_node}|{cond or ''}".encode("utf-8")
        ).hexdigest()
        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata or {}, default=str)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence = 1.0
        status = (status or "curated").strip() or "curated"
        _row = (rel_id, from_node, relation, to_node, cond, meta_json, now,
                confidence, status, source, created_by, valid_from, valid_to)
        _cols = ("id, from_node, relation, to_node, condition, metadata_json, updated_at, "
                 "confidence, status, source, created_by, valid_from, valid_to")
        _set = ("condition = excluded.condition, metadata_json = excluded.metadata_json, "
                "updated_at = excluded.updated_at, confidence = excluded.confidence, "
                "status = excluded.status, source = excluded.source, "
                "created_by = excluded.created_by, valid_from = excluded.valid_from, "
                "valid_to = excluded.valid_to")

        try:
            with self._connect() as conn:
                _ph = self._ph if self._kbackend == "postgres" else "?"
                _vals = ", ".join([_ph] * 13)
                conn.execute(
                    f"INSERT INTO process_relationships ({_cols}) VALUES ({_vals}) "
                    f"ON CONFLICT (id) DO UPDATE SET {_set}"
                    if self._kbackend == "postgres" else
                    f"INSERT INTO process_relationships ({_cols}) VALUES ({_vals}) "
                    f"ON CONFLICT(id) DO UPDATE SET {_set}",
                    _row,
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(
                "EntityRegistry: upsert_relationship failed (%s -%s-> %s): %s",
                from_node, relation, to_node, e,
            )
            return False

    def set_relationship_status(self, rel_id: str, status: str) -> bool:
        """Governance: change an edge's status (e.g. promote pending_review → confirmed, or
        reject). Returns True if the UPDATE ran without error. Backend-agnostic."""
        if not rel_id or not status:
            return False
        _ph = self._ph if self._kbackend == "postgres" else "?"
        now = datetime.now().isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE process_relationships SET status = {_ph}, updated_at = {_ph} "
                    f"WHERE id = {_ph}",
                    (status, now, rel_id),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error("EntityRegistry: set_relationship_status failed for %s: %s", rel_id, e)
            return False

    def list_relationships(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Read edges (optionally filtered by status) for governance/review surfaces.
        Read-model helper — does not resolve or walk."""
        _ph = self._ph if self._kbackend == "postgres" else "?"
        cols = ("id", "from_node", "relation", "to_node", "condition",
                "status", "confidence", "source", "created_by")
        _sel = "SELECT " + ", ".join(cols) + " FROM process_relationships"
        try:
            with self._connect() as conn:
                if status:
                    rows = conn.execute(
                        f"{_sel} WHERE status = {_ph} ORDER BY updated_at DESC LIMIT {int(limit)}",
                        (status,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"{_sel} ORDER BY updated_at DESC LIMIT {int(limit)}"
                    ).fetchall()
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.error("EntityRegistry: list_relationships failed: %s", e)
            return []

    def register_batch(self, nodes: List[Dict[str, Any]]) -> int:
        """
        Batch-register multiple nodes. Each dict has the same keys as register_entity args.
        Returns count of successfully registered nodes.
        """
        count = 0
        for node in nodes:
            ok = self.register_entity(
                node_id=node["node_id"],
                node_type=node["node_type"],
                display_name=node["display_name"],
                parent_id=node.get("parent_id"),
                skill_name=node.get("skill_name"),
                metadata=node.get("metadata"),
                aliases=node.get("aliases"),
                embed=node.get("embed", True),
            )
            if ok:
                count += 1
        return count


    def _sync_to_fts5(self, node_id: str, display_name: str,
                      aliases: List[str], node_type: str) -> None:
        """
        Sync a single entity to the fts_entities FTS5 table.
        Called after every successful register_entity() upsert.

        FTS5 doesn't support ON CONFLICT, so we delete-then-insert.
        Only sync ENTITY and ENTITY_TYPE nodes (not structural nodes).
        """
        if node_type not in ("ENTITY", "ENTITY_TYPE"):
            return  # Skip structural nodes (tower, process, activity, skill)

        if self._kbackend == "postgres":
            return  # Postgres uses a generated tsvector column (filled by register_entity)

        try:
            cur = self._db.cursor()
            # Flatten aliases to space-separated string for FTS5 indexing
            aliases_text = " ".join(a.lower().strip() for a in aliases if a and a.strip())
            # Include display_name in searchable text
            aliases_text = f"{display_name.lower()} {aliases_text}".strip()

            cur.execute("DELETE FROM fts_entities WHERE node_id = ?", (node_id,))
            cur.execute("""
                INSERT INTO fts_entities (node_id, display_name, aliases_text, node_type)
                VALUES (?, ?, ?, ?)
            """, (node_id, display_name, aliases_text, node_type))
            # Note: No separate commit — uses the same transaction as register_entity
        except Exception as e:
            logger.warning("FTS5 sync failed for '%s': %s", node_id, e)


    @staticmethod
    def _sanitize_fts_query(query: str, use_and: bool = True) -> str:
        """
        Clean query for FTS5 — remove special chars, use AND/OR logic.
        
        Args:
            query: Raw user query text
            use_and: If True, use AND (all words must match - precise).
                     If False, use OR (any word matches - broad fallback).
        
        For entity resolution, AND ensures all words must match (no false positives
        like 'services' matching 'Quick Print Services' when searching for
        'Berlin Services GmbH').
        """
        import re
        # Keep only alphanumeric and spaces
        clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', query)
        # Filter out FTS5 keywords and short words
        fts_keywords = {"or", "and", "not", "near"}
        words = [w.strip() for w in clean.split() 
                 if w.strip() and len(w.strip()) >= 2 and w.strip().lower() not in fts_keywords]
        if not words:
            return ""
        # AND = all words must match (precise), OR = any word matches (broad)
        joiner = " AND " if use_and else " OR "
        return joiner.join(words)

    def _resolve_by_fts5(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        FTS5 fast path for entity alias lookup (~1ms).

        Uses the fts_entities virtual table for instant keyword matching
        with BM25 ranking. Falls through if no matches found.
        
        Strategy: Try AND first (precise - all words must match), then
        fall back to OR (broad - any word matches) if AND returns nothing.

        Args:
            query: Raw user query text
            top_k: Maximum entities to return

        Returns:
            List of matched entities with score=1.0 and match_method='fts5'
        """
        if not query:
            return []

        # Try AND first (precise — all words must match)
        fts_query_and = self._sanitize_fts_query(query, use_and=True)
        if fts_query_and:
            matches = self._execute_fts5_query(fts_query_and, top_k)
            if matches:
                logger.debug("FTS5 AND lookup: %d matches for '%s'", len(matches), query[:50])
                return matches
        
        # Fall back to OR (broad — any word matches)
        fts_query_or = self._sanitize_fts_query(query, use_and=False)
        if fts_query_or:
            matches = self._execute_fts5_query(fts_query_or, top_k)
            if matches:
                logger.debug("FTS5 OR fallback: %d matches for '%s'", len(matches), query[:50])
                return matches
        
        return []
    
    def _execute_fts5_query(self, fts_query: str, top_k: int) -> List[Dict[str, Any]]:
        """Execute FTS5 query and enrich results with metadata."""
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                if self._kbackend == "postgres":
                    tsq = fts_query.replace(" AND ", " & ").replace(" OR ", " | ")
                    cur.execute(f"""
                        SELECT node_id, display_name, node_type,
                               ts_rank_cd(search_tsv, to_tsquery('simple', {self._ph})) AS rank
                        FROM entity_registry
                        WHERE search_tsv @@ to_tsquery('simple', {self._ph})
                          AND node_type IN ('ENTITY', 'ENTITY_TYPE')
                        ORDER BY rank DESC
                        LIMIT {self._ph}
                    """, (tsq, tsq, top_k))
                else:
                    # FTS5 MATCH with BM25 ranking (rank is negative, lower = better)
                    cur.execute("""
                        SELECT f.node_id, f.display_name, f.node_type, rank
                        FROM fts_entities f
                        WHERE fts_entities MATCH ?
                          AND f.node_type IN ('ENTITY', 'ENTITY_TYPE')
                        ORDER BY rank
                        LIMIT ?
                    """, (fts_query, top_k))
                fts_rows = cur.fetchall()
            except Exception as e:
                logger.debug("Entity keyword lookup failed: %s", e)
                return []

            if not fts_rows:
                return []

            # Enrich FTS results with full metadata from entity_registry
            matches = []
            for node_id, display_name, node_type, rank in fts_rows:
                cur.execute(f"""
                    SELECT skill_name, metadata_json
                    FROM entity_registry
                    WHERE node_id = {self._ph}
                """, (node_id,))
                row = cur.fetchone()
                if not row:
                    continue
                skill_name, meta_str = row
                matches.append({
                    "node_id": node_id,
                    "node_type": node_type,
                    "display_name": display_name,
                    "skill_name": skill_name,
                    "score": 1.0,  # keyword match = high confidence
                    "metadata": json.loads(meta_str) if meta_str else {},
                    "match_method": "fts5",
                })

        return matches

    @staticmethod
    def _tokenize_query(query: str) -> Set[str]:
        """Build token set from query: full string + individual words + bigrams/trigrams."""
        query_lower = query.lower().strip()
        tokens: Set[str] = {query_lower}
        words = []
        for word in query_lower.split():
            stripped = word.strip(".,!?;:'\"()[]{}").strip()
            if stripped and len(stripped) >= 2:
                tokens.add(stripped)
                words.append(stripped)
        # N-grams (2- and 3-word phrases) to catch multi-word aliases
        for n in range(2, 4):
            for i in range(len(words) - n + 1):
                tokens.add(" ".join(words[i:i + n]))
        return tokens

    def _resolve_by_alias(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Fast exact-match lookup against aliases_json column.
        Returns matches with score=1.0 (perfect match, zero cost).

        Checks if any token (including bigrams/trigrams) matches an alias,
        or if a multi-word alias appears as a substring in the query.
        """
        if not query:
            return []

        query_lower = query.lower().strip()
        tokens = self._tokenize_query(query)

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT node_id, node_type, display_name, skill_name,
                   metadata_json, aliases_json
            FROM entity_registry
            WHERE aliases_json != '[]'
              AND node_type IN ('ENTITY', 'ENTITY_TYPE')
            """)
            rows = cur.fetchall()

        candidates: List[tuple] = []
        for row in rows:
            nid, ntype, dname, sname, meta_str, aliases_str = row
            try:
                stored_aliases = json.loads(aliases_str) if aliases_str else []
            except (json.JSONDecodeError, TypeError):
                continue

            best_len = 0
            for alias in stored_aliases:
                if (alias in tokens or alias in query_lower) and len(alias) > best_len:
                    best_len = len(alias)

            if best_len > 0:
                candidates.append((best_len, {
                    "node_id": nid,
                    "node_type": ntype,
                    "display_name": dname,
                    "skill_name": sname,
                    "score": 1.0,
                    "metadata": json.loads(meta_str) if meta_str else {},
                    "match_method": "alias",
                }))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in candidates[:top_k]]


    # Taxonomy node_types to scan (L1-L4 structural + skill leaf nodes)
    _TAXONOMY_NODE_TYPES = ("tower", "process", "activity", "skill")

    def _resolve_by_taxonomy(self, query: str) -> List[Dict[str, Any]]:
        """
        Match query words against taxonomy node aliases (L1 tower → L4 skill).

        Unlike entity resolution (which finds WHO the query is about),
        this finds WHAT process the query refers to — providing a second
        routing signal that helps disambiguate when an entity spans
        multiple process areas.

        Returns list of matched taxonomy nodes with their skill associations,
        ordered by specificity (deepest match first: skill > activity > process > tower).
        """
        if not query:
            return []

        tokens = self._tokenize_query(query)
        query_lower = query.lower().strip()

        in_clause = _sql_in_clause(len(self._TAXONOMY_NODE_TYPES), self._ph)
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT node_id, node_type, display_name, parent_id,"
                " skill_name, aliases_json"
                " FROM entity_registry"
                " WHERE aliases_json != '[]'"
                " AND node_type IN " + in_clause,
                self._TAXONOMY_NODE_TYPES,
            )
            rows = cur.fetchall()

        matches = []
        for row in rows:
            nid, ntype, dname, parent_id, sname, aliases_str = row
            try:
                stored_aliases = json.loads(aliases_str) if aliases_str else []
            except (json.JSONDecodeError, TypeError):
                continue

            matched_alias = None
            for alias in stored_aliases:
                if alias in tokens or alias in query_lower:
                    matched_alias = alias
                    break

            if not matched_alias:
                continue

            # Walk down to find child skills if this node has no skill_name itself
            child_skills = []
            if sname:
                child_skills.append(sname)
            else:
                child_skills = self._find_descendant_skills(nid)

            matches.append({
                "node_id": nid,
                "node_type": ntype,
                "display_name": dname,
                "matched_alias": matched_alias,
                "skill_name": sname,
                "child_skills": child_skills,
            })

        # Sort by specificity: skill (most specific) → tower (least specific)
        type_order = {"skill": 0, "activity": 1, "process": 2, "tower": 3}
        matches.sort(key=lambda m: type_order.get(m["node_type"], 99))
        return matches

    def _find_descendant_skills(self, parent_node_id: str) -> List[str]:
        """Find all skill_name values in descendant nodes of a given parent."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
            WITH RECURSIVE descendants AS (
                SELECT node_id, skill_name
                FROM entity_registry
                WHERE parent_id = {self._ph}

                UNION ALL

                SELECT er.node_id, er.skill_name
                FROM entity_registry er
                JOIN descendants d ON er.parent_id = d.node_id
            )
            SELECT DISTINCT skill_name
            FROM descendants
            WHERE skill_name IS NOT NULL
            """, (parent_node_id,))
            return [row[0] for row in cur.fetchall()]

    def resolve_entities(
        self,
        query_embedding: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        threshold: Optional[float] = None,
        top_k: int = 5,
        node_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find entity_registry nodes matching the query.

        Resolution order (fast → slow):
          1. FTS5 keyword match (~1ms) — instant inverted index lookup
          2. Cosine similarity on embeddings (~50ms) — semantic fallback

        Args:
            query_embedding: Pre-computed embedding of the user query.
            query_text:      Raw query text for FTS5 keyword matching.
            threshold:       Minimum cosine similarity. Default: 0.75.
            top_k:           Max entities to return.
            node_types:      Filter by node_type. Default: ["ENTITY", "ENTITY_TYPE"].

        Returns:
            List of dicts sorted by score DESC.
        """
        fts_matches = []
        if query_text:
            fts_matches = self._resolve_by_fts5(query_text, top_k=top_k)
            if fts_matches:
                logger.debug("EntityRegistry: FTS5 hit — %d matches for '%s'",
                             len(fts_matches), query_text[:50])
                # If FTS5 found enough matches, skip semantic search entirely
                if len(fts_matches) >= top_k:
                    return fts_matches[:top_k]

        if not query_embedding:
            return fts_matches  # No embedding → FTS5-only results

        threshold = threshold or self.RESOLVE_THRESHOLD
        allowed_types = node_types or ["ENTITY", "ENTITY_TYPE"]
        in_clause = _sql_in_clause(len(allowed_types), self._ph)

        # Exclude entities already matched by FTS5
        fts_node_ids = {m["node_id"] for m in fts_matches}

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT node_id, node_type, display_name, skill_name,"
                " embedding, metadata_json"
                " FROM entity_registry"
                " WHERE node_type IN " + in_clause +
                " AND embedding IS NOT NULL",
                allowed_types,
            )
            rows = cur.fetchall()

        cosine_matches = []
        for row in rows:
            nid, ntype, dname, sname, emb_blob, meta_str = row
            if nid in fts_node_ids:
                continue  # Already matched by FTS5
            if not emb_blob:
                continue
            stored_emb = self._deserialize_embedding(emb_blob)
            score = self._cosine_similarity(query_embedding, stored_emb)
            if score >= threshold:
                cosine_matches.append({
                    "node_id": nid,
                    "node_type": ntype,
                    "display_name": dname,
                    "skill_name": sname,
                    "score": score,
                    "metadata": json.loads(meta_str) if meta_str else {},
                    "match_method": "cosine",
                })

        # Merge: FTS5 matches (score=1.0) come first, then cosine matches sorted by score
        all_matches = fts_matches + sorted(cosine_matches, key=lambda x: x["score"], reverse=True)
        return all_matches[:top_k]


    def walk_ancestors(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Walk from a leaf node up to the root, collecting every ancestor.

        Returns list ordered from LEAF → ROOT (depth ASC).
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
            WITH RECURSIVE ancestors AS (
                SELECT node_id, node_type, display_name, parent_id,
                       skill_name, metadata_json, 0 AS depth
                FROM entity_registry
                WHERE node_id = {self._ph}

                UNION ALL

                SELECT er.node_id, er.node_type, er.display_name, er.parent_id,
                       er.skill_name, er.metadata_json, a.depth + 1
                FROM entity_registry er
                JOIN ancestors a ON er.node_id = a.parent_id
            )
            SELECT node_id, node_type, display_name, skill_name, metadata_json, depth
            FROM ancestors
            ORDER BY depth ASC
            """, (node_id,))
            rows = cur.fetchall()

        result = []
        for row in rows:
            nid, ntype, dname, sname, meta_str, depth = row
            result.append({
                "node_id": nid,
                "node_type": ntype,
                "display_name": dname,
                "skill_name": sname,
                "metadata": json.loads(meta_str) if meta_str else {},
                "depth": depth,
            })
        return result


    def collect_context(
        self,
        query_embedding: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        threshold: Optional[float] = None,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """
        The ONE method called from agent.py before routing.

        Produces two routing signals:
          Signal 1 (entity):  WHO is the query about?  (entity resolution → tree walk)
          Signal 2 (process): WHAT process does it refer to?  (taxonomy keyword match)

        Steps:
          1. resolve_entities()       — alias first, then cosine fallback
          2. walk_ancestors()         — for each match, walk tree to collect skill_name + metadata
          3. _resolve_by_taxonomy()   — match query words against L1-L4 taxonomy aliases
          4. Aggregate                — merge signals, detect agreement/conflict

        Returns:
            {
                "resolved_entities": [...],
                "skill_hint":        "ar_ops" | None,       # Signal 1: from entity
                "skill_confidence":  0.92 | 0.0,
                "process_hint":      "ar_ops" | None,       # Signal 2: from taxonomy
                "process_matches":   [{"node_id": ..., "display_name": ..., "matched_alias": ..., "child_skills": [...]}],
                "signals_agree":     True | False | None,   # None = one/both signals missing
                "tree_context":      [...],
                "entity_keys_for_xref": set(),
            }
        """
        result = {
            "resolved_entities": [],
            "skill_hint": None,
            "skill_confidence": 0.0,
            "process_hint": None,
            "process_matches": [],
            "signals_agree": None,
            "tree_context": [],
            "entity_keys_for_xref": set(),
        }

        if not query_embedding and not query_text:
            return result

        matches = self.resolve_entities(
            query_embedding=query_embedding,
            query_text=query_text,
            threshold=threshold,
            top_k=top_k,
        )

        skill_hint = None
        skill_confidence = 0.0

        if matches:
            result["resolved_entities"] = [
                {"node_id": m["node_id"], "display_name": m["display_name"],
                 "node_type": m.get("node_type", ""),
                 "score": m["score"], "match_method": m.get("match_method", "unknown")}
                for m in matches
            ]

            seen_nodes: Set[str] = set()
            for match in matches:
                ancestors = self.walk_ancestors(match["node_id"])
                for ancestor in ancestors:
                    nid = ancestor["node_id"]
                    if nid in seen_nodes:
                        continue
                    seen_nodes.add(nid)
                    result["tree_context"].append({
                        "level": ancestor["node_type"],
                        "name": ancestor["display_name"],
                        "node_id": nid,
                        "metadata": ancestor["metadata"],
                    })
                    if ancestor["skill_name"] and not skill_hint:
                        skill_hint = ancestor["skill_name"]
                        skill_confidence = match["score"]

                # Only store canonical node_id — display_name will never match xref
                # (xref is written with node_ids only, see upsert_knowledge/upsert_episode)
                result["entity_keys_for_xref"].add(match["node_id"].lower().strip())

        result["skill_hint"] = skill_hint
        result["skill_confidence"] = skill_confidence

        if query_text:
            taxonomy_matches = self._resolve_by_taxonomy(query_text)
            if taxonomy_matches:
                result["process_matches"] = [
                    {"node_id": m["node_id"], "display_name": m["display_name"],
                     "node_type": m["node_type"], "matched_alias": m["matched_alias"],
                     "skill_name": m["skill_name"], "child_skills": m["child_skills"]}
                    for m in taxonomy_matches
                ]
                # Best process hint = the most specific match's skill
                for tm in taxonomy_matches:
                    if tm["skill_name"]:
                        result["process_hint"] = tm["skill_name"]
                        break
                    if tm["child_skills"]:
                        result["process_hint"] = tm["child_skills"][0]
                        break

                # Add taxonomy node_ids so xref lookup finds process-linked records
                for tm in taxonomy_matches:
                    result["entity_keys_for_xref"].add(tm["node_id"])

        if skill_hint and result["process_hint"]:
            result["signals_agree"] = (skill_hint == result["process_hint"])
        elif skill_hint or result["process_hint"]:
            result["signals_agree"] = None  # Only one signal present

        logger.debug(
            "collect_context: entity_hint=%s process_hint=%s agree=%s",
            skill_hint, result["process_hint"], result["signals_agree"],
        )

        _node_ids = [n["node_id"] for n in result.get("tree_context", [])]
        if _node_ids:
            try:
                _in_cl = _sql_in_clause(len(_node_ids), self._ph)
                with self._connect() as _conn:
                    _rels = _conn.execute(
                        "SELECT from_node, relation, to_node, condition, metadata_json"
                        " FROM process_relationships"
                        " WHERE (from_node IN " + _in_cl + " OR to_node IN " + _in_cl + ")"
                        " AND COALESCE(status, 'curated') IN ('curated', 'confirmed')",
                        _node_ids + _node_ids,
                    ).fetchall()
                if _rels:
                    _rel_lines = []
                    for r in _rels:
                        _cond = f" (when: {r[3]})" if r[3] else ""
                        _meta = json.loads(r[4] or "{}")
                        _note = f" — {_meta['note']}" if _meta.get("note") else ""
                        _rel_lines.append(
                            f"{r[0]} {r[1].upper().replace('_', ' ')} {r[2]}{_cond}{_note}"
                        )
                    result["process_relationships"] = _rel_lines
            except Exception:
                pass  # table may not exist on older DBs — non-fatal

        return result


    def _infer_entity_type_for_skill(self, skill_name: str) -> Optional[str]:
        """Walk the tree to find the ENTITY_TYPE node sharing the same process ancestor.

        Strategy: skill → activity (parent) → process (grandparent) →
        find ENTITY_TYPE children of that process.
        Returns the most specific match (deepest ancestor first).
        """
        if not skill_name:
            return None
        skill_node_id = f"skill:{skill_name.lower()}"
        ancestors = self.walk_ancestors(skill_node_id)
        ancestor_ids = [a["node_id"] for a in ancestors]
        if not ancestor_ids:
            return None
        in_clause = _sql_in_clause(len(ancestor_ids), self._ph)
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT node_id FROM entity_registry"
                " WHERE node_type = 'ENTITY_TYPE'"
                " AND parent_id IN " + in_clause +
                " ORDER BY LENGTH(parent_id) DESC",
                ancestor_ids,
            )
            row = cur.fetchone()
        return row[0] if row else None

    def auto_register_entities(
        self,
        entity_names: List[str],
        skill_name: Optional[str] = None,
    ) -> List[str]:
        """Try to resolve each entity name; register new ones that don't match.

        Args:
            entity_names: Raw entity strings extracted from a conversation.
            skill_name:   The skill that handled the conversation (used to infer parent type).

        Returns:
            List of resolved node_ids (existing or newly created).
        """
        resolved_ids: List[str] = []
        if not entity_names:
            return resolved_ids

        for raw_name in entity_names:
            name = str(raw_name).strip()
            if not name or len(name) < 2:
                continue

            # Skip entities that look like skill names (already handled elsewhere)
            if name.lower().replace(" ", "_") == (skill_name or "").lower():
                continue

            # Try alias resolution first
            matches = self._resolve_by_alias(name, top_k=1)
            if matches:
                resolved_ids.append(matches[0]["node_id"])
                continue

            # Allowlist/blocklist: skip noisy entities before registering
            if self._entity_validator is None:
                try:
                    from .entity_validation import EntityValidator
                except ImportError:
                    import importlib.util
                    _ev_path = Path(__file__).resolve().parent / "entity_validation.py"
                    _ev_spec = importlib.util.spec_from_file_location("entity_validation", _ev_path)
                    _ev_mod = importlib.util.module_from_spec(_ev_spec)
                    _ev_spec.loader.exec_module(_ev_mod)
                    EntityValidator = _ev_mod.EntityValidator
                self._entity_validator = EntityValidator(self._config_path)
            if not self._entity_validator.should_register(name):
                logger.debug("Skipping auto-register (blocked or not allowed): %s", name)
                continue

            # No match — register as new ENTITY
            parent_id = self._infer_entity_type_for_skill(skill_name)
            parent_skill = skill_name
            if parent_id:
                # Inherit skill_name from the entity_type parent
                with self._connect() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        f"SELECT skill_name FROM entity_registry WHERE node_id = {self._ph}",
                        (parent_id,),
                    )
                    row = cur.fetchone()
                if row and row[0]:
                    parent_skill = row[0]

            slug = name.lower().strip().replace(" ", "_")
            slug = slug[:60]  # keep IDs manageable
            prefix = "entity"
            if parent_id and parent_id.startswith("entity_type:"):
                prefix = parent_id.split(":", 1)[1]
            node_id = f"{prefix}:{slug}"

            ok = self.register_entity(
                node_id=node_id,
                node_type="ENTITY",
                display_name=name,
                parent_id=parent_id,
                skill_name=parent_skill,
                aliases=[name.lower(), slug.replace("_", " ")],
                embed=True,
            )
            if ok:
                logger.info("Auto-registered entity: %s (parent=%s)", node_id, parent_id)
                resolved_ids.append(node_id)

        return resolved_ids

    def should_add_to_xref(self, entity_key: str) -> bool:
        """
        Return True if this entity key should be added to entity_xref (not noisy).
        Uses EntityValidator (allowlist + blocklist) for consistency with auto_register_entities.
        Taxonomy nodes (apqc:*) and skill prefixes (skill:*) are always allowed.
        """
        if not entity_key or not entity_key.strip():
            return False
        # Taxonomy nodes and skill prefixes: always allow
        if entity_key.startswith("apqc:") or entity_key.startswith("skill:"):
            return True
        # For vendor:xxx, customer:xxx, entity:xxx — check the name part
        if ":" in entity_key:
            prefix, rest = entity_key.split(":", 1)
            if prefix in ("vendor", "customer", "entity"):
                name = rest
            else:
                name = entity_key
        else:
            name = entity_key
        # Lazy-init validator (same pattern as auto_register_entities)
        if self._entity_validator is None:
            try:
                from .entity_validation import EntityValidator
            except ImportError:
                import importlib.util
                _ev_path = Path(__file__).resolve().parent / "entity_validation.py"
                _ev_spec = importlib.util.spec_from_file_location("entity_validation", _ev_path)
                _ev_mod = importlib.util.module_from_spec(_ev_spec)
                _ev_spec.loader.exec_module(_ev_mod)
                EntityValidator = _ev_mod.EntityValidator
            self._entity_validator = EntityValidator(self._config_path)
        return self._entity_validator.should_register(name)


    def list_entities(
        self, node_type: Optional[str] = None, parent_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List registered entities, optionally filtered by type or parent."""
        with self._connect() as conn:
            cur = conn.cursor()
            conditions = []
            params = []
            if node_type:
                conditions.append(f"node_type = {self._ph}")
                params.append(node_type)
            if parent_id:
                conditions.append(f"parent_id = {self._ph}")
                params.append(parent_id)

            where_clause = _sql_where(conditions)
            cur.execute(
                "SELECT node_id, node_type, display_name, parent_id, skill_name,"
                " metadata_json, aliases_json, updated_at"
                " FROM entity_registry "
                + where_clause +
                " ORDER BY node_type, display_name",
                params,
            )

            return [
                {
                    "node_id": r[0], "node_type": r[1], "display_name": r[2],
                    "parent_id": r[3], "skill_name": r[4],
                    "metadata": json.loads(r[5]) if r[5] else {},
                    "aliases": json.loads(r[6]) if r[6] else [],
                    "updated_at": r[7],
                }
                for r in cur.fetchall()
            ]

    def count(self) -> Dict[str, int]:
        """Return count of nodes by type."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT node_type, COUNT(*) FROM entity_registry GROUP BY node_type")
            return dict(cur.fetchall())

    def get_tree(self) -> Dict[str, Any]:
        """Return full ontology tree with cross-reference link counts.

        Returns:
            {
              "nodes": [ {node_id, display_name, node_type, parent_id,
                          skill_name, aliases, knowledge_links, episode_links} ],
              "stats": {total_nodes, by_type, skill_linked,
                        total_aliases, total_knowledge_links}
            }
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT
                er.node_id,
                er.display_name,
                er.node_type,
                er.parent_id,
                er.skill_name,
                er.aliases_json,
                COALESCE(kl.cnt, 0) AS knowledge_links,
                COALESCE(el.cnt, 0) AS episode_links
            FROM entity_registry er
            LEFT JOIN (
                SELECT entity, COUNT(*) AS cnt
                FROM entity_xref WHERE record_type = 'knowledge'
                GROUP BY entity
            ) kl ON kl.entity = er.node_id
                 OR  kl.entity = er.skill_name
            LEFT JOIN (
                SELECT entity, COUNT(*) AS cnt
                FROM entity_xref WHERE record_type = 'episode'
                GROUP BY entity
            ) el ON el.entity = er.node_id
                 OR  el.entity = er.skill_name
            ORDER BY er.node_type, er.display_name
            """)
            rows = cur.fetchall()

        nodes = []
        by_type: Dict[str, int] = {}
        skill_linked = 0
        total_aliases = 0
        total_knowledge_links = 0

        for r in rows:
            aliases = json.loads(r[5]) if r[5] else []
            node = {
                "node_id": r[0],
                "display_name": r[1],
                "node_type": r[2],
                "parent_id": r[3],
                "skill_name": r[4],
                "aliases": aliases,
                "knowledge_links": r[6],
                "episode_links": r[7],
            }
            nodes.append(node)
            by_type[r[2]] = by_type.get(r[2], 0) + 1
            if r[4]:  # skill_name is not None
                skill_linked += 1
            total_aliases += len(aliases)
            total_knowledge_links += r[6]

        return {
            "nodes": nodes,
            "stats": {
                "total_nodes": len(nodes),
                "by_type": by_type,
                "skill_linked": skill_linked,
                "total_aliases": total_aliases,
                "total_knowledge_links": total_knowledge_links,
            },
        }


    def _ensure_routing_log_table(self):
        """Create routing_signal_log table if it doesn't exist (SQLite; PG uses schema DDL)."""
        if self._kbackend == "postgres":
            return  # created by knowledge_schema_ddl with GENERATED ALWAYS AS IDENTITY
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS routing_signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                query_text TEXT,
                entity_hint TEXT,
                entity_confidence REAL,
                process_hint TEXT,
                process_matches_json TEXT,
                signals_agree INTEGER,
                routed_skill TEXT,
                resolved_entities_json TEXT
            )
        """)
        self._db.commit()

    def log_routing_signal(
        self,
        query_text: str,
        entity_hint: Optional[str],
        entity_confidence: float,
        process_hint: Optional[str],
        process_matches: Optional[List[Dict]],
        signals_agree: Optional[bool],
        routed_skill: Optional[str],
        resolved_entities: Optional[List[str]] = None,
    ):
        """Record a routing decision for intelligence analytics."""
        try:
            self._ensure_routing_log_table()
            _vals = ", ".join([self._ph] * 8)
            with self._connect() as conn:
                conn.execute(f"""
                    INSERT INTO routing_signal_log
                        (query_text, entity_hint, entity_confidence, process_hint,
                         process_matches_json, signals_agree, routed_skill, resolved_entities_json)
                    VALUES ({_vals})
                """, (
                    query_text,
                    entity_hint,
                    entity_confidence,
                    process_hint,
                    json.dumps(process_matches or []),
                    1 if signals_agree is True else (0 if signals_agree is False else None),
                    routed_skill,
                    json.dumps(resolved_entities or []),
                ))
                conn.commit()
        except Exception as e:
            logger.warning("Failed to log routing signal: %s", e)

    def get_routing_stats(self) -> Dict[str, Any]:
        """Aggregate routing signal log for dashboard analytics."""
        self._ensure_routing_log_table()
        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM routing_signal_log")
            total = cur.fetchone()[0]
            if total == 0:
                return {
                    "total_routes": 0,
                    "process_miss_rate": 0,
                    "entity_miss_rate": 0,
                    "agreement_rate": 0,
                    "recent_process_misses": [],
                    "recent_entity_misses": [],
                }

            cur.execute("SELECT COUNT(*) FROM routing_signal_log WHERE process_hint IS NULL")
            process_misses = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM routing_signal_log WHERE entity_hint IS NULL")
            entity_misses = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM routing_signal_log WHERE signals_agree = 1")
            agreements = cur.fetchone()[0]

            # Queries where BOTH signals had data (for meaningful agreement rate)
            cur.execute("""
                SELECT COUNT(*) FROM routing_signal_log
                WHERE entity_hint IS NOT NULL AND process_hint IS NOT NULL
            """)
            both_present = cur.fetchone()[0]

            cur.execute("""
                SELECT query_text, routed_skill, entity_hint, timestamp
                FROM routing_signal_log
                WHERE process_hint IS NULL
                ORDER BY id DESC LIMIT 10
            """)
            recent_process_misses = [
                {"query": r[0], "routed_skill": r[1], "entity_hint": r[2], "timestamp": r[3]}
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT query_text, routed_skill, process_hint, timestamp
                FROM routing_signal_log
                WHERE entity_hint IS NULL
                ORDER BY id DESC LIMIT 10
            """)
            recent_entity_misses = [
                {"query": r[0], "routed_skill": r[1], "process_hint": r[2], "timestamp": r[3]}
                for r in cur.fetchall()
            ]

        return {
            "total_routes": total,
            "process_miss_rate": round(process_misses / total * 100, 1) if total else 0,
            "entity_miss_rate": round(entity_misses / total * 100, 1) if total else 0,
            "agreement_rate": round(agreements / both_present * 100, 1) if both_present else 0,
            "recent_process_misses": recent_process_misses,
            "recent_entity_misses": recent_entity_misses,
        }
