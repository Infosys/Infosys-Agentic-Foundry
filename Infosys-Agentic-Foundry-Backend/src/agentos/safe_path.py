# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
SafePath — Secure path resolver for AgentOS skill agents.

Inspired by AgentPro's safe_path.py — prevents sandbox escapes and
enforces read-only zones.

All file operations are confined within the agent's root directory.
Attempts to escape via '..' or absolute paths are blocked.
"""

import logging
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a path security violation is detected."""
    pass


class SafePath:
    """
    Secure path resolver that prevents sandbox escapes.

    Usage:
        sp = SafePath(agent_dir, readonly_paths=[agent_dir / "enterprise_context"])
        resolved = sp.resolve("skills/hr_policy/SKILL.md")
        if sp.is_writable(resolved):
            resolved.write_text("...")
    """

    def __init__(self, sandbox_root: Path, readonly_paths: Optional[List[Path]] = None):
        self.sandbox_root = Path(sandbox_root).resolve()
        self.readonly_paths = [Path(p).resolve() for p in (readonly_paths or [])]
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str) -> Path:
        """
        Resolve a relative path to an absolute path within the sandbox.

        Raises SecurityError if the path attempts to escape.
        """
        path = str(path).strip()

        if not path or path == ".":
            return self.sandbox_root

        # Block '..' traversal
        if ".." in path:
            log.warning(f"[SafePath] Blocked path traversal attempt: {path}")
            raise SecurityError(
                "Error [PATH_ESCAPE]: Access denied. "
                "Cannot navigate outside agent workspace using '..'."
            )

        # Strip leading / to treat as relative
        if path.startswith("/"):
            path = path.lstrip("/")

        full_path = (self.sandbox_root / path).resolve()

        # Verify it's actually inside sandbox
        try:
            full_path.relative_to(self.sandbox_root)
        except ValueError:
            log.warning(f"[SafePath] Blocked escape: '{path}' → {full_path}")
            raise SecurityError(
                f"Error [PATH_ESCAPE]: Access denied. "
                f"Path '{path}' resolves outside agent workspace."
            )

        return full_path

    def is_writable(self, resolved_path: Path) -> bool:
        """Check if a resolved path is writable (not in a read-only zone)."""
        resolved = resolved_path.resolve()
        for ro_path in self.readonly_paths:
            try:
                resolved.relative_to(ro_path)
                return False
            except ValueError:
                continue
        return True

    def to_virtual(self, resolved_path: Path) -> str:
        """Convert an absolute resolved path back to a virtual path."""
        try:
            relative = resolved_path.relative_to(self.sandbox_root)
            return str(relative).replace("\\", "/")
        except ValueError:
            return str(resolved_path)
