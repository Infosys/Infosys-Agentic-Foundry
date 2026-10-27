"""
Enterprise Evidence Viewer source resolution.

LocalSource is fully implemented because local/shared/user files are produced by
the current SafeKernel file-mode runtime. Remote providers are intentionally
registered as explicit extension points so integrators know exactly where to add
SharePoint, Azure Blob, S3, or URL download logic without changing the Evidence
API or chat UI.
"""

from __future__ import annotations

import mimetypes
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from shared.config import AGENT_ID, DATA_ROOT, SERVER_DIR, TENANT_ID
from shared.protected_files import is_protected, is_protected_ext, is_protected_name

_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")


def valid_scope_id(value: str) -> bool:
    return isinstance(value, str) and bool(_SCOPE_ID_RE.match(value))


@dataclass(frozen=True)
class DocumentContent:
    source_uri: str
    display_name: str
    mime_type: str
    size_bytes: int
    # Local providers should return a tenant-scoped file path.
    path: Path | None = None
    # Remote providers may return bytes directly when no durable local path exists.
    payload: bytes | None = None


class DocumentSource:
    source_type = "unknown"

    def resolve(self, source_uri: str, *, tenant_id: str = "", agent_id: str = "",
                user_id: str = "") -> DocumentContent:
        raise NotImplementedError


class RemoteProviderStub(DocumentSource):
    """
    Base class for source providers that require enterprise-specific auth.

    Implementors should:
      1. Parse the provider URI into tenant/site/container/bucket/key fields.
      2. Resolve credentials from the platform credential backend, never SKILL.md.
      3. Download original bytes from the remote system.
      4. Return DocumentContent(payload=bytes, display_name=..., mime_type=...).
      5. Preserve tenant/user authorization checks before returning bytes.

    Keep provider failures explicit. Do not silently fall back to public URLs or
    local paths; evidence content must stay auditable and permission aware.
    """

    provider_name = "remote"
    uri_example = ""
    integration_notes = ""

    def resolve(self, source_uri: str, *, tenant_id: str = "", agent_id: str = "",
                user_id: str = "") -> DocumentContent:
        raise NotImplementedError(
            f"{self.__class__.__name__} is registered but not configured. "
            f"Implement shared/document_source.py::{self.__class__.__name__}.resolve() "
            f"to download bytes for {self.provider_name} evidence sources. "
            f"Expected URI example: {self.uri_example}. {self.integration_notes}"
        )


class SharePointSource(RemoteProviderStub):
    """
    SharePoint/OneDrive evidence source.

    Recommended URI:
      sharepoint://{tenant}/{site}/{drive_or_library}/{path/to/file.ext}

    Developer integration checklist:
      - Use Microsoft Graph, not browser session cookies.
      - Choose auth mode explicitly: app-only client credentials or delegated.
      - Store client id/sensitive/certificate references in credential backend/env.
      - Validate tenant/site access before downloading bytes.
      - Return DocumentContent(payload=downloaded_bytes, mime_type=Graph mime).
    """

    source_type = "sharepoint"
    provider_name = "SharePoint/Microsoft Graph"
    uri_example = "sharepoint://tenant/site/library/path/file.pdf"
    integration_notes = "Use Microsoft Graph /sites/{site-id}/drive/items/{item-id}/content."


class AzureBlobSource(RemoteProviderStub):
    """
    Azure Blob evidence source.

    Recommended URI:
      azblob://{account}/{container}/{path/to/blob.ext}

    Developer integration checklist:
      - Prefer Managed Identity or workload identity in Azure deployments.
      - For local/dev, resolve sensitive from credential backend/env.
      - Use Azure SDK BlobClient.download_blob().readall().
      - Return DocumentContent(payload=bytes, mime_type=content_settings.content_type).
    """

    source_type = "azure_blob"
    provider_name = "Azure Blob Storage"
    uri_example = "azblob://account/container/path/file.pdf"
    integration_notes = "Use azure-storage-blob BlobClient with tenant-scoped credentials."


class S3Source(RemoteProviderStub):
    """
    AWS S3 evidence source.

    Recommended URI:
      s3://{bucket}/{key}

    Developer integration checklist:
      - Use IAM role/session credentials where possible.
      - Enforce tenant allowlists for bucket/prefix access.
      - Use boto3 get_object(Bucket=..., Key=...) and read Body bytes.
      - Return DocumentContent(payload=bytes, mime_type=ContentType or guessed type).
    """

    source_type = "s3"
    provider_name = "AWS S3"
    uri_example = "s3://bucket/path/file.pdf"
    integration_notes = "Use boto3 S3 client with tenant-scoped bucket/prefix policy."


class URLSource(RemoteProviderStub):
    """
    Generic HTTP(S) evidence source.

    Recommended URI:
      https://host/path/file.ext

    Developer integration checklist:
      - Add SSRF protections before enabling: host allowlist, no private IPs,
        no redirects to disallowed hosts, size/time limits, content-type checks.
      - Resolve auth headers/tokens from credential backend, not SKILL.md.
      - Return DocumentContent(payload=response.content, mime_type=Content-Type).
    """

    source_type = "url"
    provider_name = "HTTP(S) URL"
    uri_example = "https://example.com/path/file.pdf"
    integration_notes = "Enable only with host allowlists and SSRF protections."


class LocalSource(DocumentSource):
    """Resolve SafeKernel-style local virtual paths to tenant-scoped files."""

    source_type = "local"

    def __init__(self, data_root: str | Path | None = None):
        root = Path(data_root or DATA_ROOT)
        self.data_root = root if root.is_absolute() else (SERVER_DIR / root).resolve()

    def resolve(self, source_uri: str, *, tenant_id: str = "", agent_id: str = "",
                user_id: str = "") -> DocumentContent:
        tenant = tenant_id or TENANT_ID
        agent = agent_id or AGENT_ID
        user = user_id or "demo"
        for ident in (tenant, agent, user):
            if not valid_scope_id(ident):
                raise PermissionError("Invalid tenant/agent/user id for evidence source")
        # Protected files are never served; the resolved target is re-checked for symlink aliases.
        if "\x00" in source_uri or is_protected(_strip_file_scheme(source_uri)):
            raise PermissionError("This path is protected and cannot be accessed as evidence")
        try:
            path = self._resolve_virtual_path(source_uri, tenant, agent, user)
        except ValueError as exc:
            raise PermissionError("Invalid evidence source path") from exc
        if is_protected_name(path.name) or is_protected_ext(path.name):
            raise PermissionError("This path is protected and cannot be accessed as evidence")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Evidence content not found: {source_uri}")
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return DocumentContent(
            source_uri=source_uri,
            display_name=path.name,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            path=path,
        )

    def _resolve_virtual_path(self, source_uri: str, tenant_id: str,
                              agent_id: str, user_id: str) -> Path:
        uri = _strip_file_scheme(source_uri)
        tenant_root = (self.data_root / "tenants" / tenant_id).resolve()
        shared_root = (tenant_root / "shared").resolve()
        agent_root = (tenant_root / "agents" / agent_id).resolve()
        # /me/ maps to the agent-scoped user folder (same as SafeKernel).
        user_root = (agent_root / "users" / user_id).resolve()

        if uri == "/shared" or uri.startswith("/shared/"):
            remainder = uri[8:] if uri.startswith("/shared/") else ""
            return _safe_join(shared_root, remainder)
        if uri == "/me" or uri.startswith("/me/"):
            remainder = uri[3:].lstrip("/") if uri.startswith("/me/") else ""
            return _safe_join(user_root, remainder)
        if uri == "/local" or uri.startswith("/local/"):
            remainder = uri[7:] if uri.startswith("/local/") else ""
            candidates = _load_local_mounts(self.data_root, tenant_id, user_id) + [agent_root]
            resolved_candidates = [_safe_join(root, remainder) for root in candidates]
            for resolved in resolved_candidates:
                if resolved.exists():
                    return resolved
            return resolved_candidates[0]

        raw = Path(uri)
        if raw.is_absolute():
            resolved = raw.resolve()
            allowed_roots = (shared_root, agent_root, user_root)
            if any(_is_relative_to(resolved, root) for root in allowed_roots):
                return _reject_other_users(resolved, agent_root, user_root)
            raise PermissionError(f"Path is outside tenant scope: {source_uri}")

        return _reject_other_users(_safe_join(agent_root, uri), agent_root, user_root)


def get_source(source_uri: str, source_type: str = "") -> DocumentSource:
    normalized_type = (source_type or "").strip().lower()
    parsed = urlparse(source_uri or "")
    scheme = parsed.scheme.lower()

    if normalized_type == "local" or (not normalized_type and (source_uri.startswith(("/", "file://")))):
        return LocalSource()
    if normalized_type == "sharepoint" or scheme == "sharepoint":
        return SharePointSource()
    if normalized_type in {"azure_blob", "azblob", "azure"} or scheme in {"azblob", "azureblob"}:
        return AzureBlobSource()
    if normalized_type == "s3" or scheme == "s3":
        return S3Source()
    if normalized_type in {"url", "http", "https"} or scheme in {"http", "https"}:
        return URLSource()
    raise NotImplementedError(f"Evidence source provider is not installed: {source_type or source_uri}")


def _strip_file_scheme(source_uri: str) -> str:
    if source_uri.startswith("file://"):
        parsed = urlparse(source_uri)
        return parsed.path
    return source_uri


def _safe_join(root: Path, remainder: str) -> Path:
    resolved = (root / remainder.lstrip("/")).resolve()
    if not _is_relative_to(resolved, root):
        raise PermissionError("Resolved path escapes tenant scope")
    return resolved


def _reject_other_users(path: Path, agent_root: Path, user_root: Path) -> Path:
    # Another user's /me folder is never reachable via an absolute or agent-relative path.
    if _is_relative_to(path, agent_root / "users") and not _is_relative_to(path, user_root):
        raise PermissionError("Path belongs to another user")
    return path


def _load_local_mounts(data_root: Path, tenant_id: str, user_id: str) -> list[Path]:
    candidates = [
        data_root / "tenants" / tenant_id / "users" / user_id / "local_mount.json",
        data_root / "tenants" / tenant_id / "config" / "tenant_local_mount.json",
    ]
    mounts: list[Path] = []
    for cfg_path in candidates:
        try:
            if not cfg_path.exists():
                continue
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if data.get("enabled") and data.get("path"):
                path = Path(data["path"]).expanduser().resolve()
                if path.is_dir():
                    mounts.append(path)
        except Exception:
            continue
    return mounts


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
