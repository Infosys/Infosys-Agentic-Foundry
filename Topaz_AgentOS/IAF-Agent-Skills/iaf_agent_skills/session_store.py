"""
Session Store - Redis-backed session state for horizontal scaling.

Enables SkillAgent state to persist across server restarts and load-balanced requests.
Any server can restore a user's session from Redis without losing conversation history.

Design:
- Serializes only what's needed (history, pending_action, summary)
- Complex objects (LLM, Kernel) are recreated on-demand
- Feature flag for gradual rollout (USE_REDIS_SESSIONS)
- Graceful degradation if Redis unavailable

Usage:
    from iaf_agent_skills.session_store import RedisSessionStore, AgentStateSnapshot
    
    store = RedisSessionStore(redis_url="redis://localhost:6379")
    
    # Save state after agent.run()
    snapshot = agent.export_state()
    await store.save_session(tenant_id, user_id, snapshot)
    
    # Restore state on next request
    snapshot = await store.load_session(tenant_id, user_id)
    if snapshot:
        agent.import_state(snapshot)

Redis Key Structure:
    iaf:session:{tenant_id}:{user_id}:state     → HASH (main state)
    iaf:session:{tenant_id}:{user_id}:history   → LIST (conversation history as JSON strings)
    iaf:session:index:{tenant_id}               → ZSET (user_id by last_active timestamp)
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def _safe_redis_endpoint(redis_url: str) -> str:
    """Return a log-safe Redis location without credentials or query values."""
    parsed = urlsplit(redis_url)
    host = parsed.hostname or "configured-host"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path or ""
    return f"{parsed.scheme or 'redis'}://{host}{port}{database}"

# Check for async redis
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

# Default TTL for sessions (24 hours)
DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60

# In-memory cache TTL (60 seconds)
MEMORY_CACHE_TTL_SECONDS = 60


@dataclass
class AgentStateSnapshot:
    """
    Serializable snapshot of SkillAgent state.
    
    Only includes state that needs to persist across servers.
    Complex objects (LLM, Kernel, Router) are recreated.
    """
    # Identity
    session_id: str
    tenant_id: str
    agent_id: str
    user_id: str
    
    # Conversation state (HIGH priority)
    current_skill: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    reasoning_ref: Optional[Dict[str, Any]] = None
    session_summary: Optional[str] = None
    compaction_count: int = 0
    
    # Pending action for confirmation flow
    pending_action: Optional[Dict[str, Any]] = None
    # Held tool call + durable approval checkpoint (interactive stream-intercept HITL) —
    # persisted so a durable approve can re-execute the exact call after eviction/restart.
    pending_tool_call: Optional[Dict[str, Any]] = None
    approval_pending: Optional[Dict[str, Any]] = None

    # Memory state
    short_term_memory: List[Dict[str, Any]] = field(default_factory=list)

    session_summary_refs: List[Dict[str, Any]] = field(default_factory=list)
    session_summary_pointer: str = ""

    # A workflow paused mid-run (HITL). Dropping this on save meant a restart lost the
    # checkpoint and the resume had nothing to continue from.
    workflow_checkpoint: Optional[Dict[str, Any]] = None
    # Set when a session was resumed from a different session id (fork lineage).
    parent_session_id: Optional[str] = None

    # Settings
    auto_run: bool = False
    
    # Metadata
    created_at: str = ""
    last_active_at: str = ""
    server_id: str = ""  # For debugging which server last handled
    
    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_active_at:
            self.last_active_at = now
    
    def to_redis_hash(self) -> Dict[str, str]:
        """
        Convert to Redis HASH format (all values must be strings).
        
        Conversation history is stored separately as a LIST for efficiency.
        """
        pending = None
        if self.pending_action:
            pending = self.pending_action.copy()
            if "timestamp" in pending and hasattr(pending["timestamp"], "isoformat"):
                pending["timestamp"] = pending["timestamp"].isoformat()
        
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "current_skill": self.current_skill or "",
            "session_summary": self.session_summary or "",
            "compaction_count": str(self.compaction_count),
            "reasoning_ref": json.dumps(self.reasoning_ref) if self.reasoning_ref else "",
            "pending_action": json.dumps(pending) if pending else "",
            "pending_tool_call": json.dumps(self.pending_tool_call) if self.pending_tool_call else "",
            "approval_pending": json.dumps(self.approval_pending) if self.approval_pending else "",
            "short_term_memory": json.dumps(self.short_term_memory),
            "session_summary_refs": json.dumps(self.session_summary_refs or []),
            "session_summary_pointer": self.session_summary_pointer or "",
            "workflow_checkpoint": json.dumps(self.workflow_checkpoint) if self.workflow_checkpoint else "",
            "parent_session_id": self.parent_session_id or "",
            "auto_run": "1" if self.auto_run else "0",
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "server_id": self.server_id,
            # conversation_history stored in separate LIST key
        }
    
    @classmethod
    def from_redis_hash(cls, data: Dict[str, str], history: List[Dict] = None) -> "AgentStateSnapshot":
        """Reconstruct from Redis HASH and optional history LIST."""
        pending = None
        pending_str = data.get("pending_action", "")
        if pending_str:
            try:
                pending = json.loads(pending_str)
            except json.JSONDecodeError:
                pass
        
        short_term = []
        short_term_str = data.get("short_term_memory", "")
        if short_term_str:
            try:
                short_term = json.loads(short_term_str)
            except json.JSONDecodeError:
                pass

        def _load_json(key):
            s = data.get(key, "")
            if not s:
                return None
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return None

        return cls(
            session_id=data.get("session_id", ""),
            tenant_id=data.get("tenant_id", ""),
            agent_id=data.get("agent_id", ""),
            user_id=data.get("user_id", ""),
            current_skill=data.get("current_skill") or None,
            conversation_history=history or [],
            reasoning_ref=_load_json("reasoning_ref"),
            session_summary=data.get("session_summary") or None,
            compaction_count=int(data.get("compaction_count", 0)),
            pending_action=pending,
            pending_tool_call=_load_json("pending_tool_call"),
            approval_pending=_load_json("approval_pending"),
            short_term_memory=short_term,
            session_summary_refs=_load_json("session_summary_refs") or [],
            session_summary_pointer=data.get("session_summary_pointer", ""),
            workflow_checkpoint=_load_json("workflow_checkpoint"),
            parent_session_id=data.get("parent_session_id") or None,
            auto_run=data.get("auto_run") == "1",
            created_at=data.get("created_at", ""),
            last_active_at=data.get("last_active_at", ""),
            server_id=data.get("server_id", ""),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for in-memory caching)."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentStateSnapshot":
        """Reconstruct from dictionary."""
        return cls(**data)


class RedisSessionStore:
    """
    Redis-backed session state store for horizontal scaling.
    
    Features:
    - Async Redis operations
    - In-memory cache for hot sessions (60s TTL)
    - Atomic updates via MULTI/EXEC
    - TTL-based auto-expiry (24 hours default)
    - Graceful degradation if Redis unavailable
    """
    
    # Key prefixes
    PREFIX = "iaf:session"
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        db: int = 0,
        session_ttl: int = DEFAULT_SESSION_TTL_SECONDS,
        cache_ttl: int = MEMORY_CACHE_TTL_SECONDS,
        server_id: str = "",
    ):
        """
        Initialize session store.
        
        Args:
            redis_url: Redis connection URL
            db: Redis database number
            session_ttl: Session expiry in seconds (default 24h)
            cache_ttl: In-memory cache TTL in seconds (default 60s)
            server_id: Unique identifier for this server instance
        """
        if not REDIS_AVAILABLE:
            raise ImportError("redis package required. Install with: pip install redis")
        
        self._redis_url = redis_url
        self._db = db
        self._session_ttl = session_ttl
        self._cache_ttl = cache_ttl
        self._server_id = server_id or f"server-{int(time.time())}"
        
        # Redis client (type: Any due to conditional import)
        self._client: Optional[Any] = None
        self._connected = False
        
        # In-memory cache for hot sessions
        self._cache: Dict[str, AgentStateSnapshot] = {}
        self._cache_times: Dict[str, float] = {}
    
    
    DEFAULT_SESSION = "_default"

    @staticmethod
    def _scope(agent_id: str, session_id: str) -> tuple:
        """Normalise the scope pair, never letting an empty value collapse a key.

        from_redis_hash defaults agent_id/session_id to "" for a legacy or partial hash; without
        this guard that produces `iaf:session:{t}:{u}::state` — a slot every degraded write would
        share, i.e. the exact collision this scoping exists to prevent.
        """
        return (str(agent_id or "_unknown"), str(session_id or RedisSessionStore.DEFAULT_SESSION))

    def _state_key(self, tenant_id: str, user_id: str, agent_id: str, session_id: str) -> str:
        """Main state HASH key — scoped per agent AND per conversation.

        Previously `{tenant}:{user}:state`, so every conversation a user had (across every agent
        and browser tab) shared one slot, and save_session's delete-and-rebuild meant last writer
        won. agent_id/session_id already travel inside AgentStateSnapshot, they were just never
        used to compute the key.
        """
        agent_id, session_id = self._scope(agent_id, session_id)
        return f"{self.PREFIX}:{tenant_id}:{user_id}:{agent_id}:{session_id}:state"

    def _history_key(self, tenant_id: str, user_id: str, agent_id: str, session_id: str) -> str:
        """Conversation history LIST key (same scoping as _state_key)."""
        agent_id, session_id = self._scope(agent_id, session_id)
        return f"{self.PREFIX}:{tenant_id}:{user_id}:{agent_id}:{session_id}:history"

    def _index_key(self, tenant_id: str) -> str:
        """Index of active sessions in tenant (ZSET by last_active)."""
        return f"{self.PREFIX}:index:{tenant_id}"

    def _index_member(self, user_id: str, agent_id: str, session_id: str) -> str:
        """Composite index member.

        The member used to be the bare user_id, so a user's sessions all collapsed onto one ZSET
        entry and delete_session's zrem removed the user even while other sessions were live.
        """
        agent_id, session_id = self._scope(agent_id, session_id)
        return f"{user_id}:{agent_id}:{session_id}"

    def _cache_key(self, tenant_id: str, user_id: str, agent_id: str, session_id: str) -> str:
        """In-memory cache key — MUST stay in lockstep with the Redis keys above, or the
        process-local cache will serve one conversation's snapshot to another."""
        agent_id, session_id = self._scope(agent_id, session_id)
        return f"{tenant_id}:{user_id}:{agent_id}:{session_id}"
    
    
    async def connect(self) -> bool:
        """Establish Redis connection. Returns True if successful."""
        try:
            self._client = aioredis.from_url(
                self._redis_url,
                db=self._db,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._client.ping()
            self._connected = True
            logger.info("RedisSessionStore connected to %s", _safe_redis_endpoint(self._redis_url))
            return True
        except Exception as e:
            self._connected = False
            logger.warning(f"RedisSessionStore connection failed: {e} - will use in-memory only")
            return False
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._connected = False
            logger.info("RedisSessionStore disconnected")
    
    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        if not self._client or not self._connected:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            self._connected = False
            return False
    
    def _ensure_connected(self) -> bool:
        """Check connection status. Returns False if not connected."""
        return self._client is not None and self._connected
    
    
    def _get_from_cache(self, tenant_id: str, user_id: str,
                        agent_id: str, session_id: str) -> Optional[AgentStateSnapshot]:
        """Get snapshot from in-memory cache if valid."""
        cache_key = self._cache_key(tenant_id, user_id, agent_id, session_id)

        if cache_key not in self._cache:
            return None

        cache_time = self._cache_times.get(cache_key, 0)
        if time.time() - cache_time > self._cache_ttl:
            # Expired - remove from cache
            del self._cache[cache_key]
            del self._cache_times[cache_key]
            return None

        return self._cache[cache_key]

    def _set_in_cache(self, tenant_id: str, user_id: str,
                      agent_id: str, session_id: str, snapshot: AgentStateSnapshot) -> None:
        """Store snapshot in in-memory cache."""
        cache_key = self._cache_key(tenant_id, user_id, agent_id, session_id)
        self._cache[cache_key] = snapshot
        self._cache_times[cache_key] = time.time()

    def _invalidate_cache(self, tenant_id: str, user_id: str,
                         agent_id: str, session_id: str) -> None:
        """Remove snapshot from cache."""
        cache_key = self._cache_key(tenant_id, user_id, agent_id, session_id)
        self._cache.pop(cache_key, None)
        self._cache_times.pop(cache_key, None)
    
    
    async def save_session(
        self,
        snapshot: AgentStateSnapshot,
        skip_cache: bool = False
    ) -> bool:
        """
        Save session state to Redis.
        
        Args:
            snapshot: The agent state to persist
            skip_cache: If True, don't update in-memory cache
            
        Returns:
            True if saved successfully, False otherwise
        """
        snapshot.last_active_at = datetime.now(timezone.utc).isoformat()
        snapshot.server_id = self._server_id
        
        # Scope comes from the snapshot itself — agent_id/session_id have always been carried in
        # the payload, so no caller signature had to change to make keys session-scoped.
        _agent, _session = self._scope(snapshot.agent_id, snapshot.session_id)

        # Always update cache (fast path)
        if not skip_cache:
            self._set_in_cache(snapshot.tenant_id, snapshot.user_id, _agent, _session, snapshot)

        # Save to Redis if connected
        if not self._ensure_connected():
            logger.debug("Redis not connected, session in memory only")
            return False

        try:
            state_key = self._state_key(snapshot.tenant_id, snapshot.user_id, _agent, _session)
            history_key = self._history_key(snapshot.tenant_id, snapshot.user_id, _agent, _session)
            index_key = self._index_key(snapshot.tenant_id)

            async with self._client.pipeline(transaction=True) as pipe:
                state_data = snapshot.to_redis_hash()
                pipe.hset(state_key, mapping=state_data)
                pipe.expire(state_key, self._session_ttl)

                # Save conversation history (delete and rebuild)
                pipe.delete(history_key)
                if snapshot.conversation_history:
                    for entry in snapshot.conversation_history:
                        pipe.rpush(history_key, json.dumps(entry))
                pipe.expire(history_key, self._session_ttl)

                # Update index (composite member so a user's sessions don't collapse into one)
                pipe.zadd(index_key, {self._index_member(snapshot.user_id, _agent, _session): time.time()})
                pipe.expire(index_key, self._session_ttl)

                await pipe.execute()

            logger.debug("Session saved: %s:%s:%s:%s",
                         snapshot.tenant_id, snapshot.user_id, _agent, _session)
            return True
            
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            return False
    
    async def load_session(
        self,
        tenant_id: str,
        user_id: str,
        agent_id: str = "",
        session_id: str = "",
        use_cache: bool = True
    ) -> Optional[AgentStateSnapshot]:
        """
        Load session state from Redis.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier
            agent_id: Agent identifier (keys are agent-scoped)
            session_id: Conversation identifier; omit for the template/default slot
            use_cache: If True, check in-memory cache first

        Returns:
            AgentStateSnapshot if found, None otherwise
        """
        agent_id, session_id = self._scope(agent_id, session_id)

        if use_cache:
            cached = self._get_from_cache(tenant_id, user_id, agent_id, session_id)
            if cached:
                logger.debug("Session cache hit: %s:%s:%s:%s", tenant_id, user_id, agent_id, session_id)
                return cached

        if not self._ensure_connected():
            logger.debug("Redis not connected, no session found")
            return None

        try:
            state_key = self._state_key(tenant_id, user_id, agent_id, session_id)
            history_key = self._history_key(tenant_id, user_id, agent_id, session_id)
            
            async with self._client.pipeline() as pipe:
                pipe.hgetall(state_key)
                pipe.lrange(history_key, 0, -1)
                results = await pipe.execute()
            
            state_data = results[0]
            history_data = results[1]
            
            if not state_data:
                logger.debug("No session found: %s:%s:%s:%s", tenant_id, user_id, agent_id, session_id)
                return None

            history = []
            for entry_str in history_data:
                try:
                    history.append(json.loads(entry_str))
                except json.JSONDecodeError:
                    pass

            snapshot = AgentStateSnapshot.from_redis_hash(state_data, history)

            self._set_in_cache(tenant_id, user_id, agent_id, session_id, snapshot)

            logger.debug("Session loaded: %s:%s:%s:%s (history: %d entries)",
                         tenant_id, user_id, agent_id, session_id, len(history))
            return snapshot
            
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None
    
    async def delete_session(self, tenant_id: str, user_id: str,
                             agent_id: str = "", session_id: str = "") -> bool:
        """Delete ONE session from Redis and cache."""
        agent_id, session_id = self._scope(agent_id, session_id)
        self._invalidate_cache(tenant_id, user_id, agent_id, session_id)

        if not self._ensure_connected():
            return True  # Nothing to delete in Redis

        try:
            state_key = self._state_key(tenant_id, user_id, agent_id, session_id)
            history_key = self._history_key(tenant_id, user_id, agent_id, session_id)
            index_key = self._index_key(tenant_id)

            async with self._client.pipeline() as pipe:
                pipe.delete(state_key)
                pipe.delete(history_key)
                pipe.zrem(index_key, self._index_member(user_id, agent_id, session_id))
                await pipe.execute()

            logger.debug("Session deleted: %s:%s:%s:%s", tenant_id, user_id, agent_id, session_id)
            return True

        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    async def extend_ttl(self, tenant_id: str, user_id: str,
                         agent_id: str = "", session_id: str = "") -> bool:
        """Extend session TTL (called on each activity)."""
        if not self._ensure_connected():
            return False

        agent_id, session_id = self._scope(agent_id, session_id)
        try:
            state_key = self._state_key(tenant_id, user_id, agent_id, session_id)
            history_key = self._history_key(tenant_id, user_id, agent_id, session_id)

            async with self._client.pipeline() as pipe:
                pipe.expire(state_key, self._session_ttl)
                pipe.expire(history_key, self._session_ttl)
                pipe.expire(self._index_key(tenant_id), self._session_ttl)
                await pipe.execute()

            return True
        except Exception:
            return False
    
    async def list_active_sessions(self, tenant_id: str, limit: int = 100) -> List[str]:
        """List active sessions in a tenant as `user:agent:session`, most recent first."""
        if not self._ensure_connected():
            return []

        try:
            index_key = self._index_key(tenant_id)
            return await self._client.zrevrange(index_key, 0, limit - 1)
        except Exception:
            return []

    async def list_active_users(self, tenant_id: str, limit: int = 100) -> List[str]:
        """List active users in a tenant (sorted by last activity).

        The index member became composite (`user:agent:session`) when keys were made
        session-scoped, so this de-duplicates back to distinct user ids to keep the
        contract its name implies. `limit` bounds members scanned, not users returned.
        """
        seen: List[str] = []
        for member in await self.list_active_sessions(tenant_id, limit):
            user = str(member).split(":", 1)[0]
            if user and user not in seen:
                seen.append(user)
        return seen
    
    async def get_session_stats(self) -> Dict[str, Any]:
        """Get session store statistics."""
        stats = {
            "redis_connected": self._connected,
            "cache_size": len(self._cache),
            "server_id": self._server_id,
        }
        
        if self._ensure_connected():
            try:
                # Count total sessions via SCAN (non-blocking; KEYS blocks Redis)
                count = 0
                async for _ in self._client.scan_iter(f"{self.PREFIX}:*:state"):
                    count += 1
                stats["total_sessions"] = count
            except Exception:
                stats["total_sessions"] = -1
        
        return stats


# Singleton for easy import
_session_store: Optional[RedisSessionStore] = None


def get_session_store(redis_url: str = None) -> RedisSessionStore:
    """Get or create the global session store instance."""
    global _session_store
    
    if _session_store is None:
        url = redis_url or "redis://localhost:6379"
        _session_store = RedisSessionStore(redis_url=url)
    
    return _session_store


async def init_session_store(redis_url: str) -> RedisSessionStore:
    """Initialize and connect the session store."""
    store = get_session_store(redis_url)
    await store.connect()
    return store
