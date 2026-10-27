"""
IAF Agent Studio — File Explorer Router

Direct filesystem access to two locked-down roots:
  - enterprise  →  enterprise_root/
  - skills      →  IAF-Agent-Skills/skills/

Security: every path is resolved and confirmed to stay inside its root.
          Read requires auth. Write/mkdir: any auth user for skills, admin for enterprise.
          Delete/rename: admin only.
"""

from __future__ import annotations

import logging
import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.middleware import require_auth, require_admin, require_permission
from shared.config import DATA_ROOT_PATH, SKILLS_PATH_PATH
from shared.protected_files import is_protected_ext as _is_protected_ext, is_protected_name as _is_protected_name


def _is_protected_target(p: Path) -> bool:
    """Protected regardless of root: the credential store (by basename) and any
    private-key material (by extension). The enterprise root contains
    tenants/<t>/shared/config/credentials.yaml, so this keeps it out of the admin
    explorer's list/read surface for every authenticated caller."""
    return _is_protected_name(p.name) or _is_protected_ext(p.name)

logger = logging.getLogger(__name__)

router = APIRouter()


# Both roots follow the configured mounts (DATA_ROOT / SKILLS_PATH), so the admin File
# Explorer points at the shared-storage location instead of a hardcoded repo-relative path.
_ROOTS: dict[str, Path] = {
    "enterprise": DATA_ROOT_PATH.resolve(),
    "skills":     SKILLS_PATH_PATH.resolve(),
}

_ROOT_LABELS: dict[str, str] = {
    "enterprise": "Enterprise Root",
    "skills":     "Skills Library",
}

_TEXT_EXTS = {
    ".md", ".yaml", ".yml", ".txt", ".json", ".env",
    ".py", ".sh", ".toml", ".cfg", ".ini", ".csv",
}


def _resolve(root_key: str, rel_path: str) -> Path:
    root = _ROOTS.get(root_key)
    if root is None:
        raise HTTPException(status_code=400, detail=f"Unknown root: {root_key!r}")
    clean = rel_path.lstrip("/") if rel_path else ""
    resolved = (root / clean).resolve() if clean else root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    return resolved


def _require_skill_owner_for_write(user: dict, root_key: str, target: Path) -> None:
    """Ownership gate for the Skills Library root.

    The ``skills.author`` capability lets a developer create skills, but it must
    not let them overwrite a skill authored by someone else. Skill CRUD routes
    enforce this; the raw explorer write/mkdir bypassed it (Copilot #3). Admins
    and the skill's own creator are allowed; brand-new paths (no existing skill
    directory) are allowed so authors can still create.
    """
    if root_key != "skills":
        return
    roles = user.get("roles") or [user.get("role")]
    if "admin" in roles:
        return
    skills_root = _ROOTS["skills"]
    try:
        parts = target.resolve().relative_to(skills_root).parts
    except ValueError:
        return
    if not parts:
        return
    skill_dir = skills_root / parts[0]
    # An existing top-level file (e.g. _index.yaml) has no per-skill owner: admin-only overwrite.
    resolved = target.resolve()
    if resolved.exists() and not resolved.is_dir() and resolved.parent == skills_root:
        raise HTTPException(status_code=403, detail="Only an admin can modify skill-library metadata.")
    if not skill_dir.is_dir():
        return  # not inside an existing skill → creating something new is fine
    from shared import skill_versions
    owner = (skill_versions.owner(skill_dir) or "").strip().lower()
    # Skill ownership is an email or user_id; match either.
    callers = {
        (user.get("email") or "").strip().lower(),
        (user.get("user_id") or "").strip().lower(),
    }
    callers.discard("")
    if owner and owner in callers:
        return
    raise HTTPException(
        status_code=403,
        detail=f"Only the owner ({owner or 'an admin'}) or an admin can modify this skill.",
    )


def _entry(root: Path, p: Path) -> dict:
    rel = str(p.relative_to(root)).replace("\\", "/")
    stat = p.stat()
    return {
        "name":  p.name,
        "path":  rel,
        "type":  "directory" if p.is_dir() else "file",
        "ext":   p.suffix.lower() if p.is_file() else "",
        "size":  stat.st_size if p.is_file() else None,
        "mtime": stat.st_mtime,
    }


def _is_text(p: Path) -> bool:
    return p.suffix.lower() in _TEXT_EXTS


def _breadcrumb(root_key: str, rel: str) -> list[dict]:
    crumbs = [{"name": _ROOT_LABELS[root_key], "path": ""}]
    rel = rel.strip("/")
    if rel:
        acc = ""
        for part in rel.split("/"):
            acc = f"{acc}/{part}".lstrip("/")
            crumbs.append({"name": part, "path": acc})
    return crumbs


class WriteBody(BaseModel):
    root: str
    path: str
    content: str

class MkdirBody(BaseModel):
    root: str
    path: str

class DeleteBody(BaseModel):
    root: str
    path: str

class RenameBody(BaseModel):
    root: str
    path: str
    new_name: str


@router.get("/api/explorer/roots")
async def list_roots(user: dict = Depends(require_auth)):
    return [
        {"id": k, "label": _ROOT_LABELS[k], "exists": v.exists()}
        for k, v in _ROOTS.items()
    ]


@router.get("/api/explorer/list")
async def list_dir(
    root: str,
    path: str = "",
    user: dict = Depends(require_auth),
):
    target = _resolve(root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    root_path = _ROOTS[root]
    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name.startswith("."):
                continue
            # Never surface the credential store or key material; skip symlinks so
            # an alias can't smuggle a protected target past this filter.
            if child.is_symlink() or _is_protected_target(child):
                continue
            entries.append(_entry(root_path, child))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {
        "root": root,
        "path": path.strip("/"),
        "entries": entries,
        "breadcrumb": _breadcrumb(root, path),
    }


@router.get("/api/explorer/read")
async def read_file(
    root: str,
    path: str,
    user: dict = Depends(require_auth),
):
    target = _resolve(root, path)
    # Reject protected material and symlinks (the resolved target is what matters,
    # so a symlink alias to credentials.yaml / a key file cannot be read here).
    if target.is_symlink() or _is_protected_target(target) or _is_protected_target(target.resolve()):
        raise HTTPException(status_code=403, detail="This path is protected and cannot be read.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    if not _is_text(target):
        mime, _ = mimetypes.guess_type(str(target))
        return {
            "root": root, "path": path, "text": False,
            "mime": mime or "application/octet-stream",
            "size": target.stat().st_size,
        }

    content = target.read_text(encoding="utf-8", errors="replace")
    return {"root": root, "path": path, "content": content, "text": True, "ext": target.suffix.lower()}


@router.post("/api/explorer/write")
async def write_file(body: WriteBody, user: dict = Depends(require_permission("skills.author"))):
    # Non-authors (plain 'user') are blocked by the dependency above. The
    # enterprise root (config/credentials/policies) stays admin-only.
    if body.root == "enterprise" and "admin" not in (user.get("roles") or [user.get("role")]):
        raise HTTPException(status_code=403, detail="Admin required for enterprise_root")
    target = _resolve(body.root, body.path)
    if target.is_symlink() or _is_protected_target(target):
        raise HTTPException(status_code=403, detail="This path is protected and cannot be written.")
    _require_skill_owner_for_write(user, body.root, target)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    logger.info("explorer write: %s → %s/%s", user.get("email"), body.root, body.path)
    return {"ok": True, "root": body.root, "path": body.path}


@router.post("/api/explorer/mkdir")
async def make_dir(body: MkdirBody, user: dict = Depends(require_permission("skills.author"))):
    # Non-authors (plain 'user') are blocked by the dependency above. The
    # enterprise root (config/credentials/policies) stays admin-only.
    if body.root == "enterprise" and "admin" not in (user.get("roles") or [user.get("role")]):
        raise HTTPException(status_code=403, detail="Admin required for enterprise_root")
    target = _resolve(body.root, body.path)
    _require_skill_owner_for_write(user, body.root, target)
    if target.exists():
        raise HTTPException(status_code=409, detail="Already exists")
    target.mkdir(parents=True, exist_ok=False)
    logger.info("explorer mkdir: %s → %s/%s", user.get("email"), body.root, body.path)
    return {"ok": True, "root": body.root, "path": body.path}


@router.post("/api/explorer/rename")
async def rename_entry(body: RenameBody, admin: dict = Depends(require_admin)):
    target = _resolve(body.root, body.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(status_code=400, detail="new_name must be a plain name")
    # Cannot rename protected material, nor rename anything INTO a protected name.
    if target.is_symlink() or _is_protected_target(target) or _is_protected_target(target.parent / body.new_name):
        raise HTTPException(status_code=403, detail="This path is protected and cannot be renamed.")
    dest = target.parent / body.new_name
    if dest.exists():
        raise HTTPException(status_code=409, detail="Destination already exists")
    target.rename(dest)
    new_rel = str(dest.relative_to(_ROOTS[body.root])).replace("\\", "/")
    logger.info("explorer rename: %s → %s/%s → %s", admin.get("email"), body.root, body.path, new_rel)
    return {"ok": True, "root": body.root, "new_path": new_rel}


@router.delete("/api/explorer/delete")
async def delete_entry(
    root: str,
    path: str,
    admin: dict = Depends(require_admin),
):
    target = _resolve(root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_symlink() or _is_protected_target(target):
        raise HTTPException(status_code=403, detail="This path is protected and cannot be deleted.")
    if target == _ROOTS[root]:
        raise HTTPException(status_code=400, detail="Cannot delete root")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    logger.info("explorer delete: %s → %s/%s", admin.get("email"), root, path)
    return {"ok": True, "root": root, "path": path}


@router.get("/api/explorer/search")
async def search_files(
    root: str,
    q: str,
    content: bool = False,
    user: dict = Depends(require_auth),
):
    """
    Search filenames (and optionally file contents) under a root.
    Returns up to 100 matches.
    """
    root_path = _ROOTS.get(root)
    if root_path is None:
        raise HTTPException(status_code=400, detail=f"Unknown root: {root!r}")
    if not root_path.exists():
        raise HTTPException(status_code=404, detail="Root path not found")

    q_lower = q.lower().strip()
    if not q_lower:
        return {"results": []}

    results = []
    MAX = 100

    for p in root_path.rglob("*"):
        if len(results) >= MAX:
            break
        if any(part.startswith(".") for part in p.parts):
            continue
        # Never return protected material (credential store / key files) or
        # symlinks (whose alias name could mask a protected target).
        if p.is_symlink() or _is_protected_target(p):
            continue

        rel = str(p.relative_to(root_path)).replace("\\", "/")
        name_lower = p.name.lower()

        if p.is_dir():
            if q_lower in name_lower:
                results.append({"type": "directory", "path": rel, "name": p.name, "match": "name"})
            continue

        if q_lower in name_lower:
            results.append({"type": "file", "path": rel, "name": p.name, "match": "name", "ext": p.suffix.lower()})
            continue

        # File — content match (only text files, only when requested)
        if content and _is_text(p):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if q_lower in line.lower():
                        results.append({
                            "type": "file", "path": rel, "name": p.name,
                            "match": "content", "ext": p.suffix.lower(),
                            "line_no": i,
                            "line": line.strip()[:120],
                        })
                        break   # one hit per file
            except Exception:
                pass

    return {"root": root, "query": q, "content_search": content, "results": results}
