"""
IAF Agent Studio — Conversations Router

Provides sidebar-friendly endpoints for listing, loading, creating,
deleting, and renaming conversation sessions.

Endpoints:
    GET    /api/conversations               — list sessions (sidebar)
    POST   /api/conversations/new           — save current + reset session
    POST   /api/conversations/{id}/load     — load past conversation (fork semantics)
    DELETE /api/conversations/{id}          — soft-delete
    PATCH  /api/conversations/{id}          — rename title
    POST   /api/conversations/backfill      — index existing JSONL files
"""

import json
import logging
import traceback
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from shared.config import AUTH_ENABLED
from shared.state import state
from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter

logger = logging.getLogger(__name__)

router = APIRouter()
_evidence_adapter = EvidenceCollectorAdapter()


def _effective_user_id(request: Request, user_id: str) -> str:
    """Resolve the canonical user identity for conversation storage/listing.

    chat.py stores sessions under ``principal.email or principal.user_id``
    (email preferred, UUID fallback). The sidebar endpoints must resolve the
    same identity or they silently miss the user's sessions.

    In dev mode (``AUTH_ENABLED=false``), honour the browser-supplied
    ``user_id`` so the sidebar works without authentication.
    """
    if AUTH_ENABLED:
        authed = (
            getattr(request.state, "email", None)
            or getattr(request.state, "user_id", None)
        )
        return authed or user_id
    return user_id or getattr(request.state, "user_id", None) or "demo"


def _attach_evidence_to_turn(turn: dict, tenant_id: str) -> dict:
    """Attach persisted evidence for UI replay without changing per-turn semantics."""
    enriched = dict(turn)
    trace_id = (
        enriched.get("evidence_trace_id")
        or enriched.get("trace_id")
        or (enriched.get("source_documents") or {}).get("trace_id")
        or ""
    )
    if trace_id:
        enriched["evidence_trace_id"] = trace_id
    if enriched.get("source_documents"):
        return enriched
    if not trace_id:
        return enriched
    try:
        bundle = _evidence_adapter.fetch_bundle(str(trace_id), tenant_id=tenant_id)
    except Exception as exc:
        logger.debug("Evidence rehydrate failed for trace %s: %s", trace_id, exc)
        return enriched
    if bundle and (bundle.get("documents") or bundle.get("evidence_items")):
        enriched["source_documents"] = bundle
    return enriched


class RenameRequest(BaseModel):
    """Request body for renaming a conversation."""
    title: str


@router.get("/api/conversations")
async def list_conversations(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
    limit: int = 20,
    offset: int = 0,
):
    """
    Return recent conversation sessions for the sidebar.

    Sessions are ordered by last_active_at DESC (newest first).
    Soft-deleted sessions are excluded.
    """
    try:
        user_role = getattr(request.state, "role", None) or "user"
        user_id = _effective_user_id(request, user_id)
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        sessions = agent.memory.conversation_manager.list_sessions(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        # Exclude Ask Twin help sessions (session_id prefixed "asktwin:") so the
        # in-app assistant does not clutter the user's main Chats history.
        sessions = [
            s for s in sessions
            if not str(s.get("session_id", "")).startswith("asktwin:")
        ]
        for s in sessions:
            if isinstance(s.get("skills_used"), str):
                try:
                    s["skills_used"] = json.loads(s["skills_used"])
                except (json.JSONDecodeError, TypeError):
                    s["skills_used"] = []

        return {
            "sessions": sessions,
            "total": len(sessions),
            "current_session_id": agent.session_id,
        }
    except Exception as e:
        logger.error("list_conversations error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.post("/api/conversations/new")
async def new_conversation(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Start a new conversation session.

    Creates a fresh session agent via the per-session pool.
    Does NOT mutate the in-flight agent — safe to call while a
    previous conversation's agent.run() is still executing.
    """
    try:
        user_role = getattr(request.state, "role", None) or "user"
        user_id = _effective_user_id(request, user_id)
        current_agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        old_session_id = current_agent.session_id
        old_turns = len(current_agent.conversation_history)

        # Generate a new session_id and spawn a fresh agent via the pool
        user_prefix = (user_id or "anon")[:20]
        uuid_suffix = uuid.uuid4().hex[:6]
        new_session_id = f"{user_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid_suffix}"
        new_agent = await state.get_or_create_session_async(
            tenant_id, agent_id, user_id, new_session_id, user_role=user_role
        )

        # Promote this new session as the 'active' default
        state.set_active_session(tenant_id, agent_id, user_id, new_session_id, user_role=user_role)

        try:
            if hasattr(state, 'save_agent_state'):
                await state.save_agent_state(new_agent, tenant_id, agent_id, user_id)
        except Exception as save_err:
            logger.warning("Session save after new failed (non-fatal): %s", save_err)

        return {
            "old_session_id": old_session_id,
            "old_turns": old_turns,
            "new_session_id": new_session_id,
        }
    except Exception as e:
        logger.error("new_conversation error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.post("/api/conversations/{session_id}/load")
async def load_conversation(
    session_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Resume a past conversation in-place.

    If the session agent is still alive in the pool (hot path), we
    simply promote it as active and return its in-memory turns.
    This avoids JSONL read races (background log_episode thread may
    not have flushed yet) and eliminates fork proliferation.

    If the session was evicted from the pool (cold path — LRU eviction
    or server restart), we recreate the agent with the SAME session_id
    and import history from JSONL. No fork, no parent_session_id —
    the user continues in the original conversation.

    Returns the turns + session metadata so the frontend can rebuild
    the chat panel.
    """
    try:
        user_role = getattr(request.state, "role", None) or "user"
        user_id = _effective_user_id(request, user_id)
        # Use any existing agent to access conversation_manager (shared memory root)
        ref_agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)

        # 1. Verify the session exists in our index
        session_meta = ref_agent.memory.conversation_manager.get_session(session_id)
        if not session_meta:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        if session_meta.get("status") == "deleted":
            raise HTTPException(status_code=410, detail="Session has been deleted")

        # Pool hit = hot (existing agent); miss = cold clone with the SAME session_id (not a fork).
        session_agent = await state.get_or_create_session_async(
            tenant_id, agent_id, user_id, session_id, user_role=user_role
        )

        # 3. Determine if this is a hot resume (in-memory) or cold restore (JSONL)
        in_memory_history = getattr(session_agent, 'conversation_history', [])
        # After compaction the in-memory history is pruned: serve the full JSONL for display but keep the compacted history for LLM context.
        compaction_count = getattr(session_agent, 'compaction_count', 0)
        use_hot_path = bool(in_memory_history) and compaction_count == 0
        source = "memory" if use_hot_path else "disk"

        if use_hot_path:
            # Hot path: agent alive and not compacted; prefer response_raw (full HTML/UI) over the summarized response.
            turns = [
                _attach_evidence_to_turn({
                    "user_input": h.get("user_input", ""),
                    "response": h.get("response_raw") or h.get("response", ""),
                    "skill": h.get("skill", ""),
                    "evidence_trace_id": h.get("evidence_trace_id", ""),
                    "source_documents": h.get("source_documents"),
                }, tenant_id)
                for h in in_memory_history
            ]
            # Append an in-flight query as a partial turn so the UI shows the question while waiting.
            inflight = getattr(session_agent, '_inflight_query', None)
            if inflight:
                turns.append({
                    "user_input": inflight,
                    "response": "",
                    "skill": "",
                    "inflight": True,
                })
        else:
            # Cold path: read the full JSONL for display; never overwrite the compacted in-memory history.
            jsonl_turns = ref_agent.memory.conversation_manager.load_session_turns(
                session_id=session_id,
                history_root=ref_agent.memory.history_path,
            )

            # Import history for fresh/evicted sessions only (compaction_count == 0); a compacted session already holds the right window.
            if compaction_count == 0:
                history = []
                for turn in jsonl_turns:
                    history.append({
                        "timestamp": turn.get("timestamp", ""),
                        "user_id": turn.get("user_id", user_id),
                        "skill": turn.get("skill", ""),
                        "user_input": turn.get("user_input", ""),
                        "tool_calls": turn.get("tool_calls", []),
                        "response": turn.get("response", ""),
                        "evidence_trace_id": turn.get("evidence_trace_id") or turn.get("trace_id", ""),
                    })
                session_agent.conversation_history = history
                session_agent.current_skill = session_meta.get("current_skill")

            turns = [
                _attach_evidence_to_turn({
                    "user_input": t.get("user_input", ""),
                    "response": t.get("response", ""),
                    "skill": t.get("skill", ""),
                    "evidence_trace_id": t.get("evidence_trace_id") or t.get("trace_id", ""),
                }, tenant_id)
                for t in jsonl_turns
            ]

        # 4. Promote as active session
        state.set_active_session(tenant_id, agent_id, user_id, session_id, user_role=user_role)

        logger.info(
            "Resumed session %s (%s, %d turns)",
            session_id[:30], source, len(turns),
        )

        return {
            "loaded_session_id": session_id,
            "new_session_id": session_id,  # Same ID — no fork
            "turns_loaded": len(turns),
            "source": source,  # "memory" or "disk" — helpful for debugging
            "title": session_meta.get("title", ""),
            "turns": turns,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("load_conversation error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.delete("/api/conversations/{session_id}")
async def delete_conversation(
    session_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Soft-delete a conversation session (marks status='deleted').

    Does NOT delete the JSONL file — that's an audit trail.
    Cannot delete the currently active session.
    """
    try:
        user_role = getattr(request.state, "role", None) or "user"
        user_id = _effective_user_id(request, user_id)
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)

        # Prevent deleting the active session
        if session_id == agent.session_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the currently active session"
            )

        deleted = agent.memory.conversation_manager.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return {"deleted": True, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_conversation error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.patch("/api/conversations/{session_id}")
async def rename_conversation(
    session_id: str,
    body: RenameRequest,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Rename a conversation's title."""
    try:
        user_role = getattr(request.state, "role", None) or "user"
        user_id = _effective_user_id(request, user_id)
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        updated = agent.memory.conversation_manager.rename_session(
            session_id=session_id,
            title=body.title,
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return {"renamed": True, "session_id": session_id, "title": body.title.strip()[:80]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rename_conversation error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.post("/api/conversations/backfill")
async def backfill_conversations(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Scan existing JSONL history files and populate the conversation index.

    Useful on first deploy or when adding the sidebar to an existing setup.
    Idempotent — skips sessions that are already indexed.
    """
    try:
        user_role = getattr(request.state, "role", None) or "user"
        user_id = _effective_user_id(request, user_id)
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        count = agent.memory.conversation_manager.backfill_from_disk(
            history_root=agent.memory.history_path,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
        )
        return {"backfilled": count}
    except Exception as e:
        logger.error("backfill_conversations error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred")
