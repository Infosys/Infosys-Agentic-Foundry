"""
agent_os/self_auth.py — short-lived JWT minting for agent self-calls.

Problem this solves
-------------------
An agent in the middle of ``agent.run()`` has an in-memory entitlement
principal (via ``agent.entitlement_principal``) but no transit-form proof
of identity it can put in an HTTP ``Authorization: Bearer …`` header.
Calls from the agent's shell tool to its own server (e.g.
``curl POST /api/workstreams``) therefore fail with 401.

Adding a custom in-process tool per API endpoint (``create_workstream``,
``process_workstream_item``, …) sidesteps the problem but creates tool
sprawl and duplicates validation/hook firing across two code paths.

This module instead lets the agent **use the existing HTTP API the same
way humans do** by producing a signed JWT for the agent's principal,
short-lived, with a distinguishing claim so audit can tell agent-minted
tokens apart from user-login tokens.

Usage
-----

    from agent_os.self_auth import with_self_auth

    with with_self_auth(self.entitlement_principal):
        # IAF_AGENT_SELF_AUTH_TOKEN env var is set for any subprocess
        # spawned inside this block. The agent's curl can then do:
        #   curl -H "Authorization: Bearer $IAF_AGENT_SELF_AUTH_TOKEN" ...
        # and the existing auth middleware accepts it.
        run_agent_loop(...)

Security notes
--------------
* Token claims mirror ``create_access_token`` exactly so the existing
  middleware decode path works unchanged. We add a ``principal_kind:
  "service"`` claim so log analyzers + a future stricter middleware can
  treat agent-minted tokens differently.
* TTL is bounded [60s, 6h]. Default 1h covers a slow ReAct loop with
  many tool calls; if your agent runs longer than that, you have other
  problems.
* SELF_CALL_ALLOWED_PATHS is currently **advisory only** — enforced at
  the SKILL.md prompt level. A future enhancement should harden the
  auth middleware to deny non-allowlisted paths when
  ``principal_kind == "service"``.
* ``os.environ`` is process-wide; concurrent ``agent.run()`` with
  *different* principals would race. Today's use cases (single-chat
  orchestrator, Mission Mode parallel with uniform service:cron) are
  fine. For mixed-principal concurrency, switch to thread-local +
  per-subprocess env injection in ``kernel.run_shell()``.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# Environment variable the kernel publishes to the agent's shell subprocess.
ENV_VAR_NAME = "IAF_AGENT_SELF_AUTH_TOKEN"

# Advisory allowlist of self-callable paths; currently enforced only by SKILL.md prompts.
SELF_CALL_ALLOWED_PATHS: tuple[str, ...] = (
    "/api/workstreams",
    "/api/workstream-templates",
    "/api/skills",
    "/api/agents",
    "/api/conversations",
    "/api/files",
    "/api/evidence",
)

# Bounds on TTL. Below 60s tokens expire mid-LLM-call; above 6h they
# accumulate risk if leaked.
_TTL_MIN_SECONDS = 60
_TTL_MAX_SECONDS = 6 * 60 * 60


def _jwt_settings() -> tuple[str, str, str]:
    """Read JWT settings from environment without importing Studio modules."""

    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET unavailable — set JWT_SECRET before calling mint_service_jwt"
        )
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")
    tenant_id = os.getenv("TENANT_ID", "company")
    return secret, algorithm, tenant_id


@dataclass
class _PrincipalShape:
    """Minimal shape expected by mint_service_jwt. Used internally to
    normalize the various concrete principal types (ServicePrincipal,
    AuthenticatedUser, dataclass, dict, etc.) into one structure."""
    user_id: str
    email: str = ""
    role: str = "user"
    tenant_id: str = ""
    groups: tuple = ()
    allowed_tenants: tuple = ()


def _extract(principal: Any) -> _PrincipalShape:
    """Best-effort field extraction from various principal types."""
    if principal is None:
        return _PrincipalShape(user_id="")

    if isinstance(principal, dict):
        return _PrincipalShape(
            user_id=str(principal.get("user_id") or principal.get("sub") or ""),
            email=str(principal.get("email") or ""),
            role=str(principal.get("role") or "user"),
            tenant_id=str(principal.get("tenant_id") or ""),
            groups=tuple(principal.get("groups") or ()),
            allowed_tenants=tuple(principal.get("allowed_tenants") or ()),
        )

    return _PrincipalShape(
        user_id=str(getattr(principal, "user_id", "") or getattr(principal, "sub", "") or ""),
        email=str(getattr(principal, "email", "") or ""),
        role=str(getattr(principal, "role", "") or "user"),
        tenant_id=str(getattr(principal, "tenant_id", "") or ""),
        groups=tuple(getattr(principal, "groups", ()) or ()),
        allowed_tenants=tuple(getattr(principal, "allowed_tenants", ()) or ()),
    )


def mint_service_jwt(principal: Any, ttl_seconds: int = 3600) -> str:
    """Produce a short-lived signed access JWT for the agent's in-memory
    principal, so the agent can authenticate its own HTTP calls.

    Token shape mirrors ``create_access_token`` (in IAF-Agent-Studio's
    auth.tokens) so the existing auth middleware accepts it unchanged.
    Adds:

        principal_kind: "service"     # marker — agent-minted, not user-login

    Args:
        principal:     The agent's entitlement principal. ServicePrincipal,
                       AuthenticatedUser, dataclass, or dict accepted.
        ttl_seconds:   Token expiry in seconds. Clamped to [60s, 6h].

    Returns:
        Signed JWT string suitable for ``Authorization: Bearer <token>``.

    Raises:
        RuntimeError: python-jose missing, JWT_SECRET unavailable, or
                      principal has no user_id.
    """
    ttl_seconds = max(_TTL_MIN_SECONDS, min(int(ttl_seconds or 3600), _TTL_MAX_SECONDS))

    # Lazy imports — keeps agent_os import-light when Studio isn't loaded.
    try:
        from jose import jwt as _jwt
    except ImportError as exc:
        raise RuntimeError(
            "python-jose not installed — self-auth JWT minting requires it. "
            "Run: pip install python-jose[cryptography]"
        ) from exc

    jwt_secret, jwt_algorithm, default_tenant_id = _jwt_settings()

    p = _extract(principal)
    if not p.user_id:
        raise RuntimeError(
            "mint_service_jwt: principal has no user_id; cannot mint token"
        )

    now = datetime.now(timezone.utc)
    effective_tenant_id = p.tenant_id or default_tenant_id
    payload = {
        # Standard access-token claims (must match auth.tokens.create_access_token):
        "sub": p.user_id,
        "email": p.email,
        "role": p.role,
        "tenant_id": effective_tenant_id,
        "groups": list(p.groups),
        "allowed_tenants": list(p.allowed_tenants) or [effective_tenant_id],
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        # Self-auth marker — lets the auth middleware (future) treat these
        # tokens differently from user-login tokens.
        "principal_kind": "service",
    }

    token = _jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)
    logger.info(
        "self-auth: minted service JWT sub=%s tenant=%s role=%s ttl=%ds jti=%s",
        p.user_id, effective_tenant_id, p.role, ttl_seconds, payload["jti"][:8],
    )
    return token


def is_self_call_allowed(path: str) -> bool:
    """Advisory allowlist check. Returns True if ``path`` matches a prefix
    in SELF_CALL_ALLOWED_PATHS.

    Today this is informational — the auth middleware doesn't yet consult
    it. SKILL.md prompts steer agents to allowlisted paths; the next
    hardening step is to enforce here in the middleware.
    """
    p = (path or "").split("?", 1)[0].rstrip("/")
    if not p:
        return False
    for base in SELF_CALL_ALLOWED_PATHS:
        b = base.rstrip("/")
        if p == b or p.startswith(b + "/"):
            return True
    return False


@contextmanager
def with_self_auth(principal: Any, ttl_seconds: int = 3600) -> Iterator[Optional[str]]:
    """Set ``IAF_AGENT_SELF_AUTH_TOKEN`` env var for the duration of the
    block, then restore. Quietly skips if the principal is None or
    minting fails (so agent.run() continues working in test setups where
    no auth is configured).

    Yields:
        The minted token string, or None if minting was skipped.
    """
    if principal is None:
        yield None
        return

    try:
        token = mint_service_jwt(principal, ttl_seconds=ttl_seconds)
    except RuntimeError as exc:
        logger.debug("self-auth: skipping (mint failed): %s", exc)
        yield None
        return

    previous = os.environ.get(ENV_VAR_NAME)
    os.environ[ENV_VAR_NAME] = token
    try:
        yield token
    finally:
        if previous is None:
            os.environ.pop(ENV_VAR_NAME, None)
        else:
            os.environ[ENV_VAR_NAME] = previous
