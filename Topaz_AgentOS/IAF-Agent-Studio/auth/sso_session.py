"""Keycloak / SSO session bounds when the IdP is online or offline.

When Keycloak is enabled, local JWTs issued after SSO must not outlive the IdP
session indefinitely. While Keycloak is reachable we re-validate via the stored
refresh token; when it is offline we enforce a shorter offline TTL from login.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("iaf_server.auth.sso_session")

# Per-user single-flight locks so one request performs the rotating refresh and the rest reuse it.
_reval_locks: dict[str, asyncio.Lock] = {}
_REVAL_LOCKS_MAX = 4096


def _get_reval_lock(user_id: str) -> asyncio.Lock:
    """Return the single-flight lock for ``user_id``, bounding registry growth.

    One lock per distinct principal would otherwise accumulate forever in a
    long-lived worker (external/service ids especially). This runs entirely on the
    event loop with no await, so it is atomic: when the registry is full we evict
    only idle (unheld) locks — a held lock is mid-validation and must be kept, and
    an evicted idle lock is simply recreated on the next request for that user.
    """
    lock = _reval_locks.get(user_id)
    if lock is not None:
        return lock
    if len(_reval_locks) >= _REVAL_LOCKS_MAX:
        for uid in [u for u, l in _reval_locks.items() if not l.locked()]:
            del _reval_locks[uid]
    return _reval_locks.setdefault(user_id, asyncio.Lock())

SESSION_EXPIRED = "SSO_SESSION_EXPIRED"
IDP_UNAVAILABLE = "IDP_UNAVAILABLE"

_REACHABLE_CACHE: dict[str, Any] = {"checked_at": 0.0, "reachable": False}


def _cfg() -> tuple[int, int, int]:
    from shared.config import (
        KEYCLOAK_OFFLINE_SESSION_TTL_MINUTES,
        KEYCLOAK_SESSION_MAX_TTL_MINUTES,
        KEYCLOAK_REACHABILITY_CACHE_SECONDS,
    )
    return (
        KEYCLOAK_SESSION_MAX_TTL_MINUTES,
        KEYCLOAK_OFFLINE_SESSION_TTL_MINUTES,
        KEYCLOAK_REACHABILITY_CACHE_SECONDS,
    )


def _session_key(user_id: str) -> str:
    return f"auth:sso_session:{user_id}"


def _refresh_key(user_id: str) -> str:
    return f"auth:kc_refresh:{user_id}"


async def _redis():
    from shared.state import redis_client
    return redis_client


async def establish_session(
    user_id: str,
    *,
    provider: str = "keycloak",
    keycloak_refresh_token: str | None = None,
    refresh_ttl_seconds: int | None = None,
) -> None:
    """Record SSO session start and optionally persist the IdP refresh token."""
    if not user_id or provider != "keycloak":
        return
    started_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps({"provider": provider, "started_at": started_at})
    max_ttl_min, _, _ = _cfg()
    ttl = max(refresh_ttl_seconds or 0, max_ttl_min * 60 + 3600)
    client = await _redis()
    if client:
        try:
            await client.setex(_session_key(user_id), ttl, payload)
            if keycloak_refresh_token:
                await client.setex(
                    _refresh_key(user_id),
                    refresh_ttl_seconds or ttl,
                    keycloak_refresh_token,
                )
            return
        except Exception as exc:
            logger.debug("SSO session store skipped (redis): %s", exc)
    # In-process fallback for dev without Redis
    _local_sessions[user_id] = {"provider": provider, "started_at": started_at}
    if keycloak_refresh_token:
        _local_refresh[user_id] = keycloak_refresh_token


_local_sessions: dict[str, dict] = {}
_local_refresh: dict[str, str] = {}
_local_reval: dict[str, float] = {}


async def _should_revalidate(user_id: str) -> bool:
    """Throttle IdP re-validation to at most once per reachability-cache window.

    The SSO gate runs on EVERY ``/api`` and ``/auth`` request, and Keycloak
    rotates the refresh token on each use. Without a throttle, a page that fires
    several parallel calls would race to reuse a just-consumed token (one wins the
    rotation, the rest fail → the user is logged out mid-use). An atomic SET NX
    means only the first caller in each window performs the rotating refresh; the
    rest skip it and are allowed through on the strength of that recent check.
    """
    _, _, interval = _cfg()
    interval = max(5, int(interval or 30))
    key = f"auth:kc_reval:{user_id}"
    client = await _redis()
    if client:
        try:
            ok = await client.set(key, "1", ex=interval, nx=True)
            return bool(ok)
        except Exception as exc:
            logger.debug("KC revalidate throttle skipped (redis): %s", exc)
    now = time.time()
    if now - _local_reval.get(user_id, 0.0) >= interval:
        _local_reval[user_id] = now
        return True
    return False


async def _clear_revalidate(user_id: str) -> None:
    """Drop the re-validation throttle marker so the next request re-checks the
    IdP immediately. Used when a refresh FAILS — a known-bad session must not stay
    suppressed for the rest of the throttle window."""
    key = f"auth:kc_reval:{user_id}"
    client = await _redis()
    if client:
        try:
            await client.delete(key)
        except Exception as exc:
            logger.debug("KC revalidate throttle clear skipped (redis): %s", exc)
    # Always clear the in-process fallback too, or a stale local timestamp suppresses re-validation.
    _local_reval.pop(user_id, None)


async def _store_refresh_token(
    user_id: str,
    token: str,
    ttl_seconds: int | None = None,
) -> None:
    """Persist a (rotated) Keycloak refresh token WITHOUT touching the session
    record. Keycloak rotates the refresh token on every use, so after each
    re-validation the new token must replace the old one or the next cycle would
    reuse a consumed token and fail. Deliberately does not update ``started_at``
    so the absolute max-session cap keeps counting from the original login.
    """
    if not user_id or not token:
        return
    max_ttl_min, _, _ = _cfg()
    ttl = ttl_seconds or (max_ttl_min * 60 + 3600)
    client = await _redis()
    if client:
        try:
            await client.setex(_refresh_key(user_id), ttl, token)
            return
        except Exception as exc:
            logger.debug("KC refresh rotate store skipped (redis): %s", exc)
    _local_refresh[user_id] = token


async def clear_session(user_id: str) -> None:
    if not user_id:
        return
    client = await _redis()
    if client:
        try:
            await client.delete(
                _session_key(user_id), _refresh_key(user_id), f"auth:kc_reval:{user_id}"
            )
        except Exception:
            pass
    _local_sessions.pop(user_id, None)
    _local_refresh.pop(user_id, None)
    _local_reval.pop(user_id, None)


async def _load_session(user_id: str) -> Optional[dict]:
    client = await _redis()
    if client:
        try:
            raw = await client.get(_session_key(user_id))
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("SSO session load skipped: %s", exc)
    return _local_sessions.get(user_id)


async def _load_refresh_token(user_id: str) -> Optional[str]:
    client = await _redis()
    if client:
        try:
            raw = await client.get(_refresh_key(user_id))
            if raw:
                return raw.decode() if isinstance(raw, bytes) else str(raw)
        except Exception as exc:
            logger.debug("KC refresh load skipped: %s", exc)
    return _local_refresh.get(user_id)


def _session_age_seconds(started_at: str) -> float:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
    except Exception:
        return 0.0


async def keycloak_is_reachable() -> bool:
    """Cached probe of the Keycloak OIDC discovery document."""
    _, _, cache_seconds = _cfg()
    now = time.time()
    if now - float(_REACHABLE_CACHE.get("checked_at") or 0) < cache_seconds:
        return bool(_REACHABLE_CACHE.get("reachable"))
    reachable = False
    try:
        from auth.keycloak_service import get_keycloak_service
        kc = get_keycloak_service()
        if kc.is_enabled:
            reachable = await kc.is_reachable()
    except Exception as exc:
        logger.debug("Keycloak reachability probe failed: %s", exc)
    _REACHABLE_CACHE["checked_at"] = now
    _REACHABLE_CACHE["reachable"] = reachable
    return reachable


async def enforce_sso_session(user_id: str, *, provider: str | None) -> Optional[str]:
    """Return an error detail string when the SSO session must be terminated."""
    if provider != "keycloak":
        return None
    try:
        from shared.config import KEYCLOAK_ENABLED
    except ImportError:
        KEYCLOAK_ENABLED = False
    if not KEYCLOAK_ENABLED:
        return None

    session = await _load_session(user_id)
    if not session:
        # Legacy sessions predating this gate — allow until access token expires.
        return None

    max_ttl_min, offline_ttl_min, _ = _cfg()
    age_sec = _session_age_seconds(session.get("started_at", ""))
    if age_sec > max_ttl_min * 60:
        return SESSION_EXPIRED

    reachable = await keycloak_is_reachable()
    if reachable:
        # Single-flight per user within this worker; re-check inside the lock.
        lock = _get_reval_lock(user_id)
        async with lock:
            refresh = await _load_refresh_token(user_id)
            # Only re-validate against the IdP once per window (see _should_revalidate)
            # — the gate fires on every request, so unthrottled rotation would race.
            if refresh and await _should_revalidate(user_id):
                try:
                    from auth.keycloak_service import get_keycloak_service
                    new_tokens = await get_keycloak_service().refresh_tokens(refresh)
                except Exception as exc:
                    logger.info("SSO session IdP refresh failed for user=%s: %s", user_id, exc)
                    # On failure clear the throttle marker so the next request re-validates immediately.
                    await _clear_revalidate(user_id)
                    return SESSION_EXPIRED
                # Keycloak rotates the refresh token on use; persist the new one.
                rotated = getattr(new_tokens, "refresh_token", None)
                if rotated:
                    await _store_refresh_token(
                        user_id,
                        rotated,
                        ttl_seconds=getattr(new_tokens, "refresh_expires_in", None) or None,
                    )
        return None

    if age_sec > offline_ttl_min * 60:
        return SESSION_EXPIRED
    return None
