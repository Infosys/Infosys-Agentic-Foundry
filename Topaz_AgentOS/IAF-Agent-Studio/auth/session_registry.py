"""Interactive session registry: session index, revocation and single session.

Every interactive login gets a session id (``sid``) that is written into its
access and refresh tokens and kept across refreshes. Tabs and windows of one
browser share the same cookies and therefore the same ``sid``; only a login from
another browser or device creates a new session.

Three Redis structures, all keyed by ``sid``/user and never holding a token:

* **Session index** (always on) ``auth:sessions:{user_id}``: a hash of
  ``sid`` -> JSON ``{id, sid, created_at, last_seen_at, ip, user_agent,
  provider}``. ``id`` is a random public handle; the API returns it instead of
  the ``sid``. Backs ``GET /auth/sessions`` and the admin session list.
* **Revocation marker** (always on) ``auth:revoked_session:{sid}``: written on
  logout and absolute-lifetime expiry, and when a session is ended from another
  device, by "sign out of all devices" or by an administrator. A token carrying a revoked ``sid`` is rejected with
  ``401 SESSION_REVOKED`` on every request and on refresh. The marker lives as
  long as a refresh token can (``JWT_REFRESH_TTL_DAYS``), after which no token
  issued before the revocation can still be valid.
* **Single active session** (opt-in, ``AUTH_SINGLE_SESSION``)
  ``auth:active_session:{user_id}``: the user's current ``sid``; a token whose
  ``sid`` no longer matches gets ``401 SESSION_SUPERSEDED``.

Redis is the only store. An in-process map would disagree between workers, so
the request-time checks fail open on any Redis error (logged at most once a
minute). After a connection/timeout error a 30-second circuit breaker skips
Redis entirely, so an outage does not add client timeouts to every request. Revocation itself raises ``SessionStoreError`` so callers can report
that it did not happen.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("iaf_server.auth.session_registry")

SESSION_SUPERSEDED = "SESSION_SUPERSEDED"
SESSION_REVOKED = "SESSION_REVOKED"
# Readable, short-lived cookie the login page uses to explain why the user was
# signed out. Holds a reason code only.
LOGOUT_REASON_COOKIE = "iaf_logout_reason"
LOGOUT_REASON_SUPERSEDED = "session_superseded"
LOGOUT_REASON_REVOKED = "session_revoked"

_KEY = "auth:active_session:{user_id}"
_INDEX_KEY = "auth:sessions:{user_id}"
_REVOKED_KEY = "auth:revoked_session:{sid}"
_USER_AGENT_MAX = 200
_IP_MAX = 64
_WARN_INTERVAL_SECONDS = 60.0
_last_warning = 0.0


class SessionStoreError(RuntimeError):
    """The session store (Redis) is unavailable, so the operation did not happen."""


def enabled() -> bool:
    """True when AUTH_SINGLE_SESSION is on. The index and revocation are always on."""
    try:
        from shared.config import AUTH_SINGLE_SESSION
        return bool(AUTH_SINGLE_SESSION)
    except Exception:
        return False


def new_session_id() -> str:
    return uuid.uuid4().hex


def _raw_client():
    try:
        from shared.state import redis_client
        return redis_client
    except Exception:
        return None


# Circuit breaker: skip Redis for _BREAKER_SECONDS after a connection/timeout error.
_BREAKER_SECONDS = 30.0
_breaker_client = None
_breaker_until = 0.0


def _redis():
    client = _raw_client()
    if client is not None and client is _breaker_client and time.monotonic() < _breaker_until:
        return None
    return client


def _is_outage(exc: BaseException | None) -> bool:
    """Connection-level failure (redis-py ConnectionError/TimeoutError or OS
    socket errors), as opposed to a programming error."""
    if exc is None:
        return False
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    return any(cls.__name__ in ("ConnectionError", "TimeoutError") for cls in type(exc).__mro__)


def _trip(exc: BaseException | None) -> None:
    global _breaker_client, _breaker_until
    if _is_outage(exc):
        _breaker_client = _raw_client()
        _breaker_until = time.monotonic() + _BREAKER_SECONDS


def _ttl_seconds() -> int:
    try:
        from shared.config import JWT_REFRESH_TTL_DAYS
        return max(1, int(JWT_REFRESH_TTL_DAYS)) * 86400 + 60
    except Exception:
        return 86400 + 60


def _max_age_seconds() -> int:
    """Absolute session lifetime (AUTH_SESSION_MAX_HOURS), 0 when uncapped."""
    try:
        from shared.config import AUTH_SESSION_MAX_HOURS
        return max(0, int(AUTH_SESSION_MAX_HOURS)) * 3600
    except Exception:
        return 0


def _warn(message: str, exc: Exception | None = None) -> None:
    """Rate-limited warning; a connection-level ``exc`` also opens the breaker."""
    global _last_warning
    _trip(exc)
    now = time.monotonic()
    if now - _last_warning >= _WARN_INTERVAL_SECONDS:
        _last_warning = now
        logger.warning("Session registry: %s (%s)", message,
                       exc or "Redis unavailable or circuit open")


def _store_error(exc: Exception) -> SessionStoreError:
    _trip(exc)
    return SessionStoreError(str(exc))


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return str(value)



def _new_record(sid: str, *, ip: str, user_agent: str, provider: str,
                created_at: int | None = None) -> dict:
    now = int(time.time())
    return {
        "id": secrets.token_hex(8),
        "sid": sid,
        "created_at": int(created_at or now),
        "last_seen_at": now,
        "ip": (ip or "")[:_IP_MAX],
        "user_agent": (user_agent or "")[:_USER_AGENT_MAX],
        "provider": (provider or "")[:32],
    }


def _is_expired(record: dict, now: int) -> bool:
    if now - int(record.get("last_seen_at") or 0) > _ttl_seconds():
        return True
    max_age = _max_age_seconds()
    return bool(max_age and now - int(record.get("created_at") or 0) > max_age)


async def _load_index(client, user_id: str) -> dict[str, dict]:
    """Return the user's live sessions by sid, dropping expired/corrupt entries."""
    key = _INDEX_KEY.format(user_id=user_id)
    raw = await client.hgetall(key) or {}
    now = int(time.time())
    live: dict[str, dict] = {}
    stale: list[str] = []
    for field, value in raw.items():
        sid = _text(field) or ""
        try:
            record = json.loads(_text(value) or "")
        except (TypeError, ValueError):
            record = None
        if not isinstance(record, dict) or _is_expired(record, now):
            stale.append(sid)
            continue
        live[sid] = record
    if stale:
        await client.hdel(key, *stale)
    return live


async def _write_record(client, user_id: str, record: dict) -> None:
    key = _INDEX_KEY.format(user_id=user_id)
    await client.hset(key, record["sid"], json.dumps(record))
    await client.expire(key, _ttl_seconds())


async def register(user_id: str, sid: str, *, ip: str = "", user_agent: str = "",
                   provider: str = "") -> None:
    """Record a new interactive login.

    Always adds the session to the index. With AUTH_SINGLE_SESSION on it also
    becomes the user's only active session and the index keeps just this entry,
    since every older session is now superseded.
    """
    if not user_id or not sid:
        return
    client = _redis()
    if client is None:
        _warn("cannot record session")
        return
    if enabled():
        try:
            await client.setex(_KEY.format(user_id=user_id), _ttl_seconds(), sid)
        except Exception as exc:
            _warn("cannot record active session", exc)
    try:
        if enabled():
            await client.delete(_INDEX_KEY.format(user_id=user_id))
        else:
            await _load_index(client, user_id)  # prune expired entries
        await _write_record(client, user_id, _new_record(
            sid, ip=ip, user_agent=user_agent, provider=provider))
    except Exception as exc:
        _warn("cannot index session", exc)


async def touch(user_id: str, sid: str, *, ip: str = "", user_agent: str = "",
                provider: str = "", auth_time: int | None = None) -> None:
    """Renew ``sid`` on a refresh: update ``last_seen_at`` and extend TTLs.

    The active-session value is never written here: if a newer login landed
    between the refresh's ``is_current`` check and this call, writing would undo
    it. A session missing from the index (created before the index existed) is
    added unless it has been revoked.
    """
    if not user_id or not sid:
        return
    client = _redis()
    if client is None:
        return
    if enabled():
        key = _KEY.format(user_id=user_id)
        try:
            if _text(await client.get(key)) == sid:
                await client.expire(key, _ttl_seconds())
        except Exception as exc:
            _warn("cannot extend session", exc)
    try:
        index_key = _INDEX_KEY.format(user_id=user_id)
        raw = _text(await client.hget(index_key, sid))
        record = None
        if raw:
            try:
                record = json.loads(raw)
            except ValueError:
                record = None
        if isinstance(record, dict):
            record["last_seen_at"] = int(time.time())
        elif not await is_revoked(sid):
            record = _new_record(sid, ip=ip, user_agent=user_agent, provider=provider,
                                 created_at=auth_time)
        else:
            return
        await _write_record(client, user_id, record)
    except Exception as exc:
        _warn("cannot update session index", exc)


async def list_sessions(user_id: str) -> list[dict]:
    """The user's live sessions, most recently used first.

    Records include the internal ``sid``; callers must map them through
    ``public_view`` before returning them to a client. Raises
    ``SessionStoreError`` when Redis is unavailable.
    """
    if not user_id:
        return []
    client = _redis()
    if client is None:
        raise SessionStoreError("no Redis client")
    try:
        records = list((await _load_index(client, user_id)).values())
    except Exception as exc:
        raise _store_error(exc) from exc
    records.sort(key=lambda r: int(r.get("last_seen_at") or 0), reverse=True)
    return records


def _iso(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def public_view(record: dict, current_sid: str = "") -> dict:
    """Client-safe projection of an index record: no sid, no token."""
    return {
        "id": record.get("id", ""),
        "created_at": _iso(record.get("created_at")),
        "last_seen_at": _iso(record.get("last_seen_at")),
        "ip": record.get("ip", ""),
        "user_agent": record.get("user_agent", ""),
        "provider": record.get("provider", ""),
        "current": bool(current_sid) and record.get("sid") == current_sid,
    }



async def _revoke_sids(client, user_id: str, sids: list[str]) -> None:
    ttl = _ttl_seconds()
    for sid in sids:
        await client.setex(_REVOKED_KEY.format(sid=sid), ttl, "1")
    if sids:
        await client.hdel(_INDEX_KEY.format(user_id=user_id), *sids)


REVOKED = "revoked"
NOT_FOUND = "not_found"
IS_CURRENT = "current"


async def revoke(user_id: str, session_id: str, *, current_sid: str = "") -> str:
    """Revoke one of the user's sessions by its public ``id``.

    Returns ``REVOKED``, ``NOT_FOUND`` (no such session for this user) or
    ``IS_CURRENT`` (it is ``current_sid``, which is left alone: the caller
    should log out instead). Raises ``SessionStoreError`` when Redis is
    unavailable.
    """
    client = _redis()
    if client is None:
        raise SessionStoreError("no Redis client")
    if not user_id or not session_id:
        return NOT_FOUND
    try:
        index = await _load_index(client, user_id)
        sids = [sid for sid, rec in index.items() if rec.get("id") == session_id]
        if current_sid and current_sid in sids:
            return IS_CURRENT
        await _revoke_sids(client, user_id, sids)
    except Exception as exc:
        raise _store_error(exc) from exc
    return REVOKED if sids else NOT_FOUND


async def revoke_all(user_id: str, *, except_sid: str = "", include_sid: str = "") -> int:
    """Revoke every indexed session of the user except ``except_sid``.

    ``include_sid`` is revoked too even when missing from the index (e.g. the
    caller's own session on "sign out of all devices"). Returns the number of
    sessions revoked. Raises ``SessionStoreError`` when Redis is unavailable.
    """
    client = _redis()
    if client is None:
        raise SessionStoreError("no Redis client")
    if not user_id:
        return 0
    try:
        sids = [sid for sid in await _load_index(client, user_id) if sid != except_sid]
        if include_sid and include_sid != except_sid and include_sid not in sids:
            sids.append(include_sid)
        await _revoke_sids(client, user_id, sids)
    except Exception as exc:
        raise _store_error(exc) from exc
    return len(sids)


async def is_revoked(sid: str) -> bool:
    """True when ``sid`` has been revoked. Redis errors fail open (False)."""
    if not sid:
        return False
    client = _redis()
    if client is None:
        _warn("cannot check session revocation")
        return False
    try:
        return bool(await client.get(_REVOKED_KEY.format(sid=sid)))
    except Exception as exc:
        _warn("cannot check session revocation", exc)
        return False


async def check(user_id: str, sid: str) -> str | None:
    """Per-request session gate in one Redis round trip.

    Returns ``SESSION_REVOKED``, ``SESSION_SUPERSEDED`` (only with
    AUTH_SINGLE_SESSION on) or ``None`` when the session may proceed. Tokens
    without a ``sid`` (agent service tokens, legacy tokens) always pass, and
    Redis errors fail open.
    """
    if not user_id or not sid:
        return None
    client = _redis()
    if client is None:
        _warn("cannot check session")
        return None
    revoked_key = _REVOKED_KEY.format(sid=sid)
    try:
        if enabled():
            revoked, current = await client.mget(revoked_key, _KEY.format(user_id=user_id))
        else:
            revoked, current = await client.get(revoked_key), None
    except Exception as exc:
        _warn("cannot check session", exc)
        return None
    if revoked:
        return SESSION_REVOKED
    current = _text(current)
    if current is not None and current != sid:
        return SESSION_SUPERSEDED
    return None



async def is_current(user_id: str, sid: str) -> bool:
    """Return False only when the flag is on and another session has replaced ``sid``.

    Tokens without a ``sid`` (agent service tokens, tokens minted before this
    feature) and users with no recorded session are allowed. Redis errors fail open.
    """
    if not enabled() or not user_id or not sid:
        return True
    client = _redis()
    if client is None:
        _warn("cannot check session")
        return True
    try:
        current = await client.get(_KEY.format(user_id=user_id))
    except Exception as exc:
        _warn("cannot check session", exc)
        return True
    if current is None:
        return True
    return _text(current) == sid


# Stored on logout instead of deleting the key: with no record every sid counts
# as current, so an older session that was already replaced would come back.
_LOGGED_OUT = "-"


async def clear(user_id: str, sid: str) -> None:
    """End ``sid`` (logout, absolute-lifetime expiry).

    Always revokes it, so every token of that login is rejected: the refresh
    cookie (Path=/auth/refresh, never sent to /auth/logout, so it cannot be
    blacklisted there) and access tokens issued before the last refresh. Drops it
    from the index and, with AUTH_SINGLE_SESSION on, ends the active session if
    it is still ``sid``. The active key is overwritten with a marker rather than
    deleted, so sessions superseded earlier stay rejected until the next login.
    """
    if not user_id or not sid:
        return
    client = _redis()
    if client is None:
        _warn("cannot end session")
        return
    try:
        await client.setex(_REVOKED_KEY.format(sid=sid), _ttl_seconds(), "1")
    except Exception as exc:
        _warn("cannot revoke session", exc)
        return
    if enabled():
        key = _KEY.format(user_id=user_id)
        try:
            if _text(await client.get(key)) == sid:
                await client.setex(key, _ttl_seconds(), _LOGGED_OUT)
        except Exception as exc:
            _warn("cannot clear session", exc)
    try:
        await client.hdel(_INDEX_KEY.format(user_id=user_id), sid)
    except Exception as exc:
        _warn("cannot remove session from index", exc)
