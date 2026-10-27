"""
auth/tokens.py — JWT access + refresh token management

Access token  : short-lived (15 min), httponly cookie. Payload holds only sub/sid/jti/type/iat/exp.
Refresh token : longer-lived (JWT_REFRESH_TTL_DAYS), httpOnly cookie, rotated on every
                refresh. Also carries auth_time (original login) so /auth/refresh can
                enforce the absolute session lifetime (AUTH_SESSION_MAX_HOURS).

Blacklist is maintained in Redis (or in-process dict as fallback).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("iaf_server.auth.tokens")

try:
    from jose import JWTError, jwt as _jwt
    _JOSE_AVAILABLE = True
except ImportError:
    _JOSE_AVAILABLE = False
    logger.warning("python-jose not installed — JWT auth disabled. Run: pip install python-jose[cryptography]")



def _cfg():
    from shared.config import JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_TTL_MINUTES, JWT_REFRESH_TTL_DAYS
    return JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_TTL_MINUTES, JWT_REFRESH_TTL_DAYS



def create_access_token(user_id: str, sid: str = "") -> str:
    """Issue a short-lived access token.

    The payload is deliberately minimal (subject, session id and token
    bookkeeping). Email, role, groups and tenant are looked up server-side from
    the user store on each request, so none of them can be read by decoding the
    token in the browser.
    """
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose not installed")
    secret, alg, ttl_min, _ = _cfg()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=ttl_min),
    }
    if sid:
        payload["sid"] = sid
    return _jwt.encode(payload, secret, algorithm=alg)


def create_refresh_token(
    user_id: str, sid: str = "", auth_time: Optional[int] = None
) -> tuple[str, str]:
    """
    Issue a long-lived refresh token.
    Returns (token_string, jti). ``sid`` is carried over on every refresh so a
    login session keeps one id for its whole life. ``auth_time`` (epoch seconds
    of the original interactive login) is carried the same way so /auth/refresh
    can enforce the absolute session lifetime (AUTH_SESSION_MAX_HOURS). It is
    kept out of the access token.
    """
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose not installed")
    secret, alg, _, ttl_days = _cfg()
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=ttl_days),
    }
    if sid:
        payload["sid"] = sid
    if auth_time is not None:
        payload["auth_time"] = int(auth_time)
    return _jwt.encode(payload, secret, algorithm=alg), jti



def decode_access_token(token: str) -> dict:
    """
    Decode and verify an access token.
    Raises jose.JWTError on invalid/expired tokens.
    """
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose not installed")
    secret, alg, _, _ = _cfg()
    payload = _jwt.decode(token, secret, algorithms=[alg])
    if payload.get("type") != "access":
        raise ValueError("Not an access token")
    return payload


def decode_refresh_token(token: str) -> dict:
    """
    Decode and verify a refresh token.
    Raises jose.JWTError on invalid/expired tokens.
    """
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose not installed")
    secret, alg, _, _ = _cfg()
    payload = _jwt.decode(token, secret, algorithms=[alg])
    if payload.get("type") != "refresh":
        raise ValueError("Not a refresh token")
    return payload


_local_blacklist: dict[str, float] = {}


def _prune_local_blacklist():
    now = time.time()
    expired = [jti for jti, exp in _local_blacklist.items() if exp < now]
    for jti in expired:
        del _local_blacklist[jti]



async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    """Add a JTI to the blacklist so it cannot be reused."""
    try:
        from shared.state import redis_client
        if redis_client:
            await redis_client.setex(f"auth:blacklist:{jti}", ttl_seconds, "1")
            return
    except Exception:
        pass
    # Fallback
    _prune_local_blacklist()
    _local_blacklist[jti] = time.time() + ttl_seconds


async def is_blacklisted(jti: str) -> bool:
    """Return True if the JTI has been blacklisted (token revoked)."""
    try:
        from shared.state import redis_client
        if redis_client:
            result = await redis_client.get(f"auth:blacklist:{jti}")
            return result is not None
    except Exception:
        pass
    _prune_local_blacklist()
    return jti in _local_blacklist
