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
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from shared.config import SERVER_DIR, DATA_ROOT
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
    personal_path = _personal_skills_path(req.tenant_id, username)
    skill_dir = personal_path / req.skill_name

    # Validate skill name — alphanumeric + underscores only
    if not req.skill_name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Skill name must be alphanumeric with underscores/hyphens only")

    skill_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(skill_dir / "SKILL.md", req.skill_md_content)
    if req.component_html is not None:
        component_html = req.component_html.strip()
        if component_html:
            _validate_component_html(component_html)
            atomic_write_text(skill_dir / "component.html", component_html + "\n")

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
    notifications_dir = _personal_skills_path(tenant_id, username) / "notifications"
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
    personal_path = _personal_skills_path(tenant_id, username)
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
    personal_path = _personal_skills_path(req.tenant_id, username)
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

    skill_dir = _personal_skills_path(tenant_id, username) / skill_name
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

    knowledge_dir = _personal_skills_path(tenant_id, username) / skill_name / "knowledge"
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

    target = _personal_skills_path(tenant_id, username) / skill_name / "knowledge" / filename
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

        personal_path = _personal_skills_path(req.tenant_id, submitted_by)
        personal_index_path = personal_path / "_index.yaml"
        if personal_index_path.exists():
            _orig = skill_name
            def _set_approved(index: dict) -> dict:
                if _orig in index.get("skills", {}):
                    index["skills"][_orig]["scope"] = "approved"
                return index
            await locked_rmw_yaml(personal_index_path, _set_approved)

        _write_user_notification(req.tenant_id, submitted_by, skill_name, "approved", req.feedback)

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
        _write_user_notification(req.tenant_id, submitted_by, skill_name, "rejected", req.feedback)

        # Update personal index scope back to personal (can iterate and resubmit)
        personal_path = _personal_skills_path(req.tenant_id, submitted_by)
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
