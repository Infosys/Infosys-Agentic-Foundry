"""
Atomic file-write helpers with portable locking.

YAML-only (no JSON variants here) because agent_os core only needs YAML for
credential storage. JSON helpers live in iaf_agent_skills/file_utils.py
for Studio-side callers (memory.py, settings.py, etc.).

PyYAML is imported lazily so agent_os core stays stdlib-only for callers
that don't use the credential file backend.
"""
import os
import pathlib
import tempfile
from typing import Any

from .file_lock import portable_lock


def atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """Write text atomically — write to temp file then rename into place."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding=encoding
    ) as f:
        f.write(content)
        tmp = f.name
    os.replace(tmp, str(path))


def atomic_write_yaml(path, data: Any) -> None:
    """Write YAML atomically. Requires PyYAML."""
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "PyYAML is required for YAML credential storage. "
            "Install with: pip install pyyaml  (or pip install agent_os[credentials])"
        ) from e
    atomic_write_text(
        path,
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
    )


def locked_rmw_yaml_sync(path, modifier_fn) -> Any:
    """
    Read-modify-write for YAML files with portable file lock.

    Holds an exclusive lock on `path` for the duration of read → modify → write
    to prevent concurrent writers from clobbering each other.

    Args:
        path:        Path to the YAML file.
        modifier_fn: Callable that takes the loaded dict and returns the modified dict.
                     Must NOT return None (raises ValueError if it does).

    Returns:
        The new data dict written to disk.
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "PyYAML is required for YAML credential storage. "
            "Install with: pip install pyyaml  (or pip install agent_os[credentials])"
        ) from e
    path = pathlib.Path(path)
    with portable_lock(path):
        data = (
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if path.exists()
            else {}
        )
        new_data = modifier_fn(data)
        if new_data is None:
            raise ValueError(f"locked_rmw_yaml_sync: modifier returned None for {path}")
        atomic_write_yaml(path, new_data)
    return new_data
