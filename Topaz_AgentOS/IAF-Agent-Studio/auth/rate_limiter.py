"""
auth/rate_limiter.py — Per-IP and per-user rate limiting

Uses Redis sliding window counters with TTL.
Falls back to in-process dict when Redis is unavailable.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("iaf_server.auth.rate_limiter")

_local_counters: dict[str, list[float]] = defaultdict(list)


def _local_check(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """Returns (allowed, remaining). Mutates _local_counters."""
    now = time.time()
    window_start = now - window_seconds
    hits = [t for t in _local_counters[key] if t > window_start]
    _local_counters[key] = hits
    if len(hits) >= limit:
        return False, 0
    _local_counters[key].append(now)
    return True, limit - len(_local_counters[key])



# Lua makes the sliding window atomic; a plain pipeline interleaves concurrent requests.
_LUA_RATE_LIMIT = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local window_start = now - window

redis.call("zremrangebyscore", key, 0, window_start)
local count = redis.call("zcard", key)
if count < limit then
    redis.call("zadd", key, now, tostring(now))
    redis.call("expire", key, window + 1)
    return limit - count - 1
else
    return -1
end
"""


async def _redis_check(
    redis, key: str, limit: int, window_seconds: int
) -> tuple[bool, int]:
    """
    Sliding window rate limit using Redis sorted set.
    Returns (allowed, remaining).
    """
    now = time.time()
    full_key = f"auth:ratelimit:{key}"
    remaining = await redis.eval(
        _LUA_RATE_LIMIT, 1, full_key, now, window_seconds, limit
    )
    if remaining < 0:
        return False, 0
    return True, int(remaining)



async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """
    Check if the request identified by `key` is within rate limits.
    Returns (allowed: bool, remaining: int).

    key examples:
      "ip:192.168.1.1"       — per-IP limit
      "user:user_id_abc"     — per-user limit
      "login:192.168.1.1"    — login-specific IP limit
    """
    try:
        from shared.state import redis_client
        if redis_client:
            return await _redis_check(redis_client, key, limit, window_seconds)
    except Exception as exc:
        logger.debug("Redis rate limit failed, using local: %s", exc)
    return _local_check(key, limit, window_seconds)


async def is_ip_allowed(ip: str) -> tuple[bool, int]:
    """
    General API rate limit: AUTH_RATE_LIMIT_PER_MINUTE requests/minute per IP.
    """
    try:
        from shared.config import AUTH_RATE_LIMIT_PER_MINUTE
        limit = AUTH_RATE_LIMIT_PER_MINUTE
    except ImportError:
        limit = 60
    return await check_rate_limit(f"ip:{ip}", limit, 60)


async def is_login_allowed(ip: str) -> tuple[bool, int]:
    """
    Strict login rate limit: AUTH_LOGIN_RATE_LIMIT attempts/minute per IP.
    Prevents credential stuffing.
    """
    try:
        from shared.config import AUTH_LOGIN_RATE_LIMIT
        limit = AUTH_LOGIN_RATE_LIMIT
    except ImportError:
        limit = 10
    return await check_rate_limit(f"login:{ip}", limit, 60)


async def is_tenant_allowed(tenant_id: str) -> tuple[bool, int]:
    """
    Global per-tenant API rate limit: TENANT_RATE_LIMIT_PER_MINUTE requests/minute across
    ALL of a tenant's users, shared across server instances via Redis (in-process fallback
    when Redis is down). Stops one tenant/customer from starving others.

    Returns (allowed, remaining). A configured limit <= 0 disables the check.
    """
    try:
        from shared.config import TENANT_RATE_LIMIT_PER_MINUTE
        limit = TENANT_RATE_LIMIT_PER_MINUTE
    except ImportError:
        limit = 600
    if limit <= 0:
        return True, -1
    return await check_rate_limit(f"tenant:{tenant_id}", limit, 60)


async def reset_login_counter(ip: str) -> None:
    """Clear the login counter for an IP (e.g., after successful CAPTCHA)."""
    key = f"auth:ratelimit:login:{ip}"
    try:
        from shared.state import redis_client
        if redis_client:
            await redis_client.delete(key)
            return
    except Exception:
        pass
    _local_counters.pop(f"login:{ip}", None)
