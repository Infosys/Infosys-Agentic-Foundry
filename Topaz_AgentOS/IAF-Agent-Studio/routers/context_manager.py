"""
IAF Agent Studio — Enterprise Context Manager Router

Manages all enterprise knowledge sources (documents, transcripts, APIs,
database schemas, web pages, free text, policies) as .md files stored in
/shared/contexts/ and /shared/policies/ with a metadata registry.

Endpoints:
  GET    /api/context-manager              list all items
  POST   /api/context-manager              create item (text/JSON body)
  PUT    /api/context-manager/{item_id}    update content or metadata
  DELETE /api/context-manager/{item_id}    delete item + file
  POST   /api/context-manager/upload       upload file (PDF, DOCX, etc.)
  POST   /api/context-manager/fetch-url    scrape a URL → markdown
  POST   /api/context-manager/search       LLM semantic search
  POST   /api/context-manager/analyse-gap  gap analysis for a skill
  POST   /api/context-manager/check-conflicts  conflict detection
  POST   /api/context-manager/check-impact impact check before save
  GET    /api/context-manager/tree        LLM-clustered tree + orphan report (cached 1h)
  POST   /api/context-manager/reindex     force full disk re-scan + LLM re-cluster
"""

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form

from auth.middleware import require_permission
from pydantic import BaseModel

from security.dependencies import authorise_tenant, bind_request_identity, enforce_entitlement, requested_tenant
from shared.config import SERVER_DIR, DATA_ROOT, SKILLS_PATH
from shared.file_utils import atomic_write_text, atomic_write_json, locked_rmw_json
from shared.user_display import display_name as _owner_display_name, apply_display_names as _apply_owner_display_names
from shared.protected_files import (
    is_protected as _is_protected_file,
    resolve_contained as _resolve_contained,
)

logger = logging.getLogger(__name__)


# Tenant authorisation: a router-level dependency rejects (403) tenants the caller cannot access before any handler runs.

async def require_context_tenant(request: Request) -> str:
    """Router-level guard: authorise the requested tenant before any handler runs."""
    requested = await requested_tenant(request)
    # Raises 403 when `requested` is not in principal.allowed_tenants.
    principal, tenant_id, _agent, _user = bind_request_identity(
        request, requested_tenant=requested or None
    )
    request.state.context_principal = principal
    request.state.context_tenant = tenant_id
    return tenant_id


router = APIRouter(
    prefix="/api/context-manager",
    tags=["context-manager"],
    dependencies=[Depends(require_context_tenant)],
)


# Per-item access: allow by default, restrict via `context:<virtual path>` deny rules in the tenant policies.yaml.

def _context_resource_id(virtual_path: str) -> str:
    """Normalise a stored item path to the policy convention `/shared/<...>`."""
    path = str(virtual_path or "").strip().replace("\\", "/").lstrip("/")
    if path.startswith("shared/"):
        path = path[len("shared/"):]
    return "/shared/" + path


def _principal_for(request: Request):
    principal = getattr(request.state, "context_principal", None)
    if principal is None:  # defensive: dependency always sets it
        principal, _tenant, _agent, _user = bind_request_identity(request)
    return principal


def enforce_context_access(request: Request, virtual_path: str, action: str = "read") -> None:
    """Raise 403 when policy denies this principal on this context document."""
    enforce_entitlement(
        _principal_for(request), action, "context", _context_resource_id(virtual_path)
    )


def can_access_context(request: Request, virtual_path: str, action: str = "read") -> bool:
    """Non-raising variant, used to filter listings so restricted titles don't leak."""
    try:
        enforce_context_access(request, virtual_path, action)
        return True
    except HTTPException:
        return False


def _owner_identity(request: Request) -> str:
    """Identity string to stamp as a context item's creator."""
    try:
        from security.dependencies import principal_from_request
        p = principal_from_request(request)
        return getattr(p, "email", None) or getattr(p, "user_id", None) or "unknown"
    except Exception:
        return "unknown"


def _require_item_owner_or_admin(request: Request, item: dict) -> None:
    """Only the item's creator or an admin may mutate it. Legacy items with no
    recorded creator are treated as owned by admin@iaf.local."""
    try:
        from security.dependencies import principal_from_request
        p = principal_from_request(request)
    except Exception:
        raise HTTPException(403, "Not authorized to modify this item.")
    if "admin" in (getattr(p, "roles", ()) or ()):
        return
    idents = {v for v in (getattr(p, "email", None), getattr(p, "user_id", None)) if v}
    item_owner = item.get("created_by") or "admin@iaf.local"
    if item_owner not in idents:
        raise HTTPException(403, f"Only the owner ({item_owner}) or an admin can modify this item.")


def _file_owner(full_path: "Path") -> str:
    """Creator recorded in a .md file's YAML front-matter. Legacy files with no
    created_by are owned by admin@iaf.local."""
    try:
        raw = full_path.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter(raw)
        return (fm.get("created_by") or "").strip() or "admin@iaf.local"
    except Exception:
        return "admin@iaf.local"


def _require_file_owner_or_admin(request: Request, full_path: "Path") -> None:
    """Gate write/delete on a shared .md file to its creator or an admin."""
    _require_item_owner_or_admin(request, {"created_by": _file_owner(full_path)})


def _ensure_created_by(content: str, owner: str) -> str:
    """Guarantee the .md front-matter records created_by=<owner>. Only touches
    files that already have a front-matter block; never forces one onto plain
    markdown files that never had it."""
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return content
    fm_body = m.group(1)
    if re.search(r"^\s*created_by\s*:", fm_body, re.MULTILINE):
        return content
    new_fm = fm_body + f"\ncreated_by: {owner}"
    return content[:m.start(1)] + new_fm + content[m.end(1):]




VALID_TYPES = {"document", "transcript", "api", "database", "web", "notes", "policy", "root"}

TYPE_DIR = {
    "policy": "policies",
    "document": "contexts",
    "transcript": "contexts",
    "api": "contexts",
    "database": "contexts",
    "web": "contexts",
    "notes": "contexts",
}


def _shared_dir(tenant_id: str = "company") -> Path:
    data_root = Path(DATA_ROOT)
    if not data_root.is_absolute():
        data_root = (SERVER_DIR / data_root).resolve()
    return data_root / "tenants" / tenant_id / "shared"


def _registry_path(tenant_id: str = "company") -> Path:
    return _shared_dir(tenant_id) / "context_registry.json"


def _content_path(virtual_path: str, tenant_id: str = "company") -> Path:
    """Convert virtual path /shared/xxx/yyy.md → absolute filesystem path."""
    rel = virtual_path.lstrip("/")
    if rel.startswith("shared/"):
        rel = rel[len("shared/"):]
    return _shared_dir(tenant_id) / rel


def _safe_shared_file(path: str, tenant_id: str, *, require_file: bool = True) -> Path:
    """Resolve a caller-supplied ``/shared/...`` path to a real filesystem path,
    traversal- AND symlink-safe, rejecting protected material. Raises
    HTTPException on any violation; returns the resolved real Path.

    This is the single gate every caller-path context-manager endpoint uses so
    ``..`` traversal, symlink escape, and symlink-to-protected all fail closed —
    the checks run on the *resolved* target, not the requested alias.
    """
    rel = (path or "").lstrip("/")
    if rel.startswith("shared/"):
        rel = rel[len("shared/"):]
    # Fast, explicit 403 for an obviously-protected requested path.
    if _is_protected_file("/shared/" + rel):
        raise HTTPException(403, "This path is protected and cannot be accessed via the file API.")
    real = _resolve_contained(_shared_dir(tenant_id), rel)
    if real is None:
        # Escaped the tenant shared tree, or resolved to protected material.
        raise HTTPException(400, "Invalid or protected path")
    if require_file and not real.is_file():
        raise HTTPException(404, "File not found")
    return real


def _infer_type_from_path(sub_dir: str, frontmatter: dict) -> str:
    """Guess context type from folder name or frontmatter."""
    fm_type = frontmatter.get("type", "").lower()
    if fm_type in VALID_TYPES:
        return fm_type
    if sub_dir == "policies":
        return "policy"
    if sub_dir == "databases":
        return "database"
    return "document"


def _parse_frontmatter(raw: str) -> dict:
    """Extract YAML frontmatter from a markdown file. Returns {} if none."""
    match = re.match(r"^---\n(.*?)\n---", raw, re.DOTALL)
    if not match:
        return {}
    try:
        import yaml
        return yaml.safe_load(match.group(1)) or {}
    except Exception as e:
        logger.warning("Failed to parse YAML frontmatter: %s", e)
        return {}


def _autodiscover(tenant_id: str) -> dict:
    """
    Walk shared root, contexts/, policies/, and databases/ and build a registry
    from all .md files found. Reads frontmatter where available.
    Called once when the registry file does not exist yet.
    """
    shared = _shared_dir(tenant_id)
    # Root dir first so Enterprise_Context.md etc. get type="root"
    scan_dirs = [
        ("root",      shared),
        ("contexts",  shared / "contexts"),
        ("policies",  shared / "policies"),
        ("databases", shared / "databases"),
    ]
    items = []
    seen_ids: set = set()
    now = _now()

    for sub_dir, dir_path in scan_dirs:
        if not dir_path.exists():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            if md_file.stem in ("context_registry", "context_tree_cache", "_index"):
                continue
            try:
                raw = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Skipping unreadable file %s during autodiscover: %s", md_file, e)
                continue

            fm = _parse_frontmatter(raw)
            item_id = md_file.stem
            # Avoid duplicate IDs across dirs
            if item_id in seen_ids:
                item_id = f"{sub_dir}_{item_id}"
            seen_ids.add(item_id)

            # Virtual path — root files live directly under /shared/
            if sub_dir == "root":
                virtual_path = f"/shared/{md_file.name}"
            else:
                virtual_path = f"/shared/{sub_dir}/{md_file.name}"

            name = fm.get("name") or item_id.replace("_", " ").replace("-", " ").title()

            # Root-level .md files get type "root" unless frontmatter says otherwise
            if sub_dir == "root":
                item_type = fm.get("type", "root") if fm.get("type") in VALID_TYPES else "root"
            else:
                item_type = _infer_type_from_path(sub_dir, fm)

            skills = fm.get("skills") or []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",") if s.strip()]

            linked_assets = fm.get("linked_assets") or []
            if isinstance(linked_assets, str):
                linked_assets = [linked_assets]

            mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc).isoformat()

            items.append({
                "id": item_id,
                "name": name,
                "type": item_type,
                "description": fm.get("description", ""),
                "path": virtual_path,
                "source": None,
                "source_url": fm.get("source_url") or None,
                "skills": skills,
                "linked_assets": linked_assets,
                "status": fm.get("status", "active"),
                "auto_refresh": fm.get("auto_refresh") or None,
                "created_at": mtime,
                "updated_at": mtime,
            })

    reg = {"version": "1.0", "items": items}
    _save_registry(reg, tenant_id)
    logger.info("Context Manager: auto-discovered %d items for tenant '%s'", len(items), tenant_id)
    return reg


import time as _time

_registry_cache: dict[str, tuple[float, dict]] = {}  # tenant_id → (expire_at, data)
_REGISTRY_CACHE_TTL = 30  # seconds


def _load_registry(tenant_id: str = "company") -> dict:
    now = _time.monotonic()
    cached = _registry_cache.get(tenant_id)
    if cached and cached[0] > now:
        return cached[1]

    path = _registry_path(tenant_id)
    if path.exists():
        try:
            reg = json.loads(path.read_text(encoding="utf-8"))
            # If registry exists but is empty, re-scan in case files were added manually
            if not reg.get("items"):
                reg = _autodiscover(tenant_id)
            _registry_cache[tenant_id] = (now + _REGISTRY_CACHE_TTL, reg)
            return reg
        except Exception as e:
            logger.warning("Failed to parse registry JSON, falling back to autodiscover: %s", e)
    # No registry file yet — scan the filesystem
    reg = _autodiscover(tenant_id)
    _registry_cache[tenant_id] = (now + _REGISTRY_CACHE_TTL, reg)
    return reg


def _save_registry(reg: dict, tenant_id: str = "company") -> None:
    path = _registry_path(tenant_id)
    atomic_write_json(path, reg)
    # Invalidate cache so next read picks up the change
    _registry_cache.pop(tenant_id, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug or "context_" + uuid.uuid4().hex[:6]


def _word_count(text: str) -> int:
    return len(text.split())


def _read_content(virtual_path: str, tenant_id: str) -> str:
    p = _content_path(virtual_path, tenant_id)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _write_content(virtual_path: str, content: str, tenant_id: str) -> None:
    p = _content_path(virtual_path, tenant_id)
    atomic_write_text(p, content)


def _delete_content(virtual_path: str, tenant_id: str) -> None:
    p = _content_path(virtual_path, tenant_id)
    if p.exists():
        p.unlink()


def _get_llm():
    """Return light AzureChatOpenAI instance, or None if not configured."""
    try:
        from langchain_openai import AzureChatOpenAI
        deployment = os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_LIGHT",
            os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        )
        return AzureChatOpenAI(
            model=deployment,
            temperature=0.1,
            max_tokens=2000,
        )
    except Exception as e:
        logger.warning("LLM unavailable: %s", e)
        return None


def _llm_call(system: str, user: str) -> str:
    """Call LLM with system + user message, return text or raise."""
    llm = _get_llm()
    if llm is None:
        raise RuntimeError("LLM not configured — check AZURE_OPENAI_DEPLOYMENT env vars")
    from langchain_core.messages import SystemMessage, HumanMessage
    resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    try:
        from iaf_agent_skills import llm_tracker as _lt
        _lt.record("context_manager", resp, 0.0, getattr(llm, 'azure_deployment', getattr(llm, 'model_name', '')))
    except Exception as e:
        logger.warning("LLM tracker unavailable (non-fatal): %s", e)
    return resp.content.strip()


_EXT_CONVERSION = {
    ".pdf":  ("document",   "markitdown"),
    ".docx": ("document",   "markitdown"),
    ".pptx": ("document",   "markitdown"),
    ".xlsx": ("database",   "markitdown"),
    ".txt":  ("notes",      "text"),
    ".md":   ("document",   "text"),
    ".csv":  ("database",   "tabular"),
    ".tsv":  ("database",   "tabular"),
    ".json": ("notes",      "json"),
    ".jsonl":("notes",      "json"),
    ".mp3":  ("transcript", "whisper"),
    ".wav":  ("transcript", "whisper"),
    ".m4a":  ("transcript", "whisper"),
    ".ogg":  ("transcript", "whisper"),
    ".webm": ("transcript", "whisper"),
    ".flac": ("transcript", "whisper"),
    # video → whisper (audio track)
    ".mp4":  ("transcript", "whisper"),
    ".mov":  ("transcript", "whisper"),
    ".avi":  ("transcript", "whisper"),
    ".mkv":  ("transcript", "whisper"),
    ".png":  ("document",   "vision"),
    ".jpg":  ("document",   "vision"),
    ".jpeg": ("document",   "vision"),
    ".webp": ("document",   "vision"),
    ".gif":  ("document",   "vision"),
}


def _detect_conversion(filename: str) -> dict:
    """Return conversion metadata for a file: can_convert, suggested_type, method, label."""
    ext = Path(filename).suffix.lower()
    if ext not in _EXT_CONVERSION:
        return {"can_convert": False, "suggested_type": None, "method": None, "label": None}
    suggested_type, method = _EXT_CONVERSION[ext]
    labels = {
        "markitdown": "Extract text as context",
        "text":       "Register as context",
        "tabular":    "Summarise table as context",
        "json":       "Summarise structure as context",
        "whisper":    "Transcribe audio to context",
        "vision":     "Describe image as context",
    }
    return {
        "can_convert": True,
        "suggested_type": suggested_type,
        "method": method,
        "label": labels.get(method, "Convert to context"),
    }


def _extract_with_markitdown(file_bytes: bytes, ext: str) -> str:
    """Run markitdown on bytes, return markdown text."""
    import tempfile
    from markitdown import MarkItDown
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        result = MarkItDown().convert(tmp_path)
        text = getattr(result, "text_content", None) or getattr(result, "markdown", None)
        return (text or "").strip()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception as e:
            logger.warning("Failed to delete temp file %s: %s", tmp_path, e)


def _extract_tabular(file_bytes: bytes, filename: str) -> str:
    """Parse CSV/TSV → markdown table summary with column stats."""
    import csv, io
    delimiter = "\t" if filename.lower().endswith(".tsv") else ","
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return ""
    headers = rows[0]
    data_rows = rows[1:]
    total_rows = len(data_rows)

    lines = [
        f"## Table: {Path(filename).stem}",
        f"**Rows:** {total_rows:,}  |  **Columns:** {len(headers)}\n",
        "### Columns",
    ]
    for h in headers:
        col_vals = [r[headers.index(h)] for r in data_rows if headers.index(h) < len(r)]
        non_empty = sum(1 for v in col_vals if v.strip())
        lines.append(f"- **{h}** ({non_empty:,}/{total_rows:,} non-empty)")

    # Sample: first 10 rows as markdown table
    sample = data_rows[:10]
    if sample:
        lines.append("\n### Sample (first 10 rows)")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in sample:
            padded = list(row) + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(str(v)[:60] for v in padded[:len(headers)]) + " |")
    return "\n".join(lines)


def _extract_json_file(file_bytes: bytes, filename: str) -> str:
    """Summarise JSON / JSONL structure as markdown."""
    import io
    text = file_bytes.decode("utf-8", errors="replace")
    lines_out = [f"## JSON File: {Path(filename).stem}\n"]

    # JSONL: parse line by line
    if filename.lower().endswith(".jsonl"):
        records = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception as e:
                    logger.warning("Skipping malformed JSONL line: %s", e)
        lines_out.append(f"**Format:** JSONL  |  **Records:** {len(records):,}")
        if records:
            sample = records[0]
            lines_out.append(f"\n### Field Schema (from first record)")
            for k, v in (sample.items() if isinstance(sample, dict) else {}.items()):
                lines_out.append(f"- `{k}`: {type(v).__name__}")
            if len(records) > 1:
                lines_out.append(f"\n### Sample record\n```json\n{json.dumps(records[0], indent=2)[:500]}\n```")
        return "\n".join(lines_out)

    try:
        data = json.loads(text)
    except Exception as e:
        logger.warning("Failed to parse JSON content, returning raw text excerpt: %s", e)
        return text[:2000]

    if isinstance(data, list):
        lines_out.append(f"**Format:** JSON Array  |  **Items:** {len(data):,}")
        if data and isinstance(data[0], dict):
            lines_out.append("\n### Keys (from first item)")
            for k, v in data[0].items():
                lines_out.append(f"- `{k}`: {type(v).__name__}")
        if data:
            lines_out.append(f"\n### Sample item\n```json\n{json.dumps(data[0], indent=2)[:500]}\n```")
    elif isinstance(data, dict):
        lines_out.append(f"**Format:** JSON Object  |  **Top-level keys:** {len(data)}")
        lines_out.append("\n### Structure")
        for k, v in list(data.items())[:20]:
            lines_out.append(f"- `{k}` ({type(v).__name__}): {str(v)[:80]}")
    else:
        lines_out.append(str(data)[:2000])

    return "\n".join(lines_out)


def _extract_audio_whisper(file_bytes: bytes, filename: str) -> str:
    """
    Transcribe audio using Azure OpenAI Whisper deployment.
    Falls back to openai.com Whisper if Azure Whisper not configured.
    Returns transcription text or a stub if neither available.
    """
    import tempfile

    whisper_deployment = os.getenv("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper")
    api_key  = os.getenv("AZURE_OPENAI_API_KEY", "")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_ver  = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
    ext      = Path(filename).suffix.lower()

    # Write to temp file (Whisper API requires a real file, not raw bytes)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        import requests as _req
        url = f"{endpoint}/openai/deployments/{whisper_deployment}/audio/transcriptions?api-version={api_ver}"
        with open(tmp_path, "rb") as f:
            resp = _req.post(
                url,
                headers={"api-key": api_key},
                files={"file": (filename, f, "audio/mpeg")},
                data={"response_format": "verbose_json"},
                timeout=120,
            )
        if resp.status_code == 200:
            data = resp.json()
            transcript = data.get("text", "")
            duration   = data.get("duration", 0)
            lang       = data.get("language", "")
            header = f"## Transcript: {Path(filename).stem}\n"
            if duration:
                header += f"**Duration:** {int(duration)//60}m {int(duration)%60}s"
            if lang:
                header += f"  |  **Language:** {lang}"
            return header + "\n\n" + transcript
        else:
            logger.warning("Azure Whisper failed (%s): %s", resp.status_code, resp.text[:200])

        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            with open(tmp_path, "rb") as f:
                resp2 = client.audio.transcriptions.create(model="whisper-1", file=f,
                                                            response_format="verbose_json")
            return (f"## Transcript: {Path(filename).stem}\n\n{resp2.text}")
    except Exception as e:
        logger.warning("Whisper transcription failed for %s: %s", filename, e)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception as e:
            logger.warning("Failed to delete audio temp file %s: %s", tmp_path, e)

    size_mb = len(file_bytes) / (1024 * 1024)
    return (
        f"## {Path(filename).stem}\n\n"
        f"**File:** `{filename}`  |  **Size:** {size_mb:.1f} MB\n\n"
        f"> ⚠️ Transcription not available.\n"
        f"> Set `AZURE_OPENAI_WHISPER_DEPLOYMENT` in config.env to enable audio transcription.\n\n"
        f"*This file has been saved as a reference asset.*"
    )


def _extract_image_vision(file_bytes: bytes, filename: str) -> str:
    """
    Describe an image using Azure OpenAI vision (gpt-5.2-chat / GPT-4o).
    Falls back to stub if vision API not available.
    """
    import base64
    import requests as _req

    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    api_key    = os.getenv("AZURE_OPENAI_API_KEY", "")
    endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_ver    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    ext        = Path(filename).suffix.lower()

    mime_map   = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".png": "image/png", ".webp": "image/webp",
                  ".gif": "image/gif"}
    mime       = mime_map.get(ext, "image/png")
    b64_image  = base64.b64encode(file_bytes).decode()

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": ("You are an enterprise knowledge manager. Describe this image in detail "
                          "for a searchable knowledge base. Include: what is shown, key text visible, "
                          "any charts/diagrams/data, and the business context if apparent. "
                          "Format as clean markdown.")},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64_image}", "detail": "high"}},
            ],
        }],
        "max_tokens": 1500,
        "temperature": 0.1,
    }
    try:
        resp = _req.post(url, headers={"api-key": api_key, "Content-Type": "application/json"},
                         json=payload, timeout=60)
        if resp.status_code == 200:
            description = resp.json()["choices"][0]["message"]["content"].strip()
            return f"## Image: {Path(filename).stem}\n\n{description}"
        else:
            logger.warning("Vision API failed (%s): %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Vision extraction failed for %s: %s", filename, e)

    return (
        f"## {Path(filename).stem}\n\n"
        f"**File:** `{filename}`\n\n"
        f"> ⚠️ Image description not available (vision API error).\n"
        f"*Image saved as reference asset.*"
    )


def _extract_file(file_bytes: bytes, filename: str) -> str:
    """
    Route file to the correct extractor based on extension.
    Returns markdown string ready to be stored as context .md body.
    """
    ext = Path(filename).suffix.lower()
    info = _detect_conversion(filename)
    method = info.get("method")

    # Audio / Video → Whisper
    if method == "whisper":
        return _extract_audio_whisper(file_bytes, filename)

    if method == "vision":
        return _extract_image_vision(file_bytes, filename)

    if method == "tabular":
        return _extract_tabular(file_bytes, filename)

    # JSON / JSONL → structure summary
    if method == "json":
        return _extract_json_file(file_bytes, filename)

    # Plain text / markdown → direct read
    if method == "text":
        return file_bytes.decode("utf-8", errors="replace").strip()

    # markitdown (PDF, DOCX, PPTX, XLSX) + fallback
    try:
        return _extract_with_markitdown(file_bytes, ext)
    except Exception as e:
        logger.warning("markitdown failed for %s: %s", filename, e)

    return file_bytes.decode("utf-8", errors="replace").strip()


def _fetch_url(url: str) -> str:
    """Fetch URL and return clean markdown text.

    SSRF guard: this path takes a caller-supplied URL and returns the full response
    body, which made it the strongest SSRF primitive in the product — previously with
    no scheme check and no address filtering, so `http://169.254.169.254/...` or any
    internal host was fetchable. Validate before connecting, and revalidate redirects
    rather than letting the client follow them to an unchecked hop.
    """
    import requests
    from bs4 import BeautifulSoup

    from agent_os.egress_ssrf import SSRFBlocked, assert_safe_url

    try:
        assert_safe_url(url)
    except SSRFBlocked as exc:
        raise ValueError(f"blocked by egress policy: {exc}") from exc

    headers = {"User-Agent": "Mozilla/5.0 (IAF Context Manager/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15, allow_redirects=False)
    if resp.is_redirect or resp.is_permanent_redirect:
        target = resp.headers.get("Location", "")
        try:
            assert_safe_url(target)
        except SSRFBlocked as exc:
            raise ValueError(f"redirect blocked by egress policy: {exc}") from exc
        resp = requests.get(target, headers=headers, timeout=15, allow_redirects=False)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _build_md(item: dict, content_body: str) -> str:
    """Wrap body content in YAML frontmatter."""
    skills_list = json.dumps(item.get("skills", []))
    # created_by is server truth for ownership; stamp it here or the creator is locked out of their own file.
    owner = (item.get("created_by") or "").strip()
    owner_line = f"created_by: {owner}\n" if owner else ""
    return (
        f"---\n"
        f"name: {item['name']}\n"
        f"type: {item['type']}\n"
        f"description: {item.get('description', '')}\n"
        f"status: {item.get('status', 'active')}\n"
        f"skills: {skills_list}\n"
        f"{owner_line}"
        f"---\n\n"
        f"{content_body.strip()}\n"
    )


def _tree_cache_path(tenant_id: str = "company") -> Path:
    return _shared_dir(tenant_id) / "context_tree_cache.json"


def _load_tree_cache(tenant_id: str, item_count: int) -> Optional[dict]:
    """Load cached tree if < 1 hour old and item count matches."""
    cache_path = _tree_cache_path(tenant_id)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at")
        if cached_at:
            from datetime import timedelta
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)
            if age.total_seconds() > 3600:
                return None
        if data.get("total_items") != item_count:
            return None
        return data
    except Exception as e:
        logger.warning("Failed to read tree cache: %s", e)
        return None


def _save_tree_cache(tree_data: dict, tenant_id: str) -> None:
    cache_path = _tree_cache_path(tenant_id)
    tree_data["cached_at"] = _now()
    atomic_write_json(cache_path, tree_data)


def _invalidate_tree_cache(tenant_id: str) -> None:
    cache_path = _tree_cache_path(tenant_id)
    if cache_path.exists():
        try:
            cache_path.unlink()
        except Exception as e:
            logger.warning("Failed to invalidate tree cache file: %s", e)


def _detect_orphans(items: list, tenant_id: str) -> dict:
    """Detect three classes of orphans."""
    # 1. Unlinked: in registry but no skills
    unlinked = [i for i in items if not i.get("skills")]

    # 2. Unindexed: on disk but not in registry
    registered_paths = {i["path"] for i in items}
    shared = _shared_dir(tenant_id)
    unindexed = []
    for sub in ["contexts", "policies"]:
        dir_path = shared / sub
        if dir_path.exists():
            for f in sorted(dir_path.glob("*.md")):
                vpath = f"/shared/{sub}/{f.name}"
                if vpath not in registered_paths:
                    unindexed.append({
                        "path": vpath,
                        "name": f.stem.replace("_", " ").replace("-", " ").title(),
                    })

    # 3. Broken refs: skills field points to skill dirs that don't exist
    skills_root = Path(SKILLS_PATH)
    if not skills_root.is_absolute():
        skills_root = (SERVER_DIR / skills_root).resolve()
    broken_refs = []
    for item in items:
        missing = [sk for sk in (item.get("skills") or []) if not (skills_root / sk).is_dir()]
        if missing:
            broken_refs.append({
                "id": item["id"],
                "name": item["name"],
                "type": item.get("type", "document"),
                "path": item.get("path", ""),
                "missing_skills": missing,
            })

    return {"unlinked": unlinked, "unindexed": unindexed, "broken_refs": broken_refs}


def _cluster_items_by_type(items: list) -> list:
    """Rule-based fallback: group items by content type."""
    TYPE_META = {
        "document":   ("📄", "Documents"),
        "transcript": ("🎙", "Transcripts & Meetings"),
        "notes":      ("📝", "Notes & Free Text"),
        "api":        ("🔌", "APIs & Integrations"),
        "database":   ("🗄", "Databases"),
        "web":        ("🌐", "Web Sources"),
        "policy":     ("🔒", "Policies & Compliance"),
    }
    ORDER = ["document", "transcript", "notes", "api", "database", "web", "policy"]
    groups: dict = {}
    for item in items:
        t = item.get("type", "document")
        if t not in groups:
            icon, label = TYPE_META.get(t, ("📄", t.title()))
            groups[t] = {"id": f"__grp_{t}__", "label": label, "icon": icon, "description": "", "children": []}
        groups[t]["children"].append(item)
    return [groups[k] for k in ORDER if k in groups] + [v for k, v in groups.items() if k not in ORDER]


def _cluster_items_llm(items: list) -> list:
    """Ask LLM to cluster items into semantic groups; fall back to type-based on failure."""
    if not items:
        return []

    item_lines = [
        f'  {{"id":"{i["id"]}","name":"{i["name"]}","type":"{i.get("type","document")}",'
        f'"description":"{str(i.get("description",""))[:80]}"}}'
        for i in items
    ]
    items_json = "[\n" + ",\n".join(item_lines) + "\n]"

    system = (
        "You are an AI knowledge architect. Given a list of enterprise context items, "
        "cluster them into 3-6 meaningful semantic groups based on business purpose.\n\n"
        "Good group names: 'Core Business Knowledge', 'Policies & Compliance', "
        "'System Integrations', 'Database Schemas', 'External Sources', 'Meeting Notes & Transcripts'.\n\n"
        "Respond ONLY with valid JSON:\n"
        '{"groups":[{"label":"Group Name","icon":"emoji","description":"brief description",'
        '"item_ids":["id1","id2"]}]}\n\n'
        "Rules: every item in exactly one group; business-friendly labels; one emoji per group."
    )
    try:
        resp_text = _llm_call(system, f"Items to cluster:\n{items_json}")
        json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            item_map = {i["id"]: i for i in items}
            assigned: set = set()
            groups = []
            for grp in data.get("groups", []):
                children = [item_map[iid] for iid in grp.get("item_ids", []) if iid in item_map]
                assigned.update(iid for iid in grp.get("item_ids", []) if iid in item_map)
                if children:
                    label = grp.get("label", "Other")
                    groups.append({
                        "id": f"__grp_{re.sub(r'[^a-z0-9]', '_', label.lower())}__",
                        "label": label,
                        "icon": grp.get("icon", "📁"),
                        "description": grp.get("description", ""),
                        "children": children,
                    })
            unassigned = [i for i in items if i["id"] not in assigned]
            if unassigned:
                groups.append({"id": "__grp_other__", "label": "Other", "icon": "📄",
                                "description": "Remaining items", "children": unassigned})
            return groups
    except Exception as exc:
        logger.warning("LLM clustering failed (%s) — using type-based fallback", exc)
    return _cluster_items_by_type(items)


def _build_tree_data(items: list, tenant_id: str) -> dict:
    """Build full tree payload: root → LLM-clustered groups → items, plus orphan report."""
    orphans = _detect_orphans(items, tenant_id)

    root_item = next((i for i in items if i.get("type") == "root"), None)
    non_root = [i for i in items if i.get("type") != "root"]

    groups = _cluster_items_llm(non_root) if non_root else []

    tree = {
        "id": "__root__",
        "label": root_item["name"] if root_item else "Enterprise Context",
        "icon": "🗂",
        "type": "root",
        "item": root_item,
        "children": groups,
    }
    return {"tree": tree, "orphans": orphans}


class ContextCreateRequest(BaseModel):
    name: str
    type: str
    description: str = ""
    content: str = ""
    source_url: Optional[str] = None
    skills: list = []
    status: str = "active"
    auto_refresh: Optional[str] = None   # "weekly" | "monthly" | None
    tenant_id: str = "company"


class ContextUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    skills: Optional[list] = None
    status: Optional[str] = None
    tenant_id: str = "company"


class SearchRequest(BaseModel):
    query: str
    tenant_id: str = "company"


class GapAnalysisRequest(BaseModel):
    skill_name: str
    tenant_id: str = "company"


class ConflictRequest(BaseModel):
    tenant_id: str = "company"
    item_ids: Optional[list] = None   # None = check all


class ImpactRequest(BaseModel):
    item_id: str
    old_content: str
    new_content: str
    tenant_id: str = "company"


@router.get("/files/list")
async def list_context_files(tenant_id: str = "company"):
    """List all .md files under shared/ as relative paths (shared/contexts/x.md etc).
    Used by the skill editor context_file picker dropdown."""
    shared = _shared_dir(tenant_id)
    files = []
    for folder in ("contexts", "policies", "standards", "knowledge"):
        folder_path = shared / folder
        if not folder_path.exists():
            continue
        for md in sorted(folder_path.rglob("*.md")):
            rel = "shared/" + md.relative_to(shared).as_posix()
            files.append({
                "path": rel,
                "name": md.name,
                "folder": folder,
                "size_bytes": md.stat().st_size,
                "created_by": _file_owner(md),
            })
    await _apply_owner_display_names(files)
    return {"files": files}


# Must be registered BEFORE /{item_id} to avoid 405.

@router.get("/routing-map")
async def routing_map_endpoint(tenant_id: str = "company"):
    """Semantic L1→L5 tree parsed from Enterprise_Context.md and taxonomy files."""
    return await get_routing_map(tenant_id)


@router.get("")
async def list_context_items(request: Request, tenant_id: str = "company"):
    """Return all context registry items with word counts.

    Items the caller is not entitled to read are filtered out rather than
    returned-and-then-refused, so restricted document titles do not leak.
    """
    def _enrich():
        reg = _load_registry(tenant_id)
        items = reg.get("items", [])
        for item in items:
            try:
                raw = _read_content(item["path"], tenant_id)
                body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.DOTALL).strip()
                item["word_count"] = _word_count(body)
                item["exists"] = True
            except Exception as e:
                logger.warning("Failed to read content for item %s: %s", item.get("id"), e)
                item["word_count"] = 0
                item["exists"] = False
        return items

    items = await asyncio.to_thread(_enrich)
    visible = [i for i in items if can_access_context(request, i.get("path", ""), "read")]
    return {"items": visible, "total": len(visible)}


@router.post("")
async def create_context_item(req: ContextCreateRequest, request: Request, _perm: dict = Depends(require_permission("skills.author"))):
    """Create a new context item from a JSON body (text, notes, API, DB, transcript).

    Requires the developer 'skills.author' capability; plain 'user' role is excluded."""
    # Validate the requested tenant against allowed_tenants; the permission dependency checks only the role.
    bind_request_identity(request, req.tenant_id)
    if req.type not in VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{req.type}'. Valid: {sorted(VALID_TYPES)}")

    reg = _load_registry(req.tenant_id)
    item_id = _slugify(req.name)

    existing_ids = {i["id"] for i in reg.get("items", [])}
    if item_id in existing_ids:
        item_id = item_id + "_" + uuid.uuid4().hex[:4]

    sub_dir = TYPE_DIR.get(req.type, "contexts")
    filename = f"{item_id}.md"
    virtual_path = f"/shared/{sub_dir}/{filename}"

    body = req.content or f"## {req.name}\n\n_Add content here._"
    if req.source_url:
        body = f"Source: {req.source_url}\n\n" + body

    md_content = _build_md(
        {"name": req.name, "type": req.type, "description": req.description,
         "status": req.status, "skills": req.skills,
         "created_by": _owner_identity(request)},
        body
    )
    _write_content(virtual_path, md_content, req.tenant_id)

    now = _now()
    entry = {
        "id": item_id,
        "name": req.name,
        "type": req.type,
        "description": req.description,
        "path": virtual_path,
        "source": None,
        "source_url": req.source_url,
        "skills": req.skills,
        "status": req.status,
        "auto_refresh": req.auto_refresh,
        "created_at": now,
        "updated_at": now,
        "created_by": _owner_identity(request),
    }
    reg.setdefault("items", []).append(entry)
    _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)

    entry["created_by_display"] = await _owner_display_name(entry["created_by"])
    return {"item": entry, "message": "Context item created"}


@router.put("/{item_id}")
async def update_context_item(item_id: str, req: ContextUpdateRequest, request: Request):
    """Update content and/or metadata of an existing item."""
    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, f"Context item '{item_id}' not found")
    enforce_context_access(request, item["path"], "write")

    # Ownership gate: only the creator or an admin may edit this item.
    _require_item_owner_or_admin(request, item)

    if req.name is not None:
        item["name"] = req.name
    if req.description is not None:
        item["description"] = req.description
    if req.skills is not None:
        item["skills"] = req.skills
        _patch_frontmatter_field(item.get("path", ""), "skills", req.skills, req.tenant_id)
    if req.status is not None:
        item["status"] = req.status
    item["updated_at"] = _now()

    if req.content is not None:
        md_content = _build_md(item, req.content)
        _write_content(item["path"], md_content, req.tenant_id)

    _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)
    return {"item": item, "message": "Updated"}


@router.delete("/{item_id}")
async def delete_context_item(item_id: str, request: Request, tenant_id: str = "company"):
    reg = _load_registry(tenant_id)
    items = reg.get("items", [])
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, f"Context item '{item_id}' not found")
    enforce_context_access(request, item["path"], "delete")

    # Ownership gate: only the creator or an admin may delete this item.
    _require_item_owner_or_admin(request, item)

    _delete_content(item["path"], tenant_id)
    reg["items"] = [i for i in items if i["id"] != item_id]
    _save_registry(reg, tenant_id)
    _invalidate_tree_cache(tenant_id)
    return {"message": f"Deleted '{item['name']}'"}


@router.get("/{item_id}/content")
async def get_context_content(request: Request, item_id: str, tenant_id: str = "company"):
    """Return raw markdown content for an item (for edit panel)."""
    reg = _load_registry(tenant_id)
    item = next((i for i in reg.get("items", []) if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, f"Context item '{item_id}' not found")
    enforce_context_access(request, item["path"], "read")

    raw = _read_content(item["path"], tenant_id)
    body = re.sub(r"^---\n.*?\n---\n\n?", "", raw, flags=re.DOTALL).strip()
    return {"content": body, "item": item}


_ALLOWED_UPLOAD_EXTS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".txt",
    ".md", ".csv", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg", ".gif",
    # Author-editable script/config text (parity with the file API allowlist).
    # Stored as inert text; execution stays gated by SafeKernel + entitlements.
    ".py", ".sh", ".sql",
    # Public TLS certificates only; private keys belong in the credential store, never the shared tree.
    ".crt", ".cer",
}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def upload_context_file(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(""),
    description: str = Form(""),
    item_type: str = Form("document"),
    skills: str = Form("[]"),
    status: str = Form("active"),
    tenant_id: str = Form("company"),
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Upload a file (PDF, DOCX, XLSX, TXT) and convert to markdown context."""
    # Multipart: the router dependency cannot read this tenant without consuming
    # the upload stream, so authorise it explicitly here.
    tenant_id = authorise_tenant(request, tenant_id)
    if item_type not in VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{item_type}'")

    filename = file.filename or "upload.bin"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(400, f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(_ALLOWED_UPLOAD_EXTS))}")
    filename = Path(filename).name.replace("..", "_").replace("/", "_").replace("\\", "_")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large (max {_MAX_UPLOAD_SIZE // (1024*1024)} MB)")

    body = _extract_file(file_bytes, filename)
    if not body:
        raise HTTPException(422, "Could not extract text from the uploaded file")

    try:
        skills_list = json.loads(skills)
    except Exception as e:
        logger.warning("Failed to parse skills JSON, defaulting to empty list: %s", e)
        skills_list = []

    display_name = name.strip() or Path(filename).stem.replace("_", " ").replace("-", " ").title()
    item_id = _slugify(display_name)

    reg = _load_registry(tenant_id)
    existing_ids = {i["id"] for i in reg.get("items", [])}
    if item_id in existing_ids:
        item_id = item_id + "_" + uuid.uuid4().hex[:4]

    sub_dir = TYPE_DIR.get(item_type, "contexts")
    virtual_path = f"/shared/{sub_dir}/{item_id}.md"

    md_content = _build_md(
        {"name": display_name, "type": item_type, "description": description,
         "status": status, "skills": skills_list,
         "created_by": _owner_identity(request)},
        body
    )
    _write_content(virtual_path, md_content, tenant_id)

    now = _now()
    entry = {
        "id": item_id,
        "name": display_name,
        "type": item_type,
        "description": description,
        "path": virtual_path,
        "source": filename,
        "source_url": None,
        "skills": skills_list,
        "status": status,
        "auto_refresh": None,
        "created_at": now,
        "updated_at": now,
        "created_by": _owner_identity(request),
    }
    reg.setdefault("items", []).append(entry)
    _save_registry(reg, tenant_id)
    _invalidate_tree_cache(tenant_id)

    entry["created_by_display"] = await _owner_display_name(entry["created_by"])
    return {
        "item": entry,
        "word_count": _word_count(body),
        "preview": body[:500],
        "message": "File uploaded and converted to context"
    }


@router.post("/fetch-url")
async def fetch_url_preview(url: str, name: str = "", tenant_id: str = "company"):
    """Fetch a URL and return extracted markdown preview (does not save)."""
    try:
        body = _fetch_url(url)
    except ValueError as e:
        # Deliberate, safe policy message (e.g. "blocked by egress policy: ...")
        # describing why the caller's own URL was rejected — not an internals leak.
        raise HTTPException(422, str(e))
    except Exception:
        logger.warning("fetch-url failed for %r", url)
        raise HTTPException(422, "Could not fetch URL")

    display_name = name.strip() or url.split("/")[-1] or "web_context"
    return {
        "name": display_name,
        "preview": body[:1000],
        "word_count": _word_count(body),
        "body": body,
    }


@router.post("/search")
async def semantic_search(req: SearchRequest):
    """
    LLM-powered semantic search across all context items.
    Returns ranked results with relevance score and matching excerpt.
    """
    if not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")

    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])
    if not items:
        return {"results": [], "query": req.query}

    results = []
    for item in items:
        raw = _read_content(item["path"], req.tenant_id)
        body = re.sub(r"^---\n.*?\n---\n\n?", "", raw, flags=re.DOTALL).strip()
        if not body:
            continue

        # Truncate to first 2000 chars to stay within token limits
        snippet = body[:2000]

        try:
            system = (
                "You are a relevance scoring assistant. Given a search query and a document excerpt, "
                "respond ONLY with valid JSON in this exact format:\n"
                '{"score": <0-100>, "excerpt": "<most relevant sentence from the document, max 180 chars>", '
                '"reason": "<one short sentence why this is relevant>"}\n'
                "If the document is not relevant at all, return score 0."
            )
            user = f"Query: {req.query}\n\nDocument ({item['name']}):\n{snippet}"
            resp_text = _llm_call(system, user)

            json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = int(data.get("score", 0))
                if score > 20:
                    results.append({
                        "item": item,
                        "score": score,
                        "excerpt": data.get("excerpt", ""),
                        "reason": data.get("reason", ""),
                    })
        except Exception as e:
            logger.warning("Search LLM call failed for %s: %s", item["id"], e)
            if req.query.lower() in body.lower():
                results.append({
                    "item": item,
                    "score": 40,
                    "excerpt": body[:180],
                    "reason": "Keyword match",
                })

    results.sort(key=lambda x: x["score"], reverse=True)

    # Check for conflicts in top results (surface as a warning)
    conflict_hint = None
    if len(results) >= 2:
        try:
            top_names = [r["item"]["name"] for r in results[:3]]
            conflict_hint = _quick_conflict_hint(
                [r["item"] for r in results[:3]], req.tenant_id
            )
        except Exception as e:
            logger.warning("Conflict hint check failed (non-fatal): %s", e)

    return {
        "results": results,
        "query": req.query,
        "total": len(results),
        "conflict_hint": conflict_hint,
    }


def _quick_conflict_hint(items: list, tenant_id: str) -> Optional[dict]:
    """Quick LLM check: do these items contradict each other? Returns hint or None."""
    if len(items) < 2:
        return None
    snippets = []
    for item in items[:3]:
        raw = _read_content(item["path"], tenant_id)
        body = re.sub(r"^---\n.*?\n---\n\n?", "", raw, flags=re.DOTALL).strip()
        snippets.append(f"[{item['name']}]:\n{body[:600]}")

    combined = "\n\n---\n\n".join(snippets)
    system = (
        "You are a conflict detection assistant. Given excerpts from multiple knowledge documents, "
        "identify if any contain contradicting facts, values, or rules.\n"
        'Respond ONLY with JSON: {"conflict": true/false, "description": "<brief description or empty string>"}'
    )
    try:
        resp_text = _llm_call(system, combined)
        json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            if data.get("conflict"):
                return {
                    "items": [i["name"] for i in items[:3]],
                    "description": data.get("description", "")
                }
    except Exception as e:
        logger.warning("Quick conflict hint LLM call failed: %s", e)
    return None


@router.post("/analyse-gap")
async def analyse_gap(req: GapAnalysisRequest):
    """
    LLM gap analysis for a skill: what context is it missing?
    """
    skills_path = Path(SKILLS_PATH)
    if not skills_path.is_absolute():
        skills_path = (SERVER_DIR / skills_path).resolve()

    skill_dir = skills_path / req.skill_name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(404, f"Skill '{req.skill_name}' not found")

    skill_content = skill_md.read_text(encoding="utf-8")

    reg = _load_registry(req.tenant_id)
    linked_items = [
        i for i in reg.get("items", [])
        if req.skill_name in (i.get("skills") or [])
    ]
    all_items = reg.get("items", [])
    unlinked_items = [i for i in all_items if i not in linked_items]

    linked_summary = "\n".join(
        f"- {i['name']} ({i['type']}): {i.get('description', '')}"
        for i in linked_items
    ) or "None"

    unlinked_summary = "\n".join(
        f"- {i['name']} ({i['type']}): {i.get('description', '')}"
        for i in unlinked_items[:20]
    ) or "None"

    system = (
        "You are an AI knowledge gap analyser. Given a skill definition and its current context files, "
        "identify what knowledge is likely missing for the skill to work well.\n\n"
        "Respond ONLY with valid JSON:\n"
        '{"missing": [{"title": "...", "reason": "..."}], '
        '"should_link": [{"id": "...", "name": "...", "reason": "..."}], '
        '"summary": "one sentence summary"}'
    )
    user = (
        f"SKILL DEFINITION:\n{skill_content[:1500]}\n\n"
        f"CURRENTLY LINKED CONTEXT:\n{linked_summary}\n\n"
        f"OTHER AVAILABLE CONTEXT (not linked):\n{unlinked_summary}"
    )

    try:
        resp_text = _llm_call(system, user)
        json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            enriched_link = []
            for suggestion in data.get("should_link", []):
                match = next(
                    (i for i in unlinked_items
                     if i["id"] == suggestion.get("id") or i["name"] == suggestion.get("name")),
                    None
                )
                if match:
                    enriched_link.append({**match, "reason": suggestion.get("reason", "")})
                else:
                    enriched_link.append(suggestion)

            return {
                "skill": req.skill_name,
                "linked": linked_items,
                "missing": data.get("missing", []),
                "should_link": enriched_link,
                "summary": data.get("summary", ""),
            }
    except Exception as e:
        logger.exception("analyse_gap failed")
        raise HTTPException(500, "An internal error occurred")

    raise HTTPException(500, "Could not parse gap analysis response")


@router.post("/check-conflicts")
async def check_conflicts(req: ConflictRequest):
    """
    LLM conflict detection across context items.
    Checks pairs of active items for contradicting facts/rules.
    """
    reg = _load_registry(req.tenant_id)
    items = [
        i for i in reg.get("items", [])
        if i.get("status") == "active"
        and (req.item_ids is None or i["id"] in req.item_ids)
    ]

    if len(items) < 2:
        return {"conflicts": [], "checked": len(items), "message": "Need at least 2 active items"}

    conflicts = []
    checked_pairs = set()

    # Check pairs — limit to 10 pairs to avoid excessive LLM calls
    import itertools
    pairs = list(itertools.combinations(items, 2))[:10]

    for item_a, item_b in pairs:
        pair_key = tuple(sorted([item_a["id"], item_b["id"]]))
        if pair_key in checked_pairs:
            continue
        checked_pairs.add(pair_key)

        body_a = re.sub(r"^---\n.*?\n---\n\n?",
                        "", _read_content(item_a["path"], req.tenant_id), flags=re.DOTALL).strip()
        body_b = re.sub(r"^---\n.*?\n---\n\n?",
                        "", _read_content(item_b["path"], req.tenant_id), flags=re.DOTALL).strip()

        if not body_a or not body_b:
            continue

        system = (
            "You are a conflict detection assistant. Compare two knowledge documents for contradictions "
            "in facts, rules, thresholds, or procedures.\n"
            'Respond ONLY with JSON: {"conflict": true/false, '
            '"quote_a": "<relevant quote from doc A, max 120 chars>", '
            '"quote_b": "<relevant quote from doc B, max 120 chars>", '
            '"description": "<brief description of conflict>"}'
        )
        user = (
            f"Document A — {item_a['name']}:\n{body_a[:800]}\n\n"
            f"Document B — {item_b['name']}:\n{body_b[:800]}"
        )

        try:
            resp_text = _llm_call(system, user)
            json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("conflict"):
                    conflicts.append({
                        "item_a": {"id": item_a["id"], "name": item_a["name"]},
                        "item_b": {"id": item_b["id"], "name": item_b["name"]},
                        "quote_a": data.get("quote_a", ""),
                        "quote_b": data.get("quote_b", ""),
                        "description": data.get("description", ""),
                    })
        except Exception as e:
            logger.warning("Conflict check failed for %s/%s: %s", item_a["id"], item_b["id"], e)

    return {
        "conflicts": conflicts,
        "checked_pairs": len(checked_pairs),
        "total_items": len(items),
        "timestamp": _now(),
    }


@router.post("/check-impact")
async def check_impact(req: ImpactRequest):
    """
    LLM impact analysis: given old vs new content of a context item,
    which linked skills might be affected and how?
    """
    reg = _load_registry(req.tenant_id)
    item = next((i for i in reg.get("items", []) if i["id"] == req.item_id), None)
    if not item:
        raise HTTPException(404, f"Item '{req.item_id}' not found")

    linked_skills = item.get("skills", [])
    if not linked_skills:
        return {"impact": [], "message": "No skills linked — no impact"}

    skills_path = Path(SKILLS_PATH)
    if not skills_path.is_absolute():
        skills_path = (SERVER_DIR / skills_path).resolve()

    skill_descriptions = []
    for sname in linked_skills[:5]:
        skill_md = skills_path / sname / "SKILL.md"
        if skill_md.exists():
            raw = skill_md.read_text(encoding="utf-8")
            fm_match = re.match(r"^---\n(.*?)\n---", raw, re.DOTALL)
            desc = ""
            if fm_match:
                try:
                    import yaml
                    fm = yaml.safe_load(fm_match.group(1)) or {}
                    desc = fm.get("description", "")
                except Exception as e:
                    logger.warning("Failed to parse skill frontmatter for impact check: %s", e)
            skill_descriptions.append(f"- {sname}: {desc}")
        else:
            skill_descriptions.append(f"- {sname}: (description unavailable)")

    system = (
        "You are an AI impact analysis assistant. Given an old and new version of a knowledge document, "
        "and a list of skills that depend on it, identify which skills are affected and how.\n\n"
        "Respond ONLY with valid JSON:\n"
        '{"impact": [{"skill": "...", "affected": true/false, "how": "..."}], '
        '"summary": "one sentence summary", "high_risk": true/false}'
    )
    user = (
        f"CONTEXT ITEM: {item['name']}\n\n"
        f"OLD CONTENT (first 600 chars):\n{req.old_content[:600]}\n\n"
        f"NEW CONTENT (first 600 chars):\n{req.new_content[:600]}\n\n"
        f"LINKED SKILLS:\n" + "\n".join(skill_descriptions)
    )

    try:
        resp_text = _llm_call(system, user)
        json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "item": item,
                "impact": data.get("impact", []),
                "summary": data.get("summary", ""),
                "high_risk": data.get("high_risk", False),
            }
    except Exception as e:
        logger.exception("check_impact failed")
        raise HTTPException(500, "An internal error occurred")

    raise HTTPException(500, "Could not parse impact response")


@router.get("/tree")
async def get_context_tree(tenant_id: str = "company"):
    """
    Return an LLM-clustered tree of all context items with orphan detection.
    Result is cached for 1 hour (or until item count changes or reindex is called).
    """
    reg = _load_registry(tenant_id)
    items = reg.get("items", [])

    cached = _load_tree_cache(tenant_id, len(items))
    if cached:
        cached["cache_hit"] = True
        return cached

    result = _build_tree_data(items, tenant_id)
    result["last_indexed"] = _now()
    result["total_items"] = len(items)
    result["cache_hit"] = False
    _save_tree_cache(result, tenant_id)
    return result


@router.post("/reindex")
async def reindex_context_tree(tenant_id: str = "company"):
    """Force full disk re-scan + LLM re-clustering. Clears cached tree."""
    _invalidate_tree_cache(tenant_id)
    reg = _autodiscover(tenant_id)
    items = reg.get("items", [])

    result = _build_tree_data(items, tenant_id)
    result["last_indexed"] = _now()
    result["total_items"] = len(items)
    result["cache_hit"] = False
    _save_tree_cache(result, tenant_id)
    return result


_ASSET_EXTENSIONS = {
    ".db", ".sqlite", ".sqlite3",        # databases
    ".log", ".jsonl",                    # logs
    ".csv", ".tsv",                      # tabular data
    ".json",                             # raw JSON
    ".pdf", ".docx", ".pptx", ".xlsx",  # original uploads
    ".mp3", ".mp4", ".wav",              # audio/video transcripts
    ".txt",                              # plain text
}

_ASSET_TYPE_MAP = {
    ".db": "database", ".sqlite": "database", ".sqlite3": "database",
    ".log": "log", ".jsonl": "log",
    ".csv": "tabular", ".tsv": "tabular", ".json": "tabular",
    ".pdf": "document", ".docx": "document", ".pptx": "document", ".xlsx": "document",
    ".mp3": "audio", ".mp4": "video", ".wav": "audio",
    ".txt": "text",
}

_ASSET_ICON_MAP = {
    "database": "🗄", "log": "📋", "tabular": "📊",
    "document": "📄", "audio": "🎙", "video": "🎬", "text": "📝",
}

_SCAN_ASSET_DIRS = ["databases", "logs", "transcripts", "data", "knowledge", "contexts", "policies"]

_BROWSER_HIDDEN = {"context_registry.json", "context_tree_cache.json", ".gitkeep"}


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _file_meta(f: Path, folder_name: str) -> dict:
    """Build a file metadata dict for one file."""
    ext = f.suffix.lower()
    if ext == ".md":
        asset_type = "markdown"
        icon = "📝"
    else:
        asset_type = _ASSET_TYPE_MAP.get(ext, "file")
        icon = _ASSET_ICON_MAP.get(asset_type, "📄")
    stat = f.stat()
    return {
        "name": f.name,
        "path": f"/shared/{folder_name}/{f.name}",
        "ext": ext,
        "type": asset_type,
        "icon": icon,
        "is_md": ext == ".md",
        "is_db": ext in (".db", ".sqlite", ".sqlite3"),
        "size_bytes": stat.st_size,
        "size_label": _fmt_size(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _list_all_folders(tenant_id: str) -> list:
    """Return every subfolder under shared/ (including empty ones)."""
    shared = _shared_dir(tenant_id)
    folders = []
    if not shared.exists():
        return folders
    for d in sorted(shared.iterdir()):
        # not d.is_symlink(): a symlinked dir would let _browse_folder enumerate
        # files outside the tenant tree through the assets API.
        if d.is_dir() and not d.is_symlink() and not d.name.startswith(".") and d.name not in ("__pycache__",):
            file_count = sum(
                1 for f in d.iterdir()
                if f.is_file() and not f.is_symlink() and f.name not in _BROWSER_HIDDEN
                and not _is_protected_file(f"/shared/{d.name}/{f.name}")
            )
            folders.append({"folder": d.name, "file_count": file_count})
    return folders


def _browse_folder(folder_name: str, tenant_id: str) -> list:
    """Return all files inside shared/<folder_name>/, sorted."""
    shared = _shared_dir(tenant_id)
    dir_path = shared / folder_name
    if not dir_path.exists():
        return []
    # Containment: the folder must resolve to a real directory INSIDE the tenant
    # shared tree (a symlinked dir could point outside it and leak files).
    try:
        if dir_path.is_symlink():
            return []
        dir_path.resolve().relative_to(shared.resolve())  # raises if it escaped
    except (ValueError, OSError):
        return []
    files = []
    for f in sorted(dir_path.iterdir()):
        # Skip symlinks: is_file() follows links, so an innocuous-named symlink
        # could otherwise surface (and later be read) as protected material.
        if (f.is_file() and not f.is_symlink() and f.name not in _BROWSER_HIDDEN
                and not _is_protected_file(f"/shared/{folder_name}/{f.name}")):
            files.append(_file_meta(f, folder_name))
    return files


@router.get("/files/assets")
async def list_assets(tenant_id: str = "company"):
    """List all subfolders + their raw asset files."""
    folders = _list_all_folders(tenant_id)
    return {"folders": folders, "total": sum(f["file_count"] for f in folders)}


@router.get("/files/browse")
async def browse_folder(folder: str = "contexts", tenant_id: str = "company"):
    """Return folder list + files inside the selected folder."""
    safe_folder = re.sub(r"[^\w\-]", "_", folder.strip())
    all_folders = _list_all_folders(tenant_id)
    files = _browse_folder(safe_folder, tenant_id)
    return {"folders": all_folders, "current": safe_folder, "files": files}


@router.post("/files/upload")
async def upload_to_folder(
    request: Request,
    folder: str = Form(...),
    tenant_id: str = Form("company"),
    file: UploadFile = File(...),
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Upload any file to shared/<folder>/. Returns file metadata."""
    # Multipart: authorise explicitly (see require_context_tenant).
    tenant_id = authorise_tenant(request, tenant_id)
    fname = file.filename or "upload.bin"
    ext = Path(fname).suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(400, f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(_ALLOWED_UPLOAD_EXTS))}")

    safe_folder = re.sub(r"[^\w\-]", "_", folder.strip())
    safe_name = re.sub(r"[^\w\.\-]", "_", Path(fname).name)

    # Enforce the protected-file policy on the destination; the listing filter is not an access control.
    if _is_protected_file(f"/shared/{safe_folder}/{safe_name}"):
        raise HTTPException(403, "This destination is protected and cannot be written via the file API.")

    shared = _shared_dir(tenant_id)
    dest_dir = shared / safe_folder
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / safe_name
    # Ownership gate before overwrite: .md carry created_by; other existing files are admin-only.
    if dest.exists():
        if dest.suffix.lower() == ".md":
            _require_item_owner_or_admin(request, {"created_by": _file_owner(dest)})
        else:
            _require_item_owner_or_admin(request, {"created_by": None})
    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large (max {_MAX_UPLOAD_SIZE // (1024*1024)} MB)")
    import tempfile as _tf, os as _os
    with _tf.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".tmp") as _f:
        _f.write(content); _tmp = _f.name
    _os.replace(_tmp, str(dest))
    logger.info("Uploaded %s → %s", safe_name, dest)
    file_meta = _file_meta(dest, safe_folder)
    conversion = _detect_conversion(safe_name)
    return {"ok": True, "file": file_meta, "conversion": conversion}


class CreateMdRequest(BaseModel):
    folder: str
    filename: str          # e.g. "vendor_policy.md"
    content: str = ""
    register: bool = True  # also add to context registry?
    item_type: str = "document"
    item_name: str = ""
    tenant_id: str = "company"


@router.post("/files/create-md")
async def create_md_file(req: CreateMdRequest, request: Request, _perm: dict = Depends(require_permission("skills.author"))):
    """Create a new .md file inside shared/<folder>/."""
    bind_request_identity(request, req.tenant_id)
    safe_folder = re.sub(r"[^\w\-]", "_", req.folder.strip())
    safe_name = re.sub(r"[^\w\.\-]", "_", req.filename.strip())
    if not safe_name.endswith(".md"):
        safe_name += ".md"

    shared = _shared_dir(req.tenant_id)
    dest_dir = shared / safe_folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name

    display_name = req.item_name or Path(safe_name).stem.replace("_", " ").replace("-", " ").title()
    item_type = req.item_type if req.item_type in VALID_TYPES else "document"
    _creator = _owner_identity(request)

    md_content = (
        f"---\nname: {display_name}\ntype: {item_type}\n"
        f"description: \nstatus: active\nskills: []\nlinked_assets: []\n"
        f"created_by: {_creator}\n---\n\n"
        f"{req.content.strip()}\n"
    )
    atomic_write_text(dest, md_content)

    result: dict = {"ok": True, "file": _file_meta(dest, safe_folder)}

    if req.register:
        reg = _load_registry(req.tenant_id)
        items = reg.get("items", [])
        item_id = Path(safe_name).stem
        virtual_path = f"/shared/{safe_folder}/{safe_name}"
        now = _now()
        if not any(i["id"] == item_id for i in items):
            items.append({
                "id": item_id, "name": display_name, "type": item_type,
                "description": "", "path": virtual_path,
                "source": None, "source_url": None,
                "skills": [], "linked_assets": [],
                "status": "active", "auto_refresh": None,
                "created_at": now, "updated_at": now,
                "created_by": _creator,
            })
            reg["items"] = items
            _save_registry(reg, req.tenant_id)
            _invalidate_tree_cache(req.tenant_id)
        result["registered"] = True
        result["item_id"] = item_id

    return result


@router.get("/files/read")
async def read_file_content(request: Request, path: str, tenant_id: str = "company"):
    """Read content of any file under shared/."""
    # Validate the tenant against the caller before resolving the path, else a cross-tenant read is possible.
    bind_request_identity(request, tenant_id)
    # Per-item policy guard (restricted-folder deny etc.).
    enforce_context_access(request, path, "read")
    # Traversal-, symlink- and protected-safe resolution.
    full_path = _safe_shared_file(path, tenant_id)
    try:
        _owner = _file_owner(full_path)
        return {
            "content": full_path.read_text(encoding="utf-8", errors="replace"),
            "path": path,
            "created_by": _owner,
            "created_by_display": await _owner_display_name(_owner),
        }
    except Exception as e:
        logger.exception("read_file_content failed")
        raise HTTPException(500, "An internal error occurred")


class SaveFileRequest(BaseModel):
    path: str
    content: str
    tenant_id: str = "company"


@router.post("/files/save")
async def save_file_content(req: SaveFileRequest, request: Request):
    """Overwrite an existing .md file's content."""
    bind_request_identity(request, req.tenant_id)
    # Per-item policy guard before the traversal-safe resolve and owner gate.
    enforce_context_access(request, req.path, "write")
    # Traversal-/symlink-/protected-safe before the role-independent policy and
    # the owner/admin gate below.
    full_path = _safe_shared_file(req.path, req.tenant_id)

    # Ownership gate: only the file's creator or an admin may overwrite it.
    _owner = _file_owner(full_path)
    _require_file_owner_or_admin(request, full_path)

    # Keep created_by stable across edits (re-inject if the editor dropped it).
    content = _ensure_created_by(req.content, _owner)
    atomic_write_text(full_path, content)
    item_id = full_path.stem
    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])
    item = next((i for i in items if i["id"] == item_id), None)
    if item:
        item["updated_at"] = _now()
        _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)
    return {"ok": True}


@router.delete("/files/delete")
async def delete_file(path: str, request: Request, tenant_id: str = "company"):
    """Delete a file from shared/ and remove from registry if tracked."""
    bind_request_identity(request, tenant_id)
    # Per-item policy guard before the traversal-safe resolve and owner gate.
    enforce_context_access(request, path, "delete")
    # Traversal-/symlink-/protected-safe (enforces tenant containment) before the
    # role-independent policy and the owner/admin gate below.
    full_path = _safe_shared_file(path, tenant_id)

    # Ownership gate: only the file's creator or an admin may delete it.
    if full_path.suffix.lower() == ".md":
        _require_file_owner_or_admin(request, full_path)
    else:
        _require_item_owner_or_admin(request, {"created_by": None})

    full_path.unlink()
    item_id = full_path.stem
    reg = _load_registry(tenant_id)
    items = [i for i in reg.get("items", []) if i["id"] != item_id]
    reg["items"] = items
    _save_registry(reg, tenant_id)
    _invalidate_tree_cache(tenant_id)
    return {"ok": True}


class ConvertToContextRequest(BaseModel):
    asset_path: str          # e.g. /shared/databases/vendor_report.pdf
    name: Optional[str] = None
    item_type: str = "document"
    target_folder: str = "contexts"
    tenant_id: str = "company"


@router.post("/files/convert")
async def convert_to_context(req: ConvertToContextRequest, request: Request):
    """
    Read a raw file (PDF, DOCX, CSV, TXT), extract text via markitdown,
    create a context .md in target_folder, and register it.
    """
    bind_request_identity(request, req.tenant_id)
    # Traversal-/symlink-/protected-safe: never convert files outside the tenant shared tree or protected secrets.
    src = _safe_shared_file(req.asset_path, req.tenant_id)

    raw_bytes = src.read_bytes()
    content_body = _extract_file(raw_bytes, src.name)
    if not content_body.strip():
        raise HTTPException(422, "Could not extract text from file")

    display_name = req.name or src.stem.replace("_", " ").replace("-", " ").title()
    item_type = req.item_type if req.item_type in VALID_TYPES else "document"
    item_id = _slugify(display_name)
    target_folder = re.sub(r"[^\w\-]", "_", req.target_folder.strip())

    shared = _shared_dir(req.tenant_id)
    dest_dir = shared / target_folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{item_id}.md"

    md_content = (
        f"---\nname: {display_name}\ntype: {item_type}\n"
        f"description: Converted from {src.name}\nstatus: active\n"
        f"skills: []\nlinked_assets: [{req.asset_path}]\n---\n\n{content_body.strip()}\n"
    )
    atomic_write_text(dest, md_content)

    virtual_path = f"/shared/{target_folder}/{item_id}.md"
    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])
    now = _now()
    existing = next((i for i in items if i["id"] == item_id), None)
    if existing:
        existing.update({"name": display_name, "type": item_type, "path": virtual_path,
                         "linked_assets": [req.asset_path], "updated_at": now})
    else:
        items.append({
            "id": item_id, "name": display_name, "type": item_type,
            "description": f"Converted from {src.name}",
            "path": virtual_path, "source": src.name, "source_url": None,
            "skills": [], "linked_assets": [req.asset_path],
            "status": "active", "auto_refresh": None,
            "created_at": now, "updated_at": now,
        })
    reg["items"] = items
    _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)
    return {"ok": True, "item_id": item_id, "path": virtual_path, "word_count": _word_count(content_body)}


class LinkAssetRequest(BaseModel):
    asset_path: str          # e.g. /shared/databases/ap_regular.db
    tenant_id: str = "company"


@router.post("/{item_id}/link-asset")
async def link_asset(item_id: str, req: LinkAssetRequest):
    """Link a raw data file to a context .md item (stored in registry + frontmatter)."""
    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, f"Context item '{item_id}' not found")

    linked = item.get("linked_assets") or []
    if req.asset_path not in linked:
        linked.append(req.asset_path)
    item["linked_assets"] = linked
    item["updated_at"] = _now()

    # Also patch frontmatter in the .md file
    _patch_frontmatter_field(item["path"], "linked_assets", linked, req.tenant_id)

    _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)
    return {"ok": True, "linked_assets": linked}


async def get_routing_map(tenant_id: str = "company"):
    """
    Parse Enterprise_Context.md (type:root) and any taxonomy files (type:taxonomy)
    into a semantic L1→L5 tree.  Fully generic — driven by frontmatter conventions
    and markdown heading/table structure.  No domain names hardcoded.
    """
    shared = _shared_dir(tenant_id)

    def _strip_backticks(s: str) -> list[str]:
        """Extract all `path` tokens from a markdown cell."""
        return re.findall(r"`([^`]+)`", s)

    def _normalise_path(raw: str) -> str:
        """Convert context/foo.md or contexts/foo.md → shared/contexts/foo.md."""
        raw = raw.strip().strip("`")
        if raw.startswith("shared/"):
            return raw
        raw = raw.lstrip("/")
        if raw.startswith("context/") and not raw.startswith("contexts/"):
            raw = "contexts/" + raw[len("context/"):]
        return "shared/" + raw

    def _parse_md_table(lines: list[str], start: int) -> tuple[list[str], list[dict], int]:
        """
        Parse a markdown pipe table starting at line index `start`.
        Returns (headers, rows_as_dicts, next_line_index).
        """
        headers: list[str] = []
        rows: list[dict] = []
        i = start
        while i < len(lines) and not lines[i].startswith("|"):
            i += 1
        if i >= len(lines):
            return [], [], i
        headers = [h.strip() for h in lines[i].split("|") if h.strip()]
        i += 1
        if i < len(lines) and re.match(r"^\|[\s\-|]+\|?\s*$", lines[i]):
            i += 1
        while i < len(lines) and lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].split("|")]
            cells = [c for j, c in enumerate(cells) if j > 0 and j <= len(headers)]
            row = {headers[j]: cells[j] if j < len(cells) else "" for j in range(len(headers))}
            rows.append(row)
            i += 1
        return headers, rows, i

    def _parse_root(content: str) -> dict:
        """
        Parse a type:root file.
        Extracts L1 name and L2 domains with their file role → path mappings.
        Finds the table whose header contains 'Process' (or first column).
        """
        lines = content.splitlines()
        l1_name = "L1"
        domains: list[dict] = []

        for line in lines:
            m = re.match(r"^##\s+L1[:\s]+(.+)", line)
            if m:
                l1_name = m.group(1).strip()
                break

        # Find the L2 process map table (header row contains 'Process')
        tbl_start = None
        for idx, line in enumerate(lines):
            if line.startswith("|") and "Process" in line:
                tbl_start = idx
                break
        if tbl_start is None:
            return {"l1": l1_name, "domains": domains}

        headers, rows, _ = _parse_md_table(lines, tbl_start)

        for row in rows:
            proc = row.get("Process", "").strip()
            if not proc or proc.startswith("_"):
                continue
            status = "future" if re.search(r"future|placeholder|—", proc, re.I) else "active"
            # collect file roles — every column except Process, Aliases, Skills
            skip_cols = {"Process", "Aliases", "Skills"}
            files_by_role: dict[str, list[str]] = {}
            for col, val in row.items():
                if col in skip_cols or not val or val in ("—", "_Future_", ""):
                    continue
                paths = _strip_backticks(val)
                if not paths:
                    cleaned = val.strip().strip("`")
                    if cleaned and "/" in cleaned:
                        paths = [cleaned]
                if paths:
                    files_by_role[col] = [_normalise_path(p) for p in paths]
            domains.append({
                "name": proc,
                "status": status,
                "skills": [s.strip() for s in row.get("Skills", "").split(",") if s.strip() and s.strip() != "—"],
                "files": files_by_role,
                "taxonomy": None,  # filled later
            })
        return {"l1": l1_name, "domains": domains}

    def _parse_taxonomy(content: str) -> list[dict]:
        """
        Parse a type:taxonomy file.
        Uses heading depth to build L3→L4→L5 hierarchy.
        ## → L2 (ignored — we already know the domain)
        ### or #### → L3
        #### or ##### → L4  (with optional [itil-tag])
        pipe table rows under L4 → L5 activities
        Returns list of L3 group dicts.
        """
        lines = content.splitlines()
        l3_groups: list[dict] = []
        cur_l3: dict | None = None
        cur_l4: dict | None = None
        in_table = False
        tbl_headers: list[str] = []
        i = 0

        # Detect heading depth for L3/L4: taxonomy files use ####L3/#####L4 or ###L3/####L4.
        l3_depth = 4   # default: #### = L3
        l4_depth = 5   # default: ##### = L4
        for line in lines:
            m3 = re.match(r"^(#{3,6})\s+L3", line)
            if m3:
                l3_depth = len(m3.group(1))
                l4_depth = l3_depth + 1
                break

        while i < len(lines):
            line = lines[i]

            h_match = re.match(r"^(#{2,6})\s+(.*)", line)
            if h_match:
                depth = len(h_match.group(1))
                title_raw = h_match.group(2).strip()

                if depth == l3_depth:
                    # L3 group — strip "L3:" prefix if present
                    title = re.sub(r"^L3[:\s]+", "", title_raw).strip()
                    cur_l3 = {"name": title, "l4_groups": []}
                    l3_groups.append(cur_l3)
                    cur_l4 = None
                    in_table = False

                elif depth == l4_depth and cur_l3 is not None:
                    # L4 group — strip "L4:" prefix and extract [itil-tag]
                    title = re.sub(r"^L4[:\s]+", "", title_raw).strip()
                    itil_tag = ""
                    tag_m = re.search(r"`\[([^\]]+)\]`|\[([^\]]+)\]", title)
                    if tag_m:
                        itil_tag = (tag_m.group(1) or tag_m.group(2)).strip()
                        title = title[:tag_m.start()].strip()
                    cur_l4 = {"name": title, "itil_tag": itil_tag, "activities": []}
                    cur_l3["l4_groups"].append(cur_l4)
                    in_table = False
                    tbl_headers = []

                i += 1
                continue

            if line.startswith("|") and cur_l4 is not None:
                if not tbl_headers and "---" not in line:
                    tbl_headers = [h.strip() for h in line.split("|") if h.strip()]
                    i += 1
                    continue
                if re.match(r"^\|[\s\-|]+\|?\s*$", line):
                    i += 1
                    continue
                if tbl_headers:
                    cells = [c.strip() for c in line.split("|")]
                    cells = [c for j, c in enumerate(cells) if j > 0 and j <= len(tbl_headers)]
                    row = {tbl_headers[j]: cells[j] if j < len(cells) else "" for j in range(len(tbl_headers))}
                    # First column = activity name (L5)
                    name_col = tbl_headers[0] if tbl_headers else "L5"
                    act_name = row.get(name_col, "").strip()
                    if act_name and not act_name.startswith("---"):
                        activity = {"name": act_name}
                        for col in tbl_headers[1:]:
                            val = row.get(col, "").strip()
                            if val and val != "—":
                                activity[col.lower().replace(" ", "_")] = val
                        cur_l4["activities"].append(activity)
                i += 1
                continue

            if not line.startswith("|") and tbl_headers:
                tbl_headers = []

            i += 1

        return l3_groups

    # Step 1: find root file
    root_content = None
    for md in sorted(shared.glob("*.md")):
        try:
            raw = md.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(raw)
            if fm.get("type") == "root":
                root_content = raw
                break
        except Exception:
            continue

    if not root_content:
        return {"l1": "No root context found", "domains": []}

    tree = _parse_root(root_content)

    # Step 2: for each domain, find its taxonomy file and parse it
    for domain in tree["domains"]:
        taxonomy_paths = domain["files"].get("Taxonomy", [])
        for tax_path in taxonomy_paths:
            rel = tax_path.lstrip("/")
            if rel.startswith("shared/"):
                rel = rel[len("shared/"):]
            full = shared / rel
            if full.exists():
                try:
                    tax_content = full.read_text(encoding="utf-8", errors="replace")
                    domain["taxonomy"] = _parse_taxonomy(tax_content)
                except Exception as e:
                    logger.warning("routing-map: failed to parse taxonomy %s: %s", full, e)
                break

    return tree


@router.delete("/{item_id}/link-asset")
async def unlink_asset(item_id: str, asset_path: str, tenant_id: str = "company"):
    """Remove a raw data file link from a context .md item."""
    reg = _load_registry(tenant_id)
    items = reg.get("items", [])
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, f"Context item '{item_id}' not found")

    linked = [a for a in (item.get("linked_assets") or []) if a != asset_path]
    item["linked_assets"] = linked
    item["updated_at"] = _now()

    _patch_frontmatter_field(item["path"], "linked_assets", linked, tenant_id)

    _save_registry(reg, tenant_id)
    _invalidate_tree_cache(tenant_id)
    return {"ok": True, "linked_assets": linked}


def _patch_frontmatter_field(virtual_path: str, field: str, value, tenant_id: str) -> None:
    """Update or add a single frontmatter field in a .md file without touching body."""
    try:
        p = _content_path(virtual_path, tenant_id)
        if not p.exists():
            return
        raw = p.read_text(encoding="utf-8")
        import yaml as _yaml
        m = re.match(r"^---\n(.*?)\n---\n?(.*)", raw, re.DOTALL)
        if m:
            fm_dict = _yaml.safe_load(m.group(1)) or {}
            body = m.group(2)
        else:
            fm_dict = {}
            body = raw
        fm_dict[field] = value
        fm_str = _yaml.dump(fm_dict, default_flow_style=False, allow_unicode=True).strip()
        atomic_write_text(p, f"---\n{fm_str}\n---\n{body}")
    except Exception as exc:
        logger.warning("Could not patch frontmatter field %s: %s", field, exc)


class FolderCreateRequest(BaseModel):
    folder_name: str
    tenant_id: str = "company"


@router.post("/files/folder")
async def create_folder(req: FolderCreateRequest, request: Request, _perm: dict = Depends(require_permission("skills.author"))):
    """Create a new subdirectory under the tenant shared/ directory."""
    bind_request_identity(request, req.tenant_id)
    # Sanitise: allow only alphanumeric + underscore/hyphen
    safe_name = re.sub(r"[^\w\-]", "_", req.folder_name.strip().lower())
    if not safe_name:
        raise HTTPException(400, "Invalid folder name")
    shared = _shared_dir(req.tenant_id)
    new_dir = shared / safe_name
    if new_dir.exists():
        raise HTTPException(409, f"Folder '{safe_name}' already exists")
    new_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(new_dir / ".gitkeep", "")
    return {"ok": True, "folder": safe_name, "path": f"/shared/{safe_name}/"}


class IntrospectRequest(BaseModel):
    asset_path: str          # e.g. /shared/databases/ap_regular.db
    name: Optional[str] = None
    tenant_id: str = "company"


@router.post("/files/introspect-db")
async def introspect_db(req: IntrospectRequest):
    """
    Read a SQLite .db file, extract table/column/row-count info,
    auto-generate a schema .md, register it, and link the asset.
    """
    import sqlite3
    from iaf_agent_skills.sqlite_util import connect as _sqlite_connect

    shared = _shared_dir(req.tenant_id)
    rel = req.asset_path.lstrip("/")
    if rel.startswith("shared/"):
        rel = rel[len("shared/"):]
    db_file = shared / rel
    if not db_file.exists():
        raise HTTPException(404, f"File not found: {req.asset_path}")
    if db_file.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        raise HTTPException(400, "Only SQLite files are supported")

    # Safe table names only; rejects SQL metacharacters (second-order injection into PRAGMA).
    _SAFE_TBL_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')

    def _quote_sqlite_identifier(name: str) -> str:
        """Return a safely quoted SQLite identifier for trusted table names."""
        if not _SAFE_TBL_RE.match(name):
            raise ValueError(f"Unsafe table name: {name!r}")
        return f'"{name}"'

    try:
        conn = _sqlite_connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        table_info = []
        for tbl in tables:
            try:
                if not _SAFE_TBL_RE.match(tbl):
                    logger.warning("introspect_db: skipping table with unsafe name %r", tbl)
                    continue
                cursor.execute(
                    "SELECT name, type, \"notnull\", pk FROM pragma_table_info(?)",
                    (tbl,),
                )
                cols = [{"name": r[0], "type": r[1], "notnull": bool(r[2]), "pk": bool(r[3])}
                        for r in cursor.fetchall()]
                # Avoid dynamic SQL against table identifiers during introspection.
                row_count = 0
                table_info.append({"table": tbl, "columns": cols, "row_count": row_count})
            except Exception as e:
                logger.warning("Failed to introspect SQLite table %s: %s", tbl, e)
                table_info.append({"table": tbl, "columns": [], "row_count": 0})
        conn.close()
    except Exception as e:
        logger.exception("introspect_db: SQLite read failed")
        raise HTTPException(500, "An internal error occurred")

    db_name = req.name or db_file.stem.replace("_", " ").replace("-", " ").title()
    md_lines = [f"# {db_name}\n", f"**Source file:** `{db_file.name}`\n",
                f"**Tables:** {len(tables)}  |  **Total rows (approx):** "
                f"{sum(t['row_count'] for t in table_info):,}\n"]
    for t in table_info:
        md_lines.append(f"\n## {t['table']}  ({t['row_count']:,} rows)\n")
        if t["columns"]:
            md_lines.append("| Column | Type | PK | Not Null |\n|---|---|---|---|")
            for c in t["columns"]:
                pk = "✓" if c["pk"] else ""
                nn = "✓" if c["notnull"] else ""
                md_lines.append(f"| {c['name']} | {c['type']} | {pk} | {nn} |")
    content_body = "\n".join(md_lines)

    item_id = f"{db_file.stem}_schema"
    virtual_path = f"/shared/databases/{item_id}.md"
    full_path = shared / "databases" / f"{item_id}.md"
    full_path.parent.mkdir(parents=True, exist_ok=True)

    linked_assets_list = [req.asset_path]
    md_content = (
        f"---\n"
        f"name: {db_name}\n"
        f"type: database\n"
        f"description: Auto-generated schema for {db_file.name}\n"
        f"status: active\n"
        f"skills: []\n"
        f"linked_assets: [{req.asset_path}]\n"
        f"---\n\n{content_body}\n"
    )
    atomic_write_text(full_path, md_content)

    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])
    existing = next((i for i in items if i["id"] == item_id), None)
    now = _now()
    if existing:
        existing.update({
            "name": db_name, "type": "database", "path": virtual_path,
            "linked_assets": linked_assets_list, "updated_at": now,
        })
    else:
        items.append({
            "id": item_id, "name": db_name, "type": "database",
            "description": f"Auto-generated schema for {db_file.name}",
            "path": virtual_path, "source": None, "source_url": None,
            "skills": [], "linked_assets": linked_assets_list,
            "status": "active", "auto_refresh": None,
            "created_at": now, "updated_at": now,
        })
    reg["items"] = items
    _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)

    return {
        "ok": True, "item_id": item_id, "path": virtual_path,
        "tables": len(tables), "linked_assets": linked_assets_list,
    }


class ScanSkillsRequest(BaseModel):
    tenant_id: str = "company"


@router.post("/scan-skills")
async def scan_skills(req: ScanSkillsRequest):
    """
    Scan all SKILL.md files in IAF-Agent-Skills. For each skill, inspect its
    YAML frontmatter for `databases` references and match to context registry
    items. Populates the skills[] field on matched items automatically.
    """
    import yaml as _yaml

    skills_root = Path(SKILLS_PATH)
    if not skills_root.is_absolute():
        skills_root = (SERVER_DIR / skills_root).resolve()

    if not skills_root.exists():
        raise HTTPException(404, f"Skills directory not found: {skills_root}")

    reg = _load_registry(req.tenant_id)
    items = reg.get("items", [])

    # Build lookup: canonical filename (stem) → item, and path tail → item
    path_to_item: dict[str, dict] = {}
    for it in items:
        p = it.get("path", "")
        # key by last path component without extension
        stem = Path(p).stem.lower()
        path_to_item[stem] = it

    updated_count = 0
    skill_names_seen: list[str] = []

    for skill_md in skills_root.rglob("SKILL.md"):
        raw = skill_md.read_text(encoding="utf-8", errors="ignore")
        # SKILL.md format: ````skill\n---\n<yaml>\n---\n````
        # Also handle plain ---\n<yaml>\n--- and ```yaml\n<yaml>\n```
        fm_text = None
        # Pattern 1: backtick fence containing ---frontmatter---
        m = re.search(r"`{3,}(?:skill|yaml)?\s*\n---\n(.*?)\n---\n", raw, re.DOTALL)
        if m:
            fm_text = m.group(1)
        else:
            # Pattern 2: plain --- frontmatter at start
            m2 = re.match(r"^---\n(.*?)\n---", raw, re.DOTALL)
            if m2:
                fm_text = m2.group(1)
            else:
                # Pattern 3: backtick fence without inner ---
                m3 = re.search(r"`{3,}(?:skill|yaml)?\s*\n(.*?)\n`{3,}", raw, re.DOTALL)
                if m3:
                    fm_text = m3.group(1)

        skill_name: str | None = None
        db_locations: list[str] = []

        if fm_text:
            try:
                fm = _yaml.safe_load(fm_text)
                if isinstance(fm, dict):
                    skill_name = fm.get("name") or skill_md.parent.name
                    # databases can live at root level OR under business_context
                    dbs = fm.get("databases") or {}
                    bc = fm.get("business_context") or {}
                    if isinstance(bc, dict):
                        dbs = {**dbs, **(bc.get("databases") or {})}
                    if isinstance(dbs, dict):
                        for alias, db_cfg in dbs.items():
                            if isinstance(db_cfg, dict):
                                loc = db_cfg.get("location", "")
                                if loc:
                                    db_locations.append(loc)
            except Exception as e:
                logger.warning("Failed to parse skill YAML for %s during reindex: %s", skill_md, e)

        if not skill_name:
            skill_name = skill_md.parent.name

        skill_names_seen.append(skill_name)

        # Match db_locations to registry items via linked_assets or path stem
        for loc in db_locations:
            loc_stem = Path(loc).stem.lower()
            # Find registry items whose path or linked_assets reference this db
            for it in items:
                linked = [Path(a).stem.lower() for a in (it.get("linked_assets") or [])]
                item_stem = Path(it.get("path", "")).stem.lower()
                if loc_stem == item_stem or loc_stem in linked:
                    existing = it.setdefault("skills", [])
                    if skill_name not in existing:
                        existing.append(skill_name)
                        updated_count += 1

    _save_registry(reg, req.tenant_id)
    _invalidate_tree_cache(req.tenant_id)

    return {
        "ok": True,
        "skills_scanned": len(skill_names_seen),
        "links_added": updated_count,
        "skills": skill_names_seen,
    }


@router.get("/taxonomy-graph")
async def taxonomy_graph_endpoint(tenant_id: str = "company"):
    """
    Read taxonomy_signal_index (SQLite or Postgres) and return a structured L1→L2→L3→L5 tree.
    This is the ground truth for routing — the same data the router LLM sees.
    """
    from collections import OrderedDict as _OD

    from shared.state import state as _state
    _agent = _state.get_or_create("company", "enterprise_agent", "system")
    _indexer = getattr(getattr(_agent, "memory", None), "knowledge_indexer", None)
    if _indexer is None:
        raise HTTPException(503, "Agent memory not ready")

    try:
        with _indexer.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT embed_text, skill, context_files, src_file, src_mtime FROM taxonomy_signal_index")
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("taxonomy_graph_endpoint failed")
        raise HTTPException(500, "An internal error occurred")

    # Skip rows whose source .md no longer exists, so a deleted taxonomy's tab can't
    # resurface if a late extraction re-inserted its rows after the delete purge.
    _src_exists: dict = {}
    def _file_present(p) -> bool:
        if p not in _src_exists:
            try:
                _src_exists[p] = bool(p) and Path(p).exists()
            except Exception:
                _src_exists[p] = False
        return _src_exists[p]

    # Parse embed_text path into hierarchy levels
    # Format: "L1 > L2 > L3 > [L4 >] L5 activity — description"
    tax_dict: dict = _OD()
    tax_rev: dict = {}   # L1 name -> max src_mtime seen (an indexing-revision marker)
    for (embed_text, skill, ctx_raw, src_file, src_mtime) in rows:
        if not _file_present(src_file):
            continue
        parts = [p.strip() for p in embed_text.split(" > ")]
        if len(parts) < 3:
            continue
        l1, l2, l3 = parts[0], parts[1], parts[2]
        try:
            _mt = float(src_mtime or 0)
        except (TypeError, ValueError):
            _mt = 0.0
        if _mt > tax_rev.get(l1, 0.0):
            tax_rev[l1] = _mt
        l5_full = parts[-1]  # last segment = "activity — description" or just activity

        try:
            ctx_files = json.loads(ctx_raw or "[]")
        except Exception:
            ctx_files = []

        tax_dict.setdefault(l1, _OD())
        tax_dict[l1].setdefault(l2, _OD())
        if l3 not in tax_dict[l1][l2]:
            tax_dict[l1][l2][l3] = {"skill": skill, "context_files": ctx_files, "activities": []}

        if " — " in l5_full:
            act_name, act_desc = l5_full.split(" — ", 1)
        else:
            act_name, act_desc = l5_full, ""

        tax_dict[l1][l2][l3]["activities"].append(
            {"name": act_name.strip(), "description": act_desc.strip()}
        )

    taxonomies = []
    total_nodes, skill_set = 0, set()
    from shared import skill_versions as _sv
    _skills_root = SERVER_DIR / SKILLS_PATH
    _owner_cache: dict = {}

    def _skill_owner(_skill: str) -> str:
        if not _skill:
            return ""
        if _skill not in _owner_cache:
            try:
                _owner_cache[_skill] = _sv.owner(_skills_root / _skill)
            except Exception:
                _owner_cache[_skill] = ""
        return _owner_cache[_skill]

    for l1_name, l2_map in tax_dict.items():
        domains = []
        for l2_name, l3_map in l2_map.items():
            sections, domain_count, domain_skill = [], 0, None
            for l3_name, l3_data in l3_map.items():
                cnt = len(l3_data["activities"])
                domain_count += cnt
                total_nodes += cnt
                domain_skill = l3_data["skill"]
                skill_set.add(domain_skill)
                sections.append({
                    "name": l3_name,
                    "skill": l3_data["skill"],
                    "activity_count": cnt,
                    "context_files": l3_data["context_files"],
                    "activities": l3_data["activities"],
                    "created_by": _skill_owner(l3_data["skill"]),
                })
            domains.append({
                "name": l2_name,
                "skill": domain_skill,
                "node_count": domain_count,
                "sections": sections,
                "created_by": _skill_owner(domain_skill),
            })
        taxonomies.append({"name": l1_name, "domains": domains, "rev": tax_rev.get(l1_name, 0.0)})

    # Show owner display names instead of emails on every domain/section node.
    _owner_nodes = []
    for _tax in taxonomies:
        for _dom in _tax["domains"]:
            _owner_nodes.append(_dom)
            _owner_nodes.extend(_dom.get("sections", []))
    await _apply_owner_display_names(_owner_nodes)

    return {
        "stats": {"total_nodes": total_nodes, "skills": len(skill_set), "taxonomies": len(taxonomies)},
        "taxonomies": taxonomies,
    }


class TaxonomyRouteRequest(BaseModel):
    query: str
    tenant_id: str = "company"


@router.post("/taxonomy-route")
async def taxonomy_route_endpoint(req: TaxonomyRouteRequest):
    """
    Run a query through the live TaxonomySignalIndex and return per-L3 scores.
    Identical to what the router LLM receives as taxonomy_hints.
    """
    from shared.state import state as _state
    _agent = _state.get_or_create("company", "enterprise_agent", "system")

    tax_idx = getattr(_agent, "_taxonomy_index", None)
    if not tax_idx or not (getattr(tax_idx, "_ready", None) and tax_idx._ready.is_set()):
        raise HTTPException(503, "Taxonomy index not ready yet — wait a moment and retry")

    # Compute embedding via existing indexer (same path as chat.py pre-router lookup)
    emb = None
    try:
        _indexer = getattr(getattr(_agent, "memory", None), "knowledge_indexer", None)
        if _indexer:
            emb = _indexer._safe_get_embedding(req.query)
    except Exception:
        pass

    hits = tax_idx.find_skills(query_embedding=emb, query_text=req.query)

    # Group by L3 section — keep best score per section
    seen: dict = {}
    for hit in hits:
        et = hit.get("embed_text", "")
        parts = [p.strip() for p in et.split(" > ")]
        l2 = parts[1] if len(parts) > 1 else "?"
        l3 = parts[2] if len(parts) > 2 else "?"
        key = f"{l2}|{l3}"
        score = hit.get("score", 0)
        if key not in seen or score > seen[key]["score"]:
            matched = et.split(" — ")[-1] if " — " in et else et[-80:]
            seen[key] = {
                "l3": l3, "l2": l2,
                "skill": hit.get("skill"),
                "score": round(score, 4),
                "matched_activity": matched,
            }

    results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    skills_above_threshold = list({r["skill"] for r in results[:4] if r["score"] >= 0.55})
    mode = "planned" if len(skills_above_threshold) > 1 else "react"
    margin = round(results[0]["score"] - results[1]["score"], 4) if len(results) > 1 else 1.0

    return {
        "query": req.query,
        "results": results,
        "top_skill": results[0]["skill"] if results else None,
        "execution_mode": mode,
        "margin": margin,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TAXONOMY AUTHORING — create a taxonomy tab from the Skill Builder UI
#
# A taxonomy is just a .md file under /shared/contexts/taxonomy/ referenced from
# Enterprise_Context.md. The indexer (TaxonomySignalIndex) reads the frontmatter
# `name:` as L1, `### ` headings as L2 domains, `#### ` headings as L3 sections,
# and the `<!-- skill: X -->` tag right after each L3 as the routed skill. This
# endpoint scaffolds that exact shape, registers the file, and re-indexes.
# ═══════════════════════════════════════════════════════════════════════════════

_EC_TAX_MARKER = "<!-- AUTO-TAXONOMY (managed by Skill Builder) -->"


class TaxonomySectionSpec(BaseModel):
    name: str
    skill: str
    activities: list[str] = []


class TaxonomyDomainSpec(BaseModel):
    name: str
    sections: list[TaxonomySectionSpec] = []


class TaxonomyCreateRequest(BaseModel):
    name: str
    description: str = ""
    domains: list[TaxonomyDomainSpec] = []
    tenant_id: str = "company"


def _valid_skill_names() -> set:
    """Skill keys from the active skills _index.yaml (ground truth for tags)."""
    try:
        idx = SERVER_DIR / SKILLS_PATH / "_index.yaml"
        data = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
        return set((data.get("skills") or {}).keys())
    except Exception:
        return set()


def _clean_line(s: str, *, max_len: int = 200) -> str:
    """Collapse to a single trimmed line so names can't break .md structure."""
    return (s or "").replace("\r", " ").replace("\n", " ").strip()[:max_len]


def _yaml_scalar(s: str) -> str:
    """Emit a string as a single-line YAML scalar, quoted only when needed, so
    values like ``HR: Payroll`` or ``true`` can't corrupt or retype the
    frontmatter. Width is pinned so long values are never folded onto new lines."""
    dumped = yaml.safe_dump({"_": s}, allow_unicode=True, default_flow_style=False,
                            width=1_000_000).strip()
    # dumped is ``_: <scalar>`` on a single line; return just the scalar.
    return dumped[len("_:"):].strip()


def _build_taxonomy_md(name, description, skills, domains, creator) -> str:
    """Render a taxonomy .md in the exact shape TaxonomySignalIndex parses."""
    title = _clean_line(name, max_len=120)
    # Reject names that can't be stored verbatim: callers use the ORIGINAL name for
    # duplicate checks, responses and poll targets, so a name that is truncated or
    # line-collapsed here would bypass dedup (two names sharing their first 120 chars
    # merge into one tab) and make polling wait for a name that never appears.
    if title != (name or "").strip():
        raise HTTPException(422, "Taxonomy name must be a single line of at most 120 characters")
    # Emit frontmatter through a YAML dumper so names/descriptions carrying YAML
    # metacharacters (``HR: Payroll``, ``true``) are quoted instead of corrupting
    # the block or silently retyping to a bool. TSI reads this via yaml.safe_load.
    fm = {
        "name": title,
        "type": "taxonomy",
        "description": _clean_line(description),
        "status": "active",
        "skills": sorted(skills),
        "created_by": creator,
    }
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True,
                             default_flow_style=False, width=1_000_000).strip()
    out = [
        "---",
        fm_text,
        "---",
        "",
        f"# {title}",
        "",
    ]
    for d in domains:
        out += [f"### {_clean_line(d.name, max_len=120)}", ""]
        for s in d.sections:
            acts = [a for a in (_clean_line(x) for x in (s.activities or [])) if a]
            if not acts:  # guarantee >=1 node so the section is indexable/visible
                acts = [_clean_line(s.name, max_len=120)]
            out += [f"#### {_clean_line(s.name, max_len=120)}", f"<!-- skill: {s.skill} -->", ""]
            out += [f"- {a}" for a in acts]
            out.append("")
    return "\n".join(out) + "\n"


def _register_taxonomy_in_ec(tenant_id: str, rel_path: str) -> None:
    """Idempotently reference the new taxonomy file in Enterprise_Context.md so
    the indexer discovers it (the indexer greps for contexts/taxonomy/*.md)."""
    ec = _shared_dir(tenant_id) / "Enterprise_Context.md"
    try:
        content = ec.read_text(encoding="utf-8") if ec.exists() else ""
    except Exception:
        content = ""
    if rel_path in content:
        return
    ref = f"- `{rel_path}`"
    if _EC_TAX_MARKER in content:
        content = content.replace(_EC_TAX_MARKER, f"{_EC_TAX_MARKER}\n{ref}", 1)
    else:
        content = content.rstrip() + f"\n\n{_EC_TAX_MARKER}\n{ref}\n"
    atomic_write_text(ec, content)


def _trigger_taxonomy_reindex(tenant_id: str = "company", agent_id: str = "enterprise_agent") -> None:
    """Evict + warm-rebuild the enterprise agent so its TaxonomySignalIndex reloads.
    Eviction is tenant-scoped so editing one tenant's taxonomy doesn't drop other
    tenants' cached enterprise_agent (templates/kernels/session clones)."""
    from shared.state import state as _state
    _state.evict_agent(agent_id, preserve_sessions=True, tenant_id=tenant_id)
    _state.get_or_create(tenant_id, agent_id, "system")  # kicks the background TSI.load()


def _purge_taxonomy_rows(tenant_id: str, src_path, agent_id: str = "enterprise_agent") -> None:
    """Delete a removed/renamed taxonomy's extracted rows from the signal index so
    its nodes stop serving routing. The evict+rebuild only refreshes files still
    referenced in Enterprise_Context.md — never a file that's gone — so without this
    the old rows (and the stale graph tab) linger. Best-effort: the table lives in
    the knowledge indexer's DB, the same one the graph endpoint reads."""
    from shared.state import state as _state
    try:
        agent = _state.get_or_create(tenant_id, agent_id, "system")
        indexer = getattr(getattr(agent, "memory", None), "knowledge_indexer", None)
        if indexer is None:
            return
        ph = getattr(indexer, "_ph", "?")
        with indexer.connect() as conn:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM taxonomy_signal_index WHERE src_file={ph}", (str(src_path),))
            conn.commit()
    except Exception:
        logger.warning("taxonomy row purge failed for %s", src_path, exc_info=True)


def _taxonomy_root(tenant_id: str) -> Path:
    """Resolved /shared/contexts/taxonomy dir for a tenant (created on first use)."""
    root = _shared_dir(tenant_id) / "contexts" / "taxonomy"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _taxonomy_dest(tenant_id: str, slug: str) -> Path:
    """Resolve <slug>.md strictly under the taxonomy dir (sast CWE-22)."""
    root = _taxonomy_root(tenant_id)
    dest = (root / f"{slug}.md").resolve()
    if not dest.is_relative_to(root):
        raise HTTPException(400, "Invalid taxonomy name")
    return dest


def _fm_fields(text: str) -> dict:
    """Extract name/description from a markdown string's YAML frontmatter.

    Parsed as YAML (not line regex) so an empty ``description:`` no longer bleeds
    the following ``status:`` line into the value, and quotes around a name are
    decoded the same way the indexer decodes them."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text[3:]
    try:
        data = yaml.safe_load(block)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in ("name", "description"):
        if data.get(key) is not None:
            out[key] = str(data[key]).strip()
    return out


def _taxonomy_fm(path: Path) -> dict:
    """Extract the name/description frontmatter fields from a taxonomy .md."""
    try:
        return _fm_fields(path.read_text(encoding="utf-8")[:2000])
    except Exception:
        return {}


def _ensure_taxonomy_name(content: str, name: str) -> str:
    """Guarantee the markdown carries frontmatter `name: <name>` so the indexer
    reads it as L1 and find-by-name resolves. Adds frontmatter if missing."""
    repl = f"name: {_yaml_scalar(name)}"
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            fm, body = content[:end], content[end:]
            if re.search(r'^name:\s*.*$', fm, re.MULTILINE):
                # lambda replacement so backslashes/group refs in the name aren't
                # interpreted as regex replacement syntax.
                fm = re.sub(r'^name:\s*.*$', lambda _m: repl, fm, count=1, flags=re.MULTILINE)
            else:
                fm = fm.rstrip() + f"\n{repl}"
            return fm + body
    return f"---\n{repl}\ntype: taxonomy\nstatus: active\n---\n\n" + content


def _find_taxonomy_file(tenant_id: str, name: str):
    """Resolve a taxonomy's source .md by its L1 (frontmatter) name. Handles
    legacy files whose filename differs from the display name. Confined to the
    taxonomy dir (sast CWE-22: a symlinked .md resolving outside is skipped)."""
    root = _taxonomy_root(tenant_id)
    target = (name or "").strip().casefold()
    if not target:
        return None
    for p in root.glob("*.md"):
        rp = p.resolve()
        if not rp.is_relative_to(root):
            continue
        if _taxonomy_fm(rp).get("name", "").casefold() == target:
            return rp
    return None


def _taxonomy_name_taken(tenant_id: str, name: str, *, exclude=None) -> bool:
    """True when a taxonomy with this L1 (frontmatter) name already lives in a
    different source file. Guards against two files claiming one L1 name — which
    the indexer would merge into a single graph tab while edit/delete resolved only
    the first match. ``exclude`` skips the current source during a rename/update."""
    existing = _find_taxonomy_file(tenant_id, name)
    if existing is None:
        return False
    if exclude is not None and existing.resolve() == Path(exclude).resolve():
        return False
    return True


def _unregister_taxonomy_from_ec(tenant_id: str, rel_path: str) -> None:
    """Remove a taxonomy reference from Enterprise_Context.md without destroying
    the lines it shares. A standalone managed entry (the ``- `path``` line that
    ``_register_taxonomy_in_ec`` adds) is dropped whole; but a path embedded in a
    shared routing row — e.g. the Finance process-map rows that list a taxonomy
    alongside aliases, a skill, and other context links — only loses that one
    reference token, keeping the rest of the row intact."""
    ec = _shared_dir(tenant_id) / "Enterprise_Context.md"
    if not ec.exists():
        return
    try:
        lines = ec.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    # A standalone registration — whether a managed body entry (`- `path``) or a
    # frontmatter YAML list item (`- path`, quoted or not) — is dropped whole.
    managed = {
        f"- `{rel_path}`", f"- {rel_path}",
        f'- "{rel_path}"', f"- '{rel_path}'",
    }
    # Variants the path can appear as inside a shared line / inline YAML list.
    variants = [f"`{rel_path}`", f'"{rel_path}"', f"'{rel_path}'", rel_path]
    kept, changed = [], False
    for ln in lines:
        if ln.strip() in managed:
            changed = True
            continue
        if rel_path in ln:
            new = ln
            for v in variants:
                new = new.replace(v, "")
            # Tidy an inline YAML list left with dangling separators, e.g.
            # `taxonomy: ["a.md", "b.md"]` → `taxonomy: [, "b.md"]` → `["b.md"]`.
            new = re.sub(r"\[\s*,", "[", new)
            new = re.sub(r",\s*,", ",", new)
            new = re.sub(r",\s*\]", "]", new)
            # If removal left an empty list bullet (`- `, `- ""`), drop the line so
            # discovery can't resolve the empty value to the taxonomy directory.
            if re.fullmatch(r"""\s*-\s*["']?\s*["']?\s*""", new):
                changed = True
                continue
            changed = True
            kept.append(new)
        else:
            kept.append(ln)
    if changed:
        atomic_write_text(ec, "\n".join(kept) + "\n")


def _rename_taxonomy_ref_in_ec(tenant_id: str, old_rel: str, new_rel: str) -> bool:
    """Replace a taxonomy path with its new path in place across Enterprise_Context.md
    — updating both standalone managed entries and shared routing rows — so a rename
    preserves the surrounding row content. Returns True if the old path was present."""
    ec = _shared_dir(tenant_id) / "Enterprise_Context.md"
    if not ec.exists():
        return False
    try:
        content = ec.read_text(encoding="utf-8")
    except Exception:
        return False
    if old_rel not in content:
        return False
    content = content.replace(f"`{old_rel}`", f"`{new_rel}`").replace(old_rel, new_rel)
    atomic_write_text(ec, content)
    return True


def _validate_taxonomy_domains(domains) -> set:
    """Validate domains/sections/skills against the skill registry; return the
    set of skills used. Raises HTTPException on any invalid input."""
    if not domains:
        raise HTTPException(400, "Add at least one domain with a section")
    valid = _valid_skill_names()
    used = set()
    for d in domains:
        if not _clean_line(d.name, max_len=120):
            raise HTTPException(400, "Each domain needs a name")
        if not d.sections:
            raise HTTPException(400, f"Domain '{d.name}' needs at least one section")
        for s in d.sections:
            # Every section must carry a name and a skill — an aggregate check would
            # let a blank-skill section through, which is written as an unroutable
            # node and silently omitted from the index.
            if not _clean_line(s.name, max_len=120):
                raise HTTPException(400, "Each section needs a name")
            if not (s.skill or "").strip():
                raise HTTPException(400, "Each section needs a skill")
            used.add(s.skill)
    used.discard("")
    if not used:
        raise HTTPException(400, "Each section needs a skill")
    unknown = sorted(u for u in used if u not in valid)
    if unknown:
        raise HTTPException(422, f"Unknown skill(s): {', '.join(unknown)}")
    return used


@router.post("/taxonomy-create")
async def taxonomy_create_endpoint(
    req: TaxonomyCreateRequest,
    request: Request,
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Scaffold a taxonomy .md (name + L2 domains / L3 sections + skill tags),
    register it in Enterprise_Context.md, and force a taxonomy re-index."""
    bind_request_identity(request, req.tenant_id)

    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Taxonomy name is required")
    used = _validate_taxonomy_domains(req.domains)

    slug = _slugify(name)
    dest = _taxonomy_dest(req.tenant_id, slug)
    # Per-item policy guard on the write, same as /files/save.
    enforce_context_access(request, f"contexts/taxonomy/{slug}.md", "write")
    if dest.exists():
        raise HTTPException(409, f"A taxonomy named '{slug}' already exists")
    if _taxonomy_name_taken(req.tenant_id, name):
        raise HTTPException(409, f"A taxonomy named '{name}' already exists")

    try:
        md = _build_taxonomy_md(name, req.description, used, req.domains, _owner_identity(request))
        atomic_write_text(dest, md)
        _register_taxonomy_in_ec(req.tenant_id, f"contexts/taxonomy/{slug}.md")
        _trigger_taxonomy_reindex(req.tenant_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("taxonomy-create failed")
        raise HTTPException(500, "An internal error occurred")

    return {"ok": True, "name": name, "file": f"/shared/contexts/taxonomy/{slug}.md", "reindex": "started"}


class TaxonomyUpdateRequest(BaseModel):
    original_name: str
    name: str
    description: str = ""
    domains: list[TaxonomyDomainSpec] = []
    tenant_id: str = "company"


@router.post("/taxonomy-update")
async def taxonomy_update_endpoint(
    req: TaxonomyUpdateRequest,
    request: Request,
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Rewrite an existing taxonomy .md from edited fields, handle rename, and
    re-index. A blank description preserves the file's existing one."""
    bind_request_identity(request, req.tenant_id)

    new_name = (req.name or "").strip()
    if not new_name:
        raise HTTPException(400, "Taxonomy name is required")
    src = _find_taxonomy_file(req.tenant_id, req.original_name)
    if src is None:
        raise HTTPException(404, f"Taxonomy '{req.original_name}' not found")
    # Policy + ownership guards on the existing source, same as /files/save:
    # skills.author alone must not let one author overwrite another's taxonomy.
    enforce_context_access(request, f"contexts/taxonomy/{src.name}", "write")
    _require_file_owner_or_admin(request, src)
    used = _validate_taxonomy_domains(req.domains)

    name_changed = (req.original_name or "").strip().casefold() != new_name.casefold()
    if name_changed:
        dest = _taxonomy_dest(req.tenant_id, _slugify(new_name))
        # Allow a rename whose slug maps back to the same source file (e.g.
        # "Tax A" → "Tax-A"); only a *different* existing path is a conflict.
        if dest != src and dest.exists():
            raise HTTPException(409, f"A taxonomy named '{dest.stem}' already exists")
        if _taxonomy_name_taken(req.tenant_id, new_name, exclude=src):
            raise HTTPException(409, f"A taxonomy named '{new_name}' already exists")
    else:
        dest = src

    description = (req.description or "").strip() or _taxonomy_fm(src).get("description", "")

    try:
        # Preserve the file's original owner across edits (matching /files/save):
        # an admin editing another author's taxonomy must not seize ownership and
        # lock the original author out with a 403 on their next update/delete.
        md = _build_taxonomy_md(new_name, description, used, req.domains, _file_owner(src))
        atomic_write_text(dest, md)
        old_rel = f"contexts/taxonomy/{src.name}"
        new_rel = f"contexts/taxonomy/{dest.name}"
        if dest != src:
            src.unlink(missing_ok=True)
            _purge_taxonomy_rows(req.tenant_id, src)   # old path's rows must not linger
            # Replace the reference in place (keeps shared routing rows intact);
            # only register a fresh managed entry if the old path wasn't present.
            if not _rename_taxonomy_ref_in_ec(req.tenant_id, old_rel, new_rel):
                _register_taxonomy_in_ec(req.tenant_id, new_rel)
        else:
            _register_taxonomy_in_ec(req.tenant_id, new_rel)
        _trigger_taxonomy_reindex(req.tenant_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("taxonomy-update failed")
        raise HTTPException(500, "An internal error occurred")

    return {"ok": True, "name": new_name, "file": f"/shared/contexts/taxonomy/{dest.name}",
            "renamed": name_changed, "reindex": "started"}


class TaxonomyDeleteRequest(BaseModel):
    name: str
    tenant_id: str = "company"


@router.post("/taxonomy-delete")
async def taxonomy_delete_endpoint(
    req: TaxonomyDeleteRequest,
    request: Request,
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Delete a taxonomy .md, de-register it from Enterprise_Context.md, re-index."""
    bind_request_identity(request, req.tenant_id)

    src = _find_taxonomy_file(req.tenant_id, req.name)
    if src is None:
        raise HTTPException(404, f"Taxonomy '{req.name}' not found")
    # Policy + ownership guards, same as /files/delete.
    enforce_context_access(request, f"contexts/taxonomy/{src.name}", "delete")
    _require_file_owner_or_admin(request, src)

    try:
        src.unlink(missing_ok=True)
        _unregister_taxonomy_from_ec(req.tenant_id, f"contexts/taxonomy/{src.name}")
        _purge_taxonomy_rows(req.tenant_id, src)   # drop its extracted rows so routing forgets it
        _trigger_taxonomy_reindex(req.tenant_id)
    except Exception:
        logger.exception("taxonomy-delete failed")
        raise HTTPException(500, "An internal error occurred")

    return {"ok": True, "name": req.name, "reindex": "started"}


class TaxonomyImportRequest(BaseModel):
    content: str
    name: str = ""          # optional override; else taken from frontmatter/JSON
    tenant_id: str = "company"


# 512 KB cap — bound the payload before any regex/JSON scan (sast CWE-1333).
_TAXONOMY_IMPORT_MAX_BYTES = 512 * 1024


def _markdown_routable_sections(content: str) -> set:
    """Skills reachable through a properly-structured L3 section, mirroring the
    indexer's parsing contract (TaxonomySignalIndex._parse_file): a section exists
    only at a ``#### Heading`` and its skill is read from the ``<!-- skill: X -->``
    tag on the immediately following line. A tag that isn't directly under a ####
    heading is invisible to the indexer, so it doesn't count here."""
    lines = content.splitlines()
    out = set()
    for i, line in enumerate(lines):
        if re.match(r'^####\s+(?!#)', line) and i + 1 < len(lines):
            m = re.search(r'<!--\s*skill:\s*([A-Za-z0-9_\-]{1,64})\s*-->', lines[i + 1])
            if m:
                out.add(m.group(1))
    return out


def _import_from_markdown(content: str, name_override: str):
    """Validate a ready-made taxonomy .md (already in the 4-rule shape) and return
    (name, md_body, skills). Must route somewhere: >=1 valid <!-- skill: X --> tag
    sitting under a proper #### L3 section (matching the indexer's parser)."""
    name = (name_override or _fm_fields(content[:2000]).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Taxonomy name missing — add a frontmatter 'name:' or provide one")

    tags = set(re.findall(r'<!--\s*skill:\s*([A-Za-z0-9_\-]{1,64})\s*-->', content))
    if not tags:
        raise HTTPException(422, "No '<!-- skill: X -->' tags found — not a routable taxonomy")
    unknown = sorted(t for t in tags if t not in _valid_skill_names())
    if unknown:
        raise HTTPException(422, f"Unknown skill(s): {', '.join(unknown)}")

    # Structural check: the indexer only builds a node from a skill tag that sits
    # directly under a '#### Section' heading. Without this, a doc whose tags float
    # outside any L3 section imports "successfully" but produces an empty, invisible
    # graph tab (Copilot: validate hierarchy & skill assignments).
    routable = {t for t in _markdown_routable_sections(content) if t in _valid_skill_names()}
    if not routable:
        raise HTTPException(
            422,
            "No routable L3 section found — each '<!-- skill: X -->' must sit on the "
            "line directly under a '#### Section' heading",
        )

    return name, _ensure_taxonomy_name(content, name), sorted(tags)


def _import_from_json(content: str, name_override: str, creator: str):
    """Convert an imported taxonomy JSON doc into our .md and return
    (name, md_body, skills). Shape mirrors the create API:
    {name, description?, domains:[{name, sections:[{name, skill, activities?}]}]}."""
    try:
        doc = json.loads(content)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid JSON — could not parse taxonomy file")
    if not isinstance(doc, dict):
        raise HTTPException(422, "Taxonomy JSON must be an object with 'name' and 'domains'")

    name = (name_override or str(doc.get("name") or "")).strip()
    if not name:
        raise HTTPException(400, "Taxonomy name missing — add a 'name' field or provide one")
    try:
        domains = [TaxonomyDomainSpec(**d) for d in (doc.get("domains") or [])]
    except Exception:
        raise HTTPException(422, "Invalid taxonomy JSON: bad domains/sections shape")

    used = _validate_taxonomy_domains(domains)   # validates skills against _index.yaml
    md = _build_taxonomy_md(name, str(doc.get("description") or ""), used, domains, creator)
    return name, md, sorted(used)


@router.post("/taxonomy-import")
async def taxonomy_import_endpoint(
    req: TaxonomyImportRequest,
    request: Request,
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Import an existing taxonomy — either a ready-made .md (already in the 4-rule
    shape) or a JSON doc ({name, domains:[{sections:[{skill, activities}]}]}).
    Format is auto-detected. Validates it routes somewhere, saves under
    contexts/taxonomy, registers in EC.md, and re-indexes."""
    bind_request_identity(request, req.tenant_id)

    content = req.content or ""
    if not content.strip():
        raise HTTPException(400, "Taxonomy file content is required")
    if len(content.encode("utf-8")) > _TAXONOMY_IMPORT_MAX_BYTES:
        raise HTTPException(413, "Taxonomy file too large")

    # Auto-detect: a leading { or [ means JSON, otherwise treat as markdown.
    if content.lstrip()[:1] in "{[":
        name, body, skills = _import_from_json(content, req.name, _owner_identity(request))
        fmt = "json"
    else:
        name, body, skills = _import_from_markdown(content, req.name)
        # Stamp the importer as owner when the markdown carries no created_by, so a
        # non-admin can edit/delete what they imported (JSON imports and new
        # taxonomies already record an owner; without this _file_owner defaults to
        # admin@iaf.local and the importer gets 403 on their own taxonomy).
        body = _ensure_created_by(body, _owner_identity(request))
        fmt = "markdown"

    slug = _slugify(name)
    dest = _taxonomy_dest(req.tenant_id, slug)
    # Per-item policy guard on the write, same as /files/save.
    enforce_context_access(request, f"contexts/taxonomy/{slug}.md", "write")
    if dest.exists():
        raise HTTPException(409, f"A taxonomy named '{slug}' already exists")
    if _taxonomy_name_taken(req.tenant_id, name):
        raise HTTPException(409, f"A taxonomy named '{name}' already exists")

    try:
        atomic_write_text(dest, body)
        _register_taxonomy_in_ec(req.tenant_id, f"contexts/taxonomy/{slug}.md")
        _trigger_taxonomy_reindex(req.tenant_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("taxonomy-import failed")
        raise HTTPException(500, "An internal error occurred")

    return {"ok": True, "name": name, "file": f"/shared/contexts/taxonomy/{slug}.md",
            "format": fmt, "skills": skills, "reindex": "started"}


@router.post("/taxonomy-reindex")
async def taxonomy_reindex_endpoint(
    request: Request,
    tenant_id: str = "company",
    _perm: dict = Depends(require_permission("skills.author")),
):
    """Force a taxonomy signal re-index (evict + rebuild the enterprise agent)."""
    bind_request_identity(request, tenant_id)
    try:
        _trigger_taxonomy_reindex(tenant_id)
    except Exception:
        logger.exception("taxonomy-reindex failed")
        raise HTTPException(500, "An internal error occurred")
    return {"ok": True, "reindex": "started"}
