"""
IAF Agent Studio — Observers Router.

Thin HTTP layer for the Observers subsystem. Does auth + shape validation only,
then delegates to ObserverService. All business logic lives in observers/.

Routes (all prefixed /api/observers/):
  GET  /api/observers                  — list configured observers
  GET  /api/observers/{name}           — one observer spec
  GET  /api/observers/{name}/status    — liveness (running? last activity)
  POST /api/observers/act              — governed skill-action request
                                         (X-API-Key auth — the ONLY write path)

Service auth: POST /act validates X-API-Key against OBSERVERS_API_KEY, mirroring
routers/queue.py's webhook ingest. Its path is added to _PUBLIC_PREFIXES so the
JWT middleware defers to this key check.
"""

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from security.dependencies import authorise_approver, bind_request_identity, bind_websocket_identity, enforce_entitlement, principal_from_request
from shared.config import AUTH_ENABLED, OBSERVERS_ENABLED, OBSERVERS_API_KEY
try:
    from shared.config import AUTH_ENABLED
except Exception:  # pragma: no cover
    AUTH_ENABLED = False
from observers.models import ActRequest, ActResponse, ObserverSpec
from observers.service import get_observer_service
from observers.store import get_observer_store

try:  # admin gate for authoring/lifecycle writes (no-op when AUTH disabled)
    from auth.middleware import require_admin
except Exception:  # pragma: no cover
    def require_admin(request: Request):  # type: ignore
        return None

logger = logging.getLogger(__name__)

router = APIRouter()

# Observer names become YAML filenames: require a safe slug (no separators or leading dot) to prevent traversal.
_OBSERVER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _validate_observer_name(name: str) -> None:
    if not _OBSERVER_NAME_RE.match(name or ""):
        raise HTTPException(
            status_code=422,
            detail=("Invalid observer name: use letters, digits, '.', '_', '-'; "
                    "must start with a letter/digit and be ≤64 chars."),
        )


class ResolveBody(BaseModel):
    decision: str            # "approved" | "rejected"
    decided_by: str = "observer-admin"
    note: str = ""


class ChatBody(BaseModel):
    message: str
    mode: str = "copilot"
    skill_name: str = ""
    from_name: str = "operator"


def _guard_enabled() -> None:
    if not OBSERVERS_ENABLED:
        raise HTTPException(status_code=404, detail="Observers subsystem disabled")


def _spec_public(spec) -> dict:
    """Serialize a spec for the API (pydantic v1/v2 compatible)."""
    return spec.model_dump(mode="json") if hasattr(spec, "model_dump") else spec.dict()


def _caller_tenants(request: Request) -> Optional[set]:
    """Tenants the caller may access, or None when AUTH is disabled (dev/test)."""
    if not AUTH_ENABLED:
        return None
    principal = principal_from_request(request, None)
    return {t for t in (principal.allowed_tenants or ()) if t}


def _spec_or_404(request: Request, name: str):
    """Guard-enabled, load an observer spec, and scope it to the caller's tenant.

    Observer routes key off {name}. The app-wide require_request_tenant guard only
    checks a tenant NAMED in the request, so it does not cover these routes — without
    this a caller could read (or drive) another tenant's observer by guessing its
    name. Returns the spec only when it belongs to a tenant the caller may access;
    otherwise 404 — identical to a genuinely missing observer, so cross-tenant
    existence is not leaked. No-op scope when AUTH is disabled (dev).
    """
    _guard_enabled()
    spec = get_observer_store().get_spec(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Observer '{name}' not found")
    allowed = _caller_tenants(request)
    if allowed is not None and (getattr(spec, "tenant_id", "") or "company") not in allowed:
        raise HTTPException(status_code=404, detail=f"Observer '{name}' not found")
    return spec


@router.get("/api/observers")
async def list_observers(request: Request):
    """List configured observer specs the caller's tenant may see."""
    _guard_enabled()
    specs = get_observer_store().list_specs()
    allowed = _caller_tenants(request)
    if allowed is not None:
        specs = [s for s in specs if (getattr(s, "tenant_id", "") or "company") in allowed]
    return {"observers": [_spec_public(s) for s in specs]}


@router.get("/api/observers/{name}")
async def get_observer(name: str, request: Request):
    """Return a single observer spec (scoped to the caller's tenant)."""
    spec = _spec_or_404(request, name)
    return _spec_public(spec)


@router.get("/api/observers/{name}/status")
async def observer_status(name: str, request: Request):
    """Liveness for an observer (best-effort; reads the runtime)."""
    spec = _spec_or_404(request, name)
    # Runtime import is lazy — status works even if Headlong isn't installed.
    try:
        from observers.runtime import create_observer_runtime
        status = create_observer_runtime().status(spec)
    except Exception as exc:  # pragma: no cover - environment dependent
        status = {"running": False, "detail": f"runtime unavailable: {exc}"}
    return {"observer": name, **status}


@router.post("/api/observers/act", response_model=ActResponse)
async def observer_act(req: ActRequest, request: Request) -> ActResponse:
    """The only write path: an observer requests a governed skill action.

    Authenticated with X-API-Key (service auth, like queue ingest). The request
    is gated by the observer's trust tier + allowlist and routed through the
    existing HITL approval machinery inside ObserverService.
    """
    _guard_enabled()

    # Public-prefix route: require the service key and fail closed when it is unset.
    if not OBSERVERS_API_KEY:
        logger.error("OBSERVERS_API_KEY unset — refusing /api/observers/act (fail closed)")
        raise HTTPException(status_code=503, detail="Observer gateway API key is not configured")
    if request.headers.get("X-API-Key", "") != OBSERVERS_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return await get_observer_service().act(req)


@router.post("/api/observers/approvals/{approval_id}/resolve", response_model=ActResponse)
async def resolve_observer_approval(approval_id: str, body: ResolveBody, request: Request) -> ActResponse:
    """Approve/reject an observer-created HITL approval. On approve, the deferred
    skill runs. The decider is the authenticated caller and must hold the `approve`
    right in policies.yaml (the middleware only proves a valid token, not admin)."""
    _guard_enabled()
    from shared.state import approval_store
    approval = await approval_store.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="approval not found")
    # Only observer-created approvals belong here; reject others before authorising/claiming.
    if getattr(approval, "source", None) != "observer":
        raise HTTPException(status_code=404, detail="observer approval not found")
    approver = authorise_approver(request, approval)
    if not AUTH_ENABLED:
        approver = body.decided_by or approver
    return await get_observer_service().resolve(
        approval_id, body.decision, approver, body.note
    )


@router.post("/api/observers", status_code=201, dependencies=[Depends(require_admin)])
async def create_observer(spec: ObserverSpec, request: Request):
    """Create a new observer spec (409 if it already exists)."""
    _guard_enabled()
    _validate_observer_name(spec.name)
    # Bind the creating admin to the spec's tenant (403 if not entitled) so a
    # tenant-scoped admin cannot author an observer into another tenant.
    bind_request_identity(request, requested_tenant=getattr(spec, "tenant_id", None) or None)
    store = get_observer_store()
    if store.get_spec(spec.name) is not None:
        raise HTTPException(status_code=409, detail=f"Observer '{spec.name}' already exists")
    store.save_spec(spec)
    logger.info("Observer created: %s", spec.name)
    return _spec_public(spec)


@router.put("/api/observers/{name}", dependencies=[Depends(require_admin)])
async def update_observer(name: str, spec: ObserverSpec, request: Request):
    """Update an existing observer spec (404 if missing). Name in the path wins."""
    _validate_observer_name(name)
    _spec_or_404(request, name)  # existing observer must be in the caller's tenant
    # The replacement spec must also target a tenant the caller may reach.
    bind_request_identity(request, requested_tenant=getattr(spec, "tenant_id", None) or None)
    spec.name = name  # path is authoritative; prevents rename-collisions
    get_observer_store().save_spec(spec)
    logger.info("Observer updated: %s", name)
    return _spec_public(spec)


@router.delete("/api/observers/{name}", dependencies=[Depends(require_admin)])
async def delete_observer(name: str, request: Request):
    """Delete an observer spec (best-effort stop first)."""
    spec = _spec_or_404(request, name)
    store = get_observer_store()
    try:  # stop the live mind before deleting the spec (best-effort)
        from observers.runtime import create_observer_runtime
        create_observer_runtime().stop(spec)
    except Exception as exc:
        logger.warning("stop before delete failed (non-fatal): %s", exc)
    store.delete_spec(name)
    return {"deleted": name}


@router.post("/api/observers/{name}/start", dependencies=[Depends(require_admin)])
async def start_observer(name: str, request: Request):
    """Provision + start the observer's Headlong mind (and sidecar)."""
    spec = _spec_or_404(request, name)
    from observers.runtime import create_observer_runtime
    result = create_observer_runtime().start(spec)
    return {"observer": name, **result}


@router.post("/api/observers/{name}/stop", dependencies=[Depends(require_admin)])
async def stop_observer(name: str, request: Request):
    """Stop the observer's mind (and sidecar). Idempotent."""
    spec = _spec_or_404(request, name)
    from observers.runtime import create_observer_runtime
    result = create_observer_runtime().stop(spec)
    return {"observer": name, **result}


def _read_trajectory_tail(spec, limit: int = 60) -> list:
    """Return the last `limit` parsed steps of the observer's newest trajectory."""
    import json as _json
    from collections import deque
    from observers.runtime import _latest_trajectory
    traj = _latest_trajectory(spec)
    if not traj:
        return []
    steps = []
    try:
        with traj.open("r") as fh:
            for line in deque(fh, maxlen=limit):
                line = line.strip()
                if not line:
                    continue
                try:
                    steps.append(_json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return steps


async def _observer_detections(name: str, tenant: str = "company") -> list:
    """Assemble an observer's 'detections' from its source=observer HITL approvals
    (fresh, carrying Quick-Win-A outcome + trace). No new store — a VIEW."""
    from shared.state import approval_store
    fresh = {}
    try:
        for a in await approval_store.get_pending(tenant):
            fresh[getattr(a, "id", None)] = a
    except Exception:
        pass
    try:
        for h in await approval_store.get_history(tenant):
            hid = h.get("id") if isinstance(h, dict) else getattr(h, "id", None)
            if hid and hid not in fresh:
                live = await approval_store.get_approval(hid)
                if live:
                    fresh[hid] = live
    except Exception:
        pass

    dets = []
    for aid, a in fresh.items():
        if getattr(a, "source", None) != "observer":
            continue
        ctx = getattr(a, "context", None) or {}
        if ctx.get("observer") not in (name, None):
            continue
        dets.append({
            "id": aid,
            "rule": ctx.get("trigger") or getattr(a, "rule_matched", None),
            "skill": getattr(a, "skill", None),
            "task": ctx.get("task"),
            "evidence": ctx.get("evidence") or [],
            "reason": getattr(a, "reason", None),
            "urgency": getattr(a, "urgency", None),
            "status": getattr(a, "status", None),                 # pending|approved|rejected
            "execution_status": getattr(a, "execution_status", "") or "",
            "result_summary": getattr(a, "result_summary", None),
            "trace_id": getattr(a, "trace_id", None),
            "decided_by": getattr(a, "decided_by", None),
            "created_at": getattr(a, "created_at", None),
            "completed_at": getattr(a, "completed_at", None),
        })
    dets.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return dets


@router.get("/api/observers/{name}/trajectory")
async def observer_trajectory(name: str, request: Request, limit: int = 60):
    """Recent steps of the observer's live trajectory (thoughts/bash/observations/triggers)."""
    spec = _spec_or_404(request, name)
    return {"observer": name, "steps": _read_trajectory_tail(spec, min(limit, 300))}


@router.get("/api/observers/{name}/detections")
async def observer_detections(name: str, request: Request):
    """The observer's detections/escalations (approvals it created, + outcomes)."""
    spec = _spec_or_404(request, name)
    dets = await _observer_detections(name, spec.tenant_id)
    return {"observer": name, "detections": dets, "total": len(dets)}


@router.get("/api/observers/{name}/metrics")
async def observer_metrics(name: str, request: Request):
    """Detection/approval metrics for the KPI tiles."""
    spec = _spec_or_404(request, name)
    dets = await _observer_detections(name, spec.tenant_id)
    pending = sum(1 for d in dets if d["status"] == "pending")
    approved = sum(1 for d in dets if d["status"] == "approved")
    rejected = sum(1 for d in dets if d["status"] == "rejected")
    outcomes = sum(1 for d in dets if d["execution_status"] in ("done", "failed", "rejected"))
    decided = approved + rejected
    return {
        "observer": name,
        "detections": len(dets),
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "outcomes": outcomes,
        "approve_rate": round(100 * approved / decided) if decided else None,
    }


@router.websocket("/ws/observers/{name}")
async def ws_observer(websocket: WebSocket, name: str, token: str = ""):
    """Push the observer's live trajectory steps as they are appended."""
    if not OBSERVERS_ENABLED:
        await websocket.close(code=4401)
        return
    # Load the spec first so authorization can bind the caller to its tenant.
    spec = get_observer_store().get_spec(name)
    if spec is None:
        await websocket.close(code=4404)
        return
    # Bind the caller to the observer's own tenant and require tenant-scoped read access (as workstream_ws does).
    try:
        principal, _tenant_id, _user_id = await bind_websocket_identity(
            websocket,
            requested_tenant=spec.tenant_id,
            token=token or None,
        )
        enforce_entitlement(principal, "read", "observer", name)
    except HTTPException as exc:
        await websocket.close(code=4403 if exc.status_code == 403 else 4401)
        return
    await websocket.accept()
    from observers.runtime import _latest_trajectory

    try:
        await websocket.send_json({"type": "snapshot", "steps": _read_trajectory_tail(spec, 40)})
    except Exception:
        return

    traj = _latest_trajectory(spec)
    offset = 0
    if traj:
        try:
            with traj.open("r") as fh:
                fh.seek(0, 2)  # start tailing from the current end
                offset = fh.tell()
        except Exception:
            offset = 0

    idle = 0
    try:
        while True:
            await asyncio.sleep(1.0)
            t = _latest_trajectory(spec)
            if t != traj:
                traj, offset = t, 0
            if not traj:
                continue
            new = []
            try:
                with traj.open("r") as fh:
                    fh.seek(offset)
                    lines = fh.readlines()
                    offset = fh.tell()
            except Exception:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    new.append(json.loads(line))
                except Exception:
                    continue
            if new:
                idle = 0
                await websocket.send_json({"type": "steps", "steps": new})
            else:
                idle += 1
                if idle >= 25:  # ~25s heartbeat
                    idle = 0
                    await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover
        logger.debug("observer WS closed for '%s': %s", name, exc)
        return


async def _run_scoped_chat(spec, session_id: str, prompt: str, request: Request,
                           skill_name: str = "") -> dict:
    """Reuse the platform chat path (like workstream item-chat) under a scoped
    session. Returns the chat_endpoint result dict."""
    from shared.models import ChatMessage
    from routers.chat import chat_endpoint
    msg = ChatMessage(
        content=prompt,
        tenant_id=spec.tenant_id,
        agent_id=spec.agent_id,
        user_id=session_id,           # scoped session isolation (as workstreams do)
        skill_name=skill_name or None,
        human_approval=True,
        light_mode=True,
    )
    try:
        msg.knowledge_mode = "hybrid"  # optional field; ignore if not present
    except Exception:
        pass
    return await chat_endpoint(msg, request)


def _build_detection_chat_prompt(name: str, det: dict, message: str) -> str:
    return (
        f"You are assisting a human reviewing an observer detection.\n"
        f"Observer: {name}\n"
        f"Detection id: {det.get('id')}  · skill: {det.get('skill')}  · status: {det.get('status')}\n"
        f"Rule/trigger: {det.get('rule')}\n"
        f"Task: {det.get('task')}\n"
        f"Evidence: {det.get('evidence')}\n"
        f"Outcome: {det.get('execution_status')} — {(det.get('result_summary') or '')[:600]}\n"
        f"Trace: {det.get('trace_id')}\n\n"
        f"Answer the reviewer's question about THIS detection concisely.\n"
        f"Reviewer: {message}"
    )


@router.post("/api/observers/{name}/detections/{detection_id}/chat")
async def detection_chat(name: str, detection_id: str, body: ChatBody, request: Request):
    """Per-detection chat, scoped to one escalation's context (reuses chat_endpoint)."""
    spec = _spec_or_404(request, name)
    dets = await _observer_detections(name, spec.tenant_id)
    det = next((d for d in dets if d["id"] == detection_id), None)
    if det is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    prompt = _build_detection_chat_prompt(name, det, body.message)
    result = await _run_scoped_chat(spec, f"observer:{name}:detection:{detection_id}",
                                    prompt, request, body.skill_name)
    return {"observer": name, "detection_id": detection_id,
            "response": result.get("response"), "skill": result.get("skill")}


def _observer_mind_chat(spec, message: str, from_name: str = "operator", wait: int = 22) -> Optional[str]:
    """Talk to the LIVE Headlong mind: inject a chat message and read the
    responder's reply from the trajectory. Best-effort (needs the mind running)."""
    import re as _re
    import subprocess
    from observers.runtime import _identity_dir, _headlong_env, _read_console_state
    idir = _identity_dir(spec)
    from_name = _re.sub(r"[^A-Za-z0-9._-]", "", from_name) or "operator"
    # capture ids already present so we only accept a NEW reply
    before = {s.get("step_id") for s in _read_trajectory_tail(spec, 60)
              if isinstance(s, dict)}
    try:
        subprocess.run(
            ["bash", "-lc", f'cd "{idir}" && source ./activate >/dev/null 2>&1 && '
                            f'chat send --from {from_name} --to {spec.name}'],
            input=message, env=_headlong_env(), capture_output=True, text=True, timeout=25,
        )
    except Exception as exc:
        logger.warning("chat send failed for '%s': %s", spec.name, exc)
        return None
    deadline = time.time() + wait
    while time.time() < deadline:
        for s in reversed(_read_trajectory_tail(spec, 40)):
            if (isinstance(s, dict) and s.get("type") == "message"
                    and s.get("from") == spec.name and s.get("source") == "chat"
                    and s.get("step_id") not in before):
                return s.get("content")
        time.sleep(1.5)
    return None


@router.post("/api/observers/{name}/chat")
async def observer_chat(name: str, body: ChatBody, request: Request):
    """Observer-level chat: 'copilot' (read-only over activity/metrics) or 'mind'
    (message the live Headlong agent and return its responder's reply)."""
    spec = _spec_or_404(request, name)

    # mind mode — only if the mind is running; otherwise fall back to copilot.
    if body.mode == "mind":
        from observers.runtime import create_observer_runtime
        st = create_observer_runtime().status(spec)
        if st.get("running"):
            reply = await asyncio.to_thread(_observer_mind_chat, spec, body.message, body.from_name)
            if reply:
                return {"observer": name, "mode": "mind", "response": reply}
            return {"observer": name, "mode": "mind",
                    "response": "(the mind did not reply in time — it may be busy)"}
        # not running → fall through to copilot with a note

    # copilot mode — read-only summary over recent activity + metrics.
    import time as _t
    dets = await _observer_detections(name, spec.tenant_id)
    pending = [d for d in dets if d["status"] == "pending"]
    recent = _read_trajectory_tail(spec, 20)
    prompt = (
        f"You are a read-only copilot for observer '{name}'. Do NOT call tools or take "
        f"actions. Answer from this context only.\n"
        f"Focus: {spec.focus}\n"
        f"Detections: {len(dets)} total, {len(pending)} pending approval.\n"
        f"Recent detections: {[{'id':d['id'],'skill':d['skill'],'status':d['status']} for d in dets[:5]]}\n"
        f"Recent activity (last steps): "
        f"{[{'type':s.get('type'),'content':(s.get('content') or '')[:80]} for s in recent[-6:] if isinstance(s,dict)]}\n\n"
        f"User: {body.message}"
    )
    result = await _run_scoped_chat(spec, f"observer:{name}:copilot:{int(_t.time())}", prompt, request)
    return {"observer": name, "mode": "copilot", "response": result.get("response")}
