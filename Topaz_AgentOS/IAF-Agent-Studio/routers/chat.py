"""
IAF Agent Studio — Chat Router

Endpoints:
  - POST /api/chat       (REST chat)
  - POST /api/approve    (approve/reject pending action via REST)
  - GET  /api/reasoning/{trace_id}   (fetch reasoning context)
  - GET  /api/pending     (check pending action for a session)
  - POST /api/batch       (batch processing)
  - GET  /api/batch/status/{batch_id}  (poll batch job)
  - WS   /ws/chat         (streaming chat with reasoning trace)
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks

from shared.config import AUTH_ENABLED, DATA_ROOT_PATH, SERVER_DIR, TENANT_ID
from shared.ws_utils import WsSendGate
from shared.models import (
    ChatMessage,
    BatchRequest,
    BatchJobRequest,
    KernelApprovalRequest,
)
from security.dependencies import (
    bind_request_identity,
    enforce_entitlement,
    make_agent_entitlement_checker,
)
from shared.state import (
    state,
    dashboard,
    twin_broadcaster,
    twin_emitter,
    trace_emitter,
    queue_manager,
    task_integration,
    approval_store,
    chat_registry,
    checkpoint_hitl_if_needed,
    checkpoint_rlm_holds_if_needed,
    stream_intercept_approval_id as _stream_intercept_approval_id,
    reconcile_stream_intercept_durable as _reconcile_stream_intercept_durable,
    _detect_learning_signals,
    ApprovalRequest,
    QueueNames,
)
from iaf_agent_skills.capture_events import (
    emit_agentpro_reward,
    emit_chat_turn,
    emit_revision_preference,
)
from iaf_agent_skills import cancellation as run_cancellation

logger = logging.getLogger("iaf_server")
router = APIRouter()

_batch_jobs: dict = {}


def apply_force_plan_routing(routing_result: dict, all_skill_names: list[str]) -> dict:
    """Override routing for UI Plan Mode (force_plan=True).

    Forces general + planned mode and pins mode_hint so agent.py does not
    auto-upgrade to dynamic orchestrator before create_plan runs.
    """
    updated = dict(routing_result)
    updated["detected_domains"] = list(all_skill_names)
    updated["execution_mode"] = "planned"
    updated["mode_hint"] = "planned"
    updated["skill"] = "general"
    return updated


def _capture_rl_turn_best_effort(
    *,
    agent,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    session_id: str,
    trace_id: str,
    content: str,
    response: str,
    skill_name: str,
    decision_context: dict | None,
    status: str = "success",
    started_at: str | None = None,
    ended_at: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Capture RL/eval data without affecting chat correctness."""
    try:
        llm = getattr(agent, "llm", None)
        native_turn = getattr(agent, "_last_native_react_turn", None) or {}
        provider_meta = native_turn.get("provider_metadata") if isinstance(native_turn, dict) else {}
        emit_chat_turn(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            trace_id=trace_id,
            user_query=content,
            final_response=response,
            skill_name=skill_name,
            decision_context=decision_context,
            model_name=(
                str((provider_meta or {}).get("model") or "")
                or str(getattr(llm, "azure_deployment", "") or getattr(llm, "model_name", "") or "")
            ),
            provider=str((provider_meta or {}).get("provider") or ""),
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            metadata=metadata,
        )
        try:
            from shared.trace_value_service import schedule_assessment_after_capture

            schedule_assessment_after_capture(
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=user_id,
                trajectory_id=trace_id,
            )
        except Exception as trace_value_err:  # noqa: BLE001 - assessment must never affect chat
            logger.debug("Trace value scheduling skipped: %s", trace_value_err)
    except Exception as capture_err:
        logger.warning("RL capture failed (non-fatal): %s", capture_err)


def _compact_page_context(value, *, depth: int = 0):
    """Return a small, prompt-safe copy of browser-provided page context."""
    if depth > 3:
        return "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text[:500] + ("..." if len(text) > 500 else "")
    if isinstance(value, list):
        return [_compact_page_context(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, dict):
        compact = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= 40:
                compact["_truncated"] = True
                break
            key_text = str(key)[:80]
            compact[key_text] = _compact_page_context(item, depth=depth + 1)
        return compact
    return str(value)[:300]


def _compose_page_context_content(content: str, source_page: str | None, page_context: dict | None) -> str:
    """Prefix AskTwin/help requests with page state without changing normal chat turns."""
    if not source_page and not page_context:
        return content

    compact_context = _compact_page_context(page_context or {})
    try:
        context_json = json.dumps(compact_context, ensure_ascii=False, indent=2)
    except Exception:
        context_json = str(compact_context)[:2500]
    if len(context_json) > 3500:
        context_json = context_json[:3500] + "\n...context truncated..."

    source = str(source_page or "unknown").strip()[:120]
    return (
        "[ASKTWIN PAGE CONTEXT]\n"
        f"source_page: {source}\n"
        "This block is the CURRENT page context and overrides any prior AskTwin "
        "topic from another page. Answer for this route/tab/visible state first. "
        "If page_context includes visibleRecords or visibleRecordKeys, use those "
        "for questions about rows, cards, list entries, or ordinal references. "
        "If it is insufficient, then use the platform documentation. Do not claim "
        "access to hidden page state that is not present here.\n"
        f"{context_json}\n"
        "[END ASKTWIN PAGE CONTEXT]\n\n"
        f"User question: {content}"
    )


def _workstream_ref_from_page_context(page_context: dict | None) -> tuple[str | None, str | None]:
    """Extract workstream attribution from source-aware REST chat requests."""
    if not isinstance(page_context, dict):
        return None, None
    return (
        page_context.get("workstream_name") or page_context.get("workstream"),
        page_context.get("mission_item_id") or page_context.get("item_id"),
    )


def _approval_context_matches_workstream_item(approval: dict | None, ws_name: str | None, item_id: str | None) -> bool:
    if not approval or not ws_name or not item_id:
        return False
    ctx = approval.get("context") or {}
    return (
        (ctx.get("workstream_name") or ctx.get("workstream")) == ws_name
        and (ctx.get("mission_item_id") or ctx.get("item_id") or ctx.get("workstream_item")) == item_id
    )


def _persist_evidence_bundle(bundle: dict | None, execution_source: str) -> None:
    """Persist evidence without letting storage failures affect chat replies."""
    if not bundle or not (bundle.get("documents") or bundle.get("evidence_items")):
        return
    try:
        bundle["execution_source"] = execution_source
        from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter
        EvidenceCollectorAdapter().persist(bundle)
    except Exception as exc:
        logger.warning("Evidence persistence failed (%s): %s", execution_source, exc)


def _make_streaming_token_callback(safe_send_fn, loop, session_id: str):
    """
    Returns a LangChain BaseCallbackHandler that emits each LLM token over
    the WebSocket. Only imported/created when ENABLE_TOKEN_STREAMING=true.
    Falls back to None if langchain_core is unavailable.
    """
    import os
    if os.getenv("ENABLE_TOKEN_STREAMING", "false").lower() != "true":
        return None
    try:
        from langchain_core.callbacks import BaseCallbackHandler

        class _StreamingTokenCallback(BaseCallbackHandler):
            def on_llm_new_token(self, token: str, **kwargs) -> None:
                if not token:
                    return
                try:
                    asyncio.run_coroutine_threadsafe(
                        safe_send_fn({"type": "token", "token": token,
                                      "origin_session_id": session_id}),
                        loop,
                    )
                except Exception:
                    pass  # Non-fatal — token lost, response still completes

        return _StreamingTokenCallback()
    except Exception as _cb_err:
        logger.warning("StreamingTokenCallback creation failed: %s", _cb_err)
        return None


async def _run_critique_sync(agent, query, response, tool_results) -> dict:
    """Run critique synchronously and return the result dict.

    Used in sync mode — called before the response is sent to the user so the
    critique result can be embedded directly in ws_response. No WS push needed.
    Returns None on failure so the caller can skip embedding gracefully.
    """
    import asyncio as _asyncio
    try:
        from iaf_agent_skills.plan_critic import PlanCritic
        _indexer = getattr(getattr(agent, 'memory', None), 'knowledge_indexer', None)
        _critic  = PlanCritic(llm=agent.light_llm, indexer=_indexer)
        loop     = _asyncio.get_event_loop()

        critique = await loop.run_in_executor(
            None, _critic.critique_response, query, response, tool_results
        )
        logger.info(
            "Critique (sync): confidence=%s issues=%d",
            critique.get("confidence"), len(critique.get("issues", []))
        )

        # Low confidence → one revision pass
        if critique.get("confidence") == "low" and critique.get("issues"):
            _revision_prompt = (
                f"Your previous answer had grounding issues:\n"
                f"{_critic.format_response_critique_for_display(critique)}\n\n"
                f"Tool outputs for reference:\n"
                f"{_critic._format_tool_outputs(tool_results)}\n\n"
                f"Revise your answer to be strictly faithful to the tool outputs above. "
                f"Do not add any facts not present in the tool outputs. "
                f"Keep the same tone and format."
            )
            try:
                _revised = await loop.run_in_executor(None, agent.llm.invoke, _revision_prompt)
                critique["revised_response"] = _revised.content.strip()
                critique["was_revised"]      = True
                critique_final = await loop.run_in_executor(
                    None, _critic.critique_response,
                    query, critique["revised_response"], tool_results,
                )
                critique_final["was_revised"]      = True
                critique_final["revised_response"] = critique["revised_response"]
                critique = critique_final
                logger.info("Critique (sync): revision done, final confidence=%s", critique.get("confidence"))
            except Exception as _rev_err:
                logger.warning("Critique (sync) revision failed: %s", _rev_err)

        _dc = getattr(agent, '_last_decision_context', None)
        if _dc is not None:
            _dc["critique"] = critique
        return critique

    except Exception as e:
        logger.warning("_run_critique_sync failed: %s", e)
        return None


async def _run_critique_and_push(agent, query, response, tool_results, trace_id, safe_send,
                                 consistency_check: bool = False):
    """Run response grounding critique and push result to the client.

    Called either inline (sync mode — awaited before response sent) or as a
    background task (async mode — create_task after response already sent).

    In both cases the same logic runs:
      1. Call PlanCritic.critique_response() using agent.light_llm
      2. If confidence==low → one synthesis-only revision pass via agent.llm
         (no tools re-run). Marks result as was_revised=True.
      3. Push a "critique_result" WebSocket message so the UI can update the
         Grounding row in the Reasoning panel and show the Regenerate button.
      4. If consistency_check=True — fire a cold second agent run (no history,
         no memory), compare responses, push a second "critique_result" message
         with type label "consistency".

    The "critique_result" WS message payload:
      { type, trace_id, critique: {confidence, issues, summary, was_revised} }
    """
    import asyncio as _asyncio
    try:
        from iaf_agent_skills.plan_critic import PlanCritic
        _indexer = getattr(getattr(agent, 'memory', None), 'knowledge_indexer', None)
        _critic  = PlanCritic(llm=agent.light_llm, indexer=_indexer)

        # Run in executor so blocking LLM call doesn't stall the event loop
        loop = _asyncio.get_event_loop()
        critique = await loop.run_in_executor(
            None, _critic.critique_response, query, response, tool_results
        )
        logger.info(
            "Critique (bg): confidence=%s issues=%d",
            critique.get("confidence"), len(critique.get("issues", []))
        )

        # Low confidence → one surgical revision pass (patch issues only, preserve original)
        if critique.get("confidence") == "low" and critique.get("issues"):
            _issue_list = "\n".join(
                f"- {iss.get('type','').replace('_',' ')}: {iss.get('claim','')} "
                f"{'('+iss.get('evidence','')+')' if iss.get('evidence') else ''}"
                for iss in critique.get("issues", [])
            )
            _revision_prompt = (
                f"You are revising an answer to fix specific grounding issues. "
                f"Make ONLY the minimal changes needed to fix the issues listed below. "
                f"Do NOT rewrite, shorten, or restructure the answer — preserve all other content exactly.\n\n"
                f"ORIGINAL ANSWER:\n{response}\n\n"
                f"ISSUES TO FIX (only these — leave everything else unchanged):\n{_issue_list}\n\n"
                f"TOOL OUTPUTS (use these to verify facts):\n"
                f"{_critic._format_tool_outputs(tool_results)}\n\n"
                f"Instructions:\n"
                f"1. Remove or correct only the specific claims listed in ISSUES TO FIX.\n"
                f"2. Keep all other sentences, structure, and formatting from the ORIGINAL ANSWER.\n"
                f"3. Do not add new information beyond what is needed to fix the issues.\n"
                f"4. Return the full revised answer."
            )
            try:
                _revised = await loop.run_in_executor(None, agent.llm.invoke, _revision_prompt)
                critique["revised_response"] = _revised.content.strip()
                critique["was_revised"]      = True
                # Optional re-check of the revised answer (CRITIQUE_RECHECK, default true).
                from shared.config import CRITIQUE_RECHECK as _CRITIQUE_RECHECK
                if _CRITIQUE_RECHECK:
                    critique_final = await loop.run_in_executor(
                        None, _critic.critique_response,
                        query, critique["revised_response"], tool_results,
                    )
                    critique_final["was_revised"]      = True
                    critique_final["revised_response"] = critique["revised_response"]
                    critique_final["original_issues"]  = critique.get("issues", [])
                    critique = critique_final
                else:
                    critique["original_issues"] = critique.get("issues", [])
                    critique["issues"]          = []
                    critique["was_revised"]     = True
                    critique["confidence"]      = "high"
                logger.info("Critique (bg): revision done, final confidence=%s (recheck=%s)", critique.get("confidence"), _CRITIQUE_RECHECK)
            except Exception as _rev_err:
                logger.warning("Critique revision failed: %s", _rev_err)

        # Update agent decision context so trace captures final critique result
        _dc = getattr(agent, '_last_decision_context', None)
        if _dc is not None:
            _dc["critique"] = critique
        try:
            _revised_response = critique.get("revised_response") if isinstance(critique, dict) else None
            _trajectory_id = str((_dc or {}).get("trace_id") or trace_id)
            if _revised_response and str(_revised_response) != str(response):
                emit_revision_preference(
                    data_root=DATA_ROOT_PATH,
                    tenant_id=str(getattr(getattr(agent, "kernel", None), "tenant_id", "") or TENANT_ID),
                    agent_id=str(getattr(getattr(agent, "kernel", None), "agent_id", "") or ""),
                    trajectory_id=_trajectory_id,
                    original_response=str(response),
                    revised_response=str(_revised_response),
                    source="async_critique",
                )
        except Exception as _rl_pref_err:
            logger.warning("RL async critique preference capture failed (non-fatal): %s", _rl_pref_err)

        logger.info("Pushing critique_result trace_id=%s", trace_id)  # trace_id is _request_trace_id passed as param
        await safe_send({
            "type":      "critique_result",
            "trace_id":  trace_id,
            "critique":  critique,
        })

        # Runs after the critique is pushed; additive background verification.
        if consistency_check:
            try:
                logger.info("Consistency check: starting cold second run for skill=%s",
                            getattr(agent, 'current_skill', '?'))
                # The prefix steers Run 2 down a different search path so agreement is meaningful.
                _consistency_prefix = (
                    "[CONSISTENCY RUN: Verify this answer independently. "
                    "Use invoke_skill with target_skill=\"file_explorer\" as your primary search method. "
                    "Only fall back to shell grep if invoke_skill returns no results.]\n\n"
                )
                second_response = await loop.run_in_executor(
                    None,
                    lambda: agent.run(
                        _consistency_prefix + query,
                        skill_name=getattr(agent, 'current_skill', None),
                        skip_memory=True,   # cold run — no memory read/write
                        light_mode=True,    # no heavy context loading
                    )
                )
                # agent.run() can return (response, tool_calls) tuple or plain str
                if isinstance(second_response, tuple):
                    second_response = second_response[0]
                second_response = str(second_response or "")

                logger.info("Consistency check: second run complete (%d chars)", len(second_response))

                consistency = await loop.run_in_executor(
                    None, _critic.critique_consistency, query, response, second_response
                )
                import json as _json
                logger.info(
                    "Consistency check: confidence=%s issues=%d — %s",
                    consistency.get("confidence"),
                    len(consistency.get("issues", [])),
                    _json.dumps(consistency.get("issues", []), ensure_ascii=False),
                )

                # Push as a separate critique_result so UI can show it distinctly
                await safe_send({
                    "type":     "critique_result",
                    "trace_id": trace_id,
                    "critique": consistency,
                    "label":    "consistency",   # UI uses this to label the panel
                })

            except Exception as _ce:
                logger.warning("Consistency check failed (non-fatal): %s", _ce)

    except Exception as e:
        logger.warning("_run_critique_and_push failed: %s", e)


@router.post("/api/chat")
async def chat_endpoint(msg: ChatMessage, request: Request):
    """
    Synchronous (non-streaming) chat endpoint with lane queue.
    For simple integrations that don't need WebSocket.
    """
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request,
        requested_tenant=msg.tenant_id,
        requested_agent=msg.agent_id,
        requested_user=msg.user_id,
    )
    user_role = principal.roles[0] if principal.roles else "user"
    enforce_entitlement(principal, "use", "agent", agent_id)
    request_session_id = (getattr(msg, "session_id", None) or "").strip()
    if request_session_id:
        agent = await state.get_or_create_session_async(
            tenant_id, agent_id, user_id, request_session_id, user_role=user_role
        )
    else:
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
    kernel = state.get_kernel(tenant_id, agent_id, user_id, user_role=user_role)

    # Check if user is responding to a pending approval via text
    content_lower = msg.content.strip().lower()
    if agent.pending_action:
        approve_words = {"approve", "approved", "yes", "ok", "proceed", "go ahead", "do it", "confirmed", "y"}
        reject_words = {"reject", "no", "cancel", "stop", "don't", "abort", "n"}

        # These branches return before normal turn handling, so record the approval exchange in conversation memory.
        def _record_approval_turn(_resp: str) -> None:
            try:
                agent._log_conversation(msg.content, "approval", [], str(_resp or ""),
                                        llm_visible_limit=agent.EARLY_RETURN_HISTORY_LIMIT)
            except Exception as _rec_err:
                logger.debug("approval turn not recorded (non-fatal): %s", _rec_err)

        if content_lower in approve_words:
            _prior_id = _stream_intercept_approval_id(agent)
            response = agent.execute_approved_action()
            await _reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, user_id, "approve")
            _record_approval_turn(response)
            await state.save_agent_state(agent, tenant_id, agent_id, user_id)
            await dashboard.broadcast({
                "type": "approval_resolved",
                "user_id": user_id,
                "action": "approved",
                "operation": "approved_action",
            })
            return {"response": response, "skill": "approval", "user_id": user_id}
        elif content_lower in reject_words:
            _prior_id = _stream_intercept_approval_id(agent)
            response = agent.reject_pending_action()
            await _reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, user_id, "reject")
            _record_approval_turn(response)
            await state.save_agent_state(agent, tenant_id, agent_id, user_id)
            await dashboard.broadcast({
                "type": "approval_resolved",
                "user_id": user_id,
                "action": "rejected",
                "operation": "rejected_action",
            })
            return {"response": response, "skill": "approval", "user_id": user_id}

    kernel.require_confirmation = msg.human_approval

    agent.auto_run = not msg.human_approval

    # Set plan_requested flag on agent so routing can trigger planner
    agent._plan_requested = getattr(msg, 'plan_requested', False)
    content = _compose_page_context_content(
        msg.content,
        getattr(msg, "source_page", None),
        getattr(msg, "page_context", None),
    )

    try:
        last_response = None
        if agent.conversation_history:
            last_response = agent.conversation_history[-1].get("response", "")

        # Pre-router entity resolution: table mode only (file mode lets the router LLM extract entities).
        _entity_hint, _entity_confidence = None, 0.0
        _process_hint, _process_matches, _signals_agree = None, [], None
        _resolved_entities = []
        # Declared here: the routing-signal logger below references it in every mode.
        _entity_store_http = None
        _http_ctx_mode = getattr(agent, 'context_loading_mode', 'table')
        if _http_ctx_mode != 'file':
            try:
                # TABLE MODE only — SQLite entity resolution pre-signal for router
                _indexer_http = getattr(agent.memory, "knowledge_indexer", None)
                _entity_store_http = getattr(_indexer_http, "entity_registry", None) if _indexer_http else None
                if _entity_store_http and content:
                    _q_emb = await asyncio.to_thread(_indexer_http._safe_get_embedding, content)
                    if _q_emb:
                        _ectx = await asyncio.to_thread(
                            _entity_store_http.collect_context,
                            query_embedding=_q_emb, query_text=content
                        )
                        if _ectx:
                            _entity_hint       = _ectx.get("skill_hint")
                            _entity_confidence = _ectx.get("skill_confidence", 0.0)
                            _process_hint      = _ectx.get("process_hint")
                            _process_matches   = _ectx.get("process_matches", [])
                            _signals_agree     = _ectx.get("signals_agree")
                            _resolved_entities = _ectx.get("resolved_entities", [])
            except Exception as _ent_err:
                logger.warning("Entity resolution pre-signal failed (HTTP), routing continues: %s", _ent_err)

        # find_skills() returns [] while the index loads, so no readiness pre-check is needed.
        _tax_hints_http = []
        try:
            _tax_idx_http = getattr(agent, '_taxonomy_index', None)
            if _tax_idx_http:
                _idx_http = getattr(agent.memory, 'knowledge_indexer', None)
                if _idx_http:
                    _emb_http = await asyncio.to_thread(_idx_http._safe_get_embedding, content)
                    if _emb_http:
                        _tax_hints_http = await asyncio.to_thread(
                            _tax_idx_http.find_skills,
                            query_embedding=_emb_http,
                            query_text=content,
                        )
        except Exception as _tax_http_err:
            logger.debug("Pre-router taxonomy lookup failed HTTP (non-fatal): %s", _tax_http_err)
        logger.info(
            "Pre-router taxonomy signal (HTTP): %d hits%s",
            len(_tax_hints_http),
            " — " + ", ".join(
                f"{h.get('skill')}={h.get('score', 0):.3f}" for h in _tax_hints_http[:5]
            ) if _tax_hints_http else "",
        )

        # Route with full signals and return_details=True so execution_mode and
        # detected_domains are preserved and can trigger planned mode in agent.run().
        _routing_result = await asyncio.to_thread(
            agent.router.match,
            content,
            current_skill=agent.current_skill,
            last_response=last_response,
            entity_hint=_entity_hint,
            entity_confidence=_entity_confidence,
            process_hint=_process_hint,
            process_matches=_process_matches,
            signals_agree=_signals_agree,
            taxonomy_hints=_tax_hints_http,
            return_details=True,
        ) if not msg.skill_name else {
            "skill": msg.skill_name,
            "execution_mode": "react",
            "detected_domains": [],
            "method": "forced",
            "confidence": 1.0,
            "is_continuation": False,
            "alternatives": [],
        }
        _force_plan = bool(getattr(msg, "force_plan", False) or getattr(msg, "plan_requested", False))
        if _force_plan:
            _routing_result = apply_force_plan_routing(
                _routing_result,
                [s["name"] for s in agent.router.list_skills()],
            )
            logger.info(
                "FORCE PLAN (HTTP): detected_domains overridden, execution_mode=planned, "
                "mode_hint=planned, skill forced to general"
            )
        skill_name = _routing_result["skill"]
        enforce_entitlement(principal, "use", "skill", skill_name)

        try:
            # Resolve the store here when the table-mode pre-signal block did not run.
            if _entity_store_http is None:
                _idx_rs = getattr(agent.memory, "knowledge_indexer", None)
                _entity_store_http = getattr(_idx_rs, "entity_registry", None) if _idx_rs else None
            if _entity_store_http and hasattr(_entity_store_http, "log_routing_signal"):
                _entity_store_http.log_routing_signal(
                    query_text=content,
                    entity_hint=_entity_hint,
                    entity_confidence=_entity_confidence,
                    process_hint=_process_hint,
                    process_matches=_process_matches,
                    signals_agree=_signals_agree,
                    routed_skill=skill_name,
                    resolved_entities=_resolved_entities,
                )
        except Exception as _rs_err:
            logger.warning("Routing signal logging failed (HTTP, non-fatal): %s", _rs_err)

        # Lane queue: same user runs serially, different users in parallel.
        lane_name = QueueNames.session(tenant_id, user_id)
        if request_session_id:
            lane_name = f"{lane_name}:{request_session_id}"

        ws_name, ws_item_id = _workstream_ref_from_page_context(getattr(msg, "page_context", None))
        previous_ws = getattr(agent, "_mission_workstream", None)
        previous_item_id = getattr(agent, "_mission_item_id", None)
        if ws_name:
            pending = getattr(agent, "approval_pending", None)
            if pending and not _approval_context_matches_workstream_item(pending, ws_name, ws_item_id):
                logger.warning(
                    "Clearing stale in-memory HITL approval before REST workstream chat: "
                    "session=%s current=%s/%s pending_context=%s approval=%s",
                    request_session_id or user_id,
                    ws_name,
                    ws_item_id,
                    (pending.get("context") or {}),
                    pending.get("approval_id"),
                )
                agent.approval_pending = None
            agent._mission_workstream = ws_name
            agent._mission_item_id = ws_item_id

        agent._telemetry_entrypoint = "chat_rest"
        hitl_data = None
        try:
            response = await queue_manager.enqueue(
                lane_name,
                # Offload the sync SkillAgent.run() to a thread so it does not block the event loop.
                lambda: asyncio.to_thread(
                    agent.run,
                    content,
                    skill_name=skill_name,
                    routing_info=_routing_result,
                    render_ui=msg.render_ui,
                    light_mode=msg.light_mode,
                    knowledge_mode=msg.knowledge_mode,
                    profile=msg.profile,
                ),
                # SAFETY-CRITICAL: keep max_concurrent=1; SkillAgent.run() writes per-request state to instance attrs.
                max_concurrent=1,
            )

            # Mirror the WebSocket chat path: REST callers can also trigger
            # request_human_approval, so persist the checkpoint for Command Center.
            pending = getattr(agent, "approval_pending", None)
            if ws_name and pending and not _approval_context_matches_workstream_item(pending, ws_name, ws_item_id):
                logger.warning(
                    "Dropping mismatched in-memory HITL approval before REST checkpoint: "
                    "session=%s current=%s/%s pending_context=%s approval=%s",
                    request_session_id or user_id,
                    ws_name,
                    ws_item_id,
                    (pending.get("context") or {}),
                    pending.get("approval_id"),
                )
                agent.approval_pending = None
            hitl_data = await checkpoint_hitl_if_needed(
                agent,
                tenant_id,
                user_id,
                skill_name,
                source=getattr(msg, "source_page", None) or "chat",
            )
        finally:
            agent._mission_workstream = previous_ws
            agent._mission_item_id = previous_item_id

        await state.save_agent_state(agent, tenant_id, agent_id, user_id)

        dc = getattr(agent, '_last_decision_context', None)
        _rl_trace_id = str((dc if isinstance(dc, dict) else {}).get("trace_id") or uuid.uuid4().hex)

        result = {
            "response": response,
            "skill": skill_name,
            "user_id": user_id,
            "rl_trajectory_id": _rl_trace_id,
            "rl_model_call_id": f"{_rl_trace_id}:model:final",
        }
        if hitl_data:
            result["hitl_approval"] = hitl_data

        if agent.pending_action:
            _tc = getattr(agent, "pending_tool_call", None) or {}
            _tc_args = _tc.get("args", {}) if isinstance(_tc, dict) else {}
            _preview = _tc_args.get("content") or _tc_args.get("command") or ""
            result["pending_approval"] = {
                "operation": agent.pending_action.get("operation"),
                "target": agent.pending_action.get("target"),
                "command": agent.pending_action.get("command"),
                "content_preview": _preview,
                "approval_id": agent.pending_action.get("approval_id"),
            }

        _evidence_rest = getattr(agent, '_evidence_bundle', None)
        _persist_evidence_bundle(_evidence_rest, "rest")
        if _evidence_rest and (_evidence_rest.get('documents') or _evidence_rest.get('evidence_items')):
            result['source_documents'] = _evidence_rest
            result['evidence_trace_id'] = _evidence_rest.get('trace_id')

        if dc:
            # Summarize tool calls (strip large output for JSON payload size)
            tool_summary = []
            for tc in (dc.get("tool_calls") or [])[:20]:
                tool_summary.append({
                    "tool": tc.get("tool", "unknown"),
                    "input_preview": str(tc.get("input", ""))[:500],
                    "output_preview": str(tc.get("output_preview", "") or tc.get("output", ""))[:500],
                    "duration_ms": tc.get("duration_ms", 0),
                    "has_error": tc.get("has_error", False),
                })
            result["reasoning_context"] = {
                "routing": dc.get("routing", {}),
                "context_used": dc.get("context_used", {}),
                "outcome": dc.get("outcome", {}),
                "tool_calls": tool_summary,
                "reasoning_summary": dc.get("reasoning_summary", ""),
                "trace_id": dc.get("trace_id", ""),
                "critique": dc.get("critique"),  # None when critique disabled
            }

        _capture_rl_turn_best_effort(
            agent=agent,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=request_session_id or f"{tenant_id}:{user_id}",
            trace_id=_rl_trace_id,
            content=content,
            response=str(result.get("response") or ""),
            skill_name=skill_name,
            decision_context=dc if isinstance(dc, dict) else None,
            status="partial" if hitl_data else "success",
            metadata={"transport": "rest"},
        )

        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error("Chat endpoint error:\n%s", traceback.format_exc())
        _capture_rl_turn_best_effort(
            agent=agent,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=request_session_id or f"{tenant_id}:{user_id}",
            trace_id=uuid.uuid4().hex,
            content=locals().get("content", msg.content),
            response=str(e),
            skill_name=str(locals().get("skill_name") or msg.skill_name or ""),
            decision_context=getattr(agent, "_last_decision_context", None)
            if isinstance(getattr(agent, "_last_decision_context", None), dict)
            else None,
            status="failed",
            metadata={"transport": "rest", "error": str(e)},
        )
        return {"error": str(e)}


def _rearmed_pending_payload(agent):
    """After execute_approved_action, continue-the-turn may have re-paused on a NEW
    dangerous tool call (multi-step HITL). If the agent has a fresh pending_action,
    return the pending_approval payload (same shape a normal turn emits) so the chat UI
    can wire new approve buttons; otherwise None."""
    pa = getattr(agent, "pending_action", None)
    if not pa:
        return None
    _tc = getattr(agent, "pending_tool_call", None) or {}
    _tc_args = _tc.get("args", {}) if isinstance(_tc, dict) else {}
    _preview = _tc_args.get("content") or _tc_args.get("command") or ""
    return {
        "operation": pa.get("operation"),
        "target": pa.get("target"),
        "command": pa.get("command"),
        "content_preview": _preview,
        "approval_id": pa.get("approval_id"),
    }


async def _resolve_cold_approval(req, tenant_id, user_id, background_tasks, request):
    """B4 cold path: no warm in-memory pending found. Resolve the durable ApprovalStore
    row (by req.approval_id, else by scanning the user's pending stream-intercept rows)
    and delegate to the durable resolver, which rebuilds the agent and runs the exact
    held call. Returns the resolver's result dict."""
    from routers.approvals import resolve_hitl_decision
    aid = req.approval_id
    if not aid:
        try:
            rows = await approval_store.get_pending(tenant_id)
        except Exception:
            rows = []
        matches = [
            a for a in rows
            if (getattr(a, "context", {}) or {}).get("resume_kind") == "stream_intercept"
            and getattr(a, "user_id", None) == user_id
        ]
        if len(matches) > 1:
            raise HTTPException(409, "Multiple pending approvals — pass approval_id")
        if matches:
            aid = matches[0].id
    if not aid:
        raise HTTPException(404, "No pending action to approve")
    # Confirms the caller's own held tool call; the id must be a stream-intercept row owned by this caller and tenant.
    approval = await approval_store.get_approval(aid)
    if (
        not approval
        or getattr(approval, "tenant_id", None) != tenant_id
        or getattr(approval, "user_id", None) != user_id
        or (getattr(approval, "context", {}) or {}).get("resume_kind") != "stream_intercept"
    ):
        raise HTTPException(404, "No pending action to approve")
    decision = "Approve" if req.approved else "Reject"
    result = await resolve_hitl_decision(
        aid,
        decision=decision,
        decided_by=user_id,
        background_tasks=background_tasks,
    )
    return {"response": "Approval resolved; resuming.", "approved": req.approved, **(result or {})}


@router.post("/api/approve")
async def approve_action(req: KernelApprovalRequest, request: Request, background_tasks: BackgroundTasks):
    """
    Handle user approval/rejection of pending action.

    When kernel blocks a write/delete operation in ask-first mode,
    the agent stores a pending_action. This endpoint executes or
    rejects that pending action.
    """
    # Resolve identity as the chat turn does (authenticated user, not the body value) so approve hits the right session pool.
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request,
        requested_tenant=req.tenant_id,
        requested_agent=req.agent_id,
        requested_user=req.user_id,
    )
    user_role = principal.roles[0] if principal.roles else "user"
    if req.session_id:
        agent = await state.get_or_create_session_async(tenant_id, agent_id, user_id, req.session_id, user_role=user_role)
    else:
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)

    # If the resolved agent has no pending (e.g. session_id omitted and we got the
    # bare template, or the wrong session), find the instance that actually holds it.
    if not agent.pending_action:
        pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role=user_role)
        if len(pendings) == 1:
            agent = pendings[0]
        elif len(pendings) > 1:
            raise HTTPException(409, "Multiple pending actions — include the session_id of the one to resolve")
        else:
            # Warm instance gone: resolve durably by approval_id (or scan pending rows) and run the held call on a rebuilt agent.
            return await _resolve_cold_approval(req, tenant_id, user_id, background_tasks, request)

    # The approved action runs now, so it must run under this caller's entitlements (a
    # pending found via find_agents_with_pending may be an instance this request never bound).
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))

    if req.approved:
        _prior_id = _stream_intercept_approval_id(agent)
        response = agent.execute_approved_action(edited_content=req.edited_content)
        # Reconcile the durable row, then persist cleaned state so a Redis reload cannot resurrect the pending.
        await _reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, user_id, "approve")
        await state.save_agent_state(agent, tenant_id, agent_id, user_id)
        await dashboard.broadcast({
            "type": "approval_resolved",
            "user_id": user_id,
            "action": "approved",
            "operation": "approved_action",
        })
        # Continue-the-turn may re-pause on a NEW dangerous call — surface it so the
        # caller (and the dashboard) can wire the next approval.
        _rearmed = _rearmed_pending_payload(agent)
        if _rearmed:
            await dashboard.broadcast({
                "type": "approval_new",
                "user_id": user_id,
                "skill": agent.pending_action.get("skill"),
                "operation": _rearmed.get("operation"),
                "target": _rearmed.get("target"),
            })
            return {"response": response, "approved": True, "pending_approval": _rearmed}
        return {"response": response, "approved": True}
    else:
        _prior_id = _stream_intercept_approval_id(agent)
        response = agent.reject_pending_action()
        await _reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, user_id, "reject")
        await state.save_agent_state(agent, tenant_id, agent_id, user_id)
        await dashboard.broadcast({
            "type": "approval_resolved",
            "user_id": user_id,
            "action": "rejected",
            "operation": "rejected_action",
        })
        return {"response": response, "approved": False}


@router.get("/api/reasoning/{trace_id}")
async def get_episode_reasoning(
    trace_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Fetch LLM-extracted reasoning for a given trace_id.

    The reasoning is extracted asynchronously after the response is returned,
    so the UI polls this endpoint after a short delay to retrieve it.
    Returns reasoning + entities from episode_vectors table.
    """
    import sqlite3
    from pathlib import Path as _Path
    from iaf_agent_skills.sqlite_util import connect as _sqlite_connect

    native_reasoning = None
    # Prefer the live indexer accessor (SQLite and Postgres); fall back to raw sqlite3 only when none is resolvable.
    db_path = None
    row = None
    used_accessor = False
    user_role = getattr(request.state, "role", None) or "user"
    try:
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        dc = getattr(agent, "_last_decision_context", None) or {}
        if isinstance(dc, dict) and str(dc.get("trace_id") or "") == trace_id:
            native_reasoning = dc.get("native_reasoning")
        ki = getattr(agent, 'memory', None) and getattr(agent.memory, 'knowledge_indexer', None)
        if ki and hasattr(ki, 'get_episode_reasoning_row'):
            row = ki.get_episode_reasoning_row(trace_id)
            used_accessor = True
        elif ki and hasattr(ki, 'db_path'):
            candidate = _Path(str(ki.db_path))
            if candidate.exists():
                db_path = candidate
    except Exception as _db_err:
        logger.warning("Could not resolve reasoning from agent knowledge_indexer, using fallback: %s", _db_err)

    # Fallback: check common paths (only when the accessor was unavailable)
    if not used_accessor and not db_path:
        for candidate in [
            SERVER_DIR.parent / "enterprise_root" / "tenants" / tenant_id / "agents" / agent_id / "memory" / "knowledge_index.db",
            SERVER_DIR.parent / "IAF-Agent-Skills" / "memory" / "knowledge_index.db",
            _Path("memory/knowledge_index.db"),
        ]:
            if candidate.exists():
                db_path = candidate
                break

    if not used_accessor and not db_path:
        return {"reasoning": None, "entities": [], "status": "db_not_found", "native_reasoning": native_reasoning}

    try:
        if not used_accessor:
            # busy_timeout: a concurrent indexer write must not surface as 'database is locked'.
            conn = sqlite3.connect(str(db_path), timeout=30.0)
            conn.execute("PRAGMA busy_timeout=30000")
            cur = conn.cursor()
            cur.execute(
                "SELECT reasoning, entities FROM episode_vectors WHERE trace_id = ? LIMIT 1",
                (trace_id,),
            )
            row = cur.fetchone()
            conn.close()

        if not row:
            return {"reasoning": None, "entities": [], "status": "not_ready", "native_reasoning": native_reasoning}

        reasoning = row[0]
        entities_raw = row[1]
        entities = []
        if entities_raw:
            try:
                entities = json.loads(entities_raw)
            except Exception as _json_err:
                logger.warning("Failed to JSON-parse entities_raw, using raw string fallback: %s", _json_err)
                entities = [entities_raw]

        if not reasoning:
            return {"reasoning": None, "entities": entities, "status": "not_ready", "native_reasoning": native_reasoning}

        if " | " in reasoning and reasoning.strip().startswith("routed:"):
            return {"reasoning": None, "entities": entities, "status": "not_ready", "native_reasoning": native_reasoning}

        return {"reasoning": reasoning, "entities": entities, "status": "ready", "native_reasoning": native_reasoning}
    except Exception as e:
        logger.error("Reasoning context fetch failed for trace_id=%s: %s", trace_id, e, exc_info=True)
        return {"reasoning": None, "entities": [], "status": "error", "error": "An internal error occurred", "native_reasoning": native_reasoning}


@router.get("/api/pending")
async def get_pending(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Check if agent has a pending action (kernel-level or HITL)."""
    user_role = getattr(request.state, "role", None) or "user"
    if AUTH_ENABLED:
        user_id = getattr(request.state, "email", None) or getattr(request.state, "user_id", None) or user_id
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    result = {"has_pending": False}

    if agent.pending_action:
        result = {
            "has_pending": True,
            "operation": agent.pending_action.get("operation"),
            "target": agent.pending_action.get("target"),
            "command": agent.pending_action.get("command"),
            "skill": agent.pending_action.get("skill"),
        }
    elif getattr(agent, "approval_pending", None):
        ap = agent.approval_pending
        result = {
            "has_pending": True,
            "type": "hitl",
            "approval_id": ap.get("approval_id"),
            "reason": ap.get("reason"),
            "urgency": ap.get("urgency"),
        }

    return result


@router.post("/api/batch")
async def batch_process(batch: BatchJobRequest, request: Request):
    """
    Process multiple requests in parallel with configurable concurrency.

    Example:
        POST /api/batch
        {
            "items": [
                {"content": "What is 2+2?", "item_id": "calc1"},
                {"content": "What is 3+3?", "item_id": "calc2"}
            ],
            "max_concurrent": 3
        }
    """
    import uuid

    # Bind the batch to the caller: tenant/user from the body are only honoured when they
    # match the authenticated principal, and every item runs under its entitlements.
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request,
        requested_tenant=batch.tenant_id,
        requested_agent=batch.agent_id,
        requested_user=batch.user_id,
    )
    user_role = principal.roles[0] if principal.roles else "user"
    checker = make_agent_entitlement_checker(principal)
    batch_id = str(uuid.uuid4())[:8]
    lane_name = f"batch:{tenant_id}:{batch_id}"

    logger.info(
        "Batch job started: %s with %d items (max_concurrent=%d)",
        batch_id, len(batch.items), batch.max_concurrent,
    )

    # Get router from a template agent (only needed if no default_skill)
    _router = None
    if not batch.default_skill:
        template_agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        _router = template_agent.router
    else:
        logger.debug("Using default_skill='%s' (router skipped)", batch.default_skill)

    results = []
    completed = 0
    failed = 0

    async def process_item(item: BatchRequest, index: int):
        nonlocal completed, failed
        item_id = item.item_id or f"item_{index}"

        try:
            # Use skill priority: item.skill_name > batch.default_skill > router
            skill_name = item.skill_name or batch.default_skill
            if not skill_name:
                skill_name = await asyncio.to_thread(_router.match, item.content)  # Only call router if needed

            # Fresh agent per item (unique user id) avoids state collision on instance attrs.
            batch_user_id = f"batch_{batch_id}_{index}"
            item_agent = state.get_or_create(tenant_id, agent_id, batch_user_id, user_role=user_role)
            item_agent.set_entitlement_context(principal, checker)
            item_agent.auto_run = not batch.human_approval
            item_agent._telemetry_entrypoint = "batch"

            # Execute through queue (respects max_concurrent)
            response = await queue_manager.enqueue(
                lane_name,
                lambda agent=item_agent, content=item.content, skill=skill_name: agent.run(
                    content, skill_name=skill, skip_memory=True
                ),
                max_concurrent=batch.max_concurrent,
            )

            completed += 1
            logger.info("[%s] Item %s completed (%d/%d)", batch_id, item_id, completed, len(batch.items))
            return {
                "item_id": item_id,
                "status": "success",
                "skill": skill_name,
                "response": response,
            }
        except Exception as e:
            failed += 1
            logger.error("[%s] Item %s failed: %s", batch_id, item_id, e)
            return {
                "item_id": item_id,
                "status": "error",
                "error": "An internal error occurred",
            }

    # Launch all tasks concurrently — queue handles the concurrency limit
    tasks = [process_item(item, i) for i, item in enumerate(batch.items)]
    results = await asyncio.gather(*tasks)

    logger.info("Batch job completed: %s (%d success, %d failed)", batch_id, completed, failed)

    return {
        "batch_id": batch_id,
        "total": len(batch.items),
        "completed": completed,
        "failed": failed,
        "results": results,
    }


@router.get("/api/batch/status/{batch_id}")
async def batch_status(batch_id: str):
    """Get status of a batch job by checking the queue."""
    lane_name = f"batch:company:{batch_id}"

    try:
        status = await queue_manager.get_queue_status(lane_name)
        return {"batch_id": batch_id, "lane": lane_name, "status": status}
    except Exception as e:
        logger.error("Batch status check failed for batch_id=%s: %s", batch_id, e, exc_info=True)
        return {"batch_id": batch_id, "error": "An internal error occurred"}


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, token: str = None):
    """
    WebSocket for streaming chat with reasoning trace.

    Client sends: {"content": "...", "tenant_id": "...", "agent_id": "...", "user_id": "..."}
    Server sends:
      - {"type": "routing", "skill": "..."}
      - {"type": "tool_call", "tool": "shell", "args": {"command": "..."}}
      - {"type": "tool_result", "result": "..."}
      - {"type": "response", "content": "..."}
      - {"type": "error", "message": "..."}
    """
    await websocket.accept()
    if not token:
        token = websocket.cookies.get("iaf_access_token")
    _chat_user_key = None   # Track for cleanup (sentinel: has this socket registered?)
    _chat_reg_keys: list = []   # All (tenant, id) keys this socket registered under
    _ws_lock = asyncio.Lock()
    _send_gate = WsSendGate(websocket)   # Latches once the socket is gone → later sends short-circuit
    _active_tasks: set = set()
    _active_run_ids: set = set()   # cooperative-cancel run ids for in-flight turns

    async def safe_send(payload: dict) -> None:
        """Send JSON to the WebSocket under a lock so concurrent session tasks don't interleave.

        Once the client has navigated away, a streaming turn can otherwise call this for
        every remaining token — each one failing and logging. The gate latches on the
        first failure (or a not-CONNECTED state) so the rest of the turn stays quiet.
        """
        async with _ws_lock:
            if not _send_gate.allow():
                return
            try:
                await websocket.send_json(payload)
            except Exception as _send_err:
                # Expected whenever the client already navigated away / closed the tab
                # while a background task was still mid-turn — not an error condition.
                _send_gate.mark_closed()   # Stop hammering a dead socket for the rest of the turn
                logger.info("safe_send failed (socket likely closed): %s", _send_err)  # Never crash the handler

    async def handle_one_message(data: dict, run_id: str = "") -> None:
        """Process a single incoming WS message end-to-end.

        Runs as an asyncio.Task so multiple concurrent sessions execute in parallel.
        All logic is unchanged from the original loop body — only `continue` → `return`
        and `websocket.send_json` → `safe_send` to support concurrent dispatch.

        `run_id` keys the cooperative-cancellation registry: agent.run polls
        run_cancellation.is_cancelled(run_id) at its step boundaries so a UI Stop
        actually halts the backend thread (which asyncio task.cancel() cannot).
        """
        _cancel_check = run_cancellation.make_check(run_id) if run_id else None
        content = data.get("content", "")
        tenant_id = data.get("tenant_id", "company")
        agent_id = data.get("agent_id", "enterprise_agent")
        user_id = data.get("user_id", "demo")
        skill_name = data.get("skill_name")
        human_approval = data.get("human_approval", True)
        render_ui = data.get("render_ui", False)
        light_mode = data.get("light_mode", False)
        knowledge_mode = data.get("knowledge_mode")
        profile = data.get("profile")  # Harness execution profile (None → agent/tenant default)
        source_page = data.get("source_page")
        page_context = data.get("page_context")
        request_session_id = data.get("session_id")  # Per-session routing
        plan_requested = data.get("plan_requested", False)  # UI explicit plan request
        force_plan      = data.get("force_plan", False)       # UI Plan Mode toggle
        agent = None
        routed_skill = skill_name or ""
        # Unique per-request trace_id even when light mode skips begin_trace.
        import uuid as _uuid
        _request_trace_id = _uuid.uuid4().hex
        # UI critique_mode: "off" | "sync" | "async"
        # Fallback: legacy boolean enable_critique for backwards compat
        _raw_critique = data.get("critique_mode", None)
        if _raw_critique is None:
            _raw_critique = "sync" if data.get("enable_critique", False) else "off"
        critique_mode = _raw_critique  # "off" | "sync" | "async"

        # Bind identity from WS token. Browser-supplied user/tenant are only
        # accepted in dev mode; production uses the token subject + user store.
        user_role = "user"
        principal = None
        if token:
            try:
                from auth.identity import bind_identity_to_tenant
                from auth.middleware import SessionSupersededError, authenticate_access_token
                from auth.session_registry import SESSION_REVOKED, SESSION_SUPERSEDED
                # Re-validated per message (signature/expiry, revocation, session, user-store lookup for email/roles/groups).
                try:
                    _resolved, _user_record = await authenticate_access_token(token)
                except SessionSupersededError as _ended:
                    _code = str(_ended) or SESSION_SUPERSEDED
                    await safe_send({
                        "type": "error",
                        "code": _code,
                        "message": (
                            "You were signed out because your session was ended from another device or by an administrator."
                            if _code == SESSION_REVOKED else
                            "You were signed out because your account signed in from another browser or device."
                        ),
                    })
                    return
                _identity = bind_identity_to_tenant(_resolved, tenant_id)
                user_role = _identity.roles[0] if _identity.roles else "user"
                # Ignore browser-supplied user_id in authenticated mode.
                from shared.config import DATA_ROOT_PATH
                from shared.filesystem_identity import coerce_filesystem_user_id
                user_id = coerce_filesystem_user_id(
                    user_id=_identity.user_id,
                    email=_identity.email,
                    data_root=DATA_ROOT_PATH,
                    tenant_id=tenant_id,
                    agent_id=agent_id or "enterprise_agent",
                )
                principal = _identity.to_principal()
                # This socket bypasses AuthMiddleware, so the temporary-password gate is applied here.
                from auth.middleware import (
                    ACCOUNT_DISABLED,
                    PASSWORD_CHANGE_REQUIRED,
                    account_is_disabled,
                    password_rotation_outstanding,
                )
                # Disabled-account cutoff, enforced per message (socket bypasses AuthMiddleware); reuse the identity lookup's record.
                _user_kw = {"user": _user_record} if _user_record is not None else {}
                if await account_is_disabled(_identity.user_id, **_user_kw):
                    await safe_send({
                        "type": "error",
                        "code": ACCOUNT_DISABLED,
                        "message": "Account is disabled. Contact your administrator.",
                    })
                    return
                if await password_rotation_outstanding(_identity.user_id, **_user_kw):
                    await safe_send({
                        "type": "error",
                        "code": PASSWORD_CHANGE_REQUIRED,
                        "message": "Your temporary password must be changed before continuing.",
                    })
                    return
            except PermissionError:
                await safe_send({"type": "error", "message": "Tenant access denied"})
                return
            except Exception as _tok_err:
                logger.warning("WS token decode failed: %s", _tok_err)
                if AUTH_ENABLED:
                    await safe_send({"type": "error", "message": "Invalid or expired token"})
                    return
                from auth.identity import create_dev_identity
                _identity = create_dev_identity(tenant_id, user_id=user_id)
                user_role = _identity.roles[0] if _identity.roles else "user"
                principal = _identity.to_principal()
        elif AUTH_ENABLED:
            await safe_send({"type": "error", "message": "Authentication required"})
            return
        else:
            from auth.identity import create_dev_identity
            _identity = create_dev_identity(tenant_id, user_id=user_id)
            user_role = _identity.roles[0] if _identity.roles else "user"
            principal = _identity.to_principal()

        try:
            enforce_entitlement(principal, "use", "agent", agent_id)
        except HTTPException as exc:
            await safe_send({"type": "error", "message": str(exc.detail)})
            return

        if request_session_id:
            agent = await state.get_or_create_session_async(
                tenant_id, agent_id, user_id, request_session_id, user_role=user_role
            )
        else:
            agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))

        # Advertise a session id only if the client supplied one, else the reply is stashed under a server-picked session.
        _origin_sid = agent.session_id if request_session_id else ""

        # Check if user is responding to a pending approval via text
        content_lower = content.strip().lower()
        msg_type = data.get("type", "chat")  # "chat" | "plan_action" | "plan_feedback"

        if msg_type == "plan_action":
            _action = data.get("action", "")        # "approve" | "reject" | "modify"
            _plan_id = data.get("plan_id", "")
            _feedback = data.get("feedback", "")     # Free-text for "modify"

            _pending = getattr(agent, '_pending_plan', None)

            # Validate: pending plan must exist and plan_id must match
            if not _pending:
                await safe_send({
                    "type": "error",
                    "message": "No pending plan to act on.",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return
            if _plan_id and _pending.get("plan_id") != _plan_id:
                await safe_send({
                    "type": "error",
                    "message": f"Plan ID mismatch: expected {_pending.get('plan_id')}, got {_plan_id}",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return

            if _action == "approve":
                logger.info("PLANNER: Structured approve for plan %s", _pending.get("plan_id"))
                await safe_send({
                    "type": "status",
                    "status": "Executing confirmed plan...",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })

                loop = asyncio.get_running_loop()

                def _plan_status_cb_structured(msg):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            safe_send({
                                "type": "status",
                                "status": str(msg),
                                "origin_session_id": _origin_sid,
                                "timestamp": datetime.now().isoformat(),
                            }),
                            loop,
                        )
                    except Exception as _scb_err:
                        logger.warning("Plan status_callback (structured) WS send failed: %s", _scb_err)

                try:
                    plan_result = await asyncio.to_thread(
                        agent.execute_confirmed_plan,
                        status_callback=_plan_status_cb_structured,
                    )
                except Exception as e:
                    logger.error("Plan execution failed (structured approve): %s", e, exc_info=True)
                    plan_result = f"Plan execution error: {e}"

                try:
                    _indexer = getattr(agent.memory, 'knowledge_indexer', None)
                    _pending_plan = getattr(agent, '_pending_plan', None) or getattr(agent, '_last_executed_plan', None)
                    if _indexer and _pending_plan and hasattr(_indexer, 'upsert_plan_cache'):
                        import uuid as _uuid
                        _steps = _pending_plan.get("steps", [])
                        _critique = _pending_plan.get("critique")
                        _domains = _pending_plan.get("detected_domains", [])
                        _indexer.upsert_plan_cache(
                            plan_id=_pending_plan.get("plan_id", f"plan_{_uuid.uuid4().hex[:12]}"),
                            goal=content,
                            plan_steps=_steps,
                            execution_mode="planned",
                            detected_domains=_domains,
                            critique_json=_critique,
                            session_id=getattr(agent, 'session_id', None),
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            executed_at=datetime.now().isoformat(),
                            embedding=getattr(agent, '_cached_query_embedding', None),
                        )
                except Exception as _pce:
                    logger.warning("plan_cache multi-skill write failed (non-fatal): %s", _pce)

                await safe_send({
                    "type": "response",
                    "content": plan_result,
                    "skill": "planner",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return

            elif _action == "reject":
                logger.info("PLANNER: Structured reject for plan %s", _pending.get("plan_id"))
                agent._pending_plan = None
                await safe_send({
                    "type": "response",
                    "content": "Plan cancelled. How can I help you?",
                    "skill": "planner",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return

            else:
                # Unknown action — includes "modify" which is now handled by
                # the ReAct agent via create_plan tool and conversation history.
                await safe_send({
                    "type": "error",
                    "message": f"Unknown plan action: '{_action}'. Use approve or reject. "
                               f"To modify the plan, type your changes as a normal message.",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return

        if msg_type == "plan_feedback":
            _fb_plan_id = data.get("plan_id", "")
            _fb_overall = data.get("overall", "")       # "good" | "poor"
            _fb_steps = data.get("step_feedback", {})    # {step_id: {rating, note}}

            logger.info("PLANNER FEEDBACK: plan=%s overall=%s steps=%d",
                        _fb_plan_id, _fb_overall, len(_fb_steps))

            try:
                for step_id, fb in _fb_steps.items():
                    rating = fb.get("rating", "")
                    note = fb.get("note", "")
                    if rating and hasattr(agent, 'memory') and hasattr(agent.memory, 'write_knowledge'):
                        agent.memory.write_knowledge(
                            knowledge_type="plan_step_feedback",
                            summary=f"Plan step '{step_id}' rated '{rating}'"
                                    + (f": {note}" if note else ""),
                            applies_when=f"plan execution, step {step_id}",
                            source="user_feedback",
                            status="confirmed" if rating == "good" else "pending_review",
                            skill="planner",
                            tags=["plan_feedback", rating, step_id],
                            user_query=_fb_plan_id,
                        )
            except Exception as fb_err:
                logger.warning("Plan feedback recording failed (non-fatal): %s", fb_err)

            await safe_send({
                "type": "response",
                "content": "Thanks for the feedback — noted for future plan improvements.",
                "skill": "planner",
                "origin_session_id": _origin_sid,
                "timestamp": datetime.now().isoformat(),
            })
            return

        if agent.pending_action:
            approve_words = {"approve", "approved", "yes", "ok", "proceed", "go ahead", "do it", "confirmed", "y"}
            reject_words = {"reject", "no", "cancel", "stop", "don't", "abort", "n"}

            if content_lower in approve_words:
                _prior_id = _stream_intercept_approval_id(agent)
                response = agent.execute_approved_action()
                # Reconcile the durable row (resolve+delete; re-checkpoint if re-paused),
                # then persist the cleaned session state.
                await _reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, user_id, "approve")
                await state.save_agent_state(agent, tenant_id, agent_id, user_id)
                # Continue-the-turn may re-pause on a NEW dangerous call. If so, re-emit
                # the approval signal so the chat UI wires fresh approve buttons.
                _rearmed = _rearmed_pending_payload(agent)
                _resp = {
                    "type": "response",
                    "content": response,
                    "skill": "approval",
                    "timestamp": datetime.now().isoformat()
                }
                if _rearmed:
                    _resp["pending_approval"] = _rearmed
                await safe_send(_resp)
                await dashboard.broadcast({
                    "type": "approval_resolved",
                    "user_id": user_id,
                    "action": "approved",
                })
                if _rearmed:
                    await dashboard.broadcast({
                        "type": "approval_new",
                        "user_id": user_id,
                        "skill": agent.pending_action.get("skill"),
                        "operation": _rearmed.get("operation"),
                        "target": _rearmed.get("target"),
                    })
                return
            elif content_lower in reject_words:
                _prior_id = _stream_intercept_approval_id(agent)
                response = agent.reject_pending_action()
                await _reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, user_id, "reject")
                await state.save_agent_state(agent, tenant_id, agent_id, user_id)
                await safe_send({
                    "type": "response",
                    "content": response,
                    "skill": "approval",
                    "timestamp": datetime.now().isoformat()
                })
                await dashboard.broadcast({
                    "type": "approval_resolved",
                    "user_id": user_id,
                    "action": "rejected",
                })
                return

        if agent.approval_pending:
            approve_words = {"approve", "approved", "yes", "ok", "proceed", "go ahead", "do it", "confirmed", "y"}
            reject_words = {"reject", "no", "cancel", "stop", "don't", "abort", "n"}
            escalate_words = {"escalate", "manager", "escalate to manager"}

            if content_lower in approve_words or content_lower in reject_words or content_lower in escalate_words:
                ap = agent.approval_pending
                approval_id = ap.get("approval_id")

                if content_lower in approve_words:
                    decision = "approve"
                elif content_lower in reject_words:
                    decision = "reject"
                else:
                    decision = "escalate_to_manager"

                # Approving is a policy-controlled right, not something the requester gets by
                # typing "yes" in their own chat. Rejecting (withdrawing) their own request is fine.
                if decision == "approve" and not make_agent_entitlement_checker(principal)(
                    "approve", "approval", str(approval_id or "unknown"),
                    {"skill": ap.get("skill", ""), "source": "chat", "requested_by": user_id},
                ):
                    await safe_send({
                        "type": "response",
                        "content": (
                            "This request needs an authorised approver, so it is waiting in the "
                            "approvals queue. You can still reply 'reject' to withdraw it."
                        ),
                        "skill": "approval",
                        "timestamp": datetime.now().isoformat(),
                    })
                    return

                logger.info("HITL resolved via chat: %s -> %s", approval_id, decision)

                # Resolve in Redis store — exactly once. If it was already decided elsewhere
                # (e.g. the approvals page), that decision stands and nothing is re-run here.
                try:
                    resolved, _decided_now = await approval_store.claim_resolution(
                        approval_id=approval_id,
                        decision=decision,
                        decided_by=user_id,
                        decision_note=f"Resolved via chat: '{content}'",
                    )
                except Exception as _res_err:
                    logger.warning("approval_store.claim_resolution failed (approval_id=%s): %s", approval_id, _res_err)
                    resolved, _decided_now = None, True
                if resolved and not _decided_now:
                    agent.approval_pending = None
                    await safe_send({
                        "type": "response",
                        "content": (
                            f"This request was already {resolved.status}"
                            + (f" by {resolved.decided_by}" if resolved.decided_by else "") + "."
                        ),
                        "skill": "approval",
                        "timestamp": datetime.now().isoformat(),
                    })
                    return
                try:
                    _ap_context = ap.get("context") or {}
                    emit_agentpro_reward(
                        data_root=DATA_ROOT_PATH,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        channel="human_approval",
                        raw_label=decision,
                        target_id=str(approval_id or ""),
                        trajectory_id=str(_ap_context.get("trace_id") or _request_trace_id),
                        judge_id=user_id,
                        notes=ap.get("reason", ""),
                        source_event_id=str(approval_id or ""),
                        source_trace_id=str(_ap_context.get("trace_id") or _request_trace_id),
                        metadata={
                            "source": "chat_ws",
                            "context": _ap_context,
                            "resolved_status": getattr(resolved, "status", "") if resolved else "",
                        },
                    )
                except Exception as _rl_hitl_err:
                    logger.warning("RL HITL chat decision capture failed (non-fatal): %s", _rl_hitl_err)

                # Fire OnApprovalResolved on the inline-chat resume path (parity with Command Center); must run before agent.run().
                _hook_runner = getattr(agent, "hook_runner", None)
                if _hook_runner:
                    try:
                        _sctx = agent._build_session_ctx() if hasattr(agent, "_build_session_ctx") else {}
                    except Exception:
                        _sctx = {}
                    _sctx = {
                        **(_sctx or {}),
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "user_id": user_id,
                        "skill_name": ap.get("skill", "") or _sctx.get("skill_name", ""),
                        "current_skill": ap.get("skill", "") or _sctx.get("current_skill", "") or _sctx.get("skill_name", ""),
                        "entrypoint": "hitl_resume",
                    }
                    try:
                        _hook_runner.run_on_approval_resolved(
                            approval_id=approval_id,
                            decision=decision,
                            decided_by=user_id,
                            decision_note=f"Resolved via chat: '{content}'",
                            reason=ap.get("reason", ""),
                            session_ctx=_sctx,
                        )
                    except Exception as _hook_err:
                        logger.warning("OnApprovalResolved hook failed on inline resume (non-fatal): %s", _hook_err)

                agent.approval_pending = None

                # On APPROVE, a `next_step` spec launches that step as a fresh top-level turn; it only sequences turns and never authorizes a write.
                _next_step = None
                if decision == "approve":
                    _ns = (ap.get("context") or {}).get("next_step")
                    # next_step can originate from model-provided context, so validate
                    # types: only accept a dict whose `skill` is a non-empty string.
                    if isinstance(_ns, dict) and isinstance(_ns.get("skill"), str) and _ns.get("skill").strip():
                        _next_step = _ns

                try:
                    if _next_step:
                        # New stage may pause afresh — keep the resume guard OFF.
                        agent._hitl_decision_injected = False
                        _ns_skill = _next_step.get("skill")  # validated str above
                        # Point the approval record's skill at the skill that actually runs.
                        ap["skill"] = _ns_skill
                        # query/task may also be model-provided — coerce to a string
                        # so agent.run() never receives a non-str (crash/misroute).
                        _ns_q = _next_step.get("query") or _next_step.get("task") or ""
                        _ns_query = _ns_q if isinstance(_ns_q, str) else str(_ns_q)
                        logger.info(
                            "Named next-step resume: launching skill='%s' after approval_id=%s (reason=%s)",
                            _ns_skill, approval_id, ap.get("reason", ""),
                        )
                        resume_response = await asyncio.to_thread(
                            agent.run,
                            _ns_query,
                            skill_name=_ns_skill,
                        )
                    else:
                        # Same-skill re-plan: inject the decision and suppress a re-pause of the resolved stage.
                        agent._hitl_decision_injected = True  # Suppress re-trigger
                        if decision == "approve":
                            injection = (
                                f"[HUMAN DECISION] The approval '{ap.get('reason', '')}' was APPROVED "
                                f"by {user_id}. The requested action is authorized — proceed."
                            )
                        elif decision == "reject":
                            injection = (
                                f"[HUMAN DECISION] The approval '{ap.get('reason', '')}' was REJECTED "
                                f"by {user_id}. The requested action was denied — do NOT proceed. Inform the user."
                            )
                        else:
                            injection = (
                                f"[HUMAN DECISION] The approval '{ap.get('reason', '')}' was ESCALATED "
                                f"by {user_id}. Inform the user this has been escalated to a manager."
                            )

                        # Run off the event loop: agent.run() blocks and the resumed skill may call back into this server (self-call deadlock).
                        resume_response = await asyncio.to_thread(
                            agent.run,
                            injection,
                            skill_name=ap.get("skill", agent.current_skill),
                        )
                except Exception as e:
                    logger.error("Agent resume after HITL decision failed (approval_id=%s): %s", approval_id, e, exc_info=True)
                    resume_response = f"Error resuming: {e}"
                finally:
                    agent._hitl_decision_injected = False

                try:
                    await approval_store.delete_agent_state(approval_id)
                except Exception as _del_err:
                    logger.warning("approval_store.delete_agent_state failed (approval_id=%s): %s", approval_id, _del_err)

                await safe_send({
                    "type": "response",
                    "content": resume_response if isinstance(resume_response, str) else resume_response[0],
                    "skill": ap.get("skill", "approval"),
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat()
                })
                await dashboard.broadcast({
                    "type": "hitl_approval_resolved",
                    "approval_id": approval_id,
                    "status": decision,
                    "decided_by": user_id,
                    "user_id": user_id,
                    "reason": ap.get("reason"),
                })
                # Twin telemetry: HITL event (fire-and-forget)
                if twin_emitter:
                    try:
                        twin_emitter.emit_hitl(
                            user_id=user_id,
                            skill=ap.get("skill", ""),
                            action_type=decision,
                            urgency=ap.get("urgency", "medium"),
                        )
                    except Exception as _te_hitl_err:
                        logger.warning("twin_emitter.emit_hitl failed (non-fatal): %s", _te_hitl_err)
                return

        agent.auto_run = not human_approval
        agent.kernel.require_confirmation = human_approval
        logger.debug("WebSocket: human_approval=%s, auto_run=%s", human_approval, agent.auto_run)

        # Compat shim: route free text to plan_action while a plan is pending; remove once the UI sends plan_action natively.
        _pending_plan = getattr(agent, '_pending_plan', None)
        if _pending_plan and msg_type != "plan_action":
            _approve_words = {"approve", "approved", "yes", "ok", "proceed", "go ahead", "do it", "confirmed", "y"}
            _reject_words = {"reject", "no", "cancel", "stop", "abort", "n"}

            if content_lower in _approve_words:
                _shim_action = "approve"
                _shim_feedback = ""
            elif content_lower in _reject_words:
                _shim_action = "reject"
                _shim_feedback = ""
            else:
                # Any other text = modification request
                _shim_action = "modify"
                _shim_feedback = content

            # Re-inject as structured plan_action and let the handler above process it
            logger.info("PLANNER SHIM: Converting free-text '%s' → plan_action:%s", content[:50], _shim_action)
            data["type"] = "plan_action"
            data["action"] = _shim_action
            data["plan_id"] = _pending_plan.get("plan_id", "")
            data["feedback"] = _shim_feedback
            # Jump back to top of loop — plan_action handler will pick it up
            # We use a websocket re-send to avoid goto
            await safe_send({
                "type": "status",
                "status": f"Processing as plan {_shim_action}...",
                "origin_session_id": _origin_sid,
                "timestamp": datetime.now().isoformat(),
            })
            # Dispatch directly to the plan_action handler code path.
            # Rather than duplicating logic, we process it inline here.
            _pa_pending = _pending_plan
            _pa_action = _shim_action
            _pa_plan_id = _pending_plan.get("plan_id", "")
            _pa_feedback = _shim_feedback

            if _pa_action == "approve":
                logger.info("PLANNER: Shim-approve for plan %s", _pa_pending.get("plan_id"))
                await safe_send({
                    "type": "status",
                    "status": "Executing confirmed plan...",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })

                loop = asyncio.get_running_loop()

                def _plan_status_cb_shim(msg):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            safe_send({
                                "type": "status",
                                "status": str(msg),
                                "origin_session_id": _origin_sid,
                                "timestamp": datetime.now().isoformat(),
                            }),
                            loop,
                        )
                    except Exception as _scb_shim_err:
                        logger.warning("Plan status_callback (shim) WS send failed: %s", _scb_shim_err)

                try:
                    plan_result = await asyncio.to_thread(
                        agent.execute_confirmed_plan,
                        status_callback=_plan_status_cb_shim,
                    )
                except Exception as e:
                    logger.error("Plan execution failed (shim approve): %s", e, exc_info=True)
                    plan_result = f"Plan execution error: {e}"

                try:
                    _indexer = getattr(agent.memory, 'knowledge_indexer', None)
                    _pending_plan = getattr(agent, '_pending_plan', None) or getattr(agent, '_last_executed_plan', None)
                    if _indexer and _pending_plan and hasattr(_indexer, 'upsert_plan_cache'):
                        import uuid as _uuid
                        _steps = _pending_plan.get("steps", [])
                        _critique = _pending_plan.get("critique")
                        _domains = _pending_plan.get("detected_domains", [])
                        _indexer.upsert_plan_cache(
                            plan_id=_pending_plan.get("plan_id", f"plan_{_uuid.uuid4().hex[:12]}"),
                            goal=content,
                            plan_steps=_steps,
                            execution_mode="planned",
                            detected_domains=_domains,
                            critique_json=_critique,
                            session_id=getattr(agent, 'session_id', None),
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            executed_at=datetime.now().isoformat(),
                            embedding=getattr(agent, '_cached_query_embedding', None),
                        )
                except Exception as _pce:
                    logger.warning("plan_cache multi-skill write failed (non-fatal): %s", _pce)

                await safe_send({
                    "type": "response",
                    "content": plan_result,
                    "skill": "planner",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return

            elif _pa_action == "reject":
                logger.info("PLANNER: Shim-reject for plan %s", _pa_pending.get("plan_id"))
                agent._pending_plan = None
                await safe_send({
                    "type": "response",
                    "content": "Plan cancelled. How can I help you?",
                    "skill": "planner",
                    "origin_session_id": _origin_sid,
                    "timestamp": datetime.now().isoformat(),
                })
                return

            # Other text (plan modification or new goal) falls through to agent.run(); the ReAct LLM sees the plan in history and decides.

            # Inject plan_id so the LLM passes existing_plan_id instead of generating a fresh plan.
            content = (
                f"{_shim_feedback}\n\n"
                f"[PLAN MODIFICATION: You are revising an existing plan. "
                f"Call create_plan(existing_plan_id='{_pa_plan_id}', "
                f"feedback='{_shim_feedback}', "
                f"goal='{_pa_pending.get('goal', content)}') "
                f"to produce the revised plan for user confirmation. "
                f"Do NOT create a new plan from scratch.]"
            )
            # Force planning mode so [ROUTING CONTEXT] hint is injected,
            # directing the LLM to call create_plan rather than answer inline.
            force_plan = True

        # Set plan_requested flag on agent so routing can trigger planner
        agent._plan_requested = plan_requested
        content = _compose_page_context_content(content, source_page, page_context)

        # Per-session lane: conversations run in parallel; max_concurrent=1 within one.
        lane_name = f"{QueueNames.session(tenant_id, user_id)}:{agent.session_id}"

        try:
            last_response = None
            if agent.conversation_history:
                last_response = agent.conversation_history[-1].get("response", "")

            # Pre-router entity resolution (table mode only; file mode lets the router LLM extract entities).
            _entity_hint = None
            _entity_confidence = 0.0
            _process_hint = None
            _process_matches = []
            _signals_agree = None
            _resolved_entities = []
            _ws_ctx_mode = getattr(agent, 'context_loading_mode', 'table')
            if _ws_ctx_mode != 'file':
                try:
                    # TABLE MODE only — SQLite entity resolution pre-signal for router
                    _indexer = getattr(agent.memory, "knowledge_indexer", None)
                    _entity_store = getattr(_indexer, "entity_registry", None) if _indexer else None
                    if _entity_store and content:
                        _q_emb = await asyncio.to_thread(_indexer._safe_get_embedding, content)
                        if _q_emb:
                            _ectx = await asyncio.to_thread(
                                _entity_store.collect_context,
                                query_embedding=_q_emb, query_text=content
                            )
                            if _ectx:
                                _entity_hint = _ectx.get("skill_hint")
                                _entity_confidence = _ectx.get("skill_confidence", 0.0)
                                _process_hint = _ectx.get("process_hint")
                                _process_matches = _ectx.get("process_matches", [])
                                _signals_agree = _ectx.get("signals_agree")
                                _resolved_entities = _ectx.get("resolved_entities", [])
                except Exception as _ws_ent_err:
                    logger.warning("Entity resolution pre-signal failed (WS), routing continues: %s", _ws_ent_err)

            # L5 taxonomy pre-signal for all context modes; no readiness pre-check (find_skills() handles it).
            _tax_hints_ws = []
            try:
                _tax_idx_ws = getattr(agent, '_taxonomy_index', None)
                if _tax_idx_ws:
                    _idx_ws = getattr(agent.memory, 'knowledge_indexer', None)
                    if _idx_ws:
                        _emb_ws = await asyncio.to_thread(_idx_ws._safe_get_embedding, content)
                        if _emb_ws:
                            _tax_hints_ws = await asyncio.to_thread(
                                _tax_idx_ws.find_skills,
                                query_embedding=_emb_ws,
                                query_text=content,
                            )
            except Exception as _tax_ws_err:
                logger.debug("Pre-router taxonomy lookup failed (non-fatal): %s", _tax_ws_err)
            logger.info(
                "Pre-router taxonomy signal (WS): %d hits%s",
                len(_tax_hints_ws),
                " — " + ", ".join(
                    f"{h.get('skill')}={h.get('score', 0):.3f}" for h in _tax_hints_ws[:5]
                ) if _tax_hints_ws else "",
            )

            # Route with dual signals — return_details=True preserves execution_mode
            # and detected_domains so agent.py can trigger planned mode correctly.
            _routing_result = await asyncio.to_thread(
                agent.router.match,
                content,
                current_skill=agent.current_skill,
                last_response=last_response,
                entity_hint=_entity_hint,
                entity_confidence=_entity_confidence,
                process_hint=_process_hint,
                process_matches=_process_matches,
                signals_agree=_signals_agree,
                taxonomy_hints=_tax_hints_ws,
                return_details=True,
            ) if not skill_name else {
                "skill": skill_name,
                "execution_mode": "react",
                "detected_domains": [],
                "method": "forced",
                "confidence": 1.0,
                "is_continuation": False,
                "alternatives": [],
            }
            # Force plan mode: populate detected_domains so agent.py injects the [ROUTING CONTEXT] hint.
            if force_plan:
                _routing_result = apply_force_plan_routing(
                    _routing_result,
                    [s["name"] for s in agent.router.list_skills()],
                )
                logger.info(
                    "FORCE PLAN (WS): detected_domains overridden, execution_mode=planned, "
                    "mode_hint=planned, skill forced to general"
                )

            # Propagate critique settings; server-side CRITIQUE_ENABLED/CRITIQUE_MODE are defaults when the UI is 'off'.
            from shared.config import CRITIQUE_ENABLED, CRITIQUE_MODE as _SERVER_CRITIQUE_MODE, CONSISTENCY_CHECK as _SERVER_CONSISTENCY, CRITIQUE_RECHECK as _SERVER_CRITIQUE_RECHECK
            _effective_mode = critique_mode if critique_mode != "off" else (
                _SERVER_CRITIQUE_MODE if CRITIQUE_ENABLED else "off"
            )
            agent.enable_critique    = _effective_mode != "off"  # bool for plan mode compat
            agent.critique_mode      = _effective_mode           # "off" | "sync" | "async"
            # consistency_check: UI can send it, falls back to server-side env var
            _ui_consistency = data.get("consistency_check", None)
            agent.consistency_check  = _ui_consistency if _ui_consistency is not None else _SERVER_CONSISTENCY
            logger.info("Critique mode SET: %s (user=%s)", _effective_mode, user_id)

            routed_skill = _routing_result["skill"]
            try:
                enforce_entitlement(principal, "use", "skill", routed_skill)
            except HTTPException as exc:
                await safe_send({"type": "error", "message": str(exc.detail)})
                return
            await safe_send({
                "type": "routing",
                "skill": routed_skill,
                "entity_hint": _entity_hint,
                "entity_confidence": _entity_confidence,
                "process_hint": _process_hint,
                "process_matches": _process_matches,
                "signals_agree": _signals_agree,
                "resolved_entities": _resolved_entities,
                "origin_session_id": _origin_sid,
                "timestamp": datetime.now().isoformat()
            })

            try:
                _indexer = getattr(agent.memory, "knowledge_indexer", None)
                _entity_store = getattr(_indexer, "entity_registry", None) if _indexer else None
                if _entity_store and hasattr(_entity_store, "log_routing_signal"):
                    _entity_store.log_routing_signal(
                        query_text=content,
                        entity_hint=_entity_hint,
                        entity_confidence=_entity_confidence,
                        process_hint=_process_hint,
                        process_matches=_process_matches,
                        signals_agree=_signals_agree,
                        routed_skill=routed_skill,
                        resolved_entities=_resolved_entities,
                    )
            except Exception as _ws_rs_err:
                logger.warning("Routing signal logging failed (WS, non-fatal): %s", _ws_rs_err)

            await dashboard.broadcast({
                "type": "task_started",
                "user_id": user_id,
                "skill": routed_skill,
            })

            # Twin telemetry: task started (fire-and-forget)
            _twin_task_start = datetime.now()
            if twin_emitter:
                try:
                    twin_emitter.emit_task_started(user_id=user_id, skill=routed_skill)
                except Exception as _te_start_err:
                    logger.warning("twin_emitter.emit_task_started failed (non-fatal): %s", _te_start_err)

            loop = asyncio.get_running_loop()

            _live_activity = {"label": "Starting…", "phase": None, "ts": datetime.now()}

            def _note_activity(label, phase=None):
                label = (label or "").strip()
                if label and label != _live_activity["label"]:
                    _live_activity["label"] = label[:160]
                    _live_activity["phase"] = phase
                    _live_activity["ts"] = datetime.now()
                elif phase and phase != _live_activity["phase"]:
                    _live_activity["phase"] = phase

            def status_callback(msg):
                try:
                    if isinstance(msg, dict) and msg.get("__rlm_event__"):
                        # RLM execution-mode trace event → right-side reasoning panel.
                        payload = {
                            "type": "reasoning_event",
                            "event": msg.get("card_type", "reasoning_event"),
                            "card_type": msg.get("card_type", "reasoning_event"),
                            "label": msg.get("label", ""),
                            "text": msg.get("text", ""),
                            "detail": msg.get("detail", ""),
                            "depth": msg.get("depth", 0),
                            "origin_session_id": agent.session_id,
                            "timestamp": datetime.now().isoformat(),
                        }
                    elif isinstance(msg, dict) and msg.get("__progress__"):
                        payload = {
                            "type": "progress",
                            "phase": msg.get("phase"),
                            "phase_index": msg.get("phase_index", 0),
                            "phase_total": msg.get("phase_total", 6),
                            "status": msg.get("status", "active"),
                            "sub_step": msg.get("sub_step"),
                            "detail": msg.get("detail"),
                            "elapsed_ms": msg.get("elapsed_ms", 0),
                            "origin_session_id": _origin_sid,
                            "timestamp": datetime.now().isoformat(),
                        }
                    else:
                        payload = {
                            "type": "status",
                            "status": str(msg),
                            "origin_session_id": _origin_sid,
                            "timestamp": datetime.now().isoformat(),
                        }
                    # Feed the live-activity tracker so the heartbeat can narrate context.
                    try:
                        if payload["type"] == "reasoning_event":
                            _note_activity(payload.get("label") or payload.get("text") or "Working…")
                        elif payload["type"] == "progress":
                            _lbl = payload.get("sub_step") or payload.get("detail") or payload.get("phase") or "Working…"
                            _note_activity(str(_lbl).replace("_", " ").strip().capitalize(), payload.get("phase"))
                        else:
                            _note_activity(str(payload.get("status") or "Working…"))
                    except Exception:
                        pass
                    asyncio.run_coroutine_threadsafe(
                        safe_send(payload),
                        loop
                    )
                except Exception as _cb_err:
                    logger.warning("status_callback WS send failed (non-fatal): %s", _cb_err)  # Don't break agent if WebSocket send fails

            # Heartbeat: emit the current activity and per-activity elapsed time every 1.5s; the client ticks seconds between beats.
            async def heartbeat_task():
                while True:
                    await asyncio.sleep(1.5)
                    try:
                        _elapsed_ms = int((datetime.now() - _live_activity["ts"]).total_seconds() * 1000)
                        _label = _live_activity["label"] or "Thinking…"
                        await safe_send({
                            "type": "heartbeat",
                            "label": _label,
                            "phase": _live_activity["phase"],
                            "elapsed_ms": _elapsed_ms,
                            "message": f"\U0001f9e0 {_label} · {_elapsed_ms // 1000}s",
                            "origin_session_id": agent.session_id,
                            "timestamp": datetime.now().isoformat()
                        })
                    except Exception as _hb_err:
                        logger.warning("Heartbeat send failed, stopping heartbeat loop: %s", _hb_err)
                        break

            heartbeat = asyncio.create_task(heartbeat_task())

            # Per-request streaming token callback (None when feature flag off)
            _token_callback = _make_streaming_token_callback(safe_send, loop, _origin_sid)

            try:
                async def queued_agent_run():
                    agent._telemetry_entrypoint = "chat_ws"
                    return await asyncio.to_thread(
                        agent.run,
                        content,
                        skill_name=routed_skill,
                        routing_info=_routing_result,
                        return_tool_calls=True,
                        status_callback=status_callback,
                        render_ui=render_ui,
                        light_mode=light_mode,
                        knowledge_mode=knowledge_mode,
                        token_callback=_token_callback,
                        profile=profile,
                        cancel_check=_cancel_check,
                    )

                session_id = f"{tenant_id}:{user_id}:{datetime.now().strftime('%Y%m%d')}"

                async def tracked_agent_run():
                    return await queue_manager.enqueue(
                        lane_name,
                        queued_agent_run,
                        # ⚠️  SAFETY-CRITICAL: must stay 1 — same reason as
                        #    the REST chat endpoint above. See comment there.
                        max_concurrent=1
                    )

                response, tool_calls_log = await task_integration.execute_chat(
                    content=content,
                    skill_name=routed_skill,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    agent_id=agent_id,
                    agent_runner=tracked_agent_run
                )

            finally:
                heartbeat.cancel()  # Stop heartbeat when done

            # Snapshot the decision context now: the agent's dict is shared and a concurrent request can overwrite it.
            _request_dc = getattr(agent, '_last_decision_context', None)
            if _request_dc is not None:
                _request_dc = dict(_request_dc)   # shallow copy — isolates from overwrites

            await state.save_agent_state(agent, tenant_id, agent_id, user_id)

            for cmd in tool_calls_log:
                try:
                    await safe_send({
                        "type": "tool_call",
                        "tool": "shell",
                        "command": cmd,
                        "origin_session_id": _origin_sid,
                        "timestamp": datetime.now().isoformat()
                    })
                except RuntimeError as _tc_rt_err:
                    logger.warning("WebSocket closed while sending tool_call events: %s", _tc_rt_err)
                    break  # WebSocket closed

            try:
                ws_response = {
                    "type": "response",
                    "content": response,
                    "skill": routed_skill,
                    "origin_session_id": _origin_sid,  # Enables frontend session routing
                    "timestamp": datetime.now().isoformat(),
                    "resolved_entities": _resolved_entities,
                    # Context .md files read this turn; the first is used as source_context_file on confirmed knowledge.
                    "context_file": (getattr(agent, '_session_context_files', None) or [None])[0],
                    "context_files_used": getattr(agent, '_session_context_files', None) or [],
                }

                # Add plan_id and actions when a plan is pending; type stays 'response' for UI compatibility.
                _new_pending = getattr(agent, '_pending_plan', None)
                if _new_pending and not _new_pending.get("confirmed"):
                    ws_response["plan_id"] = _new_pending.get("plan_id", "")
                    ws_response["actions"] = ["approve", "reject", "modify"]
                    ws_response["skill"] = "planner"
                    # Use stored display from format_plan_for_display — LLM
                    # may paraphrase the tool result instead of returning it verbatim
                    ws_response["content"] = _new_pending.get("display", response)

                dc = _request_dc   # use local snapshot, not shared agent attribute
                _rl_trace_id = str((dc if isinstance(dc, dict) else {}).get("trace_id") or _request_trace_id)
                ws_response["rl_trajectory_id"] = _rl_trace_id
                ws_response["rl_model_call_id"] = f"{_rl_trace_id}:model:final"
                ws_response["request_trace_id"] = _request_trace_id
                if dc:
                    tool_summary = []
                    for tc in (dc.get("tool_calls") or [])[:20]:
                        tool_summary.append({
                            "tool": tc.get("tool", "unknown"),
                            "input_preview": str(tc.get("input", ""))[:500],
                            "output_preview": str(tc.get("output_preview", "") or tc.get("output", ""))[:500],
                            "duration_ms": tc.get("duration_ms", 0),
                            "has_error": tc.get("has_error", False),
                        })
                    native_reasoning = dc.get("native_reasoning") if isinstance(dc, dict) else None
                    reasoning_ref = getattr(agent, "reasoning_ref", None)
                    if not (
                        isinstance(native_reasoning, dict)
                        and str(native_reasoning.get("preview") or "").strip()
                    ):
                        fallback_summary = str(dc.get("reasoning_summary") or "").strip()
                        if (
                            fallback_summary
                            and isinstance(reasoning_ref, dict)
                            and reasoning_ref.get("response_id")
                        ):
                            native_reasoning = {
                                "provider": reasoning_ref.get("provider") or "azure",
                                "preview": fallback_summary,
                                "preview_source": "observable_summary",
                            }

                    ws_response["reasoning_context"] = {
                        "routing": dc.get("routing", {}),
                        "context_used": dc.get("context_used", {}),
                        "outcome": dc.get("outcome", {}),
                        "tool_calls": tool_summary,
                        "reasoning_summary": dc.get("reasoning_summary", ""),
                        "native_reasoning": native_reasoning,
                        "trace_id": _request_trace_id,           # unique per request — for critique matching
                        "agent_trace_id": dc.get("trace_id", ""), # agent telemetry id — for sources API
                        "critique": dc.get("critique"),  # None when critique disabled
                    }
                    if isinstance(native_reasoning, dict) and native_reasoning.get("preview"):
                        _provider = str(native_reasoning.get("provider") or "provider").strip().lower()
                        _provider_label = {
                            "azure": "Azure",
                            "azure_openai": "Azure",
                            "vertex": "Gemini",
                            "gemini": "Gemini",
                            "anthropic": "Claude",
                            "claude": "Claude",
                        }.get(_provider, _provider.replace("_", " ").title())
                        _preview_source = str(native_reasoning.get("preview_source") or "").strip()
                        await safe_send({
                            "type": "reasoning_event",
                            "event": "native_reasoning",
                            "card_type": "native_reasoning",
                            "label": f"{_provider_label} reasoning trace"
                            if _preview_source == "observable_summary"
                            else f"{_provider_label} reasoning preview",
                            "provider": native_reasoning.get("provider") or _provider,
                            "text": str(native_reasoning.get("preview") or "")[:1200],
                            "origin_session_id": _origin_sid,
                            "timestamp": datetime.now().isoformat(),
                        })
                    if isinstance(reasoning_ref, dict) and reasoning_ref.get("response_id"):
                        await safe_send({
                            "type": "reasoning_event",
                            "event": "response_id_captured",
                            "card_type": "continuity",
                            "label": "Phase 2 continuity active",
                            "provider": reasoning_ref.get("provider") or "azure",
                            "text": "Captured response_id for follow-up reasoning replay.",
                            "detail": str(reasoning_ref.get("response_id") or "")[:80],
                            "origin_session_id": _origin_sid,
                            "timestamp": datetime.now().isoformat(),
                        })
                    # Brief pause so the browser renders reasoning card before the response arrives
                    if isinstance(native_reasoning, dict) and native_reasoning.get("preview"):
                        await asyncio.sleep(0.3)
                    logger.info("Response trace_id=%s agent_trace_id=%s (user=%s)", _request_trace_id, dc.get("trace_id", ""), user_id)

                if agent.pending_action:
                    _tc = getattr(agent, "pending_tool_call", None) or {}
                    _tc_args = _tc.get("args", {}) if isinstance(_tc, dict) else {}
                    _preview = _tc_args.get("content") or _tc_args.get("command") or ""
                    ws_response["pending_approval"] = {
                        "operation": agent.pending_action.get("operation"),
                        "target": agent.pending_action.get("target"),
                        "command": agent.pending_action.get("command"),
                        "content_preview": _preview,
                        "approval_id": agent.pending_action.get("approval_id"),
                    }
                    await dashboard.broadcast({
                        "type": "approval_new",
                        "user_id": user_id,
                        "skill": routed_skill,
                        "operation": agent.pending_action.get("operation"),
                        "target": agent.pending_action.get("target"),
                    })

                # Add document evidence bundle if files were read during this turn
                _evidence = getattr(agent, '_evidence_bundle', None)
                _persist_evidence_bundle(_evidence, "websocket")
                if _evidence and (_evidence.get('documents') or _evidence.get('evidence_items')):
                    ws_response['source_documents'] = _evidence
                    ws_response['evidence_trace_id'] = _evidence.get('trace_id')

                hitl_data = await checkpoint_hitl_if_needed(
                    agent, tenant_id, user_id, routed_skill, source="chat"
                )
                if hitl_data:
                    ws_response["hitl_approval"] = hitl_data

                # RLM apply-phase: turn staged holds into pending approval cards (Command Center).
                # No-op unless the RLM populated agent._rlm_proposed; fail-safe.
                try:
                    _rlm_holds = await checkpoint_rlm_holds_if_needed(
                        agent, tenant_id, user_id, routed_skill, source="chat"
                    )
                    if _rlm_holds:
                        ws_response["rlm_holds_pending"] = _rlm_holds
                except Exception as _rlm_hold_err:
                    logger.warning("RLM hold checkpoint failed (non-fatal): %s", _rlm_hold_err)

                if not light_mode and "<!-- LEARN:" not in (response or ""):
                    _learn_signals = _detect_learning_signals(content)
                    if _learn_signals:
                        _suggestion_entity_keys = [
                            e["node_id"]
                            for e in _resolved_entities
                            if e.get("node_id")
                        ]
                        ws_response["learning_suggestion"] = {
                            "summary": content[:120],
                            "learn_type": _learn_signals["type"],
                            "applies_when": routed_skill,
                            "signals": _learn_signals["signals"],
                            "entity_keys": _suggestion_entity_keys,
                        }

                await dashboard.broadcast({
                    "type": "task_completed",
                    "user_id": user_id,
                    "skill": routed_skill,
                    "has_pending": agent.pending_action is not None,
                })

                # Twin telemetry: task completed (fire-and-forget)
                if twin_emitter:
                    try:
                        _twin_latency = (datetime.now() - _twin_task_start).total_seconds() * 1000
                        twin_emitter.emit_task_completed(
                            user_id=user_id,
                            skill=routed_skill,
                            latency_ms=_twin_latency,
                            has_pending=agent.pending_action is not None,
                        )
                    except Exception as _te_done_err:
                        logger.warning("twin_emitter.emit_task_completed failed (non-fatal): %s", _te_done_err)

                # Twin telemetry: broadcast live event to /ws/twin clients
                if twin_broadcaster:
                    try:
                        await twin_broadcaster.broadcast({
                            "type": "task_completed",
                            "user_id": user_id,
                            "skill": routed_skill,
                            "latency_ms": round((datetime.now() - _twin_task_start).total_seconds() * 1000),
                            "has_pending": agent.pending_action is not None,
                        })
                    except Exception as _tb_err:
                        logger.warning("twin_broadcaster.broadcast failed (non-fatal): %s", _tb_err)

                # sync: critique before send, embedded in ws_response; async: answer first, then critique_result. Use request-local state.
                _eff_mode = _effective_mode
                logger.info("Critique mode USED: %s (user=%s, set_at_request=%s)", _eff_mode, user_id, _effective_mode)
                _dc = _request_dc
                _tool_results = (_dc.get("tool_calls") or []) if _dc else []
                _trace_id_for_critique = _request_trace_id   # always unique per request

                if _eff_mode == "sync" and _tool_results:
                    _critique = await _run_critique_sync(
                        agent, content, response, _tool_results,
                    )
                    if _critique:
                        if ws_response.get("reasoning_context") is not None:
                            ws_response["reasoning_context"]["critique"] = _critique
                        # Auto-apply revised answer — user waited for this, no button needed
                        if _critique.get("revised_response"):
                            ws_response["content"] = _critique["revised_response"]

                # Signal UI that async grounding is in-flight — UI shows spinner
                # until the "critique_result" WS message arrives.
                _consistency = _ui_consistency if _ui_consistency is not None else _SERVER_CONSISTENCY

                if _eff_mode == "async" and _tool_results:
                    if ws_response.get("reasoning_context") is not None:
                        ws_response["reasoning_context"]["critique_pending"] = True
                        if _consistency:
                            ws_response["reasoning_context"]["consistency_pending"] = True

                _capture_rl_turn_best_effort(
                    agent=agent,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    session_id=session_id,
                    trace_id=_rl_trace_id,
                    content=content,
                    response=str(ws_response.get("content") or ""),
                    skill_name=str(ws_response.get("skill") or routed_skill),
                    decision_context=dc if isinstance(dc, dict) else None,
                    status="partial" if hitl_data else "success",
                    metadata={"transport": "websocket", "request_trace_id": _request_trace_id},
                )
                try:
                    _critique_obj = (ws_response.get("reasoning_context") or {}).get("critique")
                    _revised_response = (
                        _critique_obj.get("revised_response")
                        if isinstance(_critique_obj, dict)
                        else None
                    )
                    if _revised_response and str(_revised_response) != str(response):
                        emit_revision_preference(
                            data_root=DATA_ROOT_PATH,
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            trajectory_id=_rl_trace_id,
                            original_response=str(response),
                            revised_response=str(_revised_response),
                            source="sync_critique",
                        )
                except Exception as _rl_pref_err:
                    logger.warning("RL critique preference capture failed (non-fatal): %s", _rl_pref_err)

                await safe_send(ws_response)

                if _eff_mode == "async" and _tool_results:
                    # Answer already sent — critique runs in background
                    asyncio.create_task(_run_critique_and_push(
                        agent, content, response, _tool_results,
                        _trace_id_for_critique, safe_send,
                        consistency_check=_consistency,
                    ))

            except RuntimeError as _rt_err:
                logger.warning("WebSocket closed before response could be sent (response lost): %s", _rt_err)

        except asyncio.CancelledError:
            _capture_rl_turn_best_effort(
                agent=agent,
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=request_session_id or getattr(agent, "session_id", "") or f"{tenant_id}:{user_id}",
                trace_id=_request_trace_id,
                content=content,
                response="cancelled",
                skill_name=str(locals().get("routed_skill") or skill_name or ""),
                decision_context=getattr(agent, "_last_decision_context", None)
                if isinstance(getattr(agent, "_last_decision_context", None), dict)
                else None,
                status="cancelled",
                metadata={"transport": "websocket", "request_trace_id": _request_trace_id},
            )
            raise
        except Exception as e:
            logger.error("Unhandled error in WS message handler: %s", e, exc_info=True)
            # Twin telemetry: task error (fire-and-forget)
            if twin_emitter:
                try:
                    twin_emitter.emit_task_error(
                        user_id=user_id,
                        skill=routed_skill if 'routed_skill' in locals() else '',
                        error=str(e),
                    )
                except Exception as _te_err_err:
                    logger.warning("twin_emitter.emit_task_error failed (non-fatal): %s", _te_err_err)
            try:
                await safe_send({
                    "type": "error",
                    "message": "An internal error occurred",
                    "origin_session_id": locals().get("_origin_sid", ""),
                    "timestamp": datetime.now().isoformat()
                })
            except (RuntimeError, Exception) as _ws_close_err:
                logger.warning("WebSocket already closed when sending error to client: %s", _ws_close_err)
            _capture_rl_turn_best_effort(
                agent=agent,
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=request_session_id or getattr(agent, "session_id", "") or f"{tenant_id}:{user_id}",
                trace_id=_request_trace_id,
                content=content,
                response=str(e),
                skill_name=str(locals().get("routed_skill") or skill_name or ""),
                decision_context=getattr(agent, "_last_decision_context", None)
                if isinstance(getattr(agent, "_last_decision_context", None), dict)
                else None,
                status="failed",
                metadata={"transport": "websocket", "request_trace_id": _request_trace_id, "error": "An internal error occurred"},
            )

    try:
        while True:
            # Read the next incoming message — 25s timeout to allow server-side
            # keep-alive pings that prevent LB/proxy idle-connection teardown.
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=25)
            except asyncio.TimeoutError:
                # No client message in 25s — send ping to keep LB alive
                await safe_send({"type": "ping"})
                continue

            # Respond to client-side ping immediately
            if data.get("type") == "ping":
                await safe_send({"type": "pong"})
                continue

            # One-time WS registration on the first message for this connection.
            _tid = data.get("tenant_id", "company")
            if not _chat_user_key:
                # Register under the token-bound user id (not the client-supplied email) so cross-channel pushes reach this socket.
                _uid = data.get("user_id", "demo")
                _reg_ids = [_uid]
                if token:
                    try:
                        from auth.identity import (
                            bind_identity_to_tenant,
                            resolve_access_token_identity_async,
                        )
                        # Async resolver: the browser token has no email claim,
                        # so the email key below comes from the user store.
                        _resolved_reg, _ = await resolve_access_token_identity_async(token)
                        _bound = bind_identity_to_tenant(_resolved_reg, _tid)
                        if getattr(_bound, "user_id", None):
                            _uid = _bound.user_id
                            _reg_ids = [_uid]
                        # Also register under the email: HITL approvals are keyed by email for SSO identities.
                        _email = getattr(_bound, "email", None)
                        if _email and _email != _uid:
                            _reg_ids.append(_email)
                    except Exception as _bind_err:
                        logger.debug("WS register identity bind failed; using client user_id: %s", _bind_err)
                _chat_user_key = (_tid, _uid)
                _chat_reg_keys = [(_tid, _rid) for _rid in dict.fromkeys(_reg_ids) if _rid]
                for _rk in _chat_reg_keys:
                    await chat_registry.register(_rk[0], _rk[1], websocket)

            # Cancel is cooperative: set the flag the worker thread polls; task.cancel() would clear it before the thread observes it.
            if data.get("type") == "cancel":
                logger.info("WS CANCEL received | active_run_ids=%s active_tasks=%d",
                            list(_active_run_ids), len(_active_tasks))
                for _rid in list(_active_run_ids):
                    run_cancellation.request_cancel(_rid)
                await safe_send({"type": "cancelled", "content": "⛔ Stopped."})
                continue

            if not data.get("content", ""):
                continue

            # Run as a background task so the loop keeps receiving; per-session lanes serialize within a session.
            _run_id = uuid.uuid4().hex
            run_cancellation.begin(_run_id)
            _active_run_ids.add(_run_id)
            logger.debug("WS DISPATCH | run_id=%s | content=%.60s", _run_id, str(data.get("content", "")))
            task = asyncio.create_task(handle_one_message(data, _run_id))
            _active_tasks.add(task)

            def _on_task_done(t, _rid=_run_id):
                _active_tasks.discard(t)
                _active_run_ids.discard(_rid)
                run_cancellation.end(_rid)
            task.add_done_callback(_on_task_done)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client")
    except RuntimeError as e:
        if "not connected" in str(e).lower():
            logger.info("WebSocket connection lost")
        else:
            raise
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        # Client gone: flip the cooperative cancel flag; do not task.cancel() (it clears the flag before the thread sees it).
        for _rid in list(_active_run_ids):
            run_cancellation.request_cancel(_rid)
        # Unregister from chat registry (all keys this socket registered under)
        for _rk in (_chat_reg_keys or ([_chat_user_key] if _chat_user_key else [])):
            await chat_registry.unregister(*_rk)
