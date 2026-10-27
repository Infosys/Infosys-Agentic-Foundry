"""Self-Evolution dependency availability (TC-204).

The Self-Improvement page must run analysis end-to-end when its dependencies are
present, and degrade gracefully with a clear, admin-facing message when they are
not — never surface a raw ImportError / stack trace.

This pure resolver maps two probe results (is the ``iaf_agent_skills.self_evolution``
module importable, and is Redis reachable) to a structured status the API and UI
can render deterministically. Kept dependency-free so it is unit-testable without
importing the heavy skills package or a live Redis.
"""
from __future__ import annotations

# Stable reason codes (UI branches on these).
REASON_READY = "ready"
REASON_DEGRADED_NO_REDIS = "degraded_no_redis"
REASON_MODULE_MISSING = "module_missing"


def resolve_evolution_availability(module_ok: bool, redis_ok: bool) -> dict:
    """Map dependency probes to a structured availability status.

    Args:
        module_ok: True if ``iaf_agent_skills.self_evolution`` imported cleanly.
        redis_ok:  True if Redis responded to a ping.

    Returns:
        ``{"available": bool, "reason": str, "detail": str, "redis": bool}``.

    Semantics:
        * Module missing  -> not available (the genuinely-absent case).
        * Module present, Redis down -> available but degraded (analysis runs
          without result caching; Redis is optional for correctness).
        * Both present -> ready.
    """
    if not module_ok:
        return {
            "available": False,
            "reason": REASON_MODULE_MISSING,
            "detail": (
                "Self-Evolution is not installed in this deployment. Add the "
                "iaf_agent_skills.self_evolution module to the image to enable it."
            ),
            "redis": bool(redis_ok),
        }
    if not redis_ok:
        return {
            "available": True,
            "reason": REASON_DEGRADED_NO_REDIS,
            "detail": (
                "Running without Redis — analysis works but results are not "
                "cached between runs. Set REDIS_URL to a reachable Redis to "
                "enable caching."
            ),
            "redis": False,
        }
    return {
        "available": True,
        "reason": REASON_READY,
        "detail": "Self-Evolution is ready.",
        "redis": True,
    }
