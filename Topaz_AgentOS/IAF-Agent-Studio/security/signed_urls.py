"""Short-lived, identity-bound signatures for browser file rendering."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from shared.config import FILE_URL_SIGNING_SECRET, FILE_URL_TTL_SECONDS


class SignedUrlConfigurationError(RuntimeError):
    """Raised when signed URLs are required but no signing key is configured."""


def _payload(
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    path: str,
    expires_at: int,
) -> bytes:
    return "\n".join((tenant_id, agent_id, user_id, path, str(expires_at))).encode("utf-8")


def sign_file_request(
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    path: str,
    expires_at: int | None = None,
    secret: str | None = None,
) -> tuple[int, str]:
    key = secret if secret is not None else FILE_URL_SIGNING_SECRET
    if not key:
        raise SignedUrlConfigurationError("FILE_URL_SIGNING_SECRET is not configured")
    expiry = int(expires_at or (time.time() + FILE_URL_TTL_SECONDS))
    signature = hmac.new(
        key.encode("utf-8"),
        _payload(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            path=path,
            expires_at=expiry,
        ),
        hashlib.sha256,
    ).hexdigest()
    return expiry, signature


def verify_file_request(
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    path: str,
    expires_at: int,
    signature: str,
    secret: str | None = None,
    now: int | None = None,
) -> bool:
    current = int(time.time() if now is None else now)
    if int(expires_at) < current:
        return False
    try:
        _expiry, expected = sign_file_request(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            path=path,
            expires_at=int(expires_at),
            secret=secret,
        )
    except SignedUrlConfigurationError:
        return False
    return hmac.compare_digest(expected, str(signature or ""))


def build_signed_file_url(
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    path: str,
    expires_at: int | None = None,
) -> str:
    expiry, signature = sign_file_request(
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        path=path,
        expires_at=expires_at,
    )
    return "/api/files/serve?" + urlencode({
        "path": path,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "user_id": user_id,
        "expires": expiry,
        "signature": signature,
    })
