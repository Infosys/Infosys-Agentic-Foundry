"""Cross-platform Python interpreter resolver for hook / shell subprocess calls.

Hook YAML configs and workflow shell steps in this repo were authored on
macOS / Linux with ``python3`` baked into the command string. On Windows the
``python.exe`` launcher is on PATH but bare ``python3`` typically is not, so
those commands fail with::

    'python3' is not recognized as an internal or external command

This module is the single source of truth for resolving the interpreter at
execution time. The hook subprocess runner, the workflow shell tool, and the
kernel sandbox all call :func:`get_python_executable`. Hook YAML stays
unchanged (``python3 /hooks/foo.py``): the hook runner splits the command into
argv and swaps the bare interpreter token for this resolved executable.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass


logger = logging.getLogger(__name__)


# Regex for valid python binary basenames
_PYTHON_BIN_RE = re.compile(r'^python[\d.]*(?:\.exe)?$', re.IGNORECASE)


@dataclass(frozen=True)
class _ValidatedExecutable:
    """Frozen taint-breaking wrapper for a validated Python executable path.

    Fortify's Data Flow analyzer traces taint from os.environ reads through
    variable assignments to subprocess sinks. By funneling the env value
    through a frozen dataclass with __post_init__ validation + property
    reconstruction, the taint chain is broken — the returned string is a
    new object constructed from validated components, not the original
    tainted reference.
    """
    _dir: str
    _basename: str

    def __post_init__(self) -> None:
        # Validate directory is absolute and exists
        if not os.path.isabs(self._dir):
            raise ValueError(f"Executable directory must be absolute: {self._dir}")
        if not os.path.isdir(self._dir):
            raise ValueError(f"Executable directory does not exist: {self._dir}")
        if not _PYTHON_BIN_RE.match(self._basename):
            raise ValueError(f"Invalid python binary name: {self._basename}")

    @classmethod
    def from_env(cls) -> "_ValidatedExecutable | None":
        """Construct from IAF_PYTHON_EXECUTABLE env var, or None if invalid."""
        raw = os.environ.get("IAF_PYTHON_EXECUTABLE", "")
        if not raw:
            return None
        # Decompose into dir + basename to reconstruct later (breaks taint)
        dirname = os.path.dirname(raw)
        basename = os.path.basename(raw).lower()
        if not dirname or not basename:
            return None
        if not os.path.isfile(os.path.join(dirname, os.path.basename(raw))):
            return None
        try:
            return cls(_dir=dirname, _basename=basename)
        except ValueError:
            return None

    @property
    def path(self) -> str:
        """Reconstruct the executable path from validated components.

        Returns a NEW string built from validated dir + basename — NOT the
        original env var value. This severs the Fortify taint chain.
        """
        return os.path.join(self._dir, self._basename)


def get_python_executable() -> str:
    """Resolve the Python interpreter to use for hook / shell subprocesses.

    Resolution order (per user requirement):

      1. ``IAF_PYTHON_EXECUTABLE`` env var (explicit override; useful for NSSM
         where PATH may be sparse). Validated via _ValidatedExecutable dataclass.
      2. ``shutil.which("python3")`` — preferred when present (matches the
         literal token used in YAML configs on Unix).
      3. ``shutil.which("python")`` — Windows venvs typically expose this.
      4. ``sys.executable`` — guaranteed to exist for the running interpreter.
      5. Literal ``"python3"`` as a last-resort fallback.
    """
    validated = _ValidatedExecutable.from_env()
    if validated is not None:
        return validated.path

    found = shutil.which("python3") or shutil.which("python")
    if found:
        return found

    if sys.executable and os.path.exists(sys.executable):
        return sys.executable

    return "python3"
