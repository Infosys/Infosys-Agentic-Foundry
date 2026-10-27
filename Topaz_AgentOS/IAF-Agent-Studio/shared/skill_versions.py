"""
skill_versions — per-skill version store with an active pointer + authorship.

Model
-----
The live skill is still ``skills/<name>/SKILL.md`` (+ ``tools/*.py`` and, for graph
skills, the process-graph YAML named by ``graph_ref``) — the runtime
loader, router and ``_index.yaml`` are unchanged; SKILL.md is always the ACTIVE
version. All versions are kept as immutable snapshots alongside it:

    skills/<name>/
      SKILL.md                     ← ACTIVE version (what the runtime loads)
      tools/*.py                   ← ACTIVE version's bundled tools
      .versions/
        manifest.json              ← {active, versions:[{id,version,author,...}]}
        v1.json                    ← {"skill_md": "...", "tool_scripts": [...], "graph_files": {...}}
        v2.json
        ...

Save modes
----------
* ``record_version(..., make_active=False)`` — "Save as new version": a fresh
  snapshot that does NOT touch the live files. Promote later via ``activate_version``.
* ``update_active_version(...)`` — "Update current version": overwrite the active
  snapshot in place AND rewrite the live files.
* ``activate_version(id)`` — copy a snapshot onto the live files + move the pointer.

Authorship is always supplied by the caller from the authenticated principal — it
is never taken from client input.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from shared.file_utils import atomic_write_text

VERSIONS_DIRNAME = ".versions"
MANIFEST_NAME = "manifest.json"



def _vdir(skill_dir: Path) -> Path:
    return Path(skill_dir) / VERSIONS_DIRNAME


def _manifest_path(skill_dir: Path) -> Path:
    return _vdir(skill_dir) / MANIFEST_NAME


def _snapshot_path(skill_dir: Path, vid: str) -> Path:
    return _vdir(skill_dir) / f"{vid}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def _read_frontmatter_version(skill_md: str) -> str:
    """Best-effort pull of the ``version:`` label from SKILL.md frontmatter."""
    try:
        import yaml
        if skill_md.startswith("---"):
            parts = skill_md.split("---", 2)
            if len(parts) >= 3:
                fm = yaml.safe_load(parts[1]) or {}
                return str(fm.get("version", "1.0"))
    except Exception:
        pass
    return "1.0"


def _read_live_tool_scripts(skill_dir: Path) -> list[dict]:
    tools_dir = Path(skill_dir) / "tools"
    scripts: list[dict] = []
    if tools_dir.is_dir():
        for py in sorted(tools_dir.glob("*.py")):
            if py.name.startswith("__"):
                continue
            try:
                scripts.append({"filename": py.name, "content": py.read_text(encoding="utf-8")})
            except Exception:
                continue
    return scripts


def _normalize_graph_files(graph_files: Any) -> dict[str, str]:
    """Keep only bare, non-reserved graph filenames -> {filename: yaml_text}."""
    out: dict[str, str] = {}
    for name, content in (graph_files or {}).items():
        name = str(name or "").strip()
        if (
            not name
            or name.startswith(".")
            or "/" in name
            or "\\" in name
            or name == "SKILL.md"
            or not isinstance(content, str)
        ):
            continue
        out[name] = content
    return out


def _write_live(
    skill_dir: Path,
    skill_md: str,
    tool_scripts: list[dict],
    graph_files: Optional[dict[str, str]] = None,
) -> None:
    """Write a snapshot onto the live skill files (SKILL.md + tools/*.py + graph YAML).

    Snapshots recorded before graph files were versioned carry none; the live
    graph file is then left as it is.
    """
    skill_dir = Path(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(skill_dir / "SKILL.md", skill_md)
    for gname, gcontent in _normalize_graph_files(graph_files).items():
        atomic_write_text(skill_dir / gname, gcontent)
    incoming = set()
    tools_dir = skill_dir / "tools"
    for ts in tool_scripts or []:
        fname = (ts.get("filename") or "").strip()
        content = ts.get("content") or ""
        if not fname or not content:
            continue
        if "/" in fname or "\\" in fname or not fname.endswith(".py"):
            continue
        tools_dir.mkdir(exist_ok=True)
        incoming.add(fname)
        atomic_write_text(tools_dir / fname, content)
    if tools_dir.is_dir():
        for existing in tools_dir.glob("*.py"):
            if existing.name.startswith("__"):
                continue
            if existing.name not in incoming:
                existing.unlink()


def _snapshot(skill_md: str, scripts: list[dict], graphs: dict[str, str]) -> dict:
    snap: dict[str, Any] = {"skill_md": skill_md, "tool_scripts": scripts}
    if graphs:
        snap["graph_files"] = graphs
    return snap


def _normalize_scripts(tool_scripts: Any) -> list[dict]:
    """Accept pydantic ToolScript objects or dicts → list[{filename, content}]."""
    out: list[dict] = []
    for ts in tool_scripts or []:
        if hasattr(ts, "filename"):
            out.append({"filename": ts.filename, "content": ts.content})
        elif isinstance(ts, dict):
            out.append({"filename": ts.get("filename", ""), "content": ts.get("content", "")})
    return out



def load_manifest(skill_dir: Path) -> dict:
    """Return the manifest ({} if the skill has never been versioned)."""
    return _read_json(_manifest_path(skill_dir)) or {}


def ensure_migrated(skill_dir: Path, graph_files: Optional[dict[str, str]] = None) -> dict:
    """Lazily create a v1 snapshot from the current live SKILL.md for skills that
    predate versioning. Idempotent. Returns the manifest.

    ``graph_files`` is only used when v1 is created: a caller about to overwrite a
    legacy graph skill's DAG passes the current one so v1 can restore it.
    """
    skill_dir = Path(skill_dir)
    manifest = load_manifest(skill_dir)
    if manifest.get("versions"):
        # Backfill: earlier migrations labelled the imported author "legacy".
        # Existing/pre-versioning skills should read as owned by admin@iaf.local.
        changed = False
        for v in manifest["versions"]:
            if v.get("author") in ("legacy", "unknown", "", None):
                v["author"] = "admin@iaf.local"
                v["email"] = v.get("email") or "admin@iaf.local"
                changed = True
        # Backfill the immutable creator from the first recorded version's author
        # for manifests written before created_by existed.
        if not manifest.get("created_by"):
            manifest["created_by"] = manifest["versions"][0].get("author") or "admin@iaf.local"
            changed = True
        if changed:
            _write_json(_manifest_path(skill_dir), manifest)
        return manifest
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        return manifest  # nothing to migrate yet
    skill_md = skill_md_path.read_text(encoding="utf-8")
    _vdir(skill_dir).mkdir(parents=True, exist_ok=True)
    _write_json(_snapshot_path(skill_dir, "v1"), _snapshot(
        skill_md, _read_live_tool_scripts(skill_dir), _normalize_graph_files(graph_files),
    ))
    manifest = {
        "active": "v1",
        "created_by": "admin@iaf.local",
        "versions": [{
            "id": "v1",
            "version": _read_frontmatter_version(skill_md),
            "author": "admin@iaf.local",
            "email": "admin@iaf.local",
            "created_at": _now(),
            "updated_at": _now(),
            "action": "migrated",
            "note": "Imported from existing SKILL.md (pre-versioning).",
        }],
    }
    _write_json(_manifest_path(skill_dir), manifest)
    return manifest


def _next_id(manifest: dict) -> str:
    n = len(manifest.get("versions", [])) + 1
    existing = {v["id"] for v in manifest.get("versions", [])}
    while f"v{n}" in existing:
        n += 1
    return f"v{n}"


def record_version(
    skill_dir: Path,
    *,
    skill_md: str,
    tool_scripts: Any,
    author: str,
    email: str = "",
    action: str = "update",
    note: Optional[str] = None,
    version_label: str = "1.0",
    make_active: bool = False,
    graph_files: Optional[dict[str, str]] = None,
) -> dict:
    """Create a NEW immutable snapshot. When make_active is False the live files
    are left untouched (draft). Returns the new version entry."""
    skill_dir = Path(skill_dir)
    manifest = ensure_migrated(skill_dir)
    if not manifest:
        manifest = {"active": None, "versions": []}
    # Record the immutable creator on first snapshot; never overwrite it later.
    manifest.setdefault("created_by", author or "unknown")
    scripts = _normalize_scripts(tool_scripts)
    graphs = _normalize_graph_files(graph_files)
    vid = _next_id(manifest)
    _vdir(skill_dir).mkdir(parents=True, exist_ok=True)
    _write_json(_snapshot_path(skill_dir, vid), _snapshot(skill_md, scripts, graphs))
    entry = {
        "id": vid,
        "version": str(version_label or "1.0"),
        "author": author or "unknown",
        "email": email or "",
        "created_at": _now(),
        "updated_at": _now(),
        "action": action,
        "note": note or "",
    }
    manifest.setdefault("versions", []).append(entry)
    if make_active:
        manifest["active"] = vid
        _write_live(skill_dir, skill_md, scripts, graphs)
    _write_json(_manifest_path(skill_dir), manifest)
    return entry


def record_promotion(
    skill_dir: Path,
    *,
    author: str,
    email: str = "",
    graph_files: Optional[dict[str, str]] = None,
    note: Optional[str] = None,
) -> dict:
    """Snapshot a skill whose live files were just copied in by an approval.

    Deliberately does not call ``ensure_migrated``: with live files and no
    manifest that helper would treat the skill as pre-versioning and stamp
    ``admin@iaf.local`` as its creator. The submitter is recorded instead, and
    ``created_by`` is never overwritten on a later re-publish.
    """
    skill_dir = Path(skill_dir)
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    scripts = _read_live_tool_scripts(skill_dir)
    graphs = _normalize_graph_files(graph_files)
    manifest = load_manifest(skill_dir) or {}
    manifest.setdefault("created_by", author or "unknown")
    vid = _next_id(manifest)
    _vdir(skill_dir).mkdir(parents=True, exist_ok=True)
    _write_json(_snapshot_path(skill_dir, vid), _snapshot(skill_md, scripts, graphs))
    entry = {
        "id": vid,
        "version": _read_frontmatter_version(skill_md),
        "author": author or "unknown",
        "email": email or "",
        "created_at": _now(),
        "updated_at": _now(),
        "action": "promote",
        "note": note or "Approved and promoted from a personal skill submission.",
    }
    manifest.setdefault("versions", []).append(entry)
    manifest["active"] = vid
    _write_json(_manifest_path(skill_dir), manifest)
    return entry


def update_active_version(
    skill_dir: Path,
    *,
    skill_md: str,
    tool_scripts: Any,
    author: str,
    email: str = "",
    note: Optional[str] = None,
    version_label: str = "1.0",
    graph_files: Optional[dict[str, str]] = None,
) -> dict:
    """Overwrite the ACTIVE version's snapshot in place and rewrite the live files.
    Falls back to creating an initial active version if none exists yet."""
    skill_dir = Path(skill_dir)
    manifest = ensure_migrated(skill_dir)
    active = manifest.get("active")
    if not active:
        return record_version(
            skill_dir, skill_md=skill_md, tool_scripts=tool_scripts, author=author,
            email=email, action="create", note=note, version_label=version_label, make_active=True,
            graph_files=graph_files,
        )
    scripts = _normalize_scripts(tool_scripts)
    graphs = _normalize_graph_files(graph_files)
    _write_json(_snapshot_path(skill_dir, active), _snapshot(skill_md, scripts, graphs))
    entry = next((v for v in manifest.get("versions", []) if v["id"] == active), None)
    if entry is not None:
        entry["author"] = author or entry.get("author", "unknown")
        entry["email"] = email or entry.get("email", "")
        entry["updated_at"] = _now()
        entry["version"] = str(version_label or entry.get("version", "1.0"))
        if note is not None:
            entry["note"] = note
    _write_live(skill_dir, skill_md, scripts, graphs)
    _write_json(_manifest_path(skill_dir), manifest)
    return entry or {"id": active}


def activate_version(skill_dir: Path, vid: str, *, author: str = "", email: str = "") -> dict:
    """Promote a snapshot to live: rewrite SKILL.md + tools/, move the active pointer."""
    skill_dir = Path(skill_dir)
    manifest = ensure_migrated(skill_dir)
    entry = next((v for v in manifest.get("versions", []) if v["id"] == vid), None)
    if entry is None:
        raise KeyError(f"version '{vid}' not found")
    snap = _read_json(_snapshot_path(skill_dir, vid))
    if not snap:
        raise KeyError(f"snapshot for '{vid}' missing")
    _write_live(skill_dir, snap.get("skill_md", ""), snap.get("tool_scripts", []), snap.get("graph_files"))
    manifest["active"] = vid
    entry["activated_at"] = _now()
    if author:
        entry["activated_by"] = author
    _write_json(_manifest_path(skill_dir), manifest)
    return entry


def list_versions(skill_dir: Path) -> dict:
    """Return {active, versions:[...]} (migrating a legacy skill on first read)."""
    manifest = ensure_migrated(skill_dir)
    return {"active": manifest.get("active"), "versions": manifest.get("versions", [])}


def owner(skill_dir: Path) -> str:
    """Return the skill's creator.

    Prefers the immutable manifest-level ``created_by``. Falls back to the first
    recorded version's author for legacy manifests (backfilled by
    ``ensure_migrated``). Used for owner-or-admin edit gating and UI display.
    """
    manifest = ensure_migrated(skill_dir)
    created_by = manifest.get("created_by")
    if created_by:
        return created_by
    versions = manifest.get("versions") or []
    if versions:
        return versions[0].get("author") or "admin@iaf.local"
    return "admin@iaf.local"


def get_version_content(skill_dir: Path, vid: str) -> Optional[dict]:
    """Return {skill_md, tool_scripts} for one version (for view / diff).

    Only serves ids that exist in the manifest — this keeps the endpoint from
    reading other files in ``.versions/`` (e.g. manifest.json) via a crafted id.
    """
    manifest = ensure_migrated(skill_dir)
    if vid not in {v.get("id") for v in manifest.get("versions", [])}:
        return None
    return _read_json(_snapshot_path(skill_dir, vid))
