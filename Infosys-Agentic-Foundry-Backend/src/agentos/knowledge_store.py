# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
KnowledgeStore — Four-layer knowledge management for IAF Skill Agents.

Inspired by agent_os's knowledge_indexer but built on IAF's existing
asyncpg PostgreSQL backend (no JSONL files).

Layers:
1. Facts      — permanent knowledge about entities, processes, rules
2. Learnings  — patterns, corrections, preferences extracted from conversations
3. Episodes   — business decision records with entity/stakeholder context
4. Embeddings — semantic vector search (SentenceTransformer or OpenAI)

Storage: PostgreSQL tables with FTS + optional vector similarity.
All operations are async (asyncpg).
"""

import os
import json
import hashlib
import asyncio
import math
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class KnowledgeType(str, Enum):
    FACT = "fact"
    LEARNING = "learning"
    CORRECTION = "correction"
    PREFERENCE = "preference"
    PATTERN = "pattern"
    EXCEPTION = "exception"


class KnowledgeStatus(str, Enum):
    CONFIRMED = "confirmed"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


@dataclass
class KnowledgeEntry:
    """A single knowledge item in the store."""
    id: str = ""
    agent_id: str = ""
    department: str = "General"
    knowledge_type: str = KnowledgeType.FACT
    status: str = KnowledgeStatus.CONFIRMED
    content: str = ""
    source: str = ""                 # "user_stated", "llm_inferred", "system"
    skill_name: str = ""             # which skill context
    entity_name: str = ""            # related entity
    confidence: float = 1.0
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""             # user email
    embedding_hash: str = ""         # hash of content for dedup

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> "KnowledgeEntry":
        entry = cls()
        for k, v in row.items():
            if hasattr(entry, k):
                if k == "tags" and isinstance(v, str):
                    setattr(entry, k, json.loads(v) if v else [])
                elif k == "metadata" and isinstance(v, str):
                    setattr(entry, k, json.loads(v) if v else {})
                else:
                    setattr(entry, k, v)
        return entry


@dataclass
class EpisodeEntry:
    """A business decision episode record."""
    id: str = ""
    agent_id: str = ""
    session_id: str = ""
    department: str = "General"
    query: str = ""
    response_summary: str = ""
    skill_name: str = ""
    entity_name: str = ""
    entity_type: str = ""
    tools_used: List[str] = field(default_factory=list)
    decision_context: str = ""
    outcome: str = ""               # "success", "partial", "failure"
    learning_signals: List[str] = field(default_factory=list)
    reasoning: str = ""
    created_at: str = ""
    created_by: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tools_used"] = json.dumps(d["tools_used"])
        d["learning_signals"] = json.dumps(d["learning_signals"])
        return d


# ============================================================================
# Knowledge Store
# ============================================================================

class KnowledgeStore:
    """
    PostgreSQL-backed knowledge store with FTS and optional vector search.
    
    Usage:
        store = KnowledgeStore(pool)
        await store.initialize()
        await store.upsert(KnowledgeEntry(content="...", agent_id="..."))
        results = await store.search("query", agent_id="...")
    """

    TABLE_KNOWLEDGE = "iaf_knowledge_store"
    TABLE_EPISODES = "iaf_episode_store"

    def __init__(self, pool, embedding_fn=None):
        """
        Args:
            pool: asyncpg connection pool
            embedding_fn: Optional async callable (text) -> List[float] for vector search.
                         If None, uses FTS-only search.
        """
        self.pool = pool
        self.embedding_fn = embedding_fn
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self):
        """Create tables if they don't exist."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:       # double-check after acquiring lock
                return
        async with self.pool.acquire() as conn:
            # Knowledge table with FTS
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_KNOWLEDGE} (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    agent_id TEXT NOT NULL,
                    department TEXT DEFAULT 'General',
                    knowledge_type TEXT NOT NULL DEFAULT 'fact',
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'system',
                    skill_name TEXT DEFAULT '',
                    entity_name TEXT DEFAULT '',
                    confidence REAL DEFAULT 1.0,
                    tags TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{{}}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by TEXT DEFAULT '',
                    embedding_hash TEXT DEFAULT '',
                    embedding REAL[] DEFAULT NULL,
                    search_vector TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector('english', 
                            coalesce(content, '') || ' ' || 
                            coalesce(entity_name, '') || ' ' || 
                            coalesce(skill_name, '')
                        )
                    ) STORED
                );
            """)
            # GIN index for full-text search
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.TABLE_KNOWLEDGE}_fts 
                ON {self.TABLE_KNOWLEDGE} USING GIN (search_vector);
            """)
            # Lookup indexes
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.TABLE_KNOWLEDGE}_agent 
                ON {self.TABLE_KNOWLEDGE} (agent_id, status);
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.TABLE_KNOWLEDGE}_dedup 
                ON {self.TABLE_KNOWLEDGE} (agent_id, embedding_hash);
            """)

            # Episode table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_EPISODES} (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    agent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    department TEXT DEFAULT 'General',
                    query TEXT NOT NULL,
                    response_summary TEXT DEFAULT '',
                    skill_name TEXT DEFAULT '',
                    entity_name TEXT DEFAULT '',
                    entity_type TEXT DEFAULT '',
                    tools_used TEXT DEFAULT '[]',
                    decision_context TEXT DEFAULT '',
                    outcome TEXT DEFAULT '',
                    learning_signals TEXT DEFAULT '[]',
                    reasoning TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by TEXT DEFAULT '',
                    search_vector TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector('english',
                            coalesce(query, '') || ' ' ||
                            coalesce(response_summary, '') || ' ' ||
                            coalesce(entity_name, '') || ' ' ||
                            coalesce(skill_name, '')
                        )
                    ) STORED
                );
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.TABLE_EPISODES}_fts 
                ON {self.TABLE_EPISODES} USING GIN (search_vector);
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.TABLE_EPISODES}_agent 
                ON {self.TABLE_EPISODES} (agent_id, session_id);
            """)

        self._initialized = True
        log.info("[KnowledgeStore] Tables initialized")

    # ------------------------------------------------------------------
    # Content hashing for deduplication
    # ------------------------------------------------------------------
    @staticmethod
    def _content_hash(content: str) -> str:
        """Generate a stable hash for dedup."""
        normalized = " ".join(content.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Fix #26 — Vector embedding helpers
    # ------------------------------------------------------------------
    async def _compute_embedding(self, text: str) -> Optional[List[float]]:
        """Compute an embedding vector for *text* using the configured ``embedding_fn``.

        Returns ``None`` when no embedding function is configured or if the
        call fails (graceful degradation to FTS-only search).
        """
        if not self.embedding_fn:
            return None
        try:
            vec = await self.embedding_fn(text)
            if isinstance(vec, (list, tuple)) and len(vec) > 0:
                return [float(v) for v in vec]
        except Exception as e:
            log.warning(f"[KnowledgeStore] Embedding computation failed: {e}")
        return None

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Pure-Python cosine similarity (no numpy dependency)."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # CRUD: Knowledge
    # ------------------------------------------------------------------
    async def upsert(self, entry: KnowledgeEntry) -> str:
        """
        Insert or update a knowledge entry. Deduplicates by content hash.
        Returns the entry ID.
        """
        await self.initialize()
        entry.embedding_hash = self._content_hash(entry.content)
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        if not entry.created_at:
            entry.created_at = entry.updated_at

        # Fix #26 — compute embedding for vector search reranking
        embedding = await self._compute_embedding(entry.content)

        async with self.pool.acquire() as conn:
            # Check for duplicate (FOR UPDATE to prevent concurrent upsert races)
            existing = await conn.fetchrow(f"""
                SELECT id FROM {self.TABLE_KNOWLEDGE}
                WHERE agent_id = $1 AND embedding_hash = $2
                FOR UPDATE
            """, entry.agent_id, entry.embedding_hash)

            if existing:
                # Update existing
                await conn.execute(f"""
                    UPDATE {self.TABLE_KNOWLEDGE}
                    SET content = $1, confidence = $2, status = $3, 
                        tags = $4, metadata = $5, updated_at = NOW(),
                        skill_name = $6, entity_name = $7, source = $8,
                        embedding = $10
                    WHERE id = $9
                """,
                    entry.content, entry.confidence, entry.status,
                    json.dumps(entry.tags), json.dumps(entry.metadata),
                    entry.skill_name, entry.entity_name, entry.source,
                    existing["id"], embedding
                )
                log.debug(f"[KnowledgeStore] Updated knowledge {existing['id']}")
                return existing["id"]
            else:
                # Insert new
                row = await conn.fetchrow(f"""
                    INSERT INTO {self.TABLE_KNOWLEDGE}
                    (agent_id, department, knowledge_type, status, content, source,
                     skill_name, entity_name, confidence, tags, metadata,
                     created_by, embedding_hash, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    RETURNING id
                """,
                    entry.agent_id, entry.department, entry.knowledge_type,
                    entry.status, entry.content, entry.source,
                    entry.skill_name, entry.entity_name, entry.confidence,
                    json.dumps(entry.tags), json.dumps(entry.metadata),
                    entry.created_by, entry.embedding_hash, embedding
                )
                log.debug(f"[KnowledgeStore] Inserted knowledge {row['id']}")
                return row["id"]

    async def search(
        self,
        query: str,
        agent_id: str,
        department: str = "General",
        limit: int = 10,
        status_filter: str = "confirmed",
        knowledge_type: Optional[str] = None,
        skill_name: Optional[str] = None,
    ) -> List[KnowledgeEntry]:
        """
        Hybrid search: FTS first, then optionally rerank by vector similarity.
        Only returns entries with matching status (default: confirmed).
        """
        await self.initialize()

        # Build FTS query — sanitize for tsquery syntax
        # Strip characters that are tsquery operators (', (, ), !, &, :, *, ?, |)
        # to prevent PostgreSQL syntax errors on natural language input.
        import re as _re
        sanitized = _re.sub(r"[^a-zA-Z0-9\s]", " ", query)
        terms = [t.strip() for t in sanitized.split() if len(t.strip()) > 2]
        if not terms:
            return []
        ts_query = " & ".join(terms)

        conditions = [
            f"agent_id = $1",
            f"status = $2",
        ]
        params: list = [agent_id, status_filter]
        param_idx = 3

        if knowledge_type:
            conditions.append(f"knowledge_type = ${param_idx}")
            params.append(knowledge_type)
            param_idx += 1

        if skill_name:
            conditions.append(f"skill_name = ${param_idx}")
            params.append(skill_name)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT *, 
                       ts_rank(search_vector, to_tsquery('english', ${param_idx})) AS fts_rank
                FROM {self.TABLE_KNOWLEDGE}
                WHERE {where_clause}
                  AND search_vector @@ to_tsquery('english', ${param_idx})
                ORDER BY fts_rank DESC
                LIMIT {limit}
            """, *params, ts_query)

            if not rows:
                # Fallback: ILIKE search for partial matches
                rows = await conn.fetch(f"""
                    SELECT *, 0.1 AS fts_rank
                    FROM {self.TABLE_KNOWLEDGE}
                    WHERE {where_clause}
                      AND (content ILIKE ${param_idx} OR entity_name ILIKE ${param_idx})
                    ORDER BY updated_at DESC
                    LIMIT {limit}
                """, *params, f"%{query}%")

        entries = [KnowledgeEntry.from_row(dict(r)) for r in rows]

        # Fix #26 — when embedding_fn is available, rerank FTS results by vector similarity
        if self.embedding_fn and entries:
            try:
                entries = await self._vector_rerank(query, entries)
            except Exception as e:
                log.debug(f"[KnowledgeStore] Vector rerank failed, keeping FTS order: {e}")

        return entries

    # ------------------------------------------------------------------
    # Fix #26 — Pure vector similarity search
    # ------------------------------------------------------------------
    async def vector_search(
        self,
        query: str,
        agent_id: str,
        department: str = "General",
        limit: int = 10,
        status_filter: str = "confirmed",
        knowledge_type: Optional[str] = None,
        skill_name: Optional[str] = None,
        similarity_threshold: float = 0.5,
    ) -> List[Tuple[KnowledgeEntry, float]]:
        """Semantic vector search with cosine similarity reranking.

        1. Computes query embedding via ``self.embedding_fn``.
        2. Fetches all candidate rows that have stored embeddings.
        3. Ranks by cosine similarity and returns entries above *similarity_threshold*.

        Returns list of ``(KnowledgeEntry, similarity_score)`` tuples.
        Falls back to FTS ``search()`` if no embedding function is configured.
        """
        await self.initialize()

        query_vec = await self._compute_embedding(query)
        if query_vec is None:
            # Graceful fallback — return FTS results with synthetic score
            fts_results = await self.search(
                query, agent_id, department, limit, status_filter,
                knowledge_type, skill_name,
            )
            return [(entry, 1.0) for entry in fts_results]

        # Build WHERE clause
        conditions = ["agent_id = $1", "status = $2", "embedding IS NOT NULL"]
        params: list = [agent_id, status_filter]
        param_idx = 3

        if knowledge_type:
            conditions.append(f"knowledge_type = ${param_idx}")
            params.append(knowledge_type)
            param_idx += 1

        if skill_name:
            conditions.append(f"skill_name = ${param_idx}")
            params.append(skill_name)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT * FROM {self.TABLE_KNOWLEDGE}
                WHERE {where_clause}
                ORDER BY updated_at DESC
                LIMIT {int(os.getenv('KNOWLEDGE_VECTOR_PREFETCH', 200))}
            """, *params)

        # Compute cosine similarity in Python and rerank
        scored: List[Tuple[KnowledgeEntry, float]] = []
        for r in rows:
            row_dict = dict(r)
            stored_emb = row_dict.get("embedding")
            if not stored_emb:
                continue
            sim = self._cosine_similarity(query_vec, list(stored_emb))
            if sim >= similarity_threshold:
                scored.append((KnowledgeEntry.from_row(row_dict), sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def _vector_rerank(
        self,
        query: str,
        fts_entries: List[KnowledgeEntry],
        alpha: float = 0.6,
    ) -> List[KnowledgeEntry]:
        """Rerank FTS results using vector similarity (hybrid scoring).

        ``alpha`` controls the blend:
        - ``alpha=1.0`` → pure vector ranking
        - ``alpha=0.0`` → pure FTS ranking
        - ``alpha=0.6`` → 60 % vector + 40 % FTS (default)
        """
        query_vec = await self._compute_embedding(query)
        if query_vec is None:
            return fts_entries  # no embedding fn — keep FTS order

        scored: List[Tuple[KnowledgeEntry, float]] = []
        for idx, entry in enumerate(fts_entries):
            fts_rank = 1.0 - (idx / max(len(fts_entries), 1))  # normalize 1→0
            # Try to get stored embedding; fall back to computing on the fly
            if hasattr(entry, "_embedding") and entry._embedding:
                vec = entry._embedding
            else:
                vec = await self._compute_embedding(entry.content)
            vec_sim = self._cosine_similarity(query_vec, vec) if vec else 0.0
            combined = alpha * vec_sim + (1 - alpha) * fts_rank
            scored.append((entry, combined))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored]

    async def get_all_for_agent(
        self,
        agent_id: str,
        status: str = "confirmed",
        limit: int = 50,
    ) -> List[KnowledgeEntry]:
        """Get all knowledge entries for an agent (for prompt injection)."""
        await self.initialize()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT * FROM {self.TABLE_KNOWLEDGE}
                WHERE agent_id = $1 AND status = $2
                ORDER BY confidence DESC, updated_at DESC
                LIMIT $3
            """, agent_id, status, limit)
        return [KnowledgeEntry.from_row(dict(r)) for r in rows]

    async def update_status(
        self, entry_id: str, new_status: str, reviewer: str = ""
    ) -> bool:
        """Approve or reject a pending knowledge entry."""
        await self.initialize()
        async with self.pool.acquire() as conn:
            # Read existing metadata, merge in Python, write back.
            # The column is TEXT (not JSONB), so PostgreSQL's || operator
            # would do string concatenation, corrupting the JSON.
            row = await conn.fetchrow(f"""
                SELECT metadata FROM {self.TABLE_KNOWLEDGE} WHERE id = $1
            """, entry_id)
            existing = {}
            if row and row["metadata"]:
                try:
                    existing = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    existing = {}
            existing["reviewed_by"] = reviewer
            result = await conn.execute(f"""
                UPDATE {self.TABLE_KNOWLEDGE}
                SET status = $1, updated_at = NOW(),
                    metadata = $3
                WHERE id = $2
            """, new_status, entry_id, json.dumps(existing))
        return "UPDATE" in result

    async def delete(self, entry_id: str) -> bool:
        """Hard delete a knowledge entry."""
        await self.initialize()
        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                DELETE FROM {self.TABLE_KNOWLEDGE} WHERE id = $1
            """, entry_id)
        return "DELETE" in result

    # ------------------------------------------------------------------
    # CRUD: Episodes
    # ------------------------------------------------------------------
    async def log_episode(self, episode: EpisodeEntry) -> str:
        """Log a business decision episode."""
        await self.initialize()
        if not episode.created_at:
            episode.created_at = datetime.now(timezone.utc).isoformat()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                INSERT INTO {self.TABLE_EPISODES}
                (agent_id, session_id, department, query, response_summary,
                 skill_name, entity_name, entity_type, tools_used,
                 decision_context, outcome, learning_signals, reasoning,
                 created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                RETURNING id
            """,
                episode.agent_id, episode.session_id, episode.department,
                episode.query, episode.response_summary,
                episode.skill_name, episode.entity_name, episode.entity_type,
                json.dumps(episode.tools_used), episode.decision_context,
                episode.outcome, json.dumps(episode.learning_signals),
                episode.reasoning, episode.created_by
            )
        log.debug(f"[KnowledgeStore] Logged episode {row['id']}")
        return row["id"]

    async def search_episodes(
        self,
        query: str,
        agent_id: str,
        limit: int = 5,
    ) -> List[EpisodeEntry]:
        """Search episodes by FTS."""
        await self.initialize()
        # Sanitize query for tsquery syntax (same as search())
        import re as _re
        sanitized = _re.sub(r"[^a-zA-Z0-9\s]", " ", query)
        terms = [t.strip() for t in sanitized.split() if len(t.strip()) > 2]
        if not terms:
            return []
        ts_query = " & ".join(terms)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT *, ts_rank(search_vector, to_tsquery('english', $2)) AS rank
                FROM {self.TABLE_EPISODES}
                WHERE agent_id = $1
                  AND search_vector @@ to_tsquery('english', $2)
                ORDER BY rank DESC
                LIMIT $3
            """, agent_id, ts_query, limit)

        results = []
        for r in rows:
            ep = EpisodeEntry()
            for k, v in dict(r).items():
                if hasattr(ep, k):
                    if k in ("tools_used", "learning_signals") and isinstance(v, str):
                        setattr(ep, k, json.loads(v) if v else [])
                    else:
                        setattr(ep, k, v)
            results.append(ep)
        return results

    async def get_recent_episodes(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[EpisodeEntry]:
        """Get recent episodes for context injection."""
        await self.initialize()
        conditions = ["agent_id = $1"]
        params: list = [agent_id]
        if session_id:
            conditions.append("session_id = $2")
            params.append(session_id)

        where = " AND ".join(conditions)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT * FROM {self.TABLE_EPISODES}
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ${len(params) + 1}
            """, *params, limit)

        results = []
        for r in rows:
            ep = EpisodeEntry()
            for k, v in dict(r).items():
                if hasattr(ep, k):
                    if k in ("tools_used", "learning_signals") and isinstance(v, str):
                        setattr(ep, k, json.loads(v) if v else [])
                    else:
                        setattr(ep, k, v)
            results.append(ep)
        return results

    # ------------------------------------------------------------------
    # Bulk Operations
    # ------------------------------------------------------------------
    async def get_stats(self, agent_id: str) -> Dict[str, Any]:
        """Get knowledge store statistics for an agent."""
        await self.initialize()
        async with self.pool.acquire() as conn:
            knowledge_stats = await conn.fetchrow(f"""
                SELECT 
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'confirmed') AS confirmed,
                    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                    COUNT(DISTINCT knowledge_type) AS type_count,
                    COUNT(DISTINCT skill_name) FILTER (WHERE skill_name != '') AS skill_count
                FROM {self.TABLE_KNOWLEDGE}
                WHERE agent_id = $1
            """, agent_id)
            episode_count = await conn.fetchval(f"""
                SELECT COUNT(*) FROM {self.TABLE_EPISODES}
                WHERE agent_id = $1
            """, agent_id)

        return {
            "knowledge": dict(knowledge_stats) if knowledge_stats else {},
            "episodes": episode_count or 0,
        }

    # ------------------------------------------------------------------
    # Prompt Injection Helper
    # ------------------------------------------------------------------
    async def build_knowledge_context(
        self,
        agent_id: str,
        query: str = "",
        skill_name: str = "",
        max_items: int = 15,
    ) -> str:
        """
        Build a markdown block of relevant knowledge for prompt injection.
        Combines: confirmed facts + relevant learnings + recent episodes.
        """
        sections = []

        # 1. Get confirmed knowledge (facts, learnings, patterns)
        knowledge = await self.get_all_for_agent(agent_id, limit=max_items)
        if query:
            # Also do a targeted search
            search_results = await self.search(
                query, agent_id, skill_name=skill_name, limit=5
            )
            # Merge, deduplicate by ID
            seen_ids = {k.id for k in knowledge}
            for sr in search_results:
                if sr.id not in seen_ids:
                    knowledge.append(sr)

        if knowledge:
            facts = [k for k in knowledge if k.knowledge_type == KnowledgeType.FACT]
            learnings = [k for k in knowledge if k.knowledge_type != KnowledgeType.FACT]

            if facts:
                lines = ["## Known Facts"]
                for f in facts[:10]:
                    prefix = f"[{f.entity_name}] " if f.entity_name else ""
                    lines.append(f"- {prefix}{f.content}")
                sections.append("\n".join(lines))

            if learnings:
                lines = ["## Learnings & Patterns"]
                for l in learnings[:10]:
                    tag = f"({l.knowledge_type})" if l.knowledge_type != "learning" else ""
                    lines.append(f"- {l.content} {tag}")
                sections.append("\n".join(lines))

        # 2. Recent relevant episodes
        if query:
            episodes = await self.search_episodes(query, agent_id, limit=3)
        else:
            episodes = await self.get_recent_episodes(agent_id, limit=3)

        if episodes:
            lines = ["## Recent Relevant Interactions"]
            for ep in episodes:
                lines.append(
                    f"- **{ep.skill_name}**: {ep.query[:80]}... "
                    f"→ {ep.outcome or 'completed'}"
                )
            sections.append("\n".join(lines))

        return "\n\n".join(sections) if sections else ""
