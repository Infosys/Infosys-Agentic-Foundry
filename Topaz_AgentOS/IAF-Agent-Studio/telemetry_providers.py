"""Telemetry provider fanout for Studio emitters.

SQLite remains the local durable telemetry store inside TraceEmitter and
TwinEmitter. This module adds an adapter boundary for optional external
observability providers without letting provider failures affect runtime.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Protocol


DEFAULT_PREVIEW_LIMIT = 512
SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|passphrase|_pass\b|_pw\b|_pin\b|_auth\b|auth[_-]?key|"
    r"token|secret|api[_-]?key|access[_-]?key|private[_-]?key|signing[_-]?key|"
    r"encryption[_-]?key|authorization|bearer|credential|reasoning|thinking)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_RE = re.compile(
    r'(?i)\b(password|passphrase|token|secret|api[_-]?key|authorization)\s*[:=]\s*([^\s,;&}\]")]+)'
)


class TelemetryProvider(Protocol):
    """Minimal provider contract used by TraceEmitter and TwinEmitter."""

    name: str
    enabled: bool

    def emit(self, event_type: str, payload: Dict[str, Any], *, source: str) -> None:
        """Forward one sanitized telemetry event."""

    def snapshot(self) -> Dict[str, Any]:
        """Return bounded diagnostics safe for capability snapshots."""


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    suffix = "...[TRUNCATED]"
    return value[: max(0, limit - len(suffix))] + suffix


def _is_sensitive_key(key: str) -> bool:
    # Allow-list only known usage-count keys; a broad *_tokens suffix would exempt credential fields.
    if key.lower() in {
        "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens",
        "total_tokens", "token_count",
    }:
        return False
    return bool(SENSITIVE_KEY_RE.search(key))


def redact_and_bound(value: Any, *, preview_limit: int = DEFAULT_PREVIEW_LIMIT) -> Any:
    """Return a sanitized copy of value with sensitive fields redacted."""
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = redact_and_bound(item, preview_limit=preview_limit)
        return sanitized
    if isinstance(value, list):
        return [redact_and_bound(item, preview_limit=preview_limit) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(redact_and_bound(item, preview_limit=preview_limit) for item in value[:100])
    if isinstance(value, str):
        redacted = SENSITIVE_VALUE_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
        return _truncate(redacted, preview_limit)
    return value


def _provider_name(provider: Any, fallback_index: int) -> str:
    return str(getattr(provider, "name", None) or f"provider_{fallback_index}")


def _safe_snapshot(provider: Any, *, preview_limit: int) -> Dict[str, Any]:
    try:
        snapshot = provider.snapshot() if hasattr(provider, "snapshot") else {}
    except Exception as exc:
        snapshot = {"snapshot_error": str(exc)}
    if not isinstance(snapshot, dict):
        snapshot = {"snapshot": str(snapshot)}
    return redact_and_bound(snapshot, preview_limit=preview_limit)


class TelemetryProviderFanout:
    """Bounded, non-fatal fanout across configured telemetry providers."""

    def __init__(self, providers: Optional[Iterable[TelemetryProvider]] = None, *, preview_limit: int = DEFAULT_PREVIEW_LIMIT):
        self._providers: List[TelemetryProvider] = list(providers or [])
        self._preview_limit = preview_limit
        self._stats: Dict[str, Dict[str, Any]] = {}
        for index, provider in enumerate(self._providers):
            name = _provider_name(provider, index)
            self._stats[name] = {
                "name": name,
                "health": "ok",
                "emitted_count": 0,
                "failed_count": 0,
                "dropped_count": 0,
                "last_error_preview": "",
            }

    @classmethod
    def coerce(cls, value: Any, *, preview_limit: int = DEFAULT_PREVIEW_LIMIT) -> "TelemetryProviderFanout":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls([], preview_limit=preview_limit)
        if isinstance(value, (list, tuple)):
            return cls(value, preview_limit=preview_limit)
        return cls([value], preview_limit=preview_limit)

    def emit(self, event_type: str, payload: Dict[str, Any], *, source: str) -> None:
        if not self._providers:
            return
        sanitized = redact_and_bound(dict(payload), preview_limit=self._preview_limit)
        for index, provider in enumerate(self._providers):
            name = _provider_name(provider, index)
            stats = self._stats.setdefault(
                name,
                {
                    "name": name,
                    "health": "ok",
                    "emitted_count": 0,
                    "failed_count": 0,
                    "dropped_count": 0,
                    "last_error_preview": "",
                },
            )
            if getattr(provider, "enabled", True) is False:
                stats["dropped_count"] += 1
                stats["health"] = "disabled"
                continue
            try:
                provider.emit(event_type, dict(sanitized), source=source)
                stats["emitted_count"] += 1
                if stats["health"] != "disabled":
                    stats["health"] = "ok"
            except TypeError:
                try:
                    provider.emit(event_type, dict(sanitized))
                    stats["emitted_count"] += 1
                    stats["health"] = "ok"
                except Exception as exc:
                    self._record_failure(stats, exc)
            except Exception as exc:
                self._record_failure(stats, exc)

    def _record_failure(self, stats: Dict[str, Any], exc: Exception) -> None:
        stats["failed_count"] += 1
        stats["health"] = "degraded"
        stats["last_error_preview"] = redact_and_bound(str(exc), preview_limit=self._preview_limit)

    def snapshot(self) -> Dict[str, Any]:
        providers = []
        for index, provider in enumerate(self._providers):
            name = _provider_name(provider, index)
            base = dict(self._stats.get(name, {"name": name}))
            provider_snapshot = _safe_snapshot(provider, preview_limit=self._preview_limit)
            provider_snapshot.update(base)
            provider_snapshot.setdefault("name", name)
            provider_snapshot.setdefault("health", "ok")
            provider_snapshot.setdefault("emitted_count", 0)
            provider_snapshot.setdefault("failed_count", 0)
            provider_snapshot.setdefault("dropped_count", 0)
            provider_snapshot.setdefault("last_error_preview", "")
            providers.append(redact_and_bound(provider_snapshot, preview_limit=self._preview_limit))
        return {
            "mode": "fanout" if providers else "local_sqlite_only",
            "provider_count": len(providers),
            "preview_limit": self._preview_limit,
            "providers": providers,
        }


def build_telemetry_provider_fanout(
    *,
    exporters: str = "local",
    preview_limit: int = DEFAULT_PREVIEW_LIMIT,
    capture_content: Optional[bool] = None,
    **_legacy: Any,
) -> TelemetryProviderFanout:
    """Build the configured provider fanout from normalized config values.

    `otel` (aliases: `otlp`, `otlp_json`) mirrors traces to OpenTelemetry via the official
    SDK — see telemetry/otel_setup.py, which must have been configured first. The former
    OtlpJsonTelemetryProvider posted a custom JSON body that no OTLP collector accepts,
    one blocking HTTP call per span; it has been removed. Legacy keyword arguments
    (otlp_endpoint, service_name, timeout_seconds) are accepted and ignored here — they
    are mapped onto the standard OTEL_* variables by otel_setup.configure_otel().
    """
    providers: List[TelemetryProvider] = []
    from telemetry.otel_setup import _STATE as _otel_state, otel_selected

    # Requires otel_setup.configure_otel() to have run first (shared/state.py does).
    if otel_selected(exporters) and _otel_state.get("configured"):
        from telemetry.otel_trace_bridge import OtelTraceProvider

        providers.append(OtelTraceProvider(capture_content=capture_content))
    return TelemetryProviderFanout(providers, preview_limit=preview_limit)
