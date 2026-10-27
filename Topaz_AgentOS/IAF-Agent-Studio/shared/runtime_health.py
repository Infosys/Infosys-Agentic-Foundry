"""Lightweight readiness checks for role-specific runtime dependencies."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Protocol


class SessionStateHealth(Protocol):
    async def connect(self) -> bool: ...

    async def health_check(self) -> bool: ...


async def connect_session_dependency(
    *,
    roles: Iterable[str],
    session_state: SessionStateHealth,
    strict_mode: bool,
    timeout_seconds: float = 3.0,
) -> bool:
    """Connect API session state, failing closed for strict deployments."""
    if "api" not in roles:
        return True
    try:
        connected = await asyncio.wait_for(
            session_state.connect(),
            timeout=timeout_seconds,
        )
    except Exception:
        connected = False
    if strict_mode and not connected:
        raise RuntimeError(
            "Shared Redis session state is unavailable for the strict API role"
        )
    return connected


async def session_readiness(
    *,
    roles: Iterable[str],
    session_state: SessionStateHealth,
    timeout_seconds: float = 3.0,
) -> str:
    """Return the API session dependency state without exposing connection data."""
    if "api" not in roles:
        return "not_required"
    try:
        healthy = await asyncio.wait_for(
            session_state.health_check(),
            timeout=timeout_seconds,
        )
    except (TimeoutError, OSError):
        healthy = False
    except Exception:
        healthy = False
    return "ready" if healthy else "unavailable"
