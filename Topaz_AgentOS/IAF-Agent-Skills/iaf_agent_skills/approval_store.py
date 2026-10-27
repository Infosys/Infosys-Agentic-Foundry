"""
Approval Store - Redis-backed HITL (Human-in-the-Loop) approval queue.

Supports the Option B (Checkpoint & Resume) pattern:
1. Agent calls request_human_approval() tool
2. approval_store creates a Redis record + checkpoints agent state
3. Agent execution pauses cleanly
4. Human resolves via dashboard / API (hours/days later)
5. Resume engine restores agent state + injects decision

Redis Key Structure:
    iaf:approval:{approval_id}                → HASH (approval record)
    iaf:approval:pending:{tenant_id}          → ZSET (pending approvals by created_at)
    iaf:approval:history:{tenant_id}          → LIST (resolved approvals, capped at 500)
    iaf:approval:agent_state:{approval_id}    → STRING (JSON blob of agent state)

Design:
    - Each approval has a unique UUID
    - Agent state is checkpointed alongside the approval
    - SLA tracking with urgency-based timeouts
    - Fully async Redis operations
    - Graceful degradation if Redis unavailable
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Check for async redis
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

# TTL defaults (seconds)
APPROVAL_TTL_SECONDS = 7 * 24 * 60 * 60   # 7 days for pending approvals
STATE_TTL_SECONDS = 7 * 24 * 60 * 60       # 7 days for agent state checkpoints
HISTORY_MAX_LENGTH = 500                     # Keep last 500 resolved approvals per tenant

# SLA defaults by urgency (minutes)
DEFAULT_SLA = {
    "low": 480,       # 8 hours
    "medium": 120,    # 2 hours
    "high": 30,       # 30 minutes
    "critical": 10,   # 10 minutes
}


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    """
    A single HITL approval request created by an agent.
    """
    # Identity
    id: str                              # UUID
    tenant_id: str
    user_id: str                         # User whose agent created this
    skill: str                           # Active skill when approval was requested

    # Content (set by agent tool call)
    reason: str                          # Why approval is needed
    context: Dict[str, Any]              # Relevant data (amounts, entities, etc.)
    options: List[str]                   # e.g. ["Approve", "Reject", "Approve with conditions"]
    urgency: str = "medium"              # low | medium | high | critical

    # Rule reference (set by framework)
    rule_matched: Optional[str] = None   # Which approval_rule triggered this
    rule_type: Optional[str] = None      # "threshold" | "condition" | "always_require" | "agent_initiated"

    # Status
    status: str = "pending"
    decision: Optional[str] = None       # The chosen option
    decided_by: Optional[str] = None     # Who resolved it
    decision_note: Optional[str] = None  # Optional note from approver

    # Timestamps
    created_at: str = ""
    decided_at: Optional[str] = None
    sla_minutes: int = 120

    # Agent state reference
    agent_state_ref: Optional[str] = None  # Redis key for checkpointed agent state

    # Source context (chat, cron, supervisor, parallel, workflow)
    source: str = "chat"

    # Post-approval execution outcome (written by annotate_outcome after resume).
    # execution_status: "" (not started) | executing | done | failed
    execution_status: str = ""
    result_summary: Optional[str] = None   # Preview of what the skill produced
    trace_id: Optional[str] = None         # Trace of the post-approval execution
    error_preview: Optional[str] = None    # Error text when execution_status=failed
    completed_at: Optional[str] = None     # When the post-approval execution finished

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.sla_minutes:
            self.sla_minutes = DEFAULT_SLA.get(self.urgency, 120)

    def to_redis_hash(self) -> Dict[str, str]:
        """Serialize to Redis HASH (all values as strings)."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "skill": self.skill,
            "reason": self.reason,
            "context": json.dumps(self.context),
            "options": json.dumps(self.options),
            "urgency": self.urgency,
            "rule_matched": self.rule_matched or "",
            "rule_type": self.rule_type or "",
            "status": self.status,
            "decision": self.decision or "",
            "decided_by": self.decided_by or "",
            "decision_note": self.decision_note or "",
            "created_at": self.created_at,
            "decided_at": self.decided_at or "",
            "sla_minutes": str(self.sla_minutes),
            "agent_state_ref": self.agent_state_ref or "",
            "source": self.source or "chat",
            "execution_status": self.execution_status or "",
            "result_summary": self.result_summary or "",
            "trace_id": self.trace_id or "",
            "error_preview": self.error_preview or "",
            "completed_at": self.completed_at or "",
        }

    @classmethod
    def from_redis_hash(cls, data: Dict[str, str]) -> "ApprovalRequest":
        """Reconstruct from Redis HASH."""
        context = {}
        try:
            context = json.loads(data.get("context", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass

        options = ["Approve", "Reject"]
        try:
            options = json.loads(data.get("options", '["Approve", "Reject"]'))
        except (json.JSONDecodeError, TypeError):
            pass

        return cls(
            id=data.get("id", ""),
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id", ""),
            skill=data.get("skill", ""),
            reason=data.get("reason", ""),
            context=context,
            options=options,
            urgency=data.get("urgency", "medium"),
            rule_matched=data.get("rule_matched") or None,
            rule_type=data.get("rule_type") or None,
            status=data.get("status", "pending"),
            decision=data.get("decision") or None,
            decided_by=data.get("decided_by") or None,
            decision_note=data.get("decision_note") or None,
            created_at=data.get("created_at", ""),
            decided_at=data.get("decided_at") or None,
            sla_minutes=int(data.get("sla_minutes", 120)),
            agent_state_ref=data.get("agent_state_ref") or None,
            source=data.get("source", "chat"),
            execution_status=data.get("execution_status", ""),
            result_summary=data.get("result_summary") or None,
            trace_id=data.get("trace_id") or None,
            error_preview=data.get("error_preview") or None,
            completed_at=data.get("completed_at") or None,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API responses."""
        return asdict(self)


class ApprovalStore:
    """
    Redis-backed approval queue for HITL workflow.

    Supports:
    - Creating approvals with agent state checkpoint
    - Resolving (approve/reject) with decision metadata
    - Listing pending approvals per tenant
    - SLA tracking and expiry
    - History of resolved approvals
    """

    PREFIX = "iaf:approval"

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        if not REDIS_AVAILABLE:
            raise ImportError("redis package required: pip install redis")
        self._redis_url = redis_url
        self._client: Optional[Any] = None
        self._connected = False


    def _approval_key(self, approval_id: str) -> str:
        return f"{self.PREFIX}:{approval_id}"

    def _pending_key(self, tenant_id: str) -> str:
        return f"{self.PREFIX}:pending:{tenant_id}"

    def _history_key(self, tenant_id: str) -> str:
        return f"{self.PREFIX}:history:{tenant_id}"

    def _state_key(self, approval_id: str) -> str:
        return f"{self.PREFIX}:agent_state:{approval_id}"

    def _claim_key(self, approval_id: str) -> str:
        return f"{self.PREFIX}:claim:{approval_id}"


    async def connect(self) -> bool:
        try:
            self._client = aioredis.from_url(
                self._redis_url, decode_responses=True
            )
            await self._client.ping()
            self._connected = True
            logger.info("ApprovalStore connected to configured Redis endpoint")
            return True
        except Exception as e:
            self._connected = False
            logger.warning(f"ApprovalStore connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
            self._connected = False

    def _ok(self) -> bool:
        return self._client is not None and self._connected


    async def create_approval(
        self,
        request: ApprovalRequest,
        agent_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a new approval request and optionally checkpoint agent state.

        Returns the approval_id.
        """
        if not self._ok():
            raise ConnectionError("ApprovalStore not connected to Redis")

        approval_id = request.id

        async with self._client.pipeline(transaction=True) as pipe:
            pipe.hset(self._approval_key(approval_id), mapping=request.to_redis_hash())
            pipe.expire(self._approval_key(approval_id), APPROVAL_TTL_SECONDS)

            # Add to tenant pending set (score = created_at timestamp)
            created_ts = time.time()
            pipe.zadd(self._pending_key(request.tenant_id), {approval_id: created_ts})
            pipe.expire(self._pending_key(request.tenant_id), APPROVAL_TTL_SECONDS)

            # Checkpoint agent state if provided
            if agent_state:
                # Ensure we store a JSON string, not double-serialize if already a string
                if isinstance(agent_state, str):
                    state_json = agent_state
                else:
                    state_json = json.dumps(agent_state, default=str)
                state_key = self._state_key(approval_id)
                pipe.set(state_key, state_json)
                pipe.expire(state_key, STATE_TTL_SECONDS)
                pipe.hset(self._approval_key(approval_id), "agent_state_ref", state_key)

            await pipe.execute()

        logger.info(f"Approval created: {approval_id} (tenant={request.tenant_id}, urgency={request.urgency})")
        return approval_id


    async def resolve_approval(
        self,
        approval_id: str,
        decision: str,
        decided_by: str,
        decision_note: str = "",
    ) -> Optional[ApprovalRequest]:
        """
        Resolve a pending approval (approve / reject / etc).

        Returns the ApprovalRequest, or None if not found. An already-decided approval is
        returned unchanged — callers that run side effects must use claim_resolution(),
        which says whether THIS call made the decision.
        """
        request, _decided_now = await self.claim_resolution(
            approval_id, decision, decided_by, decision_note
        )
        return request

    async def claim_resolution(
        self,
        approval_id: str,
        decision: str,
        decided_by: str,
        decision_note: str = "",
    ) -> tuple[Optional[ApprovalRequest], bool]:
        """
        Decide a pending approval exactly once.

        Returns (request, decided_now). decided_now is True only for the single call that
        moved the approval out of "pending"; a repeat or a concurrent second click gets the
        existing decision and False, so it must not re-run the approval's side effects.
        """
        if not self._ok():
            raise ConnectionError("ApprovalStore not connected to Redis")

        key = self._approval_key(approval_id)
        data = await self._client.hgetall(key)
        if not data:
            return None, False

        request = ApprovalRequest.from_redis_hash(data)
        if request.status != "pending":
            logger.warning(f"Approval {approval_id} already resolved: {request.status}")
            return request, False

        # Two requests can both read "pending" above. SET NX lets exactly one of them proceed.
        claimed = await self._client.set(
            self._claim_key(approval_id), decided_by or "unknown",
            nx=True, ex=APPROVAL_TTL_SECONDS,
        )
        if not claimed:
            logger.warning(f"Approval {approval_id} is being resolved by a concurrent request")
            data = await self._client.hgetall(key)
            return (ApprovalRequest.from_redis_hash(data) if data else request), False

        # Build the resolved view up-front (payloads only — the authoritative
        # pending→resolved transition happens atomically in Redis below).
        now_iso = datetime.now(timezone.utc).isoformat()
        updates = {
            "status": "approved" if decision.lower() in ("approve", "approved", "yes") else "rejected",
            "decision": decision,
            "decided_by": decided_by,
            "decision_note": decision_note,
            "decided_at": now_iso,
        }
        history_entry = json.dumps({**request.to_dict(), **updates})

        _CAS_SCRIPT = (
            "local status = redis.call('HGET', KEYS[1], 'status')\n"
            "if not status then return 'NOTFOUND' end\n"
            "if status ~= 'pending' then return 'LOST' end\n"
            "redis.call('HSET', KEYS[1], 'status', ARGV[1], 'decision', ARGV[2],"
            " 'decided_by', ARGV[3], 'decision_note', ARGV[4], 'decided_at', ARGV[5])\n"
            "redis.call('ZREM', KEYS[2], ARGV[6])\n"
            "redis.call('LPUSH', KEYS[3], ARGV[7])\n"
            "redis.call('LTRIM', KEYS[3], 0, tonumber(ARGV[8]))\n"
            "return 'OK'\n"
        )
        outcome = await self._client.eval(
            _CAS_SCRIPT,
            3,
            key,
            self._pending_key(request.tenant_id),
            self._history_key(request.tenant_id),
            updates["status"],
            decision,
            decided_by,
            decision_note,
            now_iso,
            approval_id,
            history_entry,
            str(HISTORY_MAX_LENGTH - 1),
        )
        outcome = outcome.decode() if isinstance(outcome, (bytes, bytearray)) else outcome

        if outcome != "OK":
            logger.warning("Approval %s not resolved by this caller: %s", approval_id, outcome)
            return None

        # Merge updates into request object (this call is the winner).
        request.status = updates["status"]
        request.decision = decision
        request.decided_by = decided_by
        request.decision_note = decision_note
        request.decided_at = now_iso

        logger.info(f"Approval resolved: {approval_id} → {request.status} by {decided_by}")
        return request, True


    async def annotate_outcome(
        self,
        approval_id: str,
        *,
        execution_status: str,
        result_summary: str = "",
        trace_id: str = "",
        error_preview: str = "",
        completed_at: Optional[str] = None,
    ) -> bool:
        """Record the post-approval execution outcome onto the approval HASH.

        Called by the resume path (core HITL) and the observer resolve path AFTER
        the approved skill runs. Best-effort: returns False if Redis is down or the
        approval record is gone (expired). Only non-empty fields are written, so it
        can be called first with execution_status='executing' then 'done'/'failed'.
        """
        if not self._ok():
            return False
        key = self._approval_key(approval_id)
        try:
            if not await self._client.exists(key):
                return False
            mapping: Dict[str, str] = {"execution_status": execution_status or ""}
            if result_summary:
                mapping["result_summary"] = result_summary
            if trace_id:
                mapping["trace_id"] = trace_id
            if error_preview:
                mapping["error_preview"] = error_preview
            if execution_status in ("done", "failed", "rejected"):
                mapping["completed_at"] = completed_at or datetime.now(timezone.utc).isoformat()
            await self._client.hset(key, mapping=mapping)
            logger.info(f"Approval outcome annotated: {approval_id} -> {execution_status}")
            return True
        except Exception as exc:
            logger.warning(f"annotate_outcome failed for {approval_id}: {exc}")
            return False


    async def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Get a single approval by ID."""
        if not self._ok():
            return None
        data = await self._client.hgetall(self._approval_key(approval_id))
        if not data:
            return None
        return ApprovalRequest.from_redis_hash(data)

    async def get_pending(self, tenant_id: str, limit: int = 200,
                          newest_first: bool = False) -> List[ApprovalRequest]:
        """Get pending approvals for a tenant.

        limit defaults to 200 (was 50): the pending ZSET accumulates entries whose hash has
        been resolved/expired but were never zrem'd (e.g. crashed runs), so a small window
        would return only the OLDEST N and silently starve the newest real approvals — the
        exact bug where fresh HITL approvals never surfaced a button. Stale entries found in
        the scanned range are pruned here. Callers that must never miss a recent approval
        should pass newest_first=True.
        """
        if not self._ok():
            return []

        key = self._pending_key(tenant_id)
        # newest_first uses zrevrange so recent approvals are returned even behind a backlog.
        ids = (await self._client.zrevrange(key, 0, limit - 1) if newest_first
               else await self._client.zrange(key, 0, limit - 1))
        if not ids:
            return []

        results = []
        for aid in ids:
            data = await self._client.hgetall(self._approval_key(aid))
            if data and data.get("status") == "pending":
                results.append(ApprovalRequest.from_redis_hash(data))
            else:
                # Stale entry (resolved/expired, or hash gone) — prune from the pending set.
                await self._client.zrem(key, aid)

        return results

    async def get_history(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent resolved approvals for a tenant."""
        if not self._ok():
            return []
        entries = await self._client.lrange(self._history_key(tenant_id), 0, limit - 1)
        results = []
        for entry_str in entries:
            try:
                results.append(json.loads(entry_str))
            except json.JSONDecodeError:
                pass
        return results


    async def get_agent_state(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Load checkpointed agent state for resume."""
        if not self._ok():
            return None
        state_json = await self._client.get(self._state_key(approval_id))
        if not state_json:
            return None
        try:
            result = json.loads(state_json)
            # Guard against double-serialization: if result is still a string, parse again
            if isinstance(result, str):
                result = json.loads(result)
            return result
        except (json.JSONDecodeError, TypeError):
            return None

    async def save_agent_state(self, approval_id: str, state: dict) -> bool:
        """Save agent state checkpoint keyed by approval_id (for queue HITL resume)."""
        if not self._ok():
            return False
        try:
            state_json = json.dumps(state, default=str)
            key = self._state_key(approval_id)
            await self._client.set(key, state_json)
            await self._client.expire(key, STATE_TTL_SECONDS)
            return True
        except Exception as e:
            logger.warning("save_agent_state failed: %s", e)
            return False

    async def delete_agent_state(self, approval_id: str) -> bool:
        """Delete agent state checkpoint after resume."""
        if not self._ok():
            return False
        await self._client.delete(self._state_key(approval_id))
        return True


    async def delete_approval(
        self, approval_id: str, *, expected_tenant_id: Optional[str] = None
    ) -> bool:
        """Permanently remove a still-*pending* approval: record, pending-set entry, and state checkpoint.

        Only deletes when the approval is still ``pending``. A resolved approval is
        left intact so its history and checkpoint side effects are never dropped.
        The status check and deletion run atomically server-side (single Lua CAS)
        so a concurrent resolver cannot interleave and resurrect history/resume
        work while this path removes the checkpoint. When ``expected_tenant_id`` is
        supplied, a cross-tenant delete is refused. Returns True only if a pending
        approval belonging to the caller's tenant was deleted.
        """
        if not self._ok():
            return False
        key = self._approval_key(approval_id)
        data = await self._client.hgetall(key)
        if not data:
            return False
        tenant_id = data.get("tenant_id")
        if expected_tenant_id is not None and tenant_id != expected_tenant_id:
            # Caller is scoped to a different tenant — refuse cross-tenant delete.
            logger.warning(
                "Refused cross-tenant approval delete: %s (owner=%s caller=%s)",
                approval_id, tenant_id, expected_tenant_id,
            )
            return False
        # Atomic compare-and-delete: remove only if still 'pending' so we never
        # drop a resolved approval or race a concurrent resolver mid-resolution.
        _DEL_SCRIPT = (
            "local status = redis.call('HGET', KEYS[1], 'status')\n"
            "if not status then return 'NOTFOUND' end\n"
            "if status ~= 'pending' then return 'NOTPENDING' end\n"
            "redis.call('DEL', KEYS[1])\n"
            "redis.call('ZREM', KEYS[2], ARGV[1])\n"
            "redis.call('DEL', KEYS[3])\n"
            "return 'OK'\n"
        )
        outcome = await self._client.eval(
            _DEL_SCRIPT,
            3,
            key,
            self._pending_key(tenant_id or ""),
            self._state_key(approval_id),
            approval_id,
        )
        outcome = outcome.decode() if isinstance(outcome, (bytes, bytearray)) else outcome
        if outcome != "OK":
            # NOTFOUND: vanished between read and CAS. NOTPENDING: already resolved.
            logger.info("Approval not deleted (%s): %s", outcome, approval_id)
            return False
        logger.info("Approval deleted: %s (tenant=%s)", approval_id, tenant_id)
        return True

    async def delete_history_entry(self, tenant_id: str, approval_id: str) -> bool:
        """Remove a single resolved approval from tenant history by id."""
        if not self._ok():
            return False
        hkey = self._history_key(tenant_id)
        entries = await self._client.lrange(hkey, 0, -1)
        for entry_str in entries:
            try:
                rec = json.loads(entry_str)
            except (json.JSONDecodeError, TypeError):
                continue
            if rec.get("id") == approval_id or rec.get("approval_id") == approval_id:
                removed = await self._client.lrem(hkey, 1, entry_str)
                if removed:
                    logger.info("Approval history entry deleted: %s (tenant=%s)", approval_id, tenant_id)
                    return True
        return False


    async def get_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Get approval queue statistics."""
        if not self._ok():
            return {"connected": False}

        pending_count = await self._client.zcard(self._pending_key(tenant_id))
        history_count = await self._client.llen(self._history_key(tenant_id))

        return {
            "connected": True,
            "tenant_id": tenant_id,
            "pending_count": pending_count,
            "history_count": history_count,
        }



_approval_store: Optional[ApprovalStore] = None


def get_approval_store(redis_url: str = None) -> ApprovalStore:
    """Get or create the global ApprovalStore instance."""
    global _approval_store
    if _approval_store is None:
        url = redis_url or "redis://localhost:6379"
        _approval_store = ApprovalStore(redis_url=url)
    return _approval_store


async def init_approval_store(redis_url: str) -> ApprovalStore:
    """Initialize and connect the approval store."""
    store = get_approval_store(redis_url)
    await store.connect()
    return store
