"""Background-task hook fan-out helpers.

Some platform paths (self-evolution analysis, scheduled audit sweeps, demo
seeders) execute outside any SkillAgent context yet still need to fire the
Phase 3b ``OnSelfEvolutionPass`` / ``OnSkillGapDetected`` / ``OnMemoryWrite``
events. This module exposes a process-wide "background runner" that any
HookRunner can register with — typically a SkillAgent does this at
construction so the most recently active per-tenant runner becomes the
fallback target for background fan-outs.

Design notes:
  * Single-process scope. Multi-process workers must register their own.
  * Last-writer-wins. Background events are tenant-agnostic anyway (self-
    evolution analyses the whole code base), so the latest-registered
    runner is a reasonable default. Per-tenant routing can be added later
    by keying on tenant_id in session_ctx.
  * Silent no-op when no runner is registered. Callers do not need to
    guard ``if runner is not None`` — the helpers do.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BACKGROUND_RUNNER: Optional[Any] = None


def register_background_runner(runner: Any) -> None:
    """Register a HookRunner as the process-wide background event target.

    Called by ``SkillAgent.__init__`` after the agent's own HookRunner is
    built. Safe to call multiple times — last writer wins.
    """
    global _BACKGROUND_RUNNER
    _BACKGROUND_RUNNER = runner


def get_background_runner() -> Optional[Any]:
    """Return the current background runner or None if none registered."""
    return _BACKGROUND_RUNNER


def fire_on_self_evolution_pass(
    *,
    pass_id: str = "",
    skills_analyzed: int = 0,
    gaps_found: int = 0,
    duration_ms: int = 0,
    session_ctx: Optional[dict] = None,
) -> None:
    """Fire OnSelfEvolutionPass. No-op when no runner is registered."""
    runner = _BACKGROUND_RUNNER
    if runner is None or not hasattr(runner, "run_on_self_evolution_pass"):
        return
    try:
        runner.run_on_self_evolution_pass(
            pass_id=pass_id,
            skills_analyzed=skills_analyzed,
            gaps_found=gaps_found,
            duration_ms=duration_ms,
            session_ctx=session_ctx,
        )
    except Exception as exc:  # pragma: no cover - observe-only
        logger.debug("background_hooks: OnSelfEvolutionPass error (non-fatal): %s", exc)


def fire_on_skill_gap_detected(
    *,
    skill_name: str = "",
    gap_summary: str = "",
    severity: str = "",
    session_ctx: Optional[dict] = None,
) -> None:
    """Fire OnSkillGapDetected. No-op when no runner is registered."""
    runner = _BACKGROUND_RUNNER
    if runner is None or not hasattr(runner, "run_on_skill_gap_detected"):
        return
    try:
        runner.run_on_skill_gap_detected(
            skill_name=skill_name,
            gap_summary=gap_summary,
            severity=severity,
            session_ctx=session_ctx,
        )
    except Exception as exc:  # pragma: no cover - observe-only
        logger.debug("background_hooks: OnSkillGapDetected error (non-fatal): %s", exc)


def fire_on_background_task_error(
    *,
    task_name: str = "",
    error_msg: str = "",
    session_ctx: Optional[dict] = None,
) -> None:
    """Fire OnBackgroundTaskError. No-op when no runner is registered."""
    runner = _BACKGROUND_RUNNER
    if runner is None or not hasattr(runner, "run_on_background_task_error"):
        return
    try:
        runner.run_on_background_task_error(
            task_name=task_name,
            error_msg=error_msg,
            session_ctx=session_ctx,
        )
    except Exception as exc:  # pragma: no cover - observe-only
        logger.debug("background_hooks: OnBackgroundTaskError error (non-fatal): %s", exc)
