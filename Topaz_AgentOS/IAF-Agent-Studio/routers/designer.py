"""Skill Designer — NL authoring endpoints (Dev Mode).

Draft → Validate → Save. The authoring brain is the draft-only `skill_designer` skill (`tools: []`),
invoked with `skill_name` hardcoded server-side so the runtime business router is NEVER reached (the
`if not skill_name` branch in chat.py that calls `router.match` is bypassed). Nothing here executes
business actions; `/save` persists via the SAME governed paths as create_skill / create_workstream /
create_cron. Developer/admin role required on every endpoint.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth.middleware import require_auth
from security.dependencies import (
    bind_request_identity, enforce_entitlement, make_agent_entitlement_checker,
)
from shared.config import SERVER_DIR, SKILLS_PATH
from shared.state import state, queue_manager
from iaf_agent_skills.queue_manager import QueueNames
from routers.designer_core import NAME_RE, parse_envelope, validate_envelope

logger = logging.getLogger(__name__)
router = APIRouter()

DESIGNER_SKILL = "skill_designer"
_DEV_ROLES = {"admin", "developer", "owner"}


class DesignerChat(BaseModel):
    message: str
    history: Optional[list] = None
    artifact_hint: Optional[str] = None
    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None


class DesignerArtifact(BaseModel):
    envelope: dict
    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None


def _require_dev(principal) -> None:
    roles = set(getattr(principal, "roles", []) or [])
    if not (roles & _DEV_ROLES):
        raise HTTPException(status_code=403, detail="Skill Designer requires a developer/admin role.")


def _skills_path() -> Path:
    return (SERVER_DIR / SKILLS_PATH).resolve()


def _catalog(agent) -> str:
    """Compact catalog of available skills + tools to ground the designer's drafts."""
    try:
        skills = [f"- {s['name']}: {(s.get('description') or '')[:90]}"
                  for s in agent.router.list_skills()][:150]
    except Exception:
        skills = []
    try:
        tools = list((getattr(agent, "config", {}) or {}).get("tools", {}).get("allowed", []))
    except Exception:
        tools = []
    return "AVAILABLE SKILLS (use only these as graph/workstream/worker nodes):\n" + "\n".join(skills) \
        + "\n\nAVAILABLE TOOLS:\n" + ", ".join(tools)


def _skill_md_from_env(env: dict):
    """Build (name, skill_md, graph_yaml) from a skill|graph_skill envelope — single source of
    truth shared by /save (direct write) and /submit (review queue)."""
    from routers.doc_to_skill import _build_skill_md
    at = env.get("artifact_type")
    sk = dict(env.get("skill") or {})
    name = sk.get("name") or env.get("name")
    if not NAME_RE.match(name or ""):
        raise HTTPException(400, "skill name must be snake_case")
    if at == "graph_skill":
        sk["execution_mode"] = "graph"
    skill_md = _build_skill_md({
        "name": name, "description": sk.get("description", ""),
        "execution_mode": sk.get("execution_mode", "react"),
        "keywords": sk.get("keywords", []), "tools": sk.get("tools", []),
        "business_context": sk.get("business_context", {}),
        "steps": sk.get("steps", []), "worker_skills": sk.get("worker_skills", []),
        "skill_md_body": sk.get("skill_md_body", ""),
    })
    if at == "graph_skill":
        # _build_skill_md doesn't know graph_ref; inject it next to execution_mode.
        skill_md = skill_md.replace("execution_mode: graph\n",
                                    "execution_mode: graph\ngraph_ref: graph.yaml\n", 1)
    return name, skill_md, (env.get("graph_yaml", "") if at == "graph_skill" else "")


@router.post("/api/designer/chat")
async def designer_chat(req: DesignerChat, request: Request, user: dict = Depends(require_auth)):
    """Draft an artifact from NL. Isolated: forces skill_designer, never hits the runtime router. No writes."""
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request, requested_tenant=req.tenant_id, requested_agent=req.agent_id, requested_user=req.user_id)
    _require_dev(principal)
    enforce_entitlement(principal, "use", "skill", DESIGNER_SKILL)

    user_role = principal.roles[0] if getattr(principal, "roles", None) else "admin"
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
    agent.auto_run = True

    hist = ""
    for h in (req.history or [])[-6:]:
        hist += f"\n{str(h.get('role', 'user')).upper()}: {str(h.get('content', ''))[:2000]}"
    prompt = (
        _catalog(agent)
        + (f"\n\nCONVERSATION SO FAR:{hist}" if hist else "")
        + (f"\n\nARTIFACT HINT: {req.artifact_hint}" if req.artifact_hint else "")
        + f"\n\nUSER REQUEST:\n{req.message}\n\n"
        "Respond with the strict JSON envelope from your instructions — one object, no prose outside it."
    )
    lane = QueueNames.session(tenant_id, user_id)
    try:
        resp = await queue_manager.enqueue(
            lane,
            lambda: agent.run(prompt, skill_name=DESIGNER_SKILL, light_mode=True, skip_memory=True),
            max_concurrent=1,
        )
        if isinstance(resp, tuple):
            resp = resp[0]
        envelope = parse_envelope(str(resp))
        return {"status": "drafted", "envelope": envelope}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surface authoring failures to the UI
        raise HTTPException(status_code=422, detail=f"Designer draft failed: {exc}") from exc


@router.post("/api/designer/validate")
async def designer_validate(req: DesignerArtifact, request: Request, user: dict = Depends(require_auth)):
    principal, *_ = bind_request_identity(request, requested_tenant=req.tenant_id, requested_user=req.user_id)
    _require_dev(principal)
    errs = validate_envelope(req.envelope or {})
    return {"ok": not errs, "errors": errs}


@router.post("/api/designer/save")
async def designer_save(req: DesignerArtifact, request: Request, user: dict = Depends(require_auth)):
    """Persist a validated draft via the existing governed creators."""
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request, requested_tenant=req.tenant_id, requested_agent=req.agent_id, requested_user=req.user_id)
    _require_dev(principal)
    env = req.envelope or {}
    errs = validate_envelope(env)
    if errs:
        raise HTTPException(status_code=400, detail={"errors": errs})
    at = env.get("artifact_type")

    # Direct-publish (admin) path; the governed path is /api/designer/submit.
    if at in ("skill", "graph_skill"):
        from routers.skills import _update_index_yaml, _invalidate_skills_cache
        sk = dict(env.get("skill") or {})
        name, skill_md, graph_yaml = _skill_md_from_env(env)
        enforce_entitlement(principal, "manage", "skill", name)
        folder = _skills_path() / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(skill_md, encoding="utf-8")
        if at == "graph_skill":
            (folder / "graph.yaml").write_text(graph_yaml, encoding="utf-8")
        await _update_index_yaml(_skills_path(), name, sk.get("description", ""),
                                 sk.get("keywords", []), "platform")
        _invalidate_skills_cache()
        return {"status": "saved", "artifact_type": at, "name": name}

    if at == "workstream":
        from iaf_agent_skills.workstream_store import WorkstreamStore, validate_workstream
        from routers.workstreams import _tenant_root
        enforce_entitlement(principal, "write", "agent", agent_id)
        ws = dict(env.get("workstream") or {})
        name = ws.get("name") or env.get("name")
        verrs = validate_workstream(ws)
        if verrs:
            raise HTTPException(400, {"errors": verrs})
        store = WorkstreamStore(_tenant_root(tenant_id))
        if store.exists(name):
            raise HTTPException(409, f"workstream '{name}' already exists")
        ws.setdefault("status", "active")
        store.save(ws)
        cron_info = None
        if ws.get("cron_schedule"):
            try:
                from shared.state import cron_scheduler
                from iaf_agent_skills.scheduler import Job
                job = Job(name=f"ws_{name}", skill_name="mission_mode", task=name,
                          cron=ws["cron_schedule"], tenant_id=tenant_id, agent_id="enterprise_agent",
                          user_id=ws.get("cron_user_id") or "service:cron", max_runtime_seconds=180,
                          enabled=(ws.get("status") == "active"), tags=["mission_mode", "workstream"])
                saved = cron_scheduler.add_job(job)
                store.update_workstream(name, cron_job_id=getattr(saved, "id", None))
                cron_info = {"job_id": getattr(saved, "id", None)}
            except Exception as e:  # noqa: BLE001
                logger.warning("designer: workstream cron provision failed: %s", e)
        return {"status": "saved", "artifact_type": "workstream", "name": name, "cron": cron_info}

    if at == "cron":
        from shared.state import cron_scheduler
        from iaf_agent_skills.scheduler import Job
        enforce_entitlement(principal, "write", "agent", agent_id)
        cr = dict(env.get("cron") or {})
        name = cr.get("name") or env.get("name")
        if cron_scheduler.get_job_by_name(name, tenant_id=tenant_id):
            raise HTTPException(409, f"cron job '{name}' already exists")
        job = Job(name=name, skill_name=cr.get("skill_name"), task=cr.get("task", ""),
                  cron=cr.get("cron", "0 * * * *"), tenant_id=tenant_id,
                  agent_id=agent_id or "enterprise_agent", user_id=user_id,
                  description=cr.get("description", ""), enabled=True, tags=["designer"])
        saved = cron_scheduler.add_job(job)
        return {"status": "saved", "artifact_type": "cron", "name": name, "job_id": getattr(saved, "id", None)}

    raise HTTPException(400, f"unknown artifact_type: {at!r}")


@router.post("/api/designer/submit")
async def designer_submit(req: DesignerArtifact, request: Request, user: dict = Depends(require_auth)):
    """Governed path for skills/graph-skills: write to the author's personal workspace and submit to
    the central review queue (Command Center → Skill Review → Review Queue). An admin approve promotes
    it to the global skills — reusing the EXACT existing personal-skill approval flow. No direct publish.
    (Workstream/cron have no review queue and continue to use /save.)"""
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request, requested_tenant=req.tenant_id, requested_agent=req.agent_id, requested_user=req.user_id)
    _require_dev(principal)
    env = req.envelope or {}
    at = env.get("artifact_type")
    if at not in ("skill", "graph_skill"):
        raise HTTPException(400, "Only skills and graph-skills go through the review queue; use /save for workstream/cron.")
    errs = validate_envelope(env)
    if errs:
        raise HTTPException(400, {"errors": errs})

    from routers.personal_skills import (
        save_personal_skill, submit_skill_for_review,
        SavePersonalSkillRequest, SubmitSkillRequest, _personal_skills_path,
    )
    from shared.file_utils import atomic_write_text

    name, skill_md, graph_yaml = _skill_md_from_env(env)
    # Key the personal workspace by the caller's canonical user_id (matches /me/ + the owner check).
    username = getattr(request.state, "user_id", None) or user_id

    # 1) Write into the author's personal workspace (reuses the governed personal-skill save).
    await save_personal_skill(request, username, SavePersonalSkillRequest(
        skill_name=name, skill_md_content=skill_md, tenant_id=tenant_id))
    # save_personal_skill only writes SKILL.md — graph_skills need graph.yaml beside it.
    if at == "graph_skill" and graph_yaml:
        atomic_write_text(_personal_skills_path(tenant_id, username) / name / "graph.yaml", graph_yaml)

    # 2) Submit for central admin review → appears in the Command Center Review Queue.
    result = await submit_skill_for_review(request, username, name, SubmitSkillRequest(
        tenant_id=tenant_id, notes=env.get("summary", ""), publish_mode="publish_new"))

    return {
        "status": "submitted",
        "artifact_type": at,
        "name": name,
        "submission_id": result.get("submission_id"),
        "review_url": "/dashboard/v2#skill-review",
    }
