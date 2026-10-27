"""
IAF Agent Studio — Skills Management API Router

CRUD for skills, tool script validation/testing, knowledge file management,
and skill lifecycle operations (clone, status, test).
"""

import ast
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time as _time_mod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import List, Optional

import yaml

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auth.middleware import require_admin, require_auth, require_permission
from security.dependencies import bind_request_identity, enforce_entitlement, make_agent_entitlement_checker, principal_from_request
from shared.config import (
    AGENTOS_UNTRUSTED_EXECUTION_GUARD, SERVER_DIR, SKILLS_PATH, ALLOWED_KNOWLEDGE_EXTS, DATA_ROOT,
)
from shared.file_utils import atomic_write_text, atomic_write_json, atomic_write_yaml, locked_rmw_yaml
from shared.skill_test_trace import build_test_trace_evidence
from shared.models import (
    SkillCreate, ToolScriptValidateRequest, ToolScriptTestRunRequest,
    SkillTestRequest, SkillCloneRequest, SkillStatusUpdate,
)
from shared.state import state, queue_manager
from iaf_agent_skills.providers.factory import build_router_provider, build_skill_provider
from iaf_agent_skills.queue_manager import QueueNames

logger = logging.getLogger(__name__)


def _safe_graph_filename(graph_ref: str) -> str:
    """Jail graph_ref to a bare filename written inside the skill dir.

    graph_ref is client-controlled and is joined to skill_dir; a value like
    ``../../shared/hooks/evil.py`` would escape the skill jail. Require a single safe
    basename (default graph.yaml) and reject any path separators or traversal.
    """
    name = (graph_ref or "graph.yaml").strip()
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        or name != os.path.basename(name)
    ):
        raise HTTPException(status_code=400, detail="invalid graph_ref (must be a bare filename)")
    return name

router = APIRouter()


class ComponentSourceRequest(BaseModel):
    """Reviewed component.html source to persist for a skill."""
    html: str = Field(..., min_length=1)


class ComponentDraftRequest(BaseModel):
    """Request an AI-authored component draft for a target skill."""
    instruction: str = ""
    current_html: str = ""
    detected_contract: dict = {}
    sample_props: dict = {}
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"


_skills_cache: dict = {"data": None, "timestamp": 0.0}
_SKILLS_CACHE_TTL = 5  # seconds


def _invalidate_skills_cache():
    """Bust the /api/skills cache after any skill mutation, and reload the runtime
    skill routers held by live agents so Auto-route picks up the new/edited/
    approved skill immediately — no restart or wait (RT-2)."""
    _skills_cache["data"] = None
    _skills_cache["timestamp"] = 0.0
    try:
        state.reload_skill_routers()
    except Exception as exc:  # noqa: BLE001 — never let a reload failure break the mutation
        logger.warning("reload_skill_routers after skill mutation failed: %s", exc)


from shared.user_display import display_name as _display_name_for_owner
from shared.user_display import apply_display_names as _resolve_owner_display_names




def _principal_is_admin(principal) -> bool:
    return "admin" in (getattr(principal, "roles", ()) or ())


def _principal_identity(principal) -> set[str]:
    """The identity strings a principal may be recorded as an owner under."""
    return {v for v in (getattr(principal, "email", None), getattr(principal, "user_id", None)) if v}


def _require_skill_owner_or_admin(request: Request, skill_dir) -> None:
    """Allow only the skill's creator (v1 author) or an admin to mutate it.

    Admins bypass the check; everyone else must match the recorded owner.
    """
    principal = principal_from_request(request)
    if _principal_is_admin(principal):
        return
    from shared import skill_versions
    skill_owner = skill_versions.owner(skill_dir)
    if skill_owner not in _principal_identity(principal):
        raise HTTPException(
            status_code=403,
            detail=f"Only the skill owner ({skill_owner}) or an admin can modify this skill.",
        )



@router.get("/api/skills")
async def list_skills(request: Request, user_id: str = None, tenant_id: str = "company", user: dict = Depends(require_auth)):
    """List all available skills with rich metadata.

    When user_id is provided, personal skills are appended with scope='personal'.
    Global results are cached for 5s; personal skills are always live.
    """
    from shared.config import DATA_ROOT

    now = _time_mod.time()
    if _skills_cache["data"] is None or (now - _skills_cache["timestamp"]) >= _SKILLS_CACHE_TTL:
        skills_path_str = str(SERVER_DIR / SKILLS_PATH)
        skills_path = SERVER_DIR / SKILLS_PATH
        skill_router = build_router_provider(skills_path_str)
        loader = build_skill_provider(skills_path_str)

        index_path = skills_path / "_index.yaml"
        index = {}
        if index_path.exists():
            index = yaml.safe_load(index_path.read_text(encoding='utf-8')) or {}
        index_skills = index.get("skills", {})

        global_skills = []
        for skill_info in skill_router.list_skills():
            sname = skill_info["name"]
            if not (skills_path / sname).is_dir():
                logger.warning("Skill '%s' in _index.yaml but folder missing — skipping", sname)
                continue
            idx_entry = index_skills.get(sname, {})
            # Newest-first ordering signal: SKILL.md mtime (created/last edited).
            try:
                _mtime = (skills_path / sname / "SKILL.md").stat().st_mtime
            except OSError:
                _mtime = 0.0
            try:
                from shared import skill_versions as _sv
                _created_by = _sv.owner(skills_path / sname)
                skill = loader.load(sname)
                # Read context_files directly from SKILL.md frontmatter (not on Skill dataclass)
                ctx_files = []
                skill_md = skills_path / sname / "SKILL.md"
                if skill_md.exists():
                    import re as _re
                    raw = skill_md.read_text(encoding='utf-8')
                    fm_match = _re.match(r'^---\n(.*?)\n---', raw, _re.DOTALL)
                    if fm_match:
                        fm = yaml.safe_load(fm_match.group(1)) or {}
                        ctx_files = fm.get('context_files', []) or []
                global_skills.append({
                    "name": sname,
                    "description": skill_info.get("description", ""),
                    "execution_mode": getattr(skill, 'execution_mode', 'react'),
                    "has_steps": len(getattr(skill, 'steps', [])) > 0,
                    "step_count": len(getattr(skill, 'steps', [])),
                    "worker_count": len(getattr(skill, 'worker_skills', [])),
                    "version": getattr(skill, 'version', '1.0'),
                    "tools": getattr(skill, 'tools', []),
                    "context_files": ctx_files,
                    "keywords": idx_entry.get("keywords", []),
                    "status": idx_entry.get("status", "active"),
                    "category": idx_entry.get("category", "other"),
                    "business_context": getattr(skill, 'business_context', {}),
                    "created_by": _created_by,
                    "_sort_ts": _mtime,
                })
            except Exception as e:
                global_skills.append({
                    "name": sname,
                    "description": skill_info.get("description", ""),
                    "error": str(e),
                    "status": idx_entry.get("status", "active"),
                    "_sort_ts": _mtime,
                })

        # Newest skill first (last-in, first-out). Strips the internal sort key.
        global_skills.sort(key=lambda s: s.pop("_sort_ts", 0.0), reverse=True)

        _skills_cache["data"] = global_skills
        _skills_cache["timestamp"] = now

    skills = list(_skills_cache["data"])

    # Append personal skills for the requesting user (always live, never cached)
    principal, tenant_id, _, bound_user_id = bind_request_identity(request, requested_tenant=tenant_id, requested_user=user_id)
    user_id = bound_user_id

    if user_id:
        personal_dir = (
            (SERVER_DIR / DATA_ROOT).resolve()
            / "tenants" / tenant_id / "agents" / "enterprise_agent" / "users" / user_id / "skills"
        )
        personal_index_path = personal_dir / "_index.yaml"
        if personal_index_path.exists():
            personal_index = yaml.safe_load(personal_index_path.read_text(encoding='utf-8')) or {}
            global_names = {s["name"] for s in skills}
            for pname, pinfo in personal_index.get("skills", {}).items():
                if pname in global_names:
                    continue   # already in global list (approved)
                skills.append({
                    "name": pname,
                    "description": pinfo.get("description", ""),
                    "scope": pinfo.get("scope", "personal"),
                    "status": pinfo.get("status", "active"),
                    "keywords": pinfo.get("keywords", []),
                    "category": pinfo.get("category", "personal"),
                    "execution_mode": "react",
                    "created_by": pinfo.get("created_by", user_id),
                })

    # Read category metadata from _index.yaml so UI can group without hardcoding
    skills_path = SERVER_DIR / SKILLS_PATH
    index_path = skills_path / "_index.yaml"
    index = yaml.safe_load(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
    category_labels = index.get("category_labels", {})
    category_order  = index.get("category_order", [])

    filtered = []
    for skill in skills:
        try:
            enforce_entitlement(principal, "use", "skill", skill.get("name", ""))
            filtered.append(skill)
        except HTTPException:
            continue

    # Show the owner's display name instead of their email.
    await _resolve_owner_display_names(filtered)

    return {"skills": filtered, "category_labels": category_labels, "category_order": category_order}


@router.get("/api/skills/names")
async def get_skill_names(request: Request, user_id: str = None, tenant_id: str = "company", user: dict = Depends(require_auth)):
    """Get skill names for dropdowns. Merges personal skills when user_id is provided."""
    from shared.config import DATA_ROOT
    skills_path = SERVER_DIR / SKILLS_PATH
    index_path = skills_path / "_index.yaml"

    if not index_path.exists():
        return {"names": []}

    index = yaml.safe_load(index_path.read_text(encoding='utf-8')) or {}
    skills_map = index.get("skills", {})
    # Build {name: category} from global index
    name_category: dict = {
        name: (meta.get("category", "other") if isinstance(meta, dict) else "other")
        for name, meta in skills_map.items()
    }

    principal, tenant_id, _, bound_user_id = bind_request_identity(request, requested_tenant=tenant_id, requested_user=user_id)
    user_id = bound_user_id

    if user_id:
        personal_index_path = (
            (SERVER_DIR / DATA_ROOT).resolve()
            / "tenants" / tenant_id / "agents" / "enterprise_agent" / "users" / user_id / "skills" / "_index.yaml"
        )
        if personal_index_path.exists():
            personal_index = yaml.safe_load(personal_index_path.read_text(encoding='utf-8')) or {}
            for pname, pmeta in personal_index.get("skills", {}).items():
                cat = (pmeta.get("category", "personal") if isinstance(pmeta, dict) else "personal")
                name_category.setdefault(pname, cat)

    # Return list of {name, category} objects — UI uses category for optgroup grouping.
    # Sorted by name for consistent ordering.
    filtered_names = []
    for n in sorted(name_category):
        try:
            enforce_entitlement(principal, "use", "skill", n)
            filtered_names.append({"name": n, "category": name_category[n]})
        except HTTPException:
            continue
    return {"names": filtered_names}


def _parse_graph_topology(graph_yaml: str) -> dict:
    """Parse a process-graph YAML into a UI-friendly topology.

    Returns nodes (topologically ordered along the happy path), edges (with their
    `when` labels so branches are visible), and the converge block (so the loop can
    be drawn). A graph is a spine + branches + a converge loop — not a linear
    workflow — so we hand the frontend enough to represent all three faithfully.
    """
    try:
        g = yaml.safe_load(graph_yaml) or {}
    except Exception:
        return {}
    raw_nodes = [n for n in (g.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
    nodes = [{
        "id": n.get("id"),
        "skill": n.get("skill", "") or "",
        "role": n.get("role", "worker") or "worker",
        "pass_when": (n.get("verdict") or {}).get("pass_when"),
    } for n in raw_nodes]
    edges = [{
        "from": e.get("from"), "to": e.get("to"), "when": e.get("when", "") or "",
    } for e in (g.get("edges") or []) if isinstance(e, dict) and e.get("from") and e.get("to")]

    # Topological order (Kahn) so the rail reads left→right along the spine. Converge
    # is NOT an edge, so the edge set is acyclic; fall back to declaration order.
    ids = [n["id"] for n in nodes]
    indeg = {i: 0 for i in ids}
    adj = {i: [] for i in ids}
    for e in edges:
        if e["from"] in adj and e["to"] in indeg:
            adj[e["from"]].append(e["to"])
            indeg[e["to"]] += 1
    queue = [i for i in ids if indeg[i] == 0]
    order = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj.get(cur, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(order) == len(ids):
        pos = {i: k for k, i in enumerate(order)}
        nodes.sort(key=lambda n: pos.get(n["id"], 999))

    cv = g.get("converge") or {}
    converge = {}
    if isinstance(cv, dict) and cv.get("scope"):
        converge = {
            "scope": list(cv.get("scope") or []),
            "max_loops": cv.get("max_loops"),
            "on_exhausted": cv.get("on_exhausted", "") or "",
            "until": cv.get("until", "") or "",
        }
    return {"nodes": nodes, "edges": edges, "converge": converge}


@router.get("/api/skills/{skill_name}")
async def get_skill(request: Request, skill_name: str, user: dict = Depends(require_auth)):
    """Get skill details for viewing and editing."""
    enforce_entitlement(principal_from_request(request), "read", "skill", skill_name)
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_file = skills_path / skill_name / "SKILL.md"

    if not skill_file.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    content = skill_file.read_text(encoding='utf-8')

    frontmatter = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()

    tool_scripts = _read_tool_scripts(skills_path / skill_name)

    # Graph mode: load the sibling process-graph YAML and parse its topology for the Process Flow rail.
    graph_ref = frontmatter.get("graph_ref", "") or ""
    graph_yaml = ""
    graph_topology = {}
    if frontmatter.get("execution_mode") == "graph":
        # Coerce to a bare filename so a malicious on-disk graph_ref can't read outside
        # the skill dir; fall back to graph.yaml rather than failing the listing.
        _gname = os.path.basename((graph_ref or "graph.yaml").strip()) or "graph.yaml"
        _gfile = skills_path / skill_name / _gname
        if _gfile.exists():
            try:
                graph_yaml = _gfile.read_text(encoding="utf-8")
            except Exception:
                graph_yaml = ""
        if graph_yaml:
            graph_topology = _parse_graph_topology(graph_yaml)

    from shared import skill_versions
    return {
        "name": frontmatter.get("name", skill_name),
        "description": frontmatter.get("description", ""),
        "version": frontmatter.get("version", "1.0"),
        "execution_mode": frontmatter.get("execution_mode", "react"),
        "profile": frontmatter.get("profile", ""),
        "keywords": frontmatter.get("keywords", frontmatter.get("triggers", [])),
        "steps": frontmatter.get("steps", []),
        "worker_skills": frontmatter.get("worker_skills", []),
        "tools": frontmatter.get("tools", ["shell"]),
        "business_context": frontmatter.get("business_context", {}),
        "connections": frontmatter.get("connections", []),
        "mcp_connections": frontmatter.get("mcp_connections", []),
        "mcp_tools": frontmatter.get("mcp_tools", []),
        "context_file": frontmatter.get("context_file", ""),
        "sql_mode": frontmatter.get("sql_mode", "read_only"),
        "approval_rules": frontmatter.get("approval_rules", {}),
        "knowledge": frontmatter.get("knowledge", []),
        "category": frontmatter.get("category", ""),
        "max_steps": frontmatter.get("max_steps", None),
        "graph_ref": graph_ref,
        "graph_yaml": graph_yaml,
        "graph": graph_topology,
        "tool_scripts": tool_scripts,
        "prompt": body,
        "raw_content": content,
        "created_by": (_sk_owner := skill_versions.owner(skills_path / skill_name)),
        "created_by_display": await _display_name_for_owner(_sk_owner),
    }


def _component_url(skill_name: str, name: Optional[str]) -> str:
    """Public render URL for a component (default vs named)."""
    cid = _resolve_component_id(name)
    base = f"/api/skills/{skill_name}/component"
    return base if cid is None else f"{base}?name={cid}"


@router.get("/api/skills/{skill_name}/component", response_class=HTMLResponse)
async def get_skill_component(
    request: Request, skill_name: str, name: Optional[str] = None, user: dict = Depends(require_auth)
):
    """Serve a skill-local HTML component template used by chat renderers.
    `?name=<id>` selects a named component (`components/<id>.html`); omitted → `component.html`."""
    enforce_entitlement(principal_from_request(request), "read", "skill", skill_name)
    component_file = _component_path_for_skill(skill_name, name)
    if not component_file.exists() or not component_file.is_file():
        raise HTTPException(status_code=404, detail=f"Component for skill '{skill_name}' not found")
    return HTMLResponse(component_file.read_text(encoding="utf-8"))


@router.get("/api/skills/{skill_name}/component-source")
async def get_skill_component_source(
    request: Request, skill_name: str, name: Optional[str] = None, user: dict = Depends(require_auth)
):
    """Return editable component source for Skill Builder (default or `?name=<id>`)."""
    enforce_entitlement(principal_from_request(request), "read", "skill", skill_name)
    component_file = _component_path_for_skill(skill_name, name)
    exists = component_file.exists() and component_file.is_file()
    return {
        "skill": skill_name,
        "component": _resolve_component_id(name) or "component",
        "exists": exists,
        "html": component_file.read_text(encoding="utf-8") if exists else "",
        "url": _component_url(skill_name, name),
        "size_bytes": component_file.stat().st_size if exists else 0,
        "updated_at": datetime.fromtimestamp(component_file.stat().st_mtime).isoformat() if exists else None,
    }


@router.put("/api/skills/{skill_name}/component-source")
async def save_skill_component_source(
    request: Request,
    skill_name: str,
    req: ComponentSourceRequest,
    name: Optional[str] = None,
    user: dict = Depends(require_auth),
):
    """Persist reviewed component source for a skill (default or `?name=<id>`)."""
    principal = principal_from_request(request)
    enforce_entitlement(principal, "manage", "skill", skill_name)
    component_file = _component_path_for_skill(skill_name, name)
    _validate_component_html(req.html, skill_name=skill_name)
    component_file.parent.mkdir(parents=True, exist_ok=True)  # create components/ on first named save
    atomic_write_text(component_file, req.html.strip() + "\n")
    return {
        "status": "saved",
        "skill": skill_name,
        "component": _resolve_component_id(name) or "component",
        "url": _component_url(skill_name, name),
        "size_bytes": component_file.stat().st_size,
    }


@router.get("/api/skills/{skill_name}/components")
async def list_skill_components(request: Request, skill_name: str, user: dict = Depends(require_auth)):
    """List every UI component a skill ships: the default `component.html` (id `component`)
    plus each `components/<id>.html`. Used by Skill Builder and the chat renderer."""
    enforce_entitlement(principal_from_request(request), "read", "skill", skill_name)
    skill_dir = _skill_dir_for_name(skill_name)
    out: list[dict] = []

    default_file = skill_dir / "component.html"
    if default_file.exists() and default_file.is_file():
        st = default_file.stat()
        out.append({
            "id": "component", "is_default": True,
            "url": f"/api/skills/{skill_name}/component",
            "size_bytes": st.st_size,
            "updated_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
        })

    comp_dir = skill_dir / "components"
    if comp_dir.is_dir():
        for f in sorted(comp_dir.glob("*.html")):
            cid = f.stem
            if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", cid):
                continue  # skip anything that isn't a valid component id
            st = f.stat()
            out.append({
                "id": cid, "is_default": False,
                "url": f"/api/skills/{skill_name}/component?name={cid}",
                "size_bytes": st.st_size,
                "updated_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
            })

    return {"skill": skill_name, "components": out, "total": len(out)}


@router.post("/api/skills/{skill_name}/component-draft")
async def draft_skill_component(
    request: Request,
    skill_name: str,
    req: ComponentDraftRequest,
    name: Optional[str] = None,
    user: dict = Depends(require_auth),
):
    """Invoke component_authoring to draft a component without saving it (default or `?name=<id>`)."""
    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request,
        requested_tenant=req.tenant_id,
        requested_agent=req.agent_id,
        requested_user=req.user_id,
    )
    # Drafting does not persist the component. Users who can read the target
    # skill may request a proposal; saving still requires manage.
    enforce_entitlement(principal, "read", "skill", skill_name)
    enforce_entitlement(principal, "use", "skill", "component_authoring")

    skill_dir = _skill_dir_for_name(skill_name)
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    current_html = req.current_html
    if not current_html:
        component_file = _component_path_for_skill(skill_name, name)
        if component_file.exists():
            current_html = component_file.read_text(encoding="utf-8")

    prompt = _build_component_authoring_prompt(
        skill_name=skill_name,
        skill_md=skill_md,
        current_html=current_html,
        instruction=req.instruction,
        detected_contract=req.detected_contract,
        sample_props=req.sample_props,
    )
    user_role = principal.roles[0] if principal.roles else "admin"
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
    agent.auto_run = True

    lane_name = QueueNames.session(tenant_id, user_id)
    try:
        response = await queue_manager.enqueue(
            lane_name,
            lambda: agent.run(prompt, skill_name="component_authoring", light_mode=True),
            max_concurrent=1,
        )
        parsed = _parse_component_authoring_response(response)
        warnings = _component_html_warnings(parsed.get("html", ""), skill_name=skill_name)
        return {
            "status": "drafted",
            "skill": skill_name,
            "html": parsed.get("html", ""),
            "sample_props": parsed.get("sample_props", {}),
            "notes": parsed.get("notes", []),
            "warnings": warnings,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surface authoring failures to UI
        logger.exception("Component draft failed")
        raise HTTPException(status_code=422, detail="Component draft failed") from exc


def _skill_dir_for_name(skill_name: str) -> Path:
    from shared.skill_name_utils import is_valid_skill_folder_name

    if not is_valid_skill_folder_name(skill_name):
        raise HTTPException(status_code=400, detail="Invalid skill name")
    skill_name = skill_name.strip()
    skills_path = (SERVER_DIR / SKILLS_PATH).resolve()
    skill_dir = (skills_path / skill_name).resolve()
    try:
        skill_dir.relative_to(skills_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid skill path") from None
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return skill_dir


# The default component lives at the skill root as component.html; named ones under components/<id>.html.
_DEFAULT_COMPONENT_ALIASES = {"", "default", "component", "component.html"}


def _resolve_component_id(name: Optional[str]) -> Optional[str]:
    """Validate a component id. Returns None for the default (`component.html`),
    else the sanitized id used at `components/<id>.html`."""
    if name is None:
        return None
    n = name.strip()
    if n.lower() in _DEFAULT_COMPONENT_ALIASES:
        return None
    if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", n):
        raise HTTPException(status_code=400, detail="Invalid component name")
    return n


def _component_path_for_skill(skill_name: str, name: Optional[str] = None) -> Path:
    """Resolve a skill's component file. `name` None/default → `component.html`;
    a named component → `components/<id>.html`. Always path-jailed under SKILLS_PATH."""
    skill_dir = _skill_dir_for_name(skill_name)
    cid = _resolve_component_id(name)
    if cid is None:
        component_file = (skill_dir / "component.html").resolve()
    else:
        component_file = (skill_dir / "components" / f"{cid}.html").resolve()
    try:
        component_file.relative_to((SERVER_DIR / SKILLS_PATH).resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid component path") from None
    return component_file


def _component_html_warnings(html: str, *, skill_name: str) -> list[str]:
    warnings: list[str] = []
    raw = html or ""
    lowered = raw.lower()
    if not raw.strip():
        warnings.append("Component HTML is empty.")
    if f'data-skill-component="{skill_name}"' not in raw and f"data-skill-component='{skill_name}'" not in raw:
        warnings.append(f"Root component should include data-skill-component=\"{skill_name}\".")
    if re.search(r"<\s*(script|iframe|object|embed)\b", lowered):
        warnings.append("Components cannot include script, iframe, object, or embed tags.")
    if re.search(r"\son[a-z]+\s*=", lowered):
        warnings.append("Components cannot include inline event handlers like onclick/onload.")
    if "javascript:" in lowered:
        warnings.append("Components cannot include javascript: URLs.")
    return warnings


def _validate_component_html(html: str, *, skill_name: str) -> None:
    warnings = _component_html_warnings(html, skill_name=skill_name)
    blocking = [w for w in warnings if "cannot include" in w or "empty" in w]
    if blocking:
        raise HTTPException(status_code=400, detail=" ".join(blocking))


def _build_component_authoring_prompt(
    *,
    skill_name: str,
    skill_md: str,
    current_html: str,
    instruction: str,
    detected_contract: dict,
    sample_props: dict,
) -> str:
    return (
        "Draft or revise component.html for the target AgentPro skill.\n"
        "Return strict JSON only with keys html, sample_props, notes.\n\n"
        f"TARGET_SKILL: {skill_name}\n\n"
        f"USER_INSTRUCTION:\n{instruction or 'Create or improve the component from the skill contract.'}\n\n"
        f"DETECTED_CONTRACT_JSON:\n{json.dumps(detected_contract or {}, indent=2)}\n\n"
        f"SAMPLE_PROPS_JSON:\n{json.dumps(sample_props or {}, indent=2)}\n\n"
        f"CURRENT_COMPONENT_HTML:\n{current_html or '(none)'}\n\n"
        f"TARGET_SKILL_MD:\n{skill_md[:12000]}\n"
    )


def _parse_component_authoring_response(response) -> dict:
    text = response if isinstance(response, str) else (
        response.get("response") if isinstance(response, dict) else str(response)
    )
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        raise ValueError("Authoring skill did not return a JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Authoring response JSON must be an object")
    if "html" not in data:
        raise ValueError("Authoring response missing html")
    return {
        "html": str(data.get("html") or ""),
        "sample_props": data.get("sample_props") if isinstance(data.get("sample_props"), dict) else {},
        "notes": data.get("notes") if isinstance(data.get("notes"), list) else [],
    }


def _validate_graph_yaml(graph_yaml: str) -> None:
    """Validate a process-graph YAML for graph-mode skills (raises HTTPException on failure)."""
    if not (graph_yaml or "").strip():
        raise HTTPException(400, "Graph mode requires a process-graph YAML")
    try:
        import yaml as _yaml
        from iaf_agent_skills.process_graph import validate_graph, compile_to_plan
        g = _yaml.safe_load(graph_yaml)
        validate_graph(g)
        compile_to_plan(g)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface graph errors to the builder
        raise HTTPException(400, f"Invalid process graph: {e}")


# A skill name must be a single safe folder token (create_skill joins it onto the skills root).
def _validate_creatable_skill_name(name) -> None:
    """Reject skill names that aren't safe folder tokens (path-traversal / absolute
    paths / separators). Raises HTTPException(400) so callers get a clean error."""
    from shared.skill_name_utils import is_valid_skill_folder_name

    if not isinstance(name, str):
        raise HTTPException(
            status_code=400,
            detail="Invalid skill name (use letters, digits, spaces, '_' or '-'; max 80 chars)",
        )
    if name != name.strip():
        raise HTTPException(
            status_code=400,
            detail="Invalid skill name (leading or trailing whitespace is not allowed)",
        )
    if not is_valid_skill_folder_name(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid skill name (use letters, digits, spaces, '_' or '-'; max 80 chars)",
        )


@router.post("/api/skills")
async def create_skill(request: Request, skill: SkillCreate, admin: dict = Depends(require_permission("skills.author"))):
    """Create a new skill with multi-agentic support."""
    _validate_creatable_skill_name(skill.name)
    skill_name = skill.name.strip()
    enforce_entitlement(principal_from_request(request), "manage", "skill", skill_name)
    skills_path = (SERVER_DIR / SKILLS_PATH).resolve()
    skill_dir = (skills_path / skill_name).resolve()
    # Defence in depth: even with the charset guard, confirm the resolved path
    # stays inside the skills root before we mkdir anything.
    try:
        skill_dir.relative_to(skills_path)
    except ValueError:
        raise HTTPException(400, "Invalid skill path") from None

    if skill_dir.exists():
        raise HTTPException(400, f"Skill '{skill_name}' already exists")

    if skill.execution_mode in ["workflow", "parallel"] and not skill.steps:
        raise HTTPException(400, f"Execution mode '{skill.execution_mode}' requires at least one step")
    if skill.execution_mode in ["supervisor", "orchestrator"] and not skill.worker_skills:
        raise HTTPException(400, f"{skill.execution_mode.capitalize()} mode requires at least one worker_skill")
    graph_filename = None
    if skill.execution_mode == "graph":
        _validate_graph_yaml(skill.graph_yaml)
        # Validate graph_ref before creating anything, so a bad value can't leave
        # an empty skill folder behind.
        graph_filename = _safe_graph_filename(skill.graph_ref)

    skill_dir.mkdir(parents=True)

    skill_content = _build_skill_md(skill)

    # Record v1 as the active version (writes live SKILL.md, tools/ and graph YAML).
    from shared import skill_versions
    _principal = principal_from_request(request)
    _author = getattr(_principal, "email", None) or getattr(_principal, "user_id", None) or "unknown"
    entry = skill_versions.record_version(
        skill_dir,
        skill_md=skill_content,
        tool_scripts=skill.tool_scripts,
        author=_author,
        email=getattr(_principal, "email", "") or "",
        action="create",
        note=skill.version_note,
        version_label=skill.version,
        make_active=True,
        graph_files={graph_filename: skill.graph_yaml} if graph_filename else None,
    )

    await _update_index_yaml(skills_path, skill_name, skill.description, skill.keywords, skill.category)

    _invalidate_skills_cache()
    return {"message": f"Created skill '{skill_name}'", "path": str(skill_dir),
            "execution_mode": skill.execution_mode, "version": entry}


@router.put("/api/skills/{skill_name}")
async def update_skill(request: Request, skill_name: str, skill: SkillCreate, admin: dict = Depends(require_permission("skills.author"))):
    """Update an existing skill."""
    enforce_entitlement(principal_from_request(request), "manage", "skill", skill_name)
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name

    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    # Ownership gate: only the creator or an admin may edit this skill.
    _require_skill_owner_or_admin(request, skill_dir)

    if skill.execution_mode in ["workflow", "parallel"] and not skill.steps:
        raise HTTPException(400, f"Execution mode '{skill.execution_mode}' requires at least one step")
    if skill.execution_mode in ["supervisor", "orchestrator"] and not skill.worker_skills:
        raise HTTPException(400, f"{skill.execution_mode.capitalize()} mode requires at least one worker_skill")
    if skill.execution_mode == "graph":
        _validate_graph_yaml(skill.graph_yaml)

    skill_content = _build_skill_md(skill)

    # The graph YAML is versioned with SKILL.md and goes live only via _write_live.
    graph_files = (
        {_safe_graph_filename(skill.graph_ref): skill.graph_yaml}
        if skill.execution_mode == "graph" else None
    )

    # The skill_versions calls below write live SKILL.md + tools/ + graph YAML via
    # _write_live, so no separate write is needed here.
    from shared import skill_versions
    _principal = principal_from_request(request)
    _author = getattr(_principal, "email", None) or getattr(_principal, "user_id", None) or "unknown"
    _email = getattr(_principal, "email", "") or ""

    if (skill.save_mode or "current") == "new":
        # Save as a NEW, INACTIVE version — live SKILL.md + tools + _index stay put.
        entry = skill_versions.record_version(
            skill_dir,
            skill_md=skill_content,
            tool_scripts=skill.tool_scripts,
            author=_author,
            email=_email,
            action="update",
            note=skill.version_note,
            version_label=skill.version,
            make_active=False,
            graph_files=graph_files,
        )
        _invalidate_skills_cache()
        return {"message": f"Saved '{skill_name}' as new version {entry['id']} (inactive — activate to go live)",
                "version": entry, "execution_mode": skill.execution_mode}

    # Update the CURRENT (active) version in place — rewrites the live files.
    entry = skill_versions.update_active_version(
        skill_dir,
        skill_md=skill_content,
        tool_scripts=skill.tool_scripts,
        author=_author,
        email=_email,
        note=skill.version_note,
        version_label=skill.version,
        graph_files=graph_files,
    )

    await _update_index_yaml(skills_path, skill.name, skill.description, skill.keywords, skill.category)

    _invalidate_skills_cache()
    return {"message": f"Updated skill '{skill_name}'", "version": entry, "execution_mode": skill.execution_mode}


@router.get("/api/skills/{skill_name}/versions")
async def list_skill_versions(request: Request, skill_name: str, user: dict = Depends(require_auth)):
    """List a skill's version history + which one is active."""
    enforce_entitlement(principal_from_request(request), "read", "skill", skill_name)
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    from shared import skill_versions
    return skill_versions.list_versions(skill_dir)


@router.get("/api/skills/{skill_name}/versions/{version_id}")
async def get_skill_version(request: Request, skill_name: str, version_id: str, user: dict = Depends(require_auth)):
    """Return one version's snapshot content (SKILL.md + tool scripts) for view/diff."""
    enforce_entitlement(principal_from_request(request), "read", "skill", skill_name)
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    from shared import skill_versions
    content = skill_versions.get_version_content(skill_dir, version_id)
    if content is None:
        raise HTTPException(404, f"Version '{version_id}' not found for skill '{skill_name}'")
    return content


@router.post("/api/skills/{skill_name}/versions/{version_id}/activate")
async def activate_skill_version(request: Request, skill_name: str, version_id: str, admin: dict = Depends(require_permission("skills.author"))):
    """Promote a version to live (rewrite SKILL.md + tools/, move the active pointer)."""
    enforce_entitlement(principal_from_request(request), "manage", "skill", skill_name)
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    # Ownership gate: only the creator or an admin may activate a version.
    _require_skill_owner_or_admin(request, skill_dir)
    from shared import skill_versions
    _principal = principal_from_request(request)
    _author = getattr(_principal, "email", None) or getattr(_principal, "user_id", None) or "unknown"
    try:
        entry = skill_versions.activate_version(
            skill_dir, version_id, author=_author, email=getattr(_principal, "email", "") or "",
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc))

    # Active content changed → re-derive the index entry from the now-live SKILL.md.
    try:
        md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm = {}
        if md.startswith("---"):
            parts = md.split("---", 2)
            if len(parts) >= 3:
                fm = yaml.safe_load(parts[1]) or {}
        await _update_index_yaml(
            skills_path, skill_name,
            fm.get("description", ""),
            fm.get("triggers", fm.get("keywords", [])) or [],
            fm.get("category"),
        )
    except Exception as exc:
        logger.warning("activate: reindex from active SKILL.md failed for %s: %s", skill_name, exc)

    _invalidate_skills_cache()
    return {"message": f"Activated version {version_id} of '{skill_name}'", "active": version_id, "version": entry}


@router.delete("/api/skills/{skill_name}")
async def delete_skill(request: Request, skill_name: str, admin: dict = Depends(require_permission("skills.author"))):
    """Delete a skill and remove from index."""
    enforce_entitlement(principal_from_request(request), "manage", "skill", skill_name)
    # Protected skills that cannot be deleted
    protected = ["general"]
    if skill_name in protected:
        raise HTTPException(400, f"Cannot delete protected skill '{skill_name}'")

    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name

    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    # Ownership gate: only the creator or an admin may delete this skill.
    _require_skill_owner_or_admin(request, skill_dir)

    shutil.rmtree(skill_dir)

    index_path = skills_path / "_index.yaml"
    if index_path.exists():
        def _remove(index: dict) -> dict:
            index.get("skills", {}).pop(skill_name, None)
            return index
        await locked_rmw_yaml(index_path, _remove)

    _invalidate_skills_cache()
    return {"message": f"Deleted skill '{skill_name}'"}


@router.post("/api/skills/{skill_name}/test")
async def test_skill(skill_name: str, req: SkillTestRequest, request: Request, user: dict = Depends(require_auth)):
    """Test a skill with a prompt in light mode (skips memory/learning)."""
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    start = _time_mod.time()
    try:
        principal, tenant_id, agent_id, user_id = bind_request_identity(
            request,
            requested_tenant=req.tenant_id,
            requested_agent=req.agent_id,
            requested_user=req.user_id,
        )
        user_role = principal.roles[0] if principal.roles else "user"
        enforce_entitlement(principal, "use", "agent", agent_id)
        enforce_entitlement(principal, "test", "skill", skill_name)
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
        kernel = state.get_kernel(tenant_id, agent_id, user_id, user_role=user_role)
        kernel.require_confirmation = False
        agent.auto_run = True

        lane_name = QueueNames.session(tenant_id, user_id)
        response = await queue_manager.enqueue(
            lane_name,
            lambda: agent.run(req.prompt, skill_name=skill_name, light_mode=True),
            max_concurrent=1,
        )
        duration_ms = int((_time_mod.time() - start) * 1000)
        result = {
            "status": "ok",
            "response": response,
            "skill": skill_name,
            "duration_ms": duration_ms,
        }
        trace = build_test_trace_evidence(
            getattr(agent, "_last_decision_context", None),
            getattr(agent, "_evidence_bundle", None),
        )
        if trace:
            result["trace"] = trace
            if trace.get("trace_id"):
                result["trace_id"] = trace["trace_id"]
        _record_studio_test_run(skill_name, req, result)
        return result
    except Exception as e:
        duration_ms = int((_time_mod.time() - start) * 1000)
        result = {"status": "error", "error": str(e), "skill": skill_name, "duration_ms": duration_ms}
        _record_studio_test_run(skill_name, req, result)
        return result


@router.get("/api/skills/{skill_name}/test-runs")
async def list_studio_test_runs(
    skill_name: str,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
    limit: int = 20,
    user: dict = Depends(require_auth),
):
    """List compact Studio test history for a skill/user workspace."""
    path = _studio_test_runs_file(tenant_id, agent_id, user_id, skill_name)
    if not path.exists():
        return {"skill": skill_name, "runs": []}
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        runs = []
    return {"skill": skill_name, "runs": runs[:max(1, min(limit, 100))]}


def _studio_test_runs_file(tenant_id: str, agent_id: str, user_id: str, skill_name: str) -> Path:
    safe_user = (user_id or "demo").replace("/", "_").replace("\\", "_")
    safe_skill = skill_name.replace("/", "_").replace("\\", "_")
    return (
        SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id /
        "users" / safe_user / "studio_test_runs" / f"{safe_skill}.json"
    )


def _preview(value: object, limit: int = 900) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _record_studio_test_run(skill_name: str, req: SkillTestRequest, result: dict) -> None:
    path = _studio_test_runs_file(req.tenant_id, req.agent_id, req.user_id, skill_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        existing = []
    record = {
        "id": f"{skill_name}_{int(_time_mod.time() * 1000)}",
        "skill": skill_name,
        "status": result.get("status", "unknown"),
        "duration_ms": result.get("duration_ms", 0),
        "timestamp": datetime.now().isoformat(),
        "tenant_id": req.tenant_id,
        "agent_id": req.agent_id,
        "user_id": req.user_id,
        "prompt_preview": _preview(req.prompt, 400),
        "response_preview": _preview(result.get("response") or result.get("error"), 900),
    }
    atomic_write_json(path, [record] + existing[:49])


@router.post("/api/skills/{skill_name}/clone")
async def clone_skill(request: Request, skill_name: str, req: SkillCloneRequest, admin: dict = Depends(require_permission("skills.author"))):
    """Clone a skill to a new name."""
    principal = principal_from_request(request)
    enforce_entitlement(principal, "read", "skill", skill_name)
    enforce_entitlement(principal, "manage", "skill", req.new_name)
    # Validate the destination name like create_skill: entitlements are advisory, so the charset and containment checks stop path escape.
    _validate_creatable_skill_name(req.new_name)
    skills_path = (SERVER_DIR / SKILLS_PATH).resolve()
    src = (skills_path / skill_name).resolve()
    dst = (skills_path / req.new_name).resolve()
    # Contain both ends: a traversal/symlinked source must not let copytree read arbitrary directories.
    try:
        src.relative_to(skills_path)
        dst.relative_to(skills_path)
    except ValueError:
        raise HTTPException(400, "Invalid skill path") from None

    if not src.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    if dst.exists():
        raise HTTPException(400, f"Skill '{req.new_name}' already exists")

    shutil.copytree(src, dst)

    skill_file = dst / "SKILL.md"
    if skill_file.exists():
        content = skill_file.read_text(encoding='utf-8')
        content = content.replace(f"name: {skill_name}", f"name: {req.new_name}", 1)
        atomic_write_text(skill_file, content)

    # Reset lineage and ownership: a clone is a new artifact authored by the cloner.
    from shared import skill_versions
    _vdir = dst / ".versions"
    if _vdir.exists():
        shutil.rmtree(_vdir)
    _clone_tools = []
    _tools_dir = dst / "tools"
    if _tools_dir.is_dir():
        for _tp in sorted(_tools_dir.glob("*.py")):
            if _tp.name.startswith("__"):
                continue
            _clone_tools.append({"filename": _tp.name, "content": _tp.read_text(encoding="utf-8")})
    _cloner = getattr(principal, "email", None) or getattr(principal, "user_id", None) or "unknown"
    skill_versions.record_version(
        dst,
        skill_md=(skill_file.read_text(encoding="utf-8") if skill_file.exists() else ""),
        tool_scripts=_clone_tools,
        author=_cloner,
        email=getattr(principal, "email", "") or "",
        action="create",
        note=f"Cloned from {skill_name}",
        make_active=True,
    )

    index_path = skills_path / "_index.yaml"
    _new_name = req.new_name
    _src_skill = skill_name
    def _add_clone(index: dict) -> dict:
        src_entry = index.get("skills", {}).get(_src_skill, {})
        index.setdefault("skills", {})[_new_name] = {
            "description": src_entry.get("description", f"Clone of {_src_skill}"),
            "keywords": src_entry.get("keywords", []),
            "status": "draft",
        }
        return index
    await locked_rmw_yaml(index_path, _add_clone)
    _invalidate_skills_cache()

    return {"message": f"Cloned '{skill_name}' → '{req.new_name}'", "path": str(dst)}


@router.patch("/api/skills/{skill_name}/status")
async def update_skill_status(request: Request, skill_name: str, req: SkillStatusUpdate, admin: dict = Depends(require_admin)):
    """Update the lifecycle status of a skill."""
    enforce_entitlement(principal_from_request(request), "manage", "skill", skill_name)
    valid = {"draft", "active", "deprecated"}
    if req.status not in valid:
        raise HTTPException(400, f"Status must be one of: {valid}")

    skills_path = SERVER_DIR / SKILLS_PATH
    if not (skills_path / skill_name).exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    index_path = skills_path / "_index.yaml"
    _sname, _sstatus = skill_name, req.status
    def _set_status(index: dict) -> dict:
        index.setdefault("version", "1.0")
        index.setdefault("skills", {}).setdefault(_sname, {})["status"] = _sstatus
        return index
    await locked_rmw_yaml(index_path, _set_status)
    # draft->active is the approve path: bust the cache and reload routers so Auto-route sees it.
    _invalidate_skills_cache()

    return {"message": f"Status of '{skill_name}' → {req.status}", "status": req.status}


@router.get("/api/skills/{skill_name}/knowledge")
async def list_knowledge_files(skill_name: str, user: dict = Depends(require_auth)):
    """List all knowledge files for a skill."""
    skills_path = SERVER_DIR / SKILLS_PATH
    knowledge_dir = skills_path / skill_name / "knowledge"
    if not knowledge_dir.exists():
        return {"files": []}
    files = []
    for f in sorted(knowledge_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            stat = f.stat()
            files.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "ext": f.suffix.lower(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "status": "available",
            })
    return {"files": files}


@router.post("/api/skills/{skill_name}/knowledge/upload")
async def upload_knowledge_file(request: Request, skill_name: str, file: UploadFile = File(...), user: dict = Depends(require_auth)):
    """Upload a knowledge file to a skill's knowledge/ directory."""
    enforce_entitlement(principal_from_request(request), "write", "context", f"{skill_name}/{file.filename}")
    skills_path = SERVER_DIR / SKILLS_PATH
    skill_dir = skills_path / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    ext = PurePosixPath(file.filename).suffix.lower()
    if ext not in ALLOWED_KNOWLEDGE_EXTS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_KNOWLEDGE_EXTS))}")

    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    knowledge_dir = skill_dir / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10 MB)")
    dest = knowledge_dir / safe_name
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".tmp") as _f:
        _f.write(content); _tmp = _f.name
    os.replace(_tmp, str(dest))

    return {
        "message": f"Uploaded '{safe_name}' to {skill_name}/knowledge/",
        "filename": safe_name,
        "size_bytes": len(content),
        "ext": ext,
        "modified_at": datetime.fromtimestamp(dest.stat().st_mtime).isoformat(),
        "status": "available",
    }


@router.delete("/api/skills/{skill_name}/knowledge/{filename}")
async def delete_knowledge_file(request: Request, skill_name: str, filename: str, admin: dict = Depends(require_permission("knowledge.write"))):
    """Delete a knowledge file from a skill."""
    enforce_entitlement(principal_from_request(request), "delete", "context", f"{skill_name}/{filename}")
    skills_path = SERVER_DIR / SKILLS_PATH
    file_path = skills_path / skill_name / "knowledge" / filename
    if not file_path.exists():
        raise HTTPException(404, f"File '{filename}' not found")
    file_path.unlink()
    return {"message": f"Deleted '{filename}'"}


@router.post("/api/skills/tools/validate")
async def validate_tool_script(req: ToolScriptValidateRequest, user: dict = Depends(require_auth)):
    """
    Validate a Python tool script:
      1. Syntax check via ast.parse
      2. Check for TOOL_SPEC dict with required keys (name, description, params)
    Returns {valid, errors, tool_spec}.
    """
    errors = []
    tool_spec = None

    if not req.filename.endswith(".py"):
        errors.append("Filename must end with .py")
    if "/" in req.filename or "\\" in req.filename:
        errors.append("Filename must not contain path separators")

    try:
        tree = ast.parse(req.content)
    except SyntaxError as e:
        errors.append(f"SyntaxError at line {e.lineno}: {e.msg}")
        return {"valid": False, "errors": errors, "tool_spec": None}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TOOL_SPEC":
                    try:
                        spec_val = ast.literal_eval(node.value)
                        if isinstance(spec_val, dict):
                            tool_spec = spec_val
                    except (ValueError, TypeError):
                        errors.append("TOOL_SPEC found but could not be evaluated as a literal dict")

    if tool_spec is None:
        errors.append("No TOOL_SPEC dict found — tool scripts must define TOOL_SPEC = {name, description, parameters}")
    else:
        for key in ("name", "description"):
            if key not in tool_spec:
                errors.append(f"TOOL_SPEC missing required key: '{key}'")
        if "parameters" not in tool_spec and "params" not in tool_spec:
            errors.append("TOOL_SPEC missing required key: 'parameters'")
        # Normalise: if 'params' present but not 'parameters', copy it
        if tool_spec and "params" in tool_spec and "parameters" not in tool_spec:
            tool_spec["parameters"] = tool_spec.pop("params")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "tool_spec": tool_spec,
    }



# Only what a script needs to start and reach the network through the corporate proxy.
# API keys, DB passwords and signing secrets in the server's environment are NOT passed on.
_TOOL_TEST_ENV_KEYS = (
    "PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE",
)


def _tool_test_env() -> dict:
    return {k: os.environ[k] for k in _TOOL_TEST_ENV_KEYS if k in os.environ}


@router.post("/api/skills/tools/test-run")
async def test_run_tool_script(req: ToolScriptTestRunRequest, user: dict = Depends(require_admin)):
    """
    Execute a Python tool script in a subprocess with test_input piped as JSON
    to stdin.  Returns {success, stdout, stderr, elapsed_ms}.

    This runs caller-supplied code, so it is admin-only, refused outright when the
    untrusted-execution guard is on (the same posture that blocks python3 for the
    agent), and run with a minimal environment so server secrets are not inherited.
    Safety: 30-second timeout, 10 KB stdout cap, runs in a temp directory.
    """
    if AGENTOS_UNTRUSTED_EXECUTION_GUARD:
        raise HTTPException(
            status_code=403,
            detail="Tool test-run is disabled: AGENTOS_UNTRUSTED_EXECUTION_GUARD is on for this server.",
        )
    TIMEOUT_S = 30
    STDOUT_CAP = 10_240  # 10 KB

    # Quick syntax gate — don't waste a subprocess on broken code
    try:
        ast.parse(req.content)
    except SyntaxError as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"SyntaxError at line {e.lineno}: {e.msg}",
            "elapsed_ms": 0,
        }

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, prefix="iaf_tool_",
        ) as tmp:
            tmp.write(req.content)
            tmp_path = tmp.name

        input_json = json.dumps(req.test_input)
        start = _time_mod.time()

        _sp_kwargs: dict = {}
        if sys.platform == "win32":
            _sp_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, tmp_path],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=_tool_test_env(),
            cwd=os.path.dirname(tmp_path),
            **_sp_kwargs,
        )

        elapsed_ms = round((_time_mod.time() - start) * 1000)
        stdout = proc.stdout[:STDOUT_CAP] if proc.stdout else ""
        stderr = proc.stderr[:STDOUT_CAP] if proc.stderr else ""

        return {
            "success": proc.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_ms": elapsed_ms,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Script exceeded {TIMEOUT_S}s timeout",
            "elapsed_ms": TIMEOUT_S * 1000,
        }
    except Exception as e:
        logger.exception("Tool test-run failed before/after subprocess execution")
        return {
            "success": False,
            "stdout": "",
            "stderr": "Internal error while running the script",
            "elapsed_ms": 0,
        }
    finally:
        # Always clean up temp file
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _build_skill_md(skill: SkillCreate) -> str:
    """Build SKILL.md content from skill model."""
    import yaml as yaml_lib

    frontmatter = {
        "name": skill.name,
        "version": skill.version or "1.0",
        "description": skill.description,
    }

    if skill.keywords:
        frontmatter["triggers"] = skill.keywords

    if skill.tools:
        frontmatter["tools"] = skill.tools

    if skill.business_context:
        frontmatter["business_context"] = skill.business_context

    if skill.connections:
        frontmatter["connections"] = [c.dict() for c in skill.connections]

    if skill.mcp_connections:
        frontmatter["mcp_connections"] = skill.mcp_connections
    if skill.mcp_tools:
        frontmatter["mcp_tools"] = skill.mcp_tools

    if skill.context_file:
        frontmatter["context_file"] = skill.context_file

    # Per-skill knowledge bundles the agent may read (honored at runtime)
    if getattr(skill, "knowledge", None):
        frontmatter["knowledge"] = skill.knowledge

    # Per-skill data-write policy (only emit when non-default to keep SKILL.md clean)
    if getattr(skill, "sql_mode", "read_only") and skill.sql_mode != "read_only":
        frontmatter["sql_mode"] = skill.sql_mode

    if getattr(skill, "approval_rules", None):
        frontmatter["approval_rules"] = skill.approval_rules

    if skill.execution_mode != "react":
        frontmatter["execution_mode"] = skill.execution_mode

    if getattr(skill, "profile", "") and skill.profile != "standard":
        frontmatter["profile"] = skill.profile

    if skill.execution_mode in ["workflow", "parallel"] and skill.steps:
        frontmatter["steps"] = skill.steps

    if skill.execution_mode in ["supervisor", "orchestrator"] and skill.worker_skills:
        frontmatter["worker_skills"] = skill.worker_skills

    # Graph mode: point the loader at the sibling process-graph YAML (written separately).
    if skill.execution_mode == "graph":
        frontmatter["graph_ref"] = getattr(skill, "graph_ref", "") or "graph.yaml"

    if getattr(skill, "category", None):
        frontmatter["category"] = skill.category

    if getattr(skill, "max_steps", None) is not None:
        frontmatter["max_steps"] = skill.max_steps

    yaml_content = yaml_lib.dump(frontmatter, default_flow_style=False, sort_keys=False, allow_unicode=True)

    body = skill.prompt or f"# {skill.name}\n\n{skill.description}"

    return f"---\n{yaml_content}---\n\n{body}\n"


def _read_tool_scripts(skill_dir: Path) -> list:
    """Read all bundled Python tool scripts from skill_dir/tools/."""
    tools_dir = skill_dir / "tools"
    if not tools_dir.is_dir():
        return []

    scripts = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        try:
            scripts.append({
                "filename": py_file.name,
                "content": py_file.read_text(encoding="utf-8"),
            })
        except Exception:
            pass
    return scripts


def _write_tool_scripts(skill_dir: Path, tool_scripts: list):
    """Write bundled Python tool scripts to skill_dir/tools/."""
    if not tool_scripts:
        return

    tools_dir = skill_dir / "tools"
    tools_dir.mkdir(exist_ok=True)

    # Keep track of incoming filenames
    incoming = set()
    for ts in tool_scripts:
        fname = ts.filename if hasattr(ts, "filename") else ts.get("filename", "")
        content = ts.content if hasattr(ts, "content") else ts.get("content", "")
        if not fname or not content:
            continue
        # Sanitise: only allow simple filenames ending with .py
        if "/" in fname or "\\" in fname or not fname.endswith(".py"):
            continue
        incoming.add(fname)
        atomic_write_text(tools_dir / fname, content)

    for existing in tools_dir.glob("*.py"):
        if existing.name.startswith("__"):
            continue
        if existing.name not in incoming:
            existing.unlink()


async def _update_index_yaml(skills_path: Path, name: str, description: str, keywords: List[str], category: str = None):
    """Update _index.yaml with skill entry — locked RMW, cross-process safe."""
    index_path = skills_path / "_index.yaml"

    def _modify(index: dict) -> dict:
        index.setdefault("version", "1.0")
        index.setdefault("default_skill", "general")
        index.setdefault("skills", {})
        existing = index["skills"].get(name, {})
        entry = dict(existing)
        entry["description"] = description
        if keywords:
            entry["keywords"] = keywords
        # Set category: use provided value, fall back to existing, then "platform"
        if category:
            entry["category"] = category
        elif "category" not in entry:
            entry["category"] = "platform"
        index["skills"][name] = entry
        return index

    await locked_rmw_yaml(index_path, _modify)


def _index_yaml_path() -> Path:
    """Absolute path to the live _index.yaml."""
    return (SERVER_DIR / SKILLS_PATH).resolve() / "_index.yaml"


@router.get("/api/registry")
async def get_registry(user: dict = Depends(require_auth)):
    """Read and return parsed _index.yaml."""
    p = _index_yaml_path()
    if not p.exists():
        raise HTTPException(status_code=404, detail="_index.yaml not found")
    raw = p.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw)
    except Exception as e:
        logger.exception("get_registry failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")
    return {"raw": raw, "parsed": parsed}


# Entity types must be snake_case tokens; enforced here whatever client wrote them.
_ENTITY_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_entity_types(entity_types) -> None:
    """Reject a malformed ``entity_types`` value. ``None`` (key absent) is allowed;
    an empty list is allowed here (the UI warns about the routing impact of that)."""
    if entity_types is None:
        return
    if not isinstance(entity_types, list):
        raise HTTPException(status_code=400, detail="entity_types must be a list")
    bad = [et for et in entity_types
           if not isinstance(et, str) or not _ENTITY_TYPE_RE.match(et)]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity type format (use snake_case, e.g. 'server_name'): {bad}",
        )


@router.put("/api/registry")
async def save_registry(request: Request, payload: dict, admin: dict = Depends(require_admin)):
    """Write full _index.yaml from payload.raw (string) or payload.parsed (dict)."""
    enforce_entitlement(principal_from_request(request), "manage", "skill_registry", "_index")
    p = _index_yaml_path()
    if "raw" in payload and payload["raw"]:
        content = payload["raw"]
        try:
            parsed = yaml.safe_load(content)
        except Exception as e:
            logger.exception("save_registry failed")
            raise HTTPException(status_code=400, detail="An internal error occurred")
    elif "parsed" in payload:
        parsed = payload["parsed"]
        content = yaml.dump(parsed, allow_unicode=True, default_flow_style=False, sort_keys=False)
    else:
        raise HTTPException(status_code=400, detail="Provide 'raw' or 'parsed' in body")
    if isinstance(parsed, dict):
        _validate_entity_types(parsed.get("entity_types"))
    atomic_write_text(p, content)
    # A direct _index.yaml write must bust the skills cache and reload routers, or Auto-route uses a stale index.
    _invalidate_skills_cache()
    return {"ok": True, "path": str(p)}
