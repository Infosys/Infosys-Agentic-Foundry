"""Studio → engine runtime bridge registration.

The engine (``iaf_agent_skills``) never imports Studio. Instead Studio registers
implementations of the ``agentos_contracts`` host services into
``iaf_agent_skills.runtime_bridge`` at startup. This module owns those
implementations (evidence sink proxy, Mission runtime bridge) and the single
``register_runtime_services()`` entry point.

All the FastAPI event-loop / WebSocket / HITL detail that used to live inside
``mission_engine.py`` (via lazy upward imports) now lives here, on the Studio
side of the boundary.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("iaf_server")


class StudioEvidenceSink:
    """EvidenceSink implementation delegating to the Studio sink fanout.

    Uses lazy imports so registration order never matters.
    """

    def store_bundle(self, bundle: dict, *, tenant_id: str) -> dict:
        from shared.audit_evidence_sinks import get_evidence_sink_fanout

        return get_evidence_sink_fanout().store_bundle(bundle, tenant_id=tenant_id)

    def fetch_bundle(self, trace_id: str, *, tenant_id: str = "") -> Optional[dict]:
        from shared.audit_evidence_sinks import get_evidence_sink_fanout

        return get_evidence_sink_fanout().fetch_bundle(trace_id, tenant_id=tenant_id)

    def fetch_item(self, trace_id: str, evidence_id: str, *, tenant_id: str = "") -> Optional[dict]:
        from shared.audit_evidence_sinks import get_evidence_sink_fanout

        return get_evidence_sink_fanout().fetch_item(trace_id, evidence_id, tenant_id=tenant_id)

    def health(self) -> dict[str, Any]:
        from shared.audit_evidence_sinks import get_evidence_sink_fanout

        return get_evidence_sink_fanout().health()


class StudioMissionBridge:
    """MissionRuntimeBridge implementation for Studio.

    Owns event-loop scheduling for live WebSocket pushes, research-orchestrator
    synthesis, per-item HITL checkpointing, and durable runtime-DB access.
    """

    def publish_workstream_event(self, workstream_name: str, event: dict) -> None:
        try:
            from routers.workstreams import workstream_subscriptions
            from shared.state import get_main_loop
        except Exception as exc:  # pragma: no cover
            logger.debug("ws publish import failed (non-fatal): %s", exc)
            return
        loop = get_main_loop()
        if not (loop and loop.is_running()):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                workstream_subscriptions.publish(workstream_name, event),
                loop,
            )
        except Exception as exc:  # observe-only
            logger.debug("ws publish failed (non-fatal): %s", exc)

    def on_mission_complete(self, workstream_name: str, tenant_id: str) -> None:
        try:
            from shared.state import maybe_synthesize_research_workstream, get_main_loop
        except Exception as exc:  # pragma: no cover
            logger.debug("mission-complete import failed (non-fatal): %s", exc)
            return
        loop = get_main_loop()
        if loop and loop.is_running():
            # Fire-and-forget — don't block the engine on the synthesis LLM call.
            asyncio.run_coroutine_threadsafe(
                maybe_synthesize_research_workstream(workstream_name, tenant_id),
                loop,
            )

    def checkpoint_hitl(
        self,
        agent: Any,
        tenant_id: str,
        user_id: str,
        skill_name: str,
        source: str = "chat",
    ) -> Optional[dict]:
        from shared.state import checkpoint_hitl_if_needed, get_main_loop

        loop = get_main_loop()
        if loop and loop.is_running():
            # Schedule on the main FastAPI loop from this worker thread.
            future = asyncio.run_coroutine_threadsafe(
                checkpoint_hitl_if_needed(agent, tenant_id, user_id, skill_name, source=source),
                loop,
            )
            return future.result(timeout=10)
        # No main loop (test/CLI context) — run inline.
        return asyncio.run(
            checkpoint_hitl_if_needed(agent, tenant_id, user_id, skill_name, source=source)
        )

    def get_runtime_db(self) -> Any:
        try:
            from workstream_runtime.db import get_db

            return get_db()
        except RuntimeError:
            return None
        except Exception as exc:  # pragma: no cover
            logger.debug("workstream runtime DB unavailable (non-fatal): %s", exc)
            return None

    def health(self) -> dict[str, Any]:
        try:
            from shared.state import get_main_loop

            loop = get_main_loop()
            return {"available": True, "loop_running": bool(loop and loop.is_running())}
        except Exception as exc:  # pragma: no cover
            return {"available": False, "error_type": type(exc).__name__}


def _cost_function(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    from trace_emitter import calculate_cost

    return calculate_cost(model, prompt_tokens, completion_tokens)


def _emitter_factory() -> Any:
    """Return the live Studio trace emitter singleton, or create a fallback.

    Resolved lazily (at agent-run time) to avoid import-order coupling with
    ``shared.state``, and to preserve the previous on-demand fallback behavior.
    """
    try:
        from shared.state import trace_emitter as _singleton

        if _singleton is not None:
            return _singleton
    except Exception:  # pragma: no cover - state not yet importable
        pass
    try:
        from shared.config import DATA_ROOT_PATH
        from trace_emitter import get_trace_emitter

        return get_trace_emitter(str(DATA_ROOT_PATH))
    except Exception:  # pragma: no cover
        return None


_registered = False


def register_runtime_services() -> None:
    """Register all Studio host services into the engine runtime bridge.

    Called once from ``shared.config`` at import time (the earliest Studio
    module on the path). Idempotent and fully lazy — the registered callables
    defer their heavy imports until first use, so this never forces early
    imports of ``shared.state`` / ``trace_emitter`` / evidence modules.
    """
    global _registered
    if _registered:
        return
    from iaf_agent_skills.runtime_bridge import (
        register_cost_function,
        register_evidence_sink,
        register_mission_bridge,
        register_trace_emitter_factory,
    )

    register_cost_function(_cost_function)
    register_trace_emitter_factory(_emitter_factory)
    register_evidence_sink(StudioEvidenceSink())
    register_mission_bridge(StudioMissionBridge())
    _registered = True
    logger.info("Engine runtime bridge: host services registered")
