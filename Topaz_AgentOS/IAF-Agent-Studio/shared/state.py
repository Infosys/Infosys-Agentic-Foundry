"""
IAF Agent Studio — Global State & Singletons

All shared mutable state: session managers, broadcasters, queues,
schedulers, and cross-router utility functions.

Import order matters: shared.config must be imported first (sets up sys.path),
then this module can safely import from IAF libraries.
"""

import asyncio
import dataclasses
import io
import json
import logging
import os
import re as _re
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

from shared.config import (
    SERVER_DIR, DATA_ROOT_PATH, SKILLS_PATH_PATH, REDIS_URL,
    QUEUE_BACKEND, USE_REDIS_SESSIONS, TWIN_TELEMETRY, TRACE_TELEMETRY,
    TELEMETRY_EXPORTERS, TELEMETRY_OTLP_ENDPOINT, TELEMETRY_OTLP_SERVICE_NAME,
    TELEMETRY_TIMEOUT_SECONDS, TELEMETRY_PREVIEW_LIMIT, TELEMETRY_EXPORT_AUDIT, TENANT_ID,
)
from shared.file_utils import atomic_write_json

logger = logging.getLogger("iaf_server")

redis_client = None
if REDIS_URL:
    try:
        import redis.asyncio as _aioredis
        redis_client = _aioredis.from_url(REDIS_URL, decode_responses=True)
    except Exception as _exc:
        logger.debug("redis_client init skipped: %s", _exc)

from agent_os import SafeKernel, create_kernel_runtime
from iaf_agent_skills import SkillAgent
from iaf_agent_skills.queue_manager import (
    create_queue_manager, QueueNames, QueueConfig, QueueBackend,
)
from iaf_agent_skills.scheduler import (
    CronScheduler, Job, JobRun, RunStatus, SyncRedisJobStore,
)
from iaf_agent_skills.task_integration import TaskIntegration, get_task_integration
from iaf_agent_skills.session_store import (
    RedisSessionStore, AgentStateSnapshot, get_session_store, init_session_store,
)
from iaf_agent_skills.approval_store import (
    ApprovalStore, ApprovalRequest, ApprovalStatus,
    get_approval_store, init_approval_store,
)
from twin_emitter import get_twin_emitter
from trace_emitter import get_trace_emitter
from telemetry_providers import build_telemetry_provider_fanout
from shared.capability_bootstrap import build_capability_registry, log_capability_registry


# OpenTelemetry must be configured before the fanout is built; off unless TELEMETRY_EXPORTERS includes otel.
from telemetry.otel_setup import configure_otel as _configure_otel, otel_selected as _otel_selected
if _otel_selected(TELEMETRY_EXPORTERS):
    _configure_otel(
        legacy_endpoint=TELEMETRY_OTLP_ENDPOINT,
        legacy_service_name=TELEMETRY_OTLP_SERVICE_NAME,
        tenant_id=TENANT_ID,
        export_audit=TELEMETRY_EXPORT_AUDIT,
    )
telemetry_provider_fanout = build_telemetry_provider_fanout(
    exporters=TELEMETRY_EXPORTERS,
    preview_limit=TELEMETRY_PREVIEW_LIMIT,
)
twin_emitter = get_twin_emitter(str(DATA_ROOT_PATH), telemetry_providers=telemetry_provider_fanout) if TWIN_TELEMETRY else None
trace_emitter = get_trace_emitter(str(DATA_ROOT_PATH), telemetry_providers=telemetry_provider_fanout) if TRACE_TELEMETRY else None
# Host services register into the engine bridge from shared.config, so the engine never imports Studio.


_queue_backend = QueueBackend.REDIS if QUEUE_BACKEND == "redis" else QueueBackend.MEMORY
queue_manager = create_queue_manager(QueueConfig(
    backend=_queue_backend,
    redis_url=REDIS_URL if _queue_backend == QueueBackend.REDIS else None,
    log_enqueue=False,
))
logger.info(
    "Lane Queue Manager: %s%s",
    _queue_backend.value.upper(),
    " (configured endpoint)" if _queue_backend == QueueBackend.REDIS else " (in-process, single server)",
)


task_integration = get_task_integration(redis_url=REDIS_URL)
logger.info("Task Integration enabled - chat tasks visible in Redis (iaf:chat:*)")


approval_store = get_approval_store(redis_url=REDIS_URL)
logger.info("HITL Approval Store initialized (iaf:approval:*)")


# redis_client must exist at module scope; callers import it and guard on `if redis_client:`.
try:
    import redis.asyncio as _aioredis
    redis_client = _aioredis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    logger.info("Shared async Redis client ready (auth blacklist / rate-limit / audit / maintenance)")
except Exception as _redis_client_err:  # redis package missing or unusable URL
    redis_client = None
    logger.warning(
        "Shared Redis client unavailable (%s); auth blacklist + rate limiting + maintenance "
        "leader-election degrade to in-process (per-instance)", _redis_client_err
    )


_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop):
    """Called from server lifespan() to capture the main event loop."""
    global _main_loop
    _main_loop = loop


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return the live main event loop. Use this from other modules instead of importing
    `_main_loop` by value — a `from shared.state import _main_loop` copy is bound at
    import time (before lifespan runs) and stays None, which silently breaks
    run_coroutine_threadsafe cleanup in background HITL/queue resume tasks."""
    return _main_loop


_LEARN_SIGNAL_PATTERNS = [
    # Rules / thresholds
    (_re.compile(r'\b(auto[- ]?approv|auto[- ]?reject|auto[- ]?flag)\b', _re.I), "rule"),
    (_re.compile(r'\b(always|never|from now on|going forward)\b', _re.I), "rule"),
    (_re.compile(r'\b(below|above|under|over|more than|less than|threshold|limit)\s+\$?\d', _re.I), "rule"),
    # Preferences
    (_re.compile(r'\b(i prefer|i like|i want you to|use .+ instead of)\b', _re.I), "preference"),
    (_re.compile(r'\b(default to|set default|change default)\b', _re.I), "preference"),
    # Corrections
    (_re.compile(r'\b(no,? always|no,? never|that\'?s wrong|incorrect|don\'?t do that)\b', _re.I), "correction"),
    # Exceptions / overrides
    (_re.compile(r'\b(skip|ignore|override|except for|exception)\b', _re.I), "exception"),
    # Explicit memory requests
    (_re.compile(r'\b(remember|memorize|don\'?t forget|keep in mind|note that)\b', _re.I), "rule"),
]


def _detect_learning_signals(content: str) -> Optional[dict]:
    """
    Detect if user message contains learning-worthy patterns.
    Returns {"type": "rule"|"preference"|..., "signals": [...]} or None.
    """
    if not content or len(content) < 5:
        return None
    signals = []
    detected_type = None
    for pattern, learn_type in _LEARN_SIGNAL_PATTERNS:
        match = pattern.search(content)
        if match:
            signals.append(match.group(0).lower())
            if not detected_type:
                detected_type = learn_type
    if signals:
        return {"type": detected_type, "signals": signals[:3]}
    return None



class DashboardBroadcaster:
    """
    Broadcasts real-time events to all connected dashboard WebSocket clients.

    Events:
      - approval_new / approval_resolved
      - task_started / task_completed
      - cron_started / cron_completed
      - agent_active
    """

    def __init__(self):
        self._clients: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws):
        """Register a dashboard client."""
        async with self._lock:
            self._clients.add(ws)
        logger.info("Dashboard client connected (%d total)", len(self._clients))

    async def disconnect(self, ws):
        """Unregister a dashboard client."""
        async with self._lock:
            self._clients.discard(ws)
        logger.info("Dashboard client disconnected (%d total)", len(self._clients))

    async def broadcast(self, event: dict):
        """Send event to all connected dashboard clients."""
        if not self._clients:
            return
        event["server_ts"] = datetime.now().isoformat()
        dead: list = []
        async with self._lock:
            for ws in self._clients:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Global dashboard broadcaster
dashboard = DashboardBroadcaster()

# Global Command Center queue broadcaster (same class, separate instance)
queue_broadcaster = DashboardBroadcaster()



class TwinBroadcaster:
    """
    Broadcasts real-time operational events to Digital Twin dashboard clients.

    Connected via /ws/twin — pushes task lifecycle, HITL, and skill usage
    events so the twin.html dashboard updates live without polling.
    """

    def __init__(self):
        self._clients: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws):
        async with self._lock:
            self._clients.add(ws)
        logger.info("Twin client connected (%d total)", len(self._clients))

    async def disconnect(self, ws):
        async with self._lock:
            self._clients.discard(ws)
        logger.info("Twin client disconnected (%d total)", len(self._clients))

    async def broadcast(self, event: dict):
        """Send event to all connected twin dashboard clients."""
        if not self._clients:
            return
        event["server_ts"] = datetime.now().isoformat()
        dead: list = []
        async with self._lock:
            for ws in self._clients:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Global twin broadcaster (None if telemetry disabled)
twin_broadcaster = TwinBroadcaster() if TWIN_TELEMETRY else None



class ChatConnectionRegistry:
    """
    Tracks active chat WebSocket connections by user key.
    Enables cross-channel notifications (e.g., dashboard approval → chat WS).
    Key format: '{tenant_id}:{user_id}'
    """

    def __init__(self):
        self._connections: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def register(self, tenant_id: str, user_id: str, ws):
        key = f"{tenant_id}:{user_id}"
        async with self._lock:
            self._connections[key] = ws
        logger.debug("Chat WS registered: %s (%d active)", key, len(self._connections))

    async def unregister(self, tenant_id: str, user_id: str):
        key = f"{tenant_id}:{user_id}"
        async with self._lock:
            self._connections.pop(key, None)
        logger.debug("Chat WS unregistered: %s (%d active)", key, len(self._connections))

    async def send_to_user(self, tenant_id: str, user_id: str, message: dict) -> bool:
        """Send a message to a specific user's chat WS. Returns True if delivered."""
        key = f"{tenant_id}:{user_id}"
        async with self._lock:
            ws = self._connections.get(key)
        if not ws:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:
            # Connection dead — clean up
            async with self._lock:
                self._connections.pop(key, None)
            return False


# Global chat connection registry
chat_registry = ChatConnectionRegistry()


# Research synthesis push on terminal workstream state; observe-only, never raises.

async def maybe_synthesize_research_workstream(
    workstream_name: str,
    tenant_id: str = "company",
) -> Optional[dict]:
    """If the named workstream was launched by research_orchestrator AND is
    now terminal, run synthesis + push the markdown to the originating
    chat session. Safe to call multiple times — synthesize_workstream is
    idempotent.

    Returns the synthesis envelope on success, None on skip/failure.
    """
    try:
        from iaf_agent_skills.workstream_store import WorkstreamStore
        from pathlib import Path

        store = WorkstreamStore(Path(DATA_ROOT_PATH) / "tenants" / tenant_id)
        try:
            ws = store.load(workstream_name)
        except FileNotFoundError:
            return None

        meta = ws.get("meta") or {}
        if meta.get("source") != "research_orchestrator":
            return None  # not a research workstream — quiet skip

        if ws.get("status") != "completed":
            return None  # not terminal yet — quiet skip

        # Avoid re-synthesising the same workstream
        if meta.get("synthesis") and meta["synthesis"].get("preview"):
            logger.debug(
                "maybe_synthesize: %s already has synthesis — skipping",
                workstream_name,
            )
            return None

        # Synthesis can take ~5-15s (light LLM). Run off the calling path.
        from services.research_synthesis import synthesize_workstream
        result = synthesize_workstream(workstream_name, tenant_id)

        if not result.get("ok"):
            logger.warning(
                "research synthesis failed for %s: %s",
                workstream_name, result.get("reason"),
            )
            return result

        # Route by user_id; chat_registry is keyed by user.
        parent_user_id = meta.get("parent_user_id") or ws.get("owner") or ""
        if parent_user_id:
            payload = {
                "type": "research_synthesis_ready",
                "workstream_name": workstream_name,
                "markdown": result["markdown"],
                "confidence": result["confidence"],
                "stats": result["stats"],
                "url": f"/static/workstream_detail.html?name={workstream_name}",
            }
            try:
                await chat_registry.send_to_user(tenant_id, parent_user_id, payload)
                logger.info(
                    "research synthesis pushed to chat: ws=%s user=%s confidence=%s",
                    workstream_name, parent_user_id, result["confidence"],
                )
            except Exception as push_err:
                # Connection may be dead. Synthesis is persisted to disk
                # regardless — user can refresh detail page to see it.
                logger.warning(
                    "research synthesis WS push failed for ws=%s user=%s: %s",
                    workstream_name, parent_user_id, push_err,
                )
        else:
            logger.info(
                "research synthesis ready for %s but no parent_user_id — "
                "persisted to disk only",
                workstream_name,
            )

        return result
    except Exception as outer_err:
        logger.warning("maybe_synthesize_research_workstream error: %s", outer_err)
        return None



async def checkpoint_hitl_if_needed(
    agent,
    tenant_id: str,
    user_id: str,
    skill_name: str,
    source: str = "chat",
) -> Optional[dict]:
    """Persist an HITL approval checkpoint if the agent has one pending.

    Returns the hitl_approval dict (for embedding in WS responses) or None.
    """
    if not getattr(agent, "approval_pending", None):
        return None

    ap = agent.approval_pending
    hitl_data = {
        "approval_id": ap.get("approval_id"),
        "reason": ap.get("reason"),
        "urgency": ap.get("urgency"),
        "context": ap.get("context"),
        "options": ap.get("options"),
        "sla_minutes": ap.get("sla_minutes"),
    }

    # Stream-intercept records persist for cold resume but skip the hitl_approval_new broadcast.
    _is_stream_intercept = (ap.get("context") or {}).get("resume_kind") == "stream_intercept"

    # Persist to Redis
    try:
        # create_approval re-stamps timestamps, so do not rewrite an existing row.
        already = False
        try:
            already = bool(await approval_store.get_approval(ap["approval_id"]))
        except Exception:
            already = False
        if not already:
            approval_req = ApprovalRequest(
                id=ap["approval_id"],
                tenant_id=tenant_id,
                user_id=user_id,
                skill=ap.get("skill", skill_name),
                reason=ap.get("reason", ""),
                context=ap.get("context", {}),
                options=ap.get("options", ["Approve", "Reject"]),
                urgency=ap.get("urgency", "medium"),
                rule_matched=ap.get("rule_matched"),
                rule_type=ap.get("rule_type"),
                sla_minutes=ap.get("sla_minutes", 120),
                source=source,
            )
            agent_state_snapshot = agent.export_state()
            await approval_store.create_approval(
                approval_req,
                agent_state=agent_state_snapshot,
            )
            try:
                from iaf_agent_skills.capture_events import emit_agentpro_reward

                _ctx = ap.get("context") or {}
                emit_agentpro_reward(
                    data_root=DATA_ROOT_PATH,
                    tenant_id=tenant_id,
                    agent_id=str(getattr(getattr(agent, "kernel", None), "agent_id", "") or "enterprise_agent"),
                    channel="human_approval",
                    raw_label="created",
                    target_id=str(ap.get("approval_id") or ""),
                    trajectory_id=str(_ctx.get("trace_id") or getattr(agent, "_active_trace_id", "") or ap.get("approval_id") or ""),
                    judge_id=user_id,
                    source_event_id=str(ap.get("approval_id") or ""),
                    source_trace_id=str(_ctx.get("trace_id") or getattr(agent, "_active_trace_id", "") or ""),
                    metadata={
                        "source": source,
                        "skill": ap.get("skill", skill_name),
                        "reason": ap.get("reason", ""),
                        "urgency": ap.get("urgency", "medium"),
                        "context": _ctx,
                        "stream_intercept": _is_stream_intercept,
                    },
                )
            except Exception as rl_err:
                logger.debug("RL HITL approval-created reward skipped: %s", rl_err)
            # Use sys.__stdout__ to bypass any stdout redirect (cron captures stdout)
            sys.__stdout__.write(f"🔔 HITL approval persisted to Redis: {ap['approval_id']} [source={source}]\n")
            sys.__stdout__.flush()
    except Exception as hitl_err:
        sys.__stdout__.write(f"⚠️ HITL Redis persist failed: {hitl_err}\n")
        sys.__stdout__.flush()
        hitl_data["_persist_failed"] = True

    if _is_stream_intercept:
        return None

    # Inline-chat HITL stays off the Command Center board; persisted above, broadcast skipped.
    if (ap.get("context") or {}).get("resume_kind") == "inline_chat":
        return hitl_data

    # Broadcast to dashboard (business-HITL surface only)
    try:
        await dashboard.broadcast({
            "type": "hitl_approval_new",
            "approval_id": ap.get("approval_id"),
            "user_id": user_id,
            "skill": skill_name,
            "reason": ap.get("reason"),
            "urgency": ap.get("urgency"),
            "context": ap.get("context"),
            "sla_minutes": ap.get("sla_minutes"),
            "source": source,
        })
    except Exception:
        pass  # dashboard may not be initialized yet (cron at startup)

    return hitl_data


async def checkpoint_rlm_holds_if_needed(
    agent,
    tenant_id: str,
    user_id: str,
    skill_name: str,
    source: str = "chat",
) -> list:
    """Persist RLM propose-then-apply holds as pending approval cards (Command Center).

    Mirrors checkpoint_hitl_if_needed but for the RLM apply-phase, which stages N proposals
    on agent._rlm_proposed (unlike the single-slot approval_pending). Reuses ApprovalStore +
    the dashboard broadcast — no new approval system. No-op unless the apply-phase populated
    the list; fail-safe (Redis down → create_approval no-ops, turn is unaffected). Each card's
    context carries resume_kind='connector_action', action='hold_payment' so the resolve
    endpoint runs the deterministic executor (no LLM re-plan) on Approve.

    Returns the list of created approval ids.
    """
    proposed = getattr(agent, "_rlm_proposed", None)
    if not proposed:
        return []
    # Consume once so a re-render/re-pass can't duplicate the cards.
    try:
        agent._rlm_proposed = []
    except Exception:
        pass

    import uuid as _uuid
    created = []
    for pa in proposed:
        try:
            approval_id = f"rlmhold-{_uuid.uuid4().hex[:12]}"
            ctx = {
                "resume_kind": "connector_action",
                # Use the proposal's own kind, defaulting to hold_payment.
                "action": str(pa.get("kind") or "hold_payment"),
                "invoice_id": pa.get("invoice_id", ""),
                "vendor": pa.get("vendor", ""),
                "amount": pa.get("amount", 0),
                "args": pa.get("args", ""),
                "trace_id": getattr(agent, "_active_trace_id", "") or "",
            }
            reason = pa.get("rationale", "") or f"Payment hold: {pa.get('args', '')}"
            approval_req = ApprovalRequest(
                id=approval_id,
                tenant_id=tenant_id,
                user_id=user_id,
                skill=skill_name,
                reason=reason,
                context=ctx,
                options=["Approve", "Reject"],
                urgency="high",
                rule_type="agent_initiated",
                sla_minutes=120,
                source=source,
            )
            # No agent_state: these are deterministic (executed from ctx args on Approve),
            # so the background NL-resume path is intentionally not engaged.
            await approval_store.create_approval(approval_req)
            created.append(approval_id)
            try:
                await dashboard.broadcast({
                    "type": "hitl_approval_new",
                    "approval_id": approval_id,
                    "user_id": user_id,
                    "skill": skill_name,
                    "reason": reason,
                    "urgency": "high",
                    "context": ctx,
                    "sla_minutes": 120,
                    "source": source,
                })
            except Exception:
                pass  # dashboard may not be initialized yet
        except Exception as hold_err:
            logger.warning("RLM apply-phase: hold approval create failed: %s", hold_err)

    if created:
        try:
            sys.__stdout__.write(
                f"🔔 RLM apply-phase: {len(created)} hold approval(s) persisted [source={source}]\n")
            sys.__stdout__.flush()
        except Exception:
            pass
    return created


def stream_intercept_approval_id(agent) -> Optional[str]:
    """The durable approval_id of the currently-armed stream-intercept block, or None."""
    ap = getattr(agent, "approval_pending", None)
    if isinstance(ap, dict) and (ap.get("context") or {}).get("resume_kind") == "stream_intercept":
        return ap.get("approval_id")
    return None


async def reconcile_stream_intercept_durable(agent, prior_id, tenant_id, user_id, decision):
    """Reconcile the durable ApprovalStore row after a WARM interactive approve/reject.

    The warm path executes in-process and does NOT go through the durable resolver, so we
    keep ApprovalStore clean here: resolve+delete the row for the call we just consumed;
    if continue-the-turn re-paused on a NEW gated call, persist a fresh durable row so the
    next step is also cold-resumable; if the turn completed, drop the now-stale pending.
    """
    if prior_id:
        try:
            await approval_store.resolve_approval(
                approval_id=prior_id, decision=decision, decided_by=user_id,
                decision_note="resolved via interactive approve",
            )
        except Exception as e:
            logger.debug("reconcile resolve_approval failed (%s): %s", prior_id, e)
        try:
            await approval_store.delete_agent_state(prior_id)
        except Exception as e:
            logger.debug("reconcile delete_agent_state failed (%s): %s", prior_id, e)

    cur_id = stream_intercept_approval_id(agent)
    skill_name = getattr(agent, "current_skill", "") or ""
    if cur_id and cur_id != prior_id:
        # Re-paused on a new gated call → make the next step durable too.
        try:
            await checkpoint_hitl_if_needed(agent, tenant_id, user_id, skill_name, source="chat")
        except Exception as e:
            logger.debug("reconcile re-checkpoint failed: %s", e)
    elif cur_id and cur_id == prior_id:
        # Completed warm — the consumed row is resolved; drop the now-stale pending.
        agent.approval_pending = None



def _parse_queue_ingest_task(task: str, job: Job) -> dict:
    """Parse the queue_ingest skill prompt into a queue item payload."""
    text = task or ""

    def _field(name: str) -> str:
        pattern = (
            rf"(?:^|,\s*){_re.escape(name)}\s*:\s*"
            rf"(.*?)"
            rf"(?=,\s*(?:skill|priority|title|description|domain)\s*:|,\s*BUCKET_SECONDS\s*=|$)"
        )
        match = _re.search(pattern, text, flags=_re.IGNORECASE | _re.DOTALL)
        return match.group(1).strip() if match else ""

    bucket_match = _re.search(r"(?:^|,\s*)BUCKET_SECONDS\s*=\s*(\d+)", text, flags=_re.IGNORECASE)
    target_skill = _field("skill") or getattr(job, "entity_id", None) or "general"
    title = _field("title") or str(getattr(job, "name", "scheduled work")).replace("-", " ").title()
    description = _field("description") or text or title
    priority = (_field("priority") or "P3").upper()
    domain = _field("domain") or (job.tags[0] if getattr(job, "tags", None) else "general")

    payload = {
        "tenant_id": job.tenant_id or "company",
        "domain": domain,
        "entity_id": target_skill,
        "title": title,
        "description": description,
        "priority": priority,
    }
    if bucket_match:
        payload["bucket_seconds"] = int(bucket_match.group(1))
    return payload


def _queue_ingest_direct(job: Job) -> dict:
    """Insert queue_ingest cron jobs directly, avoiding shell/curl indirection."""
    import uuid as _uuid
    from cc_queue.db import init_db_path as _init_db_path, get_db as _get_queue_db
    from cc_queue.models import IngestWebhook
    from routers.queue import _compute_external_id

    _init_db_path(SERVER_DIR)
    db = _get_queue_db()
    payload = _parse_queue_ingest_task(job.task, job)
    body = IngestWebhook(**payload)
    trace_id = _uuid.uuid4().hex
    item = {
        "id": f"CC-{_uuid.uuid4().hex[:8].upper()}",
        "tenant_id": body.tenant_id,
        "external_id": _compute_external_id(body, source="cron"),
        "domain": body.domain,
        "entity_id": body.entity_id,
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "trace_id": trace_id,
        "source": "cron",
        "status": "queued",
    }
    inserted = db.insert_item(item)
    if inserted:
        item["deduped"] = False
        return item

    existing = db.get_item_by_external_id(item["external_id"])
    if not existing:
        raise RuntimeError(f"Queue insert deduped but no existing item found for {item['external_id']}")

    existing["deduped"] = True
    if existing.get("status") == "failed":
        db.update_item(
            existing["id"],
            status="queued",
            retry_count=0,
            routed_skill=None,
            routing_reason=None,
            trace_id=trace_id,
        )
        existing = db.get_item_by_external_id(item["external_id"]) or existing
        existing["deduped"] = True
        existing["requeued"] = True
    elif existing.get("status") in {"done", "dlq"}:
        item["external_id"] = f"{item['external_id']}:run:{_uuid.uuid4().hex[:8]}"
        inserted = db.insert_item(item)
        if not inserted:
            raise RuntimeError(f"Queue insert failed for fresh run {item['external_id']}")
        item["deduped"] = False
        item["fresh_after_terminal_duplicate"] = True
        return item
    return existing


def _should_post_cron_audit_queue_item(job: Job) -> bool:
    """Return whether cron completion should add a done row to Queue Monitor.

    `queue_ingest` jobs already create the real Command Center item. Adding a
    second `[CRON] ...` row makes the UI look as if the business queue work went
    straight to `done`, so skip audit rows for that bridge.
    """
    return (getattr(job, "skill_name", "") or "").strip() != "queue_ingest"


def _run_eval_suite_cron(job: Job) -> dict:
    """Run an eval suite from cron without invoking the LLM agent path."""
    from shared.evals_service import run_eval_suite

    _job_params = job.params if isinstance(job.params, dict) else {}
    return run_eval_suite(
        job.task,
        tenant_id=job.tenant_id,
        agent_id=job.agent_id,
        user_id=job.user_id,
        trigger="cron",
        metadata={
            "job_id": job.id,
            "job_name": job.name,
            "params": _job_params,
        },
    )


def _cron_executor(job: Job) -> str:
    """Execute a scheduled job using SkillAgent."""
    import io as _io
    import time as _time

    # Broadcast cron start to dashboard (fire-and-forget from sync context)
    try:
        if _main_loop and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(dashboard.broadcast({
                "type": "cron_started",
                "job_name": job.name,
                "skill": job.skill_name,
            }), _main_loop)
    except Exception:
        pass

    # Capture stdout to prevent broken pipe errors when no WebSocket is connected
    captured_output = _io.StringIO()
    original_stdout = sys.stdout

    # Mint the cron trace_id up front so schedule hooks share it as parent_trace_id.
    import uuid as _uuid_cron
    _cron_trace_id = _uuid_cron.uuid4().hex
    _schedule_ctx = {
        "tenant_id": job.tenant_id,
        "user_id": job.user_id,
        "agent_id": job.agent_id,
        "skill_name": job.skill_name,
        "entrypoint": "cron",
        "cron_job_id": getattr(job, "id", ""),
        "trace_id": _cron_trace_id,
        "parent_trace_id": _cron_trace_id,
    }
    _schedule_start_ms = _time.time() * 1000

    try:
        # Redirect stdout to buffer
        sys.stdout = captured_output

        kernel = create_kernel_runtime(
            data_root=str(DATA_ROOT_PATH),
            tenant_id=job.tenant_id,
            agent_id=job.agent_id,
            user_id=job.user_id,
            require_confirmation=False  # Scheduled jobs run unattended
        )
        skills_path = str(SKILLS_PATH_PATH)
        agent = SkillAgent(
            kernel=kernel, skills_path=skills_path,
            user_id=job.user_id, trace_emitter=trace_emitter,
            enterprise_root=str(DATA_ROOT_PATH),
        )
        agent.auto_run = True  # Cron jobs run unattended — no confirmation gates
        agent._evidence_execution_source = "cron"

        # Attach service principal so external access gates are enforced
        try:
            from security.dependencies import make_service_principal, make_agent_entitlement_checker
            _cron_principal = make_service_principal(job.tenant_id, "cron", user_id=job.user_id)
            agent.set_entitlement_context(_cron_principal, make_agent_entitlement_checker(_cron_principal))
        except Exception as _ent_err:
            logger.warning("Cron entitlement context setup failed (non-fatal): %s", _ent_err)

        # A blocking deny skips agent.run() but still records the lifecycle audit.
        _hr = getattr(agent, "hook_runner", None)
        _gate = None
        if _hr is not None:
            try:
                _gate = _hr.run_before_schedule_fire(
                    _schedule_ctx,
                    job_name=job.name,
                    cron_expr=getattr(job, "cron", ""),
                )
            except Exception as _hexc:
                logger.warning("Cron BeforeScheduleFire hook error (non-fatal): %s", _hexc)

        if _gate is not None and _gate.blocked:
            original_stdout.write(
                f"⏰ [CRON:{job.name}] Skipped by BeforeScheduleFire hook: {_gate.reason}\n"
            )
            _duration_ms = int(_time.time() * 1000 - _schedule_start_ms)
            try:
                _hr.run_after_schedule_fire(
                    _schedule_ctx,
                    job_name=job.name,
                    duration_ms=_duration_ms,
                    response=f"skipped by hook: {_gate.reason}",
                )
            except Exception:  # pragma: no cover - observe-only
                pass
            return f"skipped by BeforeScheduleFire: {_gate.reason}"

        if job.task == "batch_extract_knowledge":
            hours = 24  # Default: last 24 hours of episodes
            result_data = agent.memory.batch_extract_knowledge(hours_back=hours)
            result = json.dumps(result_data)
        elif (job.skill_name or "").strip() == "automation":
            from shared.automations_service import run_automation

            _job_params = job.params if isinstance(job.params, dict) else {}
            automation_result = run_automation(
                job.task,
                tenant_id=job.tenant_id,
                agent_id=job.agent_id,
                user_id=job.user_id,
                trigger="cron",
                context={
                    "job_id": job.id,
                    "job_name": job.name,
                    "params": _job_params,
                },
            )
            result = automation_result.get("summary") or json.dumps(automation_result)
        elif (job.skill_name or "").strip() == "eval_suite":
            eval_result = _run_eval_suite_cron(job)
            result = eval_result.get("summary") or json.dumps(eval_result)
        elif (job.skill_name or "").strip() == "queue_ingest":
            _queued_item = _queue_ingest_direct(job)
            result = (
                "✅ **Item posted to queue. Queue processor will pick it up within a few seconds.**\n\n"
                f"**Details:**\n- **Queue Item:** {_queued_item['id']}\n"
                f"- **Skill:** {_queued_item.get('entity_id') or 'auto-route'}\n"
                f"- **Priority:** {_queued_item.get('priority') or 'P3'}\n"
                f"- **Title:** {_queued_item.get('title') or ''}\n"
                f"- **Trace ID:** {_queued_item.get('trace_id') or ''}\n"
            )
            if _queued_item.get("deduped"):
                result += "- **Dedup:** reused existing queue item for this schedule window\n"
            if _queued_item.get("requeued"):
                result += "- **Recovery:** requeued a previously failed duplicate item\n"
            if _main_loop and _main_loop.is_running():
                from routers.queue import _broadcast as _q_broadcast
                asyncio.run_coroutine_threadsafe(
                    _q_broadcast({"type": "item_created", "item": _queued_item}),
                    _main_loop,
                )
        else:
            result = agent.run(job.task, skill_name=job.skill_name, skip_memory=True)

        evidence_trace_id = None
        evidence_count = 0
        try:
            _cron_evidence = getattr(agent, "_evidence_bundle", None)
            if _cron_evidence and (_cron_evidence.get("documents") or _cron_evidence.get("evidence_items")):
                _cron_evidence["execution_source"] = "cron"
                _stored = capability_registry.resolve("evidence_collector").persist(_cron_evidence)
                evidence_trace_id = _cron_evidence.get("trace_id")
                evidence_count = int(_stored.get("evidence_items_count") or _cron_evidence.get("evidence_items_count") or 0)
                original_stdout.write(
                    f"⏰ [CRON:{job.name}] Evidence stored trace_id={evidence_trace_id} items={evidence_count}\n"
                )
        except Exception as ev_exc:
            logger.warning("Cron evidence persistence failed for '%s': %s", job.name, ev_exc)

        # HITL checkpoint: if the agent paused for approval, persist it
        try:
            if _main_loop and _main_loop.is_running() and getattr(agent, "approval_pending", None):
                future = asyncio.run_coroutine_threadsafe(
                    checkpoint_hitl_if_needed(
                        agent, job.tenant_id, job.user_id,
                        job.skill_name, source="cron",
                    ),
                    _main_loop,
                )
                future.result(timeout=10)  # wait up to 10s for Redis write
                original_stdout.write(
                    f"⏰ [CRON:{job.name}] HITL approval checkpoint saved\n"
                )
        except Exception as hitl_exc:
            original_stdout.write(
                f"⚠️ [CRON:{job.name}] HITL checkpoint failed: {hitl_exc}\n"
            )

        # Log captured activity
        activity = captured_output.getvalue()
        if activity:
            original_stdout.write(f"⏰ [CRON:{job.name}] Activity captured ({len(activity)} chars)\n")

        # Broadcast cron completion to dashboard
        try:
            cron_status = "paused_for_approval" if getattr(agent, "approval_pending", None) else "success"
            if _main_loop and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(dashboard.broadcast({
                    "type": "cron_completed",
                    "job_name": job.name,
                    "skill": job.skill_name,
                    "status": cron_status,
                }), _main_loop)
        except Exception:
            pass

        try:
            if not _should_post_cron_audit_queue_item(job):
                return result
            import uuid as _uuid
            from cc_queue.db import init_db_path as _init_db_path, get_db as _get_queue_db
            _init_db_path(SERVER_DIR)
            _db = _get_queue_db()
            _summary = (result or "")[:300].replace("\n", " ")
            # external_id is the UNIQUE dedup key; scheduled seconds collapse retries into one row.
            _scheduled_epoch = int(datetime.utcnow().timestamp())
            _item = {
                "id": f"CC-{_uuid.uuid4().hex[:8].upper()}",
                "tenant_id": job.tenant_id or "company",
                "external_id": f"cron-{job.id}-{_scheduled_epoch}",
                "domain": getattr(job, "domain", None) or (job.tags[0] if job.tags else "general"),
                "entity_id": job.skill_name or "agent",
                "title": f"[CRON] {job.name}",
                "description": _summary,
                "priority": getattr(job, "priority", "P3") or "P3",
                "source": "cron",
                "trace_id": evidence_trace_id,
                # status='done': the skill already ran; 'queued' would let the processor re-execute it.
                "status": "done",
            }
            _db.insert_item(_item)
            # Broadcast to queue monitor WebSocket
            if _main_loop and _main_loop.is_running():
                from routers.queue import _broadcast as _q_broadcast
                asyncio.run_coroutine_threadsafe(
                    _q_broadcast({"type": "item_created", "item": _item}),
                    _main_loop,
                )
        except Exception as _qe:
            logger.error("CRON queue post failed for '%s': %s", job.name, _qe, exc_info=True)
            original_stdout.write(f"⚠️ [CRON:{job.name}] Queue post failed: {_qe}\n")

        # Promote evidence_trace_id only when present; never overwrite trace_id with an empty string.
        try:
            if _hr is not None:
                _after_ctx = dict(_schedule_ctx)
                if evidence_trace_id:
                    _after_ctx["evidence_trace_id"] = evidence_trace_id
                _hr.run_after_schedule_fire(
                    _after_ctx,
                    job_name=job.name,
                    duration_ms=int(_time.time() * 1000 - _schedule_start_ms),
                    response=(result or "")[:500],
                )
        except Exception as _hexc:  # pragma: no cover - observe-only must never raise
            logger.debug("Cron AfterScheduleFire hook error (non-fatal): %s", _hexc)

        return result
    except Exception as exc:
        # Broadcast cron failure
        try:
            if _main_loop and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(dashboard.broadcast({
                    "type": "cron_completed",
                    "job_name": job.name,
                    "skill": job.skill_name,
                    "status": "failed",
                    "error": str(exc),
                }), _main_loop)
        except Exception:
            pass
        try:
            _hr_err = locals().get("_hr")
            if _hr_err is not None:
                _hr_err.run_on_schedule_error(
                    _schedule_ctx,
                    job_name=job.name,
                    error_msg=str(exc)[:500],
                    duration_ms=int(_time.time() * 1000 - _schedule_start_ms),
                )
        except Exception:  # pragma: no cover - observe-only must never raise
            pass
        raise
    finally:
        # Always restore stdout
        sys.stdout = original_stdout


def _make_cron_store():
    """Try Redis first; fall back to SQLite when Redis is unavailable."""
    try:
        store = SyncRedisJobStore(redis_url=REDIS_URL)
        store._ensure_connected()
        logger.info("Cron store: Redis (%s)", REDIS_URL)
        return store
    except Exception as exc:
        logger.warning(
            "Cron store: Redis unavailable (%s) — falling back to SQLite. "
            "Jobs are local to this process; set REDIS_URL to enable distributed scheduling.",
            exc,
        )
        from iaf_agent_skills.scheduler.store import SQLiteJobStore
        return SQLiteJobStore()


cron_scheduler = CronScheduler(
    store=_make_cron_store(),
    executor=_cron_executor,
    check_interval=60,  # Check every minute
    max_concurrent_jobs=5,
)
logger.info("Cron Scheduler initialized - View Redis jobs: redis-cli KEYS 'iaf:scheduler:*'")


capability_registry = build_capability_registry(
    trace_emitter=trace_emitter,
    twin_emitter=twin_emitter,
    queue_manager=queue_manager,
    cron_scheduler=cron_scheduler,
    approval_store=approval_store,
)
log_capability_registry(capability_registry)



class ActivityStream(io.StringIO):
    """
    Custom stream that captures print output and sends it to WebSocket as activity events.
    Used to stream agent's internal activity (loading memory, calling LLM, etc.) to UI.
    """

    def __init__(self, callback: Callable[[str], None], original_stdout):
        super().__init__()
        self.callback = callback
        self.original_stdout = original_stdout
        self.buffer = ""

    def write(self, s: str):
        # Also write to original stdout for debugging
        if self.original_stdout:
            self.original_stdout.write(s)

        # Accumulate in buffer
        self.buffer += s

        # When we have a complete line, send it
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            # Process all complete lines
            for line in lines[:-1]:
                line = line.strip()
                # Only send lines with activity markers (📥, 🧠, 📝, etc.)
                if line and any(marker in line for marker in ['📥', '🧠', '📝', '💾', '🔍', '⚡', '✨']):
                    try:
                        self.callback(line)
                    except Exception:
                        pass  # Don't break if WebSocket fails
            # Keep the incomplete line in buffer
            self.buffer = lines[-1]

        return len(s)

    def flush(self):
        if self.original_stdout:
            self.original_stdout.flush()



class SessionState:
    """Holds agent instances per user session (in-memory, single-server)."""

    # Maximum number of concurrent session agents per user (LRU eviction)
    MAX_SESSIONS_PER_USER = 5

    # Agent cache entries survive until eviction, so liveness needs a bounded window.
    ONLINE_IDLE_SECONDS = 300

    def __init__(self):
        self.agents: Dict[str, SkillAgent] = {}
        self.kernels: Dict[str, SafeKernel] = {}
        # Per-session agent pool: user_key → {session_id: SkillAgent}
        self._session_pool: Dict[str, Dict[str, SkillAgent]] = {}
        # session key → epoch seconds of last use, for ONLINE_IDLE_SECONDS
        self.last_active: Dict[str, float] = {}
        # Conversation state stashed on config-change eviction: user_key -> {session_id: state_export}.
        self._session_restore: Dict[str, Dict[str, dict]] = {}

    def touch(self, key: str) -> None:
        """Record that this session key was just used."""
        self.last_active[key] = _time.time()

    def agent_liveness(self, tenant_id: str) -> Dict[str, dict]:
        """Per-agent liveness for one tenant: ``{agent_id: {...}}``.

        An agent is online when at least one of its sessions was used within
        ``ONLINE_IDLE_SECONDS``. This is deliberately not "an instance exists" —
        cached instances outlive the person who created them.

        Limitation: this answers for **this process only**. ``self.agents`` is a
        local cache, so behind more than one replica the result covers the
        replica that serves the request, not the deployment. Cross-replica
        liveness needs the signal published to a shared store and is not
        attempted here.
        """
        now = _time.time()
        prefix = f"{tenant_id}:"
        out: Dict[str, dict] = {}
        for key in list(self.agents):
            if not key.startswith(prefix):
                continue
            parts = key.split(":")
            if len(parts) < 2:
                continue
            agent_id = parts[1]
            last = self.last_active.get(key)
            entry = out.setdefault(
                agent_id, {"is_online": False, "last_active": None, "session_count": 0}
            )
            entry["session_count"] += 1
            if last is None:
                continue
            if entry["last_active"] is None or last > entry["last_active"]:
                entry["last_active"] = last
            if now - last <= self.ONLINE_IDLE_SECONDS:
                entry["is_online"] = True
        for entry in out.values():
            if entry["last_active"] is not None:
                entry["last_active"] = datetime.fromtimestamp(
                    entry["last_active"], tz=timezone.utc
                ).isoformat()
        return out

    async def connect(self) -> bool:
        """In-memory development state has no external startup dependency."""
        return True

    async def health_check(self) -> bool:
        """In-memory development state is ready while this process is alive."""
        return True

    async def disconnect(self) -> None:
        """Match the Redis state lifecycle without requiring special handling."""

    def get_or_create(self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user") -> SkillAgent:
        """Get or create agent for user session."""
        key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"

        if key not in self.agents:
            # Load optional local mount for this user
            _local = load_local_mount(tenant_id, user_id)

            # Create kernel
            kernel = create_kernel_runtime(
                data_root=str(DATA_ROOT_PATH),
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=user_id,
                user_role=user_role,
                require_confirmation=True,
                confirm_operations=["write", "delete"],
                confirm_paths=["/me/"],
                local_mount=_local,
            )
            self.kernels[key] = kernel

            # Create agent
            skills_path = str(SKILLS_PATH_PATH)
            agent = SkillAgent(
                kernel=kernel,
                skills_path=skills_path,
                user_id=user_id,
                trace_emitter=trace_emitter,
                enterprise_root=str(DATA_ROOT_PATH),
            )
            self.agents[key] = agent

        # Every retrieval counts as use, not just creation — a long-lived session
        # that is actively chatting must keep reading as online.
        self.touch(key)
        return self.agents[key]

    def remove(self, tenant_id: str, user_id: str, agent_id: str = "enterprise_agent", user_role: str = "user"):
        """Evict an agent session from the pool (used by queue processor after job completes)."""
        key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        self.agents.pop(key, None)
        self.kernels.pop(key, None)
        self.last_active.pop(key, None)

    def evict_agent(self, agent_id: str, preserve_sessions: bool = False,
                    tenant_id: Optional[str] = None) -> int:
        """Evict EVERY cached instance of ``agent_id`` — template agents, kernels,
        and active per-session clones — so the next request rebuilds from the
        current on-disk config.

        Mutating endpoints (edit tools/skills/hooks, delete) must call this: a
        session clone shares config/kernel/hooks by reference, so clearing only
        ``agents``/``kernels`` left the live session running the pre-edit agent
        (RT-1). Matches on the agent segment of the ``tenant:agent:user:role``
        key, not a raw substring, so an ``agent_id`` that merely appears inside a
        tenant/user id is not evicted. Returns the number of distinct user keys
        that held an instance of the agent.

        ``tenant_id`` (optional) additionally pins the match to the tenant segment,
        so a per-tenant mutation only evicts that tenant's instances instead of the
        shared ``agent_id`` across every tenant (Copilot: tenant-scoped eviction).
        Left ``None`` it preserves the original cross-tenant sweep.

        ``preserve_sessions`` (agent *edit*, not delete): stash each live session
        clone's conversation state before dropping it, so the next message rebuilds
        the clone with the NEW config yet keeps its history. Without this, an
        innocuous tools/hooks edit would silently reset every open conversation
        (Copilot #9). On delete we leave it ``False`` so nothing lingers.
        """
        def _matches(key: str) -> bool:
            parts = key.split(":")
            return (len(parts) >= 2 and parts[1] == agent_id
                    and (tenant_id is None or parts[0] == tenant_id))

        touched: set[str] = set()
        for key in [k for k in self.agents if _matches(k)]:
            self.agents.pop(key, None)
            self.kernels.pop(key, None)
            self.last_active.pop(key, None)
            touched.add(key)
        for key in [k for k in self._session_pool if _matches(k)]:
            pool = self._session_pool.pop(key, None)
            if preserve_sessions and pool:
                stash: Dict[str, dict] = {}
                for session_id, clone in pool.items():
                    try:
                        stash[session_id] = clone.export_state()
                    except Exception as exc:  # noqa: BLE001 — never let a bad export block the edit
                        logger.warning("session state export failed (%s): %s", session_id, exc)
                if stash:
                    self._session_restore.setdefault(key, {}).update(stash)
            self.last_active.pop(key, None)
            touched.add(key)
        if touched:
            logger.info(
                "evict_agent('%s') cleared %d cached user key(s)%s",
                agent_id, len(touched),
                " (sessions preserved)" if preserve_sessions else "",
            )
        return len(touched)

    def reload_skill_routers(self) -> int:
        """Reload the runtime skill-router index on every live agent — templates
        and per-session clones — so a skill create/approve/edit is visible to
        Auto-route immediately (RT-2).

        Clones share the template's router by reference, so we reload each
        distinct router object once. This refreshes ``router.index`` in place and
        does NOT drop conversation state (unlike eviction), which matters because
        a skill change affects every agent in the tenant. Failures per router are
        swallowed so one bad reload cannot break a global skill save. Returns the
        number of distinct routers reloaded.
        """
        seen: set[int] = set()
        reloaded = 0
        agents = list(self.agents.values())
        for pool in self._session_pool.values():
            agents.extend(pool.values())
        for agent in agents:
            router = getattr(agent, "router", None)
            if router is None or id(router) in seen:
                continue
            seen.add(id(router))
            try:
                router.reload()
                reloaded += 1
            except Exception as exc:  # noqa: BLE001 — one bad reload must not break the save
                logger.warning("skill router reload failed: %s", exc)
        if reloaded:
            logger.info("reload_skill_routers reloaded %d router(s)", reloaded)
        return reloaded


    def get_or_create_session(
        self, tenant_id: str, agent_id: str, user_id: str, session_id: str, user_role: str = "user"
    ) -> SkillAgent:
        """
        Get or create an agent for a SPECIFIC session.

        If the session agent already exists in the pool, return it.
        Otherwise, clone the template agent with a fresh session state.
        Enforces LRU eviction when pool exceeds MAX_SESSIONS_PER_USER.
        """
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"

        # A per-session conversation is use of the underlying agent.
        self.touch(user_key)

        # Ensure pool exists for this user
        if user_key not in self._session_pool:
            self._session_pool[user_key] = {}
        pool = self._session_pool[user_key]

        # Return existing session agent if cached (re-insert = genuine LRU ordering)
        if session_id in pool:
            pool[session_id] = pool.pop(session_id)
            return pool[session_id]

        # Get/create the "template" agent (full __init__)
        template = self.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)

        # Clone for this specific session (shares kernel/llm, fresh session state)
        session_agent = template.clone_for_session(new_session_id=session_id)
        # Restore a session dropped by config-change eviction onto the new clone.
        stashed = self._session_restore.get(user_key, {}).pop(session_id, None)
        if stashed is not None:
            try:
                session_agent.import_state(stashed)
                logger.info("Restored conversation for session %s after agent edit", session_id[:30])
            except Exception as exc:  # noqa: BLE001 — a bad restore must not block the new session
                logger.warning("session state restore failed (%s): %s", session_id, exc)
            if not self._session_restore.get(user_key):
                self._session_restore.pop(user_key, None)
        pool[session_id] = session_agent

        # LRU eviction: if pool exceeds limit, drop the least-recently-used session.
        # (No persistence here — this in-memory variant has no store to save to.)
        while len(pool) > self.MAX_SESSIONS_PER_USER:
            oldest_key = next(iter(pool))
            if oldest_key == session_id:
                break
            logger.info("Session pool LRU evict: %s", str(oldest_key)[:30])
            del pool[oldest_key]

        return session_agent

    async def get_or_create_session_async(
        self, tenant_id: str, agent_id: str, user_id: str, session_id: str, user_role: str = "user"
    ) -> SkillAgent:
        """Async parity with RedisSessionState so callers can always await the same name.

        There is no persistent store behind this in-memory variant, so there is nothing to
        restore — it simply delegates.
        """
        return self.get_or_create_session(tenant_id, agent_id, user_id, session_id,
                                          user_role=user_role)

    def find_agents_with_pending(
        self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user"
    ) -> list:
        """Return cached agent instances (template + session clones) for this user that
        currently hold an interactive pending (pending_action or pending_tool_call).
        Approve/deny endpoints use this to target the instance actually holding the
        pending instead of the bare template (which usually has none)."""
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        candidates = []
        tmpl = self.agents.get(user_key)
        if tmpl is not None:
            candidates.append(tmpl)
        candidates.extend(self._session_pool.get(user_key, {}).values())
        seen, out = set(), []
        for ag in candidates:
            if id(ag) in seen:
                continue
            seen.add(id(ag))
            if getattr(ag, "pending_action", None) or getattr(ag, "pending_tool_call", None):
                out.append(ag)
        return out

    def set_active_session(
        self, tenant_id: str, agent_id: str, user_id: str, session_id: str, user_role: str = "user"
    ) -> None:
        """Promote a session agent to be the 'active' default agent."""
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        pool = self._session_pool.get(user_key, {})
        if session_id in pool:
            self.agents[user_key] = pool[session_id]
            logger.debug("Active session set to: %s", session_id[:30])

    def iter_cached_agents(self, tenant_id: str, agent_id: str) -> list:
        """Every cached agent for this tenant/agent, across all users and roles.

        Templates are keyed by ``tenant:agent:user:role`` and new sessions are
        cloned from them, so a config hot-reload that patches only one entry
        leaves every other user on the previous value until eviction. Callers
        changing per-agent configuration fan out over this instead.
        """
        prefix = f"{tenant_id}:{agent_id}:"
        seen, out = set(), []
        for key, agent in list(self.agents.items()):
            if key.startswith(prefix) and id(agent) not in seen:
                seen.add(id(agent))
                out.append(agent)
        for key, pool in list(self._session_pool.items()):
            if not key.startswith(prefix):
                continue
            for agent in list(pool.values()):
                if id(agent) not in seen:
                    seen.add(id(agent))
                    out.append(agent)
        return out

    def get_or_create_kernel(
        self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user"
    ) -> SafeKernel:
        """Return a SafeKernel without booting a full SkillAgent (file browser, audit)."""
        from shared.filesystem_identity import coerce_filesystem_user_id

        fs_user = coerce_filesystem_user_id(
            user_id=user_id,
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        key = f"{tenant_id}:{agent_id}:{fs_user}:{user_role}"
        if key in self.kernels:
            return self.kernels[key]

        _local = load_local_mount(tenant_id, fs_user)
        kernel = create_kernel_runtime(
            data_root=str(DATA_ROOT_PATH),
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=fs_user,
            user_role=user_role,
            require_confirmation=True,
            confirm_operations=["write", "delete"],
            confirm_paths=["/me/"],
            local_mount=_local,
        )
        self.kernels[key] = kernel
        return kernel

    def get_kernel(self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user") -> SafeKernel:
        """Get kernel for user session."""
        return self.get_or_create_kernel(tenant_id, agent_id, user_id, user_role=user_role)

    async def save_agent_state(self, agent: SkillAgent, tenant_id: str, agent_id: str, user_id: str) -> None:
        """Save agent state (no-op for in-memory mode)."""
        pass  # In-memory mode doesn't need to save - state is already in self.agents


class RedisSessionState:
    """
    Redis-backed session state for horizontal scaling.

    Enables any server to handle any user's request by storing session
    state in Redis. Agents are recreated locally, then state is restored
    from Redis.

    Features:
    - In-memory cache (5 min TTL) for hot path performance
    - Automatic state save after each agent.run()
    - Graceful degradation if Redis unavailable
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.session_store = get_session_store(redis_url)

        # Local cache for agents (hot path - avoids Redis on every call)
        self.agents: Dict[str, SkillAgent] = {}
        self.kernels: Dict[str, SafeKernel] = {}

        # Per-session agent pool (same as SessionState — enables parallel conversations)
        self._session_pool: Dict[str, Dict[str, SkillAgent]] = {}
        self.MAX_SESSIONS_PER_USER = 5

        # session key → epoch seconds of last use (see SessionState.agent_liveness)
        self.last_active: Dict[str, float] = {}
        self.ONLINE_IDLE_SECONDS = SessionState.ONLINE_IDLE_SECONDS

        # Track when agents were last loaded from Redis
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 300  # seconds (5 min — covers real-world idle gaps)

        self._connected = False

    async def connect(self) -> bool:
        """Connect the shared session store for startup dependency checks."""
        self._connected = await self.session_store.connect()
        return self._connected

    async def health_check(self) -> bool:
        """Check Redis and retry connection after a transient outage."""
        if not self._connected:
            return await self.connect()
        healthy = await self.session_store.health_check()
        if not healthy:
            self._connected = False
        return healthy

    async def disconnect(self) -> None:
        """Close the shared Redis session connection."""
        await self.session_store.disconnect()
        self._connected = False

    async def _ensure_connected(self) -> bool:
        """Ensure Redis connection is established."""
        if not self._connected:
            self._connected = await self.connect()
        return self._connected

    def _is_cache_valid(self, key: str) -> bool:
        """Check if local cache is still valid."""
        cache_time = self._cache_times.get(key, 0)
        return _time.time() - cache_time < self._cache_ttl

    def _create_agent(self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user") -> SkillAgent:
        """Create a fresh agent instance (without state)."""
        key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"

        # Load optional local mount for this user
        _local = load_local_mount(tenant_id, user_id)

        # Create kernel
        kernel = create_kernel_runtime(
            data_root=str(DATA_ROOT_PATH),
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            user_role=user_role,
            require_confirmation=True,
            confirm_operations=["write", "delete"],
            confirm_paths=["/me/"],
            local_mount=_local,
        )
        self.kernels[key] = kernel

        # Create agent
        skills_path = str(SKILLS_PATH_PATH)
        agent = SkillAgent(
            kernel=kernel,
            skills_path=skills_path,
            user_id=user_id,
            trace_emitter=trace_emitter,
            enterprise_root=str(DATA_ROOT_PATH),
        )
        return agent

    def get_or_create(self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user") -> SkillAgent:
        """
        Get or create agent for user session.

        Synchronous wrapper - state restoration happens in background.
        For full async support, use get_or_create_async().
        """
        key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"

        # Touch the timestamp on a hit so the TTL acts as an idle timeout.
        if key in self.agents and self._is_cache_valid(key):
            self.touch(key)
            return self.agents[key]

        # Create fresh agent
        agent = self._create_agent(tenant_id, agent_id, user_id, user_role=user_role)
        self.agents[key] = agent

        self._cache_times[key] = _time.time()

        # Try to restore state from Redis (sync fallback)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._restore_state_async(agent, tenant_id, agent_id, user_id))
            else:
                loop.run_until_complete(self._restore_state_async(agent, tenant_id, agent_id, user_id))
        except RuntimeError:
            asyncio.run(self._restore_state_async(agent, tenant_id, agent_id, user_id))
        except Exception as e:
            logger.warning("State restoration skipped: %s", e)

        self.touch(key)
        return agent

    def remove(self, tenant_id: str, user_id: str, agent_id: str = "enterprise_agent", user_role: str = "user"):
        """Evict an agent session from the pool (used by queue processor after job completes)."""
        key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        self.agents.pop(key, None)
        self.kernels.pop(key, None)
        self._cache_times.pop(key, None)
        self.last_active.pop(key, None)

    def evict_agent(self, agent_id: str, preserve_sessions: bool = False,
                    tenant_id: Optional[str] = None) -> int:
        """Evict EVERY cached instance of ``agent_id`` — template agents, kernels,
        the local cache-time map, and active per-session clones — so the next
        request rebuilds from the current on-disk config. See
        ``SessionState.evict_agent`` for the RT-1 rationale.

        ``tenant_id`` (optional) pins the match to the tenant segment as well, so a
        per-tenant mutation only evicts that tenant's instances instead of every
        tenant's ``agent_id`` (Copilot: tenant-scoped eviction). Left ``None`` it
        preserves the original cross-tenant sweep.

        ``preserve_sessions`` is accepted for signature parity with
        ``SessionState`` but is a no-op here: this backend persists per-session
        conversation to Redis and restores it when the clone is rebuilt, so an
        agent edit already keeps the open conversation without an explicit stash
        (Copilot #9).
        """
        _ = preserve_sessions  # documented no-op — Redis restore preserves history
        def _matches(key: str) -> bool:
            parts = key.split(":")
            return (len(parts) >= 2 and parts[1] == agent_id
                    and (tenant_id is None or parts[0] == tenant_id))

        touched: set[str] = set()
        for key in [k for k in self.agents if _matches(k)]:
            self.agents.pop(key, None)
            self.kernels.pop(key, None)
            self._cache_times.pop(key, None)
            self.last_active.pop(key, None)
            touched.add(key)
        for key in [k for k in self._session_pool if _matches(k)]:
            self._session_pool.pop(key, None)
            self._cache_times.pop(key, None)
            self.last_active.pop(key, None)
            touched.add(key)
        if touched:
            logger.info("evict_agent('%s') cleared %d cached user key(s)", agent_id, len(touched))
        return len(touched)

    def reload_skill_routers(self) -> int:
        """Reload the runtime skill-router index on every live agent (templates
        and session clones) so a skill create/approve/edit is visible to
        Auto-route immediately (RT-2). See ``SessionState.reload_skill_routers``.
        """
        seen: set[int] = set()
        reloaded = 0
        agents = list(self.agents.values())
        for pool in self._session_pool.values():
            agents.extend(pool.values())
        for agent in agents:
            router = getattr(agent, "router", None)
            if router is None or id(router) in seen:
                continue
            seen.add(id(router))
            try:
                router.reload()
                reloaded += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("skill router reload failed: %s", exc)
        if reloaded:
            logger.info("reload_skill_routers reloaded %d router(s)", reloaded)
        return reloaded

    async def get_or_create_async(self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user") -> SkillAgent:
        """
        Get or create agent for user session (async version).

        Fully async - restores state from Redis before returning.
        """
        key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"

        # Check local cache first
        if key in self.agents and self._is_cache_valid(key):
            self.touch(key)
            return self.agents[key]

        # Ensure Redis connection
        await self._ensure_connected()

        # Create fresh agent
        agent = self._create_agent(tenant_id, agent_id, user_id, user_role=user_role)

        # Restore state from Redis
        await self._restore_state_async(agent, tenant_id, agent_id, user_id)

        # Cache locally
        self.agents[key] = agent
        self._cache_times[key] = _time.time()
        self.touch(key)

        return agent

    async def _restore_state_async(self, agent: SkillAgent, tenant_id: str, agent_id: str,
                                   user_id: str, session_id: str = "") -> None:
        """Restore agent state from Redis.

        ``session_id`` selects which conversation's slot to load. Omit it for the template path,
        which shares the store's default slot.

        The state dict is built from the snapshot's own fields rather than a hand-picked list —
        the previous version enumerated 9 keys, so everything else import_state understands
        (reasoning_ref, compaction provenance, a paused workflow checkpoint, fork lineage) was
        reset to defaults on every restore.
        """
        try:
            await self._ensure_connected()
            snapshot = await self.session_store.load_session(
                tenant_id, user_id, agent_id, session_id
            )

            if snapshot:
                state_dict = {
                    f.name: getattr(snapshot, f.name)
                    for f in dataclasses.fields(snapshot)
                    # Identity/bookkeeping the agent must not inherit from the snapshot.
                    if f.name not in ("tenant_id", "agent_id", "user_id",
                                      "created_at", "last_active_at", "server_id")
                }
                agent.import_state(state_dict)
                logger.info("Restored session from Redis: %s:%s:%s:%s (%d turns)",
                            tenant_id, user_id, agent_id, session_id or "_default",
                            len(snapshot.conversation_history or []))
            else:
                logger.info("New session: %s:%s:%s:%s",
                            tenant_id, user_id, agent_id, session_id or "_default")
        except Exception as e:
            logger.warning("Redis state restoration failed (using fresh state): %s", e)

    def get_or_create_kernel(
        self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user"
    ) -> SafeKernel:
        """Return a SafeKernel without booting a full SkillAgent (file browser, audit)."""
        from shared.filesystem_identity import coerce_filesystem_user_id

        fs_user = coerce_filesystem_user_id(
            user_id=user_id,
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        key = f"{tenant_id}:{agent_id}:{fs_user}:{user_role}"
        if key in self.kernels:
            return self.kernels[key]

        _local = load_local_mount(tenant_id, fs_user)
        kernel = create_kernel_runtime(
            data_root=str(DATA_ROOT_PATH),
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=fs_user,
            user_role=user_role,
            require_confirmation=True,
            confirm_operations=["write", "delete"],
            confirm_paths=["/me/"],
            local_mount=_local,
        )
        self.kernels[key] = kernel
        return kernel

    def get_kernel(self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user") -> SafeKernel:
        """Get kernel for user session."""
        return self.get_or_create_kernel(tenant_id, agent_id, user_id, user_role=user_role)


    async def get_or_create_session_async(
        self, tenant_id: str, agent_id: str, user_id: str, session_id: str, user_role: str = "user"
    ) -> SkillAgent:
        """Get or create an agent for a SPECIFIC session, restoring it from Redis first.

        This is the path every real chat request takes. It used to clone a blank agent and never
        consult Redis — while still SAVING to it on every turn — so the stored copy was
        overwritten by something emptier than itself.

        The restore is awaited rather than fire-and-forget: the create_task pattern used by the
        template path returns the agent before the restore lands, so a turn can start on empty
        history and then be clobbered mid-flight.
        """
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"

        # A per-session conversation is use of the underlying agent.
        self.touch(user_key)

        if user_key not in self._session_pool:
            self._session_pool[user_key] = {}
        pool = self._session_pool[user_key]

        if session_id in pool:
            # Genuine LRU: re-insert so this session becomes the most recently used. Plain dicts
            # preserve insertion order, so pop+reinsert is equivalent to move_to_end.
            pool[session_id] = pool.pop(session_id)
            return pool[session_id]

        template = self.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        session_agent = template.clone_for_session(new_session_id=session_id)
        # Restore before publishing to the pool, while the clone is provably fresh.
        await self._restore_state_async(session_agent, tenant_id, agent_id, user_id, session_id)
        pool[session_id] = session_agent

        await self._evict_session_lru(pool, session_id, tenant_id, agent_id, user_id)
        return session_agent

    async def _evict_session_lru(self, pool: dict, keep_session_id: str,
                                 tenant_id: str, agent_id: str, user_id: str) -> None:
        """Evict the least-recently-used session, SAVING it first.

        Eviction previously just dropped the clone, so anything not yet flushed to Redis was
        gone and the next request for that conversation re-cloned a blank agent.
        """
        while len(pool) > self.MAX_SESSIONS_PER_USER:
            oldest_key = next(iter(pool))
            if oldest_key == keep_session_id:
                break
            victim = pool.pop(oldest_key)
            logger.info("Session pool LRU evict: %s", str(oldest_key)[:30])
            try:
                await self.save_agent_state(victim, tenant_id, agent_id, user_id)
            except Exception as exc:
                logger.warning("Could not persist evicted session %s: %s",
                               str(oldest_key)[:30], exc)

    def get_or_create_session(
        self, tenant_id: str, agent_id: str, user_id: str, session_id: str, user_role: str = "user"
    ) -> SkillAgent:
        """Sync variant — no Redis restore. Prefer get_or_create_session_async.

        Kept for any non-async caller; a session obtained this way starts blank even when Redis
        holds a snapshot.
        """
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        if user_key not in self._session_pool:
            self._session_pool[user_key] = {}
        pool = self._session_pool[user_key]

        if session_id in pool:
            pool.move_to_end(session_id)
            return pool[session_id]

        template = self.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        session_agent = template.clone_for_session(new_session_id=session_id)
        pool[session_id] = session_agent

        if len(pool) > self.MAX_SESSIONS_PER_USER:
            oldest_key = next(iter(pool))
            if oldest_key != session_id:
                logger.info("Session pool LRU evict: %s", oldest_key[:30])
                del pool[oldest_key]

        return session_agent

    def find_agents_with_pending(
        self, tenant_id: str, agent_id: str, user_id: str, user_role: str = "user"
    ) -> list:
        """Return cached agent instances (template + session clones) for this user that
        currently hold an interactive pending (pending_action or pending_tool_call).
        Approve/deny endpoints use this to target the instance actually holding the
        pending instead of the bare template (which usually has none)."""
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        candidates = []
        tmpl = self.agents.get(user_key)
        if tmpl is not None:
            candidates.append(tmpl)
        candidates.extend(self._session_pool.get(user_key, {}).values())
        seen, out = set(), []
        for ag in candidates:
            if id(ag) in seen:
                continue
            seen.add(id(ag))
            if getattr(ag, "pending_action", None) or getattr(ag, "pending_tool_call", None):
                out.append(ag)
        return out

    def set_active_session(
        self, tenant_id: str, agent_id: str, user_id: str, session_id: str, user_role: str = "user"
    ) -> None:
        """Promote a session agent to be the 'active' default agent."""
        user_key = f"{tenant_id}:{agent_id}:{user_id}:{user_role}"
        pool = self._session_pool.get(user_key, {})
        if session_id in pool:
            self.agents[user_key] = pool[session_id]
            # Reset the expiry clock for the promoted agent. Without this it inherited the
            # template's original timestamp and could be swapped for a blank agent moments later.
            self._cache_times[user_key] = _time.time()
            logger.debug("Active session set to: %s", session_id[:30])

    # Activity tracking, the liveness rule and the config fan-out are identical
    # to SessionState's; binding them here keeps the two classes from drifting.
    touch = SessionState.touch
    agent_liveness = SessionState.agent_liveness
    iter_cached_agents = SessionState.iter_cached_agents

    async def save_agent_state(self, agent: SkillAgent, tenant_id: str, agent_id: str, user_id: str) -> None:
        """Save agent state to Redis after each operation."""
        try:
            await self._ensure_connected()

            # Export state from agent
            state_export = agent.export_state()

            # Create snapshot
            snapshot = AgentStateSnapshot(
                session_id=state_export.get("session_id", agent.session_id),
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=user_id,
                current_skill=state_export.get("current_skill"),
                conversation_history=state_export.get("conversation_history", []),
                session_summary=state_export.get("session_summary"),
                compaction_count=state_export.get("compaction_count", 0),
                pending_action=state_export.get("pending_action"),
                pending_tool_call=state_export.get("pending_tool_call"),
                approval_pending=state_export.get("approval_pending"),
                short_term_memory=state_export.get("short_term_memory", []),
                # Persist compaction provenance, transcript pointer, workflow checkpoint and fork lineage.
                session_summary_refs=state_export.get("session_summary_refs", []),
                session_summary_pointer=state_export.get("session_summary_pointer", ""),
                workflow_checkpoint=state_export.get("workflow_checkpoint"),
                parent_session_id=state_export.get("parent_session_id"),
                auto_run=state_export.get("auto_run", False),
            )

            # Save to Redis
            success = await self.session_store.save_session(snapshot)
            if success:
                logger.debug("Session saved to Redis: %s:%s:%s:%s",
                             tenant_id, user_id, agent_id, snapshot.session_id)
            else:
                logger.warning("Session save failed (Redis may be unavailable)")
        except Exception as e:
            logger.warning("Session save error: %s", e)


# Initialize state manager based on feature flag
if USE_REDIS_SESSIONS:
    state = RedisSessionState(redis_url=REDIS_URL)
    logger.info("Session State: REDIS mode enabled (horizontal scaling ready)")
else:
    state = SessionState()
    logger.info("Session State: In-memory mode (single server)")

# Warn about configuration footgun
import os as _os_check
if _os_check.getenv("EXTERNAL_ACCESS_ENABLED", "").lower() == "true" and not USE_REDIS_SESSIONS:
    pass  # In-memory mode — external access still works locally
if _os_check.getenv("EXTERNAL_ACCESS_ENABLED", "").lower() == "true" and not _os_check.getenv("ENTITLEMENTS_ENABLED", "").lower() == "true":
    logger.warning(
        "EXTERNAL_ACCESS_ENABLED=true has no effect without ENTITLEMENTS_ENABLED=true — "
        "entitlement gates require a checker to be injected via set_entitlement_context()"
    )



# Blocked directories that cannot be mounted (security)
_BLOCKED_MOUNT_PREFIXES = (
    "/",        # filesystem root (exact match only — handled separately)
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/tmp",
    "/System",
    "/Library",
    "/private",
)


def _local_mount_config_path(tenant_id: str, user_id: str) -> Path:
    """Return the path to the user's local mount config JSON."""
    root = Path(DATA_ROOT_PATH)
    return root / "tenants" / tenant_id / "users" / user_id / "local_mount.json"


def _resolve_mount_path(raw_path: str) -> Path | None:
    """Resolve a configured mount path with portability rules.

    Order of resolution:
    1. Expand ``${ENV_VAR}`` and ``$ENV_VAR`` references and ``~`` home dir.
    2. If absolute (e.g. ``D:\\data\\shared_assets``), use as-is.
    3. If relative (e.g. ``shared_assets`` or ``reference/shared_assets``),
       resolve against the repo root (parent of ``enterprise_root``).
       This lets the same JSON work on a VM and a laptop with different drive letters.

    Returns the resolved Path if it exists and is a directory, else None.
    """
    if not raw_path:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    if any(tok in expanded for tok in ("${", "%")):
        return None  # unresolved env var → treat as misconfigured
    p = Path(expanded)
    if not p.is_absolute():
        repo_root = Path(DATA_ROOT_PATH).parent  # parent of enterprise_root/
        p = (repo_root / p).resolve()
    else:
        p = p.resolve()
    return p if p.is_dir() else None


def load_local_mount(tenant_id: str, user_id: str) -> str | None:
    """Load the user's configured local mount path, or None if not set/disabled.

    Resolution order (first hit wins):
      1. ``LOCAL_MOUNT_PATH`` env var (deployment/ops override; ideal for VM .env)
      2. Per-user JSON: enterprise_root/tenants/{tenant}/users/{user}/local_mount.json
      3. Tenant default JSON: enterprise_root/tenants/{tenant}/config/tenant_local_mount.json

    JSON ``path`` values may be absolute, relative to the repo root, or contain
    ``${ENV_VAR}`` placeholders so the same file works across machines.
    """
    from shared.config import app_config
    env_override = app_config.local_mount_path or None
    if env_override:
        resolved = _resolve_mount_path(env_override)
        if resolved is not None:
            return str(resolved)
        logger.warning("LOCAL_MOUNT_PATH set but path is invalid: %s", env_override)

    root = Path(DATA_ROOT_PATH)
    candidates = [
        _local_mount_config_path(tenant_id, user_id),
        root / "tenants" / tenant_id / "config" / "tenant_local_mount.json",
    ]

    for cfg_path in candidates:
        if not cfg_path.exists():
            continue
        try:
            data = json.loads(cfg_path.read_text(encoding='utf-8'))
            if data.get("enabled") and data.get("path"):
                resolved = _resolve_mount_path(str(data["path"]))
                if resolved is not None:
                    return str(resolved)
                logger.warning(
                    "local_mount %s points to non-existent path: %s",
                    cfg_path, data.get("path"),
                )
        except Exception as exc:
            logger.warning("Failed to read local mount config %s: %s", cfg_path, exc)

    return None


def save_local_mount(
    tenant_id: str, user_id: str, mount_path: str, enabled: bool = True
) -> dict:
    """
    Validate and save a local mount configuration.

    Returns dict with 'ok' bool and optional 'error' string.
    """
    resolved = Path(mount_path).expanduser().resolve()

    if not resolved.exists():
        return {"ok": False, "error": f"Path does not exist: {resolved}"}
    if not resolved.is_dir():
        return {"ok": False, "error": f"Path is not a directory: {resolved}"}
    # Block system directories
    s = str(resolved)
    if s == "/":
        return {"ok": False, "error": "Cannot mount filesystem root."}
    for prefix in _BLOCKED_MOUNT_PREFIXES:
        if s == prefix or s.startswith(prefix + "/"):
            # Allow user home subdirs even if they start with /Users (macOS) or /home
            if s.startswith(str(Path.home())):
                break
            return {"ok": False, "error": f"Cannot mount system directory: {prefix}"}
    # Block mounting inside enterprise_root (circular)
    ent_root = str(Path(DATA_ROOT_PATH))
    if s == ent_root or s.startswith(ent_root + "/"):
        return {"ok": False, "error": "Cannot mount a path inside enterprise_root."}

    cfg_path = _local_mount_config_path(tenant_id, user_id)
    atomic_write_json(cfg_path, {"path": str(resolved), "enabled": enabled})
    return {"ok": True, "path": str(resolved), "enabled": enabled}
