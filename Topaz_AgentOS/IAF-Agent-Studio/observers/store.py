"""
Observers — persistence layer.

`ObserverStore(ABC)` with a `get_observer_store()` singleton factory, mirroring
`cc_queue.db.get_db()` and `iaf_agent_skills.approval_store.get_approval_store()`.

This slice ships `YamlObserverStore` (reads observers/spec/*.yaml). Because
callers depend only on the ABC, a future `SqliteObserverStore` (into
command_center.db, when the management UI lands) is a drop-in replacement with
zero caller changes.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from observers.models import ObserverSpec

logger = logging.getLogger(__name__)

# observers/spec/ next to this file.
SPEC_DIR = Path(__file__).resolve().parent / "spec"

# A name becomes the spec filename; keep it a safe slug so no name can traverse
# out of spec_dir. The HTTP layer validates too — this is defense in depth.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ObserverStore(ABC):
    """Persistence contract for observer specs."""

    @abstractmethod
    def list_specs(self) -> List[ObserverSpec]:
        ...

    @abstractmethod
    def get_spec(self, name: str) -> Optional[ObserverSpec]:
        ...

    @abstractmethod
    def save_spec(self, spec: ObserverSpec) -> None:
        ...

    @abstractmethod
    def delete_spec(self, name: str) -> bool:
        ...


class YamlObserverStore(ObserverStore):
    """File-backed store: one YAML file per observer under `spec_dir`.

    KNOWN LIMITATION (tenant isolation — deferred architectural change): specs are
    keyed by name under one process-wide directory; ObserverSpec.tenant_id is not part
    of the key, so two tenants can collide on the same observer name. The HTTP routes
    scope reads and mutations to the caller's authorized tenant (_caller_tenants /
    _spec_or_404), but observers ship feature-flagged off (OBSERVERS_ENABLED) and storage
    should be re-keyed by (tenant_id, name) before enabling them in a multi-tenant process.
    """

    def __init__(self, spec_dir: Path = SPEC_DIR):
        self.spec_dir = spec_dir
        self.spec_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not _SAFE_NAME_RE.match(name or ""):
            raise ValueError(f"unsafe observer name: {name!r}")
        return self.spec_dir / f"{name}.yaml"

    def list_specs(self) -> List[ObserverSpec]:
        specs: List[ObserverSpec] = []
        for path in sorted(self.spec_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text()) or {}
                specs.append(ObserverSpec(**data))
            except Exception as exc:  # skip malformed spec, don't crash the list
                logger.warning("Skipping malformed observer spec %s: %s", path.name, exc)
        return specs

    def get_spec(self, name: str) -> Optional[ObserverSpec]:
        try:
            path = self._path(name)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text()) or {}
            return ObserverSpec(**data)
        except Exception as exc:
            logger.warning("Malformed observer spec %s: %s", path.name, exc)
            return None

    def save_spec(self, spec: ObserverSpec) -> None:
        # pydantic v1 (.dict) / v2 (.model_dump) compatible.
        as_dict = spec.model_dump(mode="json") if hasattr(spec, "model_dump") else spec.dict()
        # Atomic write (temp + replace) so a crash never leaves a half-written spec.
        path = self._path(spec.name)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(as_dict, sort_keys=False))
        tmp.replace(path)
        logger.info("Saved observer spec: %s", spec.name)

    def delete_spec(self, name: str) -> bool:
        try:
            path = self._path(name)
        except ValueError:
            return False
        if not path.exists():
            return False
        path.unlink()
        logger.info("Deleted observer spec: %s", name)
        return True


_store: Optional[ObserverStore] = None


def get_observer_store() -> ObserverStore:
    """Lazily build the process-wide ObserverStore.

    Backend is chosen here so callers never construct a concrete store. Today
    only YAML; add SqliteObserverStore selection (e.g. via an env flag) later.
    """
    global _store
    if _store is None:
        _store = YamlObserverStore()
    return _store
