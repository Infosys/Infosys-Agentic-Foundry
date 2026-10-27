"""SEC-14: refuse to publish editor/backup artefacts from the static mount."""

from __future__ import annotations

BACKUP_MARKERS: tuple[str, ...] = (
    ".bak",
    ".orig",
    ".old",
    ".save",
    ".swp",
    ".swo",
    ".tmp",
    ".rej",
)


def is_backup_artifact(path: str) -> bool:
    """True when any segment of *path* looks like a backup/editor leftover."""
    for segment in path.replace("\\", "/").split("/"):
        lowered = segment.lower()
        if lowered.endswith("~"):
            return True
        if any(marker in lowered for marker in BACKUP_MARKERS):
            return True
    return False
