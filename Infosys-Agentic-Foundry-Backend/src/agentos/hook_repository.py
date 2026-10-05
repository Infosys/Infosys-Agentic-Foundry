# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Hook Repository — File-based, department-segregated hook script storage.

Storage layout (inside ``agent_workspaces/``):
    _hook_repository/
    ├── General/
    │   ├── audit_db_queries.py
    │   └── _manifest.json
    ├── IT/
    │   ├── block_ping.py
    │   └── _manifest.json
    └── Finance/
        └── _manifest.json

All hooks belong to a department. There is no global/shared folder.

Hooks have a ``scope`` field:
  - ``"agent"`` (default) — Must be explicitly bound to a specific agent/skill.
    Event type and matcher are configured at binding time.
  - ``"global"`` — Fires automatically for ALL agents in the department.
    ``event`` must be set at creation time (OnAgentStart, OnAgentEnd,
    OnAgentError, or PostSampling).

Each ``_manifest.json`` is an index of hook scripts in that folder::

    {
      "hooks": [
        {
          "hook_id": "hk_a1b2c3d4e5f6",
          "name": "Block Ping Commands",
          "description": "Blocks shell commands containing ping",
          "filename": "block_ping.py",
          "created_by": "sohan_dhara",
          "created_at": "2026-05-15T10:00:00Z",
          "department": "IT",
          "scope": "agent",
          "version": 1
        },
        {
          "hook_id": "hk_f6e5d4c3b2a1",
          "name": "Audit All Requests",
          "description": "Logs every agent invocation",
          "filename": "audit_all.py",
          "created_by": "admin",
          "created_at": "2026-05-15T11:00:00Z",
          "department": "IT",
          "scope": "global",
          "event": "OnAgentStart",
          "version": 1
        }
      ]
    }

Cloud-sync compatible: sits inside ``agent_workspaces/`` so the existing
``WorkspaceBlobSync`` picks it up automatically.
"""

import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.application_config import app_config

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_WORKSPACES_BASE = app_config.AGENT_WORKSPACES_BASE
HOOK_REPO_FOLDER = "_hook_repository"
MANIFEST_FILE = "_manifest.json"


def _sanitize_workspace_root(raw_path: str) -> str:
    """Sanitize workspace root path — reject traversal sequences."""
    if ".." in raw_path:
        return "./agent_workspaces"
    return raw_path

# Valid hook events (kept for reference/validation in hook_runner)
VALID_EVENTS = frozenset({
    "PreToolUse", "PostToolUse", "PreResponse", "PostSampling",
    "OnAgentStart", "OnAgentEnd", "OnAgentError",
})

# Events allowed for global scope (auto-fire for all agents, no per-agent binding)
GLOBAL_ALLOWED_EVENTS = frozenset({
    "OnAgentStart", "OnAgentEnd", "OnAgentError", "PostSampling",
})

# Valid scopes
VALID_SCOPES = frozenset({"agent", "global"})


# ---------------------------------------------------------------------------
# Hook metadata type
# ---------------------------------------------------------------------------

class HookMeta(dict):
    """Dict subclass for hook metadata with attribute access."""

    @property
    def hook_id(self) -> str:
        return self.get("hook_id", "")

    @property
    def name(self) -> str:
        return self.get("name", "")

    @property
    def filename(self) -> str:
        return self.get("filename", "")

    @property
    def department(self) -> str:
        return self.get("department", "General")


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class HookRepository:
    """File-based hook script repository with department segregation.

    Args:
        workspace_root: Path to agent_workspaces (default from env).
    """

    def __init__(self, workspace_root: Optional[str] = None):
        _raw = workspace_root or AGENT_WORKSPACES_BASE
        # Security: reject traversal sequences before resolution
        if ".." in str(_raw):
            log.warning(f"[HookRepository] Rejecting workspace_root with traversal: {_raw!r}")
            _raw = AGENT_WORKSPACES_BASE
        _sanitized = _sanitize_workspace_root(_raw)
        self._root = Path(os.path.realpath(_sanitized)) / HOOK_REPO_FOLDER
        # Containment: ensure resolved root is an absolute path
        if not self._root.is_absolute():
            log.warning(f"[HookRepository] Root path is not absolute, using default")
            self._root = Path(os.path.realpath(AGENT_WORKSPACES_BASE)) / HOOK_REPO_FOLDER
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dept_dir(self, department: str) -> Path:
        """Return the department directory (created if missing)."""
        safe = department.replace("..", "").replace("/", "_").replace("\\", "_").strip()
        if not safe:
            safe = "General"
        d = self._root / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest_path(self, department: str) -> Path:
        return self._dept_dir(department) / MANIFEST_FILE

    def _read_manifest(self, department: str) -> List[dict]:
        mp = self._manifest_path(department)
        if not mp.is_file():
            return []
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
            return data.get("hooks", [])
        except Exception as e:
            log.warning(f"[HookRepo] Bad manifest for {department}: {e}")
            return []

    def _write_manifest(self, department: str, hooks: List[dict]):
        mp = self._manifest_path(department)
        mp.write_text(
            json.dumps({"hooks": hooks}, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _gen_hook_id() -> str:
        return f"hk_{secrets.token_hex(6)}"

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_hook(
        self,
        name: str,
        code: str,
        department: str = "General",
        description: str = "",
        created_by: str = "",
        scope: str = "agent",
        event: Optional[str] = None,
    ) -> HookMeta:
        """Save a new hook script and register it in the manifest.

        Args:
            scope: ``"agent"`` (default) requires per-agent binding.
                   ``"global"`` auto-fires for all agents in the department.
            event: Required when scope is ``"global"``. Must be one of
                   OnAgentStart, OnAgentEnd, OnAgentError, PostSampling.

        Returns the created hook metadata dict.
        """
        # Validate scope
        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope '{scope}'. Must be one of: {sorted(VALID_SCOPES)}")

        # Check for duplicate name within the same department
        existing_hooks = self._read_manifest(department)
        for h in existing_hooks:
            if h.get("name", "").lower() == name.lower():
                raise ValueError(
                    f"A hook named '{name}' already exists in department '{department}' "
                    f"(hook_id: {h.get('hook_id')}). Please choose a different name."
                )

        # Global hooks must specify an event
        if scope == "global":
            if not event:
                raise ValueError("Global hooks must specify an 'event' (OnAgentStart, OnAgentEnd, OnAgentError, or PostSampling)")
            if event not in GLOBAL_ALLOWED_EVENTS:
                raise ValueError(
                    f"Global hooks only support events: {sorted(GLOBAL_ALLOWED_EVENTS)}. "
                    f"For '{event}', use scope='agent' and bind per-agent."
                )

        hook_id = self._gen_hook_id()

        # Sanitize filename from name
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
        filename = f"{safe_name}_{hook_id[-6:]}.py"

        # Write the script file
        dept_dir = self._dept_dir(department)
        script_path = dept_dir / filename
        log.info(f"[PVC:agent_workspaces] START create_hook — hook_id={hook_id}, name='{name}', department='{department}', scope='{scope}', path='{script_path}', mountPath=/app/agent_workspaces")
        script_path.write_text(code, encoding="utf-8")

        # Build metadata
        meta_dict = {
            "hook_id": hook_id,
            "name": name,
            "description": description,
            "filename": filename,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "department": department,
            "scope": scope,
            "version": 1,
        }
        if scope == "global" and event:
            meta_dict["event"] = event

        meta = HookMeta(meta_dict)

        # Update manifest
        hooks = self._read_manifest(department)
        hooks.append(dict(meta))
        self._write_manifest(department, hooks)

        log.info(f"[HookRepo] Created hook '{name}' ({hook_id}) scope={scope} in {department}")
        log.info(f"[PVC:agent_workspaces] END create_hook — hook_id={hook_id}, name='{name}', department='{department}', path='{script_path}', mountPath=/app/agent_workspaces")
        return meta

    def list_hooks(self, department: Optional[str] = None) -> List[HookMeta]:
        """List hooks for a department.

        - If *department* is given: returns hooks from that department only.
        - If *department* is None: returns ALL hooks across every department.
        """
        result: List[HookMeta] = []

        if department is None:
            # Return hooks from ALL departments
            for dept_dir in sorted(self._root.iterdir()):
                if not dept_dir.is_dir():
                    continue
                dept_name = dept_dir.name
                for h in self._read_manifest(dept_name):
                    h["department"] = dept_name
                    result.append(HookMeta(h))
        else:
            # Return only the specified department's hooks
            for h in self._read_manifest(department):
                h["department"] = department
                result.append(HookMeta(h))

        return result

    def get_hook(self, hook_id: str) -> Optional[HookMeta]:
        """Find a hook by ID across all departments."""
        for dept_dir in self._root.iterdir():
            if not dept_dir.is_dir():
                continue
            dept_name = dept_dir.name
            for h in self._read_manifest(dept_name):
                if h.get("hook_id") == hook_id:
                    h["department"] = dept_name
                    return HookMeta(h)
        return None

    def get_hook_code(self, hook_id: str) -> Optional[str]:
        """Return the Python source code of a hook."""
        meta = self.get_hook(hook_id)
        if not meta:
            return None
        script_path = self._dept_dir(meta.department) / meta.filename
        if not script_path.is_file():
            return None
        return script_path.read_text(encoding="utf-8")

    def get_hook_path(self, hook_id: str) -> Optional[Path]:
        """Return the absolute filesystem path of a hook script.

        Used by HookRunner to build the subprocess command.
        """
        meta = self.get_hook(hook_id)
        if not meta:
            return None
        script_path = self._dept_dir(meta.department) / meta.filename
        if not script_path.is_file():
            return None
        return script_path.resolve()

    def update_hook(
        self,
        hook_id: str,
        code: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[HookMeta]:
        """Update an existing hook's code and/or metadata."""
        meta = self.get_hook(hook_id)
        if not meta:
            return None

        department = meta.department
        hooks = self._read_manifest(department)

        for h in hooks:
            if h.get("hook_id") == hook_id:
                if name is not None:
                    h["name"] = name
                if description is not None:
                    h["description"] = description
                h["version"] = h.get("version", 1) + 1
                h["updated_at"] = datetime.now(timezone.utc).isoformat()

                if code is not None:
                    script = self._dept_dir(department) / h["filename"]
                    script.write_text(code, encoding="utf-8")

                self._write_manifest(department, hooks)
                h["department"] = department
                log.info(f"[HookRepo] Updated hook {hook_id}")
                return HookMeta(h)

        return None

    def delete_hook(self, hook_id: str) -> bool:
        """Delete a hook script and remove from manifest."""
        meta = self.get_hook(hook_id)
        if not meta:
            return False

        department = meta.department

        # Remove script file
        script_path = self._dept_dir(department) / meta.filename
        try:
            script_path.unlink(missing_ok=True)
        except Exception as e:
            log.warning(f"[HookRepo] Could not delete script {script_path}: {e}")

        # Remove from manifest
        hooks = self._read_manifest(department)
        hooks = [h for h in hooks if h.get("hook_id") != hook_id]
        self._write_manifest(department, hooks)

        log.info(f"[HookRepo] Deleted hook {hook_id}")
        return True

    def list_global_hooks(self, department: str) -> List[HookMeta]:
        """Return all hooks with scope='global' for a department.

        These are the hooks that auto-fire for every agent in the department
        without requiring per-agent binding.
        """
        result: List[HookMeta] = []
        for h in self._read_manifest(department):
            if h.get("scope") == "global" and h.get("event"):
                h["department"] = department
                result.append(HookMeta(h))
        return result

    def list_all_departments(self) -> List[str]:
        """List all department folders in the repository."""
        return sorted(
            d.name for d in self._root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_instance: Optional[HookRepository] = None


def get_hook_repository() -> HookRepository:
    """Return the singleton HookRepository instance."""
    global _instance
    if _instance is None:
        _instance = HookRepository()
    return _instance
