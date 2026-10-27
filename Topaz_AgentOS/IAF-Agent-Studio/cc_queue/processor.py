"""
Command Center — Autonomous Queue Processor.

Runs as a background asyncio task started from server lifespan.

Main loop (every QUEUE_POLL_INTERVAL seconds):
  1. Poll queue_items WHERE status='queued'
  2. Atomically claim each item
  3. Route via existing SkillRouter (reused from chat) with light model
  4. Run SkillAgent.run() in a thread (same executor chat uses)
  5. Capture status_callback messages as job_steps
  6. Watch for HITL gates — pause item, resume when approved
  7. On completion → write result_summary
  8. On repeated failure → move to DLQ
"""

import asyncio
import logging
import time
import uuid
import socket
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

import os
POLL_INTERVAL       = int(os.getenv("QUEUE_POLL_INTERVAL", "2"))
MAX_CONCURRENT      = int(os.getenv("QUEUE_MAX_CONCURRENT_JOBS", "8"))
MAX_RETRIES         = 3
TENANT_ID           = os.getenv("QUEUE_DEFAULT_TENANT", "company")
SKILL_TIMEOUT_SEC   = int(os.getenv("QUEUE_SKILL_TIMEOUT_SEC", "300"))  # 5 min per skill
CLAIM_LEASE_SEC     = int(os.getenv("QUEUE_CLAIM_LEASE_SECONDS", "360"))
CLAIM_RECLAIM_LIMIT = int(os.getenv("QUEUE_CLAIM_RECLAIM_LIMIT", "3"))
HITL_POLL_SEC    = 3    # how often to check if HITL was resolved
HITL_TIMEOUT_SEC = 600  # 10 min — item stays awaiting_human, not timed out

# Phrases emitted by request_human_approval tool that signal a HITL pause
_HITL_SIGNALS = [
    "waiting for human approval",
    "approval requested",
    "approval_id",
    "awaiting approval",
    "human approval",
    "hitl",
]


def _record_queue_reward_best_effort(
    *,
    tenant_id: str,
    item_id: str,
    raw_label: str,
    trace_id: str = "",
    notes: str = "",
    metadata: dict | None = None,
) -> None:
    try:
        from shared.config import DATA_ROOT_PATH
        from iaf_agent_skills.capture_events import emit_queue_task_lifecycle

        emit_queue_task_lifecycle(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            task_id=item_id,
            status=raw_label,
            trace_id=trace_id,
            notes=notes,
            metadata=metadata or {},
        )
    except Exception as rl_err:
        logger.debug("RL queue processor reward skipped: %s", rl_err)


class QueueProcessor:
    """Autonomous processor — polls queue, routes, executes, handles HITL."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._running = False
        self._heartbeat_ts: str = ""
        self._active_count: int = 0  # tracks jobs currently running
        self._queue_audit_sink = None
        self.worker_id = os.getenv(
            "QUEUE_WORKER_ID",
            f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}",
        )


    def start(self):
        """Called from server lifespan. Schedules the poll loop."""
        self._running = True
        self._heartbeat_ts = datetime.now(timezone.utc).isoformat()  # Mark online immediately
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._task = asyncio.create_task(self._poll_loop(), name="queue_processor")
        logger.info("Queue Processor: STARTED worker=%s (poll=%ss, max_concurrent=%s)",
                    self.worker_id, POLL_INTERVAL, MAX_CONCURRENT)

    async def stop(self):
        """Called from server lifespan shutdown."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        try:
            from cc_queue.db import get_db
            get_db().unregister_worker(self.worker_id)
        except Exception:
            pass
        logger.info("Queue Processor: STOPPED")

    @property
    def heartbeat(self) -> str:
        return self._heartbeat_ts

    def set_queue_audit_sink(self, sink):
        """Attach a structured audit sink for pre-skill queue events."""
        self._queue_audit_sink = sink

    def _redacted_queue_preview(self, item: dict) -> str:
        try:
            from iaf_agent_skills.hook_context import redact_hook_value
            preview = {
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "priority": item.get("priority", ""),
            }
            return str(redact_hook_value(preview))[:1000]
        except Exception:
            return ""

    def _emit_queue_audit(self, event: str, item: dict, **payload) -> None:
        """Emit pre-skill queue audit records without going through HookRunner."""
        try:
            from iaf_agent_skills.hook_context import redact_hook_value
            record = {
                "event": event,
                "ts": datetime.now(timezone.utc).isoformat(),
                "queue_item_id": str(item.get("id", "")),
                "tenant_id": str(item.get("tenant_id", TENANT_ID)),
                "priority": str(item.get("priority", "")),
                "retry_count": int(item.get("retry_count", 0) or 0),
                "queue_status": str(payload.pop("queue_status", "")),
                "skill_name": str(payload.pop("skill_name", "")),
                "exec_id": str(payload.pop("exec_id", "")),
                "routing_ms": int(payload.pop("routing_ms", 0) or 0),
                "input_preview": self._redacted_queue_preview(item),
            }
            for key, value in payload.items():
                record[key] = redact_hook_value(value)
            sink = self._queue_audit_sink
            if callable(sink):
                sink(record)
            elif sink and hasattr(sink, "write"):
                sink.write(record)
            else:
                try:
                    from shared.state import trace_emitter
                    if trace_emitter and hasattr(trace_emitter, "add_span"):
                        trace_emitter.add_span(
                            trace_id=str(item.get("trace_id") or item.get("id") or ""),
                            span_type="queue_lifecycle",
                            name=event,
                            start_ms=time.time() * 1000,
                            duration_ms=0,
                            status=record.get("queue_status") or "observed",
                            input_preview=record.get("input_preview", ""),
                            output_preview="",
                            metadata=record,
                        )
                    else:
                        logger.debug("Queue audit: %s", record)
                except Exception:
                    logger.debug("Queue audit: %s", record)
        except Exception as exc:
            logger.debug("Queue audit emit failed (non-fatal): %s", exc)

    def _capability_hooks_enabled(self) -> bool:
        try:
            from iaf_agent_skills.hook_runner import HookRunner
            return HookRunner.capability_hooks_enabled()
        except Exception:
            return os.getenv("CAPABILITY_HOOKS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}

    def _queue_session_ctx(self, agent, item: dict, *, exec_id: str = "", skill_name: str = "") -> dict:
        try:
            base = dict(agent._build_session_ctx()) if hasattr(agent, "_build_session_ctx") else {}
        except Exception:
            base = {}
        base.update({
            "entrypoint": "queue",
            "queue_item_id": str(item.get("id", "")),
            "item_id": str(item.get("id", "")),
            "exec_id": exec_id,
            "tenant_id": str(item.get("tenant_id") or base.get("tenant_id") or TENANT_ID),
            "skill_name": skill_name or base.get("skill_name", ""),
            "current_skill": skill_name or base.get("current_skill") or base.get("skill_name", ""),
        })
        return base

    def _fire_queue_lifecycle_hook(self, agent, method_name: str, item: dict, **payload) -> None:
        """Fire a skill-scoped queue hook through the per-item SkillAgent runner."""
        if not self._capability_hooks_enabled():
            return
        try:
            runner = getattr(agent, "hook_runner", None)
            method = getattr(runner, method_name, None) if runner else None
            if not callable(method):
                return
            item_id = str(item.get("id", ""))
            exec_id = str(payload.get("exec_id", ""))
            skill_name = str(payload.get("skill_name", ""))
            session_ctx = self._queue_session_ctx(
                agent,
                item,
                exec_id=exec_id,
                skill_name=skill_name,
            )
            hook_payload = dict(payload)
            hook_payload.setdefault("item_id", item_id)
            hook_payload.setdefault("priority", str(item.get("priority", "")))
            hook_payload.setdefault("retry_count", int(item.get("retry_count", 0) or 0))
            hook_payload.setdefault("payload_preview", self._redacted_queue_preview(item))
            method(session_ctx, **hook_payload)
        except Exception as exc:
            logger.debug("Queue lifecycle hook %s failed open: %s", method_name, exc)


    async def _poll_loop(self):
        from cc_queue.db import get_db
        while self._running:
            try:
                self._heartbeat_ts = datetime.now(timezone.utc).isoformat()
                db = get_db()
                db.heartbeat_worker(self.worker_id, self._active_count)
                db.reap_expired_claims(CLAIM_RECLAIM_LIMIT)
                # Claim as many items as there are free slots — fills burst queues immediately
                available = MAX_CONCURRENT - self._active_count
                for _ in range(available):
                    item = db.claim_next(TENANT_ID, self.worker_id, CLAIM_LEASE_SEC)
                    if not item:
                        break  # queue empty
                    asyncio.create_task(self._process_with_semaphore(item))
            except Exception as e:
                logger.exception("Queue Processor poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    async def _process_with_semaphore(self, item: dict):
        self._active_count += 1
        renewal_task = None
        if item.get("claim_token"):
            renewal_task = asyncio.create_task(
                self._renew_claim_loop(item["id"], item["claim_token"]),
                name=f"queue_lease_{item['id']}",
            )
        try:
            async with self._semaphore:
                await self._process_item(item)
        finally:
            if renewal_task:
                renewal_task.cancel()
                try:
                    await renewal_task
                except asyncio.CancelledError:
                    pass
            self._active_count -= 1

    async def _renew_claim_loop(self, item_id: str, claim_token: str) -> None:
        from cc_queue.db import get_db

        interval = max(5, min(CLAIM_LEASE_SEC // 3, 60))
        while self._running:
            await asyncio.sleep(interval)
            try:
                if not get_db().renew_lease(item_id, claim_token, CLAIM_LEASE_SEC):
                    logger.warning("Queue claim lease renewal lost: item=%s worker=%s", item_id, self.worker_id)
                    return
                get_db().heartbeat_worker(self.worker_id, self._active_count)
            except Exception as exc:
                logger.warning("Queue claim lease renewal failed: item=%s error=%s", item_id, exc)


    async def _process_item(self, item: dict):
        from cc_queue.db import get_db
        db = get_db()
        item_id = item["id"]
        tenant_id = item.get("tenant_id", TENANT_ID)
        claim_token = item.get("claim_token")
        description = item.get("description") or item.get("title", "")
        session_id = f"queue_{item_id}"  # per-job session key — used for eviction on error paths

        logger.info("Processing queue item %s: %s", item_id, item.get("title"))
        self._emit_queue_audit("QueueItemReceived", item, queue_status="routing")

        skill_name, confidence, reasoning, routing_ms = await self._route_item(
            item, description, db
        )
        self._emit_queue_audit(
            "QueueItemRouted",
            item,
            queue_status="running" if skill_name else "dlq",
            skill_name=skill_name or "",
            confidence=confidence,
            routing_reason=reasoning,
            routing_ms=routing_ms,
        )

        if not skill_name:
            if not db.move_to_dlq(
                item_id,
                "no_matching_skill",
                "SkillRouter returned no match",
                claim_token=claim_token,
            ):
                logger.warning("Queue item %s DLQ ignored after lost claim", item_id)
                return
            _record_queue_reward_best_effort(
                tenant_id=tenant_id,
                item_id=item_id,
                raw_label="dlq",
                trace_id=str(item.get("trace_id") or item_id),
                notes="SkillRouter returned no match",
                metadata={"source": "queue_processor", "reason": "no_matching_skill"},
            )
            await self._broadcast({"type": "item_failed", "item_id": item_id,
                                   "reason": "No matching skill found"})
            return

        if not db.update_item(item_id,
                              claim_token=claim_token,
                              status="running",
                              routed_skill=skill_name,
                              routing_reason=reasoning):
            logger.warning("Queue item %s running transition ignored after lost claim", item_id)
            return
        await self._broadcast({"type": "item_updated", "item_id": item_id,
                               "status": "running", "skill": skill_name})

        exec_id = str(uuid.uuid4())
        db.create_execution(exec_id, item_id, tenant_id, skill_name)

        try:
            result = await self._run_skill(item, exec_id, skill_name, db)
            completed = db.complete_item(
                item_id,
                exec_id,
                claim_token,
                item_status="done",
                execution_status="completed",
                result_summary=result,
            )
            if not completed:
                logger.warning("Queue item %s completion ignored after lost claim", item_id)
                return
            _record_queue_reward_best_effort(
                tenant_id=tenant_id,
                item_id=item_id,
                raw_label="done",
                trace_id=str(item.get("trace_id") or item_id),
                metadata={"source": "queue_processor", "exec_id": exec_id, "skill_name": skill_name},
            )
            await self._broadcast({"type": "item_completed", "item_id": item_id,
                                   "exec_id": exec_id, "summary": result[:300]})
            logger.info("Queue item %s DONE via %s", item_id, skill_name)

        except asyncio.TimeoutError:
            reason = f"Skill '{skill_name}' timed out after {SKILL_TIMEOUT_SEC}s"
            logger.error("Queue item %s TIMEOUT — %s", item_id, reason)
            db.update_execution(exec_id, status="failed", result_summary=reason)
            if not db.move_to_dlq(item_id, "skill_timeout", reason, claim_token=claim_token):
                logger.warning("Queue item %s timeout DLQ ignored after lost claim", item_id)
                return
            _record_queue_reward_best_effort(
                tenant_id=tenant_id,
                item_id=item_id,
                raw_label="dlq",
                trace_id=str(item.get("trace_id") or item_id),
                notes=reason,
                metadata={"source": "queue_processor", "exec_id": exec_id, "skill_name": skill_name, "reason": "skill_timeout"},
            )
            await self._broadcast({"type": "item_failed", "item_id": item_id,
                                   "reason": reason})
            try:
                from shared.state import state
                state.remove(tenant_id, user_id=session_id)
            except Exception:
                pass

        except _HITLPauseSignal as hitl:
            # Agent raised a HITL gate — wait for human then resume
            if not db.update_item(item_id, claim_token=claim_token, status="awaiting_human"):
                logger.warning("Queue item %s HITL transition ignored after lost claim", item_id)
                return
            db.update_execution(exec_id, status="awaiting_human", completed_at=None,
                                result_summary=f"⏳ Awaiting approval\n\nReason: {hitl.prompt}")
            _record_queue_reward_best_effort(
                tenant_id=tenant_id,
                item_id=item_id,
                raw_label="awaiting_human",
                trace_id=str(item.get("trace_id") or item_id),
                notes=hitl.prompt,
                metadata={"source": "queue_processor", "exec_id": exec_id, "skill_name": skill_name, "approval_id": hitl.approval_id},
            )
            await self._broadcast({"type": "hitl_pending", "item_id": item_id,
                                   "exec_id": exec_id, "approval_id": hitl.approval_id,
                                   "prompt": hitl.prompt})
            logger.info("Queue item %s paused — awaiting human approval %s",
                        item_id, hitl.approval_id)

        except Exception as e:
            retry = item.get("retry_count", 0) + 1
            logger.warning("Queue item %s failed (attempt %s): %s", item_id, retry, e)
            db.update_execution(exec_id, status="failed", result_summary=str(e)[:500])
            if retry >= MAX_RETRIES:
                if not db.move_to_dlq(item_id, "max_retries_exceeded", str(e)[:500], claim_token=claim_token):
                    logger.warning("Queue item %s max-retry DLQ ignored after lost claim", item_id)
                    return
                _record_queue_reward_best_effort(
                    tenant_id=tenant_id,
                    item_id=item_id,
                    raw_label="dlq",
                    trace_id=str(item.get("trace_id") or item_id),
                    notes=str(e)[:500],
                    metadata={"source": "queue_processor", "exec_id": exec_id, "skill_name": skill_name, "retry": retry, "reason": "max_retries_exceeded"},
                )
                await self._broadcast({"type": "item_failed", "item_id": item_id,
                                       "reason": str(e)[:200]})
            else:
                if not db.update_item(item_id, claim_token=claim_token, status="queued", retry_count=retry):
                    logger.warning("Queue item %s retry transition ignored after lost claim", item_id)
                    return
                _record_queue_reward_best_effort(
                    tenant_id=tenant_id,
                    item_id=item_id,
                    raw_label="retry",
                    trace_id=str(item.get("trace_id") or item_id),
                    notes=str(e)[:500],
                    metadata={"source": "queue_processor", "exec_id": exec_id, "skill_name": skill_name, "retry": retry},
                )
            try:
                from shared.state import state
                state.remove(tenant_id, user_id=session_id)
            except Exception:
                pass


    async def _route_item(self, item: dict, description: str, db) -> tuple:
        """
        Route via existing SkillRouter (same instance chat uses).
        Returns (skill_name, confidence, reasoning, latency_ms).
        """
        from shared.state import state  # AgentPool — provides the SkillRouter
        item_id = item["id"]
        tenant_id = item.get("tenant_id", TENANT_ID)
        start = time.time()

        try:
            # SkillRouter.match() is synchronous — run in thread so we don't
            # block the event loop (it makes an LLM call).
            router = state.router if hasattr(state, "router") else None

            if router is None:
                # Fallback: create a temporary router via the configured provider.
                from iaf_agent_skills.providers.factory import build_router_provider
                from shared.config import SKILLS_PATH
                router = build_router_provider(str(SKILLS_PATH))

            explicit_skill = str(item.get("entity_id") or "").strip()
            skills_index = getattr(router, "index", {}).get("skills", {}) if router else {}
            if explicit_skill and explicit_skill in skills_index:
                latency_ms = int((time.time() - start) * 1000)
                reasoning = "[explicit_entity_id] queue item declared target skill"
                db.log_routing(item_id, tenant_id, description,
                               explicit_skill, 1.0, reasoning, latency_ms)
                logger.info("Routed item %s → %s (explicit entity_id, %dms)",
                            item_id, explicit_skill, latency_ms)
                return explicit_skill, 1.0, reasoning, latency_ms

            result = await asyncio.to_thread(
                router.match, description, return_details=True
            )

            if isinstance(result, dict):
                skill_name = result.get("skill", "")
                confidence = result.get("confidence", 0.8)
                method     = result.get("method", "llm")
                reasoning  = f"[{method}] {result.get('entity_name') or ''}"
            else:
                skill_name = str(result)
                confidence = 0.8
                reasoning  = "llm"

            latency_ms = int((time.time() - start) * 1000)
            db.log_routing(item_id, tenant_id, description,
                           skill_name, confidence, reasoning, latency_ms)

            logger.info("Routed item %s → %s (confidence=%.2f, %dms)",
                        item_id, skill_name, confidence, latency_ms)
            return skill_name, confidence, reasoning, latency_ms

        except Exception as e:
            logger.warning("Routing failed for item %s: %s", item_id, e)
            return None, 0.0, str(e), 0


    async def _run_skill(self, item: dict, exec_id: str,
                         skill_name: str, db) -> str:
        """
        Run the skill via existing SkillAgent — same executor as chat.
        Captures status_callback messages as job_steps.
        Returns the agent's final response string.
        """
        from shared.state import state
        from cc_queue.db import get_db as _get_db

        item_id    = item["id"]
        tenant_id  = item.get("tenant_id", TENANT_ID)
        query      = item.get("description") or item.get("title", "")

        # Each queue item gets its own isolated agent session — no shared state between concurrent jobs
        session_id = f"queue_{item_id}"
        agent = state.get_or_create(tenant_id, "enterprise_agent", session_id)
        agent.auto_run = True  # Queue processor runs autonomously — no confirmation gates
        agent._evidence_execution_source = "queue"
        agent._entrypoint = "queue"
        agent._queue_item_id = str(item_id)
        agent._queue_exec_id = str(exec_id)
        agent.approval_pending = None  # Ensure clean HITL state for this job

        # Attach service principal so external access gates are enforced
        try:
            from security.dependencies import make_service_principal, make_agent_entitlement_checker
            _queue_principal = make_service_principal(tenant_id, "queue")
            agent.set_entitlement_context(_queue_principal, make_agent_entitlement_checker(_queue_principal))
        except Exception as _ent_err:
            import logging as _log
            _log.getLogger("iaf_server").warning("Queue entitlement context setup failed (non-fatal): %s", _ent_err)

        step_counter = [0]
        hitl_signal  = [None]   # Will hold _HITLPauseSignal if detected

        def step_callback(msg):
            """Capture every agent status update as a job_step."""
            step_counter[0] += 1
            step_no = step_counter[0]

            if isinstance(msg, dict) and msg.get("__progress__"):
                step_name = msg.get("phase") or msg.get("sub_step") or f"step_{step_no}"
                output    = msg.get("detail") or msg.get("status") or str(msg)
                action    = "progress"
            else:
                text      = str(msg)
                step_name = text[:60] if len(text) > 60 else text
                output    = text
                action    = "agent_step"

                # Detect HITL gate signal
                lower = text.lower()
                if any(sig in lower for sig in _HITL_SIGNALS):
                    approval_id = _extract_approval_id(text)
                    hitl_signal[0] = _HITLPauseSignal(
                        approval_id=approval_id,
                        prompt=text[:500]
                    )

            # Write step to DB (sync, called from agent thread)
            try:
                _get_db().append_step(exec_id, step_no, step_name, output, action)
                # Broadcast step update (fire-and-forget via thread-safe call)
                _fire_broadcast({
                    "type": "step_added",
                    "item_id": item_id,
                    "exec_id": exec_id,
                    "step": {
                        "step_number": step_no,
                        "step_name": step_name,
                        "output": output[:300],
                        "action": action,
                    }
                })
            except Exception:
                pass  # Never break the agent for a logging failure

        # wait_for releases the semaphore slot if a skill hangs.
        start_ts = time.time()
        self._fire_queue_lifecycle_hook(
            agent,
            "run_before_queue_item_start",
            item,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status="running",
        )
        # Harness profile: a long-running profile (e.g. deep-research) may extend the deadline
        # beyond the default 300s so a durable job is not DLQ'd mid-run.
        _skill_timeout = SKILL_TIMEOUT_SEC
        try:
            from agentos_contracts.profile import resolve_profile
            from iaf_agent_skills.harness_profiles import load_profile_registry
            _sk = agent.loader.load(skill_name)
            _reg = load_profile_registry(getattr(getattr(agent, "kernel", None), "agent_root", None))
            _sel = resolve_profile(skill=_sk, config=getattr(agent, "config", {}) or {},
                                   env=os.environ, registry=_reg)
            _deadline = (_sel.dimensions.get("budget") or {}).get("deadline_seconds")
            if _deadline:
                _skill_timeout = max(int(SKILL_TIMEOUT_SEC), int(_deadline))
                logger.info("cc_queue: profile '%s' extends skill timeout to %ss (item %s)",
                            _sel.name, _skill_timeout, getattr(item, "id", "?"))
        except Exception:
            pass  # profile resolution is best-effort; fall back to the default timeout
        # asyncio.wait_for treats timeout=0 as immediate, so map <=0 to None (no limit).
        _effective_timeout = _skill_timeout if (_skill_timeout and _skill_timeout > 0) else None
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    agent.run,
                    query,
                    skill_name=skill_name,
                    status_callback=step_callback,
                    skip_memory=True,
                    light_mode=True,
                ),
                timeout=_effective_timeout,
            )
        except asyncio.TimeoutError as exc:
            duration_ms = int((time.time() - start_ts) * 1000)
            self._fire_queue_lifecycle_hook(
                agent,
                "run_on_queue_item_error",
                item,
                exec_id=exec_id,
                skill_name=skill_name,
                queue_status="failed",
                error_msg=f"Skill timed out after {SKILL_TIMEOUT_SEC}s",
                error_type=type(exc).__name__,
                retry_count=int(item.get("retry_count", 0) or 0),
                will_dlq=True,
                duration_ms=duration_ms,
            )
            self._fire_queue_lifecycle_hook(
                agent,
                "run_on_queue_dlq",
                item,
                exec_id=exec_id,
                skill_name=skill_name,
                failure_reason="skill_timeout",
                error_msg=f"Skill timed out after {SKILL_TIMEOUT_SEC}s",
                error_type=type(exc).__name__,
                retry_count=int(item.get("retry_count", 0) or 0),
            )
            raise
        except _HITLPauseSignal:
            raise
        except Exception as exc:
            duration_ms = int((time.time() - start_ts) * 1000)
            retry = int(item.get("retry_count", 0) or 0) + 1
            will_dlq = retry >= MAX_RETRIES
            self._fire_queue_lifecycle_hook(
                agent,
                "run_on_queue_item_error",
                item,
                exec_id=exec_id,
                skill_name=skill_name,
                queue_status="failed",
                error_msg=str(exc)[:500],
                error_type=type(exc).__name__,
                retry_count=retry,
                will_dlq=will_dlq,
                duration_ms=duration_ms,
            )
            if will_dlq:
                self._fire_queue_lifecycle_hook(
                    agent,
                    "run_on_queue_dlq",
                    item,
                    exec_id=exec_id,
                    skill_name=skill_name,
                    failure_reason="max_retries_exceeded",
                    error_msg=str(exc)[:500],
                    error_type=type(exc).__name__,
                    retry_count=retry,
                )
            else:
                self._fire_queue_lifecycle_hook(
                    agent,
                    "run_before_queue_retry",
                    item,
                    exec_id=exec_id,
                    skill_name=skill_name,
                    retry_count=retry,
                    error_msg=str(exc)[:500],
                    error_type=type(exc).__name__,
                )
            raise

        # request_human_approval sets agent.approval_pending; check it before the keyword hitl_signal.
        _orig_ap = None  # full original approval_pending (preserves context for the checkpoint)
        if getattr(agent, 'approval_pending', None) and not hitl_signal[0]:
            ap = agent.approval_pending
            _orig_ap = dict(ap)  # #3 — keep the FULL dict (resume_kind, pending tool, options, …)
            agent.approval_pending = None  # Clear immediately — prevent concurrent items inheriting this
            approval_id = ap.get("approval_id", f"hitl-{uuid.uuid4().hex[:8]}")
            prompt = ap.get("reason", "Human approval requested")
            hitl_signal[0] = _HITLPauseSignal(approval_id=approval_id, prompt=prompt)
            logger.info("HITL detected via agent.approval_pending for queue item %s, approval %s",
                        item_id, approval_id)

        if hitl_signal[0]:
            # _run_skill is async — await directly instead of run_coroutine_threadsafe
            # (run_coroutine_threadsafe(...).result() from inside the event loop deadlocks)
            try:
                approval_id = hitl_signal[0].approval_id
                if not getattr(agent, 'approval_pending', None):
                    # Restore the full original approval so a queue tool-block stays cold-resumable.
                    if _orig_ap:
                        agent.approval_pending = _orig_ap
                    else:
                        agent.approval_pending = {
                            "approval_id": approval_id,
                            "reason": hitl_signal[0].prompt[:300],
                            "urgency": "medium",
                            "skill": skill_name,
                            "options": ["Approve", "Reject"],
                            "sla_minutes": 120,
                        }
                from shared.state import checkpoint_hitl_if_needed
                # Patch export_state to inject queue metadata into the checkpoint blob
                orig_export = agent.export_state
                def _export_with_meta():
                    s = orig_export()
                    s.update({
                        "_queue_item_id": item_id,
                        "_exec_id": exec_id,
                        "_skill_name": skill_name,
                        "_query": query,
                        "tenant_id": tenant_id,
                    })
                    return s
                agent.export_state = _export_with_meta
                try:
                    await checkpoint_hitl_if_needed(
                        agent, tenant_id, session_id, skill_name, source="queue"
                    )
                finally:
                    agent.export_state = orig_export
                logger.info("HITL checkpoint persisted for queue item %s, approval %s",
                            item_id, approval_id)
            except Exception as e:
                logger.warning("Could not persist HITL checkpoint: %s", e)
            self._fire_queue_lifecycle_hook(
                agent,
                "run_on_queue_hitl_pending",
                item,
                exec_id=exec_id,
                skill_name=skill_name,
                approval_id=hitl_signal[0].approval_id,
                prompt=hitl_signal[0].prompt[:500],
            )
            raise hitl_signal[0]

        result = str(response) if response else "Completed."

        _q_evidence = getattr(agent, '_evidence_bundle', None)
        evidence_trace_id = ""
        evidence_count = 0
        if _q_evidence and (_q_evidence.get('documents') or _q_evidence.get('evidence_items')):
            _q_evidence['execution_source'] = 'queue'
            evidence_count = int(_q_evidence.get('evidence_items_count') or len(_q_evidence.get('evidence_items') or []))
            evidence_trace_id = str(_q_evidence.get("trace_id") or "")
            logger.info(
                "Queue evidence: %d item(s) captured for item %s",
                evidence_count, item_id,
            )
            try:
                from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter
                _stored = EvidenceCollectorAdapter().persist(_q_evidence)
                db.set_execution_evidence(
                    exec_id,
                    str(_q_evidence.get("trace_id") or ""),
                    int(_stored.get("evidence_items_count") or evidence_count),
                )
            except Exception as ev_exc:
                logger.warning("Queue evidence persistence failed for item %s: %s", item_id, ev_exc)

        self._fire_queue_lifecycle_hook(
            agent,
            "run_after_queue_item_complete",
            item,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status="done",
            result_summary=result[:1000],
            duration_ms=int((time.time() - start_ts) * 1000),
            evidence_trace_id=evidence_trace_id,
            evidence_count=evidence_count,
        )

        # Evict the per-job agent session — frees memory, no state leakage between jobs
        try:
            state.remove(tenant_id, user_id=session_id)
        except Exception:
            pass

        return result


    async def _broadcast(self, payload: dict):
        """Push a real-time event to all Command Center WebSocket clients."""
        try:
            from shared.state import queue_broadcaster
            await queue_broadcaster.broadcast(payload)
        except Exception:
            pass  # WebSocket broadcast is best-effort



class _HITLPauseSignal(Exception):
    """Raised inside process_item when agent emits a HITL gate."""
    def __init__(self, approval_id: str, prompt: str):
        self.approval_id = approval_id
        self.prompt = prompt
        super().__init__(f"HITL gate: {approval_id}")


def _extract_approval_id(text: str) -> str:
    """Try to extract an approval ID from the HITL signal text."""
    import re
    # Accept =, :, space or quote as separator (handles "approval_id=uuid" and "approval_id: uuid")
    match = re.search(r'approval[_\-]?id["\s:=]+([a-zA-Z0-9_\-]+)', text, re.I)
    if match:
        return match.group(1)
    return f"hitl-{uuid.uuid4().hex[:8]}"


def _fire_broadcast(payload: dict):
    """Thread-safe fire-and-forget broadcast from agent thread."""
    try:
        import asyncio as _asyncio
        from shared.state import _main_loop
        if _main_loop and not _main_loop.is_closed():
            from shared.state import queue_broadcaster
            _asyncio.run_coroutine_threadsafe(
                queue_broadcaster.broadcast(payload), _main_loop
            )
    except Exception:
        pass


_processor: Optional[QueueProcessor] = None


def get_processor() -> QueueProcessor:
    global _processor
    if _processor is None:
        _processor = QueueProcessor()
    return _processor
