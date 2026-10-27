"""
Cross-platform file utilities — atomic writes and locked read-modify-write.

Works on Windows, Linux, and Mac. Safe across multiple gunicorn workers.

Two primitives:
  atomic_write_*   — crash-safe plain writes (temp file + os.replace)
  locked_rmw_*     — cross-process read-modify-write (portable_lock + atomic write)

Usage:
    from shared.file_utils import atomic_write_yaml, locked_rmw_yaml

    # Plain write (new file or full overwrite):
    atomic_write_yaml(path, data)

    # Read-modify-write (shared state, must be atomic):
    async def _modify(current: dict) -> dict:
        current["key"] = new_value
        return current          # MUST return — None raises ValueError
    await locked_rmw_yaml(path, _modify)
"""

import asyncio
import json
import os
import pathlib
import tempfile
from typing import Any, Callable

import yaml

# file_lock lives two levels up in IAF-Agent-Skills — import via installed package
# or fall back to a local portable_lock implementation using the same algorithm
try:
    from iaf_agent_skills.file_lock import portable_lock
except ImportError:
    # Inline fallback so this module works standalone (e.g. in tests)
    import time as _time
    from contextlib import contextmanager as _contextmanager

    _STALE = 30

    @_contextmanager
    def portable_lock(path, timeout=10):
        lock_path = pathlib.Path(str(path) + ".lock")
        deadline = _time.monotonic() + timeout
        wait = 0.02
        acquired = False
        while _time.monotonic() < deadline:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                acquired = True
                break
            except FileExistsError:
                try:
                    if _time.monotonic() - lock_path.stat().st_mtime > _STALE:
                        lock_path.unlink(missing_ok=True)
                except OSError:
                    pass
                _time.sleep(wait)
                wait = min(wait * 2, 0.20)
        if not acquired:
            raise TimeoutError(f"portable_lock timeout: {path}")
        try:
            yield
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass



def atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """Write content to path atomically — reader gets old or new, never partial."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding=encoding
    ) as f:
        f.write(content)
        tmp = f.name
    os.replace(tmp, str(path))


def atomic_write_json(path, data: Any, indent: int = 2) -> None:
    """Atomically write data as JSON."""
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))


def atomic_write_yaml(path, data: Any) -> None:
    """Atomically write data as YAML."""
    atomic_write_text(
        path,
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
    )



async def locked_rmw_yaml(path, modifier_fn: Callable[[dict], dict]) -> Any:
    """
    Async-safe, cross-process read-modify-write for YAML files.

    Acquires a portable file lock, reads the file, calls modifier_fn(data),
    then atomically writes the result. Runs on a thread so the asyncio event
    loop is never blocked.

    Contract for modifier_fn:
      - Receives the current dict (empty dict if file doesn't exist)
      - MUST return the new dict — returning None raises ValueError
      - May raise to abort the write (exception propagates, file unchanged)
    """
    path = pathlib.Path(path)
    result: Any = None

    def _do() -> None:
        nonlocal result
        with portable_lock(path):
            data = (
                yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if path.exists()
                else {}
            )
            new_data = modifier_fn(data)
            if new_data is None:
                raise ValueError(
                    f"locked_rmw_yaml: modifier_fn returned None for {path} "
                    "— modifier must return the modified dict"
                )
            atomic_write_yaml(path, new_data)
            result = new_data

    await asyncio.to_thread(_do)
    return result


async def locked_rmw_json(path, modifier_fn: Callable[[dict], dict]) -> Any:
    """
    Async-safe, cross-process read-modify-write for JSON files.

    Same contract as locked_rmw_yaml — modifier_fn must return new dict.
    """
    path = pathlib.Path(path)
    result: Any = None

    def _do() -> None:
        nonlocal result
        with portable_lock(path):
            data = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists()
                else {}
            )
            new_data = modifier_fn(data)
            if new_data is None:
                raise ValueError(
                    f"locked_rmw_json: modifier_fn returned None for {path} "
                    "— modifier must return the modified dict"
                )
            atomic_write_json(path, new_data)
            result = new_data

    await asyncio.to_thread(_do)
    return result
