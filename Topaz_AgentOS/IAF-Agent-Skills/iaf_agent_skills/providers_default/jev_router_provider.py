"""
JevRouterProvider — optional TypeSafe (Jev) semantic skill router.

Wraps the existing router (DefaultRouterProvider / SkillRouter) and, for a fresh
high-confidence query, chooses the skill with a single TypeSafe `Choice` call
instead of the LLM. Everything ambiguous falls back to the wrapped LLM router,
which keeps the full-fidelity behavior (entity extraction, search_variants,
multi-domain detection, confirmation/continuation handling).

Opt-in per agent via config.yaml:

    router:
      provider: jev
      fallback: llm
      confidence_threshold: 0.90      # below this -> delegate to the LLM router
      api_key_env: TYPESAFE_API_KEY   # env var holding the key (never hardcode)
      model: jev-latest               # optional

Design rules (from live back-pressure tests on this repo):
  - Jev is reliable on ATOMIC, well-scoped skill sets (finance_agents ~90%,
    a single narrow domain ~100%) and unreliable on overlapping generalist catalogs — so
    this is opt-in per agent, defaulting OFF.
  - Jev can only PICK a skill; it cannot generate entity_name / search_variants /
    multi-domain plans. So the fast path is taken ONLY for a fresh, single,
    high-confidence task query; every other case delegates to the LLM router.
  - Any Jev error, missing key, or missing SDK => transparent delegation. The
    router must never break because of this wrapper.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class JevRouterProvider:
    """Delegating wrapper that adds a Jev fast-path in front of an LLM router."""

    name = "jev_router"

    def __init__(self, inner: Any, config: dict | None = None):
        cfg = config or {}
        self._inner = inner
        self._threshold = float(cfg.get("confidence_threshold", 0.90))
        self._model = cfg.get("model", "jev-latest")
        self._api_key_env = cfg.get("api_key_env", "TYPESAFE_API_KEY")
        self._fallback = str(cfg.get("fallback", "llm")).lower()
        self._client = None
        self._disabled = False
        self._init_client()

    def _init_client(self) -> None:
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            logger.warning("JevRouterProvider: %s not set — Jev disabled, using LLM router.", self._api_key_env)
            self._disabled = True
            return
        try:
            from typesafe_sdk import TypeSafeClient
            self._client = TypeSafeClient(api_key=api_key)
            logger.info("JevRouterProvider active (model=%s, threshold=%.2f).", self._model, self._threshold)
        except Exception as e:  # SDK missing or client build failed
            logger.warning("JevRouterProvider: TypeSafe SDK unavailable (%s) — using LLM router.", e)
            self._disabled = True

    @property
    def llm(self) -> Any:
        return self._inner.llm

    @llm.setter
    def llm(self, value: Any) -> None:
        self._inner.llm = value

    def __getattr__(self, item: str) -> Any:
        # __getattr__ only fires for attributes missing on this wrapper.
        return getattr(self._inner, item)

    def match(
        self,
        query: str,
        current_skill: str | None = None,
        last_response: str | None = None,
        return_details: bool = False,
        pending_action: dict | None = None,
        entity_hint: str | None = None,
        entity_confidence: float = 0.0,
        process_hint: str | None = None,
        process_matches: list | None = None,
        signals_agree: bool | None = None,
        taxonomy_hints: list | None = None,
    ):
        """Jev fast-path for fresh high-confidence queries; delegate otherwise."""

        def _delegate():
            return self._inner.match(
                query,
                current_skill=current_skill,
                last_response=last_response,
                return_details=return_details,
                pending_action=pending_action,
                entity_hint=entity_hint,
                entity_confidence=entity_confidence,
                process_hint=process_hint,
                process_matches=process_matches,
                signals_agree=signals_agree,
                taxonomy_hints=taxonomy_hints,
            )

        if self._disabled or pending_action:
            return _delegate()
        if current_skill and len(query.split()) <= 5:
            return _delegate()

        skills = self._inner._get_filtered_skills()
        if not skills or len(skills) < 2:
            return _delegate()

        options = {
            name: ((meta.get("description", "") if isinstance(meta, dict) else "") or "")[:200]
            for name, meta in skills.items()
        }

        try:
            from typesafe_sdk import Choice
            ans = self._client.system_one(
                state=query,
                questions={"skill": Choice(
                    instructions="Which skill should handle this user query",
                    criteria=options,
                )},
            ).answers["skill"]
        except Exception as e:
            logger.warning("JevRouterProvider: Jev call failed (%s) — delegating to LLM router.", e)
            return _delegate()

        chosen = ans.choice
        confidence = float(getattr(ans, "confidence", 0.0) or 0.0)

        # Low confidence or invalid pick -> let the LLM router (with all its extra
        # signals) make the call. This is where the accuracy safety net lives.
        if confidence < self._threshold or chosen not in skills:
            logger.info("Jev low-confidence (%.2f < %.2f) or invalid pick '%s' -> LLM fallback.",
                        confidence, self._threshold, chosen)
            return _delegate()

        logger.info("Jev routed '%s' (confidence=%.2f).", chosen, confidence)
        if not return_details:
            return chosen

        alternatives = [{"skill": s, "score": 0.0} for s in skills if s != chosen][:3]
        return {
            "skill": chosen,
            "method": "jev",
            "confidence": confidence,
            "is_continuation": False,
            "is_confirmation": False,
            "entity_hint": entity_hint,
            "entity_confidence": entity_confidence,
            "process_hint": process_hint,
            "signals_agree": signals_agree,
            "alternatives": alternatives,
            "detected_domains": [chosen],
            "execution_mode": "react",
            "complexity_class": "simple",
            "mode_hint": "react",
            "search_variants": [],
            "entity_name": None,
            "entity_type": None,
            "_router_jev": {
                "model": self._model,
                "confidence": confidence,
                "probabilities": getattr(ans, "probabilities", {}) or {},
            },
        }

    def health(self) -> dict[str, Any]:
        inner_health = self._inner.health() if hasattr(self._inner, "health") else {}
        return {
            "provider": self.name,
            "jev_enabled": not self._disabled,
            "threshold": self._threshold,
            "inner": inner_health,
        }
