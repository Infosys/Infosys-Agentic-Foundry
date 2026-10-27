"""Provider-neutral data contracts for React runtime adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentos_contracts import VALID_REACT_RUNTIMES


DEFAULT_PREVIEW_LIMIT = 1000


def bounded_preview(value: Any, *, limit: int = DEFAULT_PREVIEW_LIMIT) -> str:
    """Return a string preview bounded for traces, diagnostics, and tests."""
    text = "" if value is None else str(value)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


@dataclass(frozen=True)
class NativeToolCall:
    """Canonical tool-call shape emitted by a provider-native React turn."""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    type: str = "tool_call"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "args": dict(self.args),
            "type": self.type,
        }


@dataclass(frozen=True)
class NativeUsage:
    """Provider-neutral usage accounting for one native model turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": int(self.input_tokens or 0),
            "output_tokens": int(self.output_tokens or 0),
            "total_tokens": int(self.total_tokens or 0),
        }


@dataclass(frozen=True)
class NativeProviderMetadata:
    """Bounded provider metadata that is safe to attach to traces."""

    provider: str = ""
    model: str = ""
    finish_reason: str = ""
    response_id: str = ""
    cache_metadata: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self, *, preview_limit: int = DEFAULT_PREVIEW_LIMIT) -> dict[str, Any]:
        return {
            "provider": bounded_preview(self.provider, limit=preview_limit),
            "model": bounded_preview(self.model, limit=preview_limit),
            "finish_reason": bounded_preview(self.finish_reason, limit=preview_limit),
            "response_id": bounded_preview(self.response_id, limit=preview_limit),
            "cache_metadata": dict(self.cache_metadata or {}),
        }


@dataclass(frozen=True)
class NativeTurn:
    """One provider-native model turn after response normalization."""

    content: str = ""
    reasoning: str = ""
    reasoning_items: list[dict[str, Any]] = field(default_factory=list)
    response_id: str = ""
    tool_calls: list[NativeToolCall | dict[str, Any]] = field(default_factory=list)
    usage: NativeUsage = field(default_factory=NativeUsage)
    provider_metadata: NativeProviderMetadata = field(default_factory=NativeProviderMetadata)
    raw_response_preview: str = ""

    def normalized_tool_calls(self) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, call in enumerate(self.tool_calls):
            if isinstance(call, NativeToolCall):
                normalized.append(call.to_dict())
                continue
            call_id = str(call.get("id") or f"call_{index}")
            normalized.append({
                "id": call_id,
                "name": str(call.get("name") or ""),
                "args": dict(call.get("args") or {}),
                "type": str(call.get("type") or "tool_call"),
            })
        return normalized

    def to_safe_dict(self, *, preview_limit: int = DEFAULT_PREVIEW_LIMIT) -> dict[str, Any]:
        return {
            "content": self.content,
            "reasoning": bounded_preview(self.reasoning, limit=preview_limit),
            "reasoning_items": [
                {
                    key: bounded_preview(value, limit=preview_limit)
                    if isinstance(value, str) else value
                    for key, value in dict(item).items()
                }
                for item in self.reasoning_items
            ],
            "response_id": bounded_preview(self.response_id, limit=preview_limit),
            "tool_calls": self.normalized_tool_calls(),
            "usage": self.usage.to_safe_dict(),
            "provider_metadata": self.provider_metadata.to_safe_dict(preview_limit=preview_limit),
            "raw_response_preview": bounded_preview(self.raw_response_preview, limit=preview_limit),
        }


@dataclass(frozen=True)
class ToolGovernanceDecision:
    """Decision returned by the shared tool-call firewall."""

    allowed: bool
    status: str
    reason: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    source: str = ""

    @classmethod
    def allow(cls, *, tool_call_id: str, tool_name: str, source: str) -> "ToolGovernanceDecision":
        return cls(True, "allowed", tool_call_id=tool_call_id, tool_name=tool_name, source=source)

    @classmethod
    def pending(
        cls,
        *,
        reason: str,
        tool_call_id: str,
        tool_name: str,
        source: str,
        status: str = "pending",
    ) -> "ToolGovernanceDecision":
        return cls(False, status, reason=reason, tool_call_id=tool_call_id, tool_name=tool_name, source=source)

    @classmethod
    def blocked(
        cls,
        *,
        reason: str,
        tool_call_id: str,
        tool_name: str,
        source: str,
    ) -> "ToolGovernanceDecision":
        return cls(False, "blocked", reason=reason, tool_call_id=tool_call_id, tool_name=tool_name, source=source)
