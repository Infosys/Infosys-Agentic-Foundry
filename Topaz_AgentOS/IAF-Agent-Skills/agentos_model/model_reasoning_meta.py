"""Provider-neutral reasoning capability metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


ReasoningDial = Literal["none", "effort", "budget", "adaptive"]
ReasoningWireFormat = Literal["none", "responses", "thinking", "content_tag"]

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ReasoningCapability:
    """Reasoning capability contract shared by model providers."""

    provider: str
    model: str
    supports_reasoning: bool = False
    dial: ReasoningDial = "none"
    wire_format: ReasoningWireFormat = "none"
    replayable: bool = False
    default_effort: str = "medium"
    notes: str = ""

    def to_safe_dict(self) -> dict[str, object]:
        """Return metadata safe for logs/traces; no reasoning content included."""

        return {
            "provider": self.provider,
            "model": self.model,
            "supports_reasoning": self.supports_reasoning,
            "dial": self.dial,
            "wire_format": self.wire_format,
            "replayable": self.replayable,
            "default_effort": self.default_effort,
            "notes": self.notes,
        }


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def is_truthy_env(name: str, *, default: str = "false") -> bool:
    """Return True for common truthy env var spellings."""

    return _norm(os.getenv(name, default)) in TRUTHY_ENV_VALUES


def provider_env_prefix(provider: str) -> str:
    """Map provider identifiers to config/env prefixes."""

    provider_key = _norm(provider)
    if provider_key in {"azure", "azure_openai", "openai_azure"}:
        return "AZURE"
    if provider_key in {"vertex", "gemini", "google_vertex"}:
        return "VERTEX"
    if provider_key in {"anthropic", "claude"}:
        return "ANTHROPIC"
    if provider_key in {"openai", "openai_compat"}:
        return "OPENAI"
    return provider_key.upper()


def reasoning_replay_enabled(provider: str) -> bool:
    """Provider-scoped replay flag, default off."""

    prefix = provider_env_prefix(provider)
    if not is_truthy_env(f"{prefix}_REASONING_REPLAY"):
        return False
    if prefix == "AZURE" and not is_truthy_env("AZURE_REASONING_ENABLED"):
        return False
    return True


def reasoning_expose_enabled(provider: str) -> bool:
    """Provider-scoped debug exposure flag, default off."""

    prefix = provider_env_prefix(provider)
    return is_truthy_env(f"{prefix}_REASONING_EXPOSE")


def get_reasoning_capability(provider: str, model: str) -> ReasoningCapability:
    """Return conservative reasoning metadata for a provider/model pair."""

    provider_key = _norm(provider)
    model_key = _norm(model)

    if provider_key in {"azure", "azure_openai", "openai_azure"}:
        if any(token in model_key for token in ("gpt-5", "o1", "o3", "o4")):
            return ReasoningCapability(
                provider="azure",
                model=model,
                supports_reasoning=True,
                dial="effort",
                wire_format="responses",
                replayable=True,
                default_effort="medium",
                notes="Azure/OpenAI reasoning models need Responses API for replay.",
            )
        return ReasoningCapability(provider="azure", model=model)

    if provider_key in {"vertex", "gemini", "google_vertex"}:
        if "gemini" in model_key:
            return ReasoningCapability(
                provider="vertex",
                model=model,
                supports_reasoning=True,
                dial="budget",
                wire_format="thinking",
                replayable=True,
                default_effort="medium",
                notes="Gemini reasoning uses thinkingConfig/thought parts; replay is bounded text context.",
            )
        return ReasoningCapability(provider="vertex", model=model)

    if provider_key in {"anthropic", "claude"}:
        if "claude" in model_key:
            dial: ReasoningDial = "adaptive" if any(
                v in model_key for v in ("4.6", "4.7", "4.8", "4-6", "4-7", "4-8", "sonnet-5", "fable-5", "mythos-5")
            ) else "budget"
            return ReasoningCapability(
                provider="anthropic",
                model=model,
                supports_reasoning=True,
                dial=dial,
                wire_format="thinking",
                replayable=True,
                default_effort="medium",
                notes="Claude thinking blocks require provider-specific replay safety.",
            )
        return ReasoningCapability(provider="anthropic", model=model)

    if provider_key in {"openai", "openai_compat"}:
        if any(token in model_key for token in ("deepseek", "qwen", "kimi", "reasoning")):
            return ReasoningCapability(
                provider="openai_compat",
                model=model,
                supports_reasoning=True,
                dial="none",
                wire_format="content_tag",
                replayable=False,
                notes="OpenAI-compatible local reasoning commonly appears as text tags or reasoning_content.",
            )
        return ReasoningCapability(provider="openai_compat", model=model)

    return ReasoningCapability(provider=provider_key or "unknown", model=model)
