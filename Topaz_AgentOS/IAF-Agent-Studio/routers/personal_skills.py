"""
IAF Agent Studio — Personal Skills API

Handles per-user personal skill workspace and the central review/approval workflow.

Endpoints:
  GET    /api/personal-skills/{username}                              — list user's personal skills
  POST   /api/personal-skills/{username}/save                        — create/update a personal skill
  GET    /api/personal-skills/{username}/notifications               — list review notifications
  GET    /api/personal-skills/{username}/submissions                 — list user's own submissions
  DELETE /api/personal-skills/{username}/{skill_name}                — delete a personal skill
  POST   /api/personal-skills/{username}/{skill_name}/submit         — submit for central review

  GET    /api/personal-skills/{username}/{skill_name}/skill-md       — read SKILL.md draft
  POST   /api/personal-skills/{username}/{skill_name}/knowledge/upload — upload knowledge file
  GET    /api/personal-skills/{username}/{skill_name}/knowledge      — list knowledge files
  DELETE /api/personal-skills/{username}/{skill_name}/knowledge/{filename} — delete knowledge file
  POST   /api/personal-skills/{username}/{skill_name}/tools/save     — save tool script
  GET    /api/personal-skills/{username}/{skill_name}/tools          — list tool scripts
  DELETE /api/personal-skills/{username}/{skill_name}/tools/{filename} — delete tool script

  GET    /api/skill-submissions                                       — list all submissions (admin)
  POST   /api/skill-submissions/{submission_id}/review               — approve or reject (admin)
"""

import difflib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import yaml
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from shared.config import SERVER_DIR, DATA_ROOT
from shared.models import ToolScript
from shared.file_utils import atomic_write_text, atomic_write_json, atomic_write_yaml, locked_rmw_yaml
from security.dependencies import enforce_entitlement, principal_from_request

logger = logging.getLogger(__name__)
router = APIRouter()

# Allowed extensions and size limit for knowledge files
KNOWLEDGE_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".csv", ".json", ".yaml", ".yml"}
KNOWLEDGE_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def _require_own_or_admin(request: Request, username: str) -> None:
    """Raise 403 if the caller is not the owner of this skill workspace or an admin.
    Admins can access any user's workspace (needed for the review/approval workflow).
    """
    caller = getattr(request.state, "user_id", None)
    role   = getattr(request.state, "role", "user")
    if role == "admin":
        return
    if caller != username:
        raise HTTPException(403, "You can only access your own skill workspace")


def _require_admin(request: Request) -> None:
    """Raise 403 if the caller is not an admin."""
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(403, "Admin access required")


def _enforce(request: Request, action: str, resource_type: str, resource_id: str, tenant_id: str = "company") -> None:
    principal = principal_from_request(request, fallback_tenant=tenant_id)
    enforce_entitlement(principal, action, resource_type, resource_id)


def _enterprise_root() -> Path:
    """Resolve the enterprise_root directory."""
    return (SERVER_DIR / DATA_ROOT).resolve()


def _personal_skills_path(tenant_id: str, username: str) -> Path:
    """Path to a user's personal skills folder.

    Matches the kernel's /me/ path resolution:
      /me/skills/ → agents/enterprise_agent/users/{user_id}/skills/
    """
    return _enterprise_root() / "tenants" / tenant_id / "agents" / "enterprise_agent" / "users" / username / "skills"


def _submissions_path(tenant_id: str) -> Path:
    """Path to the shared skill submissions queue."""
    return _enterprise_root() / "tenants" / tenant_id / "shared" / "skill_submissions"


def _graph_filename(skill_md: Path) -> str:
    """Bare graph filename declared by a SKILL.md's ``graph_ref`` (default graph.yaml).

    Reduced to a single path component so it can never traverse out of the skill
    folder; ``.``/``..``/empty fall back to the default.
    """
    graph_ref = "graph.yaml"
    try:
        _parts = skill_md.read_text(encoding="utf-8").split("---", 2)
        if len(_parts) >= 3:
            graph_ref = (yaml.safe_load(_parts[1]) or {}).get("graph_ref") or "graph.yaml"
    except Exception:
        graph_ref = "graph.yaml"
    name = Path(str(graph_ref)).name
    return name if name not in ("", ".", "..") else "graph.yaml"


def _global_skills_path() -> Path:
    """Path to the central production skills folder (reads SKILLS_PATH env var)."""
    from shared.config import SKILLS_PATH
    return (SERVER_DIR / SKILLS_PATH).resolve()


class SavePersonalSkillRequest(BaseModel):
    skill_name: str
    skill_md_content: str                      # Full SKILL.md text
    component_html: Optional[str] = None       # Optional skill-local component.html draft
    source_scope: str = "new"                  # new | shared | personal | submitted | approved
    source_skill_name: str = ""                # shared skill being edited, if any
    tenant_id: str = "company"
    # Bundled Python tool scripts. None => preserve on-disk tools/; [] => remove
    # all; non-empty => replace. (Without this field, tool scripts added in the
    # personal-skill UI were never written to disk.)
    tool_scripts: Optional[List[ToolScript]] = None


class SubmitSkillRequest(BaseModel):
    tenant_id: str = "company"
    notes: Optional[str] = None               # Optional notes from user
    note: Optional[str] = None                # Backward-compat alias for notes
    publish_mode: str = "publish_new"         # publish_new | update_existing
    source_skill_name: str = ""               # existing shared skill to update


class ReviewSkillRequest(BaseModel):
    verdict: str                              # "approved" | "rejected"
    feedback: Optional[str] = None
    tenant_id: str = "company"


class SaveToolScriptRequest(BaseModel):
    filename: str                             # must end in .py
    content: str                              # Python source code
    tenant_id: str = "company"


@router.get("/api/personal-skills/{username}")
async def list_personal_skills(request: Request, username: str, tenant_id: str = "company"):
    """List all personal skills for a user, merged with global scope info."""
    _require_own_or_admin(request, username)
    _enforce(request, "read", "skill", f"personal/{username}/*", tenant_id)
    username = await _reconcile_personal_workspace(request, tenant_id, username)
    personal_path = _personal_skills_path(tenant_id, username)
    index_path = personal_path / "_index.yaml"

    if not personal_path.exists() or not index_path.exists():
        return {"skills": [], "username": username}

    try:
        index = yaml.safe_load(index_path.read_text(encoding='utf-8')) or {}
    except Exception:
        index = {}

    skills = []
    for skill_name, meta in index.get("skills", {}).items():
        skill_dir = personal_path / skill_name
        skills.append({
            "name": skill_name,
            "description": meta.get("description", ""),
            "keywords": meta.get("keywords", []),
            "status": meta.get("status", "active"),
            "scope": meta.get("scope", "personal"),   # personal | submitted | approved
            "source_scope": meta.get("source_scope", "new"),
            "source_skill_name": meta.get("source_skill_name", ""),
            "created_at": meta.get("created_at"),
            "submitted_at": meta.get("submitted_at"),
            "has_skill_md": (skill_dir / "SKILL.md").exists(),
        })

    return {"skills": skills, "username": username}


@router.post("/api/personal-skills/{username}/save")
async def save_personal_skill(request: Request, username: str, req: SavePersonalSkillRequest):
    """
    Save (create or overwrite) a personal skill for a user.
    Writes SKILL.md and updates the user's personal _index.yaml.
    Called by the create_skill agent via curl or directly from the UI.
    """
    _require_own_or_admin(request, username)
    _enforce(request, "write", "skill", f"personal/{username}/{req.skill_name}", req.tenant_id)
    username = await _reconcile_personal_workspace(request, req.tenant_id, username)
    personal_path = _personal_skills_path(req.tenant_id, username)
    skill_dir = personal_path / req.skill_name

    # Validate skill name — alphanumeric + underscores only
    if not req.skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    # Validate tool filenames UP FRONT, before any skill file is written. Otherwise a bad
    # filename 400s inside _sync_tool_scripts only AFTER SKILL.md / component.html have been
    # overwritten, and a brand-new skill is left in an unindexed folder (the index upsert
    # below never runs). Fail the whole save cleanly before touching disk. (round-4 #2)
    if req.tool_scripts is not None:
        _validate_tool_script_filenames(req.tool_scripts)

    skill_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(skill_dir / "SKILL.md", req.skill_md_content)
    if req.component_html is not None:
        component_html = req.component_html.strip()
        if component_html:
            _validate_component_html(component_html)
            atomic_write_text(skill_dir / "component.html", component_html + "\n")
    # Persist bundled tool scripts. None => leave on-disk tools/ untouched.
    if req.tool_scripts is not None:
        _sync_tool_scripts(skill_dir, req.tool_scripts)

    # Parse description, keywords, and category from the frontmatter for the index
    description, keywords = _extract_frontmatter_meta(req.skill_md_content, req.skill_name)
    _category = ""
    if req.skill_md_content.startswith("---"):
        _parts = req.skill_md_content.split("---", 2)
        if len(_parts) >= 3:
            try:
                _category = (yaml.safe_load(_parts[1]) or {}).get("category", "")
            except Exception:
                pass

    index_path = personal_path / "_index.yaml"
    _sname, _desc, _kw = req.skill_name, description, keywords
    def _upsert(index: dict) -> dict:
        index.setdefault("skills", {})
        existing = index["skills"].get(_sname, {})
        entry = {
            "description": _desc,
            "keywords": _kw,
            "status": "active",
            "scope": existing.get("scope", "personal"),
            "created_at": existing.get("created_at", datetime.now().isoformat()),
            "source_scope": req.source_scope or existing.get("source_scope", "new"),
            "source_skill_name": req.source_skill_name or existing.get("source_skill_name", ""),
        }
        if _category:
            entry["category"] = _category
        index["skills"][_sname] = entry
        return index
    await locked_rmw_yaml(index_path, _upsert)

    logger.info("Personal skill saved: %s / %s", username, req.skill_name)
    return {
        "message": f"Saved personal skill '{req.skill_name}' for {username}",
        "path": str(skill_dir / "SKILL.md"),
        "scope": "personal",
    }


@router.get("/api/personal-skills/{username}/{skill_name}/skill-md")
async def get_personal_skill_md(request: Request, username: str, skill_name: str, tenant_id: str = "company"):
    """Read a personal skill's SKILL.md, parsed into the same shape as GET /api/skills/{name}."""
    _require_own_or_admin(request, username)
    _enforce(request, "read", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    username = await _reconcile_personal_workspace(request, tenant_id, username)
    skill_dir = _personal_skills_path(tenant_id, username) / skill_name
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise HTTPException(404, f"Personal skill '{skill_name}' not found for {username}")

    content = skill_file.read_text(encoding="utf-8")

    frontmatter: dict = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()

    tool_scripts = []
    tools_dir = skill_dir / "tools"
    if tools_dir.is_dir():
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            try:
                tool_scripts.append({"filename": py_file.name, "content": py_file.read_text(encoding="utf-8")})
            except Exception:
                pass

    # Return the draft's saved component so the editor can hydrate it on reopen. Without this
    # the editor falls back to a default template and an unrelated save overwrites the real
    # component.html (its only copy). None => no component saved. (round-4 #4)
    component_html = None
    component_file = skill_dir / "component.html"
    if component_file.exists():
        try:
            component_html = component_file.read_text(encoding="utf-8")
        except Exception:
            component_html = None

    return {
        "name": frontmatter.get("name", skill_name),
        "description": frontmatter.get("description", ""),
        "version": frontmatter.get("version", "1.0"),
        "component_html": component_html,
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
        "tool_scripts": tool_scripts,
        "prompt": body,
        "raw_content": content,
        "category": frontmatter.get("category", ""),
        "max_steps": frontmatter.get("max_steps", None),
    }


@router.get("/api/personal-skills/{username}/notifications")
async def list_personal_skill_notifications(
    request: Request,
    username: str,
    tenant_id: str = "company",
    limit: int = 20,
):
    """List review notifications written for a user's personal skills."""
    _require_own_or_admin(request, username)
    _enforce(request, "read", "skill", f"personal/{username}/*", tenant_id)
    fs_user = await _reconcile_personal_workspace(request, tenant_id, username)
    notifications_dir = _personal_skills_path(tenant_id, fs_user) / "notifications"
    if not notifications_dir.exists():
        return {"notifications": [], "username": username}

    notifications = []
    for notif_file in sorted(notifications_dir.glob("*.json"), reverse=True):
        try:
            notification = json.loads(notif_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        notifications.append({
            **notification,
            "id": notif_file.stem,
        })
        if len(notifications) >= max(1, min(limit, 100)):
            break

    return {"notifications": notifications, "username": username}


@router.get("/api/personal-skills/{username}/submissions")
async def list_user_skill_submissions(request: Request, username: str, tenant_id: str = "company"):
    """
    List all skill submissions belonging to this user with their current status and feedback.
    Reads from the skill_submissions folder, filtering by username in the folder name
    pattern: {skill}__{username}__{timestamp}.
    """
    _require_own_or_admin(request, username)
    _enforce(request, "read", "skill", f"personal/{username}/*", tenant_id)
    submissions_root = _submissions_path(tenant_id)
    if not submissions_root.exists():
        return {"submissions": [], "username": username}

    submissions = []
    for sub_dir in sorted(submissions_root.iterdir(), reverse=True):
        if not sub_dir.is_dir():
            continue

        # Filter by username using folder name pattern: {skill}__{username}__{ts}
        parts = sub_dir.name.split("__", 2)
        if len(parts) < 3 or parts[1] != username:
            continue

        meta_file = sub_dir / "submission.json"
        if not meta_file.exists():
            continue

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        review_obj = {}
        review_file = sub_dir / "review.json"
        if review_file.exists():
            try:
                review_obj = json.loads(review_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        submissions.append({
            "submission_id": meta.get("submission_id", sub_dir.name),
            "skill_name": meta.get("skill_name", ""),
            "submitted_at": meta.get("submitted_at"),
            "status": meta.get("status", "pending"),
            "publish_mode": meta.get("publish_mode", "publish_new"),
            "notes": meta.get("notes", ""),
            "feedback": review_obj.get("feedback", ""),
            "reviewed_at": review_obj.get("reviewed_at", ""),
            "reviewed_by": review_obj.get("reviewed_by", ""),
        })

    return {"submissions": submissions, "username": username}


@router.delete("/api/personal-skills/{username}/{skill_name}")
async def delete_personal_skill(request: Request, username: str, skill_name: str, tenant_id: str = "company"):
    """Delete a personal skill and remove from index."""
    _require_own_or_admin(request, username)
    _enforce(request, "delete", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")
    # Filesystem key is canonical; the submission TAG prefix below stays the request
    # username so cancelling pending submissions keys off the same tag `submit` wrote.
    fs_user = await _reconcile_personal_workspace(request, tenant_id, username)
    personal_path = _personal_skills_path(tenant_id, fs_user)
    skill_dir = personal_path / skill_name

    if not skill_dir.exists():
        raise HTTPException(404, f"Personal skill '{skill_name}' not found for {username}")

    shutil.rmtree(skill_dir)

    index_path = personal_path / "_index.yaml"
    if index_path.exists():
        _del = skill_name
        def _remove(index: dict) -> dict:
            index.get("skills", {}).pop(_del, None)
            return index
        await locked_rmw_yaml(index_path, _remove)

    # Cancel any pending submissions for this skill so they disappear from the admin queue
    submissions_root = _submissions_path(tenant_id)
    if submissions_root.exists():
        prefix = f"{skill_name}__{username}__"
        for sub_dir in submissions_root.iterdir():
            if not sub_dir.is_dir() or not sub_dir.name.startswith(prefix):
                continue
            meta_file = sub_dir / "submission.json"
            if not meta_file.exists():
                continue
            try:
                sub_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if sub_meta.get("status") == "pending":
                    sub_meta["status"] = "cancelled"
                    atomic_write_json(meta_file, sub_meta)
                    logger.info("Cancelled pending submission %s (skill deleted)", sub_dir.name)
            except Exception:
                pass

    return {"message": f"Deleted personal skill '{skill_name}'"}


@router.post("/api/personal-skills/{username}/{skill_name}/submit")
async def submit_skill_for_review(request: Request, username: str, skill_name: str, req: SubmitSkillRequest):
    """
    Submit a personal skill to the central review queue.
    Copies the skill to shared/skill_submissions/ and notifies admins.
    """
    _require_own_or_admin(request, username)
    _enforce(request, "submit", "skill", f"personal/{username}/{skill_name}", req.tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")
    # Copy the submission FROM the canonical workspace folder; the submission_id tag and
    # submitted_by below keep the request username (identity is separate from the fs key).
    fs_user = await _reconcile_personal_workspace(request, req.tenant_id, username)
    personal_path = _personal_skills_path(req.tenant_id, fs_user)
    skill_dir = personal_path / skill_name
    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        raise HTTPException(404, f"Personal skill '{skill_name}' not found")

    # Block publish_new submissions when a global skill with the same name already exists.
    # The user should use the "Propose Update" flow instead.
    publish_mode_req = req.publish_mode if req.publish_mode in ("publish_new", "update_existing") else "publish_new"
    if publish_mode_req == "publish_new":
        global_skill_dir = _global_skills_path() / skill_name
        if global_skill_dir.exists():
            raise HTTPException(
                409,
                f"A global skill named '{skill_name}' already exists. "
                "Open that skill and use 'Propose Update' to submit your changes for review."
            )

    # Resolve notes — prefer "notes", fall back to backward-compat "note"
    notes = req.notes if req.notes is not None else (req.note or "")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    submission_id = f"{skill_name}__{username}__{timestamp}"
    submissions_root = _submissions_path(req.tenant_id)
    submission_dir = submissions_root / submission_id
    submission_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(skill_file, submission_dir / "SKILL.md")
    component_file = skill_dir / "component.html"
    if component_file.exists():
        shutil.copy(component_file, submission_dir / "component.html")
    # Snapshot the graph file named by graph_ref (jailed to a bare filename), not a hard-coded graph.yaml.
    graph_name = _graph_filename(skill_file)
    graph_file = skill_dir / graph_name
    if graph_file.is_file():
        shutil.copy(graph_file, submission_dir / graph_name)
    # Snapshot knowledge/ and tools/ at submit time so approval uses a consistent state
    for subfolder in ("knowledge", "tools"):
        src = skill_dir / subfolder
        if src.exists() and src.is_dir():
            shutil.copytree(src, submission_dir / subfolder, dirs_exist_ok=True)

    personal_index = {}
    index_path = personal_path / "_index.yaml"
    if index_path.exists():
        try:
            personal_index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        except Exception:
            personal_index = {}
    skill_meta = personal_index.get("skills", {}).get(skill_name, {})
    publish_mode = req.publish_mode
    source_skill_name = req.source_skill_name or skill_meta.get("source_skill_name", "")
    if publish_mode not in ("publish_new", "update_existing"):
        publish_mode = "publish_new"
    if not source_skill_name and skill_meta.get("source_scope") == "shared":
        source_skill_name = skill_name
    if publish_mode == "update_existing" and not source_skill_name:
        source_skill_name = skill_name

    submission_meta = {
        "submission_id": submission_id,
        "skill_name": skill_name,
        "submitted_by": username,
        "submitted_by_email": getattr(request.state, "email", None) or username,
        "submitted_at": datetime.now().isoformat(),
        "notes": notes,
        "status": "pending",
        "publish_mode": publish_mode,
        "source_skill_name": source_skill_name,
    }
    atomic_write_json(submission_dir / "submission.json", submission_meta)

    if index_path.exists():
        _sub = skill_name
        def _mark_submitted(index: dict) -> dict:
            if _sub in index.get("skills", {}):
                index["skills"][_sub]["scope"] = "submitted"
                index["skills"][_sub]["submitted_at"] = datetime.now().isoformat()
                index["skills"][_sub]["publish_mode"] = publish_mode
                index["skills"][_sub]["source_skill_name"] = source_skill_name
            return index
        await locked_rmw_yaml(index_path, _mark_submitted)

    logger.info("Skill submitted for review: %s by %s (id=%s)", skill_name, username, submission_id)
    return {
        "message": f"Skill '{skill_name}' submitted for review",
        "submission_id": submission_id,
        "status": "pending",
    }


@router.post("/api/personal-skills/{username}/{skill_name}/knowledge/upload")
async def upload_personal_skill_knowledge(
    request: Request,
    username: str,
    skill_name: str,
    file: UploadFile = File(...),
    tenant_id: str = "company",
):
    """Upload a knowledge file to a personal skill's knowledge/ folder. Max 10 MB."""
    _require_own_or_admin(request, username)
    _enforce(request, "write", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    filename = file.filename or ""
    if not filename or not _safe_filename(filename):
        raise HTTPException(400, "Invalid filename")
    ext = Path(filename).suffix.lower()
    if ext not in KNOWLEDGE_ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(KNOWLEDGE_ALLOWED_EXTENSIONS))}",
        )

    try:
        content = await file.read()
    finally:
        await file.close()
    if len(content) > KNOWLEDGE_MAX_SIZE:
        raise HTTPException(413, "File exceeds 10 MB limit")

    fs_user = await _reconcile_personal_workspace(request, tenant_id, username)
    skill_dir = _personal_skills_path(tenant_id, fs_user) / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Personal skill '{skill_name}' not found for {username}")

    knowledge_dir = skill_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    dest = knowledge_dir / filename
    # Atomic write: unique temp name per upload to avoid concurrent-upload corruption
    tmp = dest.with_name(dest.name + f".{datetime.now().strftime('%Y%m%d%H%M%S%f')}.tmp")
    tmp.write_bytes(content)
    tmp.replace(dest)

    logger.info("Knowledge file uploaded: %s / %s / knowledge / %s", username, skill_name, filename)
    return {"filename": filename, "size": len(content)}


@router.get("/api/personal-skills/{username}/{skill_name}/knowledge")
async def list_personal_skill_knowledge(
    request: Request,
    username: str,
    skill_name: str,
    tenant_id: str = "company",
):
    """List knowledge files in a personal skill's knowledge/ folder."""
    _require_own_or_admin(request, username)
    _enforce(request, "read", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    fs_user = await _reconcile_personal_workspace(request, tenant_id, username)
    knowledge_dir = _personal_skills_path(tenant_id, fs_user) / skill_name / "knowledge"
    if not knowledge_dir.exists():
        return {"files": [], "skill_name": skill_name}

    files = []
    for f in sorted(knowledge_dir.iterdir()):
        if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".tmp"):
            stat = f.stat()
            files.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "ext": f.suffix.lower(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "status": "available",
            })
    return {"files": files, "skill_name": skill_name}


@router.delete("/api/personal-skills/{username}/{skill_name}/knowledge/{filename}")
async def delete_personal_skill_knowledge(
    request: Request,
    username: str,
    skill_name: str,
    filename: str,
    tenant_id: str = "company",
):
    """Delete a knowledge file from a personal skill's knowledge/ folder."""
    _require_own_or_admin(request, username)
    _enforce(request, "delete", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")
    if not filename or not _safe_filename(filename):
        raise HTTPException(400, "Invalid filename")

    fs_user = await _reconcile_personal_workspace(request, tenant_id, username)
    target = _personal_skills_path(tenant_id, fs_user) / skill_name / "knowledge" / filename
    if not target.exists():
        raise HTTPException(404, f"Knowledge file '{filename}' not found")

    target.unlink()
    logger.info("Knowledge file deleted: %s / %s / knowledge / %s", username, skill_name, filename)
    return {"message": f"Deleted knowledge file '{filename}'"}


@router.post("/api/personal-skills/{username}/{skill_name}/tools/save")
async def save_personal_skill_tool(
    request: Request,
    username: str,
    skill_name: str,
    req: SaveToolScriptRequest,
):
    """Save a Python tool script to a personal skill's tools/ folder."""
    _require_own_or_admin(request, username)
    _enforce(request, "write", "skill", f"personal/{username}/{skill_name}", req.tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    filename = req.filename
    if not filename or not _safe_filename(filename):
        raise HTTPException(400, "Invalid filename")
    if not filename.endswith(".py"):
        raise HTTPException(400, "Tool script filename must end in .py")

    username = await _reconcile_personal_workspace(request, req.tenant_id, username)
    skill_dir = _personal_skills_path(req.tenant_id, username) / skill_name
    if not skill_dir.exists():
        raise HTTPException(404, f"Personal skill '{skill_name}' not found for {username}")

    tools_dir = skill_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    dest = tools_dir / filename
    atomic_write_text(dest, req.content)

    logger.info("Tool script saved: %s / %s / tools / %s", username, skill_name, filename)
    return {"filename": filename, "size": len(req.content.encode("utf-8"))}


@router.get("/api/personal-skills/{username}/{skill_name}/tools")
async def list_personal_skill_tools(
    request: Request,
    username: str,
    skill_name: str,
    tenant_id: str = "company",
):
    """List Python tool scripts in a personal skill's tools/ folder."""
    _require_own_or_admin(request, username)
    _enforce(request, "read", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    username = await _reconcile_personal_workspace(request, tenant_id, username)
    tools_dir = _personal_skills_path(tenant_id, username) / skill_name / "tools"
    if not tools_dir.exists():
        return {"files": [], "skill_name": skill_name}

    files = []
    for f in sorted(tools_dir.iterdir()):
        if f.is_file() and f.suffix == ".py":
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                content = ""
            files.append({"filename": f.name, "content": content})
    return {"files": files, "skill_name": skill_name}


@router.delete("/api/personal-skills/{username}/{skill_name}/tools/{filename}")
async def delete_personal_skill_tool(
    request: Request,
    username: str,
    skill_name: str,
    filename: str,
    tenant_id: str = "company",
):
    """Delete a tool script from a personal skill's tools/ folder."""
    _require_own_or_admin(request, username)
    _enforce(request, "delete", "skill", f"personal/{username}/{skill_name}", tenant_id)
    if not skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")
    if not filename or not _safe_filename(filename):
        raise HTTPException(400, "Invalid filename")
    if not filename.endswith(".py"):
        raise HTTPException(400, "Only .py tool scripts can be deleted via this endpoint")

    username = await _reconcile_personal_workspace(request, tenant_id, username)
    target = _personal_skills_path(tenant_id, username) / skill_name / "tools" / filename
    if not target.exists():
        raise HTTPException(404, f"Tool script '{filename}' not found")

    target.unlink()
    logger.info("Tool script deleted: %s / %s / tools / %s", username, skill_name, filename)
    return {"message": f"Deleted tool script '{filename}'"}


@router.get("/api/skill-submissions")
async def list_skill_submissions(request: Request, tenant_id: str = "company", status: str = "all"):
    """
    List all skill submissions for admin review.
    status filter: all | pending | approved | rejected
    """
    _require_admin(request)
    _enforce(request, "review", "skill_submission", "*", tenant_id)
    submissions_root = _submissions_path(tenant_id)
    if not submissions_root.exists():
        return {"submissions": []}

    submissions = []
    for sub_dir in sorted(submissions_root.iterdir(), reverse=True):
        if not sub_dir.is_dir():
            continue

        meta_file = sub_dir / "submission.json"
        if not meta_file.exists():
            continue

        try:
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            continue

        # Apply status filter — cancelled items are never shown unless explicitly requested
        sub_status = meta.get("status", "pending")
        if sub_status == "cancelled" and status != "cancelled":
            continue
        if status not in ("all", "cancelled") and sub_status != status:
            continue

        review_file = sub_dir / "review.json"
        review = {}
        if review_file.exists():
            try:
                review = json.loads(review_file.read_text(encoding='utf-8'))
            except Exception:
                pass

        submissions.append({
            **meta,
            "review": review,
            "has_skill_md": (sub_dir / "SKILL.md").exists(),
            "has_component": (sub_dir / "component.html").exists(),
        })

    return {"submissions": submissions, "count": len(submissions)}


@router.get("/api/skill-submissions/{submission_id}/skill-md")
async def get_submission_skill_md(request: Request, submission_id: str, tenant_id: str = "company"):
    """Get the SKILL.md content for a specific submission (for admin preview)."""
    _require_admin(request)
    _validate_submission_id(submission_id)
    _enforce(request, "review", "skill_submission", submission_id, tenant_id)
    sub_dir = _submissions_path(tenant_id) / submission_id
    skill_file = sub_dir / "SKILL.md"

    if not skill_file.exists():
        raise HTTPException(404, f"Submission '{submission_id}' not found")

    return {"submission_id": submission_id, "content": skill_file.read_text(encoding='utf-8')}


@router.get("/api/skill-submissions/{submission_id}/preview")
async def preview_skill_submission(request: Request, submission_id: str, tenant_id: str = "company"):
    """Preview publish impact before approving a submitted personal skill."""
    _require_admin(request)
    _validate_submission_id(submission_id)
    _enforce(request, "review", "skill_submission", submission_id, tenant_id)
    return _build_submission_preview(tenant_id, submission_id)


@router.post("/api/skill-submissions/{submission_id}/review")
async def review_skill_submission(request: Request, submission_id: str, req: ReviewSkillRequest):
    _require_admin(request)
    _validate_submission_id(submission_id)
    _enforce(request, "review", "skill_submission", submission_id, req.tenant_id)
    """
    Admin approves or rejects a submitted skill.

    On approval: copies SKILL.md to central IAF-Agent-Skills/skills/ and
    appends the entry to the global _index.yaml so it's immediately available
    to all users. Also copies knowledge/ and tools/ from the submitter's
    personal skill folder if they exist.

    On rejection: records the decision and feedback. The submitter's personal
    skill remains intact for iteration.
    """
    if req.verdict not in ("approved", "rejected"):
        raise HTTPException(400, "verdict must be 'approved' or 'rejected'")
    if req.verdict == "rejected" and not (req.feedback or "").strip():
        raise HTTPException(400, "feedback is required when rejecting a submission")

    sub_dir = _submissions_path(req.tenant_id) / submission_id
    meta_file = sub_dir / "submission.json"
    skill_file = sub_dir / "SKILL.md"

    if not meta_file.exists():
        raise HTTPException(404, f"Submission '{submission_id}' not found")

    meta = json.loads(meta_file.read_text(encoding='utf-8'))
    if meta.get("status") != "pending":
        raise HTTPException(400, f"Submission already reviewed (status: {meta['status']})")

    skill_name = meta["skill_name"]
    submitted_by = meta["submitted_by"]
    # The submitter's FILESYSTEM key may be canonical (email) while the submission tag is
    # the raw username — resolve it so the post-review index + notification writes land in
    # the folder the submitter actually reads from. (admin context → _canonical_fs_user_id,
    # not the owner-only reconcile.)
    fs_submitter = _canonical_fs_user_id(req.tenant_id, submitted_by, meta.get("submitted_by_email") or "")
    preview = _build_submission_preview(req.tenant_id, submission_id)

    review = {
        "reviewed_at": datetime.now().isoformat(),
        "verdict": req.verdict,
        "feedback": req.feedback or "",
        "target_skill_name": preview["target_skill_name"],
        "conflict_strategy": preview["conflict_strategy"],
        "publish_mode": preview["publish_mode"],
    }
    atomic_write_json(sub_dir / "review.json", review)
    meta["status"] = req.verdict
    atomic_write_json(meta_file, meta)

    if req.verdict == "approved":
        global_skills = _global_skills_path()
        skill_name_registered = preview["target_skill_name"]
        target_dir = global_skills / skill_name_registered

        from shared import skill_versions
        try:
            # Keep the original owner of a pre-versioning skill; snapshot its graph file for rollback.
            if (target_dir / "SKILL.md").exists():
                legacy_graph = target_dir / _graph_filename(target_dir / "SKILL.md")
                skill_versions.ensure_migrated(
                    target_dir,
                    graph_files=(
                        {legacy_graph.name: legacy_graph.read_text(encoding="utf-8")}
                        if legacy_graph.is_file() else None
                    ),
                )
        except Exception:
            logger.warning("Could not baseline versions for %s", skill_name_registered, exc_info=True)

        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(skill_file, target_dir / "SKILL.md")
        submitted_component = sub_dir / "component.html"
        if submitted_component.exists():
            shutil.copy(submitted_component, target_dir / "component.html")
        # Promote the graph_skill's DAG alongside its SKILL.md, using the same
        # graph_ref-derived filename the submission snapshotted.
        graph_name = _graph_filename(skill_file)
        submitted_graph = sub_dir / graph_name
        if submitted_graph.is_file():
            shutil.copy(submitted_graph, target_dir / graph_name)

        # Copy knowledge/ and tools/ from the submission snapshot (not the live personal dir)
        for subfolder in ("knowledge", "tools"):
            src = sub_dir / subfolder
            if src.exists() and src.is_dir():
                dest = target_dir / subfolder
                shutil.copytree(src, dest, dirs_exist_ok=True)

        # Record the submitter as owner; must not fail an already-live approval.
        try:
            promoted_graph = target_dir / graph_name
            skill_versions.record_promotion(
                target_dir,
                author=meta.get("submitted_by_email") or submitted_by,
                email=meta.get("submitted_by_email") or "",
                graph_files=(
                    {graph_name: promoted_graph.read_text(encoding="utf-8")}
                    if promoted_graph.is_file() else None
                ),
            )
        except Exception:
            logger.warning("Could not record version for %s", skill_name_registered, exc_info=True)

        # Update global _index.yaml — locked RMW (shared across all users)
        description, keywords = _extract_frontmatter_meta(skill_file.read_text(encoding='utf-8'), skill_name)
        global_index_path = global_skills / "_index.yaml"
        _sreg, _desc, _kw, _by = skill_name_registered, description, keywords, submitted_by
        def _promote(index: dict) -> dict:
            index.setdefault("skills", {})[_sreg] = {
                "description": _desc,
                "keywords": _kw,
                "status": "active",
                "promoted_from": _by,
                "promoted_at": datetime.now().isoformat(),
            }
            return index
        await locked_rmw_yaml(global_index_path, _promote)

        # Bust the /api/skills cache so the newly promoted skill is immediately visible
        try:
            from routers.skills import _invalidate_skills_cache
            _invalidate_skills_cache()
        except Exception:
            pass

        personal_path = _personal_skills_path(req.tenant_id, fs_submitter)
        personal_index_path = personal_path / "_index.yaml"
        if personal_index_path.exists():
            _orig = skill_name
            def _set_approved(index: dict) -> dict:
                if _orig in index.get("skills", {}):
                    index["skills"][_orig]["scope"] = "approved"
                return index
            await locked_rmw_yaml(personal_index_path, _set_approved)

        _write_user_notification(req.tenant_id, fs_submitter, skill_name, "approved", req.feedback)

        logger.info("Skill approved and promoted: %s → global (by admin)", skill_name_registered)
        return {
            "message": f"Approved — '{skill_name_registered}' is now live for all users",
            "verdict": "approved",
            "skill_name": skill_name_registered,
            "target_skill_name": skill_name_registered,
            "published_skill_name": skill_name_registered,
            "conflict_strategy": preview["conflict_strategy"],
            "publish_mode": preview["publish_mode"],
            "publish_url": f"/studio?skill={skill_name_registered}",
        }

    else:
        # Rejected — write notification so user knows
        _write_user_notification(req.tenant_id, fs_submitter, skill_name, "rejected", req.feedback)

        # Update personal index scope back to personal (can iterate and resubmit)
        personal_path = _personal_skills_path(req.tenant_id, fs_submitter)
        personal_index_path = personal_path / "_index.yaml"
        if personal_index_path.exists():
            _rej = skill_name
            def _set_rejected(index: dict) -> dict:
                if _rej in index.get("skills", {}):
                    index["skills"][_rej]["scope"] = "personal"
                return index
            await locked_rmw_yaml(personal_index_path, _set_rejected)

        logger.info("Skill rejected: %s (submitted by %s)", skill_name, submitted_by)
        return {
            "message": f"Rejected — '{skill_name}' returned to {submitted_by}'s workspace",
            "verdict": "rejected",
            "feedback": req.feedback,
            "target_skill_name": preview["target_skill_name"],
            "conflict_strategy": preview["conflict_strategy"],
        }


def _build_submission_preview(tenant_id: str, submission_id: str) -> dict:
    """Build a compact publish preview for an admin review decision."""
    sub_dir = _submissions_path(tenant_id) / submission_id
    meta_file = sub_dir / "submission.json"
    skill_file = sub_dir / "SKILL.md"
    if not meta_file.exists() or not skill_file.exists():
        raise HTTPException(404, f"Submission '{submission_id}' not found")

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    skill_name = meta["skill_name"]
    submitted_by = meta["submitted_by"]
    submitted_content = skill_file.read_text(encoding="utf-8")

    global_skills = _global_skills_path()
    publish_mode = str(meta.get("publish_mode") or "publish_new")
    source_skill_name = str(meta.get("source_skill_name") or "")
    if publish_mode == "update_existing" and not source_skill_name:
        source_skill_name = skill_name
    existing_name = source_skill_name if publish_mode == "update_existing" else skill_name
    existing_skill_file = global_skills / existing_name / "SKILL.md"
    has_conflict = existing_skill_file.exists()
    if publish_mode == "update_existing" and has_conflict:
        target_skill_name = existing_name
        conflict_strategy = "update_existing"
    else:
        target_skill_name = _publish_target_name(global_skills, skill_name, submitted_by)
        conflict_strategy = "namespace_with_submitter" if has_conflict else "publish_as_submitted"

    existing_content = ""
    diff_lines = []
    if has_conflict:
        existing_content = existing_skill_file.read_text(encoding="utf-8")
        diff_lines = list(difflib.unified_diff(
            existing_content.splitlines(),
            submitted_content.splitlines(),
            fromfile=f"global/{existing_name}/SKILL.md",
            tofile=f"submission/{submission_id}/SKILL.md",
            lineterm="",
        ))

    description, keywords = _extract_frontmatter_meta(submitted_content, skill_name)
    return {
        "submission_id": submission_id,
        "skill_name": skill_name,
        "submitted_by": submitted_by,
        "status": meta.get("status", "pending"),
        "publish_mode": publish_mode,
        "source_skill_name": source_skill_name,
        "has_conflict": has_conflict,
        "target_skill_name": target_skill_name,
        "conflict_strategy": conflict_strategy,
        "existing_skill_name": skill_name if has_conflict else None,
        "description": description,
        "keywords": keywords,
        "diff": "\n".join(diff_lines[:240]),
        "diff_truncated": len(diff_lines) > 240,
        "submitted_size_bytes": len(submitted_content.encode("utf-8")),
        "existing_size_bytes": len(existing_content.encode("utf-8")) if has_conflict else 0,
        "has_component": (sub_dir / "component.html").exists(),
    }


def _publish_target_name(global_skills: Path, skill_name: str, submitted_by: str) -> str:
    """Resolve a non-overwriting global skill folder name for an approval."""
    if not (global_skills / skill_name).exists():
        return skill_name
    base = f"{skill_name}__{submitted_by}"
    if not (global_skills / base).exists():
        return base
    counter = 2
    while (global_skills / f"{base}__{counter}").exists():
        counter += 1
    return f"{base}__{counter}"

def _extract_frontmatter_meta(skill_md: str, fallback_name: str) -> tuple:
    """Extract description and keywords from SKILL.md frontmatter."""
    import re
    description = fallback_name
    keywords = []

    fence_match = re.match(r'^[`]{3,4}\w*\s*\n(.*)', skill_md, re.DOTALL)
    if fence_match:
        inner = fence_match.group(1)
        skill_md = re.sub(r'\n[`]{3,4}\s*$', '', inner)

    match = re.match(r'^---\s*\n(.*?)\n---', skill_md, re.DOTALL)
    if match:
        try:
            fm = yaml.safe_load(match.group(1)) or {}
            description = fm.get("description", fallback_name)
            keywords = fm.get("triggers", fm.get("keywords", []))
        except Exception:
            pass

    return description, keywords


def _validate_component_html(html: str) -> None:
    lowered = html.lower()
    if re.search(r"<\s*(script|iframe|object|embed)\b", lowered):
        raise HTTPException(400, "Component HTML cannot include script, iframe, object, or embed tags")
    if re.search(r"\son[a-z]+\s*=", lowered):
        raise HTTPException(400, "Component HTML cannot include inline event handlers")
    if "javascript:" in lowered:
        raise HTTPException(400, "Component HTML cannot include javascript: URLs")


def _validate_submission_id(submission_id: str) -> None:
    """Raise 400 if submission_id contains path-traversal characters."""
    if not re.fullmatch(r"[\w\-]{1,200}", submission_id):
        raise HTTPException(400, "Invalid submission ID")


def _safe_filename(filename: str) -> bool:
    """Return True if the filename is safe — no path traversal characters."""
    p = Path(filename)
    return (
        p.name == filename
        and ".." not in filename
        and "/" not in filename
        and "\\" not in filename
    )


def _validate_tool_script_filenames(tool_scripts) -> None:
    """Raise 400 if any incoming tool-script filename is unsafe or not a ``.py`` file.

    Called BEFORE any skill file is written so an invalid batch fails the save cleanly
    instead of 400-ing after SKILL.md/component.html are already overwritten. ``_sync_tool_scripts``
    repeats the same guard as defence-in-depth. (round-4 #2)
    """
    for ts in tool_scripts or []:
        if isinstance(ts, dict):
            fname = ts.get("filename")
        else:
            fname = getattr(ts, "filename", None)
        fname = (fname or "").strip()
        if not fname or not fname.endswith(".py") or not _safe_filename(fname):
            logger.warning("personal skill: rejecting unsafe tool filename %r", fname)
            raise HTTPException(400, "Tool script filename must be a safe, non-empty .py filename")


def _sync_tool_scripts(skill_dir: Path, tool_scripts) -> None:
    """Persist bundled tool scripts into ``skill_dir/tools/`` and prune removals.

    The caller only invokes this when ``tool_scripts is not None``. ``[]`` clears
    all scripts; a non-empty list is authoritative. Unsafe or non-``.py``
    filenames are rejected (no path traversal) so a payload can never write
    outside ``tools/``.
    """
    tools_dir = Path(skill_dir) / "tools"
    incoming: dict[str, str] = {}
    for ts in tool_scripts or []:
        if isinstance(ts, dict):
            fname, content = ts.get("filename"), ts.get("content")
        else:
            fname, content = getattr(ts, "filename", None), getattr(ts, "content", None)
        fname = (fname or "").strip()
        content = content or ""
        # Reject an invalid entry up front rather than silently dropping it: a non-empty
        # request whose only entries are invalid would otherwise leave ``incoming`` empty
        # and the prune below would delete EVERY existing script (silent data loss). An
        # intentional "remove all" is the distinct ``[]`` case, which has no entries here.
        if not fname or not fname.endswith(".py") or not _safe_filename(fname):
            logger.warning("personal skill: rejecting unsafe tool filename %r", fname)
            raise HTTPException(400, "Tool script filename must be a safe, non-empty .py filename")
        incoming[fname] = content

    if incoming:
        tools_dir.mkdir(parents=True, exist_ok=True)
        for fname, content in incoming.items():
            atomic_write_text(tools_dir / fname, content)

    # Prune any .py no longer present in the incoming set (keeps __init__.py etc.).
    if tools_dir.is_dir():
        for existing in tools_dir.glob("*.py"):
            if existing.name.startswith("__"):
                continue
            if existing.name not in incoming:
                try:
                    existing.unlink()
                except OSError:
                    logger.warning("personal skill: could not prune %s", existing)


# ── Personal-workspace reconciliation ──────────────────────────────────────
# A user's personal folder is keyed by a filesystem id (email or user_id). When
# that key churned (legacy uuid4 provisioning) a user's drafts could land in an
# alternate-key folder and go invisible in the UI. microsoft._stable_user_id now
# stops new churn; the helpers below pull EXISTING alt-key folders into the key
# the UI uses. They only ever COPY — user data is never deleted.
_reconciled_workspaces: dict[str, str] = {}


def _newest_mtime(path: Path) -> float:
    """Most recent mtime anywhere under *path* (0.0 if empty/missing)."""
    newest = 0.0
    try:
        for p in path.rglob("*"):
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    except Exception:
        pass
    return newest


def _merge_index_entries(dst_index: dict, src_index: dict) -> dict:
    """Copy skill entries from *src_index* that *dst_index* lacks (no overwrite)."""
    dst_index.setdefault("skills", {})
    for sname, meta in (src_index.get("skills") or {}).items():
        if sname not in dst_index["skills"]:
            dst_index["skills"][sname] = meta
    return dst_index


async def _merge_personal_dirs(src_skills: Path, dst_skills: Path) -> int:
    """Copy skill folders from *src_skills* into *dst_skills* (copy-only).

    Folders already present in the destination are left authoritative; the
    conflicting source copy is backed up under ``dst/_merged_backup/<ts>/``.
    ``_index.yaml`` entries are merged without overwriting. Returns the number
    of skill folders newly copied in.

    Raises on any copy/backup/index failure so the caller can decline to mark the
    workspace reconciled — a swallowed failure would wrongly block the owner's
    drafts from importing on a later request/restart.
    """
    if not src_skills.is_dir() or src_skills.resolve() == dst_skills.resolve():
        return 0
    dst_skills.mkdir(parents=True, exist_ok=True)
    merged = 0
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for child in src_skills.iterdir():
        if not child.is_dir() or child.name in ("_merged_backup", "notifications"):
            continue
        target = dst_skills / child.name
        if not target.exists():
            # Stage into a temp sibling, then atomically promote. A crash mid-copytree
            # leaves only the dot-prefixed staging dir (never listed as a skill, cleaned
            # on the next run), not a half-populated authoritative target that the next
            # reconciliation would trust and mark .reconciled without repairing. (#5)
            staging = dst_skills / f".{child.name}.tmp-{ts}-{os.getpid()}"
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            try:
                shutil.copytree(child, staging)
                if target.exists():
                    # Lost a concurrent race — keep the existing authoritative copy.
                    shutil.rmtree(staging, ignore_errors=True)
                else:
                    os.replace(staging, target)  # atomic promote (same filesystem)
                    merged += 1
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        else:
            backup = dst_skills / "_merged_backup" / ts / child.name
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(child, backup)

    src_idx_path = src_skills / "_index.yaml"
    dst_idx_path = dst_skills / "_index.yaml"
    if src_idx_path.exists():
        src_idx = yaml.safe_load(src_idx_path.read_text(encoding="utf-8")) or {}
        # Merge through the cross-process lock so a concurrent personal save/delete on
        # the destination index isn't clobbered by this read/merge/write (copy-only:
        # _merge_index_entries never overwrites an existing destination entry).
        await locked_rmw_yaml(dst_idx_path, lambda cur: _merge_index_entries(cur or {}, src_idx))
    return merged


def _canonical_fs_user_id(tenant_id: str, user_id: str, email: str) -> str:
    """The ONE filesystem user key for this principal — the same key chat/SkillAgent
    resolve via coerce_filesystem_user_id, so builder/CRUD and execution act on one
    folder instead of diverging (uid folder vs legacy email folder). Falls back to the
    given user_id if resolution isn't possible (keeps single-tenant/local unchanged)."""
    try:
        from shared.filesystem_identity import coerce_filesystem_user_id
        return coerce_filesystem_user_id(
            user_id=user_id,
            email=email or None,
            data_root=_enterprise_root(),
            tenant_id=tenant_id,
            agent_id="enterprise_agent",
        ) or user_id
    except Exception:
        return user_id


async def _reconcile_personal_workspace(request: Request, tenant_id: str, username: str) -> str:
    """Resolve the canonical personal-workspace key and pull orphaned alt-key folders in.

    Returns the ONE canonical filesystem key (via coerce_filesystem_user_id — the same
    key chat/SkillAgent use), so builder edits, retirement and execution all act on the
    same folder. Only the authenticated OWNER's own workspace is reconciled: alt-key
    folders (the requested key, the principal's email and user_id) are merged into the
    canonical folder, copy-only. A persistent ``.reconciled`` marker — written only after
    a clean pass — makes the merge run at most once, so a later delete/retire isn't undone
    by a restart re-copying an alt-key folder back. An admin viewing ANOTHER user's
    workspace never merges or marks (and isn't cached, so the owner's own later request
    still reconciles). Never raises — on any failure it leaves the workspace unmarked so a
    later request retries, and returns a safe key.
    """
    cache_key = f"{tenant_id}/{username}"
    if cache_key in _reconciled_workspaces:
        return _reconciled_workspaces[cache_key]

    # Identify the principal; only its OWN workspace is reconciled.
    try:
        principal = principal_from_request(request)
        p_email = (getattr(principal, "email", "") or "").strip()
        p_uid = (getattr(principal, "user_id", "") or "").strip()
    except Exception:
        p_email = p_uid = ""

    is_owner = bool(username) and username in (p_email, p_uid)
    if not is_owner:
        # Admin viewing someone else's workspace (or no principal): never merge, mark,
        # or cache — the owner's own later request must still reconcile. BUT still resolve
        # the TARGET user's canonical filesystem key, so admin list/read/delete act on the
        # owner's real folder. Returning the raw key would, after a restart clears the
        # cache, point admin ops at a stale alt-key (e.g. UUID) folder — 404 or the wrong
        # drafts — even though the owner saved under the canonical email key. (#6)
        try:
            # username may be an email or a uid. coerce_filesystem_user_id can resolve an
            # email folder only WITH an email hint — for a UUID-addressed admin request it
            # otherwise can't discover the owner's canonical folder and would fall back to the
            # stale UUID copy. So resolve the target account through the auth provider first to
            # recover its email, then choose the filesystem key. (round-6 #6)
            _email_hint = username if (username and "@" in username) else ""
            if not _email_hint and username:
                try:
                    from auth.factory import get_provider
                    provider = await get_provider()
                    target_user = await provider.get_user(username)
                    _email_hint = (getattr(target_user, "email", "") or "").strip()
                except Exception:
                    _email_hint = ""   # provider lookup unavailable — fall back to raw key resolution
            return _canonical_fs_user_id(tenant_id, username, _email_hint)
        except Exception:
            return username

    canonical = _canonical_fs_user_id(tenant_id, p_uid or username, p_email)
    canonical_cache_key = f"{tenant_id}/{canonical}"
    try:
        dst_skills = _personal_skills_path(tenant_id, canonical)
        marker = dst_skills / ".reconciled"
        # Already reconciled once (survives restarts): skip the merge so a canonical
        # deletion isn't resurrected by re-importing an alt-key folder.
        if marker.exists():
            _reconciled_workspaces[cache_key] = canonical
            _reconciled_workspaces[canonical_cache_key] = canonical
            return canonical

        # Merge every alternate key for THIS principal into the canonical folder.
        alt_keys = {k for k in (username, p_email, p_uid) if k and k != canonical}
        for alt in alt_keys:
            src_skills = _personal_skills_path(tenant_id, alt)
            if src_skills.is_dir():
                n = await _merge_personal_dirs(src_skills, dst_skills)
                if n:
                    logger.info("reconcile: merged %d skill(s) from '%s' into '%s'", n, alt, canonical)

        # Mark + cache ONLY after a clean eligible pass, so a copy/index failure retries
        # on the next request/restart instead of permanently blocking the import.
        dst_skills.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        _reconciled_workspaces[cache_key] = canonical
        _reconciled_workspaces[canonical_cache_key] = canonical
        return canonical
    except Exception as exc:
        # Leave unmarked/uncached so a later request retries; return the canonical key so
        # the request still operates on the execution-aligned folder.
        logger.warning("reconcile: deferred for %s/%s (will retry): %s", tenant_id, canonical, exc)
        return canonical


def _write_user_notification(tenant_id: str, username: str, skill_name: str, verdict: str, feedback: str):
    """Write a notification file to the user's personal folder."""
    personal_path = _personal_skills_path(tenant_id, username)
    notifications_dir = personal_path / "notifications"
    notifications_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    notification = {
        "timestamp": datetime.now().isoformat(),
        "skill_name": skill_name,
        "verdict": verdict,
        "feedback": feedback or "",
        "message": (
            f"Your skill '{skill_name}' was approved and is now live for all users."
            if verdict == "approved"
            else f"Your skill '{skill_name}' was not approved. Feedback: {feedback or 'No feedback provided.'}"
        ),
    }
    notif_file = notifications_dir / f"skill_review_{skill_name}_{timestamp}.json"
    atomic_write_json(notif_file, notification)
