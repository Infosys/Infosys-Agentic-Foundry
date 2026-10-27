"""Shadow-safe taxonomy routing facade over TaxonomySignalIndex.

The production default is `current`: calls pass straight through to the existing
TaxonomySignalIndex behavior. `shadow` mode returns the current result first and
compares a candidate provider asynchronously, recording bounded drift metadata.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

TAXONOMY_ROUTING_MODE_ENV = "TAXONOMY_ROUTING_MODE"
TAXONOMY_SHADOW_SAMPLE_RATE_ENV = "TAXONOMY_SHADOW_SAMPLE_RATE"
VALID_TAXONOMY_ROUTING_MODES = ("current", "shadow")
_MAX_QUERY_PREVIEW_CHARS = 120


def taxonomy_routing_mode(env: Optional[Dict[str, str]] = None) -> str:
    """Return the effective taxonomy routing mode, defaulting invalid values to current."""
    source = env if env is not None else os.environ
    value = str(source.get(TAXONOMY_ROUTING_MODE_ENV, "current")).strip().lower()
    if value not in VALID_TAXONOMY_ROUTING_MODES:
        logger.warning("Invalid %s=%r; using current", TAXONOMY_ROUTING_MODE_ENV, value)
        return "current"
    return value


def taxonomy_shadow_sample_rate(env: Optional[Dict[str, str]] = None) -> float:
    """Return bounded shadow comparison sample rate from environment."""
    source = env if env is not None else os.environ
    raw_value = str(source.get(TAXONOMY_SHADOW_SAMPLE_RATE_ENV, "1.0")).strip()
    try:
        return max(0.0, min(1.0, float(raw_value)))
    except ValueError:
        logger.warning("Invalid %s=%r; using 1.0", TAXONOMY_SHADOW_SAMPLE_RATE_ENV, raw_value)
        return 1.0


class TaxonomyRoutingCapability:
    """Adapter boundary around TaxonomySignalIndex with optional async shadow comparison."""

    _SUPPORTED = ["find_skill", "find_skills", "load", "snapshot"]

    def __init__(
        self,
        current_index: Any,
        *,
        shadow_index: Any = None,
        mode: Optional[str] = None,
        shadow_sample_rate: Optional[float] = None,
        shadow_async: bool = True,
        max_drift_events: int = 100,
    ) -> None:
        self._current_index = current_index
        self._shadow_index = shadow_index if shadow_index is not None else current_index
        self._mode = mode
        self._shadow_sample_rate = shadow_sample_rate
        self._shadow_async = shadow_async
        self._drift_events = deque(maxlen=max(1, int(max_drift_events or 1)))
        self._shadow_threads: list[threading.Thread] = []
        self._lock = threading.RLock()

    @property
    def _ready(self) -> Any:
        """Pass through the underlying index readiness event so HTTP/chat readiness checks work."""
        return getattr(self._current_index, "_ready", None)

    def metadata(self) -> Dict[str, Any]:
        return {
            "mode": self._effective_mode(),
            "enable_flag": TAXONOMY_ROUTING_MODE_ENV,
            "valid_modes": list(VALID_TAXONOMY_ROUTING_MODES),
            "shadow_sample_rate_env": TAXONOMY_SHADOW_SAMPLE_RATE_ENV,
            "diagnostics": "bounded_in_memory_drift_log",
            "provider_status": "deferred_quality_parity_required",
            "current_result_authoritative": True,
            "swap_target": False,
            "defer_reason": "routing quality is user-visible; alternate providers must prove parity in shadow mode first",
            "supports": list(self._SUPPORTED),
        }

    def snapshot(self, limit: int = 50) -> List[Dict[str, Any]]:
        normalized_limit = max(0, int(limit or 0))
        if normalized_limit == 0:
            return []
        with self._lock:
            events = list(self._drift_events)[-normalized_limit:]
        return [dict(event) for event in events]

    def wait_for_shadow(self, timeout: float = 1.0) -> None:
        """Testing/support hook: wait for outstanding shadow comparisons."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                threads = [thread for thread in self._shadow_threads if thread.is_alive()]
                self._shadow_threads = threads
            if not threads:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            for thread in threads:
                thread.join(timeout=min(0.05, remaining))

    @property
    def _ready(self):
        """Readiness Event of the wrapped index, or None when there is no index.

        The underlying TaxonomySignalIndex builds on a daemon thread and exposes a
        threading.Event. Callers reasonably probe `getattr(idx, '_ready', None)`;
        without this proxy that returns None on the wrapper and the probe silently
        reads as "never ready", disabling the caller's branch for good. (That is
        exactly how the pre-router taxonomy signal in chat.py was dead.)
        """
        return getattr(self._current_index, "_ready", None)

    def is_ready(self) -> bool:
        """True when the wrapped index has finished loading."""
        ev = self._ready
        return bool(ev is not None and ev.is_set())

    def load(self) -> None:
        if self._current_index is None:
            return
        try:
            self._current_index.load()
        except Exception as exc:
            logger.warning("TaxonomyRoutingCapability.load current failed (non-fatal): %s", exc)
        if self._effective_mode() == "shadow" and self._shadow_index is not None and self._shadow_index is not self._current_index:
            try:
                self._shadow_index.load()
            except Exception as exc:
                logger.warning("TaxonomyRoutingCapability.load shadow failed (non-fatal): %s", exc)

    def find_skill(self, query_embedding: List[float], query_text: str = "") -> Optional[dict]:
        if self._current_index is None or not query_embedding:
            return None
        try:
            current_result = self._current_index.find_skill(query_embedding, query_text=query_text)
        except Exception as exc:
            logger.warning("TaxonomyRoutingCapability.find_skill current failed (non-fatal): %s", exc)
            return None
        self._maybe_shadow("find_skill", query_embedding, query_text, current_result, {})
        return current_result

    def find_skills(
        self,
        query_embedding: List[float],
        query_text: str = "",
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> List[dict]:
        if self._current_index is None or not query_embedding:
            return []
        try:
            current_result = self._current_index.find_skills(
                query_embedding,
                query_text=query_text,
                top_k=top_k,
                min_score=min_score,
            )
            current_result = _sort_hits(current_result)[:top_k]
        except Exception as exc:
            logger.warning("TaxonomyRoutingCapability.find_skills current failed (non-fatal): %s", exc)
            return []
        self._maybe_shadow(
            "find_skills",
            query_embedding,
            query_text,
            current_result,
            {"top_k": top_k, "min_score": min_score},
        )
        return current_result

    def _effective_mode(self) -> str:
        if self._mode is not None:
            value = str(self._mode).strip().lower()
            return value if value in VALID_TAXONOMY_ROUTING_MODES else "current"
        return taxonomy_routing_mode()

    def _effective_sample_rate(self, query_text: str) -> float:
        if self._shadow_sample_rate is not None:
            return max(0.0, min(1.0, float(self._shadow_sample_rate)))
        return taxonomy_shadow_sample_rate()

    def _should_shadow(self, query_text: str) -> bool:
        if self._effective_mode() != "shadow" or self._shadow_index is None:
            return False
        rate = self._effective_sample_rate(query_text)
        if rate <= 0.0:
            return False
        if rate >= 1.0:
            return True
        bucket = int(_query_hash(query_text), 16) % 10_000
        return bucket < int(rate * 10_000)

    def _maybe_shadow(
        self,
        operation: str,
        query_embedding: List[float],
        query_text: str,
        current_result: Any,
        kwargs: Dict[str, Any],
    ) -> None:
        if not self._should_shadow(query_text):
            return
        if self._shadow_async:
            thread = threading.Thread(
                target=self._run_shadow,
                args=(operation, list(query_embedding), query_text, current_result, dict(kwargs)),
                daemon=True,
                name="TaxonomyRoutingShadow",
            )
            with self._lock:
                self._shadow_threads.append(thread)
            thread.start()
            return
        self._run_shadow(operation, query_embedding, query_text, current_result, kwargs)

    def _run_shadow(
        self,
        operation: str,
        query_embedding: List[float],
        query_text: str,
        current_result: Any,
        kwargs: Dict[str, Any],
    ) -> None:
        start = time.time()
        shadow_result = None
        error_type = None
        error_preview = None
        try:
            if operation == "find_skill":
                shadow_result = self._shadow_index.find_skill(query_embedding, query_text=query_text)
            else:
                shadow_result = self._shadow_index.find_skills(
                    query_embedding,
                    query_text=query_text,
                    top_k=kwargs.get("top_k", 5),
                    min_score=kwargs.get("min_score", 0.55),
                )
                shadow_result = _sort_hits(shadow_result)[: kwargs.get("top_k", 5)]
        except Exception as exc:
            error_type = type(exc).__name__
            error_preview = str(exc)[:160]

        current_summary = _result_summary(current_result)
        shadow_summary = _result_summary(shadow_result)
        drift = bool(error_type or current_summary != shadow_summary)
        if not drift:
            return

        event = {
            "operation": operation,
            "query_hash": _query_hash(query_text),
            "query_preview": _query_preview(query_text),
            "current_skill": current_summary.get("skill"),
            "shadow_skill": shadow_summary.get("skill"),
            "current_score": current_summary.get("score"),
            "shadow_score": shadow_summary.get("score"),
            "score_delta": _score_delta(current_summary.get("score"), shadow_summary.get("score")),
            "current_method": current_summary.get("method"),
            "shadow_method": shadow_summary.get("method"),
            "drift": True,
            "latency_ms": int((time.time() - start) * 1000),
            "error_type": error_type,
            "error_preview": error_preview,
        }
        with self._lock:
            self._drift_events.append(event)


def _sort_hits(hits: Any) -> List[dict]:
    if not hits:
        return []
    return sorted(
        [dict(hit) for hit in hits if isinstance(hit, dict)],
        key=lambda hit: (
            -float(hit.get("score") or 0.0),
            str(hit.get("skill") or ""),
            str(hit.get("embed_text") or ""),
            str(hit.get("method") or ""),
        ),
    )


def _result_summary(result: Any) -> Dict[str, Any]:
    if isinstance(result, list):
        hits = _sort_hits(result)
        if not hits:
            return {"skill": None, "score": None, "method": None, "digest": "[]"}
        first = hits[0]
        return {
            "skill": first.get("skill"),
            "score": _safe_float(first.get("score")),
            "method": first.get("method"),
            "digest": [(hit.get("skill"), _safe_float(hit.get("score")), hit.get("embed_text")) for hit in hits],
        }
    if isinstance(result, dict):
        return {
            "skill": result.get("skill"),
            "score": _safe_float(result.get("score")),
            "method": result.get("method"),
            "digest": (result.get("skill"), _safe_float(result.get("score")), result.get("embed_text")),
        }
    return {"skill": None, "score": None, "method": None, "digest": None}


def _safe_float(value: Any) -> Optional[float]:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _score_delta(current_score: Optional[float], shadow_score: Optional[float]) -> Optional[float]:
    if current_score is None or shadow_score is None:
        return None
    return round(current_score - shadow_score, 6)


def _query_hash(query_text: str) -> str:
    return hashlib.sha256((query_text or "").encode("utf-8", errors="ignore")).hexdigest()


def _query_preview(query_text: str) -> str:
    text = re.sub(
        r"(?i)\b(password|token|secret|api[_-]?key)\s*=\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=<redacted>",
        query_text or "",
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_QUERY_PREVIEW_CHARS]


__all__ = [
    "TAXONOMY_ROUTING_MODE_ENV",
    "TAXONOMY_SHADOW_SAMPLE_RATE_ENV",
    "TaxonomyRoutingCapability",
    "taxonomy_routing_mode",
    "taxonomy_shadow_sample_rate",
]
