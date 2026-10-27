"""Default SkillProvider backed by the existing SkillLoader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from iaf_agent_skills.loader import Skill, SkillLoader


class FileSystemSkillProvider:
    """Compatibility wrapper around ``SkillLoader``."""

    name = "filesystem"

    def __init__(self, skills_path: str):
        self._loader = SkillLoader(skills_path)

    @property
    def skills_path(self) -> Path:
        return self._loader.skills_path

    def set_personal_path(self, personal_path: Any) -> None:
        self._loader.set_personal_path(personal_path)

    def load(self, skill_name: str) -> Skill:
        return self._loader.load(skill_name)

    def get_file_content(self, skill: Skill, file_key: str) -> Optional[str]:
        return self._loader.get_file_content(skill, file_key)

    def get_prompt(self, skill: Skill, include_files: bool = True) -> str:
        return self._loader.get_prompt(skill, include_files=include_files)

    def list_skill_files(self, skill: Skill) -> list[dict[str, str]]:
        return self._loader.list_skill_files(skill)

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "skills_path": str(self.skills_path), "status": "ok"}

    def snapshot(self) -> dict[str, Any]:
        return self.health()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)
