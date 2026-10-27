"""Default RouterProvider backed by the existing SkillRouter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from iaf_agent_skills.router import SkillRouter


class DefaultRouterProvider:
    """Compatibility wrapper around ``SkillRouter``."""

    name = "default_router"

    def __init__(self, skills_path: str):
        self._router = SkillRouter(skills_path)

    @property
    def skills_path(self) -> Path:
        return self._router.skills_path

    @property
    def index_path(self) -> Path:
        return self._router.index_path

    @property
    def index(self) -> dict[str, Any]:
        return self._router.index

    @property
    def default_skill(self) -> str:
        return self._router.default_skill

    @property
    def llm(self) -> Any:
        return self._router.llm

    @llm.setter
    def llm(self, value: Any) -> None:
        self._router.llm = value

    def reload(self) -> None:
        self._router.reload()

    def set_personal_path(self, personal_path: Any) -> None:
        self._router.set_personal_path(personal_path)

    def set_skill_filter(self, allowed: list | None = None, denied: list | None = None) -> None:
        self._router.set_skill_filter(allowed=allowed, denied=denied)

    def _get_filtered_skills(self) -> dict[str, Any]:
        return self._router._get_filtered_skills()

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
    ) -> str | dict:
        return self._router.match(
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

    def list_skills(self) -> list[dict[str, Any]]:
        return self._router.list_skills()

    def get_skill_info(self, skill_name: str) -> Optional[dict[str, Any]]:
        return self._router.get_skill_info(skill_name)

    def skill_exists(self, skill_name: str) -> bool:
        return self._router.skill_exists(skill_name)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "skills_path": str(self.skills_path),
            "skill_count": len((self.index or {}).get("skills", {}) or {}),
            "status": "ok",
        }

    def snapshot(self) -> dict[str, Any]:
        return self.health()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._router, name)
