"""Validation and filename helpers for skill folder names."""

from __future__ import annotations

import re

# Safe single path segment: letters, digits, underscore, hyphen, space.
# No slashes or ".." — joined directly under the skills root.
SKILL_FOLDER_NAME_RE = re.compile(r"^[a-zA-Z0-9_\- ]{1,80}$")


def is_valid_skill_folder_name(name: str) -> bool:
    n = (name or "").strip()
    return bool(n and SKILL_FOLDER_NAME_RE.match(n))


def safe_pack_download_name(skill_names: list[str]) -> str:
    """Build a filesystem-safe .skillpack.zip download filename."""
    if len(skill_names) == 1:
        raw = (skill_names[0] or "").strip()
        safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", raw).strip("_") or "skill"
        return f"{safe}.skillpack.zip"
    return f"skills-{len(skill_names)}.skillpack.zip"
