"""Harness execution profiles — dependency-free resolution + built-in presets.

A *profile* is a named preset that fills the behavioural harness knobs (execution engine,
verification depth, model tier, autonomy, budget, learning, durability) so a use-case author
selects one name instead of hand-setting a dozen knobs. This module is the stable contract
(mirrors ``react_runtime.py``): a frozen ``ProfileSelection`` + a ``resolve_profile`` precedence
resolver + the built-in preset vectors + a one-way safety ratchet.

Design (AGENTS.md):
- Profiles are **default vectors over orthogonal dimensions**, not a flat enum — every dimension is
  independently overridable, so combinations like ``deep-research + long-running`` are expressible.
- Precedence (request wins): ``builtin < config < skill < request`` for normal dims; **safety** dims
  use a one-way ratchet — an override may only *tighten*, never loosen, a locked floor.
- Reversible: the default profile is ``standard`` whose vector is empty, i.e. it changes nothing —
  a skill with no ``profile:`` and no tenant file behaves byte-identically to today.
- Tenant config (``harness_profiles.yaml``) overrides/extends the built-ins; this module is the
  code-level fallback so the system works with no file.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


DEFAULT_PROFILE = "standard"

# Sparse overrides; ``standard`` is intentionally empty (the parity anchor).
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "standard": {},

    "fast-lookup": {
        "engine": "react",
        "memory": {"light_mode": True},
        "verification": {"enabled": False, "critique_mode": "off", "consistency": False},
        "model_tier": "light",
        "reasoning_effort": "low",
        "knowledge_retrieval": "scan",
        "learning": {"world_model_learn": False, "rl_capture": False},
    },

    "high-assurance": {
        "verification": {
            "enabled": True, "threshold": 0.85, "max_iter": 3,
            "critique_mode": "sync", "consistency": True, "verifier_model": "primary",
        },
        "model_tier": "primary",
        "reasoning_effort": "high",
        "autonomy": {"auto_run": False, "locked": True},  # locked → ratchet floor
        "learning": {"world_model_learn": False},
    },

    "autonomous": {
        "engine": "orchestrator",
        "verification": {"enabled": True, "auto_complexity": True},
        "autonomy": {"auto_run": True, "gated": True},   # gated → requires entitlements + hitl patterns
        "budget": {"deadline_seconds": 1800},
    },

    "deep-research": {
        "engine": "orchestrator",
        "verification": {"enabled": True, "auto_complexity": True},
        "model_tier": "primary",
        "reasoning_effort": "high",
        "budget": {"max_tool_calls": 40, "deadline_seconds": 3600},
        "knowledge_retrieval": "hybrid",
        "learning": {"world_model_learn": True},
        "duration": "long-running",
    },
}

# ``locked: True`` pins a safety knob (autonomy.auto_run=False); no later layer may loosen it.


@dataclass(frozen=True)
class ProfileSelection:
    """Resolved profile name + the merged dimension vector + provenance."""

    name: str
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    source: str = "default"        # which layer chose the NAME: request|skill|config|default
    fallback_reason: str = ""

    def dim(self, *path: str, default: Any = None) -> Any:
        """Read a nested dimension, e.g. ``sel.dim('verification', 'threshold')``."""
        cur: Any = self.dimensions
        for key in path:
            if not isinstance(cur, Mapping) or key not in cur:
                return default
            cur = cur[key]
        return cur


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` (override wins). Returns a new dict."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def available_profiles(registry: Optional[Mapping[str, Any]] = None) -> dict[str, dict[str, Any]]:
    """Return builtin presets overlaid with a tenant registry (``harness_profiles.yaml`` ``profiles``).

    Tenant entries may ``extends:`` another profile to inherit its vector and specify only deltas.
    """
    merged: dict[str, dict[str, Any]] = {k: copy.deepcopy(v) for k, v in BUILTIN_PROFILES.items()}
    reg = _as_mapping(registry)
    profiles_cfg = _as_mapping(reg.get("profiles"))
    # two passes so ``extends`` can reference a builtin or an earlier tenant profile
    for name, spec in profiles_cfg.items():
        spec_map = _as_mapping(spec)
        base_name = str(spec_map.get("extends") or "")
        base = merged.get(base_name, {}) if base_name else merged.get(name, {})
        vec = {k: v for k, v in spec_map.items() if k != "extends"}
        merged[name] = _deep_merge(base, vec)
    return merged


def _apply_ratchet(vec: Mapping[str, Any]) -> dict[str, Any]:
    """One-way safety ratchet: a ``locked`` safety floor pins its knob to the safe value.

    Today: ``autonomy.locked=True`` forces ``autonomy.auto_run=False`` — a derived/tenant profile
    that tried to flip it True is clamped back (and marked ``_ratchet_clamped``).
    """
    out = copy.deepcopy(dict(vec))
    autonomy = out.get("autonomy")
    if isinstance(autonomy, dict) and autonomy.get("locked"):
        if autonomy.get("auto_run") is True:
            autonomy["_ratchet_clamped"] = True
        autonomy["auto_run"] = False
    return out


def resolve_profile(
    *,
    skill: Any = None,
    config: Optional[Mapping[str, Any]] = None,
    env: Optional[Mapping[str, str]] = None,
    routing_info: Optional[Mapping[str, Any]] = None,
    registry: Optional[Mapping[str, Any]] = None,
) -> ProfileSelection:
    """Resolve the active profile NAME by precedence, then return its merged dimension vector.

    Name precedence (first non-empty wins, request highest):
        routing_info['profile']  >  skill.profile  >  config['profile'/'default_profile']  >
        env['HARNESS_PROFILE']  >  registry.default_profile  >  ``standard``
    Unknown name → warn-reason + fall back to ``standard`` (never raises).
    The returned ``dimensions`` are the resolved profile's vector with the safety ratchet applied.
    """
    config_map = _as_mapping(config or {})
    routing_map = _as_mapping(routing_info or {})
    env_map: Mapping[str, str] = env if env is not None else {}
    profiles = available_profiles(registry)

    reg_default = str(_as_mapping(registry).get("default_profile") or "") or DEFAULT_PROFILE
    candidates = (
        (routing_map.get("profile"), "request"),
        (getattr(skill, "profile", "") if skill is not None else "", "skill"),
        (config_map.get("profile") or config_map.get("default_profile"), "config"),
        (env_map.get("HARNESS_PROFILE", ""), "env"),
        (reg_default, "default"),
    )

    for value, source in candidates:
        name = str(value or "").strip()
        if not name:
            continue
        if name in profiles:
            vec = _apply_ratchet(profiles[name])
            return ProfileSelection(name=name, dimensions=vec, source=source)
        # named but unknown → fall back to standard, carry a reason
        return ProfileSelection(
            name=DEFAULT_PROFILE,
            dimensions=dict(profiles.get(DEFAULT_PROFILE, {})),
            source=source,
            fallback_reason=f"Unknown profile '{name}', falling back to '{DEFAULT_PROFILE}'",
        )

    return ProfileSelection(name=DEFAULT_PROFILE, dimensions=dict(profiles.get(DEFAULT_PROFILE, {})), source="default")
