"""Vision event → Workstream item materializer (enterprise ingress core).

This is the ONE genuinely-new core piece of the physical-AI pipeline. It sits
between the durable task queue and the Workstreams board:

    edge sensor → TaskQueue.submit(event) → worker dequeues
        → handle_vision_event(...)            ← THIS MODULE
        → WorkstreamStore.append_item(...)    → visible row in Workstreams UI
        → mission_engine runs the vision graph → classify → gate → verify → act

Design rules (why it looks like this):
  * Pure & dependency-injected. It imports no queue, no store, no HTTP. The
    caller passes an ``append_item`` callable and an optional ``entitlement_check``.
    That keeps it unit-testable with fakes (no Redis, no live server) and reusable
    by any transport (worker daemon, cron drain, direct API).
  * Fail-classified, never crash. Every outcome is a typed ``VisionOutcome`` so the
    worker can map it cleanly to ack / retry / dead-letter. Bad input is a
    *permanent* reject (DLQ), infrastructure hiccups are *transient* (retry).
  * Idempotent by ``event_id``. ``append_item`` raises on a duplicate id; we treat
    that as DEDUPED, so a camera firing twice for the same event is harmless.

The item the graph consumes only has {id, description, acceptance_criteria,
priority_metric} (WorkstreamItemIn). We therefore encode the frame path, the
question and the options into the description using explicit, regex-friendly
tokens (``frame=`` / ``options:``) so the graph's worker node can parse them —
mirroring how ``_parse_queue_ingest_task`` encodes queue jobs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Workstream names are filesystem-safe slugs (matches WorkstreamStore._NAME_RE).
_WORKSTREAM_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

# Bound the encoded description so we never write an unbounded string to YAML.
_DESCRIPTION_LIMIT = 1200
_MAX_OPTIONS = 12


class VisionOutcome(str, Enum):
    """Terminal classification of one vision event, consumed by the worker.

    The worker maps these to queue actions:
        MATERIALIZED → ack (row created, graph will run)
        DEDUPED      → ack (same event already present — safe no-op)
        REJECTED     → dead-letter (permanently invalid input; retry won't help)
        DENIED       → dead-letter (entitlement refused; retry won't help)
        ERROR        → nack / retry (transient failure — store locked, IO, etc.)
    """

    MATERIALIZED = "materialized"
    DEDUPED = "deduped"
    REJECTED = "rejected"
    DENIED = "denied"
    ERROR = "error"


class VisionEventError(ValueError):
    """Raised for permanently-invalid event payloads (→ REJECTED / dead-letter)."""


@dataclass(frozen=True)
class VisionEvent:
    """Normalized camera-trigger event. ``event_id`` is the dedup key + item id."""

    event_id: str
    workstream: str
    image_ref: str
    question: str
    camera_id: str = "unknown"
    options: tuple[str, ...] = ()          # empty → yes/no (noul) mode
    observed_verdict: Optional[str] = None  # what the cheap edge trigger already saw
    observed_confidence: Optional[float] = None
    priority_metric: Optional[float] = None
    acceptance_criteria: tuple[str, ...] = ()
    tenant_id: str = "company"
    ts: Optional[str] = None

    @property
    def mode(self) -> str:
        """'choice' when options are supplied, else 'noul' (calibrated yes/no)."""
        return "choice" if self.options else "noul"


@dataclass(frozen=True)
class VisionIngestResult:
    """Outcome of handling one event. ``item`` is set only on MATERIALIZED."""

    outcome: VisionOutcome
    workstream: str
    item_id: str
    reason: str = ""
    item: Optional[dict] = None

    @property
    def ok(self) -> bool:
        """True when the event reached a safe terminal state (row exists)."""
        return self.outcome in (VisionOutcome.MATERIALIZED, VisionOutcome.DEDUPED)



def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _coerce_options(raw: Any) -> tuple[str, ...]:
    """Accept list/tuple or a 'a,b,c' / 'a|b|c' string. Drop blanks, cap length."""
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        parts = re.split(r"[|,]", raw)
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        raise VisionEventError(f"options must be a list or delimited string, got {type(raw).__name__}")
    opts = [_clean_str(p) for p in parts]
    opts = [o for o in opts if o]
    if len(opts) == 1:
        # A single option is not a real choice — treat as malformed rather than
        # silently degrading to noul (which would hide an authoring mistake).
        raise VisionEventError("options must contain at least 2 distinct choices (or be empty for yes/no)")
    return tuple(opts[:_MAX_OPTIONS])


def _coerce_float(raw: Any, field_name: str) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise VisionEventError(f"{field_name} must be a number, got {raw!r}")


def normalize_event(raw: dict) -> VisionEvent:
    """Validate + coerce a raw event dict into a VisionEvent.

    Raises VisionEventError on any *permanent* problem (missing/blank required
    field, malformed options/numbers, bad workstream slug). The worker turns
    that into a dead-letter — retrying identical bad input never helps.
    """
    if not isinstance(raw, dict):
        raise VisionEventError(f"event must be a dict, got {type(raw).__name__}")

    event_id = _clean_str(raw.get("event_id"))
    workstream = _clean_str(raw.get("workstream"))
    image_ref = _clean_str(raw.get("image_ref"))
    question = _clean_str(raw.get("question"))

    missing = [n for n, v in (
        ("event_id", event_id), ("workstream", workstream),
        ("image_ref", image_ref), ("question", question),
    ) if not v]
    if missing:
        raise VisionEventError(f"missing required field(s): {', '.join(missing)}")

    if not _WORKSTREAM_NAME_RE.match(workstream):
        raise VisionEventError(f"invalid workstream name: {workstream!r}")

    acceptance = tuple(
        c for c in (_clean_str(x) for x in (raw.get("acceptance_criteria") or []))
        if c
    )

    return VisionEvent(
        event_id=event_id,
        workstream=workstream,
        image_ref=image_ref,
        question=question,
        camera_id=_clean_str(raw.get("camera_id")) or "unknown",
        options=_coerce_options(raw.get("options")),
        observed_verdict=_clean_str(raw.get("observed_verdict")) or None,
        observed_confidence=_coerce_float(raw.get("observed_confidence"), "observed_confidence"),
        priority_metric=_coerce_float(raw.get("priority_metric"), "priority_metric"),
        acceptance_criteria=acceptance,
        tenant_id=_clean_str(raw.get("tenant_id")) or "company",
        ts=_clean_str(raw.get("ts")) or None,
    )



def _default_acceptance(evt: VisionEvent) -> tuple[str, ...]:
    """A sensible acceptance checklist when the caller didn't supply one."""
    return (
        "The frame clearly shows the inspected subject (else escalate).",
        f"An independent verifier confirms: {evt.question}",
    )


def build_item(evt: VisionEvent) -> dict:
    """Render a VisionEvent into a WorkstreamItemIn-shaped dict.

    The frame path and question are encoded with explicit ``frame=`` / ``options:``
    tokens so the graph's worker node can regex them back out deterministically.
    """
    lines = [
        f"[vision] camera={evt.camera_id} frame={evt.image_ref}",
        f"Q: {evt.question}",
    ]
    if evt.options:
        lines.append("options: " + " | ".join(evt.options))
    if evt.observed_verdict:
        conf = f" ({evt.observed_confidence:.2f})" if evt.observed_confidence is not None else ""
        lines.append(f"observed: {evt.observed_verdict}{conf}")
    description = "\n".join(lines)[:_DESCRIPTION_LIMIT]

    acceptance = list(evt.acceptance_criteria or _default_acceptance(evt))

    item: dict = {
        "id": evt.event_id,
        "description": description,
        "acceptance_criteria": acceptance,
    }
    if evt.priority_metric is not None:
        item["priority_metric"] = evt.priority_metric
    return item



AppendItem = Callable[[str, dict], dict]
EntitlementCheck = Callable[[VisionEvent], tuple[bool, str]]


def handle_vision_event(
    raw: dict,
    *,
    append_item: AppendItem,
    entitlement_check: Optional[EntitlementCheck] = None,
) -> VisionIngestResult:
    """Materialize one camera event as a Workstream item. Never raises.

    Args:
        raw: the event payload pulled off the queue.
        append_item: WorkstreamStore.append_item (or a fake). Must raise
            ValueError containing 'already present' on duplicate id, and
            FileNotFoundError when the workstream doesn't exist.
        entitlement_check: optional gate. Return (False, reason) to deny an
            event (e.g. camera/tenant lacks ``vision_allowed``).

    Returns:
        VisionIngestResult with a typed VisionOutcome for the worker to route.
    """
    # 1) Normalize — permanent-invalid input dead-letters here.
    try:
        evt = normalize_event(raw)
    except VisionEventError as exc:
        ws = _clean_str(raw.get("workstream")) if isinstance(raw, dict) else ""
        eid = _clean_str(raw.get("event_id")) if isinstance(raw, dict) else ""
        logger.warning("vision event rejected: %s", exc)
        return VisionIngestResult(VisionOutcome.REJECTED, ws, eid, reason=str(exc))

    # 2) Entitlement — deny before we ever write a row.
    if entitlement_check is not None:
        try:
            allowed, reason = entitlement_check(evt)
        except Exception as exc:  # a broken checker is transient, not a denial
            logger.exception("entitlement check errored for %s", evt.event_id)
            return VisionIngestResult(VisionOutcome.ERROR, evt.workstream, evt.event_id,
                                      reason=f"entitlement check failed: {exc}")
        if not allowed:
            logger.warning("vision event %s denied: %s", evt.event_id, reason)
            return VisionIngestResult(VisionOutcome.DENIED, evt.workstream, evt.event_id,
                                      reason=reason or "entitlement denied")

    # 3) Materialize — the visible Workstreams row.
    item = build_item(evt)
    try:
        stored = append_item(evt.workstream, item)
    except FileNotFoundError as exc:
        # Unknown workstream is an authoring/config error → permanent.
        logger.warning("vision event %s targets missing workstream %s", evt.event_id, evt.workstream)
        return VisionIngestResult(VisionOutcome.REJECTED, evt.workstream, evt.event_id, reason=str(exc))
    except ValueError as exc:
        if "already present" in str(exc).lower():
            # Same camera event seen twice — idempotent no-op.
            return VisionIngestResult(VisionOutcome.DEDUPED, evt.workstream, evt.event_id,
                                      reason="duplicate event_id")
        # Any other ValueError (e.g. failed item validation) is permanent.
        logger.warning("vision event %s rejected by store: %s", evt.event_id, exc)
        return VisionIngestResult(VisionOutcome.REJECTED, evt.workstream, evt.event_id, reason=str(exc))
    except Exception as exc:  # store locked / IO / anything transient → retry
        logger.exception("vision event %s transient append failure", evt.event_id)
        return VisionIngestResult(VisionOutcome.ERROR, evt.workstream, evt.event_id,
                                  reason=f"append failed: {exc}")

    logger.info("vision event %s materialized in workstream %s", evt.event_id, evt.workstream)
    return VisionIngestResult(VisionOutcome.MATERIALIZED, evt.workstream, evt.event_id,
                              item=stored if isinstance(stored, dict) else item)
