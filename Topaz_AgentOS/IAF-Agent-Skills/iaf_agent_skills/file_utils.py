"""
Sync atomic write helpers for the skills engine (non-async context).
Shares the same portable_lock from file_lock.py.
"""
import json
import os
import pathlib
import tempfile
from typing import Any

import yaml

from .yaml_fast import safe_load as _fast_yaml_load

from .file_lock import portable_lock


def atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp", encoding=encoding
    ) as f:
        f.write(content)
        tmp = f.name
    os.replace(tmp, str(path))


def atomic_write_json(path, data: Any, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))


def atomic_write_yaml(path, data: Any) -> None:
    atomic_write_text(
        path,
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
    )


def locked_rmw_json_sync(path, modifier_fn) -> Any:
    """Sync read-modify-write for JSON files. modifier_fn must return new dict."""
    path = pathlib.Path(path)
    with portable_lock(path):
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        new_data = modifier_fn(data)
        if new_data is None:
            raise ValueError(f"locked_rmw_json_sync: modifier returned None for {path}")
        atomic_write_json(path, new_data)
    return new_data


def locked_rmw_yaml_sync(path, modifier_fn) -> Any:
    """Sync read-modify-write for YAML files. modifier_fn must return new dict."""
    path = pathlib.Path(path)
    with portable_lock(path):
        data = _fast_yaml_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}
        new_data = modifier_fn(data)
        if new_data is None:
            raise ValueError(f"locked_rmw_yaml_sync: modifier returned None for {path}")
        atomic_write_yaml(path, new_data)
    return new_data
