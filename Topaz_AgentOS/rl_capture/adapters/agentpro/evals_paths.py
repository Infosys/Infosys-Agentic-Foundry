"""AgentPro path adapter for tenant-owned eval assets."""

from __future__ import annotations

import os
from pathlib import Path


def tenant_root(tenant_id: str) -> Path:
    from shared.config import DATA_ROOT_PATH

    return DATA_ROOT_PATH / "tenants" / tenant_id


def evals_dir(tenant_id: str) -> Path:
    root = tenant_root(tenant_id) / "evals"
    root.mkdir(parents=True, exist_ok=True)
    return root


def golden_sets_dir(tenant_id: str) -> Path:
    root = tenant_root(tenant_id) / "golden_sets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def evaluators_dir(tenant_id: str) -> Path:
    root = tenant_root(tenant_id) / "eval_evaluators"
    root.mkdir(parents=True, exist_ok=True)
    return root


def eval_runtime_db_path(tenant_id: str) -> Path:
    override = os.getenv("EVAL_RUNTIME_DB_PATH", "").strip()
    if override:
        from agent_os.safe_path import validated_path

        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            from shared.config import resolve_server_path

            candidate = resolve_server_path(candidate)
        # Raises SecurityError for values outside the portable path allowlist.
        path = validated_path(candidate, label="EVAL_RUNTIME_DB_PATH")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    root = tenant_root(tenant_id) / "shared" / "databases"
    root.mkdir(parents=True, exist_ok=True)
    return root / "eval_runtime.db"


def eval_storage_engine(tenant_id: str):
    """Return the active StorageEngine for eval runtime persistence."""
    from iaf_agent_skills.storage.engine import get_engine

    return get_engine(eval_runtime_db_path(tenant_id))
