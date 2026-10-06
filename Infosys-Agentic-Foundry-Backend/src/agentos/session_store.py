# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
SessionStore — Redis-backed session state snapshots for IAF horizontal scaling.

Inspired by agent_os's session management. Provides fast session state
serialization/deserialization so any worker node can resume a session
without hitting PostgreSQL for hot-path state lookups.

Purpose:
  - Horizontal scaling: any worker can pick up a session mid-flight
  - Fast state restore: Redis read (~1ms) vs PostgreSQL read (~10-50ms)
  - Session affinity fallback: if sticky session breaks, state is in Redis
  - Lightweight session metadata without full LangGraph checkpoint overhead

Integration:
  - Saves after final_response node (background task)
  - Restores at start of generate_past_conversation_summary node
  - Complements (not replaces) LangGraph AsyncPostgresSaver
"""

import os
import json
import time
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Encryption layer  (Fix #22 — GDPR / regulatory compliance)
# ============================================================================

_SESSION_ENCRYPTION_KEY = os.getenv("SESSION_ENCRYPTION_KEY", "").strip()
_fernet = None

if _SESSION_ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        # Accept raw 32-byte key OR a Fernet-encoded key
        try:
            _fernet = Fernet(_SESSION_ENCRYPTION_KEY.encode())
        except Exception:
            # Derive a valid Fernet key from arbitrary secret_data via PBKDF2.
            # Uses a deterministic salt for consistency across restarts.
            import hashlib as _hashlib
            _fixed_salt = _hashlib.sha256(
                b"IAF-session-store-salt:" + _SESSION_ENCRYPTION_KEY.encode()
            ).digest()[:16]
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=_fixed_salt,
                iterations=100_000,
            )
            _derived = base64.urlsafe_b64encode(
                kdf.derive(_SESSION_ENCRYPTION_KEY.encode())
            )
            _fernet = Fernet(_derived)
        log.info("[SessionStore] Encryption at rest ENABLED (Fernet/AES-128-CBC, PBKDF2)")
    except ImportError:
        log.warning(
            "[SessionStore] SESSION_ENCRYPTION_KEY set but 'cryptography' package not installed. "
            "Install with: pip install cryptography.  Falling back to plaintext."
        )
else:
    log.debug("[SessionStore] Encryption at rest DISABLED (no SESSION_ENCRYPTION_KEY)")


def _encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* if Fernet is available, else return as-is."""
    if _fernet is None:
        return plaintext
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decrypt(ciphertext: str) -> str:
    """Decrypt *ciphertext* if Fernet is available, else return as-is."""
    if _fernet is None:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception:
        # Fallback: data might have been written before encryption was enabled.
        # Log a warning so data-corruption / key-rotation issues are visible.
        log.warning(
            "[SessionStore] Fernet decryption failed — returning raw data. "
            "Possible key rotation or pre-encryption data."
        )
        return ciphertext


# ============================================================================
# Configuration
# ============================================================================

try:
    SESSION_TTL = int(os.getenv("SESSION_STORE_TTL", 86400))
except (ValueError, TypeError):
    SESSION_TTL = 86400  # 24h default
SESSION_PREFIX = "iaf:session"
ENABLE_SESSION_STORE = os.getenv("ENABLE_SESSION_STORE", "true").lower() in ("true", "1", "yes")
# Circuit breaker cooldown: seconds to wait before retrying after a failure
try:
    CIRCUIT_BREAKER_COOLDOWN = int(os.getenv("SESSION_STORE_CB_COOLDOWN", 30))
except (ValueError, TypeError):
    CIRCUIT_BREAKER_COOLDOWN = 30


def _parse_host_port_list(hosts_str: str, default_port: int = 6379) -> List[tuple]:
    """Parse a comma-separated list of host:port pairs.

    Examples:
        "host1:6379,host2:6380"  -> [("host1", 6379), ("host2", 6380)]
        "host1,host2"            -> [("host1", default_port), ("host2", default_port)]
        "host1:26379"            -> [("host1", 26379)]
    """
    result = []
    for entry in hosts_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            host, port_str = entry.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = default_port
        else:
            host = entry
            port = default_port
        result.append((host, port))
    return result or [("localhost", default_port)]


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class SessionSnapshot:
    """A lightweight snapshot of active session state."""
    agent_id: str
    session_id: str
    user_id: str = ""

    # Routing state
    current_skill: str = ""
    routing_method: str = ""
    routing_confidence: float = 0.0

    # Context / memory
    session_summary: str = ""
    preference: str = ""
    past_conversation_summary: str = ""
    conversation_turn_count: int = 0

    # Metadata
    department: str = "General"
    model_name: str = ""
    last_query: str = ""
    last_response_preview: str = ""       # First 200 chars

    # File context (AgentShell)
    file_context_management: bool = False

    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    last_active_at: str = ""

    # Custom extension dict for skill-specific state
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON, then encrypt if a key is configured."""
        plaintext = json.dumps(asdict(self), default=str)
        return _encrypt(plaintext)

    @classmethod
    def from_json(cls, data: str) -> "SessionSnapshot":
        """Decrypt (if needed) then deserialize."""
        plaintext = _decrypt(data)
        d = json.loads(plaintext)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================================================
# Session Store
# ============================================================================

class SessionStore:
    """
    Redis-backed session state store for horizontal scaling.
    
    Uses sync redis.Redis matching existing IAF patterns
    (cache_config.py, redis_postgres_manager.py).
    
    Usage:
        store = SessionStore()  # auto-connects using env vars
        
        # Save session snapshot (fire-and-forget after final_response)
        store.save(SessionSnapshot(
            agent_id="abc", session_id="xyz",
            current_skill="data_retrieval",
            session_summary="User asked about Q3 revenue...",
        ))
        
        # Restore at start of next request
        snapshot = store.restore("abc", "xyz")
        if snapshot:
            state["past_conversation_summary"] = snapshot.session_summary
            ...
    """

    def __init__(self, redis_client=None):
        """
        Args:
            redis_client: Optional pre-configured redis.Redis instance.
                         If None, creates one from env vars.
        """
        self._client = redis_client
        self._connected = False
        self._connection_failed = False  # Circuit-breaker: skip after first failure
        self._last_failure_time: float = 0.0  # Timestamp of last failure (for cooldown)

    @property
    def client(self):
        """Lazy-init Redis connection with fast port pre-check."""
        if self._client is None:
            # Fast port-reachability check BEFORE creating the Redis client.
            # On Windows, socket_connect_timeout is unreliable — the OS TCP
            # stack retransmits SYN packets for ~21s before giving up, ignoring
            # the Python-level timeout. A raw socket probe with 0.5s timeout
            # catches unreachable ports immediately.
            if not self._is_port_reachable():
                self._connection_failed = True
                log.warning(
                    "[SessionStore] Redis port unreachable — circuit-breaker tripped immediately."
                )
                return None
            self._client = self._create_client()
        return self._client

    @property
    def is_available(self) -> bool:
        """Fast check: returns False if circuit breaker is open and cooldown hasn't elapsed."""
        if self._connection_failed:
            self._maybe_reset_circuit_breaker()
        return not self._connection_failed

    def _maybe_reset_circuit_breaker(self):
        """Half-open circuit breaker: after cooldown, attempt a probe and reset if Redis is reachable."""
        if not self._connection_failed:
            return
        elapsed = time.time() - self._last_failure_time
        if elapsed < CIRCUIT_BREAKER_COOLDOWN:
            return  # Still in cooldown
        # Attempt a probe
        if self._is_port_reachable():
            log.info(
                f"[SessionStore] Circuit breaker HALF-OPEN: Redis port reachable "
                f"after {elapsed:.0f}s cooldown — resetting."
            )
            self._connection_failed = False
            self._client = None  # Force fresh client creation
        else:
            # Still down — reset cooldown timer for next attempt
            self._last_failure_time = time.time()
            log.debug("[SessionStore] Circuit breaker probe failed — still OPEN.")

    def _trip_circuit_breaker(self, context: str, error: Exception):
        """Trip the circuit breaker and record the failure timestamp."""
        self._connection_failed = True
        self._last_failure_time = time.time()
        log.warning(f"[SessionStore] {context} failed (circuit-breaker tripped): {error}")

    @staticmethod
    def _is_port_reachable() -> bool:
        """Quick TCP probe to check if Redis port is listening (0.5s timeout).
        
        Supports standalone, sentinel, and cluster modes.
        For sentinel/cluster, probes ALL configured nodes and returns True
        if at least one is reachable.
        """
        import socket
        mode = os.getenv("REDIS_MODE", "standalone").lower().strip()

        if mode == "sentinel":
            sentinel_hosts = os.getenv("REDIS_SENTINEL_HOSTS", "")
            if sentinel_hosts:
                nodes = _parse_host_port_list(sentinel_hosts, default_port=26379)
                for host, port in nodes:
                    try:
                        sock = socket.create_connection((host, port), timeout=0.5)
                        sock.close()
                        return True
                    except (OSError, socket.timeout):
                        continue
                return False

        elif mode == "cluster":
            cluster_nodes = os.getenv("REDIS_CLUSTER_NODES", "")
            if cluster_nodes:
                nodes = _parse_host_port_list(cluster_nodes, default_port=6379)
                for host, port in nodes:
                    try:
                        sock = socket.create_connection((host, port), timeout=0.5)
                        sock.close()
                        return True
                    except (OSError, socket.timeout):
                        continue
                return False

        # Standalone mode (default)
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))
        try:
            sock = socket.create_connection((host, port), timeout=0.5)
            sock.close()
            return True
        except (OSError, socket.timeout):
            return False

    @staticmethod
    def _create_client():
        """Create Redis client from environment variables.

        Supports three modes via REDIS_MODE env var:
          - "standalone" (default): plain redis.Redis
          - "sentinel": redis.sentinel.Sentinel for HA failover
          - "cluster": redis.cluster.RedisCluster for sharding

        Environment variables used:
          REDIS_MODE             - connection mode
          REDIS_HOST / REDIS_PORT - standalone connection
          REDIS_SENTINEL_HOSTS   - comma-separated host:port pairs (default port 26379)
          REDIS_SENTINEL_MASTER  - master name (default "mymaster")
          REDIS_DB               - database number (default 0)
          REDIS_CLUSTER_NODES    - comma-separated host:port pairs
          Credentials are read from environment at runtime.
        """
        import redis
        mode = os.getenv("REDIS_MODE", "standalone").lower().strip()
        _redis_credential = os.getenv("REDIS_PASSWORD")
        password = _redis_credential if _redis_credential and _redis_credential.strip() not in ("", "None", "none") else None
        del _redis_credential  # clear intermediate reference

        if mode == "sentinel":
            from redis.sentinel import Sentinel
            sentinel_hosts_str = os.getenv("REDIS_SENTINEL_HOSTS", "localhost:26379")
            master_name = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")
            db = int(os.getenv("REDIS_DB", 0))

            sentinel_nodes = _parse_host_port_list(sentinel_hosts_str, default_port=26379)
            _sentinel_credential = os.getenv("REDIS_SENTINEL_PASSWORD")
            sentinel_password = _sentinel_credential if _sentinel_credential and _sentinel_credential.strip() not in ("", "None", "none") else None
            del _sentinel_credential  # clear intermediate reference

            sentinel = Sentinel(
                sentinel_nodes,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                sentinel_kwargs={"password": sentinel_password} if sentinel_password else {},
            )
            client = sentinel.master_for(
                master_name,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                password=password,
                db=db,
                decode_responses=True,
            )
            log.info(
                f"[SessionStore] Redis Sentinel client created: "
                f"master={master_name}, sentinels={sentinel_nodes}"
            )
            return client

        elif mode == "cluster":
            from redis.cluster import RedisCluster, ClusterNode
            cluster_nodes_str = os.getenv("REDIS_CLUSTER_NODES", "localhost:6379")
            nodes = _parse_host_port_list(cluster_nodes_str, default_port=6379)
            startup_nodes = [ClusterNode(h, p) for h, p in nodes]

            client = RedisCluster(
                startup_nodes=startup_nodes,
                password=password,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
                skip_full_coverage_check=True,
            )
            log.info(
                f"[SessionStore] Redis Cluster client created: "
                f"nodes={nodes}"
            )
            return client

        else:
            # Standalone mode (default)
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", 6379))
            db = int(os.getenv("REDIS_DB", 0))

            return redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
                # NOTE: Do NOT set retry_on_error — it causes automatic retries
                # that multiply the timeout (2s × retries) when Redis is down,
                # adding 4-24s of dead wait time per request.
            )

    def _key(self, agent_id: str, session_id: str) -> str:
        """Generate Redis key."""
        return f"{SESSION_PREFIX}:{agent_id}:{session_id}"

    def _meta_key(self, agent_id: str) -> str:
        """Index key for all sessions of an agent."""
        return f"{SESSION_PREFIX}:{agent_id}:_index"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    def save(self, snapshot: SessionSnapshot, ttl: int = SESSION_TTL) -> bool:
        """
        Save a session snapshot to Redis.
        
        Returns True on success, False on error (never raises).
        """
        if not ENABLE_SESSION_STORE:
            return False
        if self._connection_failed:
            self._maybe_reset_circuit_breaker()
            if self._connection_failed:
                return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            if not snapshot.created_at:
                snapshot.created_at = now
            snapshot.updated_at = now
            snapshot.last_active_at = now

            client = self.client
            if client is None:
                return False

            key = self._key(snapshot.agent_id, snapshot.session_id)
            pipe = client.pipeline(transaction=True)

            # Store snapshot
            pipe.setex(key, ttl, snapshot.to_json())

            # Track in agent's session index (sorted set by timestamp)
            pipe.zadd(
                self._meta_key(snapshot.agent_id),
                {snapshot.session_id: time.time()}
            )
            pipe.expire(self._meta_key(snapshot.agent_id), ttl)

            pipe.execute()
            self._connected = True
            log.debug(
                f"[SessionStore] Saved session {snapshot.session_id[:8]}... "
                f"for agent {snapshot.agent_id[:8]}..."
            )
            return True
        except Exception as e:
            self._trip_circuit_breaker("Save", e)
            return False

    def restore(self, agent_id: str, session_id: str) -> Optional[SessionSnapshot]:
        """
        Restore a session snapshot from Redis.
        
        Returns None if not found or on error (never raises).
        """
        if not ENABLE_SESSION_STORE:
            return None
        if self._connection_failed:
            self._maybe_reset_circuit_breaker()
            if self._connection_failed:
                return None
        try:
            client = self.client
            if client is None:
                return None
            key = self._key(agent_id, session_id)
            data = client.get(key)
            if data:
                snapshot = SessionSnapshot.from_json(data)
                self._connected = True
                log.debug(
                    f"[SessionStore] Restored session {session_id[:8]}... "
                    f"(skill={snapshot.current_skill})"
                )
                return snapshot
            return None
        except Exception as e:
            self._trip_circuit_breaker("Restore", e)
            return None

    def touch(self, agent_id: str, session_id: str, ttl: int = SESSION_TTL) -> bool:
        """Extend TTL without modifying content."""
        if not ENABLE_SESSION_STORE or self._connection_failed:
            return False
        try:
            client = self.client
            if client is None:
                return False
            key = self._key(agent_id, session_id)
            return bool(client.expire(key, ttl))
        except Exception as e:
            self._trip_circuit_breaker("Touch", e)
            return False

    def delete(self, agent_id: str, session_id: str) -> bool:
        """Remove a session snapshot."""
        if not ENABLE_SESSION_STORE or self._connection_failed:
            return False
        try:
            client = self.client
            if client is None:
                return False
            key = self._key(agent_id, session_id)
            pipe = client.pipeline(transaction=False)
            pipe.delete(key)
            pipe.zrem(self._meta_key(agent_id), session_id)
            pipe.execute()
            return True
        except Exception as e:
            self._trip_circuit_breaker("Delete", e)
            return False

    # ------------------------------------------------------------------
    # Batch / query operations
    # ------------------------------------------------------------------
    def list_sessions(self, agent_id: str, limit: int = 50) -> List[str]:
        """List active session IDs for an agent (most recent first)."""
        if not ENABLE_SESSION_STORE or self._connection_failed:
            return []
        try:
            client = self.client
            if client is None:
                return []
            meta_key = self._meta_key(agent_id)
            sessions = client.zrevrange(meta_key, 0, limit - 1)
            return sessions or []
        except Exception as e:
            self._trip_circuit_breaker("ListSessions", e)
            return []

    def get_active_count(self, agent_id: str) -> int:
        """Count active sessions for an agent."""
        if not ENABLE_SESSION_STORE or self._connection_failed:
            return 0
        try:
            client = self.client
            if client is None:
                return 0
            return client.zcard(self._meta_key(agent_id))
        except Exception as e:
            self._trip_circuit_breaker("GetActiveCount", e)
            return 0

    def cleanup_expired(self, agent_id: str) -> int:
        """Remove expired session IDs from the index."""
        if not ENABLE_SESSION_STORE or self._connection_failed:
            return 0
        try:
            client = self.client
            if client is None:
                return 0
            meta_key = self._meta_key(agent_id)
            sessions = client.zrange(meta_key, 0, -1)
            if not sessions:
                return 0
            # Use pipeline to batch EXISTS checks (avoid O(n) round-trips)
            check_pipe = client.pipeline(transaction=False)
            for sid in sessions:
                check_pipe.exists(self._key(agent_id, sid))
            exists_results = check_pipe.execute()
            # Collect expired session IDs and remove in a single pipeline
            expired = [
                sid for sid, exists in zip(sessions, exists_results) if not exists
            ]
            if expired:
                rem_pipe = client.pipeline(transaction=False)
                for sid in expired:
                    rem_pipe.zrem(meta_key, sid)
                rem_pipe.execute()
            return len(expired)
        except Exception as e:
            self._trip_circuit_breaker("CleanupExpired", e)
            return 0

    # ------------------------------------------------------------------
    # Workflow state helpers
    # ------------------------------------------------------------------
    @staticmethod
    def snapshot_from_state(
        state: Dict[str, Any],
        agent_id: str,
        session_id: str,
        user_id: str = "",
    ) -> SessionSnapshot:
        """
        Build a SessionSnapshot from SkillWorkflowState dict.
        
        Call this in the final_response node to capture current state.
        """
        response = state.get("response", "")
        return SessionSnapshot(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            current_skill=state.get("skill_name", ""),
            routing_method=state.get("routing_method", ""),
            routing_confidence=state.get("routing_confidence", 0.0),
            session_summary=state.get("past_conversation_summary", ""),
            preference=state.get("preference", ""),
            past_conversation_summary=state.get("past_conversation_summary", ""),
            conversation_turn_count=len(state.get("ongoing_conversation", [])),
            department=state.get("department_name", "General") or "General",
            model_name=state.get("model_name", ""),
            last_query=state.get("query", ""),
            last_response_preview=response[:200] if response else "",
            file_context_management=state.get("file_context_management_flag", False),
        )

    def apply_snapshot(
        self,
        snapshot: SessionSnapshot,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply a restored snapshot to workflow state dict.
        
        Only fills fields that are empty/missing in the current state
        (doesn't override fresh data from the current request).
        """
        if not snapshot:
            return state

        if not state.get("past_conversation_summary"):
            state["past_conversation_summary"] = snapshot.past_conversation_summary
        if not state.get("preference"):
            state["preference"] = snapshot.preference
        if not state.get("skill_name") and snapshot.current_skill:
            state["skill_name"] = snapshot.current_skill
            state["routing_method"] = snapshot.routing_method
            state["routing_confidence"] = snapshot.routing_confidence

        return state

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return self.client.ping()
        except Exception:
            return False
