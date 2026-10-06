# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
AgentShell - Secure Unix-like shell for AI agents.

Provides a sandboxed shell environment with:
- Standard Unix commands (ls, cd, cat, grep, find, echo, etc.)
- Semantic search via semgrep command
- Auto-indexing of memory files
- Path security (no traversal, no dangerous commands)
"""

import os
import re
import shlex
import fnmatch
import difflib
import hashlib
import math
import platform
import socket
import subprocess
import time as _time_mod
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass

from src.config.application_config import app_config

# Support both relative and absolute imports
try:
    from .vector_store import VectorStore
except ImportError:
    from vector_store import VectorStore

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-path write lock (Fix #17) — prevents two concurrent sessions
# writing to the same /agent/facts/ file from interleaving and corrupting data.
# ---------------------------------------------------------------------------
_write_lock_registry: Dict[str, threading.Lock] = {}
_write_lock_meta = threading.Lock()              # protects the registry itself
_write_lock_refcounts: Dict[str, int] = {}


def _acquire_write_lock(path: str) -> threading.Lock:
    """Get (or create) a per-path lock and acquire it."""
    with _write_lock_meta:
        if path not in _write_lock_registry:
            _write_lock_registry[path] = threading.Lock()
            _write_lock_refcounts[path] = 0
        _write_lock_refcounts[path] += 1
        lock = _write_lock_registry[path]
    lock.acquire()
    return lock


def _release_write_lock(path: str):
    """Release and optionally clean up a per-path lock."""
    with _write_lock_meta:
        lock = _write_lock_registry.get(path)
        if lock is None:
            return
        lock.release()
        _write_lock_refcounts[path] -= 1
        if _write_lock_refcounts[path] <= 0:
            _write_lock_registry.pop(path, None)
            _write_lock_refcounts.pop(path, None)


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    output: str
    error_code: Optional[str] = None


class AgentShell:
    """
    Secure shell environment for AI agents.
    
    Provides Unix-like commands in a sandboxed environment:
    - ls, cd, pwd: Navigate directories
    - cat, head, tail: Read files
    - grep: Search for patterns
    - find: Find files by name
    - echo: Write to files (with > and >>)
    - mkdir, touch: Create directories and files
    - semgrep: Semantic search
    
    Directory Structure (NEW - Separated User and Agent):
    ```
    {workspace_root}/
    ├── users/                          # User-level data (shared across ALL agents)
    │   └── {user_email}/
    │       └── preferences.md          # User preferences (theme, language, etc.)
    │
    └── agents/                         # Agent-level data (separate from users)
        └── {agent_id}/
            ├── agent/                  # Agent-level data (persistent across sessions)
            │   ├── facts/              # Agent-specific facts, API keys, credentials
            │   ├── learnings/          # Agent learnings
            │   └── entities/           # Known entities
            ├── db_cache/               # Database schema & sample data cache
            │   ├── schema_cache.json
            │   ├── sample_data_cache.json
            │   └── cache_metadata.json
            └── sessions/
                └── {session_id}/
                    ├── session/        # Session-level data (current session only)
                    │   ├── workspace/  # Scratchpad for current task
                    │   ├── history/    # Session history
                    │   └── pending_context/
                    │       └── current.md
                    ├── conversations/  # VIRTUAL: Past chat history (read-only)
                    │   ├── summary.md
                    │   └── full.md
                    └── .index/         # Vector store index
    ```
    """
    
    # Blocked commands for security
    BLOCKED_COMMANDS = [
        "rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp",
        "sudo", "su", "wget", "ssh", "scp", "rsync",
        "kill", "pkill", "killall", "shutdown", "reboot",
        "python", "python3", "node", "ruby", "perl", "bash", "sh"
    ]
    
    # Limits
    MAX_READ_BYTES = 50 * 1024  # 50KB
    MAX_READ_LINES = 200
    MAX_LIST_ITEMS = 100
    MAX_GREP_RESULTS = 50
    MAX_FIND_RESULTS = 100
    MAX_RGLOB_DEPTH = 8          # max directory depth for recursive scans
    MAX_RGLOB_ENTRIES = 5_000    # max entries visited per rglob call
    MAX_READFILE_OUTPUT_CHARS = 100_000  # output truncation for readfile
    SHELL_COMMAND_TIMEOUT = 30   # seconds per shell invocation

    # Text-like extensions that grep -r will search (H2: expanded set)
    _GREP_EXTENSIONS = {
        "", ".md", ".txt", ".json", ".yaml", ".yml",
        ".csv", ".tsv", ".log",
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs",
        ".xml", ".html", ".htm", ".css",
        ".cfg", ".ini", ".toml", ".env", ".sh", ".bat", ".ps1",
        ".sql", ".r", ".rb", ".pl", ".lua",
        ".properties", ".conf", ".config",
    }
    
    # Binary / complex file extensions that require execute_python_code
    BINARY_EXTENSIONS = {
        ".pdf", ".xlsx", ".xls", ".docx", ".pptx",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
        ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".mp3", ".wav", ".mp4", ".avi", ".mov",
        ".parquet", ".feather", ".orc", ".avro",
        ".sqlite", ".db",
        ".pkl", ".pickle", ".npy", ".npz",
    }
    
    # Dangerous operators
    DANGEROUS_OPERATORS = ["&&", "||", ";", "`", "$(", "${"]
    
    # Virtual directories (not real filesystem)
    VIRTUAL_DIRS = ["/session/conversations"]
    
    def __init__(
        self,
        agent_id: str,
        session_id: str,
        user_email: str = None,
        workspace_root: str = "./agent_workspaces",
        department: str = None,
        chat_logs_path: str = None,
        enable_semantic_search: bool = True,
        additional_paths: list = None,
        allowed_absolute_mount_roots: list = None,
        agentos_root_override: str = None,
        databases_root_override: str = None,
    ):
        """
        Initialize AgentShell.
        
        Args:
            agent_id: Agent identifier (MANDATORY).
            session_id: Session identifier (MANDATORY).
            user_email: User email for user-level persistence (optional but recommended).
            workspace_root: Root directory for all workspaces.
            department: Department name for workspace segregation (defaults to 'General').
            chat_logs_path: Path to conversations.json (auto-detected if None).
            enable_semantic_search: Enable semgrep command.
            additional_paths: Optional list of dicts with keys 'path' (relative
                paths are resolved under ``user_uploads/{department}/``;
                set ``absolute: True`` for system-level paths),
                'permission' ('read' or 'read-write'), and optional
                'absolute' (bool, default False).
                The virtual mount name is auto-derived from the last path segment.
            allowed_absolute_mount_roots: Optional list of absolute directory
                paths that this agent is allowed to mount when entries have
                absolute=True.  Stored in agent_config.json.  If the env var
                ALLOWED_ABSOLUTE_MOUNT_ROOTS is also set, agent-level roots
                must additionally be within those server-level roots.
            agentos_root_override: If provided, overrides the default
                ``{workspace_root}/{department}/agentos_agents/{agent_id}/``
                path for skills and enterprise_context resolution.  Used when
                a shared agent's assets live in the owner's department folder.
            databases_root_override: If provided, overrides the default
                ``{workspace_root}/{department}/databases/`` path for database
                schema/samples resolution.  Used for cross-department sharing.
        """
        if not agent_id or not session_id:
            raise ValueError("agent_id and session_id are required")
        
        self.agent_id = agent_id
        self.session_id = session_id
        self.user_email = user_email or "anonymous"
        self.department = department or "General"
        # Sanitize email for filesystem (replace @ and . with _)
        self.user_dir_name = self.user_email.replace("@", "_at_").replace(".", "_")
        self.workspace_root = Path(workspace_root).resolve()
        
        # Chat logs path - auto-detect if not provided
        if chat_logs_path:
            self.chat_logs_path = Path(chat_logs_path)
        else:
            # Try to find conversations.json relative to src/inference/chat_logs
            possible_paths = [
                Path(__file__).parent.parent.parent / "inference" / "chat_logs" / "conversations.json",
                Path("./src/inference/chat_logs/conversations.json"),
                Path("./chat_logs/conversations.json"),
            ]
            self.chat_logs_path = None
            for p in possible_paths:
                if p.exists():
                    self.chat_logs_path = p.resolve()
                    break
        
        # NEW STRUCTURE: Department-segregated workspace
        # {workspace_root}/{department}/users/{user_email}/
        # {workspace_root}/{department}/agents/{agent_id}/
        # {workspace_root}/{department}/databases/{connection_name}/ (SHARED/REUSABLE)
        
        dept_root = self.workspace_root / self.department
        
        # User root: shared across all agents for this user within the department
        self.user_root = (dept_root / "users" / self.user_dir_name).resolve()
        
        # Agent root: separate from user, under /agents/
        self.agent_root = (dept_root / "agents" / agent_id).resolve()
        
        # Databases root: SHARED across all agents within the department (reusable)
        # Override available for cross-department sharing (databases live in owner's dept)
        if databases_root_override:
            self.databases_root = Path(databases_root_override).resolve()
        else:
            self.databases_root = (dept_root / "databases").resolve()
        
        # Agentos root: where skill files and enterprise context live
        # Path: {workspace_root}/{department}/agentos_agents/{agent_id}/
        # Override available for cross-department sharing (assets live in owner's dept)
        if agentos_root_override:
            self.agentos_root = Path(agentos_root_override).resolve()
        else:
            self.agentos_root = (dept_root / "agentos_agents" / agent_id).resolve()
        self.skills_root = (self.agentos_root / "skills").resolve()
        self.enterprise_context_root = (self.agentos_root / "enterprise_context").resolve()
        
        # Session root: under agent, in sessions folder
        self.shell_root = (self.agent_root / "sessions" / session_id).resolve()
        
        # Virtual current working directory
        self.cwd = "/"
        
        # ---- Process additional_paths (user-configured custom mounts) ----
        self._additional_mounts = []  # List of (virtual_prefix, real_path, readonly)
        if additional_paths:
            dept_root = self.workspace_root / self.department
            existing_prefixes = {"/user", "/databases", "/skills", "/enterprise_context", "/agent", "/session"}
            used_names = set()

            # --- Build effective allowed roots (agent-level + server override) ---
            # 1. Agent-level roots (from agent_config.json via parameter)
            _agent_roots: list[Path] = []
            if allowed_absolute_mount_roots:
                for _r in allowed_absolute_mount_roots:
                    _r = str(_r).strip()
                    if _r:
                        _agent_roots.append(Path(_r).resolve())

            # 1b. Auto-derive roots from absolute entries when none were
            #     explicitly provided.  This prevents silent mount failures
            #     when a user adds an absolute path but omits the roots list.
            #     Only auto-derive when the parameter is None (not configured);
            #     an explicit empty list [] means "disabled".
            if allowed_absolute_mount_roots is None and not _agent_roots:
                for _entry in additional_paths:
                    if _entry.get("absolute"):
                        _raw = _entry.get("path", "").strip()
                        if _raw:
                            _p = Path(_raw).resolve()
                            # Use the path itself if it's a directory, else its parent
                            _agent_roots.append(_p if _p.is_dir() else _p.parent)
                if _agent_roots:
                    # De-duplicate while preserving order
                    _seen: set[Path] = set()
                    _deduped: list[Path] = []
                    for _ar in _agent_roots:
                        if _ar not in _seen:
                            _seen.add(_ar)
                            _deduped.append(_ar)
                    _agent_roots = _deduped
                    log.info(
                        f"[AgentShell] Auto-derived allowed_absolute_mount_roots "
                        f"from additional_paths: {[str(r) for r in _agent_roots]}"
                    )

            # 2. Server-level roots from env (optional hard constraint)
            _server_roots_raw = app_config.ALLOWED_ABSOLUTE_MOUNT_ROOTS
            _server_roots: list[Path] = []
            if _server_roots_raw:
                for _r in _server_roots_raw.split(","):
                    _r = _r.strip()
                    if _r:
                        # Sanitize: reject traversal sequences, resolve to canonical absolute
                        if ".." in _r:
                            log.warning(f"[AgentShell] Rejecting mount root with traversal: {_r!r}")
                            continue
                        _server_roots.append(Path(os.path.realpath(_r)))

            # 3. Compute effective roots:
            #    - If server roots set: agent roots must be within server roots
            #    - If server roots not set: agent roots used directly
            # Security: validate all agent roots are canonical absolute paths
            _validated_agent_roots: list[Path] = []
            for _ar in _agent_roots:
                _ar_resolved = Path(os.path.realpath(str(_ar)))
                if ".." in str(_ar):
                    log.warning(f"[AgentShell] Rejecting agent root with traversal: {_ar}")
                    continue
                _validated_agent_roots.append(_ar_resolved)
            _agent_roots = _validated_agent_roots

            _allowed_abs_roots: list[Path] = []
            if _agent_roots:
                if _server_roots:
                    # Filter: only keep agent roots that are under a server root
                    for ar in _agent_roots:
                        for sr in _server_roots:
                            try:
                                if ar.is_relative_to(sr):
                                    _allowed_abs_roots.append(ar)
                                    break
                            except (TypeError, AttributeError):
                                if str(ar).startswith(str(sr)):
                                    _allowed_abs_roots.append(ar)
                                    break
                    if _agent_roots and not _allowed_abs_roots:
                        log.warning(
                            f"[AgentShell] All agent-level allowed_absolute_mount_roots "
                            f"were filtered out by server ALLOWED_ABSOLUTE_MOUNT_ROOTS. "
                            f"Agent roots: {[str(r) for r in _agent_roots]}, "
                            f"Server roots: {[str(r) for r in _server_roots]}"
                        )
                else:
                    # No server constraint — use agent-level roots directly
                    _allowed_abs_roots = _agent_roots

            for entry in additional_paths:
                rel_path = entry.get("path", "").strip().replace("\\", "/").strip("/")
                permission = entry.get("permission", "read").strip().lower()
                is_absolute = entry.get("absolute", False)

                if not rel_path:
                    log.warning("[AgentShell] Skipping additional_path with empty path")
                    continue
                
                # Derive virtual mount name from the last path segment
                mount_name = Path(rel_path).name.strip()
                if not mount_name:
                    log.warning(f"[AgentShell] Cannot derive mount name from path: {rel_path}")
                    continue
                
                # Sanitize: lowercase, replace spaces/special chars
                safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in mount_name.lower())
                if not safe_name:
                    log.warning(f"[AgentShell] Mount name sanitization yielded empty string for: {mount_name}")
                    continue
                
                virtual_prefix = f"/{safe_name}"
                
                # Collision check: skip if conflicts with built-in or already used
                if virtual_prefix in existing_prefixes or safe_name in used_names:
                    log.warning(
                        f"[AgentShell] Skipping additional_path '{rel_path}': "
                        f"mount name '/{safe_name}' collides with existing mount"
                    )
                    continue

                # ---- Resolve real path (relative vs absolute mode) ----
                if is_absolute:
                    # Absolute-path mode: path must be under an allowed root
                    # Reconstruct the original absolute path (we stripped '/' earlier)
                    abs_path_str = entry.get("path", "").strip().replace("\\", "/")
                    real_path = Path(abs_path_str).resolve()

                    if not _allowed_abs_roots:
                        log.warning(
                            f"[AgentShell] Skipping absolute mount '{abs_path_str}': "
                            f"no allowed_absolute_mount_roots configured for this agent"
                        )
                        continue

                    # Check the resolved path sits under at least one allowed root
                    is_under_allowed = False
                    for allowed_root in _allowed_abs_roots:
                        try:
                            if real_path.is_relative_to(allowed_root):
                                is_under_allowed = True
                                break
                        except (TypeError, AttributeError):
                            # Python < 3.9 fallback
                            if str(real_path).startswith(str(allowed_root)):
                                is_under_allowed = True
                                break

                    if not is_under_allowed:
                        log.warning(
                            f"[AgentShell] Skipping absolute mount '{abs_path_str}': "
                            f"resolved path {real_path} is not under any allowed root. "
                            f"Allowed: {[str(r) for r in _allowed_abs_roots]}"
                        )
                        continue

                    # Symlink guard: resolve must still land under the allowed root
                    try:
                        resolved_real = real_path.resolve(strict=False)
                        is_still_under = False
                        for allowed_root in _allowed_abs_roots:
                            try:
                                if resolved_real.is_relative_to(allowed_root):
                                    is_still_under = True
                                    break
                            except (TypeError, AttributeError):
                                if str(resolved_real).startswith(str(allowed_root)):
                                    is_still_under = True
                                    break
                        if not is_still_under:
                            log.warning(
                                f"[AgentShell] Skipping absolute mount '{abs_path_str}': "
                                f"symlink resolves to {resolved_real} outside allowed roots"
                            )
                            continue
                    except OSError:
                        pass  # Path doesn't exist yet — OK, we'll create it

                    if not real_path.exists():
                        log.warning(
                            f"[AgentShell] Absolute mount path does not exist: {real_path}. "
                            f"Skipping (will not auto-create external directories)."
                        )
                        continue

                else:
                    # Relative-path mode: resolve under user_uploads/{department}/
                    # Users upload files/folders there; agent config references
                    # only the folder name and the system resolves the rest.
                    uploads_root = (self.workspace_root.parent / "user_uploads" / self.department).resolve()
                    real_path = (uploads_root / rel_path).resolve()
                    if not str(real_path).startswith(str(uploads_root)):
                        log.warning(
                            f"[AgentShell] Skipping additional_path '{rel_path}': "
                            f"resolved path {real_path} is outside user_uploads root"
                        )
                        continue

                    # Create directory if it doesn't exist
                    real_path.mkdir(parents=True, exist_ok=True)
                
                readonly = permission != "read-write"
                self._additional_mounts.append((virtual_prefix, real_path, readonly))
                used_names.add(safe_name)
                mode_tag = "ABSOLUTE" if is_absolute else "relative"
                log.info(
                    f"[AgentShell] Additional mount ({mode_tag}): {virtual_prefix} → {real_path} "
                    f"({'read-only' if readonly else 'read-write'})"
                )
        
        # Initialize vector store for semantic search
        self.vector_store: Optional[VectorStore] = None
        if enable_semantic_search:
            index_path = self.shell_root / ".index" / "vectors.json"
            self.vector_store = VectorStore(storage_path=index_path)
        
        # Bootstrap directory structure
        self._bootstrap()
        
        log.info(f"AgentShell initialized: user={self.user_email}, agent={agent_id}, session={session_id}")
    
    # ------------------------------------------------------------------
    #  Single source of truth for virtual ↔ real path mapping.
    #
    #  Every mount point is defined ONCE here.  _resolve_path,
    #  _to_virtual_path, _is_inside_sandbox, _is_readonly_path,
    #  and _all_virtual_roots all derive from this list.
    #
    #  To add a 7th mount point, add ONE entry here — nothing else.
    # ------------------------------------------------------------------

    @property
    def _mount_points(self):
        """Return the canonical list of (virtual_prefix, real_path, readonly) tuples.

        Order matters: more-specific prefixes MUST come before less-specific
        ones (e.g. ``/session`` before ``/``).  ``_resolve_path`` and
        ``_to_virtual_path`` iterate and short-circuit on the first match.

        Additional user-configured mounts (from ``additional_paths``) are
        appended after the 6 built-in mounts.
        """
        mounts = [
            ("/user",               self.user_root,                False),
            ("/databases",          self.databases_root,           True),
            ("/skills",             self.skills_root,              True),
            ("/enterprise_context", self.enterprise_context_root,  True),
            ("/agent",              self.agent_root / "agent",     False),
            ("/session",            self.shell_root / "session",   False),
        ]
        # Append additional user-configured mounts
        if self._additional_mounts:
            mounts.extend(self._additional_mounts)
        return mounts

    def get_path_mapping(self) -> dict:
        """Return a ``{virtual_prefix: {"real_path": str, "permission": str}}`` dict.

        This is consumed by :func:`create_skill_tools` so that
        ``execute_python_code`` can read binary/complex files (PDF, Excel,
        DOCX, …) from any mounted virtual path.
        """
        return {
            prefix: {"real_path": str(real_path), "permission": "read" if readonly else "read-write"}
            for prefix, real_path, readonly in self._mount_points
        }

    # ----- Hidden file guard (blocks agent from seeing mapping files) -----
    # File names that the shell must NEVER expose to the agent.
    _HIDDEN_FILENAMES = frozenset({"_path_mapping.json"})

    def _is_hidden_file(self, path: "Path") -> bool:
        """Return True if *path* refers to a file the agent must not access."""
        return path.name in self._HIDDEN_FILENAMES

    def _is_binary_file(self, path: "Path") -> bool:
        """Return True if *path* has a binary / complex extension that ``cat``
        cannot meaningfully render as UTF-8 text."""
        return path.suffix.lower() in self.BINARY_EXTENSIONS

    @staticmethod
    def _binary_redirect_message(display_path: str, virtual_path: str) -> str:
        """Return a user-friendly message directing the agent to use
        ``readfile`` for binary files."""
        ext = Path(display_path).suffix.lower()
        return (
            f"cat: {display_path}: Binary file ('{ext}') cannot be read as text.\n"
            f"Use `readfile {virtual_path}` to extract content from this file."
        )

    def _bootstrap(self):
        """Create the hierarchical directory structure (NEW STRUCTURE)."""
        # User-level directories (under /users/{user_email}/ - shared across ALL agents)
        # Only preferences file lives here
        user_dirs = [
            self.user_root,  # /users/{user_email}/
        ]
        
        # Agent-level directories (under /agents/{agent_id}/ - persistent across sessions)
        # Facts, API keys, credentials go here (NO db data - that's shared)
        agent_dirs = [
            self.agent_root / "agent" / "facts",
            self.agent_root / "agent" / "learnings",
            self.agent_root / "agent" / "entities",
        ]
        
        # Databases directory (SHARED across ALL agents - reusable)
        # /databases/{connection_name}/ with schema.md and samples.md
        databases_dirs = [
            self.databases_root,  # /databases/
        ]
        
        # Session-level directories (under /agents/{agent_id}/sessions/{session_id}/)
        session_dirs = [
            self.shell_root / "session" / "workspace",
            self.shell_root / "session" / "history",
            self.shell_root / "session" / "pending_context",  # For multi-turn conversation state
            self.shell_root / ".index",
        ]
        
        all_dirs = user_dirs + agent_dirs + databases_dirs + session_dirs
        for d in all_dirs:
            d.mkdir(parents=True, exist_ok=True)
        
        # Create empty pending_context file if not exists (session-specific)
        pending_context = self.shell_root / "session" / "pending_context" / "current.md"
        if not pending_context.exists():
            pending_context.write_text("", encoding="utf-8")
        
        # Create user preferences file if not exists (directly under /users/{user_email}/)
        user_prefs = self.user_root / "preferences.md"
        if not user_prefs.exists():
            user_prefs.write_text(f"""# User Preferences

**User:** {self.user_email}
**Created:** {datetime.now().isoformat()}

## Display Settings
- theme: default
- language: en

## Notification Settings
- email_notifications: true

## Other Preferences
(Add your preferences here)
""", encoding="utf-8")
        
        # Create welcome/README file in session
        readme = self.shell_root / "README.md"
        if not readme.exists():
            readme.write_text(f"""# Agent Workspace

**User:** {self.user_email}
**Agent:** {self.agent_id}
**Session:** {self.session_id}
**Created:** {datetime.now().isoformat()}

## Directory Structure (NEW - Separated Users, Agents, and Databases)

### Skill Files (READ-ONLY)
- `/skills/{{skill_name}}/SKILL.md` - Core knowledge and instructions
- `/skills/{{skill_name}}/INSTRUCTIONS.md` - Step-by-step procedures
- `/skills/{{skill_name}}/EXAMPLES.md` - Example queries and responses

### Enterprise Context (READ-ONLY)
- `/enterprise_context/` - Enterprise-wide context and policies

### User Level (shared across ALL agents)
- `/user/preferences.md` - User display/notification preferences

### Agent Level (separate from users, persistent across sessions)
- `/agent/facts/` - Agent-specific facts, API keys, credentials
- `/agent/learnings/` - Patterns and insights
- `/agent/entities/` - Known entities

### Databases Level (SHARED/REUSABLE across ALL agents, READ-ONLY)
- `/databases/{{connection_name}}/schema.md` - Database schema
- `/databases/{{connection_name}}/samples.md` - Sample data

### Session Level (current session)
- `/session/workspace/` - Scratchpad for current task
- `/session/history/` - Session history
- `/session/conversations/` - [VIRTUAL] Past chat history (read-only)
  - `summary.md` - AI-generated conversation summaries
  - `full.md` - Full conversation history

## Commands

- `ls`, `cd`, `pwd` - Navigate
- `cat`, `head`, `tail` - Read files
- `grep "pattern" /path` - Search by text
- `semgrep "concept" /path` - Search by meaning
- `echo "text" > /file` - Write to file
- `find /path -name "*.md"` - Find files
- `get_secret <key_name>` - Retrieve credentials from platform vault

## Tips

1. Skill files are at `/skills/{{skill_name}}/` (READ-ONLY, always read SKILL.md first)
2. Enterprise context is at `/enterprise_context/` (READ-ONLY)
3. User preferences go to `/user/preferences.md` (shared across all agents)
4. API keys and facts go to `/agent/facts/` (persists across sessions)
5. Database schema/sample files are at `/databases/{{conn}}/` (SHARED, read with cat)
6. Use `/session/workspace/` for temporary work
7. Use `semgrep` when exact grep fails
""", encoding="utf-8")
    
    def run(self, command: str) -> str:
        """
        Execute a shell command.
        
        Args:
            command: The command to execute.
            
        Returns:
            Command output as string.
        """
        command = command.strip()
        
        if not command:
            return ""
        
        # Security checks — block path traversal in path-like tokens only
        # We check for '..' as a path component (not inside quoted strings
        # like grep patterns), then fall back to _is_inside_sandbox() as
        # a hard second layer after path resolution.
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        for token in tokens:
            # Skip flags and quoted patterns (grep "foo..bar")
            if token.startswith("-"):
                continue
            if "/" in token or "\\" in token:
                # This looks like a path — block '..' components
                if ".." in token.split("/") or ".." in token.split("\\"):
                    return "Error: Path traversal (..) is not allowed"
        
        for op in self.DANGEROUS_OPERATORS:
            if op in command:
                return f"Error: Operator '{op}' is not allowed"
        
        # Parse command — with timeout guard (H5)
        import concurrent.futures as _cf

        def _exec_inner():
            return self._execute(command)

        try:
            with _cf.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_exec_inner)
                result = future.result(timeout=self.SHELL_COMMAND_TIMEOUT)
            return result.output
        except _cf.TimeoutError:
            log.warning(f"Shell command timed out ({self.SHELL_COMMAND_TIMEOUT}s): {command[:120]}")
            return f"Error: Command timed out after {self.SHELL_COMMAND_TIMEOUT} seconds"
        except Exception as e:
            log.error(f"Command error: {command} -> {e}")
            return f"Error: {str(e)}"
    
    def _execute(self, command: str) -> CommandResult:
        """Execute a parsed command (supports pipes)."""
        # --- Pipe support: split on | and chain results ---
        if " | " in command:
            return self._execute_pipeline(command)

        # Handle redirects
        redirect = None
        append = False
        
        if " >> " in command:
            parts = command.split(" >> ", 1)
            command = parts[0].strip()
            redirect = parts[1].strip()
            append = True
        elif " > " in command:
            parts = command.split(" > ", 1)
            command = parts[0].strip()
            redirect = parts[1].strip()
        
        # Tokenize
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return CommandResult(False, f"Parse error: {e}")
        
        if not tokens:
            return CommandResult(True, "")
        
        cmd = tokens[0].lower()
        args = tokens[1:]
        
        # Check if blocked
        if cmd in self.BLOCKED_COMMANDS:
            return CommandResult(False, f"Error: '{cmd}' is blocked for security reasons")
        
        # Dispatch to handler
        handlers = {
            "ls": self._cmd_ls,
            "cd": self._cmd_cd,
            "pwd": self._cmd_pwd,
            "cat": self._cmd_cat,
            "readfile": self._cmd_readfile,
            "head": self._cmd_head,
            "tail": self._cmd_tail,
            "grep": self._cmd_grep,
            "find": self._cmd_find,
            "mkdir": self._cmd_mkdir,
            "touch": self._cmd_touch,
            "echo": lambda a: self._cmd_echo(a, redirect, append),
            "semgrep": self._cmd_semgrep,
            "tree": self._cmd_tree,
            "wc": self._cmd_wc,
            "sed": self._cmd_sed,
            "stat": self._cmd_stat,
            "diff": self._cmd_diff,
            "get_secret": self._cmd_get_secret,
            "help": self._cmd_help,
            # --- System Info ---
            "date": self._cmd_date,
            "whoami": self._cmd_whoami,
            "hostname": self._cmd_hostname,
            "uname": self._cmd_uname,
            "uptime": self._cmd_uptime,
            "id": self._cmd_id,
            # --- Environment / Config ---
            "env": self._cmd_env,
            "printenv": self._cmd_env,
            "which": self._cmd_which,
            "type": self._cmd_which,
            # --- Text Processing ---
            "sort": self._cmd_sort,
            "uniq": self._cmd_uniq,
            "cut": self._cmd_cut,
            "tr": self._cmd_tr,
            "awk": self._cmd_awk,
            "rev": self._cmd_rev,
            "tac": self._cmd_tac,
            "paste": self._cmd_paste,
            "nl": self._cmd_nl,
            "column": self._cmd_column,
            "fold": self._cmd_fold,
            "expand": self._cmd_expand,
            "unexpand": self._cmd_unexpand,
            # --- File / Disk Info ---
            "du": self._cmd_du,
            "df": self._cmd_df,
            "file": self._cmd_file,
            "sha256sum": self._cmd_sha256sum,
            "basename": self._cmd_basename,
            "dirname": self._cmd_dirname,
            "realpath": self._cmd_realpath,
            # --- Data / Math ---
            "expr": self._cmd_expr,
            "seq": self._cmd_seq,
            "true": self._cmd_true,
            "false": self._cmd_false,
            # --- Networking ---
            "ping": self._cmd_ping,
            "nslookup": self._cmd_nslookup,
            "curl": self._cmd_curl,
        }

        handler = handlers.get(cmd)
        if not handler:
            return CommandResult(False, f"Unknown command: {cmd}. Type 'help' for available commands.")
        
        result = handler(args)
        
        # Handle redirect for non-echo commands
        if redirect and cmd != "echo":
            return self._write_redirect(result.output, redirect, append)
        
        return result

    def _execute_pipeline(self, command: str) -> CommandResult:
        """Execute a pipeline of commands connected by |.

        Only the *last* command in the pipeline may use redirects.
        Intermediate results are fed as stdin-like input: for ``head``
        and ``tail`` the piped text is used directly; for ``grep`` the
        piped text is searched line-by-line.
        """
        segments = [s.strip() for s in command.split(" | ")]
        if len(segments) > 5:
            return CommandResult(False, "Pipeline too long (max 5 stages)")

        result = self._execute(segments[0])
        if not result.success:
            return result

        for seg in segments[1:]:
            # Parse the next command with its args
            try:
                tokens = shlex.split(seg)
            except ValueError as e:
                return CommandResult(False, f"Parse error in pipe: {e}")
            if not tokens:
                continue

            piped_cmd = tokens[0].lower()
            piped_args = tokens[1:]

            if piped_cmd == "head":
                n = 10
                for j, a in enumerate(piped_args):
                    if a == "-n" and j + 1 < len(piped_args):
                        try: n = int(piped_args[j + 1])
                        except ValueError: pass
                    elif a.startswith("-") and a[1:].isdigit():
                        n = int(a[1:])
                lines = result.output.splitlines()
                result = CommandResult(True, "\n".join(lines[:n]))
            elif piped_cmd == "tail":
                n = 10
                for j, a in enumerate(piped_args):
                    if a == "-n" and j + 1 < len(piped_args):
                        try: n = int(piped_args[j + 1])
                        except ValueError: pass
                    elif a.startswith("-") and a[1:].isdigit():
                        n = int(a[1:])
                lines = result.output.splitlines()
                result = CommandResult(True, "\n".join(lines[-n:]))
            elif piped_cmd == "grep":
                # Parse grep flags from piped args
                ignore_case = "-i" in piped_args
                show_line_nums = "-n" in piped_args
                invert = "-v" in piped_args
                pattern = None
                for a in piped_args:
                    if not a.startswith("-"):
                        pattern = a
                        break
                if not pattern:
                    return CommandResult(False, "grep: missing pattern in pipe")
                flags = re.IGNORECASE if ignore_case else 0
                try:
                    regex = re.compile(pattern, flags)
                except re.error as e:
                    return CommandResult(False, f"grep: invalid pattern: {e}")
                matched = []
                for i, line in enumerate(result.output.splitlines(), 1):
                    hit = bool(regex.search(line))
                    if hit != invert:
                        prefix = f"{i}: " if show_line_nums else ""
                        matched.append(f"{prefix}{line}")
                result = CommandResult(True, "\n".join(matched) if matched else f"No matches for '{pattern}'")
            elif piped_cmd == "wc":
                text = result.output
                lc = len(text.splitlines())
                wc = len(text.split())
                cc = len(text)
                show_l = "-l" in piped_args
                show_w = "-w" in piped_args
                show_c = "-c" in piped_args
                if not (show_l or show_w or show_c):
                    show_l = show_w = show_c = True
                parts = []
                if show_l: parts.append(str(lc))
                if show_w: parts.append(str(wc))
                if show_c: parts.append(str(cc))
                result = CommandResult(True, " ".join(parts))
            else:
                # ---- Generic pipe handler for text-processing commands ----
                # These commands accept input via their _get_input_text helper
                # but in a pipe context we inject the previous output as a
                # temporary file.  Simpler approach: write to a temp in-memory
                # path and let the handler read it, OR handle inline.
                _pipe_text_cmds = {
                    "sort", "uniq", "cut", "tr", "awk", "rev", "tac",
                    "nl", "column", "fold", "expand", "unexpand",
                }
                if piped_cmd in _pipe_text_cmds:
                    # Inject piped text: write to a temp file in session workspace
                    import tempfile
                    _tmp_dir = self._resolve_path("/session/workspace")
                    _tmp_dir.mkdir(parents=True, exist_ok=True)
                    _tmp_path = _tmp_dir / ".pipe_tmp"
                    try:
                        _tmp_path.write_text(result.output, encoding="utf-8")
                        handler = getattr(self, f"_cmd_{piped_cmd}", None)
                        if handler:
                            vpath = self._to_virtual_path(_tmp_path)
                            result = handler(piped_args + [vpath])
                        else:
                            result = CommandResult(False, f"Pipe: handler not found for '{piped_cmd}'")
                    finally:
                        try:
                            _tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                else:
                    return CommandResult(False, f"Pipe: '{piped_cmd}' cannot receive piped input. Supported: head, tail, grep, wc, sort, uniq, cut, tr, awk, rev, tac, nl, column, fold, expand, unexpand")

        return result
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve a virtual path to real path using ``_mount_points``."""
        path = path.strip()
        
        # Handle empty or current
        if not path or path == ".":
            return self._resolve_cwd()
        
        # Normalize path
        if path.startswith("/"):
            virtual = path
        else:
            if self.cwd == "/":
                virtual = "/" + path
            else:
                virtual = self.cwd + "/" + path
        
        # Clean up path
        parts = [p for p in virtual.split("/") if p and p != "."]
        clean_path = "/" + "/".join(parts)
        
        if clean_path == "/":
            return self.shell_root
        
        # Walk mount points (single source of truth).
        # Mount prefixes are stored lowercase (see additional_paths sanitization),
        # so we compare case-insensitively on the *mount name* only. The tail
        # (sub_path) keeps its original casing so filenames stay case-correct
        # on case-sensitive filesystems (Linux).
        clean_lower = clean_path.lower()
        for prefix, real_root, _readonly in self._mount_points:
            prefix_lower = prefix.lower()
            if clean_lower == prefix_lower or clean_lower.startswith(prefix_lower + "/"):
                sub_path = clean_path[len(prefix_lower):].lstrip("/")
                if sub_path:
                    return real_root / sub_path
                return real_root
        
        # Default: map to shell_root (for any other paths)
        return self.shell_root / clean_path.lstrip("/")
    
    def _resolve_cwd(self) -> Path:
        """Resolve current working directory."""
        return self._resolve_path(self.cwd)
    
    def _to_virtual_path(self, real_path: Path) -> str:
        """Convert real path to virtual path using ``_mount_points``."""
        resolved = real_path.resolve()
        
        for prefix, real_root, _readonly in self._mount_points:
            try:
                rel = resolved.relative_to(real_root)
                rel_str = str(rel).replace("\\", "/")
                if rel_str == "." or rel_str == "":
                    return prefix
                return prefix + "/" + rel_str
            except ValueError:
                continue
        
        # Fallback: check shell_root (general)
        try:
            rel = resolved.relative_to(self.shell_root)
            rel_str = str(rel).replace("\\", "/")
            if rel_str == "." or rel_str == "":
                return "/"
            return "/" + rel_str
        except ValueError:
            return str(real_path)
    
    def _is_inside_sandbox(self, path: Path) -> bool:
        """Check if path is inside any of the allowed sandboxes (derived from ``_mount_points``)."""
        try:
            resolved_path = path.resolve()
            for _prefix, real_root, _readonly in self._mount_points:
                try:
                    resolved_path.relative_to(real_root.resolve())
                    return True
                except ValueError:
                    continue
            # Also check the shell_root itself (for session-level files outside /session/)
            try:
                resolved_path.relative_to(self.shell_root.resolve())
                return True
            except ValueError:
                pass
            return False
        except Exception as exc:
            log.debug(f"_is_inside_sandbox: path resolution failed: {exc}")
            return False

    def _is_readonly_path(self, path: Path) -> bool:
        """Check if path is inside a read-only sandbox (derived from ``_mount_points``)."""
        try:
            resolved_path = path.resolve()
            for _prefix, real_root, readonly in self._mount_points:
                if not readonly:
                    continue
                try:
                    resolved_path.relative_to(real_root.resolve())
                    return True
                except ValueError:
                    continue
            return False
        except Exception as exc:
            log.debug(f"_is_readonly_path: path resolution failed: {exc}")
            return False
    
    def _index_file(self, file_path: Path):
        """Index a file for semantic search."""
        if not self.vector_store:
            return
        
        # Index files in /user/, /agent/, and /session/
        virtual_path = self._to_virtual_path(file_path)
        if not (virtual_path.startswith("/user/") or 
                virtual_path.startswith("/agent/") or 
                virtual_path.startswith("/session/")):
            return
        
        try:
            content = file_path.read_text(encoding="utf-8")
            if content.strip():
                self.vector_store.upsert(virtual_path, content)
                log.debug(f"Indexed: {virtual_path}")
        except Exception as e:
            log.warning(f"Failed to index {virtual_path}: {e}")
    
    # =========================================================================
    # CONVERSATION HISTORY METHODS (Virtual /conversations directory)
    # =========================================================================
    
    def _load_conversations(self) -> Dict[str, Any]:
        """Load conversations from chat_logs/conversations.json."""
        if not self.chat_logs_path or not self.chat_logs_path.exists():
            return {}
        
        try:
            import json
            content = self.chat_logs_path.read_text(encoding="utf-8").strip()
            if not content:
                return {}
            return json.loads(content)
        except Exception as e:
            log.warning(f"Failed to load conversations: {e}")
            return {}
    
    def _get_session_messages(self) -> List[Dict[str, Any]]:
        """Get messages for current agent_id and session_id."""
        all_convs = self._load_conversations()
        
        if not all_convs:
            return []
        
        if self.agent_id not in all_convs:
            return []
        
        agent_sessions = all_convs[self.agent_id]
        
        if self.session_id not in agent_sessions:
            return []
        
        session_data = agent_sessions[self.session_id]
        return session_data.get("messages", [])
    
    def _get_session_summaries(self) -> List[Dict[str, Any]]:
        """Get stored summaries for current agent_id and session_id."""
        all_convs = self._load_conversations()
        
        if not all_convs:
            return []
        
        if self.agent_id not in all_convs:
            return []
        
        agent_sessions = all_convs[self.agent_id]
        
        if self.session_id not in agent_sessions:
            return []
        
        session_data = agent_sessions[self.session_id]
        return session_data.get("summaries", [])

    def _generate_conversation_summary(self) -> str:
        """
        Generate a summary of the conversation history.
        ONLY shows AI-generated summaries, NOT raw messages.
        If no summaries exist, instructs user to check full.md instead.
        """
        summaries = self._get_session_summaries()
        messages = self._get_session_messages()
        
        # Build summary header
        lines = [
            "# Conversation Summary",
            ""
        ]
        
        # If no summaries exist
        if not summaries:
            lines.extend([
                "No AI-generated summaries available yet.",
                "",
                f"**Total messages in session:** {len(messages)}",
                "",
                "To see the full conversation history, use:",
                "```",
                "cat /session/conversations/full.md",
                "```",
                "",
                "Or to see recent messages:",
                "```",
                "tail -n 50 /session/conversations/full.md",
                "```"
            ])
            return "\n".join(lines)
        
        # Display AI-generated summaries only
        lines.extend([
            f"**Total Summaries:** {len(summaries)}",
            f"**Total Messages:** {len(messages)}",
            "",
            "---",
            ""
        ])
        
        for i, summary_entry in enumerate(summaries, 1):
            summary_text = summary_entry.get("summary", "No summary text")
            summarized_at = summary_entry.get("summarized_at", "")[:19]
            message_count = summary_entry.get("message_count", 0)
            time_range = summary_entry.get("time_range", {})
            from_time = time_range.get("from", "")[:19]
            to_time = time_range.get("to", "")[:19]
            
            lines.append(f"## Summary {i}")
            lines.append(f"**Created:** {summarized_at}")
            lines.append(f"**Messages Covered:** {message_count} ({from_time} to {to_time})")
            lines.append("")
            lines.append(summary_text)
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Footer with hint
        lines.extend([
            "",
            "*For full conversation details, use: `cat /session/conversations/full.md`*"
        ])
        
        return "\n".join(lines)
    
    def _generate_full_conversation(self) -> str:
        """Generate full conversation history."""
        messages = self._get_session_messages()
        
        if not messages:
            return "# Full Conversation History\n\nNo conversation history found for this session."
        
        lines = [
            "# Full Conversation History",
            f"\n**Agent:** {self.agent_id}",
            f"**Session:** {self.session_id}",
            f"**Total Messages:** {len(messages)}",
            "",
            "---",
            ""
        ]
        
        for i, msg in enumerate(messages, 1):
            human = msg.get("human_message", "")
            ai = msg.get("ai_message", "")
            time = msg.get("end_timestamp", "")
            
            lines.append(f"## Message {i}")
            lines.append(f"**Time:** {time}")
            lines.append("")
            lines.append(f"**User:**")
            lines.append(f"```")
            lines.append(human)
            lines.append(f"```")
            lines.append("")
            lines.append(f"**Assistant:**")
            lines.append(f"```")
            lines.append(ai)
            lines.append(f"```")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _search_conversations(self, pattern: str, case_insensitive: bool = False) -> str:
        """Search conversations for a pattern."""
        messages = self._get_session_messages()
        
        if not messages:
            return "No conversation history to search."
        
        if case_insensitive:
            pattern = pattern.lower()
        
        matches = []
        for i, msg in enumerate(messages, 1):
            human = msg.get("human_message", "")
            ai = msg.get("ai_message", "")
            time = msg.get("end_timestamp", "")[:19]
            
            human_check = human.lower() if case_insensitive else human
            ai_check = ai.lower() if case_insensitive else ai
            
            if pattern in human_check:
                # Find the matching line
                for line_num, line in enumerate(human.split("\n"), 1):
                    line_check = line.lower() if case_insensitive else line
                    if pattern in line_check:
                        matches.append(f"/session/conversations/full.md:msg{i}:user:{line_num}: {line.strip()[:100]}")
            
            if pattern in ai_check:
                for line_num, line in enumerate(ai.split("\n"), 1):
                    line_check = line.lower() if case_insensitive else line
                    if pattern in line_check:
                        matches.append(f"/session/conversations/full.md:msg{i}:ai:{line_num}: {line.strip()[:100]}")
        
        if not matches:
            return f"No matches found for '{pattern}' in conversations."
        
        if len(matches) > self.MAX_GREP_RESULTS:
            matches = matches[:self.MAX_GREP_RESULTS]
            matches.append(f"... truncated ({self.MAX_GREP_RESULTS} matches shown)")
        
        return "\n".join(matches)
    
    def _is_virtual_path(self, path: str) -> bool:
        """Check if path is in a virtual directory."""
        # Normalize path
        path = path.rstrip("/")
        return path.startswith("/session/conversations") or path == "/session/conversations"
    
    def _handle_virtual_cat(self, path: str) -> CommandResult:
        """Handle cat for virtual files."""
        # Normalize path - handle both /conversations and /session/conversations
        path = path.rstrip("/")
        if path in ["/session/conversations/summary.md", "/conversations/summary.md"]:
            return CommandResult(True, self._generate_conversation_summary())
        elif path in ["/session/conversations/full.md", "/conversations/full.md"]:
            return CommandResult(True, self._generate_full_conversation())
        else:
            return CommandResult(False, f"cat: {path}: No such file (valid: summary.md, full.md)")
    
    def _handle_virtual_ls(self, path: str, long_format: bool = False) -> CommandResult:
        """Handle ls for virtual directories."""
        path = path.rstrip("/")
        if path in ["/session/conversations", "/conversations"]:
            if long_format:
                lines = [
                    "total 2",
                    "-r--r--r--  1 agent  agent  0  Jan 13 00:00 summary.md",
                    "-r--r--r--  1 agent  agent  0  Jan 13 00:00 full.md"
                ]
            else:
                lines = ["summary.md", "full.md"]
            return CommandResult(True, "\n".join(lines))
        else:
            return CommandResult(False, f"ls: {path}: No such directory")
    
    # =========================================================================
    # COMMAND IMPLEMENTATIONS
    # =========================================================================
    
    def _cmd_ls(self, args: List[str]) -> CommandResult:
        """List directory contents."""
        show_all = "-a" in args or "-la" in args or "-al" in args
        long_format = "-l" in args or "-la" in args or "-al" in args
        
        # Get path argument
        path_arg = None
        for a in args:
            if not a.startswith("-"):
                path_arg = a
                break
        
        # Resolve the path
        if path_arg:
            resolved = path_arg if path_arg.startswith("/") else f"{self.cwd.rstrip('/')}/{path_arg}"
        else:
            resolved = self.cwd
        
        # Normalize resolved path
        parts = [p for p in resolved.split("/") if p and p != "."]
        resolved = "/" + "/".join(parts) if parts else "/"
        
        # Check for virtual directories
        if self._is_virtual_path(resolved):
            return self._handle_virtual_ls(resolved, long_format)
        
        # Special handling for root - show ALL virtual mount points
        if resolved == "/":
            ts = datetime.now().strftime('%Y-%m-%d %H:%M')
            if long_format:
                lines = []
                for prefix, _real_root, readonly in self._mount_points:
                    name = prefix.lstrip("/") + "/"
                    ro_tag = "(read-only)" if readonly else ""
                    lines.append(f"drw-r--r--        0 {ts} {name:<22s} # {ro_tag}")
            else:
                names = [prefix.lstrip("/") + "/" for prefix, _, _ in self._mount_points]
                lines = ["  ".join(names)]
            return CommandResult(True, "\n".join(lines) if long_format else lines[0])
        
        target = self._resolve_path(path_arg or ".")
        
        if not target.exists():
            return CommandResult(False, f"ls: {path_arg or '.'}: No such directory")
        
        if not target.is_dir():
            return CommandResult(True, self._to_virtual_path(target))
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "ls: Access denied")
        
        try:
            items = list(target.iterdir())
            
            # Filter hidden files
            if not show_all:
                items = [i for i in items if not i.name.startswith(".")]
            # Always filter system-hidden files (e.g. _path_mapping.json)
            items = [i for i in items if not self._is_hidden_file(i)]

            items = sorted(items, key=lambda x: (not x.is_dir(), x.name.lower()))
            items = items[:self.MAX_LIST_ITEMS]
            
            # Check if we're at /session - add virtual conversations directory
            is_at_session = resolved == "/session"
            
            if long_format:
                lines = []
                # Add virtual conversations directory if at /session
                if is_at_session:
                    lines.append(f"drw-r--r--        0 {datetime.now().strftime('%Y-%m-%d %H:%M')} conversations/  [virtual]")
                for item in items:
                    try:
                        stat = item.stat()
                        is_dir = "d" if item.is_dir() else "-"
                        size = stat.st_size
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                        name = item.name + "/" if item.is_dir() else item.name
                        lines.append(f"{is_dir}rw-r--r-- {size:>8} {mtime} {name}")
                    except Exception as exc:
                        log.debug(f"ls: could not stat {item.name}: {exc}")
                        lines.append(f"?--------- ? ? {item.name}")
                return CommandResult(True, "\n".join(lines))
            else:
                names = []
                # Add virtual conversations directory if at /session
                if is_at_session:
                    names.append("conversations/")
                for item in items:
                    name = item.name + "/" if item.is_dir() else item.name
                    names.append(name)
                return CommandResult(True, "  ".join(names))
                
        except PermissionError:
            return CommandResult(False, "ls: Permission denied")
    
    def _cmd_cd(self, args: List[str]) -> CommandResult:
        """Change directory."""
        if not args:
            self.cwd = "/"
            return CommandResult(True, "")
        
        path = args[0]
        
        # Handle virtual directories - /session/conversations
        if path in ["/session/conversations", "session/conversations", "conversations"]:
            # If just "conversations", only valid from /session
            if path == "conversations" and self.cwd != "/session":
                return CommandResult(False, f"cd: {path}: No such directory")
            self.cwd = "/session/conversations"
            return CommandResult(True, "")
        
        # Build absolute virtual path
        if path.startswith("/"):
            virtual = path
        else:
            if self.cwd == "/":
                virtual = "/" + path
            else:
                virtual = self.cwd.rstrip("/") + "/" + path
        
        # Normalize
        parts = [p for p in virtual.split("/") if p and p != "."]
        virtual = "/" + "/".join(parts) if parts else "/"
        
        # Handle special virtual paths
        if virtual in ["/user", "/agent", "/session"]:
            self.cwd = virtual
            return CommandResult(True, "")
        
        target = self._resolve_path(path)
        
        if not target.exists():
            return CommandResult(False, f"cd: {path}: No such directory")
        
        if not target.is_dir():
            return CommandResult(False, f"cd: {path}: Not a directory")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "cd: Access denied")
        
        self.cwd = self._to_virtual_path(target)
        return CommandResult(True, "")
    
    def _cmd_pwd(self, args: List[str]) -> CommandResult:
        """Print working directory."""
        return CommandResult(True, self.cwd)
    
    def _cmd_cat(self, args: List[str]) -> CommandResult:
        """Concatenate and print files. Supports -n for line numbers."""
        if not args:
            return CommandResult(False, "cat: missing file operand")

        show_line_nums = "-n" in args
        file_args = [a for a in args if not a.startswith("-")]

        if not file_args:
            return CommandResult(False, "cat: missing file operand")

        outputs = []
        for path_arg in file_args:
            # Resolve the path
            if path_arg.startswith("/"):
                resolved_virtual = path_arg
            else:
                resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
            
            # Check for virtual files (conversations)
            if self._is_virtual_path(resolved_virtual):
                result = self._handle_virtual_cat(resolved_virtual)
                content = result.output
                if show_line_nums:
                    numbered = [f"{i:>4}  {line}" for i, line in enumerate(content.splitlines(), 1)]
                    content = "\n".join(numbered)
                outputs.append(content)
                continue
            
            target = self._resolve_path(path_arg)
            
            if not target.exists():
                outputs.append(f"cat: {path_arg}: No such file")
                continue
            
            if target.is_dir():
                outputs.append(f"cat: {path_arg}: Is a directory")
                continue
            
            if not self._is_inside_sandbox(target):
                outputs.append(f"cat: {path_arg}: Access denied")
                continue

            if self._is_hidden_file(target):
                outputs.append(f"cat: {path_arg}: No such file")
                continue

            # Detect binary / complex files and redirect to execute_python_code
            if self._is_binary_file(target):
                outputs.append(self._binary_redirect_message(path_arg, resolved_virtual))
                continue
            
            try:
                content = target.read_text(encoding="utf-8")
                if len(content) > self.MAX_READ_BYTES:
                    content = content[:self.MAX_READ_BYTES]
                    content += f"\n... [truncated at {self.MAX_READ_BYTES} bytes]"
                if show_line_nums:
                    numbered = [f"{i:>4}  {line}" for i, line in enumerate(content.splitlines(), 1)]
                    content = "\n".join(numbered)
                outputs.append(content)
            except Exception as e:
                outputs.append(f"cat: {path_arg}: {e}")
        
        return CommandResult(True, "\n".join(outputs))
    
    def _cmd_head(self, args: List[str]) -> CommandResult:
        """Print first lines of file."""
        num_lines = 10
        path_arg = None
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    num_lines = int(args[i + 1])
                    i += 2
                    continue
                except (ValueError, TypeError):
                    pass
            elif args[i].startswith("-") and args[i][1:].isdigit():
                num_lines = int(args[i][1:])
            else:
                path_arg = args[i]
            i += 1
        
        if not path_arg:
            return CommandResult(False, "head: missing file operand")
        
        # Resolve the virtual path for conversations
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        
        # Check for virtual files (conversations)
        if self._is_virtual_path(resolved_virtual):
            result = self._handle_virtual_cat(resolved_virtual)
            if not result.success:
                return result
            lines = result.output.splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[:num_lines]))
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"head: {path_arg}: No such file")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"head: Access denied")

        # Detect binary / complex files and redirect to execute_python_code
        if self._is_binary_file(target):
            vpath = path_arg if path_arg.startswith("/") else resolved_virtual
            return CommandResult(False, self._binary_redirect_message(path_arg, vpath))

        try:
            lines = target.read_text(encoding="utf-8").splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[:num_lines]))
        except Exception as e:
            return CommandResult(False, f"head: {e}")
    
    def _cmd_tail(self, args: List[str]) -> CommandResult:
        """Print last lines of file."""
        num_lines = 10
        path_arg = None
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    num_lines = int(args[i + 1])
                    i += 2
                    continue
                except (ValueError, TypeError):
                    pass
            elif args[i].startswith("-") and args[i][1:].isdigit():
                num_lines = int(args[i][1:])
            else:
                path_arg = args[i]
            i += 1
        
        if not path_arg:
            return CommandResult(False, "tail: missing file operand")
        
        # Resolve the virtual path for conversations
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        
        # Check for virtual files (conversations)
        if self._is_virtual_path(resolved_virtual):
            result = self._handle_virtual_cat(resolved_virtual)
            if not result.success:
                return result
            lines = result.output.splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[-num_lines:]))
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"tail: {path_arg}: No such file")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"tail: Access denied")

        # Detect binary / complex files and redirect to execute_python_code
        if self._is_binary_file(target):
            vpath = path_arg if path_arg.startswith("/") else resolved_virtual
            return CommandResult(False, self._binary_redirect_message(path_arg, vpath))

        try:
            lines = target.read_text(encoding="utf-8").splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[-num_lines:]))
        except Exception as e:
            return CommandResult(False, f"tail: {e}")

    # ---- readfile: unified reader for binary / complex files ----

    # Maximum file size that readfile will process (50 MB)
    MAX_READFILE_BYTES = 50 * 1024 * 1024

    def _cmd_readfile(self, args: List[str]) -> CommandResult:
        """Read any file — including PDF, Excel, DOCX, PPTX, CSV, images, etc.

        Usage:  readfile <path>
                readfile <filename>   (auto-discovers across all mounts)

        Unlike ``cat`` (text-only), ``readfile`` automatically detects the file
        format and extracts human-readable text.  Text files are returned as-is.

        If the given path does not exist, ``readfile`` searches all mount points
        for a file with a matching name.  If exactly one match is found it is
        read automatically; if multiple matches exist they are listed so the
        agent can pick the right one.
        """
        if not args:
            return CommandResult(False, "readfile: missing file operand")

        path_arg = args[0]

        # Resolve virtual → real
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"

        target = self._resolve_path(path_arg)

        # --- Auto-discovery: if not found, search all mounts by filename ---
        if not target.exists():
            found = self._find_file_across_mounts(path_arg)
            if len(found) == 0:
                return CommandResult(False, f"readfile: {path_arg}: No such file")
            if len(found) == 1:
                resolved_virtual, target = found[0]
            else:
                # Multiple matches — list them
                listing = "\n".join(f"  {vp}" for vp, _rp in found)
                return CommandResult(
                    False,
                    f"readfile: '{path_arg}' found in multiple locations. "
                    f"Specify the full path:\n{listing}",
                )

        if target.is_dir():
            return CommandResult(False, f"readfile: {path_arg}: Is a directory")
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"readfile: {path_arg}: Access denied")
        if self._is_hidden_file(target):
            return CommandResult(False, f"readfile: {path_arg}: No such file")

        # Size guard
        fsize = target.stat().st_size
        if fsize > self.MAX_READFILE_BYTES:
            mb = round(fsize / (1024 * 1024), 1)
            cap = round(self.MAX_READFILE_BYTES / (1024 * 1024), 1)
            return CommandResult(
                False,
                f"readfile: {path_arg}: File too large ({mb} MB, limit {cap} MB)",
            )

        ext = target.suffix.lower()
        real = str(target)

        try:
            content = self._readfile_by_ext(real, ext)
            # H3: Truncate large output to keep LLM context manageable
            if len(content) > self.MAX_READFILE_OUTPUT_CHARS:
                content = (
                    content[: self.MAX_READFILE_OUTPUT_CHARS]
                    + f"\n\n... [output truncated at {self.MAX_READFILE_OUTPUT_CHARS:,} chars]"
                )
            return CommandResult(True, content)
        except Exception as e:
            # Sanitise: never leak real filesystem paths
            msg = str(e)
            for _prefix, real_root, _ro in self._mount_points:
                rp = str(real_root)
                if rp in msg:
                    msg = msg.replace(rp, _prefix)
            return CommandResult(False, f"readfile: {path_arg}: {msg}")

    # ---- per-format readers (used by _cmd_readfile) ----

    @staticmethod
    def _readfile_by_ext(real: str, ext: str) -> str:  # noqa: C901
        """Dispatch file reading by extension and return extracted text."""
        import json as _json

        # ---- PDF ----
        if ext == ".pdf":
            try:
                import pdfplumber
                parts = []
                with pdfplumber.open(real) as pdf:
                    for i, page in enumerate(pdf.pages):
                        t = page.extract_text()
                        if t:
                            parts.append(f"--- Page {i+1} ---\n{t}")
                return "\n\n".join(parts) if parts else "(PDF contains no extractable text)"
            except ImportError:
                pass
            try:
                import PyPDF2
                parts = []
                with open(real, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for i, page in enumerate(reader.pages):
                        t = page.extract_text()
                        if t:
                            parts.append(f"--- Page {i+1} ---\n{t}")
                return "\n\n".join(parts) if parts else "(PDF contains no extractable text)"
            except ImportError:
                return "Error: Install pdfplumber or PyPDF2 to read PDF files."

        # ---- Excel ----
        if ext in (".xlsx", ".xls"):
            try:
                import pandas as pd
                xls = pd.ExcelFile(real)
                parts = []
                for sheet in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet)
                    parts.append(f"--- Sheet: {sheet} ---\n{df.to_string(index=False)}")
                return "\n\n".join(parts)
            except ImportError:
                return "Error: Install pandas and openpyxl to read Excel files."

        # ---- CSV ----
        if ext == ".csv":
            try:
                import pandas as pd
                df = pd.read_csv(real)
                return df.to_string(index=False)
            except ImportError:
                import csv as _csv
                with open(real, "r", encoding="utf-8") as f:
                    rows = list(_csv.reader(f))
                return "\n".join(",".join(row) for row in rows)

        # ---- Word DOCX ----
        if ext == ".docx":
            try:
                from docx import Document
                doc = Document(real)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables_text = []
                for table in doc.tables:
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        tables_text.append(" | ".join(cells))
                result = "\n".join(paragraphs)
                if tables_text:
                    result += "\n\n--- Tables ---\n" + "\n".join(tables_text)
                return result if result.strip() else "(DOCX contains no extractable text)"
            except ImportError:
                return "Error: Install python-docx to read DOCX files."

        # ---- PowerPoint PPTX ----
        if ext == ".pptx":
            try:
                from pptx import Presentation
                prs = Presentation(real)
                parts = []
                for i, slide in enumerate(prs.slides):
                    texts = []
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            texts.append(shape.text)
                    if texts:
                        parts.append(f"--- Slide {i+1} ---\n" + "\n".join(texts))
                return "\n\n".join(parts) if parts else "(PPTX contains no extractable text)"
            except ImportError:
                return "Error: Install python-pptx to read PPTX files."

        # ---- JSON ----
        if ext == ".json":
            with open(real, "r", encoding="utf-8") as f:
                data = _json.load(f)
            return _json.dumps(data, indent=2, ensure_ascii=False)

        # ---- YAML ----
        if ext in (".yaml", ".yml"):
            try:
                import yaml
                with open(real, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                return _json.dumps(data, indent=2, ensure_ascii=False) if data else ""
            except ImportError:
                with open(real, "r", encoding="utf-8") as f:
                    return f.read()

        # ---- Images ----
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".svg"):
            import os as _os
            if ext == ".svg":
                with open(real, "r", encoding="utf-8") as f:
                    return f.read()
            import base64
            size = _os.path.getsize(real)
            with open(real, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"[Image: {_os.path.basename(real)}, {size} bytes]\nbase64:{b64}"

        # ---- Parquet ----
        if ext == ".parquet":
            try:
                import pandas as pd
                df = pd.read_parquet(real)
                return df.to_string(index=False)
            except ImportError:
                return "Error: Install pandas and pyarrow to read Parquet files."

        # ---- Generic text (try multiple encodings) ----
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(real, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue

        # ---- Binary fallback ----
        import base64 as _b64
        with open(real, "rb") as f:
            raw = f.read()
        import os as _os
        return (
            f"[Binary file: {_os.path.basename(real)}, {len(raw)} bytes]\n"
            f"base64:{_b64.b64encode(raw).decode('ascii')}"
        )

    # ---- Helpers for root-level searches across virtual mounts ----

    # ------------------------------------------------------------------
    # Depth-bounded rglob — prevents runaway scans on large trees (H1)
    # ------------------------------------------------------------------
    @staticmethod
    def _bounded_rglob(root: Path, pattern: str, *,
                       max_depth: int = 8, max_entries: int = 5_000):
        """Yield paths matching *pattern* under *root*, limited by depth and count."""
        visited = 0
        for dirpath, dirnames, filenames in os.walk(root):
            depth = Path(dirpath).relative_to(root).parts
            if len(depth) >= max_depth:
                dirnames.clear()       # stop descending
                continue
            for name in filenames:
                full = Path(dirpath) / name
                if fnmatch.fnmatch(name, pattern):
                    yield full
                visited += 1
                if visited >= max_entries:
                    return

    def _find_file_across_mounts(self, filename: str) -> list:
        """Search all mount points for a file matching *filename*.

        *filename* can be a bare name (``report.pdf``) or contain glob
        characters (``*.xlsx``).  Only files (not directories) are returned.

        Returns a list of ``(virtual_path, real_Path)`` tuples, capped at 20
        results to avoid runaway scans.
        """
        results: list = []
        bare = Path(filename).name  # strip any leading dirs
        use_glob = "*" in bare or "?" in bare
        glob_pattern = bare if use_glob else "*"

        for prefix, real_root, _ro in self._mount_points:
            if not real_root.is_dir():
                continue
            try:
                for p in self._bounded_rglob(
                    real_root, glob_pattern,
                    max_depth=self.MAX_RGLOB_DEPTH,
                    max_entries=self.MAX_RGLOB_ENTRIES,
                ):
                    if not p.is_file():
                        continue
                    if self._is_hidden_file(p):
                        continue
                    # Symlink guard: skip files whose resolved target
                    # escapes the mount root (prevents symlink-based
                    # sandbox escape in auto-discovery results).
                    try:
                        if not p.resolve().is_relative_to(real_root.resolve()):
                            continue
                    except (OSError, ValueError):
                        continue
                    if use_glob or p.name.lower() == bare.lower():
                        try:
                            rel = p.relative_to(real_root)
                            vpath = prefix + "/" + str(rel).replace("\\", "/")
                            results.append((vpath, p.resolve()))
                        except ValueError:
                            continue
                    if len(results) >= 20:
                        return results
            except Exception:
                continue
        return results

    def _all_virtual_roots(self) -> list:
        """Return (virtual_prefix, real_path) for every virtual mount point.

        Used by grep / find / semgrep so that a root-level search (path ``/``)
        correctly traverses *all* disjoint real directories.

        Derived from ``_mount_points`` — no separate maintenance needed.
        """
        return [(prefix, real_root) for prefix, real_root, _ro in self._mount_points]

    def _cmd_grep(self, args: List[str]) -> CommandResult:
        """Search for pattern in files. Supports -A/-B/-C context, -e multi-pattern."""
        if len(args) < 1:
            return CommandResult(False, "grep: missing pattern")
        
        # Parse options
        recursive = False
        ignore_case = False
        show_line_nums = False
        list_files_only = False
        invert_match = False
        after_ctx = 0
        before_ctx = 0
        patterns: List[str] = []

        i = 0
        path_arg = "."
        while i < len(args):
            a = args[i]
            if a in ("-r", "-R"):
                recursive = True
            elif a == "-i":
                ignore_case = True
            elif a == "-n":
                show_line_nums = True
            elif a in ("-l", "-rl"):
                list_files_only = True
                if a == "-rl":
                    recursive = True
            elif a == "-v":
                invert_match = True
            elif a == "-A" and i + 1 < len(args):
                try: after_ctx = int(args[i + 1])
                except ValueError: pass
                i += 1
            elif a == "-B" and i + 1 < len(args):
                try: before_ctx = int(args[i + 1])
                except ValueError: pass
                i += 1
            elif a == "-C" and i + 1 < len(args):
                try:
                    ctx = int(args[i + 1])
                    after_ctx = before_ctx = ctx
                except ValueError: pass
                i += 1
            elif a == "-e" and i + 1 < len(args):
                patterns.append(args[i + 1])
                i += 1
            # Compound flags like -rn, -rin, -rni, etc.
            elif a.startswith("-") and len(a) > 1 and all(c in "rRinlv" for c in a[1:]):
                for c in a[1:]:
                    if c in ("r", "R"): recursive = True
                    elif c == "i": ignore_case = True
                    elif c == "n": show_line_nums = True
                    elif c == "l": list_files_only = True
                    elif c == "v": invert_match = True
            elif not a.startswith("-"):
                if not patterns:
                    patterns.append(a)
                else:
                    path_arg = a
            i += 1
        
        if not patterns:
            return CommandResult(False, "grep: missing pattern")

        # Combine patterns with alternation
        pattern = "|".join(f"(?:{p})" for p in patterns) if len(patterns) > 1 else patterns[0]
        
        # Resolve the virtual path for special-case checks
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        
        # Normalize
        parts = [p for p in resolved_virtual.split("/") if p and p != "."]
        resolved_virtual = "/" + "/".join(parts) if parts else "/"
        
        # Check if searching in conversations
        if self._is_virtual_path(resolved_virtual) or resolved_virtual == "/conversations":
            conv_results = self._search_conversations(pattern, ignore_case)
            return CommandResult(True, conv_results)
        
        # Compile pattern
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return CommandResult(False, f"grep: invalid pattern: {e}")
        
        results: list = []
        matched_files: set = set()

        def search_file(file_path: Path):
            if self._is_hidden_file(file_path):
                return False
            virtual = self._to_virtual_path(file_path)
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
                # Collect matching line numbers first (for context support)
                match_indices: list = []  # 0-based indices
                for idx, line in enumerate(lines):
                    hit = bool(regex.search(line))
                    if hit != invert_match:
                        match_indices.append(idx)

                if not match_indices:
                    return False

                if list_files_only:
                    if virtual not in matched_files:
                        matched_files.add(virtual)
                        results.append(virtual)
                    return len(results) >= self.MAX_GREP_RESULTS

                # Build output with optional context lines
                has_context = after_ctx > 0 or before_ctx > 0
                shown_lines: set = set()  # avoid duplicates in context
                last_shown = -2  # track separator placement

                for m_idx in match_indices:
                    start = max(0, m_idx - before_ctx)
                    end = min(len(lines) - 1, m_idx + after_ctx)

                    # Separator between non-contiguous groups
                    if has_context and last_shown >= 0 and start > last_shown + 1:
                        results.append("--")

                    for li in range(start, end + 1):
                        if li in shown_lines:
                            continue
                        shown_lines.add(li)
                        last_shown = li
                        lineno = li + 1  # 1-based
                        sep = ":" if li == m_idx else "-"  # match vs context
                        if show_line_nums:
                            results.append(f"{virtual}{sep}{lineno}{sep} {lines[li]}")
                        else:
                            results.append(f"{virtual}{sep} {lines[li]}")

                    if len(results) >= self.MAX_GREP_RESULTS:
                        return True
            except Exception as exc:
                log.debug(f"grep: error reading {file_path}: {exc}")
            return len(results) >= self.MAX_GREP_RESULTS

        def search_dir(target: Path):
            """Recursively (or non-recursively) search a single real dir."""
            if not target.exists() or not self._is_inside_sandbox(target):
                return
            if target.is_file():
                search_file(target)
                return
            if recursive:
                for fp in self._bounded_rglob(
                    target, "*",
                    max_depth=self.MAX_RGLOB_DEPTH,
                    max_entries=self.MAX_RGLOB_ENTRIES,
                ):
                    if fp.is_file() and fp.suffix in self._GREP_EXTENSIONS:
                        if search_file(fp):
                            return
            else:
                for fp in target.iterdir():
                    if fp.is_file():
                        if search_file(fp):
                            return

        # --- Root-level search: fan out across ALL virtual mounts ---
        if resolved_virtual == "/" and recursive:
            for _vprefix, real_root in self._all_virtual_roots():
                if len(results) >= self.MAX_GREP_RESULTS:
                    break
                search_dir(real_root)
        else:
            target = self._resolve_path(path_arg)
            if not target.exists():
                return CommandResult(False, f"grep: {path_arg}: No such file or directory")
            if not self._is_inside_sandbox(target):
                return CommandResult(False, "grep: Access denied")
            search_dir(target)
        
        if not results:
            return CommandResult(True, f"No matches for '{pattern}'")
        
        output = "\n".join(results)
        if len(results) >= self.MAX_GREP_RESULTS:
            output += f"\n... [truncated at {self.MAX_GREP_RESULTS} results]"
        
        return CommandResult(True, output)
    
    def _cmd_find(self, args: List[str]) -> CommandResult:
        """Find files by name. Supports -iname for case-insensitive matching."""
        path_arg = "."
        name_pattern = None
        iname_pattern = None  # case-insensitive variant
        file_type = None
        
        i = 0
        while i < len(args):
            if args[i] == "-name" and i + 1 < len(args):
                name_pattern = args[i + 1]
                i += 2
            elif args[i] == "-iname" and i + 1 < len(args):
                iname_pattern = args[i + 1]
                i += 2
            elif args[i] == "-type" and i + 1 < len(args):
                file_type = args[i + 1]
                i += 2
            elif not args[i].startswith("-"):
                path_arg = args[i]
                i += 1
            else:
                i += 1
        
        # Resolve the virtual path to decide if this is a root-level search
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        parts_v = [p for p in resolved_virtual.split("/") if p and p != "."]
        resolved_virtual = "/" + "/".join(parts_v) if parts_v else "/"

        results = []

        def _scan_dir(real_dir: Path):
            if not real_dir.exists() or not self._is_inside_sandbox(real_dir):
                return
            for item in self._bounded_rglob(
                real_dir, "*",
                max_depth=self.MAX_RGLOB_DEPTH,
                max_entries=self.MAX_RGLOB_ENTRIES,
            ):
                if len(results) >= self.MAX_FIND_RESULTS:
                    break
                if self._is_hidden_file(item):
                    continue
                if file_type == "f" and not item.is_file():
                    continue
                if file_type == "d" and not item.is_dir():
                    continue
                if name_pattern and not fnmatch.fnmatch(item.name, name_pattern):
                    continue
                if iname_pattern and not fnmatch.fnmatch(item.name.lower(), iname_pattern.lower()):
                    continue
                results.append(self._to_virtual_path(item))

        # Root-level find: fan out across all virtual mounts
        if resolved_virtual == "/":
            for _vp, real_root in self._all_virtual_roots():
                if len(results) >= self.MAX_FIND_RESULTS:
                    break
                _scan_dir(real_root)
        else:
            target = self._resolve_path(path_arg)
            if not target.exists():
                return CommandResult(False, f"find: {path_arg}: No such directory")
            if not self._is_inside_sandbox(target):
                return CommandResult(False, "find: Access denied")
            _scan_dir(target)
        
        if not results:
            return CommandResult(True, "No files found")
        
        output = "\n".join(results)
        if len(results) >= self.MAX_FIND_RESULTS:
            output += f"\n... [truncated at {self.MAX_FIND_RESULTS} results]"
        
        return CommandResult(True, output)
    
    def _cmd_mkdir(self, args: List[str]) -> CommandResult:
        """Create directories."""
        if not args:
            return CommandResult(False, "mkdir: missing operand")
        
        parents = "-p" in args
        
        for path_arg in args:
            if path_arg.startswith("-"):
                continue
            
            target = self._resolve_path(path_arg)
            
            if not self._is_inside_sandbox(target):
                return CommandResult(False, f"mkdir: {path_arg}: Access denied")
            
            if self._is_readonly_path(target):
                return CommandResult(False, f"mkdir: {path_arg}: Read-only path")
            
            try:
                if parents:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.mkdir(exist_ok=False)
            except FileExistsError:
                return CommandResult(False, f"mkdir: {path_arg}: File exists")
            except Exception as e:
                return CommandResult(False, f"mkdir: {e}")
        
        return CommandResult(True, "")
    
    def _cmd_touch(self, args: List[str]) -> CommandResult:
        """Create empty files."""
        if not args:
            return CommandResult(False, "touch: missing operand")
        
        for path_arg in args:
            target = self._resolve_path(path_arg)
            
            if not self._is_inside_sandbox(target):
                return CommandResult(False, f"touch: {path_arg}: Access denied")
            
            if self._is_readonly_path(target):
                return CommandResult(False, f"touch: {path_arg}: Read-only path")
            
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            except Exception as e:
                return CommandResult(False, f"touch: {e}")
        
        return CommandResult(True, "")
    
    def _cmd_echo(self, args: List[str], redirect: Optional[str], append: bool) -> CommandResult:
        """Echo text, optionally to a file."""
        text = " ".join(args)
        
        # Remove surrounding quotes if present
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        
        if not redirect:
            return CommandResult(True, text)
        
        return self._write_redirect(text + "\n", redirect, append)
    
    def _write_redirect(self, content: str, path: str, append: bool) -> CommandResult:
        """Write content to file via redirect (with per-path locking)."""
        target = self._resolve_path(path)
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"Redirect: {path}: Access denied")
        
        if self._is_readonly_path(target):
            return CommandResult(False, f"Redirect: {path}: Read-only path (skills, enterprise_context, and databases are read-only)")
        
        # Acquire per-path lock to prevent concurrent sessions from
        # interleaving writes to the same file (e.g. /agent/facts/).
        lock_key = str(target)
        _acquire_write_lock(lock_key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            
            mode = "a" if append else "w"
            with open(target, mode, encoding="utf-8") as f:
                f.write(content)
            
            # Index if in memory folder
            self._index_file(target)
            
            action = "Appended to" if append else "Wrote to"
            virtual = self._to_virtual_path(target)
            
            # --- Fire-and-forget blob sync for this file ---
            try:
                from src.utils.workspace_blob_sync import WorkspaceBlobSync
                import os as _os
                storage_provider = _os.getenv('STORAGE_PROVIDER', '')
                if storage_provider:
                    from src.storage import get_storage_client
                    _client = get_storage_client(storage_provider)
                    _syncer = WorkspaceBlobSync(
                        storage_client=_client,
                        workspace_root=str(self.workspace_root),
                        department=self.department,
                        agent_id=self.agent_id,
                        session_id=self.session_id,
                        user_email=self.user_email,
                    )
                    blob_key = _syncer.make_blob_key(virtual)
                    _syncer.schedule_file_sync(target, blob_key, name=f"blob_shell_write_{virtual}")
            except Exception:
                pass  # Non-critical: never block agent on blob failure
            # --- End blob sync ---
            
            # Show index status for memory files
            if virtual.startswith("/memory/") and self.vector_store:
                return CommandResult(True, f"{action} {virtual} (indexed to memory)")
            return CommandResult(True, f"{action} {virtual}")
            
        except Exception as e:
            return CommandResult(False, f"Redirect error: {e}")
        finally:
            _release_write_lock(lock_key)

    # ---- P0: sed — line-range reading ----

    def _cmd_sed(self, args: List[str]) -> CommandResult:
        """Print a range of lines from a file.

        Usage:
            sed -n '10,20p' <file>      Print lines 10-20
            sed -n '5p' <file>          Print line 5 only
            sed -n '10,20p' -n <file>   (same — -n is implicit)
        """
        if not args:
            return CommandResult(False, "sed: missing arguments\nUsage: sed -n '<start>,<end>p' <file>")

        # Parse args — expect  -n  '<range>p'  <file>
        range_expr = None
        path_arg = None

        for a in args:
            if a == "-n":
                continue  # ignore, always behave as -n
            # Pattern like '10,20p' or '5p'
            stripped = a.strip("'\"")
            if stripped.endswith("p") and any(c.isdigit() for c in stripped):
                range_expr = stripped[:-1]  # drop trailing 'p'
            elif not a.startswith("-"):
                path_arg = a

        if not range_expr:
            return CommandResult(False, "sed: missing range expression\nUsage: sed -n '10,20p' <file>")
        if not path_arg:
            return CommandResult(False, "sed: missing file operand")

        # Parse range
        if "," in range_expr:
            parts = range_expr.split(",", 1)
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                return CommandResult(False, f"sed: invalid range '{range_expr}'")
        else:
            try:
                start = end = int(range_expr)
            except ValueError:
                return CommandResult(False, f"sed: invalid range '{range_expr}'")

        if start < 1:
            start = 1
        if end < start:
            return CommandResult(False, f"sed: end ({end}) must be >= start ({start})")

        # Resolve virtual path
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"

        if self._is_virtual_path(resolved_virtual):
            result = self._handle_virtual_cat(resolved_virtual)
            if not result.success:
                return result
            lines = result.output.splitlines()
            selected = lines[start - 1:end]
            numbered = [f"{start + i:>4}  {line}" for i, line in enumerate(selected)]
            return CommandResult(True, "\n".join(numbered))

        target = self._resolve_path(path_arg)
        if not target.exists():
            return CommandResult(False, f"sed: {path_arg}: No such file")
        if target.is_dir():
            return CommandResult(False, f"sed: {path_arg}: Is a directory")
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "sed: Access denied")

        try:
            all_lines = target.read_text(encoding="utf-8").splitlines()
            # Clamp end to file length
            end = min(end, len(all_lines))
            selected = all_lines[start - 1:end]
            # Show line numbers for easy reference
            numbered = [f"{start + i:>4}  {line}" for i, line in enumerate(selected)]
            return CommandResult(True, "\n".join(numbered))
        except Exception as e:
            return CommandResult(False, f"sed: {e}")

    # ---- P1: stat — file metadata ----

    def _cmd_stat(self, args: List[str]) -> CommandResult:
        """Show file/directory metadata (size, line count, modified time).

        Usage: stat <file_or_dir>
        """
        if not args:
            return CommandResult(False, "stat: missing operand")

        path_arg = args[0]
        target = self._resolve_path(path_arg)
        virtual = self._to_virtual_path(target)

        if not target.exists():
            return CommandResult(False, f"stat: {path_arg}: No such file or directory")
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "stat: Access denied")

        try:
            st = target.stat()
            size = st.st_size
            modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            lines = [f"  File: {virtual}"]
            if target.is_file():
                lines.append(f"  Type: regular file")
                lines.append(f"  Size: {size} bytes ({self._human_size(size)})")
                # Count lines without reading entire file into memory
                try:
                    lc = sum(1 for _ in open(target, encoding="utf-8"))
                    lines.append(f" Lines: {lc}")
                except Exception:
                    pass
            else:
                # Directory — count children
                n_files = sum(1 for _ in target.iterdir() if _.is_file())
                n_dirs = sum(1 for _ in target.iterdir() if _.is_dir())
                lines.append(f"  Type: directory")
                lines.append(f" Items: {n_files} files, {n_dirs} subdirectories")
            lines.append(f"  Modified: {modified}")
            return CommandResult(True, "\n".join(lines))
        except Exception as e:
            return CommandResult(False, f"stat: {e}")

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Format bytes as human-readable string."""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}K"
        else:
            return f"{size_bytes / (1024 * 1024):.1f}M"

    # ---- P2: diff — compare two files ----

    def _cmd_diff(self, args: List[str]) -> CommandResult:
        """Compare two files line by line (unified diff).

        Usage: diff <file1> <file2>
        """
        file_args = [a for a in args if not a.startswith("-")]
        if len(file_args) < 2:
            return CommandResult(False, "diff: need exactly 2 files\nUsage: diff <file1> <file2>")

        path1, path2 = file_args[0], file_args[1]
        target1 = self._resolve_path(path1)
        target2 = self._resolve_path(path2)

        for p, t in [(path1, target1), (path2, target2)]:
            if not t.exists():
                return CommandResult(False, f"diff: {p}: No such file")
            if t.is_dir():
                return CommandResult(False, f"diff: {p}: Is a directory")
            if not self._is_inside_sandbox(t):
                return CommandResult(False, f"diff: {p}: Access denied")

        try:
            lines1 = target1.read_text(encoding="utf-8").splitlines(keepends=True)
            lines2 = target2.read_text(encoding="utf-8").splitlines(keepends=True)
            vpath1 = self._to_virtual_path(target1)
            vpath2 = self._to_virtual_path(target2)

            diff_lines = list(difflib.unified_diff(
                lines1, lines2,
                fromfile=vpath1, tofile=vpath2,
                lineterm=""
            ))

            if not diff_lines:
                return CommandResult(True, f"Files {vpath1} and {vpath2} are identical")

            return CommandResult(True, "\n".join(diff_lines))
        except Exception as e:
            return CommandResult(False, f"diff: {e}")

    def _cmd_semgrep(self, args: List[str]) -> CommandResult:
        """Semantic search using vector store."""
        if not self.vector_store:
            return CommandResult(False, "semgrep: Semantic search is not enabled")
        
        if not args:
            return CommandResult(False, "semgrep: missing query")
        
        # Parse arguments
        query = None
        path_prefix = None
        top_k = 10
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    top_k = int(args[i + 1])
                    i += 2
                    continue
                except:
                    pass
            elif not args[i].startswith("-"):
                if query is None:
                    query = args[i]
                else:
                    path_prefix = args[i]
            i += 1
        
        if not query:
            return CommandResult(False, "semgrep: missing query")
        
        # Convert path to virtual prefix
        if path_prefix:
            # Normalize
            pparts = [p for p in path_prefix.split("/") if p and p != "."]
            norm_prefix = "/" + "/".join(pparts) if pparts else "/"
        else:
            norm_prefix = None

        # For root-level semantic search, search across ALL virtual mounts
        if norm_prefix == "/" or norm_prefix is None:
            results = []
            for vprefix, real_root in self._all_virtual_roots():
                vp = self._to_virtual_path(real_root)
                hits = self.vector_store.search(query, path_prefix=vp, top_k=top_k)
                if hits:
                    results.extend(hits)
            # Sort by score descending, keep top_k
            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:top_k]
        else:
            if path_prefix:
                resolved = self._resolve_path(path_prefix)
                path_prefix = self._to_virtual_path(resolved)
            results = self.vector_store.search(query, path_prefix=path_prefix, top_k=top_k)
        
        if not results:
            return CommandResult(True, f"No semantic matches for '{query}'")
        
        lines = [f"Found {len(results)} semantic matches for '{query}':\n"]
        for r in results:
            score_pct = int(r.score * 100)
            lines.append(f"{r.path} [{score_pct}% match]: {r.snippet}")
        
        return CommandResult(True, "\n".join(lines))
    
    def _cmd_tree(self, args: List[str]) -> CommandResult:
        """Show directory tree. Supports --size to display file sizes."""
        path_arg = "."
        max_depth = 3
        show_size = False

        positionals = []
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-L" and i + 1 < len(args):
                try: max_depth = int(args[i + 1])
                except ValueError: pass
                i += 2
                continue
            elif a in ("--size", "-s", "--sz"):
                show_size = True
            elif not a.startswith("-"):
                positionals.append(a)
            i += 1

        if positionals:
            path_arg = positionals[0]
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"tree: {path_arg}: No such directory")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "tree: Access denied")
        
        lines = [self._to_virtual_path(target)]

        def _fmt_size(size_bytes: int) -> str:
            """Human-readable file size."""
            if size_bytes < 1024:
                return f"{size_bytes}B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f}K"
            else:
                return f"{size_bytes / (1024 * 1024):.1f}M"

        def build_tree(path: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                items = [it for it in items if not it.name.startswith(".")]
                
                for idx, item in enumerate(items):
                    is_last = idx == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    name = item.name + "/" if item.is_dir() else item.name
                    if show_size and item.is_file():
                        try:
                            sz = _fmt_size(item.stat().st_size)
                            name = f"{name} ({sz})"
                        except OSError:
                            pass
                    lines.append(f"{prefix}{connector}{name}")
                    
                    if item.is_dir() and depth < max_depth:
                        extension = "    " if is_last else "│   "
                        build_tree(item, prefix + extension, depth + 1)
            except Exception:
                pass
        
        build_tree(target, "", 1)
        return CommandResult(True, "\n".join(lines))
    
    def _cmd_wc(self, args: List[str]) -> CommandResult:
        """Count lines, words, characters. Supports glob patterns."""
        if not args:
            return CommandResult(False, "wc: missing file operand")
        
        show_lines = "-l" in args
        show_words = "-w" in args
        show_chars = "-c" in args
        
        # If no specific flag, show all
        if not (show_lines or show_words or show_chars):
            show_lines = show_words = show_chars = True
        
        path_args = [a for a in args if not a.startswith("-")]
        
        if not path_args:
            return CommandResult(False, "wc: missing file operand")

        # Expand glob patterns
        resolved_files: List[Tuple[str, Path]] = []
        for pa in path_args:
            if "*" in pa or "?" in pa:
                # Glob expansion: resolve the parent directory
                base_path = self._resolve_path(os.path.dirname(pa) or ".")
                glob_pattern = os.path.basename(pa)
                if base_path.exists() and base_path.is_dir():
                    for fp in sorted(base_path.glob(glob_pattern)):
                        if fp.is_file() and self._is_inside_sandbox(fp):
                            resolved_files.append((self._to_virtual_path(fp), fp))
            else:
                t = self._resolve_path(pa)
                if t.exists() and t.is_file() and self._is_inside_sandbox(t):
                    resolved_files.append((self._to_virtual_path(t), t))
                elif not t.exists():
                    return CommandResult(False, f"wc: {pa}: No such file")
                elif not self._is_inside_sandbox(t):
                    return CommandResult(False, "wc: Access denied")

        if not resolved_files:
            return CommandResult(False, "wc: no matching files")

        output_lines = []
        total_l = total_w = total_c = 0
        for vpath, target in resolved_files:
            try:
                content = target.read_text(encoding="utf-8")
                lc = len(content.splitlines())
                wc = len(content.split())
                cc = len(content)
                total_l += lc; total_w += wc; total_c += cc
                parts = []
                if show_lines: parts.append(str(lc))
                if show_words: parts.append(str(wc))
                if show_chars: parts.append(str(cc))
                parts.append(vpath)
                output_lines.append(" ".join(parts))
            except Exception as e:
                output_lines.append(f"wc: {vpath}: {e}")

        # Show totals when multiple files
        if len(resolved_files) > 1:
            parts = []
            if show_lines: parts.append(str(total_l))
            if show_words: parts.append(str(total_w))
            if show_chars: parts.append(str(total_c))
            parts.append("total")
            output_lines.append(" ".join(parts))

        return CommandResult(True, "\n".join(output_lines))
    
    def _cmd_get_secret(self, args: List[str]) -> CommandResult:
        """Retrieve a secret_data from the vault (public, private, or group).

        Usage:
            get_secret <key_name>                   # private (user) secret_data
            get_secret --public <key_name>           # public secret_data
            get_secret --group <group_name> <key_name>  # group secret_data
        """
        if not args:
            return CommandResult(
                False,
                "Usage: get_secret <key_name>\n"
                "       get_secret --public <key_name>\n"
                "       get_secret --group <group_name> <key_name>\n"
                "\nRetrieves a secret value from the platform vault."
            )

        secret_type = "private"  # default
        group_name = None
        key_name = None

        # Parse flags
        i = 0
        while i < len(args):
            if args[i] == "--public":
                secret_type = "public"
                i += 1
            elif args[i] == "--group":
                secret_type = "group"
                i += 1
                if i < len(args):
                    group_name = args[i]
                    i += 1
                else:
                    return CommandResult(False, "Error: --group requires a group name followed by a key name")
            elif not args[i].startswith("--"):
                key_name = args[i]
                i += 1
            else:
                return CommandResult(False, f"Unknown flag: {args[i]}")

        if not key_name:
            return CommandResult(False, "Error: secret key name is required")

        try:
            # Ensure ContextVars are set so secrets_handler functions can read
            # the current user identity.  The shell already stores user_email
            # and department from construction time, but the ContextVars may
            # not be propagated into the current execution context (e.g. when
            # the shell command runs inside a LangGraph node).
            from src.utils.secrets_handler import current_user_email, current_user_department
            _prev_email = current_user_email.get(None)
            _prev_dept = current_user_department.get(None)
            _tok_email = _tok_dept = None
            if not _prev_email and self.user_email and self.user_email != "anonymous":
                _tok_email = current_user_email.set(self.user_email)
            if not _prev_dept and self.department:
                _tok_dept = current_user_department.set(self.department)

            try:
                if secret_type == "public":
                    from src.utils.secrets_handler import get_public_key
                    dept = current_user_department.get(self.department)
                    value = get_public_key(key_name, default=None, department_name=dept)
                    if value is None:
                        return CommandResult(False, f"Public secret '{key_name}' not found in vault")
                    log.info(f"[AgentShell] get_secret: retrieved public secret '{key_name}'")
                    return CommandResult(True, value)

                elif secret_type == "group":
                    from src.utils.secrets_handler import get_group_secrets
                    if not group_name:
                        return CommandResult(False, "Error: --group requires a group name")
                    value = get_group_secrets(group_name, key_name, default_value=None)
                    if value is None:
                        return CommandResult(False, f"Group secret '{key_name}' not found in group '{group_name}'")
                    log.info(f"[AgentShell] get_secret: retrieved group secret '{key_name}' from group '{group_name}'")
                    return CommandResult(True, value)

                else:  # private
                    from src.utils.secrets_handler import get_user_secrets
                    value = get_user_secrets(key_name, default_value=None)
                    if value is None:
                        return CommandResult(False, f"Private secret '{key_name}' not found in vault")
                    log.info(f"[AgentShell] get_secret: retrieved private (user) secret '{key_name}'")
                    return CommandResult(True, value)

            finally:
                # Restore previous ContextVar values if we changed them
                if _tok_email is not None:
                    current_user_email.reset(_tok_email)
                if _tok_dept is not None:
                    current_user_department.reset(_tok_dept)

        except ValueError as e:
            return CommandResult(False, f"Vault access error: {e}")
        except PermissionError as e:
            return CommandResult(False, f"Vault permission denied: {e}")
        except Exception as e:
            log.warning(f"[AgentShell] get_secret failed: {e}")
            return CommandResult(False, f"Error retrieving secret: {e}")

    # ==================================================================
    # NEW COMMANDS — System Info, Text Processing, File/Disk, Math, Net
    # ==================================================================

    # ---- System Info ----

    def _cmd_date(self, args: List[str]) -> CommandResult:
        """Print the current date and time.

        Usage: date [+FORMAT]
        Supports common strftime format codes, e.g. date +%Y-%m-%d
        """
        now = datetime.now()
        if args and args[0].startswith("+"):
            fmt = args[0][1:]  # strip leading +
            try:
                return CommandResult(True, now.strftime(fmt))
            except Exception as e:
                return CommandResult(False, f"date: invalid format: {e}")
        return CommandResult(True, now.strftime("%a %b %d %H:%M:%S %Z %Y"))

    def _cmd_whoami(self, args: List[str]) -> CommandResult:
        """Print the current user email.

        Usage: whoami
        """
        return CommandResult(True, self.user_email)

    def _cmd_hostname(self, args: List[str]) -> CommandResult:
        """Print the system hostname.

        Usage: hostname
        """
        try:
            return CommandResult(True, socket.gethostname())
        except Exception:
            return CommandResult(True, "unknown")

    def _cmd_uname(self, args: List[str]) -> CommandResult:
        """Print system information.

        Usage: uname [-a|-s|-r|-m|-n]
        """
        show_all = not args or "-a" in args
        parts = []
        if show_all or "-s" in args:
            parts.append(platform.system())
        if show_all or "-n" in args:
            parts.append(platform.node())
        if show_all or "-r" in args:
            parts.append(platform.release())
        if show_all or "-m" in args:
            parts.append(platform.machine())
        if show_all:
            parts.append(platform.version())
        return CommandResult(True, " ".join(parts))

    def _cmd_uptime(self, args: List[str]) -> CommandResult:
        """Print how long the current process has been running.

        Usage: uptime
        """
        import psutil
        try:
            boot = psutil.Process(os.getpid()).create_time()
            elapsed = _time_mod.time() - boot
            hours, rem = divmod(int(elapsed), 3600)
            minutes, seconds = divmod(rem, 60)
            now_str = datetime.now().strftime("%H:%M:%S")
            return CommandResult(True, f" {now_str} up {hours}:{minutes:02d}:{seconds:02d}")
        except Exception:
            # Fallback: just print current time
            return CommandResult(True, f" {datetime.now().strftime('%H:%M:%S')} up (unavailable)")

    def _cmd_id(self, args: List[str]) -> CommandResult:
        """Print user identity information.

        Usage: id
        """
        return CommandResult(True, f"uid=agent({self.agent_id}) user={self.user_email} department={self.department}")

    # ---- Environment / Config ----

    def _cmd_env(self, args: List[str]) -> CommandResult:
        """Print environment variables (filtered — sensitive values hidden).

        Usage: env [VARNAME]
        If VARNAME given, prints just that variable's value.
        Sensitive vars are masked (SECRET_DATA, TOKEN, KEY, CREDENTIAL, etc.).
        """
        _sensitive_patterns = re.compile(
            r"(password|secret|token|key|credential|api_key|private|auth|jwt|bearer|cookie)",
            re.IGNORECASE,
        )
        if args:
            # Print specific variable
            val = os.environ.get(args[0])
            if val is None:
                return CommandResult(False, f"env: {args[0]}: not set")
            if _sensitive_patterns.search(args[0]):
                return CommandResult(True, f"{args[0]}=****")
            return CommandResult(True, f"{args[0]}={val}")
        # Print all (filtered)
        lines = []
        for k in sorted(os.environ.keys()):
            if _sensitive_patterns.search(k):
                lines.append(f"{k}=****")
            else:
                v = os.environ[k]
                # Truncate very long values
                if len(v) > 200:
                    v = v[:200] + "..."
                lines.append(f"{k}={v}")
        return CommandResult(True, "\n".join(lines))

    def _cmd_which(self, args: List[str]) -> CommandResult:
        """Check if a command exists in the virtual shell.

        Usage: which <command>
        """
        if not args:
            return CommandResult(False, "which: missing argument")
        cmd_name = args[0].lower()
        # Check in virtual handlers + blocked list
        all_handlers = {
            "ls", "cd", "pwd", "cat", "readfile", "head", "tail", "grep",
            "find", "mkdir", "touch", "echo", "semgrep", "tree", "wc",
            "sed", "stat", "diff", "get_secret", "help",
            "date", "whoami", "hostname", "uname", "uptime", "id",
            "env", "printenv", "which", "type",
            "sort", "uniq", "cut", "tr", "awk", "rev", "tac", "paste",
            "nl", "column", "fold", "expand", "unexpand",
            "du", "df", "file", "sha256sum", "basename",
            "dirname", "realpath",
            "expr", "seq", "true", "false",
            "ping", "nslookup", "curl",
        }
        if cmd_name in all_handlers:
            return CommandResult(True, f"/usr/bin/{cmd_name} (virtual shell built-in)")
        if cmd_name in {c.lower() for c in self.BLOCKED_COMMANDS}:
            return CommandResult(False, f"{cmd_name}: blocked for security reasons")
        return CommandResult(False, f"{cmd_name}: not found")

    # ---- Text Processing ----

    def _cmd_sort(self, args: List[str]) -> CommandResult:
        """Sort lines of text.

        Usage: sort [-r] [-n] [-u] [-k N] [file]
        Reads from file or pipe input. -r reverse, -n numeric, -u unique, -k field.
        """
        # Expand combined flags like -rn → -r -n
        expanded_args: List[str] = []
        for a in args:
            if re.match(r"^-[rnuRNU]{2,}$", a):
                for ch in a[1:]:
                    expanded_args.append(f"-{ch}")
            else:
                expanded_args.append(a)
        args = expanded_args

        reverse = "-r" in args
        numeric = "-n" in args
        unique = "-u" in args
        field_idx = None
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-k" and i + 1 < len(args):
                try:
                    field_idx = int(args[i + 1]) - 1  # 1-based to 0-based
                except ValueError:
                    return CommandResult(False, f"sort: invalid field number: {args[i + 1]}")
                i += 2
                continue
            if args[i] not in ("-r", "-n", "-u"):
                clean_args.append(args[i])
            i += 1

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "sort: missing file operand or pipe input")
        lines = text.splitlines()

        def sort_key(line):
            if field_idx is not None:
                fields = line.split()
                val = fields[field_idx] if field_idx < len(fields) else ""
            else:
                val = line
            if numeric:
                try:
                    return float(re.match(r"[-+]?[\d.]+", val).group())
                except (ValueError, AttributeError):
                    return 0.0
            return val

        lines.sort(key=sort_key, reverse=reverse)
        if unique:
            seen = set()
            deduped = []
            for ln in lines:
                if ln not in seen:
                    seen.add(ln)
                    deduped.append(ln)
            lines = deduped
        return CommandResult(True, "\n".join(lines))

    def _cmd_uniq(self, args: List[str]) -> CommandResult:
        """Remove adjacent duplicate lines.

        Usage: uniq [-c] [-d] [-u] [file]
        -c prefix lines with count, -d only print duplicates,
        -u only print unique lines.
        """
        count_flag = "-c" in args
        dups_only = "-d" in args
        uniq_only = "-u" in args
        clean_args = [a for a in args if a not in ("-c", "-d", "-u")]

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "uniq: missing file operand or pipe input")
        lines = text.splitlines()
        if not lines:
            return CommandResult(True, "")

        groups = []
        prev = lines[0]
        cnt = 1
        for ln in lines[1:]:
            if ln == prev:
                cnt += 1
            else:
                groups.append((cnt, prev))
                prev = ln
                cnt = 1
        groups.append((cnt, prev))

        result = []
        for c, ln in groups:
            if dups_only and c < 2:
                continue
            if uniq_only and c > 1:
                continue
            if count_flag:
                result.append(f"{c:7d} {ln}")
            else:
                result.append(ln)
        return CommandResult(True, "\n".join(result))

    def _cmd_cut(self, args: List[str]) -> CommandResult:
        """Extract columns/fields from lines.

        Usage: cut -d DELIM -f FIELDS [file]
               cut -c CHARS [file]
        FIELDS/CHARS: e.g. 1,3 or 1-3 (1-based).
        """
        delim = "\t"
        fields_spec = None
        chars_spec = None
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-d" and i + 1 < len(args):
                delim = args[i + 1]
                if delim.startswith("'") or delim.startswith('"'):
                    delim = delim.strip("'\"")
                i += 2
                continue
            elif args[i] == "-f" and i + 1 < len(args):
                fields_spec = args[i + 1]
                i += 2
                continue
            elif args[i] == "-c" and i + 1 < len(args):
                chars_spec = args[i + 1]
                i += 2
                continue
            else:
                clean_args.append(args[i])
            i += 1

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "cut: missing file operand or pipe input")

        def parse_spec(spec: str) -> list:
            """Parse field/char spec like '1,3' or '1-3' into 0-based indices."""
            indices = set()
            for part in spec.split(","):
                part = part.strip()
                if "-" in part:
                    try:
                        start, end = part.split("-", 1)
                        s = int(start) - 1 if start else 0
                        e = int(end) if end else 9999
                        indices.update(range(s, e))
                    except ValueError:
                        pass
                else:
                    try:
                        indices.add(int(part) - 1)
                    except ValueError:
                        pass
            return sorted(indices)

        result = []
        for line in text.splitlines():
            if chars_spec:
                idxs = parse_spec(chars_spec)
                result.append("".join(line[i] for i in idxs if i < len(line)))
            elif fields_spec:
                parts = line.split(delim)
                idxs = parse_spec(fields_spec)
                selected = [parts[i] for i in idxs if i < len(parts)]
                result.append(delim.join(selected))
            else:
                result.append(line)
        return CommandResult(True, "\n".join(result))

    @staticmethod
    def _expand_tr_set(s: str) -> str:
        """Expand tr-style character ranges like ``a-z`` or ``A-Z`` into full strings."""
        result: List[str] = []
        i = 0
        while i < len(s):
            if (i + 2 < len(s) and s[i + 1] == '-'
                    and ord(s[i]) < ord(s[i + 2])):
                for c in range(ord(s[i]), ord(s[i + 2]) + 1):
                    result.append(chr(c))
                i += 3
            else:
                result.append(s[i])
                i += 1
        return "".join(result)

    def _cmd_tr(self, args: List[str]) -> CommandResult:
        """Translate or delete characters.

        Usage: tr [-d] SET1 [SET2] [file]
        -d: delete characters in SET1.
        Otherwise: replace chars in SET1 with SET2 (positional).
        Supports range notation: a-z, A-Z, 0-9.
        """
        delete = "-d" in args
        clean_args = [a for a in args if a != "-d"]

        if not clean_args:
            return CommandResult(False, "tr: missing operand")

        set1 = self._expand_tr_set(clean_args[0].strip("'\""))
        set2 = self._expand_tr_set(clean_args[1].strip("'\"")) if len(clean_args) > 1 and not delete else ""
        file_args = clean_args[2:] if not delete else clean_args[1:]

        text = self._get_input_text(file_args)
        if text is None:
            # If set2 / file_args didn't resolve, try using remaining args
            text = self._get_input_text(clean_args[2:] if len(clean_args) > 2 else [])
            if text is None:
                return CommandResult(False, "tr: missing input")

        if delete:
            table = str.maketrans("", "", set1)
            return CommandResult(True, text.translate(table))
        else:
            # Pad set2 to match set1 length
            if len(set2) < len(set1):
                set2 = set2 + set2[-1:] * (len(set1) - len(set2))
            table = str.maketrans(set1, set2[:len(set1)])
            return CommandResult(True, text.translate(table))

    def _cmd_awk(self, args: List[str]) -> CommandResult:
        """Simple AWK-like pattern processing.

        Usage: awk [-F DELIM] 'PATTERN' [file]
        Supports simple print patterns:
          '{print $1}'         — print first field
          '{print $1, $3}'     — print fields 1 and 3
          '{print NR, $0}'     — print line number and whole line
          '/pattern/ {print}'  — print lines matching pattern
          'BEGIN {print "hdr"} {print $0} END {print "done"}'
        """
        delim = None
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-F" and i + 1 < len(args):
                delim = args[i + 1].strip("'\"")
                i += 2
                continue
            clean_args.append(args[i])
            i += 1

        if not clean_args:
            return CommandResult(False, "awk: missing program")

        program = clean_args[0].strip("'\"")
        file_args = clean_args[1:]

        text = self._get_input_text(file_args)
        if text is None:
            return CommandResult(False, "awk: missing input")

        lines = text.splitlines()
        result = []

        # Parse simple awk patterns
        # Check for /regex/ filter
        line_filter = None
        filter_match = re.match(r"^/(.*?)/\s*\{", program)
        if filter_match:
            line_filter = re.compile(filter_match.group(1))
            program = program[filter_match.end() - 1:]  # keep from {

        # Check for BEGIN/END blocks
        begin_text = ""
        end_text = ""
        begin_match = re.match(r"BEGIN\s*\{(.*?)\}\s*(.*)", program, re.DOTALL)
        if begin_match:
            begin_cmd = begin_match.group(1).strip()
            program = begin_match.group(2).strip()
            # Simple: extract print string
            pm = re.match(r'print\s+"(.*?)"', begin_cmd)
            if pm:
                begin_text = pm.group(1)

        end_match = re.search(r"END\s*\{(.*?)\}\s*$", program, re.DOTALL)
        if end_match:
            end_cmd = end_match.group(1).strip()
            program = program[:end_match.start()].strip()
            pm = re.match(r'print\s+"(.*?)"', end_cmd)
            if pm:
                end_text = pm.group(1)

        if begin_text:
            result.append(begin_text)

        # Parse the main {print ...} block
        print_match = re.match(r"\{\s*print\s+(.*?)\s*\}", program)
        if not print_match:
            # Default: just print whole line
            for nr, line in enumerate(lines, 1):
                if line_filter and not line_filter.search(line):
                    continue
                result.append(line)
        else:
            fields_expr = print_match.group(1)
            for nr, line in enumerate(lines, 1):
                if line_filter and not line_filter.search(line):
                    continue
                parts = line.split(delim) if delim else line.split()
                out_parts = []
                for token in re.split(r",\s*", fields_expr):
                    token = token.strip()
                    if token == "$0":
                        out_parts.append(line)
                    elif token == "NR":
                        out_parts.append(str(nr))
                    elif token == "NF":
                        out_parts.append(str(len(parts)))
                    elif re.match(r"\$(\d+)", token):
                        idx = int(token[1:]) - 1
                        out_parts.append(parts[idx] if 0 <= idx < len(parts) else "")
                    elif token.startswith('"') and token.endswith('"'):
                        out_parts.append(token.strip('"'))
                    else:
                        out_parts.append(token)
                result.append(" ".join(out_parts))

        if end_text:
            result.append(end_text)

        return CommandResult(True, "\n".join(result))

    def _cmd_rev(self, args: List[str]) -> CommandResult:
        """Reverse each line of input.

        Usage: rev [file]
        """
        text = self._get_input_text(args)
        if text is None:
            return CommandResult(False, "rev: missing file operand or pipe input")
        return CommandResult(True, "\n".join(line[::-1] for line in text.splitlines()))

    def _cmd_tac(self, args: List[str]) -> CommandResult:
        """Print file in reverse (last line first).

        Usage: tac [file]
        """
        text = self._get_input_text(args)
        if text is None:
            return CommandResult(False, "tac: missing file operand or pipe input")
        return CommandResult(True, "\n".join(reversed(text.splitlines())))

    def _cmd_paste(self, args: List[str]) -> CommandResult:
        """Merge lines of files side by side.

        Usage: paste [-d DELIM] file1 file2
        Default delimiter is tab.
        """
        delim = "\t"
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-d" and i + 1 < len(args):
                delim = args[i + 1].strip("'\"")
                i += 2
                continue
            clean_args.append(args[i])
            i += 1

        if len(clean_args) < 2:
            return CommandResult(False, "paste: need at least two files")

        all_lines = []
        for farg in clean_args:
            target = self._resolve_path(farg)
            if not target.is_file():
                return CommandResult(False, f"paste: {farg}: No such file")
            if not self._is_inside_sandbox(target):
                return CommandResult(False, "paste: Access denied")
            try:
                all_lines.append(target.read_text(encoding="utf-8").splitlines())
            except Exception as e:
                return CommandResult(False, f"paste: {farg}: {e}")

        max_len = max(len(l) for l in all_lines)
        result = []
        for i in range(max_len):
            row = []
            for lines in all_lines:
                row.append(lines[i] if i < len(lines) else "")
            result.append(delim.join(row))
        return CommandResult(True, "\n".join(result))

    def _cmd_nl(self, args: List[str]) -> CommandResult:
        """Number lines of a file.

        Usage: nl [-ba] [file]
        -ba: number all lines (including blank).
        """
        number_blank = "-ba" in args
        clean_args = [a for a in args if a != "-ba"]

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "nl: missing file operand or pipe input")

        result = []
        num = 0
        for line in text.splitlines():
            if line.strip() or number_blank:
                num += 1
                result.append(f"{num:6d}\t{line}")
            else:
                result.append(f"      \t{line}")
        return CommandResult(True, "\n".join(result))

    def _cmd_column(self, args: List[str]) -> CommandResult:
        """Columnate output.

        Usage: column [-t] [-s DELIM] [file]
        -t: create a table (auto-detect columns).
        -s: specify input delimiter.
        """
        table_mode = "-t" in args
        delim = None
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-s" and i + 1 < len(args):
                delim = args[i + 1].strip("'\"")
                i += 2
                continue
            if args[i] != "-t":
                clean_args.append(args[i])
            i += 1

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "column: missing input")

        if not table_mode:
            return CommandResult(True, text)

        rows = []
        for line in text.splitlines():
            if delim:
                rows.append(line.split(delim))
            else:
                rows.append(line.split())
        if not rows:
            return CommandResult(True, "")

        # Calculate column widths
        max_cols = max(len(r) for r in rows)
        widths = [0] * max_cols
        for row in rows:
            for j, cell in enumerate(row):
                widths[j] = max(widths[j], len(cell))

        result = []
        for row in rows:
            parts = []
            for j, cell in enumerate(row):
                parts.append(cell.ljust(widths[j]) if j < len(widths) else cell)
            result.append("  ".join(parts).rstrip())
        return CommandResult(True, "\n".join(result))

    def _cmd_fold(self, args: List[str]) -> CommandResult:
        """Wrap lines to a specified width.

        Usage: fold [-w WIDTH] [file]
        Default width: 80.
        """
        width = 80
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-w" and i + 1 < len(args):
                try:
                    width = int(args[i + 1])
                except ValueError:
                    return CommandResult(False, f"fold: invalid width: {args[i + 1]}")
                i += 2
                continue
            clean_args.append(args[i])
            i += 1

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "fold: missing input")

        result = []
        for line in text.splitlines():
            while len(line) > width:
                result.append(line[:width])
                line = line[width:]
            result.append(line)
        return CommandResult(True, "\n".join(result))

    def _cmd_expand(self, args: List[str]) -> CommandResult:
        """Convert tabs to spaces.

        Usage: expand [-t N] [file]
        Default tab size: 8.
        """
        tab_size = 8
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-t" and i + 1 < len(args):
                try:
                    tab_size = int(args[i + 1])
                except ValueError:
                    return CommandResult(False, f"expand: invalid tab size: {args[i + 1]}")
                i += 2
                continue
            clean_args.append(args[i])
            i += 1

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "expand: missing input")
        return CommandResult(True, text.expandtabs(tab_size))

    def _cmd_unexpand(self, args: List[str]) -> CommandResult:
        """Convert spaces to tabs.

        Usage: unexpand [-t N] [file]
        Default tab size: 8.
        """
        tab_size = 8
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-t" and i + 1 < len(args):
                try:
                    tab_size = int(args[i + 1])
                except ValueError:
                    return CommandResult(False, f"unexpand: invalid tab size: {args[i + 1]}")
                i += 2
                continue
            clean_args.append(args[i])
            i += 1

        text = self._get_input_text(clean_args)
        if text is None:
            return CommandResult(False, "unexpand: missing input")
        result = []
        for line in text.splitlines():
            # Replace leading spaces with tabs
            stripped = line.lstrip(" ")
            n_spaces = len(line) - len(stripped)
            tabs = "\t" * (n_spaces // tab_size)
            remaining = " " * (n_spaces % tab_size)
            result.append(tabs + remaining + stripped)
        return CommandResult(True, "\n".join(result))

    # ---- File / Disk Info ----

    def _cmd_du(self, args: List[str]) -> CommandResult:
        """Estimate file/directory disk usage.

        Usage: du [-h] [-s] [-d N] [path]
        -h: human-readable sizes, -s: summary only, -d N: max depth.
        """
        human = "-h" in args
        summary = "-s" in args
        max_depth = None
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-d" and i + 1 < len(args):
                try:
                    max_depth = int(args[i + 1])
                except ValueError:
                    return CommandResult(False, f"du: invalid depth: {args[i + 1]}")
                i += 2
                continue
            if args[i] not in ("-h", "-s"):
                clean_args.append(args[i])
            i += 1

        path_arg = clean_args[0] if clean_args else "."
        target = self._resolve_path(path_arg)
        if not target.exists():
            return CommandResult(False, f"du: {path_arg}: No such file or directory")
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "du: Access denied")

        def get_size(p: Path, depth: int = 0) -> List[Tuple[int, str]]:
            results = []
            if p.is_file():
                return [(p.stat().st_size, self._to_virtual_path(p))]
            total = 0
            try:
                for child in sorted(p.iterdir()):
                    if child.is_file():
                        total += child.stat().st_size
                    elif child.is_dir():
                        sub = get_size(child, depth + 1)
                        if sub:
                            sub_total = sub[-1][0]
                            total += sub_total
                            if not summary and (max_depth is None or depth + 1 <= max_depth):
                                results.extend(sub)
            except PermissionError:
                pass
            results.append((total, self._to_virtual_path(p)))
            return results

        try:
            entries = get_size(target)
            lines = []
            for size, vpath in entries:
                if human:
                    lines.append(f"{self._human_size(size):>8s}\t{vpath}")
                else:
                    lines.append(f"{size:>12d}\t{vpath}")
            return CommandResult(True, "\n".join(lines))
        except Exception as e:
            return CommandResult(False, f"du: {e}")

    def _cmd_df(self, args: List[str]) -> CommandResult:
        """Show disk free space for the agent workspace.

        Usage: df [-h]
        """
        import shutil
        human = "-h" in args
        try:
            usage = shutil.disk_usage(str(self.workspace_root))
            if human:
                lines = [
                    "Filesystem      Size  Used Avail Use%",
                    f"workspace  {self._human_size(usage.total):>8s} {self._human_size(usage.used):>5s} {self._human_size(usage.free):>5s} {usage.used * 100 // usage.total:3d}%",
                ]
            else:
                lines = [
                    "Filesystem      1K-blocks      Used Available Use%",
                    f"workspace  {usage.total // 1024:>12d} {usage.used // 1024:>9d} {usage.free // 1024:>9d} {usage.used * 100 // usage.total:3d}%",
                ]
            return CommandResult(True, "\n".join(lines))
        except Exception as e:
            return CommandResult(False, f"df: {e}")

    def _cmd_file(self, args: List[str]) -> CommandResult:
        """Determine file type.

        Usage: file <path>
        """
        if not args:
            return CommandResult(False, "file: missing operand")
        path_arg = args[0]
        target = self._resolve_path(path_arg)
        if not target.exists():
            return CommandResult(False, f"file: {path_arg}: No such file or directory")
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "file: Access denied")

        vpath = self._to_virtual_path(target)
        if target.is_dir():
            return CommandResult(True, f"{vpath}: directory")

        ext = target.suffix.lower()
        if ext in self.BINARY_EXTENSIONS:
            type_map = {
                ".pdf": "PDF document", ".xlsx": "Excel spreadsheet",
                ".xls": "Excel spreadsheet", ".docx": "Word document",
                ".pptx": "PowerPoint presentation",
                ".png": "PNG image", ".jpg": "JPEG image", ".jpeg": "JPEG image",
                ".gif": "GIF image", ".bmp": "BMP image", ".webp": "WebP image",
                ".zip": "ZIP archive", ".tar": "tar archive",
                ".gz": "gzip compressed", ".bz2": "bzip2 compressed",
                ".mp3": "MP3 audio", ".wav": "WAV audio",
                ".mp4": "MP4 video", ".avi": "AVI video",
                ".sqlite": "SQLite database", ".db": "database file",
                ".pkl": "Python pickle", ".npy": "NumPy array",
                ".parquet": "Parquet columnar data",
            }
            desc = type_map.get(ext, "binary data")
            size = target.stat().st_size
            return CommandResult(True, f"{vpath}: {desc} ({self._human_size(size)})")

        # Try to detect text encoding
        try:
            with open(target, "rb") as f:
                sample = f.read(512)
            if b"\x00" in sample:
                return CommandResult(True, f"{vpath}: binary data ({self._human_size(target.stat().st_size)})")
            # Text file — detect type by extension
            text_types = {
                ".py": "Python script", ".js": "JavaScript source",
                ".ts": "TypeScript source", ".java": "Java source",
                ".c": "C source", ".cpp": "C++ source", ".h": "C/C++ header",
                ".go": "Go source", ".rs": "Rust source",
                ".md": "Markdown document", ".txt": "ASCII text",
                ".json": "JSON data", ".yaml": "YAML data", ".yml": "YAML data",
                ".xml": "XML document", ".html": "HTML document",
                ".css": "CSS stylesheet", ".csv": "CSV data",
                ".sql": "SQL script", ".sh": "shell script",
                ".bat": "batch script", ".ps1": "PowerShell script",
                ".toml": "TOML config", ".ini": "INI config",
                ".cfg": "config file", ".conf": "config file",
                ".log": "log file", ".env": "environment file",
            }
            desc = text_types.get(ext, "UTF-8 text")
            lc = sum(1 for _ in open(target, encoding="utf-8"))
            return CommandResult(True, f"{vpath}: {desc}, {lc} lines")
        except Exception:
            return CommandResult(True, f"{vpath}: data ({self._human_size(target.stat().st_size)})")

    def _cmd_sha256sum(self, args: List[str]) -> CommandResult:
        """Compute SHA-256 checksum of a file.

        Usage: sha256sum <file> [file2 ...]
        """
        if not args:
            return CommandResult(False, "sha256sum: missing operand")
        results = []
        for farg in args:
            target = self._resolve_path(farg)
            if not target.is_file():
                results.append(f"sha256sum: {farg}: No such file")
                continue
            if not self._is_inside_sandbox(target):
                results.append(f"sha256sum: {farg}: Access denied")
                continue
            try:
                h = hashlib.sha256()
                with open(target, "rb") as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        h.update(chunk)
                results.append(f"{h.hexdigest()}  {self._to_virtual_path(target)}")
            except Exception as e:
                results.append(f"sha256sum: {farg}: {e}")
        return CommandResult(True, "\n".join(results))

    def _cmd_basename(self, args: List[str]) -> CommandResult:
        """Strip directory from a path.

        Usage: basename <path> [suffix]
        """
        if not args:
            return CommandResult(False, "basename: missing operand")
        name = Path(args[0]).name
        if len(args) > 1 and name.endswith(args[1]):
            name = name[: -len(args[1])]
        return CommandResult(True, name)

    def _cmd_dirname(self, args: List[str]) -> CommandResult:
        """Strip last component from a path.

        Usage: dirname <path>
        """
        if not args:
            return CommandResult(False, "dirname: missing operand")
        parent = str(Path(args[0]).parent)
        return CommandResult(True, parent if parent != "." else "/")

    def _cmd_realpath(self, args: List[str]) -> CommandResult:
        """Resolve a path to its canonical virtual path.

        Usage: realpath <path>
        """
        if not args:
            return CommandResult(False, "realpath: missing operand")
        target = self._resolve_path(args[0])
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "realpath: Access denied")
        return CommandResult(True, self._to_virtual_path(target))

    # ---- Data / Math ----

    def _cmd_expr(self, args: List[str]) -> CommandResult:
        """Evaluate a math expression.

        Usage: expr <expression>
        Examples: expr 2 + 3, expr 10 / 3, expr 2 '*' 5
        Also supports: expr length "hello", expr substr "hello" 2 3
        """
        if not args:
            return CommandResult(False, "expr: missing operand")

        # String operations
        if args[0] == "length" and len(args) >= 2:
            return CommandResult(True, str(len(args[1].strip("'\"") )))
        if args[0] == "substr" and len(args) >= 4:
            s = args[1].strip("'\"")
            try:
                pos = int(args[2]) - 1  # 1-based
                length = int(args[3])
                return CommandResult(True, s[pos:pos + length])
            except (ValueError, IndexError) as e:
                return CommandResult(False, f"expr: {e}")

        # Math: join all args and evaluate safely
        expr_str = " ".join(args).replace("'", "").replace('"', '')
        # Only allow digits, operators, spaces, parens, decimal points
        if not re.match(r"^[\d\s+\-*/%().]+$", expr_str):
            return CommandResult(False, f"expr: invalid expression: {expr_str}")
        try:
            # Use a safe eval with only math operations
            result = eval(expr_str, {"__builtins__": {}}, {"abs": abs, "min": min, "max": max, "round": round})
            # expr traditionally returns integers when possible
            if isinstance(result, float) and result == int(result):
                result = int(result)
            return CommandResult(True, str(result))
        except ZeroDivisionError:
            return CommandResult(False, "expr: division by zero")
        except Exception as e:
            return CommandResult(False, f"expr: {e}")

    def _cmd_seq(self, args: List[str]) -> CommandResult:
        """Print a sequence of numbers.

        Usage: seq [FIRST [INCREMENT]] LAST
        Examples: seq 5, seq 2 10, seq 1 2 10
        """
        if not args:
            return CommandResult(False, "seq: missing operand")
        try:
            nums = [float(a) for a in args]
        except ValueError:
            return CommandResult(False, "seq: invalid number")

        if len(nums) == 1:
            first, incr, last = 1, 1, nums[0]
        elif len(nums) == 2:
            first, incr, last = nums[0], 1, nums[1]
        elif len(nums) == 3:
            first, incr, last = nums[0], nums[1], nums[2]
        else:
            return CommandResult(False, "seq: too many arguments")

        if incr == 0:
            return CommandResult(False, "seq: increment must not be 0")

        # Safety: limit output to 10000 numbers
        result = []
        current = first
        limit = 10000
        if incr > 0:
            while current <= last and len(result) < limit:
                result.append(str(int(current) if current == int(current) else current))
                current += incr
        else:
            while current >= last and len(result) < limit:
                result.append(str(int(current) if current == int(current) else current))
                current += incr
        return CommandResult(True, "\n".join(result))

    def _cmd_true(self, args: List[str]) -> CommandResult:
        """Return success (exit code 0).

        Usage: true
        """
        return CommandResult(True, "")

    def _cmd_false(self, args: List[str]) -> CommandResult:
        """Return failure (exit code 1).

        Usage: false
        """
        return CommandResult(False, "")

    # ---- Networking (bounded, read-only) ----

    def _cmd_ping(self, args: List[str]) -> CommandResult:
        """Ping a host (limited to 4 packets).

        Usage: ping [-c N] <host>
        Maximum 4 packets. Uses real ICMP ping via subprocess.
        """
        count = 4
        clean_args = []
        i = 0
        while i < len(args):
            if args[i] == "-c" and i + 1 < len(args):
                try:
                    count = min(int(args[i + 1]), 4)  # cap at 4
                except ValueError:
                    return CommandResult(False, f"ping: invalid count: {args[i + 1]}")
                i += 2
                continue
            clean_args.append(args[i])
            i += 1

        if not clean_args:
            return CommandResult(False, "ping: missing host operand")
        host = clean_args[0]

        # Basic validation — no shell injection
        if not re.match(r"^[a-zA-Z0-9._\-]+$", host):
            return CommandResult(False, f"ping: invalid hostname: {host}")

        try:
            # Platform-appropriate ping
            if platform.system().lower() == "windows":
                cmd_list = ["ping", "-n", str(count), host]
            else:
                cmd_list = ["ping", "-c", str(count), host]
            result = subprocess.run(
                cmd_list,
                capture_output=True, text=True, timeout=15,
            )
            output = result.stdout or result.stderr
            return CommandResult(result.returncode == 0, output.strip())
        except subprocess.TimeoutExpired:
            return CommandResult(False, f"ping: {host}: timed out after 15 seconds")
        except FileNotFoundError:
            return CommandResult(False, "ping: command not available on this system")
        except Exception as e:
            return CommandResult(False, f"ping: {e}")

    def _cmd_nslookup(self, args: List[str]) -> CommandResult:
        """DNS lookup for a hostname.

        Usage: nslookup <hostname>
        """
        if not args:
            return CommandResult(False, "nslookup: missing hostname")
        host = args[0]
        if not re.match(r"^[a-zA-Z0-9._\-]+$", host):
            return CommandResult(False, f"nslookup: invalid hostname: {host}")
        try:
            results = socket.getaddrinfo(host, None)
            seen = set()
            lines = [f"Server:  (local resolver)", f"Name:    {host}", ""]
            for family, _, _, _, addr in results:
                ip = addr[0]
                if ip not in seen:
                    seen.add(ip)
                    kind = "IPv6" if family == socket.AF_INET6 else "IPv4"
                    lines.append(f"Address: {ip} ({kind})")
            if not seen:
                return CommandResult(False, f"nslookup: {host}: Name not resolved")
            return CommandResult(True, "\n".join(lines))
        except socket.gaierror as e:
            return CommandResult(False, f"nslookup: {host}: {e}")
        except Exception as e:
            return CommandResult(False, f"nslookup: {e}")

    def _cmd_curl(self, args: List[str]) -> CommandResult:
        """Fetch a URL (GET only, read-only).

        Usage: curl [-s] [-I] <url>
        Only HTTP GET is allowed. No POST/PUT/DELETE.
        -s: silent mode (no progress). -I: headers only.
        """
        import urllib.request
        import urllib.error

        silent = "-s" in args
        headers_only = "-I" in args
        clean_args = [a for a in args if a not in ("-s", "-I")]

        if not clean_args:
            return CommandResult(False, "curl: missing URL")
        url = clean_args[0]

        # Only allow http/https
        if not re.match(r"^https?://", url, re.IGNORECASE):
            return CommandResult(False, "curl: only http:// and https:// URLs are allowed")

        # Block POST-like flags
        blocked_flags = {"-X", "--request", "-d", "--data", "-F", "--form", "--upload-file", "-T"}
        for a in args:
            if a in blocked_flags:
                return CommandResult(False, f"curl: {a} is not allowed (GET only)")

        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "IAF-AgentShell/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if headers_only:
                    lines = [f"HTTP/{resp.version // 10}.{resp.version % 10} {resp.status} {resp.reason}"]
                    for k, v in resp.headers.items():
                        lines.append(f"{k}: {v}")
                    return CommandResult(True, "\n".join(lines))
                body = resp.read(self.MAX_READ_BYTES).decode("utf-8", errors="replace")
                if not silent:
                    header_info = f"  % Total    % Received  Time\n  {len(body):>8d}  {len(body):>8d}  --:--:--\n"
                    return CommandResult(True, header_info + body)
                return CommandResult(True, body)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(4096).decode("utf-8", errors="replace")
            except Exception:
                pass
            return CommandResult(False, f"curl: HTTP {e.code} {e.reason}\n{body}".strip())
        except urllib.error.URLError as e:
            return CommandResult(False, f"curl: {url}: {e.reason}")
        except Exception as e:
            return CommandResult(False, f"curl: {e}")

    # ---- Pipe input helper ----

    def _get_input_text(self, file_args: List[str]) -> Optional[str]:
        """Read text from the first file argument, or return None."""
        if not file_args:
            return None
        target = self._resolve_path(file_args[0])
        if not target.is_file():
            return None
        if not self._is_inside_sandbox(target):
            return None
        try:
            return target.read_text(encoding="utf-8")
        except Exception:
            return None

    def _cmd_help(self, args: List[str]) -> CommandResult:
        """Show help."""
        help_text = """Available Commands:

Navigation:
  ls [path]                         List directory contents
  cd [path]                         Change directory
  pwd                               Print working directory
  tree [-L N] [--size] [path]       Show directory tree (--size shows file sizes)

Reading Files:
  cat [-n] <file>                   Print file contents (-n adds line numbers)
  readfile <file>                   Read any file (PDF, Excel, DOCX, PPTX, CSV, images, etc.)
  head [-n N] <file>                Print first N lines (default: 10)
  tail [-n N] <file>                Print last N lines (default: 10)
  sed -n '<start>,<end>p' <file>    Print specific line range
  wc [-lwc] <file|glob>             Count lines/words/chars
  stat <file|dir>                   Show file metadata (size, lines, modified)
  diff <file1> <file2>              Compare two files (unified diff)

Searching:
  grep [-rinlv] [-A N] [-B N] [-C N] [-e pat] <pattern> [path]
                                    Search for text pattern
  semgrep <query> [path]            Semantic search (by meaning)
  find <path> -name <pattern>       Find files by name
  find <path> -iname <pattern>      Find files (case-insensitive)

Writing:
  echo "text" > file                Write to file
  echo "text" >> file               Append to file
  mkdir [-p] <path>                 Create directory
  touch <file>                      Create empty file

System Info:
  date [+FORMAT]                    Print current date/time (e.g. date +%Y-%m-%d)
  whoami                            Print current user email
  hostname                          Print system hostname
  uname [-a|-s|-r|-m|-n]            Print system information
  uptime                            Print process uptime
  id                                Print user identity info

Environment:
  env [VARNAME]                     Print environment variables (secrets masked)
  printenv [VARNAME]                Same as env
  which <command>                   Check if command exists in shell
  type <command>                    Same as which

Text Processing:
  sort [-r] [-n] [-u] [-k N] [file] Sort lines (-r reverse, -n numeric, -u unique)
  uniq [-c] [-d] [-u] [file]       Remove adjacent duplicates (-c count)
  cut -d DELIM -f FIELDS [file]    Extract columns (e.g. cut -d ',' -f 1,3)
  cut -c CHARS [file]              Extract character positions
  tr [-d] SET1 [SET2] [file]       Translate/delete characters
  awk [-F DELIM] 'PROG' [file]     Pattern processing (print $1, NR, etc.)
  rev [file]                        Reverse each line
  tac [file]                        Print file in reverse (last line first)
  paste [-d DELIM] file1 file2     Merge files side by side
  nl [-ba] [file]                   Number lines
  column [-t] [-s DELIM] [file]    Columnate output (-t table mode)
  fold [-w WIDTH] [file]            Wrap lines to width (default: 80)
  expand [-t N] [file]              Convert tabs to spaces
  unexpand [-t N] [file]            Convert spaces to tabs

File / Disk Info:
  du [-h] [-s] [-d N] [path]       Disk usage (-h human, -s summary)
  df [-h]                           Disk free space
  file <path>                       Detect file type
  sha256sum <file> [file2 ...]      Compute SHA-256 checksum
  basename <path> [suffix]          Strip directory from path
  dirname <path>                    Strip filename from path
  realpath <path>                   Resolve to canonical virtual path

Math / Data:
  expr <expression>                 Evaluate math (e.g. expr 2 + 3)
  expr length "string"              String length
  expr substr "string" POS LEN      Substring
  seq [FIRST [INCR]] LAST           Print number sequence
  true                              Return success (exit 0)
  false                             Return failure (exit 1)

Networking (read-only):
  ping [-c N] <host>                ICMP ping (max 4 packets)
  nslookup <hostname>               DNS lookup
  curl [-s] [-I] <url>              HTTP GET (read-only, no POST/PUT/DELETE)

Vault Secrets:
  get_secret <key_name>             Get private (user) secret from vault
  get_secret --public <key_name>    Get public secret from vault
  get_secret --group <group> <key>  Get group secret from vault

Pipes (chain commands):
  grep "pattern" file | head -5     First 5 matches
  cat file | grep "word"            Search within file output
  cat file | sort | uniq -c         Count unique lines
  curl -s https://api.example.com | grep "key"   Search API response
  find / -name "*.md" | wc -l       Count matching files

Tips:
  - Use sed -n '45,60p' to read specific lines
  - Use grep -C 3 "pattern" to see context around matches
  - Use pipes to chain: grep "error" file | head -5
  - Use stat to check file size before reading
  - Use file <path> to check if a file is text or binary
  - Use du -h -s /agent to see total agent storage
  - Use date +%s for Unix timestamp
  - ALWAYS check pending_context before processing new requests
"""
        return CommandResult(True, help_text)
