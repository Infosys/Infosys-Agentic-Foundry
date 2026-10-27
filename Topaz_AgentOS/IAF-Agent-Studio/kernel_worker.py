"""AgentOS remote kernel worker.

Runs the real SafeKernel behind a signed internal HTTP boundary. The main
AgentPro API can keep the natural shell tool surface while the kernel state,
credential handles, cwd, and Python subprocesses live in this worker process.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from shared.config import AGENTOS_KERNEL_WORKER_BIND, AGENTOS_KERNEL_WORKER_PORT
from agent_os import SafeKernel
from agent_os.kernel_runtime import (
    REMOTE_KERNEL_UNCONFIGURED_MSG,
    kernel_token_key,
    sign_kernel_request,
)
from security.models import Principal, Resource
from security.provider import get_entitlement_provider


logger = logging.getLogger(__name__)


def ensure_kernel_token_key() -> str:
    """Fail closed when the shared signing key is missing.

    The worker has no built-in key: Studio and the worker must both be started
    with the same AGENTOS_KERNEL_TOKEN_SECRET (or JWT_SECRET).
    """
    token_key = kernel_token_key()
    if not token_key:
        logger.critical("Kernel worker refusing to start. %s", REMOTE_KERNEL_UNCONFIGURED_MSG)
        raise RuntimeError(REMOTE_KERNEL_UNCONFIGURED_MSG)
    return token_key


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Covers `uvicorn kernel_worker:app` launches as well as `python3 kernel_worker.py`.
    ensure_kernel_token_key()
    yield


app = FastAPI(title="AgentOS Kernel Worker", version="1.0", lifespan=_lifespan)

_KERNELS: dict[str, tuple[float, SafeKernel]] = {}


def _verify(body: bytes, signature: str) -> None:
    token_key = kernel_token_key()
    if not token_key:
        # Never verify against an empty key; startup should have refused already.
        logger.critical("Kernel worker request rejected. %s", REMOTE_KERNEL_UNCONFIGURED_MSG)
        raise HTTPException(status_code=503, detail="Kernel worker signing key not configured")
    if not signature or not hmac.compare_digest(signature, sign_kernel_request(body, token_key)):
        raise HTTPException(status_code=401, detail="Invalid kernel worker signature")


class KernelRequest(BaseModel):
    op: str
    args: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any]
    principal: dict[str, Any] | None = None
    current_skill: str | None = None
    ts: float = 0


def _ttl() -> int:
    try:
        return max(60, min(int(os.getenv("AGENTOS_KERNEL_SESSION_TTL_SECONDS", "1800")), 24 * 3600))
    except ValueError:
        return 1800


def _clean_cache() -> None:
    now = time.time()
    ttl = _ttl()
    expired = [key for key, (seen, _kernel) in _KERNELS.items() if now - seen > ttl]
    for key in expired:
        _KERNELS.pop(key, None)


def _principal(payload: dict[str, Any] | None) -> Principal | None:
    if not payload:
        return None
    return Principal(
        user_id=str(payload.get("user_id") or ""),
        email=str(payload.get("email") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        roles=tuple(payload.get("roles") or ()),
        groups=tuple(payload.get("groups") or ()),
        allowed_tenants=tuple(payload.get("allowed_tenants") or ()),
        attributes=dict(payload.get("attributes") or {}),
    )


def _checker(principal: Principal):
    provider = get_entitlement_provider()

    def _check(action: str, resource_type: str, resource_id: str, context: dict | None = None) -> bool:
        resource = Resource(resource_type, resource_id, tenant_id=principal.tenant_id)
        return provider.check(principal, action, resource, context or {}).allowed

    return _check


def _kernel(session: dict[str, Any]) -> SafeKernel:
    _clean_cache()
    session_id = str(session.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing kernel session_id")
    cached = _KERNELS.get(session_id)
    if cached:
        _KERNELS[session_id] = (time.time(), cached[1])
        return cached[1]
    kernel = SafeKernel(
        data_root=str(session.get("data_root") or ""),
        tenant_id=str(session.get("tenant_id") or "company"),
        agent_id=str(session.get("agent_id") or "enterprise_agent"),
        user_id=str(session.get("user_id") or "") or None,
        user_role=str(session.get("user_role") or "user"),
        require_confirmation=bool(session.get("require_confirmation", False)),
        confirm_operations=list(session.get("confirm_operations") or ["write", "delete"]),
        confirm_paths=session.get("confirm_paths"),
        local_mount=str(session.get("local_mount") or "") or None,
    )
    _KERNELS[session_id] = (time.time(), kernel)
    return kernel


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "cached_kernels": len(_KERNELS)}


@app.post("/kernel/execute")
async def execute(request: Request) -> dict[str, Any]:
    body = await request.body()
    _verify(body, request.headers.get("X-AgentOS-Kernel-Signature", ""))
    payload = KernelRequest(**json.loads(body.decode("utf-8")))
    if payload.ts and abs(time.time() - float(payload.ts)) > 300:
        raise HTTPException(status_code=401, detail="Expired kernel worker request")

    kernel = _kernel(payload.session)
    kernel.current_skill = payload.current_skill
    principal = _principal(payload.principal)
    if principal:
        kernel.set_entitlement_context(principal, _checker(principal))

    try:
        if payload.op == "run_shell_command":
            result = kernel.run_shell_command(
                str(payload.args.get("command") or ""),
                confirmed=bool(payload.args.get("confirmed", False)),
            )
        elif payload.op == "write_file":
            if payload.args.get("content_is_bytes"):
                content = base64.b64decode(str(payload.args.get("content_b64") or ""))
            else:
                content = str(payload.args.get("content") or "")
            result = kernel.write_file(
                str(payload.args.get("path") or ""),
                content,
                append=bool(payload.args.get("append", False)),
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported kernel op: {payload.op}")
        return {"ok": True, "result": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Kernel worker op %r failed", payload.op)
        return {"ok": False, "error": "Kernel worker operation failed"}


if __name__ == "__main__":
    import uvicorn

    try:
        ensure_kernel_token_key()
    except RuntimeError:
        sys.exit(2)

    uvicorn.run(
        "kernel_worker:app",
        host=AGENTOS_KERNEL_WORKER_BIND or "127.0.0.1",
        port=AGENTOS_KERNEL_WORKER_PORT,
        reload=False,
    )

