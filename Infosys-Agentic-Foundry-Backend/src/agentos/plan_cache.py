# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
PlanCache — Query→Skill→Tools plan caching for IAF Skill Agents.

Inspired by agent_os's plan cache. Caches successful routing + execution
patterns so identical/similar queries skip re-routing and replay faster.

Two-layer dedup:
1. Structural fingerprint — exact hash match (instant, zero-cost)
2. Semantic similarity — embedding cosine ≥ threshold (optional, requires embedding_fn)

Storage: PostgreSQL table with GIN index for fast prefix lookup.
"""

import os
import json
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple, Callable
from dataclasses import dataclass, field, asdict

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class CachedPlan:
    """A cached routing + execution plan."""
    id: str = ""
    agent_id: str = ""
    department: str = "General"
    
    # Fingerprint
    query_hash: str = ""             # SHA-256 of normalized query
    query_text: str = ""             # Original query for display
    
    # Routing result
    skill_name: str = ""
    routing_method: str = ""         # "llm", "keyword", "sticky", "plan_cache"
    routing_confidence: float = 1.0
    
    # Execution trace
    tools_used: List[str] = field(default_factory=list)
    tool_sequence: str = ""          # "tool1→tool2→tool3" for structural matching
    
    # Outcome
    outcome: str = "success"         # "success", "partial", "failure"
    user_approved: bool = True       # Was the result accepted by the user?
    
    # Metadata
    hit_count: int = 0               # How many times this plan was replayed
    created_at: str = ""
    last_used_at: str = ""
    created_by: str = ""
    
    # Optional embedding for semantic match
    embedding: Optional[List[float]] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tools_used"] = json.dumps(d["tools_used"])
        d.pop("embedding", None)  # Don't include in dict repr
        return d


# ============================================================================
# Plan Cache
# ============================================================================

class PlanCache:
    """
    PostgreSQL-backed plan cache with structural + optional semantic matching.
    
    Usage:
        cache = PlanCache(pool)
        await cache.initialize()
        
        # Check cache before routing
        plan = await cache.lookup(query, agent_id)
        if plan:
            # Use cached routing: plan.skill_name, plan.tools_used
            ...
        
        # After successful execution, store the plan
        await cache.store(CachedPlan(
            agent_id=agent_id, query_text=query,
            skill_name="data_retrieval", tools_used=["sql_query", "format_table"],
            outcome="success"
        ))
    """

    TABLE_NAME = "iaf_plan_cache"
    SEMANTIC_THRESHOLD = float(os.getenv("PLAN_CACHE_SEMANTIC_THRESHOLD", "0.90"))

    # Max plans per agent before LRU eviction.  Override via env var.
    try:
        MAX_PLANS_PER_AGENT = int(os.getenv("PLAN_CACHE_MAX_PER_AGENT", "500"))
    except (ValueError, TypeError):
        MAX_PLANS_PER_AGENT = 500

    def __init__(self, pool, embedding_fn: Optional[Callable] = None):
        """
        Args:
            pool: asyncpg connection pool
            embedding_fn: Optional async callable (text) -> List[float]
        """
        self.pool = pool
        self.embedding_fn = embedding_fn
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self):
        """Create plan cache table if it doesn't exist."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:       # double-check after acquiring lock
                return
            async with self.pool.acquire() as conn:
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                        id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        agent_id TEXT NOT NULL,
                        department TEXT DEFAULT 'General',
                        query_hash TEXT NOT NULL,
                        query_text TEXT NOT NULL,
                        skill_name TEXT NOT NULL,
                        routing_method TEXT DEFAULT '',
                        routing_confidence REAL DEFAULT 1.0,
                        tools_used TEXT DEFAULT '[]',
                        tool_sequence TEXT DEFAULT '',
                        outcome TEXT DEFAULT 'success',
                        user_approved BOOLEAN DEFAULT TRUE,
                        hit_count INTEGER DEFAULT 0,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        last_used_at TIMESTAMPTZ DEFAULT NOW(),
                        created_by TEXT DEFAULT '',
                        embedding REAL[] DEFAULT NULL
                    );
                """)
                # Fast lookup by agent + hash (also serves as uniqueness constraint for ON CONFLICT).
                # Must be UNIQUE for ON CONFLICT (agent_id, query_hash) to work.
                # If a non-unique index with this name already exists (from older code),
                # drop it first and recreate as UNIQUE.
                is_unique = await conn.fetchval(f"""
                    SELECT indisunique FROM pg_index
                    JOIN pg_class ON pg_class.oid = pg_index.indexrelid
                    WHERE pg_class.relname = 'idx_{self.TABLE_NAME}_lookup'
                """)
                if is_unique is not None and not is_unique:
                    log.info(f"[PlanCache] Upgrading idx_{self.TABLE_NAME}_lookup to UNIQUE")
                    await conn.execute(f"DROP INDEX IF EXISTS idx_{self.TABLE_NAME}_lookup")
                    is_unique = None  # force re-creation below
                if is_unique is None:
                    await conn.execute(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_{self.TABLE_NAME}_lookup
                        ON {self.TABLE_NAME} (agent_id, query_hash);
                    """)
                # For cleanup: old unused plans
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.TABLE_NAME}_age
                    ON {self.TABLE_NAME} (agent_id, last_used_at);
                """)

            self._initialized = True
            log.info("[PlanCache] Table initialized")

    # ------------------------------------------------------------------
    # Fingerprinting
    # ------------------------------------------------------------------
    @staticmethod
    def _query_hash(query: str) -> str:
        """
        Generate structural fingerprint of a query.
        Normalizes: lowercase, collapse whitespace, strip punctuation.
        """
        import re
        normalized = query.lower().strip()
        normalized = re.sub(r'[^\w\s]', '', normalized)  # strip punctuation
        normalized = re.sub(r'\s+', ' ', normalized)      # collapse whitespace
        return hashlib.sha256(normalized.encode()).hexdigest()[:20]

    @staticmethod
    def _tool_sequence(tools: List[str]) -> str:
        """Generate a deterministic tool sequence signature."""
        return "→".join(sorted(set(tools))) if tools else ""

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    async def lookup(
        self,
        query: str,
        agent_id: str,
        department: str = "General",
    ) -> Optional[CachedPlan]:
        """
        Look up a cached plan for a query.
        
        Two-layer matching:
        1. Exact structural hash match (fast, zero-cost)
        2. Semantic embedding match (if embedding_fn configured)
        
        Returns None if no match found.
        """
        await self.initialize()
        query_hash = self._query_hash(query)

        async with self.pool.acquire() as conn:
            # Layer 1: Exact hash match
            row = await conn.fetchrow(f"""
                SELECT * FROM {self.TABLE_NAME}
                WHERE agent_id = $1 AND query_hash = $2
                  AND outcome = 'success' AND user_approved = TRUE
                ORDER BY hit_count DESC, last_used_at DESC
                LIMIT 1
            """, agent_id, query_hash)

            if row:
                # Update hit count and last_used
                await conn.execute(f"""
                    UPDATE {self.TABLE_NAME}
                    SET hit_count = hit_count + 1, last_used_at = NOW()
                    WHERE id = $1
                """, row["id"])
                
                plan = self._row_to_plan(row)
                plan.routing_method = "plan_cache_exact"
                log.info(f"[PlanCache] Exact hit for '{query[:40]}...' → {plan.skill_name} (hits: {plan.hit_count + 1})")
                return plan

        # Layer 2: Semantic match (only if embedding_fn is available)
        if self.embedding_fn:
            return await self._semantic_lookup(query, agent_id)

        return None

    async def _semantic_lookup(
        self, query: str, agent_id: str
    ) -> Optional[CachedPlan]:
        """Semantic similarity search using embeddings."""
        try:
            query_embedding = await self.embedding_fn(query)
            if not query_embedding:
                return None

            async with self.pool.acquire() as conn:
                # Fetch recent successful plans with embeddings
                rows = await conn.fetch(f"""
                    SELECT *, embedding FROM {self.TABLE_NAME}
                    WHERE agent_id = $1
                      AND outcome = 'success' AND user_approved = TRUE
                      AND embedding IS NOT NULL
                    ORDER BY last_used_at DESC
                    LIMIT 50
                """, agent_id)

                if not rows:
                    return None

                # Compute cosine similarities
                best_score = 0.0
                best_row = None
                for row in rows:
                    stored_emb = row["embedding"]
                    if stored_emb:
                        score = self._cosine_similarity(query_embedding, stored_emb)
                        if score > best_score:
                            best_score = score
                            best_row = row

                if best_row and best_score >= self.SEMANTIC_THRESHOLD:
                    # Reuse the same connection for the hit_count update
                    await conn.execute(f"""
                        UPDATE {self.TABLE_NAME}
                        SET hit_count = hit_count + 1, last_used_at = NOW()
                        WHERE id = $1
                    """, best_row["id"])

                plan = self._row_to_plan(best_row)
                plan.routing_method = f"plan_cache_semantic({best_score:.2f})"
                log.info(
                    f"[PlanCache] Semantic hit ({best_score:.2f}) for "
                    f"'{query[:40]}...' → {plan.skill_name}"
                )
                return plan

        except Exception as e:
            log.warning(f"[PlanCache] Semantic lookup failed: {e}")

        return None

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Pure Python cosine similarity."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------
    async def store(self, plan: CachedPlan) -> str:
        """
        Store a successful plan in the cache.
        Deduplicates by query_hash — updates existing instead of inserting duplicate.
        Triggers LRU eviction when per-agent count exceeds MAX_PLANS_PER_AGENT.
        """
        await self.initialize()
        plan.query_hash = self._query_hash(plan.query_text)
        plan.tool_sequence = self._tool_sequence(plan.tools_used)
        if not plan.created_at:
            plan.created_at = datetime.now(timezone.utc).isoformat()
        plan.last_used_at = datetime.now(timezone.utc).isoformat()

        # Compute embedding if available
        embedding = None
        if self.embedding_fn:
            try:
                embedding = await self.embedding_fn(plan.query_text)
            except Exception as e:
                log.warning(f"[PlanCache] Embedding failed: {e}")

        async with self.pool.acquire() as conn:
            # Atomic upsert: INSERT ... ON CONFLICT to avoid TOCTOU race
            row = await conn.fetchrow(f"""
                INSERT INTO {self.TABLE_NAME}
                (agent_id, department, query_hash, query_text,
                 skill_name, routing_method, routing_confidence,
                 tools_used, tool_sequence, outcome,
                 user_approved, created_by, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (agent_id, query_hash)
                    DO UPDATE SET skill_name = EXCLUDED.skill_name,
                                 tools_used = EXCLUDED.tools_used,
                                 tool_sequence = EXCLUDED.tool_sequence,
                                 outcome = EXCLUDED.outcome,
                                 user_approved = EXCLUDED.user_approved,
                                 hit_count = {self.TABLE_NAME}.hit_count + 1,
                                 last_used_at = NOW(),
                                 routing_method = EXCLUDED.routing_method,
                                 routing_confidence = EXCLUDED.routing_confidence,
                                 embedding = EXCLUDED.embedding
                RETURNING id
            """,
                plan.agent_id, plan.department, plan.query_hash,
                plan.query_text, plan.skill_name, plan.routing_method,
                plan.routing_confidence, json.dumps(plan.tools_used),
                plan.tool_sequence, plan.outcome,
                plan.user_approved, plan.created_by, embedding
            )
            plan_id = row["id"]
            log.debug(f"[PlanCache] Upserted plan {plan_id}")
            # Evict oldest entries if the agent exceeds the size limit
            await self._evict_if_over_limit(plan.agent_id)
            return plan_id

    async def _evict_if_over_limit(self, agent_id: str):
        """Remove least-recently-used plans when the per-agent count
        exceeds ``MAX_PLANS_PER_AGENT``.  Keeps the most-used / most-recent
        entries and deletes the rest.
        """
        if self.MAX_PLANS_PER_AGENT <= 0:
            return  # unlimited
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self.TABLE_NAME} WHERE agent_id = $1",
                    agent_id,
                )
                if count is None or count <= self.MAX_PLANS_PER_AGENT:
                    return

                excess = count - self.MAX_PLANS_PER_AGENT
                # Delete the *excess* rows with lowest hit_count and oldest last_used_at
                result = await conn.execute(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE id IN (
                        SELECT id FROM {self.TABLE_NAME}
                        WHERE agent_id = $1
                        ORDER BY hit_count ASC, last_used_at ASC
                        LIMIT $2
                    )
                """, agent_id, excess)
                try:
                    evicted = int(result.split()[-1]) if result else 0
                except (ValueError, IndexError):
                    evicted = 0
                if evicted > 0:
                    log.info(
                        f"[PlanCache] Evicted {evicted} LRU plans for agent {agent_id} "
                        f"(limit={self.MAX_PLANS_PER_AGENT})"
                    )
        except Exception as e:
            log.warning(f"[PlanCache] Eviction check failed: {e}")

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------
    async def invalidate(self, agent_id: str, skill_name: Optional[str] = None) -> int:
        """
        Invalidate plans. Called when a skill is updated/deleted.
        Returns number of invalidated plans.
        """
        await self.initialize()
        async with self.pool.acquire() as conn:
            if skill_name:
                result = await conn.execute(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE agent_id = $1 AND skill_name = $2
                """, agent_id, skill_name)
            else:
                result = await conn.execute(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE agent_id = $1
                """, agent_id)
        
        try:
            count = int(result.split()[-1]) if result else 0
        except (ValueError, IndexError):
            count = 0
        if count > 0:
            log.info(f"[PlanCache] Invalidated {count} plans for {agent_id}/{skill_name or '*'}")
        return count

    async def mark_failed(self, query: str, agent_id: str) -> bool:
        """Mark a cached plan as failed (user rejected or execution error)."""
        await self.initialize()
        query_hash = self._query_hash(query)
        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                UPDATE {self.TABLE_NAME}
                SET outcome = 'failure', user_approved = FALSE
                WHERE agent_id = $1 AND query_hash = $2
            """, agent_id, query_hash)
        return "UPDATE" in result

    async def cleanup(self, agent_id: str, max_age_days: int = 30) -> int:
        """Remove old unused plans."""
        await self.initialize()
        # Enforce int to prevent SQL injection via INTERVAL string interpolation
        safe_days = int(max_age_days)
        if safe_days < 1 or safe_days > 3650:
            raise ValueError(f"max_age_days must be between 1 and 3650, got {max_age_days}")
        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                DELETE FROM {self.TABLE_NAME}
                WHERE agent_id = $1
                  AND last_used_at < NOW() - make_interval(days => $2)
                  AND hit_count < 3
            """, agent_id, safe_days)
        try:
            count = int(result.split()[-1]) if result else 0
        except (ValueError, IndexError):
            count = 0
        return count

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    async def get_stats(self, agent_id: str) -> Dict[str, Any]:
        """Get plan cache statistics."""
        await self.initialize()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT
                    COUNT(*) AS total_plans,
                    SUM(hit_count) AS total_hits,
                    COUNT(*) FILTER (WHERE outcome = 'success') AS successful,
                    COUNT(*) FILTER (WHERE outcome = 'failure') AS failed,
                    COUNT(DISTINCT skill_name) AS unique_skills,
                    AVG(hit_count) AS avg_hits_per_plan,
                    MAX(last_used_at) AS last_used
                FROM {self.TABLE_NAME}
                WHERE agent_id = $1
            """, agent_id)
        return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _row_to_plan(self, row) -> CachedPlan:
        """Convert a DB row to CachedPlan."""
        plan = CachedPlan()
        for k, v in dict(row).items():
            if k == "embedding":
                continue  # Skip embedding in the returned plan
            if hasattr(plan, k):
                if k == "tools_used" and isinstance(v, str):
                    setattr(plan, k, json.loads(v) if v else [])
                else:
                    setattr(plan, k, v)
        return plan
