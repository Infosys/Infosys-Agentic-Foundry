"""
IAF Agent Studio — File Browser API Router

Endpoints for virtual filesystem operations via SafeKernel.
"""

import asyncio
import logging
import mimetypes
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse
from agent_os.path_ids import validate_path_id
from agent_os.safe_path import SecurityError
from security.dependencies import require_scoped_identity
from security.signed_urls import (
    SignedUrlConfigurationError,
    build_signed_file_url,
    verify_file_request,
)
from shared.models import FileOperation
from shared.state import state, load_local_mount, save_local_mount
from shared.config import ALLOW_UNSIGNED_FILE_URLS, AUTH_ENABLED, DATA_ROOT_PATH, TENANT_ID
from shared.document_extract import EXTRACTABLE_EXTENSIONS, extract_file_text, pdf_page_count
from shared.user_display import display_name as _owner_display_name, apply_display_names as _apply_owner_display_names

logger = logging.getLogger(__name__)

router = APIRouter()

# Anchor to the SERVER_DIR-relative DATA_ROOT_PATH; Path(DATA_ROOT).resolve() uses the process CWD.
_DATA_ROOT = DATA_ROOT_PATH

import re as _re


# Secrets never listed/read/written/deleted via the generic file API, even with file:* grants.
from shared.protected_files import (
    PROTECTED_PATHS as _PROTECTED_PATHS,
    norm_vpath as _norm_vpath,
    is_protected as _is_protected,
    is_protected_ext as _is_protected_ext,
    is_protected_name as _is_protected_name,
)


def _reject_if_protected(virtual_path: str) -> None:
    # Blocks protected paths/basenames and key material on canonicalized paths (./, .., //, trailing slash).
    if _is_protected(virtual_path):
        raise HTTPException(status_code=403, detail="This path is protected and cannot be accessed via the file API.")


def _reject_if_protected_real(resolved: Path) -> None:
    # Second gate: the symlink-resolved target must not be protected material.
    name = resolved.name
    if _is_protected_name(name) or _is_protected_ext(name):
        raise HTTPException(status_code=403, detail="This path is protected and cannot be accessed via the file API.")


def _resolve_shared_real(virtual_path: str, tenant_id: str):
    """Resolve a /shared/ virtual path to a real Path (traversal-safe), else None."""
    vp = (virtual_path or "").strip()
    if vp.startswith("/shared/"):
        rel = vp[len("/shared/"):]
    elif vp.startswith("shared/"):
        rel = vp[len("shared/"):]
    else:
        return None
    base = (_DATA_ROOT / "tenants" / tenant_id / "shared").resolve()
    real = (base / rel).resolve()
    try:
        real.relative_to(base)
    except ValueError:
        return None
    return real


def _md_created_by(real: Path) -> str:
    """Creator recorded in a .md file's YAML front-matter. Legacy files with no
    created_by are owned by admin@iaf.local (admin-only edit)."""
    try:
        raw = real.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "admin@iaf.local"
    m = _re.match(r"^---\n(.*?)\n---", raw, _re.DOTALL)
    if not m:
        return "admin@iaf.local"
    cm = _re.search(r"^\s*created_by\s*:\s*(.+?)\s*$", m.group(1), _re.MULTILINE)
    return (cm.group(1).strip() if cm else "") or "admin@iaf.local"


def _principal_can_edit(principal, owner: str) -> bool:
    roles = getattr(principal, "roles", ()) or ()
    if "admin" in roles:
        return True
    idents = {v for v in (getattr(principal, "email", None), getattr(principal, "user_id", None)) if v}
    return owner in idents


def _principal_ident(principal, fallback: str = "unknown") -> str:
    return getattr(principal, "email", None) or getattr(principal, "user_id", None) or fallback


def _ensure_created_by_text(content: str, owner: str) -> str:
    """Inject created_by into an existing front-matter block if missing. Never
    forces front-matter onto plain markdown files that never had one."""
    m = _re.match(r"^---\n(.*?)\n---", content, _re.DOTALL)
    if not m:
        return content
    if _re.search(r"^\s*created_by\s*:", m.group(1), _re.MULTILINE):
        return content
    return content[:m.end(1)] + f"\ncreated_by: {owner}" + content[m.end(1):]



def _file_metadata(resolved: Path, virtual_path: str) -> dict:
    stat = resolved.stat()
    ext = resolved.suffix.lower()
    mime, _ = mimetypes.guess_type(str(resolved))
    metadata = {
        "name": resolved.name,
        "path": virtual_path,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "extension": ext,
        "file_type": mime or "application/octet-stream",
    }
    if ext == ".pdf":
        pages = pdf_page_count(resolved)
        if pages is not None:
            metadata["pages"] = pages
    return metadata


def _looks_binary(raw: bytes) -> bool:
    if not raw:
        return False
    if b"\x00" in raw[:8192]:
        return True
    sample = raw[:8192]
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def _file_url(path: str, tenant_id: str, agent_id: str, user_id: str) -> str:
    try:
        return build_signed_file_url(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            path=path,
        )
    except SignedUrlConfigurationError:
        if not ALLOW_UNSIGNED_FILE_URLS:
            raise HTTPException(status_code=503, detail="Signed file URLs are not configured")
        return "/api/files/serve?" + urlencode({
            "path": path,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "user_id": user_id,
        })


def _parse_ls_long_line(line: str) -> tuple[str, bool] | None:
    """Parse SafeKernel ``ls -l`` output; filename may contain spaces."""
    line = line.strip()
    if not line or line.startswith("total"):
        return None
    is_dir = line.startswith("d")
    # SafeKernel format: perm  size  Mon DD HH:MM  filename...
    parts = line.split(None, 5)
    if len(parts) >= 6:
        name = parts[5].rstrip("/")
        return name, is_dir or name.endswith("/")
    if len(parts) >= 1:
        name = parts[-1].rstrip("/")
        return name, is_dir or name.endswith("/")
    return None


def _scandir_list(
    virtual_path: str,
    tenant_id: str,
    *,
    agent_id: str = "enterprise_agent",
    user_id: str | None = None,
):
    """
    Resolve /shared/, /global/, or /me/ virtual paths directly via os.scandir,
    bypassing the kernel rate limiter. Returns (files_list, raw_str) or
    (None, None) if the path should fall through to the kernel.
    """
    vp = virtual_path.strip().rstrip("/") or "/"

    if vp.startswith("/shared"):
        base = _DATA_ROOT / "tenants" / tenant_id / "shared"
        rel  = vp[8:] if vp.startswith("/shared/") else ""
    elif vp.startswith("/global"):
        base = _DATA_ROOT / "global_shared"
        rel  = vp[8:] if vp.startswith("/global/") else ""
    elif (vp == "/me" or vp.startswith("/me/")) and user_id:
        base = (
            _DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id / "users" / user_id
        )
        rel = vp[3:].lstrip("/") if vp.startswith("/me/") else ""
    else:
        return None, None  # kernel handles /local/, agent root, etc.

    real = (base / rel).resolve() if rel else base.resolve()

    # Block path traversal outside the base
    try:
        real.relative_to(base.resolve())
    except ValueError:
        return None, None

    if not real.exists():
        return [], ""

    files = []
    try:
        with os.scandir(real) as it:
            for entry in sorted(it, key=lambda e: e.name):
                if entry.name.startswith("."):
                    continue
                # Skip symlinks: a link could point at credentials.yaml or key material and be followed by read/serve.
                if entry.is_symlink():
                    continue
                virt = (virtual_path.rstrip("/") + "/" + entry.name).replace("//", "/")
                # Never surface protected secrets (credentials.yaml) in the tree.
                if _is_protected(virt):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                item = {
                    "name": entry.name,
                    "type": "directory" if is_dir else "file",
                    "path": virt,
                }
                if not is_dir:
                    # Surface the creator (.md front-matter created_by; other files are admin-owned).
                    item["created_by"] = (
                        _md_created_by(Path(entry.path))
                        if entry.name.lower().endswith(".md") else "admin@iaf.local"
                    )
                files.append(item)
    except PermissionError:
        pass

    return files, f"scandir:{real}"


@router.get("/api/files")
async def list_files(
    request: Request,
    path: str = "/",
    tenant_id: str = TENANT_ID,
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """List files in virtual path."""
    principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action="read",
        resource_type="file",
        resource_id=path,
    )
    # Fast path: /shared/, /global/, /me/ bypass the kernel rate limiter entirely
    files, raw = _scandir_list(path, tenant_id, agent_id=agent_id, user_id=user_id)
    if files is not None:
        for item in files:
            if item.get("type") == "file":
                item["serve_url"] = _file_url(item["path"], tenant_id, agent_id, user_id)
        # Resolve the raw created_by identity into a friendly display name.
        await _apply_owner_display_names(files)
        return {"path": path, "files": files, "raw": raw}

    # Fallback: other virtual paths (agent root, /me/, /local/) via kernel
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    result = kernel.run_shell_command(f"ls -la {shlex.quote(path)}")

    files = []
    for line in result.strip().split("\n"):
        # Skip symlinks (ls -la leading 'l'): the link may point at protected material.
        if line.lstrip().startswith("l"):
            continue
        parsed = _parse_ls_long_line(line)
        if not parsed:
            continue
        name, is_dir = parsed
        virt = f"{path.rstrip('/')}/{name}".replace("//", "/")
        # Never surface protected secrets or private-key material (.key/.pem/…),
        # even for agent-root / /me/ / /local/ paths that come back via kernel ls.
        if _is_protected(virt):
            continue
        files.append({
            "name": name,
            "type": "directory" if is_dir else "file",
            "path": virt,
        })
    for item in files:
        if item.get("type") == "file":
            item["serve_url"] = _file_url(item["path"], tenant_id, agent_id, user_id)

    return {"path": path, "files": files, "raw": result}


@router.get("/api/files/content")
async def read_file_content(
    request: Request,
    path: str,
    tenant_id: str = TENANT_ID,
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Read file content."""
    _reject_if_protected(path)
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action="read",
        resource_type="file",
        resource_id=path,
    )
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    try:
        resolved = kernel._resolve_path(path)
    except Exception as exc:
        logger.exception("read_file_content failed")
        raise HTTPException(status_code=400, detail="An internal error occurred") from exc
    _reject_if_protected_real(resolved)  # symlink-target guard
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    metadata = _file_metadata(resolved, path)
    ext = resolved.suffix.lower()

    if ext in EXTRACTABLE_EXTENSIONS:
        try:
            content, extractor = await asyncio.to_thread(
                extract_file_text,
                resolved,
                tenant_id=tenant_id,
                max_chars=8000,
            )
        except Exception as exc:
            logger.exception("read_file_content failed")
            raise HTTPException(
                status_code=400,
                detail="An internal error occurred",
            ) from exc
        created_by = None
        created_by_display = None
        real = _resolve_shared_real(path, tenant_id)
        if real is not None and real.suffix.lower() == ".md":
            created_by = _md_created_by(real)
            created_by_display = await _owner_display_name(created_by)
        return {
            "path": path,
            "content": content,
            "preview_type": "extracted_text",
            "extractor": extractor,
            "metadata": metadata,
            "created_by": created_by,
            "created_by_display": created_by_display,
        }

    try:
        raw = resolved.read_bytes()
    except Exception as exc:
        logger.exception("read_file_content failed")
        raise HTTPException(status_code=400, detail="An internal error occurred") from exc
    if _looks_binary(raw):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Binary file preview is not supported for {path}. "
                "Use Download or Open Original."
            ),
        )
    content = raw.decode("utf-8", errors="replace")
    created_by = None
    created_by_display = None
    real = _resolve_shared_real(path, tenant_id)
    if real is not None and real.suffix.lower() == ".md":
        # created_by must stay the raw identity (the editor compares it for edit rights); display name is separate.
        created_by = _md_created_by(real)
        created_by_display = await _owner_display_name(created_by)
    return {
        "path": path,
        "content": content,
        "preview_type": "text",
        "metadata": metadata,
        "created_by": created_by,
        "created_by_display": created_by_display,
    }


@router.post("/api/files/write")
async def write_file_content(op: FileOperation, request: Request):
    """Write file content."""
    _reject_if_protected(op.path)
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=op.tenant_id,
        requested_agent=op.agent_id,
        requested_user=op.user_id,
        action="write",
        resource_type="file",
        resource_id=op.path,
    )
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    # Symlink-target guard: reject if the path resolves to protected material
    # (a symlink alias would pass the lexical _reject_if_protected above).
    try:
        _reject_if_protected_real(kernel._resolve_path(op.path))
    except HTTPException:
        raise
    except Exception:
        pass
    # Ownership gate for existing shared files: .md carry created_by; others are admin-only.
    _sr = _resolve_shared_real(op.path, tenant_id)
    if _sr is not None and _sr.exists():
        _own = _md_created_by(_sr) if _sr.suffix.lower() == ".md" else "admin@iaf.local"
        if not _principal_can_edit(_principal, _own):
            raise HTTPException(403, f"Only the owner ({_own}) or an admin can edit this file.")
    escaped = op.content.replace("'", "'\\''") if op.content else ""
    result = kernel.run_shell_command(f"echo '{escaped}' > {op.path} # CONFIRMED")
    return {"path": op.path, "result": result}


@router.post("/api/files/mkdir")
async def make_dir(op: FileOperation, request: Request):
    """Create directory."""
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=op.tenant_id,
        requested_agent=op.agent_id,
        requested_user=op.user_id,
        action="write",
        resource_type="file",
        resource_id=op.path,
    )
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    result = kernel.run_shell_command(f"mkdir -p {op.path} # CONFIRMED")
    return {"path": op.path, "result": result}


_ALLOWED_UPLOAD_EXTS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".txt",
    ".md", ".csv", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg", ".gif",
    # Author-editable script/config text; execution is gated by SafeKernel at runtime.
    ".py", ".sh", ".sql",
    # Public TLS certificates only; private keys belong in the credential store.
    ".crt", ".cer",
}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/api/files/upload")
async def upload_file(
    request: Request,
    file: UploadFile,
    path: str = Form(...),
    tenant_id: str = Form(TENANT_ID),
    agent_id: str = Form("enterprise_agent"),
    user_id: str = Form("demo"),
):
    """Upload a file to the virtual filesystem."""
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action="write",
        resource_type="file",
        resource_id=path,
    )
    filename = file.filename or "upload.bin"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(400, f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(_ALLOWED_UPLOAD_EXTS))}")

    safe_filename = Path(filename).name.replace("..", "_").replace("/", "_").replace("\\", "_")

    kernel = state.get_kernel(tenant_id, agent_id, user_id)

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large (max {_MAX_UPLOAD_SIZE // (1024*1024)} MB)")

    if path.endswith('/'):
        full_path = path + safe_filename
    else:
        full_path = path + '/' + safe_filename

    # Re-check the canonicalized destination: never land on a protected path or key material.
    _reject_if_protected(full_path)
    # Symlink-target guard: a symlinked destination could resolve to protected
    # material despite the lexical check above.
    try:
        _reject_if_protected_real(kernel._resolve_path(full_path))
    except HTTPException:
        raise
    except Exception:
        pass

    # Ownership gate for shared .md context files: only the creator or an admin
    # may overwrite an existing file. Legacy files (no created_by) are admin-only.
    _shared_real = _resolve_shared_real(full_path, tenant_id)
    _is_shared_md = _shared_real is not None and _shared_real.suffix.lower() == ".md"
    _owner_for_stamp = _principal_ident(_principal, user_id)
    if _shared_real is not None and _shared_real.exists():
        _owner = _md_created_by(_shared_real) if _is_shared_md else "admin@iaf.local"
        if not _principal_can_edit(_principal, _owner):
            raise HTTPException(403, f"Only the owner ({_owner}) or an admin can edit this file.")
        if _is_shared_md:
            _owner_for_stamp = _owner

    dir_path = '/'.join(full_path.rsplit('/', 1)[:-1]) or '/'
    if dir_path and dir_path != '/':
        kernel.run_shell_command(f"mkdir -p {shlex.quote(dir_path)} # CONFIRMED")

    # Use write_file method to bypass shell parsing
    try:
        text_content = content.decode('utf-8')
        if _is_shared_md:
            text_content = _ensure_created_by_text(text_content, _owner_for_stamp)
        result = kernel.write_file(full_path, text_content)
    except UnicodeDecodeError:
        # Binary file - write as bytes
        result = kernel.write_file(full_path, content)

    if result.startswith("Error"):
        return {"path": full_path, "filename": file.filename, "result": result, "error": True}

    return {"path": full_path, "filename": file.filename, "result": result}


@router.get("/api/files/url")
async def create_file_url(
    request: Request,
    path: str,
    tenant_id: str = TENANT_ID,
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Create a short-lived URL suitable for img, PDF, and download elements."""
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action="read",
        resource_type="file",
        resource_id=path,
    )
    return {"url": _file_url(path, tenant_id, agent_id, user_id)}


async def _authenticate_unsigned_serve(request: Request, path: str, tenant_id: str, agent_id: str, user_id: str):
    """/api/files/serve is a public route, so authenticate the cookie/bearer here."""
    from auth.identity import apply_identity_to_state
    from auth.middleware import _extract_token, authenticate_access_token

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication or a signed file URL is required")
    try:
        identity, _user = await authenticate_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    apply_identity_to_state(request.state, identity)
    _p, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action="read",
        resource_type="file",
        resource_id=path,
    )
    return tenant_id, agent_id, user_id


@router.get("/api/files/serve")
async def serve_file(
    request: Request,
    path: str,
    tenant_id: str = TENANT_ID,
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
    expires: int = 0,
    signature: str = "",
):
    """Serve a binary file (image, etc.) directly with correct Content-Type."""
    try:
        for _value, _label in ((tenant_id, "tenant_id"), (agent_id, "agent_id"), (user_id, "user_id")):
            validate_path_id(_value, _label)
    except SecurityError:
        raise HTTPException(status_code=400, detail=f"Invalid {_label}")
    _reject_if_protected(path)
    has_signed_fields = bool(expires or signature)
    valid_signature = bool(expires and signature) and verify_file_request(
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        path=path,
        expires_at=expires,
        signature=signature,
    )
    if has_signed_fields and not valid_signature:
        raise HTTPException(status_code=401, detail="Invalid or expired file URL")
    if not valid_signature and not ALLOW_UNSIGNED_FILE_URLS:
        raise HTTPException(status_code=401, detail="A signed file URL is required")
    if not valid_signature and AUTH_ENABLED:
        tenant_id, agent_id, user_id = await _authenticate_unsigned_serve(
            request, path, tenant_id, agent_id, user_id
        )
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    real_path = kernel._resolve_path(path)
    _reject_if_protected_real(real_path)  # symlink-target guard
    if not real_path.exists() or not real_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    mime, _ = mimetypes.guess_type(str(real_path))
    # HTML files must not be served inline under the Studio origin — an uploaded
    # HTML file would run with Studio's cookies and origin.  Force download for
    # all HTML MIME types; everything else is safe to display inline.
    is_html = (mime or "").startswith("text/html")
    disposition = f'attachment; filename="{real_path.name}"' if is_html else "inline"
    extra_headers: dict[str, str] = {"Content-Disposition": disposition}
    if is_html:
        extra_headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(
        str(real_path),
        media_type=mime or "application/octet-stream",
        headers=extra_headers,
    )


@router.delete("/api/files")
async def delete_file(
    request: Request,
    path: str,
    tenant_id: str = TENANT_ID,
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Delete a single file. Protected paths (secrets/config) are always rejected;
    RBAC is enforced via the delete entitlement, and shared files remain
    owner/admin-gated (parity with upload overwrite)."""
    _reject_if_protected(path)
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action="delete",
        resource_type="file",
        resource_id=path,
    )
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    # Symlink-target guard: don't act on a path that resolves to protected material.
    try:
        _reject_if_protected_real(kernel._resolve_path(path))
    except HTTPException:
        raise
    except Exception:
        pass

    # Ownership gate for shared files: only the creator or an admin may delete.
    _shared_real = _resolve_shared_real(path, tenant_id)
    if _shared_real is not None and _shared_real.exists():
        _is_shared_md = _shared_real.suffix.lower() == ".md"
        _owner = _md_created_by(_shared_real) if _is_shared_md else "admin@iaf.local"
        if not _principal_can_edit(_principal, _owner):
            raise HTTPException(403, f"Only the owner ({_owner}) or an admin can delete this file.")

    result = kernel.delete_file(path)
    if isinstance(result, str) and result.startswith("Error"):
        return {"path": path, "result": result, "error": True}
    return {"path": path, "result": result}


def _apply_local_mount_to_cached_kernels(
    tenant_id: str, user_id: str, mount_path: str | None
) -> int:
    """
    Hot-patch every cached SafeKernel that belongs to *tenant_id / user_id*
    so its ``local_mount`` attribute reflects the newly saved value.
    Returns the number of kernels patched.

    This avoids forcing a full session restart after the user changes
    their local-mount configuration.
    """
    from pathlib import Path

    resolved = Path(mount_path).resolve() if mount_path else None
    patched = 0
    # state.kernels keys look like  "tenant:agent:user"
    for key, kernel in getattr(state, "kernels", {}).items():
        parts = key.split(":")
        if len(parts) >= 3 and parts[0] == tenant_id and parts[2] == user_id:
            kernel.local_mount = resolved
            patched += 1
    return patched


@router.get("/api/files/local-mount")
async def get_local_mount(
    request: Request,
    tenant_id: str = TENANT_ID,
    user_id: str = "demo",
):
    """Return the current local-mount configuration for this user."""
    _principal, tenant_id, _agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_user=user_id,
        action="read",
        resource_type="file",
        resource_id="/local",
    )
    try:
        path = load_local_mount(tenant_id, user_id)
        return {
            "path": path,
            "enabled": path is not None,
        }
    except Exception as exc:
        logger.exception("Failed to read local-mount config")
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.post("/api/files/local-mount")
async def set_local_mount(
    request: Request,
    tenant_id: str = TENANT_ID,
    user_id: str = "demo",
    path: str = "",
    enabled: bool = True,
):
    """
    Save / update the local-mount configuration.

    Body params (query-string or JSON form):
      path    – absolute filesystem path the user wants to mount
      enabled – set False to disable without deleting the saved path
    """
    _principal, tenant_id, _agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_user=user_id,
        action="write",
        resource_type="file",
        resource_id="/local",
    )
    result = save_local_mount(tenant_id, user_id, path, enabled)

    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Validation failed"))

    # Hot-patch any already-cached kernels so /local works immediately
    mount_value = path if enabled else None
    patched = _apply_local_mount_to_cached_kernels(tenant_id, user_id, mount_value)
    result["kernels_patched"] = patched

    return result
