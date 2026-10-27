"""
IAF Agent Studio — Skill Pack (import / export) API Router.

Moves skills between instances (e.g. staging → prod) as portable ".skillpack.zip"
archives, so operators no longer re-create skills, tools, scripts and contexts by
hand.

A skill pack is a zip:

    manifest.json                      — pack metadata + per-skill requirements
    skills/<name>/...                  — the full skill folder (SKILL.md, tools/,
                                         hooks/, contexts/, viewers/, component.html…)
    shared/scripts/<path>              — referenced shared scripts (opt-in)
    shared/contexts/<path>             — referenced shared context files (opt-in)
    shared/knowledge/<path>            — referenced shared knowledge (opt-in)

Design rules:
  - Self-contained but SELECTIVE: the caller chooses which skills and which shared
    files travel (analyze → pick → export).
  - Secrets NEVER travel. The pack carries credential *names* + required scope only;
    the manifest reports what the target must configure (credentials, MCP URLs, DBs).
  - Instance-specific bits (MCP urls, api base_urls, DB hosts) are surfaced as
    "requirements" for the operator to remap on the target — never silently applied.
  - Import writes through the same helpers as normal skill creation and merges only
    the skill's own _index.yaml entry (never the whole registry).
  - Zip extraction is path-jailed (zip-slip safe).
"""

import io
import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import List, Optional

import yaml

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.middleware import require_admin
from security.dependencies import enforce_entitlement, principal_from_request
from shared.config import SERVER_DIR, SKILLS_PATH
from shared.file_utils import atomic_write_text
from shared.skill_name_utils import is_valid_skill_folder_name, safe_pack_download_name
from routers.skills import (
    _skill_dir_for_name,
    _update_index_yaml,
    _invalidate_skills_cache,
    _validate_component_html,
)

logger = logging.getLogger(__name__)
router = APIRouter()

PACK_FORMAT = "iaf-skillpack"
PACK_VERSION = 1
_SKIP_DIRS = {"__pycache__", ".git", ".ipynb_checkpoints"}
_SKIP_EXT = {".pyc", ".pyo"}
_MAX_UPLOAD = 50 * 1024 * 1024  # 50 MB (compressed upload)
# Decompression limits (zip-bomb guard): checked from the central directory
# before any member is read into memory.
_MAX_PACK_MEMBERS = 5000
_MAX_PACK_UNCOMPRESSED = 200 * 1024 * 1024  # 200 MB total
_MAX_MEMBER_RATIO = 200  # uncompressed / compressed, per member

# Matches /shared/<kind>/<path> references in SKILL.md body or frontmatter.
_SHARED_REF_RE = re.compile(r"/shared/(scripts|contexts|knowledge|databases)/([^\s\"'`)\]},]+)")


def _skills_root() -> Path:
    return (SERVER_DIR / SKILLS_PATH).resolve()


def _shared_root() -> Path:
    return (_skills_root().parent / "shared").resolve()


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a SKILL.md (supports --- and ```skill fences)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        m = re.match(r"^```skill\s*\n(.*?)\n```", text, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}


def _rel_files(base: Path) -> List[str]:
    """POSIX-relative file paths under base, skipping caches/compiled files."""
    out: List[str] = []
    if not base.is_dir():
        return out
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if Path(f).suffix.lower() in _SKIP_EXT:
                continue
            out.append((Path(root) / f).relative_to(base).as_posix())
    return sorted(out)


def _analyze_skill(name: str) -> dict:
    """Inspect one skill: its own files, the shared files it references, and the
    instance-specific requirements the target must satisfy."""
    skill_dir = _skill_dir_for_name(name)  # path-jailed; raises 400 on traversal
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        raise HTTPException(404, f"Skill '{name}' not found (no SKILL.md)")
    text = md.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    blob = text + "\n" + yaml.safe_dump(fm, default_flow_style=False)

    shared_root = _shared_root()
    shared_refs = {"scripts": set(), "contexts": set(), "knowledge": set(), "databases": set()}
    for kind, rest in _SHARED_REF_RE.findall(blob):
        shared_refs[kind].add(f"{kind}/{rest.strip().rstrip('.,);:')}")

    # Frontmatter context/knowledge declarations (absolute /shared/... or bare paths).
    def _add_paths(values):
        for v in values:
            if not isinstance(v, str):
                continue
            mm = _SHARED_REF_RE.search(v)
            if mm:
                shared_refs[mm.group(1)].add(f"{mm.group(1)}/{mm.group(2).strip().rstrip('.,);:')}")

    cf = fm.get("context_file")
    if isinstance(cf, str):
        _add_paths([cf])
    _add_paths(fm.get("context_files") or [])
    _add_paths(fm.get("knowledge") or [])

    # Shared files that actually exist on disk → includable in the pack.
    includable = {"scripts": [], "contexts": [], "knowledge": []}
    for kind in includable:
        for rel in sorted(shared_refs[kind]):
            if (shared_root / rel).is_file():
                includable[kind].append(rel)
            elif (shared_root / rel).is_dir():
                for sub in _rel_files(shared_root / rel):
                    includable[kind].append(f"{rel}/{sub}")

    # Requirements the operator must set up on the target.
    creds = []
    for c in (fm.get("connections") or []):
        if not isinstance(c, dict):
            continue
        cfg = c.get("config", {}) or {}
        cred_name = c.get("credential") or cfg.get("credential") or cfg.get("credential_ref")
        if cred_name:
            creds.append({"name": str(cred_name), "connection": c.get("name"),
                          "auth_type": cfg.get("auth_type")})
    mcp = []
    for m in (fm.get("mcp_connections") or []):
        if isinstance(m, dict):
            mcp.append({"name": m.get("name"), "transport": m.get("transport"),
                        "url": m.get("url")})
    databases = set(shared_refs["databases"])
    bc = fm.get("business_context") or {}
    for k, v in (bc.get("databases") or {}).items():
        loc = v.get("location") if isinstance(v, dict) else v
        if isinstance(loc, str) and loc.strip():
            # Normalize /shared/<kind>/<path> to the same form the reference scan
            # produces so the same database isn't listed twice in requirements.
            mm = _SHARED_REF_RE.search(loc)
            databases.add(f"{mm.group(1)}/{mm.group(2)}" if mm else loc.strip())
    workers = []
    for w in (fm.get("worker_skills") or []):
        workers.append(w.get("name") if isinstance(w, dict) else w)

    return {
        "name": name,
        "skill_files": _rel_files(skill_dir),
        "includable_shared": includable,
        "requires": {
            "credentials": creds,
            "mcp_servers": mcp,
            "databases": sorted(databases),
            "worker_skills": [w for w in workers if w],
        },
        "registry": _registry_entry(name),
    }


def _registry_entry(name: str) -> dict:
    """This skill's entry from _index.yaml (description/category/keywords)."""
    idx = _skills_root() / "_index.yaml"
    if not idx.is_file():
        return {}
    try:
        data = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    entry = (data.get("skills") or {}).get(name, {}) or {}
    return {
        "description": entry.get("description", ""),
        "category": entry.get("category", "platform"),
        "keywords": entry.get("keywords", []) or [],
    }


class AnalyzeRequest(BaseModel):
    skills: List[str]


@router.post("/api/skill-packs/analyze")
async def analyze_skills(req: AnalyzeRequest, request: Request, admin: dict = Depends(require_admin)):
    """Return, for each requested skill, its files, the shared files it references
    (that the caller can opt to include), and the requirements the target must have.
    Drives the Export dialog's checkboxes."""
    principal = principal_from_request(request)
    results = []
    for name in req.skills:
        enforce_entitlement(principal, "read", "skill", name)
        results.append(_analyze_skill(name))
    return {"skills": results}


class ExportRequest(BaseModel):
    skills: List[str]
    # Selected shared files to vendor into the pack (POSIX paths relative to
    # the tenant's shared/ root, e.g. "scripts/fpna/foo.py", "contexts/x.md").
    shared_files: List[str] = []


def _safe_shared_rel(rel: str) -> Optional[Path]:
    """Resolve a shared-relative path and confirm it stays under shared/ (no ..)."""
    try:
        p = (_shared_root() / rel).resolve()
        p.relative_to(_shared_root())
    except Exception:
        return None
    return p if p.is_file() else None


@router.post("/api/skill-packs/export")
async def export_skills(req: ExportRequest, request: Request, admin: dict = Depends(require_admin)):
    """Build and stream a .skillpack.zip for the selected skills + chosen shared files."""
    principal = principal_from_request(request)
    if not req.skills:
        raise HTTPException(400, "No skills selected")

    manifest = {
        "format": PACK_FORMAT,
        "format_version": PACK_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {"tenant": _skills_root().parent.name},
        "skills": [],
        "shared_files": [],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in req.skills:
            enforce_entitlement(principal, "read", "skill", name)
            info = _analyze_skill(name)
            skill_dir = _skill_dir_for_name(name)
            for rel in info["skill_files"]:
                zf.write(skill_dir / rel, f"skills/{name}/{rel}")
            manifest["skills"].append({
                "name": name,
                "registry": info["registry"],
                "requires": info["requires"],
            })

        # Vendor the selected shared files (deduped, path-jailed).
        written_shared = []
        for rel in dict.fromkeys(req.shared_files):
            disk = _safe_shared_rel(rel)
            if disk is None:
                logger.warning("skill-pack export: skipping invalid/missing shared file %r", rel)
                continue
            zf.write(disk, f"shared/{rel}")
            written_shared.append(rel)
        manifest["shared_files"] = written_shared

        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    fname = safe_pack_download_name(req.skills)
    logger.info("skill-pack export: %d skill(s), %d shared file(s) -> %s",
                len(req.skills), len(manifest["shared_files"]), fname)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _jailed_target(root: Path, arc_rel: str) -> Optional[Path]:
    """Resolve an archive member under root, rejecting absolute paths / .. (zip-slip)."""
    pp = PurePosixPath(arc_rel)
    if pp.is_absolute() or any(part == ".." for part in pp.parts):
        return None
    target = (root / Path(*pp.parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _read_pack(data: bytes) -> tuple[dict, dict]:
    """Parse a pack zip in memory. Returns (manifest, members) where members maps
    archive path -> bytes. Validates format + basic structure."""
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(413, "Skill pack exceeds size limit")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Not a valid .zip archive")
    infos = zf.infolist()
    if len(infos) > _MAX_PACK_MEMBERS:
        raise HTTPException(413, "Skill pack contains too many files")
    total = 0
    for info in infos:
        total += info.file_size
        if total > _MAX_PACK_UNCOMPRESSED:
            raise HTTPException(413, "Skill pack expands beyond the size limit")
        if info.file_size > 1024 * 1024 and info.file_size > _MAX_MEMBER_RATIO * max(info.compress_size, 1):
            raise HTTPException(400, "Skill pack member has a suspicious compression ratio")
    names = [i.filename for i in infos]
    if "manifest.json" not in names:
        raise HTTPException(400, "Not a skill pack (manifest.json missing)")
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except Exception:
        raise HTTPException(400, "Corrupt manifest.json")
    if manifest.get("format") != PACK_FORMAT:
        raise HTTPException(400, f"Unknown pack format: {manifest.get('format')!r}")
    if int(manifest.get("format_version", 0)) > PACK_VERSION:
        raise HTTPException(400, "Pack was created by a newer version of the platform")
    members = {n: zf.read(n) for n in names if not n.endswith("/")}
    return manifest, members


def _pack_summary(manifest: dict, members: dict) -> dict:
    """Preview: which skills are in the pack, which already exist on this instance,
    the shared files it carries, and the requirements to configure. No writes."""
    skills_root = _skills_root()
    skills = []
    for s in manifest.get("skills", []):
        name = s.get("name")
        prefix = f"skills/{name}/"
        files = [n[len(prefix):] for n in members if n.startswith(prefix)]
        exists = (skills_root / name / "SKILL.md").is_file() if name else False
        skills.append({
            "name": name,
            "exists": exists,
            # Default name to offer if the operator chooses to rename-on-import.
            "suggested_name": _unique_skill_name(name) if (exists and name) else None,
            "file_count": len(files),
            "has_tools": any(f.startswith("tools/") for f in files),
            "requires": s.get("requires", {}),
            "registry": s.get("registry", {}),
        })
    shared_root = _shared_root()
    shared = [
        {"path": n[len("shared/"):], "exists": (shared_root / n[len("shared/"):]).exists()}
        for n in members if n.startswith("shared/")
    ]
    shared.sort(key=lambda x: x["path"])
    conflicts = [s["name"] for s in skills if s["exists"]]
    return {
        "format_version": manifest.get("format_version"),
        "exported_at": manifest.get("exported_at"),
        "source": manifest.get("source", {}),
        "skills": skills,
        "shared_files": shared,                                  # [{path, exists}]
        "conflicts": conflicts,                                  # skill names that already exist
        "new_skills": [s["name"] for s in skills if not s["exists"]],
        "shared_conflicts": [x["path"] for x in shared if x["exists"]],
    }


def _sanitize_skill_name(name: str):
    """Return a safe skill folder name, or None if invalid (blocks path traversal /
    odd characters). Skill names are folder names, so keep them simple."""
    n = (name or "").strip()
    return n if is_valid_skill_folder_name(n) else None


def _unique_skill_name(base: str) -> str:
    root = _skills_root()
    if not (root / base).exists():
        return base
    i = 2
    while (root / f"{base}_imported{'' if i == 2 else i}").exists():
        i += 1
    return f"{base}_imported{'' if i == 2 else i}"


@router.post("/api/skill-packs/import")
async def import_pack(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    on_conflict: str = Form("skip"),        # skip | overwrite | rename
    rename_to: str = Form(""),              # JSON {original_name: desired_name} for rename-on-conflict
    write_shared: bool = Form(True),
    overwrite_shared: bool = Form(False),
    admin: dict = Depends(require_admin),
):
    """Import a .skillpack.zip. With dry_run=true, only previews (no writes)."""
    principal = principal_from_request(request)
    data = await file.read()
    manifest, members = _read_pack(data)

    if dry_run:
        return {"preview": _pack_summary(manifest, members)}

    if on_conflict not in ("skip", "overwrite", "rename"):
        raise HTTPException(400, "on_conflict must be skip|overwrite|rename")

    # Operator-chosen names for rename-on-conflict (skills can't be renamed after
    # creation, so let the caller decide the imported name instead of an auto suffix).
    try:
        rename_map = json.loads(rename_to) if rename_to.strip() else {}
        if not isinstance(rename_map, dict):
            rename_map = {}
    except Exception:
        rename_map = {}

    skills_root = _skills_root()
    report = {"imported": [], "skipped": [], "renamed": [],
              "shared_written": [], "shared_skipped": [], "requirements": [], "errors": []}

    for s in manifest.get("skills", []):
        src_name = s.get("name")
        if not src_name:
            continue
        enforce_entitlement(principal, "manage", "skill", src_name)
        prefix = f"skills/{src_name}/"
        skill_members = {n[len(prefix):]: b for n, b in members.items() if n.startswith(prefix)}
        if "SKILL.md" not in skill_members:
            report["errors"].append(f"{src_name}: SKILL.md missing in pack")
            continue

        try:
            _parse_frontmatter(skill_members["SKILL.md"].decode("utf-8"))
        except Exception as e:
            report["errors"].append(f"{src_name}: unreadable SKILL.md ({e})")
            continue

        # Validate any tool scripts + component html before writing anything.
        bad = _validate_members(src_name, skill_members)
        if bad:
            report["errors"].extend(bad)
            continue

        target_name = src_name
        exists = (skills_root / src_name / "SKILL.md").is_file()
        clean_replace = False
        if exists:
            if on_conflict == "skip":
                report["skipped"].append(src_name)
                continue
            if on_conflict == "rename":
                requested_raw = rename_map.get(src_name) if isinstance(rename_map, dict) else None
                if requested_raw:
                    requested = _sanitize_skill_name(requested_raw)
                    if not requested:
                        report["errors"].append(f"{src_name}: invalid rename target '{requested_raw}'")
                        continue
                    if (skills_root / requested).exists():
                        report["errors"].append(f"{src_name}: rename target '{requested}' already exists")
                        continue
                    target_name = requested
                else:
                    target_name = _unique_skill_name(src_name)
                report["renamed"].append({"from": src_name, "to": target_name})
            elif on_conflict == "overwrite":
                clean_replace = True

        target_dir = (skills_root / target_name).resolve()
        try:
            target_dir.relative_to(skills_root)
        except ValueError:
            report["errors"].append(f"{src_name}: illegal target name")
            continue

        # Overwrite is a clean replace: remove the existing skill folder first so no stale files remain.
        if clean_replace and target_dir.is_dir():
            try:
                shutil.rmtree(target_dir)
            except Exception as e:
                report["errors"].append(f"{src_name}: could not clear existing skill for overwrite ({e})")
                continue

        for rel, content in skill_members.items():
            dest = _jailed_target(target_dir, rel)
            if dest is None:
                report["errors"].append(f"{src_name}: unsafe path in pack: {rel}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_member(dest, content)

        # If renamed, fix the name in the written SKILL.md frontmatter.
        if target_name != src_name:
            _rewrite_skill_name(target_dir / "SKILL.md", target_name)

        reg = s.get("registry", {}) or {}
        await _update_index_yaml(
            skills_root, target_name,
            reg.get("description", ""), reg.get("keywords", []) or [],
            reg.get("category"),
        )
        report["imported"].append(target_name)
        req = s.get("requires", {}) or {}
        if any(req.get(k) for k in ("credentials", "mcp_servers", "databases", "worker_skills")):
            report["requirements"].append({"skill": target_name, **req})

    # Shared files (opt-in; never overwrite unless asked).
    if write_shared:
        shared_root = _shared_root()
        for n, content in members.items():
            if not n.startswith("shared/"):
                continue
            dest = _jailed_target(shared_root, n[len("shared/"):])
            if dest is None:
                report["errors"].append(f"unsafe shared path in pack: {n}")
                continue
            if dest.exists() and not overwrite_shared:
                report["shared_skipped"].append(n[len("shared/"):])
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_member(dest, content)
            report["shared_written"].append(n[len("shared/"):])

    _invalidate_skills_cache()
    logger.info("skill-pack import: imported=%d skipped=%d renamed=%d shared=%d errors=%d",
                len(report["imported"]), len(report["skipped"]), len(report["renamed"]),
                len(report["shared_written"]), len(report["errors"]))
    return {"report": report}


def _validate_members(name: str, skill_members: dict) -> List[str]:
    """Syntax-check tool scripts and sanity-check component HTML. Returns error strings."""
    import ast
    errors = []
    for rel, content in skill_members.items():
        if rel.startswith("tools/") and rel.endswith(".py") and not Path(rel).name.startswith("__"):
            try:
                ast.parse(content.decode("utf-8"))
            except SyntaxError as e:
                errors.append(f"{name}: tool {rel} has a syntax error (line {e.lineno})")
        elif rel == "component.html" or (rel.startswith("viewers/") and rel.endswith(".html")):
            try:
                _validate_component_html(content.decode("utf-8"), skill_name=name)
            except HTTPException as he:
                errors.append(f"{name}: {rel} rejected — {he.detail}")
            except Exception:
                pass
    return errors


def _write_member(dest: Path, content: bytes) -> None:
    """Write a pack member. Text files go through atomic_write_text; binaries direct."""
    try:
        atomic_write_text(dest, content.decode("utf-8"))
    except UnicodeDecodeError:
        dest.write_bytes(content)


def _rewrite_skill_name(md_path: Path, new_name: str) -> None:
    """Update the top-level `name:` field in a SKILL.md frontmatter after a
    rename-on-import. Anchored to column 0 so INDENTED name: keys (e.g. a
    connection's `name:`) are never touched, and scoped to the leading
    `--- … ---` frontmatter block so a `name:` in the body can't be hit."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return
    fm = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)", text, re.DOTALL)
    if fm:
        new_fm, n = re.subn(r"(?m)^(name\s*:\s*).+$", rf"\g<1>{new_name}", fm.group(2), count=1)
        if n:
            atomic_write_text(md_path, fm.group(1) + new_fm + fm.group(3) + text[fm.end():])
            return
    # Fallback (no standard frontmatter fence): first column-0 name: line.
    new_text, n = re.subn(r"(?m)^(name\s*:\s*).+$", rf"\g<1>{new_name}", text, count=1)
    if n:
        atomic_write_text(md_path, new_text)
