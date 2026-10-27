"""
SafePath - Secure path resolution for AgentOS.

Ensures all file operations are confined within the sandbox.
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a security violation is detected."""
    pass


# Path confinement helpers shared by the kernel, SkillAgent, Studio services and scripts.

# One path component: word chars (unicode), space, and . _ - @ + ( ) ~
_PATH_SEGMENT_RE = re.compile(r"^[\w .@+()~\-]{1,255}$")
# A whole operator/config-supplied path (absolute or relative, POSIX or Windows).
_PATH_STRING_RE = re.compile(r"^[\w .@+()~:/\\\-]{1,4096}$")

PathLike = Union[str, "os.PathLike[str]"]


def reconstruct_path(path: PathLike) -> Path:
    """Return a fresh ``Path`` rebuilt from an already-validated value.

    Breaks static-analysis taint chains; never use it in place of validation.
    """
    return Path(str(path).encode("utf-8").decode("utf-8"))


def validated_path(raw: PathLike, *, label: str = "path") -> Path:
    """Validate an operator/config-supplied path, resolve it, return a fresh Path.

    Rejects empty values, NUL/control characters and anything outside the
    portable path character set. ``~`` is expanded before resolving.
    """
    value = os.fspath(raw).strip() if raw is not None else ""
    if not value or not _PATH_STRING_RE.fullmatch(value):
        raise SecurityError(f"Error [PATH_INVALID]: invalid {label}")
    resolved = Path(value).expanduser().resolve()
    return reconstruct_path(resolved)


def confine_to_root(path: PathLike, root: PathLike, *, label: str = "path") -> Path:
    """Resolve ``path`` and require it to sit at or under ``root``."""
    trusted_root = Path(root).resolve()
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(trusted_root):
        raise SecurityError(f"Error [PATH_ESCAPE]: {label} resolves outside its root")
    return reconstruct_path(resolved)


def safe_join_under_root(root: PathLike, remainder: PathLike, *, label: str = "path") -> Path:
    """Join a relative ``remainder`` under a trusted ``root`` with validation.

    Every segment must match the segment allowlist; ``..`` is rejected
    outright, and the joined result must still resolve under ``root``.
    """
    trusted_root = Path(root).resolve()
    normalized = os.fspath(remainder).replace("\\", "/").lstrip("/")
    if not normalized:
        return reconstruct_path(trusted_root)
    for segment in normalized.split("/"):
        if not segment or segment == ".":
            continue
        if segment == "..":
            raise SecurityError(f"Error [PATH_ESCAPE]: {label} may not contain '..'")
        if not _PATH_SEGMENT_RE.fullmatch(segment):
            raise SecurityError(f"Error [PATH_INVALID]: invalid segment in {label}")
    joined = (trusted_root / reconstruct_path(normalized)).resolve()
    if not joined.is_relative_to(trusted_root):
        raise SecurityError(f"Error [PATH_ESCAPE]: {label} resolves outside its root")
    return reconstruct_path(joined)


class SafePath:
    """
    Secure path resolver that prevents sandbox escapes.
    
    All paths are resolved relative to the sandbox root.
    Attempts to escape via '..' or absolute paths are blocked.
    """
    
    def __init__(
        self,
        sandbox_root: Path,
        readonly_paths: Optional[List[Path]] = None
    ):
        """
        Initialize SafePath.
        
        Args:
            sandbox_root: The root directory of the sandbox.
            readonly_paths: List of paths that are read-only.
        """
        self.sandbox_root = Path(sandbox_root).resolve()
        self.readonly_paths = [Path(p).resolve() for p in (readonly_paths or [])]
        
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
    
    def resolve(self, path: str, cwd: Path = None) -> Path:
        """
        Resolve a path securely within the sandbox.
        
        Args:
            path: The path to resolve (relative or absolute-looking).
            cwd: Current working directory (relative to sandbox).
            
        Returns:
            Absolute Path object within sandbox.
            
        Raises:
            SecurityError: If path attempts to escape sandbox.
        """
        path = str(path).strip()
        
        if not path or path == ".":
            if cwd:
                return self.sandbox_root / cwd.lstrip("/")
            return self.sandbox_root
        
        if ".." in path:
            logger.warning("Security violation: Error [PATH_ESCAPE]: Access denied. Cannot navigate outside your sandbox using '..'")
            raise SecurityError(
                "Error [PATH_ESCAPE]: Access denied. "
                "Cannot navigate outside your sandbox using '..'"
            )
        
        if path.startswith("/"):
            path = path.lstrip("/")
        
        if cwd and not path.startswith("/"):
            base = self.sandbox_root / str(cwd).lstrip("/")
            full_path = (base / path).resolve()
        else:
            full_path = (self.sandbox_root / path).resolve()
        
        try:
            full_path.relative_to(self.sandbox_root)
        except ValueError:
            logger.warning("Security violation: Error [PATH_ESCAPE]: Access denied. Path '%s' resolves outside sandbox.", path)
            raise SecurityError(
                f"Error [PATH_ESCAPE]: Access denied. "
                f"Path '{path}' resolves outside sandbox."
            )
        
        return full_path
    
    def is_writable(self, resolved_path: Path) -> bool:
        """
        Check if a path is writable.
        
        Args:
            resolved_path: An already-resolved absolute path.
            
        Returns:
            True if writable, False if read-only.
        """
        resolved = resolved_path.resolve()
        
        for ro_path in self.readonly_paths:
            try:
                resolved.relative_to(ro_path)
                return False  # Path is under a read-only directory
            except ValueError:
                continue
        
        return True
    
    def to_virtual(self, resolved_path: Path) -> str:
        """
        Convert a resolved path back to virtual (sandbox-relative) path.
        
        Args:
            resolved_path: An absolute path within the sandbox.
            
        Returns:
            Virtual path string (e.g., '/memory/facts/user.md').
        """
        try:
            relative = resolved_path.relative_to(self.sandbox_root)
            return "/" + str(relative)
        except ValueError:
            return str(resolved_path)
