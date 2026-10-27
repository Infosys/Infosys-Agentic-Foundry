"""Example SkillProvider backed by an in-memory registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from iaf_agent_skills.loader import Skill


class MemorySkillProvider:
    """Tiny starter provider for partner skill registries."""

    def __init__(self, skills_path: str, registry: dict[str, Skill] | None = None):
        self.skills_path = Path(skills_path)
        self.registry = registry or {}
        self.personal_path: Optional[Path] = None

    def set_personal_path(self, personal_path: Any) -> None:
        self.personal_path = Path(personal_path) if personal_path else None

    def load(self, skill_name: str) -> Skill:
        if skill_name not in self.registry:
            raise FileNotFoundError(f"Skill not found in partner registry: {skill_name}")
        return self.registry[skill_name]

    def get_file_content(self, skill: Skill, file_key: str) -> Optional[str]:
        return None

    def get_prompt(self, skill: Skill, include_files: bool = True) -> str:
        return skill.body

    def list_skill_files(self, skill: Skill) -> list[dict[str, str]]:
        return []

    def health(self) -> dict[str, Any]:
        return {
            "provider": "memory_skill_provider",
            "skill_count": len(self.registry),
            "status": "ok",
        }

    def snapshot(self) -> dict[str, Any]:
        return self.health()
