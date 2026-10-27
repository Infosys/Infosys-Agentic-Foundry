"""
progress_phases.py — ProgressPhase enum + ProgressTracker for visual stepper
═══════════════════════════════════════════════════════════════════════════════
Emits structured progress dicts through a callback for the frontend stepper.
Replaces raw string emit_status() in the REACT execution path.

WS message shape:
{
    "type": "progress",
    "phase": "loading_context",      # ProgressPhase.value
    "phase_index": 0,                # 0-based ordinal
    "phase_total": 6,                # total phases for progress %
    "status": "active",              # "active" | "completed" | "error"
    "sub_step": null,                # optional: tool name or sub-detail
    "detail": "Retrieving 3 eps",    # optional: human-readable context
    "elapsed_ms": 0,                 # ms since phase started
    "origin_session_id": "...",      # added by chat.py relay
    "timestamp": "..."               # added by chat.py relay
}
"""
from enum import Enum
import time
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ProgressPhase(str, Enum):
    """Known phases in the REACT agent execution pipeline.
    Ordered by typical execution sequence."""
    LOADING_CONTEXT    = "loading_context"      # 0
    BUILDING_PROMPT    = "building_prompt"       # 1
    GENERATING         = "generating"           # 2
    EXECUTING_TOOLS    = "executing_tools"       # 3
    PROCESSING         = "processing"           # 4
    SAVING             = "saving"               # 5


# Ordered list for index lookup
PHASE_ORDER: list[ProgressPhase] = list(ProgressPhase)
PHASE_INDEX: dict[ProgressPhase, int] = {p: i for i, p in enumerate(PHASE_ORDER)}


class ProgressTracker:
    """Thread-safe progress emitter that wraps a status_callback.

    Usage in agent.py:
        tracker = ProgressTracker(status_callback, phase_total=6)
        tracker.start_phase(ProgressPhase.LOADING_CONTEXT)
        tracker.sub_step(detail="Retrieving 3 episodes")
        tracker.complete_phase()
        tracker.start_phase(ProgressPhase.BUILDING_PROMPT, detail="4 turns")
        ...
    """

    def __init__(
        self,
        callback: Optional[Callable[[Any], None]] = None,
        phase_total: int = len(PHASE_ORDER),
    ):
        self._callback = callback
        self._phase_total = phase_total
        self._current_phase: Optional[ProgressPhase] = None
        self._phase_start: float = 0.0


    def start_phase(
        self,
        phase: ProgressPhase,
        *,
        detail: Optional[str] = None,
        sub_step: Optional[str] = None,
    ) -> None:
        """Mark a phase as active.  Auto-completes the previous phase."""
        # Auto-complete previous phase if still active
        if self._current_phase is not None and self._current_phase != phase:
            self.complete_phase()

        self._current_phase = phase
        self._phase_start = time.time()
        self._emit(phase, status="active", sub_step=sub_step, detail=detail)

    def complete_phase(
        self,
        phase: Optional[ProgressPhase] = None,
        *,
        detail: Optional[str] = None,
    ) -> None:
        """Mark the current (or specified) phase as completed."""
        target = phase or self._current_phase
        if target is None:
            return
        elapsed = int((time.time() - self._phase_start) * 1000) if self._phase_start else 0
        self._emit(target, status="completed", detail=detail, elapsed_ms=elapsed)
        if target == self._current_phase:
            self._current_phase = None
            self._phase_start = 0.0

    def sub_step(
        self,
        sub_step: str,
        *,
        detail: Optional[str] = None,
        status: str = "active",
    ) -> None:
        """Emit a sub-step within the current active phase."""
        phase = self._current_phase
        if phase is None:
            return  # No active phase — ignore silently
        elapsed = int((time.time() - self._phase_start) * 1000) if self._phase_start else 0
        self._emit(phase, status=status, sub_step=sub_step, detail=detail, elapsed_ms=elapsed)

    def error_phase(
        self,
        phase: Optional[ProgressPhase] = None,
        *,
        sub_step: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Mark a phase or sub-step as errored."""
        target = phase or self._current_phase
        if target is None:
            return
        elapsed = int((time.time() - self._phase_start) * 1000) if self._phase_start else 0
        self._emit(target, status="error", sub_step=sub_step, detail=detail, elapsed_ms=elapsed)

    # ── Backward-compatible string emit (for workflow/parallel/supervisor) ──

    def emit_status(self, msg: str) -> None:
        """Emit a plain string status — backward compat for non-REACT paths.
        The callback receives a raw string, just like the old emit_status()."""
        if self._callback:
            try:
                self._callback(msg)
            except Exception:
                pass


    def _emit(
        self,
        phase: ProgressPhase,
        *,
        status: str,
        sub_step: Optional[str] = None,
        detail: Optional[str] = None,
        elapsed_ms: int = 0,
    ) -> None:
        """Build the progress dict and invoke the callback."""
        if not self._callback:
            return
        payload = {
            "__progress__": True,  # Marker for chat.py to distinguish from str
            "phase": phase.value,
            "phase_index": PHASE_INDEX.get(phase, 0),
            "phase_total": self._phase_total,
            "status": status,
            "sub_step": sub_step,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
        }
        try:
            self._callback(payload)
        except Exception:
            logger.debug("Progress emit failed for phase=%s", phase.value, exc_info=True)
