"""Vision edge — config-driven event construction + submission (producer side).

The sensor that watches cameras uses this to turn "camera X saw Y" into a durable
``vision_event`` task, WITHOUT hardcoding anything per use case. Everything a new
use case needs lives in the tenant ``camera_registry`` (one row per camera), so
adding a camera is a config edit, not a code change (Tier-0 reuse).

    sensor detects change on camera → jev trigger observes verdict/confidence
        → VisionEdge.emit(camera_id, frame_ref, verdict, confidence)   ← HERE
        → looks up the camera's sensing spec + trigger rule
        → if it should fire: build event → make_vision_task → submit(task)
        → durable queue → worker → Workstreams row

Submission is injected (``submit_task``) so this module is testable without Redis;
in production the sensor passes a thin wrapper around ``TaskQueue.submit``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .vision_worker import make_vision_task

logger = logging.getLogger(__name__)

_MAX_OPTIONS = 12


@dataclass(frozen=True)
class CameraSpec:
    """One camera's sensing contract — a single row of the camera_registry.

    Attributes:
        camera_id:   stable id, also the frame folder namespace.
        workstream:  target workstream that runs the vision graph.
        question:    what to ask each frame (choice criteria or yes/no).
        options:     choices for 'choice' mode; empty → calibrated yes/no.
        gate:        min observed confidence for the edge trigger to fire.
        fire_on:     verdicts that warrant firing (empty → any verdict fires).
        frames_dir:  root where frames are stored (path convention below).
        tenant_id:   owning tenant.
    """

    camera_id: str
    workstream: str
    question: str
    options: tuple[str, ...] = ()
    gate: float = 0.0
    fire_on: tuple[str, ...] = ()
    frames_dir: str = "shared/frames"
    tenant_id: str = "company"


def _as_tuple(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace("|", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw]
    else:
        return ()
    return tuple(p for p in parts if p)[:_MAX_OPTIONS]


def load_camera_registry(source: Any) -> dict[str, CameraSpec]:
    """Load {camera_id: CameraSpec} from a dict, a list of rows, or a YAML path.

    Accepts either the parsed registry (dict/list — used by tests and callers who
    already loaded YAML) or a filesystem path to a ``camera_registry.yaml``.
    """
    rows: Any
    if isinstance(source, (str, Path)):
        import yaml  # lazy: only needed for the path form
        data = yaml.safe_load(Path(source).read_text(encoding="utf-8")) or {}
        rows = data.get("cameras", data)
    else:
        rows = source

    if isinstance(rows, dict):
        iterable = [dict(v, camera_id=v.get("camera_id", k)) for k, v in rows.items()]
    elif isinstance(rows, list):
        iterable = rows
    else:
        raise ValueError(f"unsupported camera_registry shape: {type(rows).__name__}")

    registry: dict[str, CameraSpec] = {}
    for row in iterable:
        cam = str(row.get("camera_id", "")).strip()
        if not cam:
            raise ValueError("camera_registry row missing camera_id")
        for req in ("workstream", "question"):
            if not str(row.get(req, "")).strip():
                raise ValueError(f"camera {cam!r} missing required field {req!r}")
        registry[cam] = CameraSpec(
            camera_id=cam,
            workstream=str(row["workstream"]).strip(),
            question=str(row["question"]).strip(),
            options=_as_tuple(row.get("options")),
            gate=float(row.get("gate", 0.0) or 0.0),
            fire_on=_as_tuple(row.get("fire_on")),
            frames_dir=str(row.get("frames_dir", "shared/frames")).strip() or "shared/frames",
            tenant_id=str(row.get("tenant_id", "company")).strip() or "company",
        )
    return registry


def frame_path(spec: CameraSpec, event_id: str) -> str:
    """Deterministic frame location: <frames_dir>/<workstream>/<event_id>.jpg.

    Naming frames by event id lets the graph derive the image path from the item
    id — no need to smuggle paths around.
    """
    return str(Path(spec.frames_dir) / spec.workstream / f"{event_id}.jpg")


def should_fire(spec: CameraSpec, observed_verdict: Optional[str],
                observed_confidence: Optional[float]) -> bool:
    """Trigger rule: fire only if confidence clears the gate AND (no verdict
    allow-list, or the observed verdict is in it). Missing confidence never fires.
    """
    if observed_confidence is None or observed_confidence < spec.gate:
        return False
    if spec.fire_on and (observed_verdict or "").strip() not in spec.fire_on:
        return False
    return True


def build_event(
    spec: CameraSpec,
    *,
    frame_ref: Optional[str] = None,
    observed_verdict: Optional[str] = None,
    observed_confidence: Optional[float] = None,
    event_id: Optional[str] = None,
    priority_metric: Optional[float] = None,
) -> dict:
    """Assemble the event dict (matches vision_event_handler.normalize_event input)."""
    eid = (event_id or "").strip() or f"{spec.camera_id}-{uuid.uuid4().hex[:8]}"
    ref = (frame_ref or "").strip() or frame_path(spec, eid)
    event: dict = {
        "event_id": eid,
        "workstream": spec.workstream,
        "image_ref": ref,
        "question": spec.question,
        "camera_id": spec.camera_id,
        "tenant_id": spec.tenant_id,
    }
    if spec.options:
        event["options"] = list(spec.options)
    if observed_verdict:
        event["observed_verdict"] = observed_verdict
    if observed_confidence is not None:
        event["observed_confidence"] = observed_confidence
    if priority_metric is not None:
        event["priority_metric"] = priority_metric
    return event


@dataclass
class EmitResult:
    """Outcome of an emit() call."""
    fired: bool
    reason: str = ""
    task_id: Optional[str] = None
    event: Optional[dict] = None


class QueueSubmitter:
    """Sync adapter over the async durable ``TaskQueue`` for a long-running sensor.

    ``TaskQueue.submit`` is a coroutine whose Redis connection is bound to the event
    loop that created it, so we can't ``asyncio.run`` per call (that opens/closes a
    loop each time and breaks the connection). Instead we own ONE background loop in
    a daemon thread and marshal each submit onto it via ``run_coroutine_threadsafe``.

    Usage:
        submitter = QueueSubmitter(task_queue)      # task_queue: TaskQueue (async)
        edge = VisionEdge(registry, submitter)      # submitter is the sync callable
        ... submitter.close() on shutdown
    """

    def __init__(self, queue: Any, submit_timeout: float = 30.0):
        self._queue = queue
        self._submit_timeout = submit_timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="vision-queue-submitter")
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def __call__(self, task: Any) -> str:
        """Submit a TaskDefinition synchronously; returns the task id."""
        fut = asyncio.run_coroutine_threadsafe(self._queue.submit(task), self._loop)
        return fut.result(timeout=self._submit_timeout)

    def close(self) -> None:
        """Stop the background loop (call on sensor shutdown)."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


class VisionEdge:
    """Producer: maps a camera observation to a durable queued vision task.

    Args:
        registry: {camera_id: CameraSpec} (from load_camera_registry).
        submit_task: callable that persists a TaskDefinition and returns a task
            id — in prod a thin sync wrapper around ``TaskQueue.submit``.
    """

    def __init__(self, registry: dict[str, CameraSpec],
                 submit_task: Callable[[Any], str]):
        self._registry = registry
        self._submit = submit_task

    def emit(
        self,
        camera_id: str,
        *,
        frame_ref: Optional[str] = None,
        observed_verdict: Optional[str] = None,
        observed_confidence: Optional[float] = None,
        event_id: Optional[str] = None,
        priority_metric: Optional[float] = None,
        force: bool = False,
    ) -> EmitResult:
        """Consider one observation; submit a task iff the trigger rule fires.

        ``force=True`` bypasses the gate (used for manual/test injection).
        """
        spec = self._registry.get(camera_id)
        if spec is None:
            return EmitResult(False, reason=f"unknown camera {camera_id!r}")

        if not force and not should_fire(spec, observed_verdict, observed_confidence):
            return EmitResult(False, reason="below gate or verdict not in fire_on")

        event = build_event(
            spec,
            frame_ref=frame_ref,
            observed_verdict=observed_verdict,
            observed_confidence=observed_confidence,
            event_id=event_id,
            priority_metric=priority_metric,
        )
        task = make_vision_task(event, tenant_id=spec.tenant_id)
        task_id = self._submit(task)
        logger.info("vision edge fired camera=%s event=%s task=%s",
                    camera_id, event["event_id"], task_id)
        return EmitResult(True, task_id=task_id, event=event)
