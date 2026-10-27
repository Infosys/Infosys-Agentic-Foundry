"""Kernel runtime adapters for local and remote AgentOS execution.

The SkillAgent/tool surface intentionally stays shell-like.  This module moves
the execution target behind a small adapter so the real SafeKernel can run
in-process for development or behind a signed worker boundary for enterprise
deployments.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .kernel import SafeKernel

logger = logging.getLogger(__name__)


@runtime_checkable
class KernelRuntime(Protocol):
    tenant_id: str
    agent_id: str
    user_id: str | None
    user_role: str
    data_root: Path
    tenant_root: Path
    agent_root: Path
    shared_path: Path
    local_mount: Path | None
    current_skill: str | None

    def run_shell_command(self, command: str, confirmed: bool = False) -> str: ...
    def write_file(self, virtual_path: str, content: bytes | str, append: bool = False) -> str: ...
    def set_entitlement_context(self, principal=None, checker=None): ...
    def attach_hook_runner(self, *args, **kwargs): ...


class LocalKernelRuntime(SafeKernel):
    """Compatibility adapter: the existing SafeKernel remains the local runtime."""


REMOTE_KERNEL_UNCONFIGURED_MSG = (
    "Remote kernel signing key is not configured: set AGENTOS_KERNEL_TOKEN_SECRET "
    "(or JWT_SECRET) to the same value in both the Studio process and the kernel "
    "worker. The remote kernel backend fails closed without it."
)


def kernel_token_key() -> str:
    """Return the shared HMAC key for the remote kernel boundary, or "".

    Resolution order: ``AGENTOS_KERNEL_TOKEN_SECRET`` then ``JWT_SECRET``. There is
    deliberately no built-in default; callers must fail closed on "".
    """
    token_key = os.getenv("AGENTOS_KERNEL_TOKEN_SECRET", "").strip()
    if not token_key:
        token_key = os.getenv("JWT_SECRET", "").strip()
    return token_key


def require_kernel_token_key() -> str:
    """Return the shared kernel signing key or raise ``RuntimeError`` if unset."""
    token_key = kernel_token_key()
    if not token_key:
        raise RuntimeError(REMOTE_KERNEL_UNCONFIGURED_MSG)
    return token_key


def sign_kernel_request(body: bytes, token_key: str) -> str:
    """HMAC-SHA256 signature shared by the remote client and the kernel worker."""
    if not token_key:
        raise RuntimeError(REMOTE_KERNEL_UNCONFIGURED_MSG)
    return hmac.new(token_key.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _principal_to_dict(principal: Any) -> dict[str, Any] | None:
    if principal is None:
        return None
    return {
        "user_id": getattr(principal, "user_id", ""),
        "email": getattr(principal, "email", ""),
        "tenant_id": getattr(principal, "tenant_id", ""),
        "roles": list(getattr(principal, "roles", ()) or ()),
        "groups": list(getattr(principal, "groups", ()) or ()),
        "allowed_tenants": list(getattr(principal, "allowed_tenants", ()) or ()),
        "attributes": dict(getattr(principal, "attributes", {}) or {}),
    }


class RemoteKernelRuntime:
    """Client-side proxy for a SafeKernel owned by a separate kernel worker."""

    def __init__(
        self,
        *,
        data_root: str = "./data",
        tenant_id: str = "company",
        agent_id: str = "enterprise_agent",
        user_id: str | None = None,
        user_role: str = "user",
        require_confirmation: bool = False,
        confirm_operations: list[str] | None = None,
        confirm_paths: list[str] | None = None,
        local_mount: str | None = None,
        endpoint: str | None = None,
        token_key: str | None = None,
        **_extra: Any,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.user_role = user_role
        self.require_confirmation = require_confirmation
        self.confirm_operations = confirm_operations or ["write", "delete"]
        self.confirm_paths = confirm_paths
        self.local_mount = Path(local_mount).resolve() if local_mount else None
        self.tenant_root = self.data_root / "tenants" / tenant_id
        self.agent_root = self.tenant_root / "agents" / agent_id
        self.shared_path = self.tenant_root / "shared"
        self.global_shared = self.data_root / "global_shared"
        # ContextVar: session clones share one runtime, so a plain attribute would race across sessions.
        self._current_skill_cv: contextvars.ContextVar = contextvars.ContextVar(
            "remote_kernel_current_skill", default=None
        )
        self._endpoint = (endpoint or os.getenv("AGENTOS_KERNEL_URL", "http://127.0.0.1:18081")).rstrip("/")
        # Fail closed: no built-in signing key for the remote boundary.
        self._token_key = token_key or require_kernel_token_key()
        self._session_id = "|".join([
            str(self.data_root),
            tenant_id,
            agent_id,
            user_id or "",
            user_role,
        ])
        self._principal: dict[str, Any] | None = None

    @property
    def current_skill(self) -> str | None:
        return self._current_skill_cv.get()

    @current_skill.setter
    def current_skill(self, value: str | None) -> None:
        self._current_skill_cv.set(value)

    def set_entitlement_context(self, principal=None, checker=None):
        self._principal = _principal_to_dict(principal)

    def attach_hook_runner(self, *args, **kwargs):
        # Hook runners are in-process callables. The remote worker preserves the
        # hard kernel gates; model/tool hooks still run around the client tool.
        return None

    def run_shell_command(self, command: str, confirmed: bool = False) -> str:
        return str(self._call("run_shell_command", {"command": command, "confirmed": bool(confirmed)}).get("result", ""))

    def write_file(self, virtual_path: str, content: bytes | str, append: bool = False) -> str:
        payload: dict[str, Any] = {"path": virtual_path, "append": bool(append)}
        if isinstance(content, bytes):
            payload["content_b64"] = base64.b64encode(content).decode("ascii")
            payload["content_is_bytes"] = True
        else:
            payload["content"] = content
            payload["content_is_bytes"] = False
        return str(self._call("write_file", payload).get("result", ""))

    def _resolve_path(self, virtual_path: str) -> Path:
        """Compatibility helper for limited direct callers.

        Execution still happens in the worker. This local resolver exists for
        legacy cleanup/readback code that expects a Path object after a tool call.
        Must mirror SafeKernel layout: /me/ -> agent_root/users/{user_id}/, not
        tenant_root/users/.
        """
        path = str(virtual_path).strip()
        if ".." in path:
            raise ValueError("Path traversal is not allowed")
        if path == "/me/global.md":
            if not self.user_id:
                raise ValueError("/me/global.md requires user_id to be set")
            return (self.tenant_root / "users" / self.user_id / "profile.md").resolve()
        if path.startswith("/shared/"):
            return (self.shared_path / path[len("/shared/"):]).resolve()
        if path == "/shared":
            return self.shared_path.resolve()
        if path.startswith("/global/"):
            return (self.global_shared / path[len("/global/"):]).resolve()
        if path == "/global":
            return self.global_shared.resolve()
        if path.startswith("/memory/"):
            return (self.agent_root / "memory" / path[len("/memory/"):]).resolve()
        if path.startswith("/workspace/"):
            return (self.agent_root / "workspace" / path[len("/workspace/"):]).resolve()
        if self.user_id and (path == "/me" or path.startswith("/me/")):
            suffix = "" if path == "/me" else path[3:].lstrip("/")
            base = self.agent_root / "users" / self.user_id
            return (base / suffix).resolve() if suffix else base.resolve()
        if path.startswith("/local/") and self.local_mount:
            return (self.local_mount / path[len("/local/"):]).resolve()
        if path == "/local" and self.local_mount:
            return self.local_mount.resolve()
        return (self.agent_root / path.lstrip("/")).resolve()

    def _call(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {
                "op": op,
                "args": args,
                "session": self._session_payload(),
                "principal": self._principal,
                "current_skill": self.current_skill,
                "ts": time.time(),
            },
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self._endpoint}/kernel/execute",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-AgentOS-Kernel-Signature": sign_kernel_request(body, self._token_key),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=float(os.getenv("AGENTOS_KERNEL_TIMEOUT_SECONDS", "120"))) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            logger.warning("Kernel remote call failed: HTTP %s: %s", exc.code, detail[:500])
            return {"result": f"Error [KERNEL_REMOTE]: HTTP {exc.code}"}
        except Exception as exc:
            logger.exception("Kernel remote call failed")
            return {"result": "Error [KERNEL_REMOTE]: request failed"}
        if not data.get("ok", False):
            return {"result": data.get("error") or "Error [KERNEL_REMOTE]: remote execution failed"}
        return data

    def _session_payload(self) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "data_root": str(self.data_root),
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id or "",
            "user_role": self.user_role,
            "require_confirmation": self.require_confirmation,
            "confirm_operations": self.confirm_operations,
            "confirm_paths": self.confirm_paths,
            "local_mount": str(self.local_mount) if self.local_mount else "",
        }


def create_kernel_runtime(*, backend: str | None = None, **kwargs) -> KernelRuntime:
    selected = (backend or os.getenv("AGENTOS_KERNEL_BACKEND", "local")).strip().lower()
    if selected == "remote":
        return RemoteKernelRuntime(**kwargs)
    if selected == "local":
        return LocalKernelRuntime(**kwargs)
    if selected == "openshell":
        # Imported lazily and only inside this branch, so the optional OpenShell SDK
        # never loads for 'local'/'remote' deployments.
        from .openshell_runtime import OpenShellKernelRuntime

        return OpenShellKernelRuntime(**kwargs)
    # Fail closed: an unknown backend must not fall back to the in-process local kernel.
    raise ValueError(
        f"Unknown AGENTOS_KERNEL_BACKEND {selected!r}; expected 'local', 'remote' or "
        f"'openshell'. Refusing to fall back to in-process 'local' (fail-closed)."
    )

