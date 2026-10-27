"""
SafeKernel - The core execution engine for AgentOS.

This module implements the "Smart Shell" that parses and executes
Unix-like commands in a secure, sandboxed environment.
"""

import ast
import logging
import os
import platform
import re
import json
import shlex
import sys
import time
import gzip
import shutil
import subprocess
import threading
import weakref
import contextvars
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from collections import deque

# Prevent child processes from popping a console window on Windows, where the
# server runs under console-less pythonw.exe. Evaluates to 0 (no-op) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

from .safe_path import SafePath, SecurityError
from .path_ids import validate_path_id
from .vector_store import VectorStore
from .external_access import (
    match_http_resource,
    resource_for_database,
    resources_for_credential,
)
from .egress_ssrf import SSRFBlocked, assert_safe_url

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    pass


class FileLock:
    """
    Thread-safe file locking with optional OS-level locking.
    
    Uses threading.Lock for cross-thread safety and fcntl.flock
    for cross-process safety on Unix systems.
    """
    # WeakValueDictionary: entries are removed automatically when no thread holds
    # a reference to the lock, so the registry never grows unbounded.
    _locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
    _lock_registry = threading.Lock()

    @classmethod
    def get_lock(cls, file_path: Path) -> threading.Lock:
        """Get or create a lock for a specific file path."""
        path_str = str(file_path.resolve())
        with cls._lock_registry:
            lock = cls._locks.get(path_str)
            if lock is None:
                lock = threading.Lock()
                cls._locks[path_str] = lock
            return lock


class RateLimiter:
    """
    Sliding window rate limiter.
    
    Tracks command timestamps and rejects requests that exceed
    the configured rate.
    """
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in the window.
            window_seconds: Time window in seconds.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: deque = deque()
        self._lock = threading.Lock()
    
    def check(self) -> bool:
        """
        Check if a request is allowed.
        
        Returns:
            True if allowed, raises RateLimitExceeded if not.
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            while self.timestamps and self.timestamps[0] < window_start:
                self.timestamps.popleft()
            
            if len(self.timestamps) >= self.max_requests:
                oldest = self.timestamps[0]
                retry_after = int(oldest - window_start) + 1
                raise RateLimitExceeded(
                    f"Error [RATE_LIMITED]: Too many requests. "
                    f"Limit is {self.max_requests} commands per {self.window_seconds} seconds. "
                    f"Retry in {retry_after}s."
                )
            
            self.timestamps.append(now)
            return True
    
    def get_remaining(self) -> int:
        """Get remaining requests in current window."""
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            count = sum(1 for t in self.timestamps if t >= window_start)
            return max(0, self.max_requests - count)


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    output: str
    error_code: Optional[str] = None


class UserRole:
    """User role constants for RBAC."""
    USER = "user"           # Can only access own folder
    MANAGER = "manager"     # Can access team members' folders
    ADMIN = "admin"         # Can access all user folders
    AUDITOR = "auditor"     # Read-only access to everything


class TeamResolver:
    """
    Resolves team membership for RBAC.
    
    Supports three modes:
    - STATIC: Team members passed as a list at initialization
    - FILE: Team hierarchy loaded from a JSON file
    - CALLBACK: External function to resolve team members
    """
    
    MODE_STATIC = "static"
    MODE_FILE = "file"
    MODE_CALLBACK = "callback"
    
    def __init__(
        self,
        mode: str = MODE_STATIC,
        managed_users: Optional[List[str]] = None,
        team_file_path: Optional[Path] = None,
        resolver_callback: Optional[callable] = None
    ):
        """
        Initialize TeamResolver.
        
        Args:
            mode: Resolution mode (static, file, callback).
            managed_users: Static list of managed user IDs.
            team_file_path: Path to teams.json file.
            resolver_callback: Function(user_id, role) -> List[str] of managed users.
        """
        self.mode = mode
        self._managed_users = managed_users or []
        self._team_file_path = team_file_path
        self._resolver_callback = resolver_callback
        # Cache stores (result, inserted_at) per key so each entry has its own TTL.
        self._cache: Dict[str, Tuple[List[str], float]] = {}
        self._cache_ttl = 300  # 5 minutes per entry
    
    def get_managed_users(self, user_id: str, team_id: Optional[str] = None) -> List[str]:
        """
        Get list of users this user can manage/access.
        
        Args:
            user_id: The requesting user's ID.
            team_id: Optional team ID for file-based resolution.
            
        Returns:
            List of user IDs this user can access.
        """
        if self.mode == self.MODE_STATIC:
            return self._managed_users
        
        elif self.mode == self.MODE_FILE:
            return self._resolve_from_file(user_id, team_id)
        
        elif self.mode == self.MODE_CALLBACK:
            if self._resolver_callback:
                try:
                    return self._resolver_callback(user_id, team_id)
                except Exception as e:
                    logger.error("Team resolver callback failed: %s", e)
                    return []
            return []
        
        return []
    
    def _resolve_from_file(self, user_id: str, team_id: Optional[str]) -> List[str]:
        """Resolve team members from JSON file."""
        if not self._team_file_path or not self._team_file_path.exists():
            return []
        
        now = time.time()
        cache_key = f"{user_id}:{team_id}"
        entry = self._cache.get(cache_key)
        if entry is not None:
            cached_result, inserted_at = entry
            if (now - inserted_at) < self._cache_ttl:
                return cached_result
            del self._cache[cache_key]  # evict stale entry immediately
        
        try:
            with open(self._team_file_path, "r") as f:
                teams_data = json.load(f)
            
            # Expected JSON: {"teams": {id: {"manager": ..., "members": [...]}}, "admins": [...]}
            
            managed = []
            
            for tid, team_info in teams_data.get("teams", {}).items():
                if team_info.get("manager") == user_id:
                    managed.extend(team_info.get("members", []))
                if team_id and tid == team_id:
                    if user_id in team_info.get("members", []) or team_info.get("manager") == user_id:
                        managed.extend(team_info.get("members", []))
            
            managed = list(set(m for m in managed if m != user_id))
            
            self._cache[cache_key] = (managed, now)
            
            return managed
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Failed to load team file '%s': %s", self._team_file_path, e)
            return []


class AccessDeniedError(SecurityError):
    """Raised when user access is denied due to RBAC."""
    pass


class SafeKernel:
    """
    The Safe Kernel - Core execution engine for AgentOS.
    
    Provides a Unix-like shell interface that is:
    - Sandboxed to a specific directory tree
    - Permission-aware (read-only vs read-write)
    - Augmented with semantic search (semgrep)
    - Auto-indexing for memory files
    """
    
    BLOCKED_COMMANDS = [
        "rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp",
        "sudo", "su", "wget", "ssh", "scp", "rsync",
        "kill", "pkill", "killall", "shutdown", "reboot",
        "dd", "mkfs", "mount", "umount", "fdisk",
        "python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh"
    ]
    
    MAX_READ_BYTES = 50 * 1024  # 50KB
    MAX_READ_LINES = 100
    MAX_LIST_ITEMS = 100
    MAX_GREP_RESULTS = 50
    MAX_FIND_RESULTS = 100
    MAX_RECURSIVE_DEPTH = 5
    COMMAND_TIMEOUT = 30  # seconds
    
    DANGEROUS_OPERATORS = ["&&", "||", ";", "`", "$(", "${"]
    PIPE_OPERATOR = "|"
    # Only read-only text filters may follow `curl |`: no interpreters, exec-capable tools or file writers.
    ALLOWED_PIPE_FILTERS = {
        "grep", "egrep", "fgrep", "head", "tail", "wc",
        "sort", "uniq", "cut", "tr", "jq",
    }
    INVALID_FILENAME_CHARS = ["&&", "||", ";", "`", "$", "<", ">", "\n", "\r"]
    
    DEFAULT_RATE_LIMIT = 60  # commands per minute
    DEFAULT_RATE_WINDOW = 60  # seconds
    
    AUDIT_LOG_MAX_DAYS = 30  # keep logs for 30 days
    AUDIT_LOG_COMPRESS_AFTER_DAYS = 1  # compress logs older than 1 day
    
    def __init__(
        self,
        data_root: str,
        tenant_id: str,
        agent_id: str,
        user_id: Optional[str] = None,
        user_role: str = UserRole.USER,
        team_id: Optional[str] = None,
        managed_users: Optional[List[str]] = None,  # Option A: Static list
        team_file_path: Optional[str] = None,        # Option B: JSON file
        team_resolver_callback: Optional[callable] = None,  # Option C: External callback
        vector_store: Optional[VectorStore] = None,
        enable_audit_log: bool = True,
        rate_limit: Optional[int] = None,
        rate_window: Optional[int] = None,
        require_confirmation: bool = False,
        confirm_operations: Optional[List[str]] = None,  # ["write", "delete", "mkdir"]
        confirm_paths: Optional[List[str]] = None,  # ["/me/"] - paths requiring confirmation
        local_mount: Optional[str] = None,
        secret_provider: Optional[Any] = None,
    ):
        """
        Initialize the Safe Kernel.
        
        Args:
            data_root: Root directory for all data.
            tenant_id: Tenant/organization identifier.
            agent_id: Agent identifier.
            user_id: Current user's identifier (for RBAC).
            user_role: User's role - 'user', 'manager', 'admin', 'auditor'.
            team_id: User's team identifier.
            managed_users: Option A - Static list of user IDs this user can access.
            team_file_path: Option B - Path to teams.json for team hierarchy.
            team_resolver_callback: Option C - Function(user_id, team_id) -> List[str].
            vector_store: Optional VectorStore for semantic search.
            enable_audit_log: Whether to log all commands.
            rate_limit: Max commands per window (default: 60).
            rate_window: Rate limit window in seconds (default: 60).
            require_confirmation: If True, write ops need # CONFIRMED tag.
            confirm_operations: Which ops need confirmation - write, delete, mkdir.
            confirm_paths: Paths that require confirmation (e.g., ["/me/"]).
            local_mount: Optional real filesystem path to mount at /local.
            vault_provider: Optional provider used by get_credential.
        """
        validate_path_id(tenant_id, "tenant_id")
        validate_path_id(agent_id, "agent_id")
        if user_id:
            validate_path_id(user_id, "user_id")
        self.data_root = Path(data_root).resolve()
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.enable_audit_log = enable_audit_log
        self._secret_provider = secret_provider
        
        self.user_id = user_id
        self.user_role = user_role
        self.team_id = team_id
        # Context-local: SafeKernel is shared across session clones, so a plain attribute would race. Do not make _session_vars context-local.
        self._current_skill_cv: contextvars.ContextVar = contextvars.ContextVar(
            "kernel_current_skill", default=None
        )
        self.current_skill = None  # routes through the property setter below
        self.hook_runner = None
        self._hook_session_ctx_provider = None
        self.entitlement_principal = None
        self.entitlement_checker = None
        self.external_access_enabled = os.getenv(
            "EXTERNAL_ACCESS_ENABLED",
            os.getenv("ENTITLEMENTS_ENABLED", "false"),
        ).lower() == "true"
        self.external_access_unknown_mode = os.getenv("EXTERNAL_ACCESS_UNKNOWN_MODE", "audit").lower()
        self.external_access_audit_enabled = os.getenv("EXTERNAL_ACCESS_AUDIT_ENABLED", "true").lower() == "true"
        self.external_access_enforce_credentials = os.getenv(
            "EXTERNAL_ACCESS_ENFORCE_CREDENTIALS",
            str(self.external_access_enabled).lower(),
        ).lower() == "true"
        self.external_access_enforce_sql = os.getenv(
            "EXTERNAL_ACCESS_ENFORCE_SQL",
            str(self.external_access_enabled).lower(),
        ).lower() == "true"
        # Fail closed: with governance on, a kernel nobody bound to a principal denies every
        # governed action (egress, credentials, SQL) and logs it, instead of skipping the gates.
        self.entitlement_checker = self._default_entitlement_checker()
        
        self.require_confirmation = require_confirmation
        self.confirm_operations = confirm_operations or ["write", "delete"]
        self.confirm_paths = confirm_paths  # None means all paths
        
        self.tenant_root = self.data_root / "tenants" / tenant_id
        self.agent_root = self.tenant_root / "agents" / agent_id
        self.shared_path = self.tenant_root / "shared"
        self.tenant_user_root = self.tenant_root / "users"  # Global user profiles (tenant-level)
        self.global_shared = self.data_root / "global_shared"
        for _root in (self.tenant_root, self.agent_root):
            if not _root.resolve().is_relative_to(self.data_root):
                raise SecurityError("Error [PATH_ESCAPE]: root resolves outside data root")

        # Opt-in (AGENTOS_KERNEL_FILE_CACHE=1) mtime-validated read cache for cat/grep/wc; invalidated on write.
        self._file_cache_enabled = os.getenv("AGENTOS_KERNEL_FILE_CACHE", "").strip().lower() in ("1", "true", "on", "yes")
        self._file_cache: Dict[tuple, tuple] = {}          # (path, encoding, errors) -> (mtime, content)
        self._file_cache_lock = threading.Lock()
        self._FILE_CACHE_MAX_ENTRIES = 512
        self._FILE_CACHE_MAX_BYTES = 1_000_000             # don't cache files larger than ~1 MB

        if team_resolver_callback:
            self.team_resolver = TeamResolver(
                mode=TeamResolver.MODE_CALLBACK,
                resolver_callback=team_resolver_callback
            )
        elif team_file_path:
            self.team_resolver = TeamResolver(
                mode=TeamResolver.MODE_FILE,
                team_file_path=Path(team_file_path)
            )
        else:
            self.team_resolver = TeamResolver(
                mode=TeamResolver.MODE_STATIC,
                managed_users=managed_users or []
            )
        
        self.cwd = "/"

        # Session-scoped credential variable store — real values never sent to LLM
        # Populated by get_credential command; substituted into shell commands at execution time
        self._session_vars: dict = {}
        
        self.safe_path = SafePath(
            sandbox_root=self.agent_root,
            readonly_paths=[self.shared_path, self.global_shared]
        )
        
        # We need to handle shared paths specially - they're outside agent_root
        # but should still be accessible for reading
        self._accessible_readonly_roots = [self.shared_path, self.global_shared]
        
        if local_mount:
            _lm = Path(local_mount).resolve()
            if _lm.is_dir():
                self.local_mount = _lm
            else:
                logger.warning("Local mount path does not exist or is not a directory: %s", local_mount)
                self.local_mount = None
        else:
            self.local_mount = None
        
        self.python3_enabled = os.getenv("AGENT_PYTHON3_ENABLED", "false").lower() == "true"
        self.python3_sandbox_user = os.getenv("AGENT_PYTHON3_SANDBOX_USER", "").strip()
        self.python3_timeout = int(os.getenv("AGENT_PYTHON3_TIMEOUT", "30"))
        self.python3_max_memory_mb = int(os.getenv("AGENT_PYTHON3_MAX_MEMORY_MB", "512"))
        self.enterprise_strict_mode = os.getenv("ENTERPRISE_STRICT_MODE", "false").lower() == "true"

        # Untrusted multi-tenant guard: disables python3 so it falls through to BLOCKED_COMMANDS.
        self.untrusted_execution_guard = (
            os.getenv("AGENTOS_UNTRUSTED_EXECUTION_GUARD", "false").lower() == "true"
        )
        if self.untrusted_execution_guard and self.python3_enabled:
            import logging as _logging
            _logging.getLogger("agent_os.kernel").warning(
                "AGENTOS_UNTRUSTED_EXECUTION_GUARD=true — forcing python3 execution OFF "
                "(overrides AGENT_PYTHON3_ENABLED) for untrusted multi-tenant safety."
            )
            self.python3_enabled = False

        if self.python3_enabled and not self.python3_sandbox_user:
            if self.enterprise_strict_mode:
                raise RuntimeError(
                    "AGENT_PYTHON3_ENABLED=true requires AGENT_PYTHON3_SANDBOX_USER "
                    "when ENTERPRISE_STRICT_MODE=true"
                )
            import logging as _logging
            _logging.getLogger("agent_os.kernel").warning(
                "⚠️  SECURITY WARNING: AGENT_PYTHON3_ENABLED=true but AGENT_PYTHON3_SANDBOX_USER is not set. "
                "Agent Python3 code runs as the SERVER PROCESS USER with full file system access. "
                "For production, create a restricted OS user and set AGENT_PYTHON3_SANDBOX_USER=<username>. "
                "See config.env.example for setup instructions."
            )

        # Per-user rate limiters — keyed by user_id so one busy user can't starve others.
        self._rate_limit_max = rate_limit or self.DEFAULT_RATE_LIMIT
        self._rate_limit_window = rate_window or self.DEFAULT_RATE_WINDOW
        self._rate_limiters: Dict[str, RateLimiter] = {}
        
        if vector_store:
            self.vector_store = vector_store
        else:
            index_path = self.agent_root / ".index" / "vectors.json"
            self.vector_store = VectorStore(storage_path=index_path)
        
        # Prefer bundled vendor/bin ripgrep, then system PATH.
        _kernel_dir = Path(__file__).resolve().parent
        _bundled_rg = _kernel_dir / "vendor" / "bin" / ("rg.exe" if sys.platform == "win32" else "rg")
        if _bundled_rg.exists():
            self._rg_path = str(_bundled_rg)
            logger.info("Ripgrep (bundled) at %s - grep acceleration enabled", self._rg_path)
        else:
            self._rg_path = shutil.which("rg")
            if self._rg_path:
                logger.info("Ripgrep detected at %s - grep acceleration enabled", self._rg_path)
        
        self._bootstrap()
    
    def _bootstrap(self):
        """Create the directory structure on first run.
        
        Only scaffolds directories that are actively written to by code:
        - workspace/          : LLM writes work products via shell/write_file tool
        - memory/learnings/   : agent.py append_learning() writes JSONL per tool call
        - memory/history/     : memory.py log_episode() writes session JSONL
        - users/              : per-user profile.md read by _load_user_profile()
        - teams/              : team resolver (future)
        - .audit/             : kernel._log_command() writes audit JSONL
        - .index/             : VectorStore writes vectors.json
        - shared/policies/    : ar_ops skill reads validation rules
        - shared/knowledge/   : general skill browses tenant knowledge
        
        Note: memory/context_graph/, knowledge_index.db, master_index.json
        are created by memory.py on first access, not here.
        """
        dirs = [
            self.agent_root / "workspace",
            
            self.agent_root / "memory" / "learnings",
            self.agent_root / "memory" / "history",
            
            self.agent_root / "users",
            
            self.agent_root / "teams",
            
            self.agent_root / ".audit",
            self.agent_root / ".index",
            
            self.shared_path / "policies",
            self.shared_path / "knowledge",
            
            self.global_shared,
            
            self.tenant_user_root,
        ]
        
        # Skip service accounts: ':' in user_id is illegal in Windows directory names.
        if self.user_id and ":" not in self.user_id:
            user_folder = self.agent_root / "users" / self.user_id
            dirs.extend([user_folder, user_folder / "uploads"])

            global_user_folder = self.tenant_user_root / self.user_id
            dirs.append(global_user_folder)
        
        if self.team_id:
            team_folder = self.agent_root / "teams" / self.team_id
            dirs.append(team_folder)
        
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        
        if self.user_id and ":" not in self.user_id:
            global_profile_file = self.tenant_user_root / self.user_id / "profile.md"
            if not global_profile_file.exists():
                global_profile_template = f"""# Global Profile: {self.user_id}

## Identity
- **User ID:** {self.user_id}
- **Name:** 
- **Employer:** 
- **Role:** 
- **Timezone:** 

## Communication Style
<!-- How you prefer responses formatted/toned -->
<!-- e.g., "Concise answers preferred", "No emojis", "Tables over bullets" -->

## Technical Context
<!-- Your tech stack and coding conventions -->
<!-- e.g., "Python 3.11, macOS", "Prefers pytest", "Uses type hints" -->

## Known Facts
<!-- Explicit facts you've shared about yourself -->
<!-- e.g., "Working at Infosys", "Based in Bangalore" -->

## Pet Peeves
<!-- Things that frustrate you - applies across all agents -->
<!-- e.g., "Don't ask permission for reads", "Skip verbose preambles" -->

---
*This global profile applies to all agents. Agent-specific preferences are stored separately.*
*Last updated: {datetime.now().strftime('%Y-%m-%d')}*
"""
                global_profile_file.write_text(global_profile_template, encoding='utf-8')
            
            profile_file = self.agent_root / "users" / self.user_id / "profile.md"
            if not profile_file.exists():
                profile_template = f"""# Agent Profile: {self.user_id} @ {self.agent_id}

## Domain Context
<!-- Your expertise and context for THIS agent -->
<!-- e.g., "F&A Transformation lead", "Expert in O2C processes" -->

## Workflow Preferences
<!-- How you like to interact with THIS agent -->
<!-- e.g., "Show plan before execution", "Always include taxonomy reference" -->

## Learned Patterns
<!-- Naming conventions and patterns for THIS agent -->
<!-- e.g., "Client folders use underscores: ACME_Corp" -->

---
*This profile is specific to {self.agent_id}. Global preferences are in /me/global.md.*
*Last updated: {datetime.now().strftime('%Y-%m-%d')}*
"""
                profile_file.write_text(profile_template, encoding='utf-8')
    
    def _resolve_path(self, path: str) -> Path:
        """
        Resolve a virtual path to a real path.
        
        Handles special prefixes:
        - /me/global.md -> tenant-level global profile (facts, comm style, pet peeves)
        - /me/ -> current user's agent-specific folder (shortcut for /users/{user_id}/)
        - /team/ -> team folder
        - /users/{id}/ -> specific user folder (RBAC checked)
        - /shared/ -> tenant shared directory
        - /global/ -> global shared directory
        - /local/ -> user-configured external directory (desktop mode)
        - Everything else -> agent root
        """
        path = path.strip()
        
        if ".." in path:
            raise SecurityError(
                "Error [PATH_ESCAPE]: Access denied. "
                "Cannot navigate outside your sandbox using '..'"
            )
        
        if not path or path == ".":
            return self._resolve_cwd()
        
        if path.startswith("/"):
            virtual_path = path
        else:
            if self.cwd == "/":
                virtual_path = "/" + path
            else:
                virtual_path = self.cwd.rstrip("/") + "/" + path
        
        if virtual_path == "/me/global.md":
            if not self.user_id:
                raise SecurityError(
                    "Error [NO_USER]: /me/global.md requires user_id to be set."
                )
            return self.tenant_user_root / self.user_id / "profile.md"
        
        if virtual_path == "/me" or virtual_path.startswith("/me/"):
            if not self.user_id:
                raise SecurityError(
                    "Error [NO_USER]: /me/ path requires user_id to be set."
                )
            if virtual_path == "/me":
                virtual_path = f"/users/{self.user_id}"
            else:
                virtual_path = f"/users/{self.user_id}{virtual_path[3:]}"
        
        if virtual_path == "/team" or virtual_path.startswith("/team/"):
            if not self.team_id:
                raise SecurityError(
                    "Error [NO_TEAM]: /team/ path requires team_id to be set."
                )
            if virtual_path == "/team":
                virtual_path = f"/teams/{self.team_id}"
            else:
                virtual_path = f"/teams/{self.team_id}{virtual_path[5:]}"
        
        if virtual_path.startswith("/users/"):
            self._check_user_access(virtual_path)
        
        if virtual_path == "/shared" or virtual_path.startswith("/shared/"):
            if virtual_path == "/shared":
                return self.shared_path
            remainder = virtual_path[8:]  # Remove '/shared/'
            return self._contain(self.shared_path, remainder)
        elif virtual_path == "/global" or virtual_path.startswith("/global/"):
            if virtual_path == "/global":
                return self.global_shared
            remainder = virtual_path[8:]  # Remove '/global/'
            return self._contain(self.global_shared, remainder)
        elif virtual_path == "/local" or virtual_path.startswith("/local/"):
            if not self.local_mount:
                raise SecurityError(
                    "Error [NO_LOCAL_MOUNT]: No local folder configured. "
                    "Set a local folder path in Settings → Local Folder."
                )
            if virtual_path == "/local":
                return self.local_mount
            remainder = virtual_path[7:]  # Remove '/local/'
            return self._contain(self.local_mount, remainder)
        else:
            remainder = virtual_path.lstrip("/")
            return self._contain(self.agent_root, remainder)

    @staticmethod
    def _contain(base: Path, remainder: str) -> Path:
        """Join `remainder` under `base` and refuse any result that lands outside it.

        The '..' check above is not enough: `Path(base) / "/etc/x"` discards `base`
        entirely (so "/shared//etc/x" escaped), and a symlink can point anywhere.
        Both sides are resolved so a symlinked data root still compares correctly.
        """
        candidate = base / remainder.lstrip("/")
        try:
            candidate.resolve().relative_to(base.resolve())
        except ValueError:
            raise SecurityError(
                "Error [PATH_ESCAPE]: Access denied. "
                "That path resolves outside your sandbox."
            ) from None
        return candidate
    
    def _check_user_access(self, virtual_path: str):
        """
        Check if current user can access this /users/ path.
        
        Raises:
            AccessDeniedError: If access is not allowed.
        """
        if not self.user_id:
            return
        
        parts = virtual_path.split("/")
        if len(parts) < 3:
            return  # Just /users or /users/ - allow listing
        
        target_user = parts[2]
        
        if self.user_role == UserRole.ADMIN:
            return
        
        if self.user_role == UserRole.AUDITOR:
            return
        
        if target_user == self.user_id:
            return
        
        if self.user_role == UserRole.MANAGER:
            managed_users = self.team_resolver.get_managed_users(
                self.user_id, self.team_id
            )
            if target_user in managed_users:
                return
        
        raise AccessDeniedError(
            f"Error [ACCESS_DENIED]: User '{self.user_id}' cannot access "
            f"'/users/{target_user}/'. You can only access your own folder at '/me/'."
        )
    
    def _is_user_write_allowed(self, virtual_path: str) -> bool:
        """
        Check if current user can write to this path.
        
        Auditors cannot write anywhere.
        Users can only write to their own folder.
        Managers can write to their folder and team folders.
        Admins can write anywhere.
        """
        if self.user_role == UserRole.AUDITOR:
            return False
        
        if not self.user_id:
            return True
        
        if virtual_path.startswith("/users/"):
            parts = virtual_path.split("/")
            if len(parts) >= 3:
                target_user = parts[2]
                
                if target_user == self.user_id:
                    return True
                
                if self.user_role == UserRole.ADMIN:
                    return True
                
                if self.user_role == UserRole.MANAGER:
                    managed_users = self.team_resolver.get_managed_users(
                        self.user_id, self.team_id
                    )
                    if target_user in managed_users:
                        return True
                
                return False
        
        return True
    
    def _resolve_cwd(self) -> Path:
        """Resolve current working directory."""
        if self.cwd == "/":
            return self.agent_root
        
        if self.cwd.startswith("/shared/"):
            remainder = self.cwd[8:]
            return self.shared_path / remainder
        elif self.cwd.startswith("/global/"):
            remainder = self.cwd[8:]
            return self.global_shared / remainder
        else:
            return self.agent_root / self.cwd.lstrip("/")
    
    def _to_virtual_path(self, real_path: Path) -> str:
        """Convert a real path back to virtual path."""
        real_path = Path(real_path).resolve()
        
        try:
            relative = real_path.relative_to(self.shared_path)
            return "/shared/" + str(relative)
        except ValueError:
            pass
        
        try:
            relative = real_path.relative_to(self.global_shared)
            return "/global/" + str(relative)
        except ValueError:
            pass
        
        try:
            relative = real_path.relative_to(self.agent_root)
            if str(relative) == ".":
                return "/"
            return "/" + str(relative)
        except ValueError:
            return str(real_path)
    
    def _is_writable(self, virtual_path: str) -> bool:
        """
        Check if a virtual path is writable.
        
        Combines:
        - System-level checks (shared/global are read-only)
        - /local is writable (confirmation enforced separately)
        - User-level RBAC checks
        """
        if virtual_path.startswith("/shared/") or virtual_path.startswith("/global/"):
            return False
        
        if virtual_path.startswith("/local/") or virtual_path == "/local":
            return self.local_mount is not None
        
        if not self._is_user_write_allowed(virtual_path):
            return False
        
        return True
    
    # Allowlist regex for audit log filenames.
    _AUDIT_LOG_RE = re.compile(r'^commands(?:_\d{4}-\d{2}-\d{2})?\.jsonl(?:\.gz)?$')

    def _safe_audit_path(self, candidate: Path) -> Path:
        """Validate an audit log path before any filesystem operation.

        Centralised validator that Fortify can recognise as a sanitiser gate.
        Every ``open()``, ``gzip.open()``, ``copyfileobj()``, and ``unlink()``
        in audit log code MUST pass through this method first.

        Checks:
        1. Resolved path is inside the audit directory.
        2. Filename matches an allowlisted pattern.
        3. Path is not a symlink (TOCTOU defence).
        """
        audit_dir = (self.agent_root / ".audit").resolve()
        resolved = candidate.resolve()

        if not resolved.is_relative_to(audit_dir):
            raise ValueError(f"Audit path escapes audit directory: {candidate}")

        if not self._AUDIT_LOG_RE.fullmatch(resolved.name):
            raise ValueError(f"Invalid audit log file name: {resolved.name}")

        if candidate.is_symlink():
            raise ValueError(f"Audit log path is a symlink: {candidate}")

        return resolved

    def _safe_copy_audit_file(
        self, src: Path, dst: Path, *, compress: bool = False
    ) -> None:
        """Copy validated audit file content via an intermediate buffer.

        Both *src* and *dst* MUST have already passed through
        ``_safe_audit_path()``.  Reading into ``bytes`` first and writing
        from that buffer severs the Fortify data-flow taint from
        ``open(src)`` → ``shutil.copyfileobj()`` → ``open(dst)`` (CWE-73).
        """
        _CHUNK = 64 * 1024
        data = src.read_bytes()
        if compress:
            with gzip.open(dst, 'wb') as f_out:
                for offset in range(0, len(data), _CHUNK):
                    f_out.write(data[offset:offset + _CHUNK])
        else:
            with open(dst, 'ab') as f_out:
                for offset in range(0, len(data), _CHUNK):
                    f_out.write(data[offset:offset + _CHUNK])

    def _get_audit_file_path(self, date: Optional[datetime] = None) -> Path:
        """Get the audit log file path for a specific date."""
        if date is None:
            date = datetime.now(timezone.utc)
        date_str = date.strftime("%Y-%m-%d")
        return self.agent_root / ".audit" / f"commands_{date_str}.jsonl"
    
    def _rotate_audit_logs(self):
        """
        Rotate and compress old audit logs.
        
        - Compress logs older than AUDIT_LOG_COMPRESS_AFTER_DAYS
        - Delete logs older than AUDIT_LOG_MAX_DAYS

        Every path is validated through _safe_audit_path() before any
        filesystem operation (open, gzip, copyfileobj, unlink).
        """
        audit_dir = self.agent_root / ".audit"
        if not audit_dir.exists():
            return
        
        now = datetime.now(timezone.utc)
        compress_threshold = now - timedelta(days=self.AUDIT_LOG_COMPRESS_AFTER_DAYS)
        delete_threshold = now - timedelta(days=self.AUDIT_LOG_MAX_DAYS)
        
        for log_file in audit_dir.glob("commands_*.jsonl"):
            try:
                safe_log = self._safe_audit_path(log_file)
            except ValueError:
                continue

            try:
                date_str = safe_log.stem.replace("commands_", "")
                log_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            
            if log_date < delete_threshold:
                safe_log.unlink(missing_ok=True)
                try:
                    safe_gz = self._safe_audit_path(log_file.with_suffix(".jsonl.gz"))
                    if safe_gz.exists():
                        safe_gz.unlink()
                except ValueError:
                    pass
                continue
            
            if log_date < compress_threshold:
                try:
                    safe_gz = self._safe_audit_path(log_file.with_suffix(".jsonl.gz"))
                except ValueError:
                    continue
                if not safe_gz.exists():
                    try:
                        self._safe_copy_audit_file(safe_log, safe_gz, compress=True)
                        safe_log.unlink()
                    except Exception as e:
                        logger.warning("Failed to compress audit log '%s': %s", safe_log, e)
        
        legacy_log = audit_dir / "commands.jsonl"
        if legacy_log.exists():
            try:
                safe_legacy = self._safe_audit_path(legacy_log)
                safe_today = self._safe_audit_path(self._get_audit_file_path())
                self._safe_copy_audit_file(safe_legacy, safe_today, compress=False)
                safe_legacy.unlink()
            except ValueError as e:
                logger.warning("Audit path validation failed: %s", e)
            except Exception as e:
                logger.warning("Failed to migrate legacy audit log: %s", e)
    
    def _log_command(self, command: str, result: str, success: bool, duration: float):
        """Log command to audit trail with file locking."""
        if not self.enable_audit_log:
            return
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "output_preview": result[:500] if result else "",
            "success": success,
            "duration_ms": int(duration * 1000)
        }
        
        audit_file = self._get_audit_file_path()
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        
        lock = FileLock.get_lock(audit_file)
        with lock:
            with open(audit_file, "a") as f:
                if HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(json.dumps(log_entry) + "\n")
                finally:
                    if HAS_FCNTL:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def set_entitlement_context(self, principal=None, checker=None):
        """Attach request-scoped entitlement context for kernel-level gates."""
        self.entitlement_principal = principal
        self.entitlement_checker = checker if checker is not None else self._default_entitlement_checker()

    def _default_entitlement_checker(self):
        """The checker used until a caller binds a principal.

        Every gate below is written `if not (enabled and self.entitlement_checker): allow`,
        so a None checker used to switch governance OFF for any code path that forgot to
        call set_entitlement_context(). With governance enabled we install a deny-all
        checker instead, which turns those gates on and names the unbound path in the log.
        """
        if not self.external_access_enabled:
            return None

        def _deny_unbound(action, resource_type, resource_id, context=None) -> bool:
            logger.warning(
                "Kernel governance: no principal bound for tenant=%s agent=%s user=%s — "
                "denying %s on %s:%s. The code path that built this agent must call "
                "set_entitlement_context().",
                self.tenant_id, self.agent_id, self.user_id, action, resource_type, resource_id,
            )
            return False

        _deny_unbound.unbound = True
        return _deny_unbound

    def _entitlement_allowed(self, action: str, resource_type: str, resource_id: str, context: dict | None = None) -> bool:
        if not self.entitlement_checker:
            return True
        try:
            return bool(self.entitlement_checker(action, resource_type, resource_id, context or {}))
        except Exception as exc:
            logger.warning("Kernel entitlement check failed for %s:%s action=%s: %s", resource_type, resource_id, action, exc)
            return False

    def _redact_external_text(self, text: str) -> str:
        text = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
        text = re.sub(r"(-u\s+)[^\s'\"]+", r"\1[REDACTED]", text)
        text = re.sub(r"(Authorization:\s*Basic\s+)[A-Za-z0-9+/=]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
        for var_name, real_value in self._session_vars.items():
            text = text.replace(real_value, f"${var_name}")
        return text

    def _audit_external_access(
        self,
        *,
        action: str,
        resource: str,
        allowed: bool,
        reason: str,
        command: str = "",
        metadata: dict | None = None,
    ) -> None:
        if not self.external_access_audit_enabled:
            return
        try:
            audit_path = self.shared_path / "databases" / "external_access_audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tenant_id": self.tenant_id,
                "agent_id": self.agent_id,
                "user_id": self.user_id,
                "skill": self.current_skill,
                "action": action,
                "resource": resource,
                "allowed": allowed,
                "reason": reason,
                "command_preview": self._redact_external_text(command)[:500] if command else "",
                "metadata": metadata or {},
            }
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            from agent_os.audit_log import emit_audit
            emit_audit("external_access", entry)  # SIEM export via OTel logs, if enabled
        except Exception as exc:
            logger.debug("External access audit skipped: %s", exc)

    def _external_resource_allowed(self, resource, action: str = "access", context: dict | None = None) -> bool:
        decision_context = {
            "label": getattr(resource, "label", ""),
            "risk": getattr(resource, "risk", ""),
            **(context or {}),
        }
        allowed = self._entitlement_allowed(action, resource.resource_type, resource.resource_id, decision_context)
        self._audit_external_access(
            action=action,
            resource=resource.id,
            allowed=allowed,
            reason="entitlement decision",
            metadata=decision_context,
        )
        return allowed

    @property
    def current_skill(self) -> Optional[str]:
        return self._current_skill_cv.get()

    @current_skill.setter
    def current_skill(self, value: Optional[str]) -> None:
        self._current_skill_cv.set(value)

    def _credential_allowed(self, credential_name: str) -> tuple[bool, str]:
        if not (self.external_access_enabled and self.external_access_enforce_credentials and self.entitlement_checker):
            return True, "external credential enforcement disabled"

        context = {"credential": credential_name, "skill": self.current_skill or self.agent_id}
        linked = resources_for_credential(self.tenant_root, credential_name)
        for resource in linked:
            if self._external_resource_allowed(resource, "access", context):
                return True, f"allowed via {resource.id}"

        if self._entitlement_allowed("use", "credential", credential_name, context):
            self._audit_external_access(
                action="use",
                resource=f"credential:{credential_name}",
                allowed=True,
                reason="direct credential override",
                metadata=context,
            )
            return True, "allowed via direct credential override"

        if not linked and self.external_access_unknown_mode != "deny":
            self._audit_external_access(
                action="use",
                resource=f"credential:{credential_name}",
                allowed=True,
                reason="unregistered credential allowed in audit mode",
                metadata=context,
            )
            return True, "unregistered credential allowed in audit mode"

        self._audit_external_access(
            action="use",
            resource=f"credential:{credential_name}",
            allowed=False,
            reason="no linked external resource or credential override allowed",
            metadata={**context, "linked_resources": [r.id for r in linked]},
        )
        return False, "credential access denied by external access policy"

    def database_allowed(self, database: str, operation: str = "read") -> tuple[bool, str]:
        """Check external DB entitlement for SQL tools and Python sqlite access."""
        if not (self.external_access_enabled and self.external_access_enforce_sql and self.entitlement_checker):
            return True, "external SQL enforcement disabled"
        action = "delete" if operation == "delete" else ("write" if operation == "write" else "read")
        context = {"database": database, "operation": operation, "skill": self.current_skill or self.agent_id}
        resource = resource_for_database(self.tenant_root, database)
        if resource:
            allowed = self._external_resource_allowed(resource, action, context)
            return (True, f"allowed via {resource.id}") if allowed else (False, f"database access denied for {resource.id}")
        if self.external_access_unknown_mode != "deny":
            self._audit_external_access(
                action=action,
                resource=f"external:db.{Path(str(database)).stem or 'unknown'}",
                allowed=True,
                reason="unregistered database allowed in audit mode",
                metadata=context,
            )
            return True, "unregistered database allowed in audit mode"
        self._audit_external_access(
            action=action,
            resource=f"external:db.{Path(str(database)).stem or 'unknown'}",
            allowed=False,
            reason="unregistered database denied",
            metadata=context,
        )
        return False, "database access denied by external access policy"

    @staticmethod
    def _curl_method(args: list[str]) -> str:
        for idx, arg in enumerate(args):
            if arg in {"-X", "--request"} and idx + 1 < len(args):
                return args[idx + 1].upper()
            if arg.startswith("-X") and len(arg) > 2:
                return arg[2:].upper()
        return "GET"

    # curl options that consume the NEXT argv token as their value. Their values must
    # never be mistaken for a request target (e.g. a header "Accept: x" or a data body).
    _CURL_VALUE_OPTS = {
        "-H", "--header", "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode",
        "-X", "--request", "-u", "--user", "-A", "--user-agent", "-e", "--referer",
        "-b", "--cookie", "-c", "--cookie-jar", "-m", "--max-time", "--connect-timeout",
        "--proto", "--proto-redir", "--noproxy", "-F", "--form", "-K", "--config",
        "--resolve", "--interface", "--cacert", "--capath", "--cert", "--key",
        "--retry", "--retry-delay", "--retry-max-time", "-o", "--output", "-T",
        "--upload-file", "--dump-header", "-D", "--trace", "--trace-ascii",
        "--write-out", "-w", "-y", "-Y", "--limit-rate",
    }
    _CURL_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://")
    _CURL_HOSTISH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*(?::\d{1,5})?(?:/.*)?$")

    @classmethod
    def _curl_targets(cls, args: list[str]) -> tuple[list[str], list[str]]:
        """Return (http_urls_to_govern, forbidden_scheme_targets).

        Previously only `^https?://` tokens were treated as targets, so three forms
        skipped governance entirely: a scheme-less host (`curl example.com/x` — curl
        silently prefixes http://), the `--url=<v>` form, and non-HTTP schemes
        (`file://`, `dict://169.254.169.254`, `gopher://`, `telnet://`).
        """
        urls: list[str] = []
        forbidden: list[str] = []
        skip_next = False
        for arg in args:
            if not isinstance(arg, str):
                continue
            if skip_next:
                skip_next = False
                continue
            if arg in cls._CURL_VALUE_OPTS:
                skip_next = True
                continue
            candidate = arg
            if arg.startswith("--url="):
                candidate = arg[len("--url="):]
            elif arg.startswith("-"):
                continue  # some other flag
            if not candidate:
                continue
            match = cls._CURL_SCHEME_RE.match(candidate)
            if match:
                if match.group(1).lower() in ("http", "https"):
                    urls.append(candidate)
                else:
                    forbidden.append(candidate)
                continue
            # Scheme-less token: curl would request http://<token>; require a dotted host or localhost.
            host_part = candidate.split("/", 1)[0]
            if cls._CURL_HOSTISH_RE.match(candidate) and (
                "." in host_part or host_part.split(":", 1)[0].lower() == "localhost"
            ):
                urls.append("http://" + candidate)
        return urls, forbidden

    @classmethod
    def _curl_urls(cls, args: list[str]) -> list[str]:
        """Back-compat shim: the governed HTTP(S) targets only."""
        return cls._curl_targets(args)[0]

    def _check_http_external_access(self, args: list[str], command: str) -> tuple[bool, str]:
        """Audit and optionally deny curl targets matched by external_access.yaml."""
        if not (self.external_access_enabled and self.entitlement_checker):
            return True, "external HTTP governance disabled"
        # Refuse connection overrides (--resolve, --connect-to) that bypass the DNS-based SSRF check.
        for a in args:
            if isinstance(a, str) and (
                a in ("--resolve", "--connect-to")
                or a.startswith("--resolve=")
                or a.startswith("--connect-to=")
            ):
                opt = a.split("=", 1)[0]
                self._audit_external_access(
                    action="access",
                    resource="external:connection_override",
                    allowed=False,
                    reason=f"curl connection override {opt} is not permitted (bypasses SSRF target validation)",
                    command=command,
                    metadata={"skill": self.current_skill or self.agent_id},
                )
                return False, f"curl connection override {opt} is not permitted"
        method = self._curl_method(args)
        urls, forbidden = self._curl_targets(args)
        if forbidden:
            # Non-HTTP(S) schemes are never legitimate here and cannot be matched
            # against the HTTP registry, so they are refused outright in every mode.
            self._audit_external_access(
                action="access",
                resource="external:forbidden_scheme",
                allowed=False,
                reason="non-HTTP(S) scheme is not permitted",
                command=command,
                metadata={"target": forbidden[0], "skill": self.current_skill or self.agent_id},
            )
            return False, f"non-HTTP(S) scheme is not permitted: {forbidden[0]}"
        if not urls:
            return True, "no URL detected"

        for url in urls:
            resource = match_http_resource(self.tenant_root, url, method)
            context = {"url": url, "method": method, "skill": self.current_skill or self.agent_id}

            # SSRF check covers every target; allow_loopback only for registered targets, never metadata/private ranges.
            try:
                assert_safe_url(url, allow_loopback=bool(resource))
            except SSRFBlocked as exc:
                self._audit_external_access(
                    action="access",
                    resource=(resource.id if resource else "external:unknown"),
                    allowed=False,
                    reason=f"SSRF guard: {exc}",
                    command=command,
                    metadata=context,
                )
                return False, f"external access denied (SSRF guard): {exc}"

            if resource:
                allowed = self._external_resource_allowed(resource, "access", context)
                # An explicit entitlement DENY is honoured in every mode.
                if not allowed:
                    return False, f"external access denied for {resource.id}"
            elif self.external_access_unknown_mode == "deny":
                self._audit_external_access(
                    action="access",
                    resource="external:unknown",
                    allowed=False,
                    reason="unknown external target denied",
                    command=command,
                    metadata=context,
                )
                return False, f"external target is not registered: {url}"
            else:
                self._audit_external_access(
                    action="access",
                    resource="external:unknown",
                    allowed=True,
                    reason="unknown external target allowed in audit mode",
                    command=command,
                    metadata=context,
                )
        return True, "external HTTP governance passed"
    
    def run_shell_command(self, command: str, confirmed: bool = False, user_id: str = "") -> str:
        """
        Main entry point - execute a shell command.
        
        Args:
            command: The command string to execute.
            confirmed: If True, skip confirmation for write operations.
                      Set to True only after user explicitly approves.
            
        Returns:
            Command output as string.
        """
        start_time = time.time()
        command = command.strip()
        
        if not command:
            return "Error: Empty command."
        
        # Rate limiting check (per-user bucket; empty user_id = shared bucket for callers
        # that don't supply one, e.g. legacy cron/queue workers)
        bucket = user_id or "_shared"
        if bucket not in self._rate_limiters:
            self._rate_limiters[bucket] = RateLimiter(
                max_requests=self._rate_limit_max,
                window_seconds=self._rate_limit_window,
            )
        try:
            self._rate_limiters[bucket].check()
        except RateLimitExceeded as e:
            return str(e)
        
        try:
            self._rotate_audit_logs()
        except Exception as e:
            logger.warning("Audit log rotation failed: %s", e)
            pass  # Don't fail command on rotation error
        
        try:
            result = self._execute(command, confirmed=confirmed)
            duration = time.time() - start_time
            self._log_command(command, result, True, duration)
            return result
        except SecurityError as e:
            duration = time.time() - start_time
            self._log_command(command, str(e), False, duration)
            return str(e)
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Error [INTERNAL]: {str(e)}"
            self._log_command(command, error_msg, False, duration)
            return error_msg
    
    def _read_text_cached(self, resolved: Path, encoding: str = "utf-8", errors: Optional[str] = None) -> str:
        """Read a file's text. When the file cache is enabled, serve from an in-process
        cache if the file is unchanged (mtime-validated → NEVER returns stale content);
        otherwise this is a plain read. Used only by full-content readers (cat/grep/wc/
        semgrep) — directory listings and partial reads (head/tail) are not cached."""
        def _read() -> str:
            return resolved.read_text(encoding=encoding) if errors is None \
                else resolved.read_text(encoding=encoding, errors=errors)
        if not self._file_cache_enabled:
            return _read()
        key = (str(resolved), encoding, errors)
        try:
            mtime = resolved.stat().st_mtime
        except OSError:
            return _read()  # can't stat → read directly, don't cache
        with self._file_cache_lock:
            hit = self._file_cache.get(key)
            if hit is not None and hit[0] == mtime:
                return hit[1]
        content = _read()
        if len(content) <= self._FILE_CACHE_MAX_BYTES:
            with self._file_cache_lock:
                if len(self._file_cache) >= self._FILE_CACHE_MAX_ENTRIES:
                    self._file_cache.clear()   # simple bound to avoid unbounded growth
                self._file_cache[key] = (mtime, content)
        return content

    def _invalidate_file_cache(self, resolved) -> None:
        """Drop any cached content for a path after it is written (keeps the cache correct
        for the writing instance; other instances/external edits are caught by mtime)."""
        if not self._file_cache_enabled:
            return
        p = str(resolved)
        with self._file_cache_lock:
            for k in [k for k in self._file_cache if k[0] == p]:
                self._file_cache.pop(k, None)

    def write_file(self, virtual_path: str, content: bytes | str, append: bool = False) -> str:
        """
        Write content directly to a file (bypasses shell parsing).
        
        This is the safe way to write arbitrary content that may contain
        shell special characters like backticks, $(), etc.
        
        Args:
            virtual_path: Virtual path like /me/uploads/file.txt
            content: File content (str or bytes)
            append: If True, append to existing file
            
        Returns:
            Success message or error string starting with "Error"
        """
        if not virtual_path.startswith("/"):
            virtual_path = self.cwd.rstrip("/") + "/" + virtual_path
        
        if not self._is_writable(virtual_path):
            return f"Error [PERMISSION_DENIED]: Cannot write to '{virtual_path}'. This directory is read-only."
        
        try:
            resolved = self._resolve_path(virtual_path)
        except SecurityError as e:
            return str(e)
        
        resolved.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(content, str):
            mode = "a" if append else "w"
            encoding = "utf-8"
        else:
            mode = "ab" if append else "wb"
            encoding = None
        
        lock = FileLock.get_lock(resolved)
        try:
            with lock:
                if encoding:
                    with open(resolved, mode, encoding=encoding) as f:
                        if HAS_FCNTL:
                            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                        try:
                            f.write(content)
                        finally:
                            if HAS_FCNTL:
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                else:
                    with open(resolved, mode) as f:
                        if HAS_FCNTL:
                            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                        try:
                            f.write(content)
                        finally:
                            if HAS_FCNTL:
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            return f"Error [WRITE_FAILED]: {str(e)}"

        # Drop any cached copy so subsequent cat/grep see the new content immediately.
        self._invalidate_file_cache(resolved)

        if "/memory/" in virtual_path and isinstance(content, str):
            self._index_file(resolved)
            return f"Wrote to {virtual_path} (indexed to memory)"
        
        return f"Wrote to {virtual_path}"

    def delete_file(self, virtual_path: str) -> str:
        """
        Delete a single file within the sandbox.

        Mirrors write_file's permission and path-resolution guards. Directories
        are refused here so a stray path can never wipe a folder tree.

        Returns a success message or an error string starting with "Error".
        """
        if not virtual_path.startswith("/"):
            virtual_path = self.cwd.rstrip("/") + "/" + virtual_path

        # Delete is a write-class mutation, so honor read-only directories.
        if not self._is_writable(virtual_path):
            return f"Error [PERMISSION_DENIED]: Cannot delete '{virtual_path}'. This directory is read-only."

        try:
            resolved = self._resolve_path(virtual_path)
        except SecurityError as e:
            return str(e)

        if not resolved.exists():
            return f"Error [NOT_FOUND]: '{virtual_path}' does not exist."
        if resolved.is_dir():
            return f"Error [IS_DIRECTORY]: '{virtual_path}' is a directory, not a file."

        lock = FileLock.get_lock(resolved)
        try:
            with lock:
                resolved.unlink()
        except Exception as e:
            return f"Error [DELETE_FAILED]: {str(e)}"

        self._invalidate_file_cache(resolved)
        return f"Deleted {virtual_path}"

    # Legacy confirmation tag (kept for backward compatibility)
    CONFIRMATION_TAG = "# CONFIRMED"
    
    def _requires_confirmation(self, command: str, cmd: str, args: List[str], redirect: Optional[Dict], confirmed: bool = False) -> Optional[str]:
        """
        Check if a command requires user confirmation.
        
        Args:
            command: The full command string
            cmd: The parsed command name
            args: Command arguments
            redirect: Redirect info if present
            confirmed: If True, user has approved this operation
        
        Returns:
            None if no confirmation needed, or an error message asking for confirmation.
        """
        if not self.require_confirmation:
            return None
        
        if confirmed or self.CONFIRMATION_TAG in command:
            return None
        
        operation = None
        target_path = None
        
        if redirect:  # echo "..." > file or echo "..." >> file
            operation = "write"
            target_path = redirect["target"]
        elif cmd == "rm":
            operation = "delete"
            target_path = args[0] if args else None
        elif cmd == "mkdir":
            operation = "mkdir"
            for arg in args:
                if not arg.startswith("-"):
                    target_path = arg
                    break
        elif cmd == "touch":
            operation = "write"
            target_path = args[0] if args else None
        
        if operation not in self.confirm_operations:
            return None
        
        if self.confirm_paths and target_path:
            if not target_path.startswith("/"):
                target_path = self.cwd.rstrip("/") + "/" + target_path
            
            path_matches = any(target_path.startswith(cp) for cp in self.confirm_paths)
            if not path_matches:
                return None
        
        return (
            f"⚠️ CONFIRMATION REQUIRED\n"
            f"Operation: {operation}\n"
            f"Target: {target_path or 'unknown'}\n"
            f"Command: {command}\n\n"
            f"Ask user for approval, then call again with confirmed=True"
        )
    
    # Only these commands need a real secret; substituting elsewhere would echo plaintext back to the model.
    _CRED_SUBSTITUTION_COMMANDS = ("curl",)

    def _command_allows_credentials(self, command: str) -> bool:
        head = command.lstrip().split(None, 1)[0] if command.strip() else ""
        return head in self._CRED_SUBSTITUTION_COMMANDS

    def _substitute_session_vars(self, command: str) -> str:
        """Replace $CRED_* placeholders with real values from the session store.

        Scoped to credential-consuming commands (see _CRED_SUBSTITUTION_COMMANDS).
        For any other command the placeholder is left intact, so the secret never
        becomes echo-able / cat-able output.
        """
        if not self._session_vars:
            return command
        if not self._command_allows_credentials(command):
            return command
        for var_name, real_value in self._session_vars.items():
            command = command.replace(f"${var_name}", real_value)
        return command

    def set_secret_provider(self, secret_provider) -> None:
        """Attach a request/tenant scoped vault provider."""
        self._secret_provider = secret_provider

    def _credential_config_dir(self) -> Path:
        """Discover the tenant shared config directory used by local credentials."""
        agent_root = Path(self.agent_root)
        shared_config = agent_root.parent.parent / "shared" / "config"
        if shared_config.exists():
            return shared_config
        for parent in [agent_root] + list(agent_root.parents):
            candidate = parent / "enterprise_root"
            if candidate.exists():
                return candidate / "tenants" / "company" / "shared" / "config"
        return shared_config

    def _get_secret_provider(self):
        if self._secret_provider is None:
            from .secret_provider import build_secret_provider
            self._secret_provider = build_secret_provider(config_dir=self._credential_config_dir())
        return self._secret_provider

    @staticmethod
    def _safe_secret_error(exc: Exception) -> str:
        error_name = type(exc).__name__
        if "unavailable" in error_name.lower() or "timeout" in str(exc).lower():
            return "secret provider unavailable"
        return f"secret provider error ({error_name})"

    def attach_hook_runner(self, hook_runner, session_ctx_provider=None) -> None:
        self.hook_runner = hook_runner
        self._hook_session_ctx_provider = session_ctx_provider

    def _kernel_hook_session_ctx(self, tool_name: str = "") -> dict:
        current_skill = self.current_skill or ""
        ctx = {
            "tenant_id": self.tenant_id or "",
            "agent_id": self.agent_id or "",
            "user_id": self.user_id or "",
            "skill_name": current_skill,
            "current_skill": current_skill,
            "entrypoint": "kernel",
            "tool_name": tool_name or "",
        }
        provider = self._hook_session_ctx_provider
        if provider:
            try:
                provided = provider()
                if isinstance(provided, dict):
                    for key, value in provided.items():
                        if value not in (None, ""):
                            ctx[key] = value
            except Exception as exc:
                logger.debug("Kernel hook session context provider failed: %s", exc)
        ctx.setdefault("entrypoint", "kernel")
        if not ctx.get("entrypoint"):
            ctx["entrypoint"] = "kernel"
        return ctx

    def _fire_kernel_post_tool(self, tool_name: str, tool_input, output_summary: str) -> None:
        runner = getattr(self, "hook_runner", None)
        if not runner:
            return
        try:
            runner.run_post_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=str(output_summary or "")[:2000],
                session_ctx=self._kernel_hook_session_ctx(tool_name),
            )
        except Exception as exc:
            logger.debug("Kernel PostToolUse hook failed for %s: %s", tool_name, exc)

    def _cmd_get_credential(self, args: list) -> str:
        """
        Load a credential field into the session variable store.

        Usage: get_credential <name> <field>
        Example: get_credential ccd_k8s_api token

        Returns a masked variable name to the LLM — real value is never in LLM context.
        Use $CRED_<NAME>_<FIELD> in subsequent shell commands; kernel substitutes at runtime.
        """
        if len(args) < 2:
            self._fire_kernel_post_tool("get_credential", {"args_count": len(args)}, "USAGE")
            return ("Error [get_credential]: Usage: get_credential <name> <field>  "
                    "(for a Vault connection: get_credential <conn> <key> <vault_path>)")
        cred_name, field = args[0], args[1]
        # Optional 3rd arg = Vault KV path -> resolve <key> live from the scoped
        # `type: vault` connection named <conn>, instead of a local credential field.
        vault_path = args[2] if len(args) >= 3 else None
        hook_input = {"name": cred_name, "field": field}
        runner = getattr(self, "hook_runner", None)
        if runner:
            try:
                gate = runner.run_pre_tool(
                    "get_credential",
                    hook_input,
                    self._kernel_hook_session_ctx("get_credential"),
                )
                if getattr(gate, "blocked", False):
                    reason = getattr(gate, "reason", "blocked by hook") or "blocked by hook"
                    self._fire_kernel_post_tool("get_credential", hook_input, "BLOCKED")
                    return f"Error [get_credential]: {reason}"
            except Exception as exc:
                logger.debug("Kernel PreToolUse hook failed for get_credential: %s", exc)
        try:
            allowed, reason = self._credential_allowed(cred_name)
            if not allowed:
                self._fire_kernel_post_tool("get_credential", hook_input, "DENIED")
                return f"Error [get_credential]: {reason}"
            provider = self._get_secret_provider()
            if vault_path is not None:
                resolver = getattr(provider, "resolve_vault_secret", None)
                if not callable(resolver):
                    self._fire_kernel_post_tool("get_credential", hook_input, "VAULT_UNAVAILABLE")
                    return "Error [get_credential]: Vault resolution is not available for this provider"
                cred = resolver(
                    cred_name,
                    vault_path,
                    field,
                    consumer=self.current_skill or self.agent_id,
                    accessor=self.user_id or self.agent_id,
                    purpose="kernel get_credential (vault)",
                )
                if not cred:
                    self._fire_kernel_post_tool("get_credential", hook_input, "NOT_FOUND")
                    return (f"Error [get_credential]: Vault secret '{field}' at path '{vault_path}' via "
                            f"connection '{cred_name}' not found (missing / scope-denied / read failed)")
                value = cred.value.get(field)
                if not value:
                    self._fire_kernel_post_tool("get_credential", hook_input, "FIELD_NOT_FOUND")
                    return f"Error [get_credential]: Key '{field}' not present in secret at '{vault_path}'"
                var_name = f"CRED_{cred_name.upper()}_{field.upper()}"
                self._session_vars[var_name] = value
                self._fire_kernel_post_tool("get_credential", hook_input, f"LOADED:${var_name}")
                return f"✓ Credential loaded as ${var_name}"
            cred = provider.resolve(
                cred_name,
                consumer=self.current_skill or self.agent_id,
                accessor=self.user_id or self.agent_id,
                purpose="kernel get_credential",
            )
            if not cred:
                # resolve() returns None for both missing and scope-denied; re-check existence to tell the LLM the truth.
                try:
                    exists = cred_name in (provider.list_names("") or [])
                except Exception:
                    exists = False
                self._fire_kernel_post_tool("get_credential", hook_input, "NOT_FOUND")
                if exists:
                    return (f"Error [get_credential]: Credential '{cred_name}' exists but is "
                            f"not authorized for the current skill "
                            f"'{self.current_skill or self.agent_id}' (scope-restricted). "
                            f"It is NOT missing — do NOT ask the user to add it.")
                return f"Error [get_credential]: Credential '{cred_name}' not found"
            value = cred.value.get(field)
            if not value:
                self._fire_kernel_post_tool("get_credential", hook_input, "FIELD_NOT_FOUND")
                return f"Error [get_credential]: Field '{field}' not found in '{cred_name}'"
            var_name = f"CRED_{cred_name.upper()}_{field.upper()}"
            self._session_vars[var_name] = value
            self._fire_kernel_post_tool("get_credential", hook_input, f"LOADED:${var_name}")
            return f"✓ Credential loaded as ${var_name}"
        except Exception as e:
            self._fire_kernel_post_tool("get_credential", hook_input, f"ERROR:{type(e).__name__}")
            return f"Error [get_credential]: {self._safe_secret_error(e)}"

    def _execute(self, command: str, confirmed: bool = False) -> str:
        """Parse and execute a command."""
        clean_command = command.replace(self.CONFIRMATION_TAG, "").strip()

        clean_command = self._substitute_session_vars(clean_command)

        if clean_command.lstrip().startswith("get_credential"):
            args = clean_command.lstrip()[len("get_credential"):].split()
            return self._cmd_get_credential(args)

        # Fast-path for python3 — must come BEFORE _parse_command because
        # python code legitimately contains ; | && which are blocked operators.
        if self.python3_enabled and clean_command.lstrip().startswith("python3"):
            raw = clean_command.lstrip()[len("python3"):].lstrip()
            args = self._parse_python3_args(raw)
            return self._cmd_python3(args)

        # Piped curl is parsed without a shell; downstream stages must be read-only filters from ALLOWED_PIPE_FILTERS.
        stripped_clean = clean_command.lstrip()
        if stripped_clean.startswith("curl ") and self._has_unquoted_pipe(stripped_clean):
            try:
                all_tokens = shlex.split(stripped_clean)
            except ValueError as _e:
                return f"Error [PIPE]: could not parse command ({_e})."
            # Split the token stream into pipeline stages on bare '|' tokens (shlex keeps
            # quoted pipes inside their token, so only real pipe operators split here).
            stages: List[List[str]] = []
            current: List[str] = []
            for tok in all_tokens:
                if tok == "|":
                    stages.append(current)
                    current = []
                else:
                    current.append(tok)
            stages.append(current)
            if any(len(seg) == 0 for seg in stages):
                return "Error [PIPE]: empty pipeline stage."
            curl_seg = stages[0]
            downstream = stages[1:]
            for seg in downstream:
                prog = os.path.basename(seg[0]).lower()
                if prog not in self.ALLOWED_PIPE_FILTERS:
                    return (
                        f"Error [PIPE_BLOCKED]: '{seg[0]}' is not an allowed pipe target. "
                        f"Only `curl` piped into read-only filters "
                        f"({', '.join(sorted(self.ALLOWED_PIPE_FILTERS))}) is permitted. "
                        f"Piping downloaded content into an interpreter (python3/bash/sh/…) "
                        f"is blocked."
                    )
            # Bypass corporate proxies as _cmd_curl does; argv form means no shell interpretation.
            _noproxy = (
                os.getenv("CURL_NOPROXY") or os.getenv("NO_PROXY") or os.getenv("no_proxy", "")
            ).strip()
            if _noproxy and "--noproxy" not in curl_seg:
                curl_seg = [curl_seg[0], "--noproxy", _noproxy] + curl_seg[1:]
                logger.debug("Auto-injected --noproxy for piped curl (hosts=%s)", _noproxy)
            _curl_to = self._resolve_curl_timeout()
            if "--max-time" not in curl_seg and "-m" not in curl_seg:
                curl_seg = [curl_seg[0], "--max-time", str(_curl_to)] + curl_seg[1:]
            allowed, reason = self._check_http_external_access(curl_seg[1:], " ".join(curl_seg))
            if not allowed:
                return f"Error [EXTERNAL_ACCESS_DENIED]: {reason}"
            return self._run_argv_pipeline([curl_seg] + downstream)

        parsed = self._parse_command(clean_command)
        cmd = parsed["cmd"].lower()
        args = parsed["args"]
        redirect = parsed.get("redirect")
        
        if cmd in self.BLOCKED_COMMANDS:
            return f"Error [COMMAND_BLOCKED]: '{cmd}' is disabled for safety."
        
        confirmation_msg = self._requires_confirmation(command, cmd, args, redirect, confirmed=confirmed)
        if confirmation_msg:
            return confirmation_msg
        
        handlers = {
            "ls": self._cmd_ls,
            "dir": self._cmd_ls,
            "cd": self._cmd_cd,
            "pwd": self._cmd_pwd,
            "cat": self._cmd_cat,
            "head": self._cmd_head,
            "tail": self._cmd_tail,
            "grep": self._cmd_grep,
            "find": self._cmd_find,
            "mkdir": self._cmd_mkdir,
            "touch": self._cmd_touch,
            "echo": lambda a: self._cmd_echo(a, redirect),
            "semgrep": self._cmd_semgrep,
            "tree": self._cmd_tree,
            "wc": self._cmd_wc,
            "curl": lambda a: self._cmd_curl(a, redirect),
        }

        if self.python3_enabled:
            handlers["python3"] = self._cmd_python3

        if cmd not in handlers:
            return f"Error [UNKNOWN_COMMAND]: '{cmd}' not recognized. Supported: {', '.join(sorted(handlers.keys()))}"

        return handlers[cmd](args)

    def _run_argv_pipeline(self, stages: List[List[str]]) -> str:
        """Run a validated pipeline (`curl` → read-only filters) as argv arrays chained by
        OS pipes, with NO shell. Callers MUST have already validated that stages[0] is curl
        and every downstream stage[0] is in ALLOWED_PIPE_FILTERS."""
        procs: List[subprocess.Popen] = []
        try:
            prev_stdout = None
            for i, stage in enumerate(stages):
                p = subprocess.Popen(
                    stage,
                    stdin=prev_stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=_NO_WINDOW,
                )
                # Close our copy of the previous stage's stdout so it receives SIGPIPE
                # when a downstream filter (e.g. head) exits early.
                if prev_stdout is not None:
                    prev_stdout.close()
                prev_stdout = p.stdout
                procs.append(p)
            _pipe_timeout = max(60, self._resolve_curl_timeout() + 15)
            try:
                out, err = procs[-1].communicate(timeout=_pipe_timeout)
            except subprocess.TimeoutExpired:
                for p in procs:
                    p.kill()
                return f"Error [PIPE]: Command timed out ({_pipe_timeout}s)."
            # Reap upstream stages so they don't linger as zombies.
            for p in procs[:-1]:
                try:
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
            rc = procs[-1].returncode
            out = (out or "").strip()
            if rc == 0:
                return out if out else "(no matching lines)"
            if rc == 1 and not out:
                # grep/filters return 1 when no matches were found — not an error.
                return "(no matching lines found)"
            return out or (err or "").strip() or "(no output)"
        except FileNotFoundError as _e:
            return f"Error [PIPE]: command not found ({_e})."
        except Exception as _e:
            return f"Error [PIPE]: {_e}"
        finally:
            for p in procs:
                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass

    def _parse_command(self, command: str) -> Dict[str, Any]:
        """Parse a command string into components."""
        redirect = None
        
        for op in self.DANGEROUS_OPERATORS:
            if op in command:
                raise SecurityError(
                    f"Error [COMMAND_INJECTION]: '{op}' is not allowed in commands. "
                    f"Remove '{op}' and everything after it. "
                    "Run a single command with no chaining operators (no ||, &&, ;, |, $())."
                )
        
        # Pipes outside quotes are blocked, except curl | filter pipelines.
        if self._has_unquoted_pipe(command):
            stripped = command.lstrip()
            _safe_pipe_prefixes = ("curl ", "grep ")
            if not any(stripped.startswith(p) for p in _safe_pipe_prefixes):
                raise SecurityError(
                    f"Error [COMMAND_INJECTION]: Pipe '{self.PIPE_OPERATOR}' is not allowed. "
                    "Run each command separately. For filtering, use grep flags like -i instead of piping."
                )
        
        if " >> " in command:
            parts = command.split(" >> ", 1)
            command = parts[0]
            target = parts[1].strip()
            if (target.startswith("'") and target.endswith("'")) or \
               (target.startswith('"') and target.endswith('"')):
                target = target[1:-1]
            redirect = {"target": target, "append": True}
        elif " > " in command:
            parts = command.split(" > ", 1)
            command = parts[0]
            target = parts[1].strip()
            if (target.startswith("'") and target.endswith("'")) or \
               (target.startswith('"') and target.endswith('"')):
                target = target[1:-1]
            redirect = {"target": target, "append": False}
        
        tokens = self._tokenize(command)
        
        return {
            "cmd": tokens[0] if tokens else "",
            "args": tokens[1:],
            "redirect": redirect
        }
    
    def _tokenize(self, command: str) -> List[str]:
        """Tokenize command respecting quotes."""
        tokens = []
        current = ""
        in_quotes = False
        quote_char = None
        
        for char in command:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
            elif char == " " and not in_quotes:
                if current:
                    tokens.append(current)
                    current = ""
            else:
                current += char
        
        if current:
            tokens.append(current)
        
        return tokens
    
    def _has_unquoted_pipe(self, command: str) -> bool:
        """
        Check if command contains a pipe character outside quotes.
        
        Returns:
            True if pipe is found outside quotes, False otherwise.
        """
        in_quotes = False
        quote_char = None
        
        for char in command:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
            elif char == self.PIPE_OPERATOR and not in_quotes:
                return True
        
        return False
    
    
    def _cmd_ls(self, args: List[str]) -> str:
        """List directory contents."""
        show_all = "-a" in args or "-la" in args or "-al" in args
        long_format = "-l" in args or "-la" in args or "-al" in args
        recursive = "-R" in args
        
        path = "."
        for arg in args:
            if not arg.startswith("-"):
                path = arg
                break
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: '{path}' does not exist."
        
        if not resolved.is_dir():
            return f"Error: '{path}' is not a directory."
        
        items = []
        try:
            for item in sorted(resolved.iterdir()):
                if not show_all and item.name.startswith("."):
                    continue
                
                if long_format:
                    stat = item.stat()
                    size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d %H:%M")
                    type_char = "d" if item.is_dir() else "-"
                    items.append(f"{type_char}rw-r--r--  {size:>8}  {mtime}  {item.name}")
                else:
                    suffix = "/" if item.is_dir() else ""
                    items.append(item.name + suffix)
                
                if len(items) >= self.MAX_LIST_ITEMS:
                    items.append(f"... (truncated, showing first {self.MAX_LIST_ITEMS} items)")
                    break
        except PermissionError:
            return f"Error [PERMISSION_DENIED]: Cannot read directory '{path}'."
        
        if not items:
            return "(empty directory)"
        
        return "\n".join(items)
    
    def _cmd_cd(self, args: List[str]) -> str:
        """Change current directory."""
        if not args:
            self.cwd = "/"
            return "Changed to /"
        
        path = args[0]
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: Directory '{path}' does not exist."
        
        if not resolved.is_dir():
            return f"Error: '{path}' is not a directory."
        
        self.cwd = self._to_virtual_path(resolved)
        return f"Changed to {self.cwd}"
    
    def _cmd_pwd(self, args: List[str]) -> str:
        """Print working directory."""
        return self.cwd
    
    def _cmd_cat(self, args: List[str]) -> str:
        """Read file contents."""
        if not args:
            return "Error: cat requires a file path."
        
        path = args[0]
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: File '{path}' does not exist.\nSuggestion: Use 'ls' to see available files."
        
        if not resolved.is_file():
            return f"Error: '{path}' is not a file."
        
        try:
            content = self._read_text_cached(resolved, encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: '{path}' is not a text file."
        except PermissionError:
            return f"Error [PERMISSION_DENIED]: Cannot read file '{path}'."
        
        if len(content) > self.MAX_READ_BYTES:
            content = content[:self.MAX_READ_BYTES]
            content += f"\n\n... [OUTPUT TRUNCATED - File exceeds {self.MAX_READ_BYTES // 1024}KB. Use 'head', 'tail', or 'grep' to read specific sections.]"
        
        return content
    
    def _cmd_head(self, args: List[str]) -> str:
        """Read first N lines of a file."""
        n = 20  # default
        path = None
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    n = min(int(args[i + 1]), self.MAX_READ_LINES)
                except ValueError:
                    pass
                i += 2
            elif not args[i].startswith("-"):
                path = args[i]
                i += 1
            else:
                i += 1
        
        if not path:
            return "Error: head requires a file path."
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: File '{path}' does not exist."
        
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= n:
                        break
                    lines.append(line.rstrip())
            return "\n".join(lines)
        except Exception as e:
            return f"Error reading file: {str(e)}"
    
    def _cmd_tail(self, args: List[str]) -> str:
        """Read last N lines of a file."""
        n = 20
        path = None
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    n = min(int(args[i + 1]), self.MAX_READ_LINES)
                except ValueError:
                    pass
                i += 2
            elif not args[i].startswith("-"):
                path = args[i]
                i += 1
            else:
                i += 1
        
        if not path:
            return "Error: tail requires a file path."
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: File '{path}' does not exist."
        
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return "".join(lines[-n:]).rstrip()
        except Exception as e:
            return f"Error reading file: {str(e)}"
    
    
    def _rg_search(self, pattern: str, resolved_path: Path, flags: dict) -> Optional[str]:
        """
        Fast grep using ripgrep (rg) subprocess.
        
        Security model:
        - resolved_path is ALREADY validated by _resolve_path() before this is called
        - rg only searches within the sandboxed resolved path
        - Output paths are converted back to virtual paths via _to_virtual_path()
        - Any rg failure returns None → triggers Python fallback
        
        Args:
            pattern: The search pattern (raw, before regex compilation)
            resolved_path: Already-sandboxed real filesystem path
            flags: Dict of grep flags parsed by _cmd_grep
            
        Returns:
            Formatted output string, or None to signal fallback to Python grep
        """
        cmd = [self._rg_path, "--no-heading", "--color=never"]
        
        if flags.get("ignore_case"):       cmd.append("-i")
        if flags.get("show_line_nums"):    cmd.append("-n")
        if flags.get("count_only"):        cmd.append("-c")
        if flags.get("files_only"):        cmd.append("-l")
        if flags.get("files_without_match"): cmd.append("--files-without-match")
        if flags.get("invert_match"):      cmd.append("-v")
        if flags.get("whole_word"):        cmd.append("-w")
        if flags.get("whole_line"):        cmd.append("--line-regexp")
        if flags.get("only_matching"):     cmd.append("-o")
        if flags.get("fixed_string"):      cmd.append("-F")
        if flags.get("quiet_mode"):        cmd.append("-q")
        if flags.get("hide_filename"):     cmd.append("--no-filename")
        
        if not flags.get("recursive") and resolved_path.is_dir():
            cmd.append("--max-depth=1")
        
        if flags.get("after_context"):
            cmd += ["-A", str(flags["after_context"])]
        if flags.get("before_context"):
            cmd += ["-B", str(flags["before_context"])]
        
        if flags.get("max_count"):
            cmd += ["-m", str(flags["max_count"])]
        
        if flags.get("include_pattern"):
            cmd += ["--glob", flags["include_pattern"]]
        if flags.get("exclude_pattern"):
            cmd += ["--glob", f"!{flags['exclude_pattern']}"]
        
        cmd += ["--", pattern, str(resolved_path)]
        
        try:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.COMMAND_TIMEOUT,
                    creationflags=_NO_WINDOW,
                )
            except OSError as _e:
                import errno as _errno
                if _e.errno == _errno.EAGAIN:
                    logger.warning("rg EAGAIN — retrying single-threaded")
                    result = subprocess.run(
                        cmd + ["--threads=1"],
                        capture_output=True,
                        text=True,
                        timeout=self.COMMAND_TIMEOUT,
                        creationflags=_NO_WINDOW,
                    )
                else:
                    raise

            # rg exit codes: 0=matches found, 1=no matches, 2+=error
            if result.returncode > 1:
                return None
            
            if flags.get("quiet_mode"):
                return ""
            
            output = result.stdout.strip()
            
            if not output:
                if flags.get("count_only"):
                    return "0"
                return f"No matches found for '{pattern}'."
            
            output = self._rg_convert_paths(output, resolved_path)
            
            lines = output.split("\n")
            if len(lines) > self.MAX_GREP_RESULTS:
                output = "\n".join(lines[:self.MAX_GREP_RESULTS])
                output += f"\n... (truncated at {self.MAX_GREP_RESULTS} results)"
            
            return output
            
        except subprocess.TimeoutExpired:
            return None
        except (FileNotFoundError, OSError, Exception):
            return None
    
    def _rg_convert_paths(self, output: str, search_root: Path) -> str:
        """
        Convert real filesystem paths in ripgrep output to virtual paths.
        
        Handles all output formats:
        - "/real/path/file.txt:10: content"  → "/virtual/file.txt:10: content"
        - "/real/path/file.txt:3"            → "/virtual/file.txt:3"  (count mode)
        - "/real/path/file.txt"              → "/virtual/file.txt"    (files-only)
        
        Uses the kernel's _to_virtual_path() for correct /shared/, /global/, /me/ mapping.
        """
        search_root_str = str(search_root.resolve())
        lines = output.split("\n")
        converted = []
        
        for line in lines:
            if line == "--":
                converted.append(line)
                continue
            
            if line.startswith(search_root_str) or line.startswith(str(search_root)):
                remainder = line[len(search_root_str):]
                if remainder.startswith("/"):
                    remainder = remainder[1:]
                
                # File paths could contain ':', so reconstruct from search_root.
                colon_pos = -1
                test_path = search_root
                parts = remainder.split(":")
                
                for i, part in enumerate(parts):
                    if i == 0:
                        candidate = search_root / part
                    else:
                        candidate = search_root / ":".join(parts[:i+1])
                    
                    if candidate.exists():
                        test_path = candidate
                        colon_pos = len(":".join(parts[:i+1]))
                    else:
                        break
                
                virtual_path = self._to_virtual_path(test_path)
                
                after_path = remainder[colon_pos:] if colon_pos >= 0 else ""
                converted.append(f"{virtual_path}{after_path}")
            else:
                converted.append(line)
        
        return "\n".join(converted)
    
    def _cmd_grep(self, args: List[str]) -> str:
        """Search for pattern in files.
        
        Supported flags:
            -r, -R    Recursive search into subdirectories
            -i        Case-insensitive matching
            -n        Show line numbers
            -c        Count matches only (per file)
            -l        List matching filenames only
            -L        List non-matching filenames only
            -v        Invert match (show non-matching lines)
            -w        Match whole words only
            -x        Match whole lines only
            -o        Show only the matching part of lines
            -h        Hide filenames in output
            -H        Show filenames in output (default for multi-file)
            -A NUM    Show NUM lines after each match
            -B NUM    Show NUM lines before each match
            -C NUM    Show NUM lines before and after each match
            -F        Fixed string match (disable regex)
            -E        Extended regex (default, for compatibility)
            -q        Quiet mode (exit status only, no output)
            -s        Suppress error messages
            -m NUM    Stop after NUM matches per file
            --include=PATTERN  Only search files matching pattern
            --exclude=PATTERN  Skip files matching pattern
        """
        recursive = "-r" in args or "-R" in args
        ignore_case = "-i" in args
        show_line_nums = "-n" in args
        count_only = "-c" in args
        files_only = "-l" in args
        files_without_match = "-L" in args
        invert_match = "-v" in args
        whole_word = "-w" in args
        whole_line = "-x" in args
        only_matching = "-o" in args
        hide_filename = "-h" in args
        show_filename = "-H" in args
        fixed_string = "-F" in args
        quiet_mode = "-q" in args
        suppress_errors = "-s" in args
        
        after_context = 0
        before_context = 0
        max_count = None
        include_pattern = None
        exclude_pattern = None
        
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ("-A", "-B", "-C", "-m") and i + 1 < len(args):
                try:
                    num = int(args[i + 1])
                    if arg == "-A":
                        after_context = num
                    elif arg == "-B":
                        before_context = num
                    elif arg == "-C":
                        before_context = after_context = num
                    elif arg == "-m":
                        max_count = num
                    i += 2
                    continue
                except ValueError:
                    pass
            elif arg.startswith("--include="):
                include_pattern = arg[10:]
            elif arg.startswith("--exclude="):
                exclude_pattern = arg[10:]
            i += 1
        
        non_flag_args = []
        skip_next = False
        for idx, a in enumerate(args):
            if skip_next:
                skip_next = False
                continue
            if a in ("-A", "-B", "-C", "-m"):
                skip_next = True
                continue
            if not a.startswith("-"):
                non_flag_args.append(a)
        
        if len(non_flag_args) < 1:
            return "Error: grep requires a pattern. Usage: grep [OPTIONS] 'pattern' [path]"
        
        pattern = non_flag_args[0]
        path = non_flag_args[1] if len(non_flag_args) > 1 else "."
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            if suppress_errors:
                return ""
            return f"Error [FILE_NOT_FOUND]: '{path}' does not exist."
        
        if fixed_string:
            pattern = re.escape(pattern)
        if whole_word:
            pattern = rf"\b{pattern}\b"
        if whole_line:
            pattern = rf"^{pattern}$"
        
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            if suppress_errors:
                return ""
            return f"Error: Invalid regex pattern: {str(e)}"
        
        # ripgrep fast path; any failure falls back to the Python implementation.
        if self._rg_path:
            rg_pattern = non_flag_args[0]
            rg_flags = {
                "recursive": recursive,
                "ignore_case": ignore_case,
                "show_line_nums": show_line_nums,
                "count_only": count_only,
                "files_only": files_only,
                "files_without_match": files_without_match,
                "invert_match": invert_match,
                "whole_word": whole_word,
                "whole_line": whole_line,
                "only_matching": only_matching,
                "hide_filename": hide_filename,
                "show_filename": show_filename,
                "fixed_string": fixed_string,
                "quiet_mode": quiet_mode,
                "after_context": after_context,
                "before_context": before_context,
                "max_count": max_count,
                "include_pattern": include_pattern,
                "exclude_pattern": exclude_pattern,
            }
            rg_result = self._rg_search(rg_pattern, resolved, rg_flags)
            if rg_result is not None:
                return rg_result
        
        results = []
        file_match_counts = {}
        files_with_matches = []
        files_without_matches = []
        total_matches = 0
        
        def should_include_file(file_path: Path) -> bool:
            """Check if file should be searched based on --include/--exclude."""
            name = file_path.name
            if include_pattern:
                import fnmatch
                if not fnmatch.fnmatch(name, include_pattern):
                    return False
            if exclude_pattern:
                import fnmatch
                if fnmatch.fnmatch(name, exclude_pattern):
                    return False
            return True
        
        def search_file(file_path: Path, virtual_path: str) -> bool:
            """Search a single file. Returns True if should stop searching."""
            nonlocal total_matches
            
            if not should_include_file(file_path):
                return False
            
            try:
                lines = self._read_text_cached(file_path, encoding="utf-8").splitlines(keepends=True)
            except (UnicodeDecodeError, PermissionError):
                return False
            
            file_matches = 0
            matched_line_nums = set()
            context_lines = set()
            
            for line_num, line in enumerate(lines, 1):
                line_stripped = line.rstrip()
                matches = bool(regex.search(line_stripped))
                
                if invert_match:
                    matches = not matches
                
                if matches:
                    matched_line_nums.add(line_num)
                    file_matches += 1
                    
                    for ctx in range(max(1, line_num - before_context), line_num):
                        context_lines.add(ctx)
                    for ctx in range(line_num + 1, min(len(lines) + 1, line_num + after_context + 1)):
                        context_lines.add(ctx)
                    
                    if max_count and file_matches >= max_count:
                        break
            
            if file_matches > 0:
                files_with_matches.append(virtual_path)
                file_match_counts[virtual_path] = file_matches
                total_matches += file_matches
                
                if not quiet_mode and not count_only and not files_only:
                    show_fname = show_filename or (not hide_filename and recursive)
                    
                    all_output_lines = sorted(matched_line_nums | context_lines)
                    prev_line = 0
                    
                    for line_num in all_output_lines:
                        if line_num < 1 or line_num > len(lines):
                            continue
                        
                        line_content = lines[line_num - 1].rstrip()
                        is_match = line_num in matched_line_nums
                        
                        if before_context or after_context:
                            if prev_line and line_num > prev_line + 1:
                                results.append("--")
                        prev_line = line_num
                        
                        if only_matching and is_match:
                            for match in regex.finditer(line_content):
                                if show_fname:
                                    if show_line_nums:
                                        results.append(f"{virtual_path}:{line_num}:{match.group()}")
                                    else:
                                        results.append(f"{virtual_path}:{match.group()}")
                                else:
                                    if show_line_nums:
                                        results.append(f"{line_num}:{match.group()}")
                                    else:
                                        results.append(match.group())
                        else:
                            sep = ":" if is_match else "-"
                            
                            if show_fname:
                                if show_line_nums:
                                    results.append(f"{virtual_path}:{line_num}{sep} {line_content}")
                                else:
                                    results.append(f"{virtual_path}{sep} {line_content}")
                            else:
                                if show_line_nums:
                                    results.append(f"{line_num}{sep} {line_content}")
                                else:
                                    results.append(line_content)
                        
                        if len(results) >= self.MAX_GREP_RESULTS:
                            return True
            else:
                files_without_matches.append(virtual_path)
            
            return len(results) >= self.MAX_GREP_RESULTS
        
        if resolved.is_file():
            search_file(resolved, path)
        elif recursive:
            for file_path in sorted(resolved.rglob("*")):
                if file_path.is_file():
                    virtual = self._to_virtual_path(file_path)
                    if search_file(file_path, virtual):
                        break
        else:
            for file_path in sorted(resolved.iterdir()):
                if file_path.is_file():
                    virtual = self._to_virtual_path(file_path)
                    if search_file(file_path, virtual):
                        break
        
        if quiet_mode:
            return ""  # Just return empty, caller checks if matches found
        
        if files_without_match:
            if files_without_matches:
                return "\n".join(files_without_matches)
            return ""
        
        if files_only:
            if files_with_matches:
                return "\n".join(files_with_matches)
            return f"No matches found for '{pattern}'."
        
        if count_only:
            if file_match_counts:
                if len(file_match_counts) == 1 and not recursive:
                    return str(list(file_match_counts.values())[0])
                return "\n".join(f"{f}:{c}" for f, c in file_match_counts.items())
            return "0"
        
        if not results:
            return f"No matches found for '{pattern}'."
        
        output = "\n".join(results)
        if len(results) >= self.MAX_GREP_RESULTS:
            output += f"\n... (truncated at {self.MAX_GREP_RESULTS} results)"
        
        return output
    
    def _cmd_find(self, args: List[str]) -> str:
        """Find files by name pattern.

        Supported flags:
            -name PATTERN  Glob pattern to match filenames (e.g. '*.md', '*process*')
            -type f        List files only (directories excluded)
            -type d        List directories only (files excluded)
            -maxdepth N    Ignored (rglob is always fully recursive)
            Other flags    Silently ignored (e.g. -mtime, -atime, -size, -perm)

        Note: Paths with spaces MUST be quoted: find '/local/Invoice To Pay_md' -name '*.md'
        """
        # Flags that consume the next token as their value — skip both to avoid
        # treating the value (e.g. "f" in "-type f") as a positional path argument.
        _VALUE_FLAGS = {"-type", "-maxdepth", "-mindepth", "-mtime", "-atime",
                        "-ctime", "-size", "-perm", "-user", "-group"}

        path = "."
        name_pattern = None
        type_filter = None   # "f" = files only, "d" = dirs only, None = both

        i = 0
        while i < len(args):
            if args[i] == "-name" and i + 1 < len(args):
                name_pattern = args[i + 1]
                i += 2
            elif args[i] == "-type" and i + 1 < len(args):
                type_filter = args[i + 1]   # "f" or "d"
                i += 2
            elif args[i] in _VALUE_FLAGS and i + 1 < len(args):
                i += 2  # skip flag AND its value token
            elif not args[i].startswith("-"):
                path = args[i]
                i += 1
            else:
                i += 1  # skip unknown boolean flag

        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)

        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: '{path}' does not exist."

        pattern = name_pattern if name_pattern else "*"

        results = []
        for item in resolved.rglob(pattern):
            if type_filter == "f" and not item.is_file():
                continue
            if type_filter == "d" and not item.is_dir():
                continue
            virtual = self._to_virtual_path(item)
            results.append(virtual)
            if len(results) >= self.MAX_FIND_RESULTS:
                break

        if not results:
            return "No files found."

        output = "\n".join(results)
        if len(results) >= self.MAX_FIND_RESULTS:
            output += f"\n... (truncated at {self.MAX_FIND_RESULTS} results)"

        return output
    
    def _cmd_mkdir(self, args: List[str]) -> str:
        """Create a directory. Supports -p flag for parents."""
        if not args:
            return "Error: mkdir requires a directory path."
        
        parents = False
        path = None
        for arg in args:
            if arg == "-p":
                parents = True
            elif not arg.startswith("-"):
                path = arg
        
        if not path:
            return "Error: mkdir requires a directory path."
        
        if not self._is_writable(path if path.startswith("/") else self.cwd + "/" + path):
            return f"Error [PERMISSION_DENIED]: Cannot create directory in read-only area."
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if resolved.exists():
            return f"Directory '{path}' already exists."
        
        if not parents and not resolved.parent.exists():
            return f"Error: Parent directory does not exist. Use 'mkdir -p {path}' to create parents."
        
        resolved.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {self._to_virtual_path(resolved)}"
    
    def _cmd_touch(self, args: List[str]) -> str:
        """Create an empty file."""
        if not args:
            return "Error: touch requires a file path."
        
        path = args[0]
        
        virtual_path = path if path.startswith("/") else (self.cwd.rstrip("/") + "/" + path)
        if not self._is_writable(virtual_path):
            return f"Error [PERMISSION_DENIED]: Cannot create file in read-only area."
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        resolved.parent.mkdir(parents=True, exist_ok=True)
        
        resolved.touch()
        return f"Created: {self._to_virtual_path(resolved)}"
    
    def _cmd_echo(self, args: List[str], redirect: Optional[Dict]) -> str:
        """Echo text (with optional file redirection)."""
        content = " ".join(args)
        
        if not redirect:
            return content
        
        target = redirect["target"]
        append = redirect["append"]
        
        for char in self.INVALID_FILENAME_CHARS:
            if char in target:
                return f"Error [INVALID_FILENAME]: Filename cannot contain '{char}'. Use a simple filename like 'notes.txt'."
        
        if target.startswith("/"):
            virtual_path = target
        else:
            virtual_path = self.cwd.rstrip("/") + "/" + target
        
        if not self._is_writable(virtual_path):
            return f"Error [PERMISSION_DENIED]: Cannot write to '{target}'. This directory is read-only."
        
        try:
            resolved = self._resolve_path(target)
        except SecurityError as e:
            return str(e)
        
        resolved.parent.mkdir(parents=True, exist_ok=True)
        
        mode = "a" if append else "w"
        lock = FileLock.get_lock(resolved)
        with lock:
            with open(resolved, mode, encoding="utf-8") as f:
                if HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(content + "\n")
                finally:
                    if HAS_FCNTL:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Drop any cached copy so subsequent cat/grep see the new content immediately.
        self._invalidate_file_cache(resolved)

        if "/memory/" in virtual_path:
            self._index_file(resolved)
            return f"Wrote to {virtual_path} (indexed to memory)"
        
        return f"Wrote to {virtual_path}"
    
    def _cmd_semgrep(self, args: List[str]) -> str:
        """
        Semantic grep — find files by meaning, not exact text.

        For /local/ paths: uses ripgrep broad scan → BM25 ranking (no API, no pre-indexing).
        For /memory/ paths or no path: uses VectorStore (agent's own indexed notes).

        Usage: semgrep 'natural language query' [path]
        Examples:
            semgrep 'how are invoices approved' '/local/Invoice To Pay_md/'
            semgrep 'payment run configuration' /local/
            semgrep 'what I learned about vendor onboarding'
        """
        if not args:
            return "Error: semgrep requires a query. Usage: semgrep 'concept to find' [path]"

        query = args[0]
        search_path = args[1] if len(args) > 1 else None

        use_local_bm25 = False
        if search_path:
            norm = search_path.strip().lstrip("/").lower()
            if norm.startswith("local"):
                use_local_bm25 = True

        if use_local_bm25:
            return self._semgrep_local(query, search_path)

        path_prefix = None
        if search_path:
            try:
                resolved = self._resolve_path(search_path)
                path_prefix = str(resolved)
            except SecurityError:
                pass

        results = self.vector_store.search(query, path_prefix=path_prefix, top_k=10)
        if not results:
            return (
                f"semgrep: No conceptually similar content found for '{query}'.\n"
                f"Suggestion: For /local/ files use: semgrep '{query}' /local/"
            )

        lines = []
        for r in results:
            virtual_path = self._to_virtual_path(Path(r.path))
            score_pct = int(r.score * 100)
            lines.append(f"{virtual_path} [{score_pct}% match]: {r.snippet}")
        return "\n".join(lines)

    def _semgrep_local(self, query: str, search_path: str) -> str:
        """
        Grep-then-BM25 semantic search over /local/ files.

        Step 1 — Extract meaningful keywords from the query (strip stop words).
        Step 2 — Run ripgrep with an OR-pattern across all keywords to get candidates.
        Step 3 — BM25-score each candidate file against the full query.
        Step 4 — Return top 10 ranked results with the best matching snippet.

        No API calls. No pre-indexing. Works immediately on any /local/ content.
        """
        _STOP = {
            'the', 'a', 'an', 'and', 'or', 'in', 'of', 'for', 'to', 'is',
            'are', 'how', 'what', 'does', 'do', 'i', 'my', 'me', 'with',
            'by', 'from', 'show', 'can', 'we', 'it', 'its', 'this', 'that',
            'get', 'give', 'tell', 'find', 'list', 'when', 'where', 'which',
            'on', 'at', 'be', 'been', 'was', 'were', 'have', 'has', 'had',
            'will', 'would', 'could', 'should', 'about', 'all', 'us', 'our',
        }
        query_terms = [
            w.lower() for w in re.findall(r'\w+', query)
            if w.lower() not in _STOP and len(w) > 2
        ]

        if not query_terms:
            return f"semgrep: Could not extract search terms from '{query}'."

        try:
            resolved = self._resolve_path(search_path)
        except SecurityError as e:
            return str(e)

        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: '{search_path}' does not exist."

        candidate_files: List[Path] = []

        if self._rg_path:
            or_pattern = "|".join(re.escape(t) for t in query_terms[:10])
            try:
                result = subprocess.run(
                    [self._rg_path, "--no-heading", "--color=never",
                     "-i", "-l", "--", or_pattern, str(resolved)],
                    capture_output=True, text=True, timeout=15,
                    creationflags=_NO_WINDOW,
                )
                if result.returncode <= 1:
                    for line in result.stdout.strip().splitlines():
                        p = Path(line.strip())
                        if p.is_file():
                            candidate_files.append(p)
            except Exception:
                pass

        if not candidate_files:
            _SKIP_EXT = {'.db', '.pyc', '.zip', '.tar', '.gz', '.rdb',
                         '.bin', '.pyo', '.db-wal', '.db-shm', '.png',
                         '.jpg', '.jpeg', '.gif', '.mp4', '.mp3'}
            for fp in resolved.rglob('*'):
                if fp.is_file() and fp.suffix.lower() not in _SKIP_EXT:
                    candidate_files.append(fp)

        if not candidate_files:
            return f"semgrep: No searchable files found under '{search_path}'."

        scored: List[tuple] = []
        for file_path in candidate_files[:60]:   # cap scan at 60 files
            try:
                content = self._read_text_cached(file_path, encoding="utf-8", errors="ignore")
                if not content.strip():
                    continue
                doc_terms = re.findall(r'\w+', content.lower())
                score = self._bm25_score(query_terms, doc_terms)
                if score > 0:
                    snippet = self._best_snippet(content, query_terms)
                    scored.append((score, file_path, snippet))
            except Exception:
                continue

        if not scored:
            return (
                f"semgrep: No conceptually similar content found for '{query}'.\n"
                f"Tried {len(candidate_files)} files under '{search_path}'.\n"
                f"Suggestion: Try 'grep' with a more specific keyword."
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        lines = []
        for score, file_path, snippet in scored[:10]:
            virtual = self._to_virtual_path(file_path)
            score_pct = min(int(score / max(scored[0][0], 1) * 95) + 1, 99)
            lines.append(f"{virtual} [{score_pct}% match]: {snippet}")

        logger.info(
            "semgrep BM25: query=%r  candidates=%d  scored=%d  top=%s",
            query, len(candidate_files), len(scored),
            lines[0][:80] if lines else "none",
        )
        return "\n".join(lines)

    def _bm25_score(
        self,
        query_terms: List[str],
        doc_terms: List[str],
        k1: float = 1.5,
        b: float = 0.75,
        avgdl: int = 400,
    ) -> float:
        """
        BM25 relevance score for one document against a query.

        Simplified (no corpus-level IDF — treats all terms equally).
        Accurate enough for ranking within a single folder search.
        """
        dl = len(doc_terms)
        score = 0.0
        for term in query_terms:
            tf = doc_terms.count(term)
            if tf == 0:
                continue
            score += (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        return score

    def _best_snippet(
        self,
        content: str,
        query_terms: List[str],
        window: int = 200,
    ) -> str:
        """
        Return the line in content with the highest query term overlap.
        Falls back to the first non-empty line if no match found.
        """
        best_line = ""
        best_count = -1
        for line in content.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            line_lower = line_stripped.lower()
            count = sum(1 for t in query_terms if t in line_lower)
            if count > best_count:
                best_count = count
                best_line = line_stripped
        return (best_line[:window] + "…") if len(best_line) > window else best_line
    
    def _cmd_tree(self, args: List[str]) -> str:
        """Display directory tree."""
        path = args[0] if args else "."
        max_depth = 3
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: '{path}' does not exist."
        
        lines = [self._to_virtual_path(resolved)]
        
        def add_tree(dir_path: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            
            try:
                items = sorted(dir_path.iterdir())
            except PermissionError:
                return
            
            for i, item in enumerate(items):
                if item.name.startswith("."):
                    continue
                
                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{item.name}")
                
                if item.is_dir():
                    extension = "    " if is_last else "│   "
                    add_tree(item, prefix + extension, depth + 1)
        
        add_tree(resolved, "", 1)
        return "\n".join(lines)
    
    def _cmd_wc(self, args: List[str]) -> str:
        """Count lines, words, characters."""
        if not args:
            return "Error: wc requires a file path."
        
        path = args[-1]  # Last non-flag arg
        
        try:
            resolved = self._resolve_path(path)
        except SecurityError as e:
            return str(e)
        
        if not resolved.exists():
            return f"Error [FILE_NOT_FOUND]: File '{path}' does not exist."
        
        try:
            content = self._read_text_cached(resolved, encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read file '%s': %s", path, e)
            return f"Error reading file."
        
        lines = content.count("\n")
        words = len(content.split())
        chars = len(content)
        
        return f"  {lines}  {words}  {chars} {path}"
    
    @staticmethod
    def _sanitize_curl_token(raw: str, pattern: re.Pattern, var_name: str) -> str:
        """Validate a bearer-token env var against an allowlist and return a
        sanitised copy.  Returns empty string on failure.  Acts as a Fortify
        sanitiser gate: raises-or-reconstructs to sever the taint chain from
        os.environ → subprocess.run (CWE-78).
        """
        if not raw:
            return ""
        if not pattern.fullmatch(raw):
            logger.warning("Curl env var %s failed allowlist validation", var_name)
            return ""
        return raw.encode("utf-8").decode("utf-8")

    @staticmethod
    def _resolve_curl_timeout() -> int:
        """Hard timeout (seconds) applied to every agent-issued curl call.

        Configurable via the CURL_TIMEOUT env var; defaults to 30 and is clamped
        to [5, 600]. Governs both curl --max-time and the subprocess watchdog
        (single and piped curl paths).
        """
        try:
            val = int(os.getenv("CURL_TIMEOUT", "30"))
        except (TypeError, ValueError):
            val = 30
        return max(5, min(600, val))

    def _cmd_curl(self, args: List[str], redirect: Optional[Dict] = None) -> str:
        """Execute curl for HTTP requests.

        Supports GET/POST requests with headers.
        Redirect (> /path/file) writes output to a virtual-path file.
        """
        import subprocess

        # Block curl options that write files or read config files; match by prefix to catch glued forms (-o/tmp/x).
        dangerous_opts = [
            '-o', '--output', '-O', '--remote-name', '-T', '--upload-file',
            '--dump-header', '-D', '--cookie-jar', '-c', '--trace', '--trace-ascii',
            '-K', '--config', '--output-dir',
        ]
        for arg in args:
            s = str(arg)
            for opt in dangerous_opts:
                if s == opt or (opt.startswith('-') and not opt.startswith('--') and s.startswith(opt) and len(s) > len(opt)):
                    return f"Error [CURL_BLOCKED]: '{opt}' is not allowed. Curl output goes to stdout only."
                if opt.startswith('--') and s.startswith(opt + '='):
                    return f"Error [CURL_BLOCKED]: '{opt}' is not allowed. Curl output goes to stdout only."

        allowed, reason = self._check_http_external_access(args, "curl " + " ".join(shlex.quote(str(arg)) for arg in args))
        if not allowed:
            return f"Error [EXTERNAL_ACCESS_DENIED]: {reason}"

        # Allowlisted env vars are substituted into args; never broaden, curl args are logged.
        _SUBSTITUTABLE_ENV_VARS = ("IAF_AGENT_SELF_AUTH_TOKEN",)
        _TOKEN_RE = re.compile(r'^[A-Za-z0-9._~+/=\-]{1,8192}$')
        substituted_args: List[str] = []
        for arg in args:
            s = str(arg)
            for var in _SUBSTITUTABLE_ENV_VARS:
                if "$" + var in s:
                    _raw_val = os.environ.get(var, "")
                    _safe_val = self._sanitize_curl_token(_raw_val, _TOKEN_RE, var)
                    s = s.replace("${" + var + "}", _safe_val).replace("$" + var, _safe_val)
            substituted_args.append(s)
        args = substituted_args

        # --proto/--proto-redir pin curl to HTTP(S), including across redirects.
        _curl_timeout = self._resolve_curl_timeout()
        cmd = [
            "curl", "-s", "--max-time", str(_curl_timeout),  # CURL_TIMEOUT (default 30s)
            "--proto", "=http,https", "--proto-redir", "=http,https",
        ]

        # Bypass corporate proxies (e.g. Zscaler) for internal/F5 hosts.
        # Reads CURL_NOPROXY from config.env; falls back to system NO_PROXY env var.
        _NOPROXY_RE = re.compile(r'^[A-Za-z0-9.*,:\-_/]+$')
        _noproxy = (
            os.getenv("CURL_NOPROXY") or os.getenv("NO_PROXY") or os.getenv("no_proxy", "")
        ).strip()
        if _noproxy:
            if not _NOPROXY_RE.fullmatch(_noproxy):
                logger.warning("CURL_NOPROXY failed allowlist validation")
                _noproxy = ""
            else:
                _noproxy = _noproxy.encode("utf-8").decode("utf-8")
            if _noproxy:
                cmd.extend(["--noproxy", _noproxy])
                logger.debug("Curl --noproxy applied (hosts=%s)", _noproxy)

        # Strip user overrides so the enforced --proto pins and SSRF target check cannot be relaxed.
        _OVERRIDE_OPTS = ("--proto", "--proto-redir", "--resolve", "--connect-to")
        _filtered: List[str] = []
        _skip = False
        for _a in args:
            if _skip:
                _skip = False
                continue
            if isinstance(_a, str) and _a in _OVERRIDE_OPTS:
                _skip = True  # also drop its value token
                continue
            if isinstance(_a, str) and any(_a.startswith(o + "=") for o in _OVERRIDE_OPTS):
                continue
            _filtered.append(_a)
        cmd.extend(_filtered)
        cmd = list(cmd)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_curl_timeout,
                creationflags=_NO_WINDOW,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr or 'curl failed'}"
            output = result.stdout or "(empty response)"
        except subprocess.TimeoutExpired:
            return f"Error: Request timed out ({_curl_timeout}s)"
        except Exception as e:
            return f"Error: {str(e)}"

        if redirect:
            target = redirect.get("target", "")
            if not target:
                return output
            for char in self.INVALID_FILENAME_CHARS:
                if char in target:
                    return f"Error [INVALID_FILENAME]: '{char}' not allowed in path"
            virtual_path = target if target.startswith("/") else self.cwd.rstrip("/") + "/" + target
            if not self._is_writable(virtual_path):
                return f"Error [READ_ONLY]: Cannot write to '{virtual_path}'"
            try:
                resolved = self._resolve_path(target)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                lock = FileLock.get_lock(resolved)
                with lock:
                    resolved.write_text(output, encoding="utf-8")
                self._invalidate_file_cache(resolved)
                return f"Saved to {virtual_path} ({len(output)} chars)"
            except Exception as e:
                return f"Error writing redirect: {e}"

        return output
    
    def _index_file(self, file_path: Path):
        """Add or update a file in the vector index."""
        try:
            content = file_path.read_text(encoding="utf-8")
            self.vector_store.upsert(
                path=str(file_path),
                content=content,
                metadata={
                    "virtual_path": self._to_virtual_path(file_path),
                    "indexed_at": datetime.now(timezone.utc).isoformat()
                }
            )
        except Exception as e:
            logger.error("Failed to index file '%s': %s", file_path, e)
            pass  # Silently fail indexing


    def _parse_python3_args(self, raw: str) -> List[str]:
        """
        Parse args after 'python3' into a list, respecting quoted strings.
        e.g. '-c "from x import y; print(1)"' -> ['-c', 'from x import y; print(1)']
        """
        import shlex
        heredoc = re.match(
            r"""^\s*(?:-\s*)?<<\s*['"]?([A-Za-z_][A-Za-z0-9_-]*)['"]?\s*\n([\s\S]*?)\n\s*\1\s*$""",
            raw,
        )
        if heredoc:
            return ["-c", heredoc.group(2)]
        try:
            return shlex.split(raw)
        except ValueError:
            # shlex can fail on unmatched quotes — fall back to naive split
            if raw.startswith("-c"):
                rest = raw[2:].strip()
                if (rest.startswith('"') and rest.endswith('"')) or \
                   (rest.startswith("'") and rest.endswith("'")):
                    rest = rest[1:-1]
                return ["-c", rest]
            return raw.split()

    _PYTHON3_BLOCKED_MODULES = {
        "subprocess", "multiprocessing", "socket", "socketserver",
        "ctypes", "cffi", "pty", "tty",
        "http", "urllib", "httpx", "requests", "aiohttp", "httplib2",
    }
    _PYTHON3_BLOCKED_CALLS = {
        ("os", "system"), ("os", "popen"), ("os", "execv"),
        ("os", "execve"), ("os", "execvp"), ("os", "fork"),
        ("os", "spawn"), ("os", "spawnl"),
    }
    # Standalone function calls blocked (exec/eval prevent AST bypass via dynamic code generation)
    _PYTHON3_BLOCKED_FUNCTIONS = {"__import__", "exec", "eval", "compile"}

    def _python3_ast_scan(self, code: str) -> Optional[str]:
        """
        Scan code with AST parser. Returns error string if blocked, None if safe.
        Catches dynamic import patterns that string matching misses.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"Error [PYTHON3_SYNTAX]: {e}"

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module] if node.module else [])
                )
                for name in names:
                    root = name.split(".")[0] if name else ""
                    if root in self._PYTHON3_BLOCKED_MODULES:
                        hint = ""
                        if root in ("subprocess", "multiprocessing"):
                            hint = (
                                " Hint: do NOT call shell tools from python3. "
                                "Issue 'grep'/'find'/'cat' as direct shell() commands instead. "
                                "For parallelism, make multiple shell() tool calls — the runtime parallelises them."
                            )
                        elif root in ("urllib", "httpx", "requests", "aiohttp", "httplib2", "socket"):
                            hint = " Hint: network access is sandboxed. Use the curl shell tool or a dedicated skill."
                        return (
                            f"Error [PYTHON3_BLOCKED]: Import '{root}' is not allowed. "
                            f"Blocked: {', '.join(sorted(self._PYTHON3_BLOCKED_MODULES))}.{hint}"
                        )

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self._PYTHON3_BLOCKED_FUNCTIONS:
                        return f"Error [PYTHON3_BLOCKED]: '{node.func.id}' is not allowed."
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        pair = (node.func.value.id, node.func.attr)
                        if pair in self._PYTHON3_BLOCKED_CALLS:
                            return (
                                f"Error [PYTHON3_BLOCKED]: "
                                f"'{node.func.value.id}.{node.func.attr}' is not allowed."
                            )
        return None  # safe

    def _python3_sqlite_guard(self, code: str) -> Optional[str]:
        """Apply DB entitlement checks to direct sqlite3 access from python3."""
        if not (self.external_access_enabled and self.external_access_enforce_sql and self.entitlement_checker):
            return None
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None

        sqlite_imported = False
        checked_any = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                sqlite_imported = sqlite_imported or any(alias.name.split(".")[0] == "sqlite3" for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                sqlite_imported = sqlite_imported or (node.module or "").split(".")[0] == "sqlite3"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect":
                if not node.args:
                    continue
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    checked_any = True
                    allowed, reason = self.database_allowed(arg.value, "read")
                    if not allowed:
                        return f"Error [PYTHON3_SQLITE_DENIED]: {reason}"

        if sqlite_imported and not checked_any and self.external_access_unknown_mode == "deny":
            self._audit_external_access(
                action="read",
                resource="external:db.unknown",
                allowed=False,
                reason="sqlite3 import without statically detectable database path",
                metadata={"skill": self.current_skill or self.agent_id},
            )
            return "Error [PYTHON3_SQLITE_DENIED]: sqlite3 access requires a literal governed database path"
        return None

    def _python3_rewrite_paths(self, code: str) -> str:
        """
        Replace virtual paths (/me/, /shared/, /users/) in code string
        with real filesystem paths using the kernel's existing path resolver.
        """
        pattern = re.compile(
            r'(?<![/\w])(/(?:me|shared|users|workspace|local)/[^\s\'"\\,)]*)'
        )

        def replace(match):
            virtual = match.group(1).rstrip("/.,)")
            try:
                real = self._resolve_path(virtual)
                return real.as_posix()
            except Exception:
                return virtual  # leave unchanged if can't resolve

        return pattern.sub(replace, code)

    # Script args: printable text; no NUL or control chars other than tab/newline/CR.
    _PY3_SCRIPT_ARG_RE = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]{0,32767}$")

    @staticmethod
    def _reconstruct_str(value: str) -> str:
        """Return a fresh copy of an already-validated string (breaks taint chains)."""
        return value.encode("utf-8", "surrogatepass").decode("utf-8", "surrogatepass")

    def _sanitize_python3_script_args(self, args: List[str]) -> List[str]:
        """Validate python3 script argv tokens before subprocess (CWE-78)."""
        safe_args: List[str] = []
        for raw in args:
            arg = str(raw)
            if not self._PY3_SCRIPT_ARG_RE.fullmatch(arg):
                raise SecurityError("Error [PYTHON3]: script argument contains control characters")
            safe_args.append(self._reconstruct_str(arg))
        return safe_args

    def _cmd_python3(self, args: List[str]) -> str:
        """
        Execute Python3 code safely.

        Supports:
          python3 -c "code"          inline code
          python3 /me/script.py      run a virtual-path script file

        Security layers (always applied):
          1. AST scan — blocks dangerous imports and os.system calls
          2. Virtual path rewriting — /me/ and /shared/ resolved to real paths
          3. Clean environment — no sensitive data from server process
          4. Timeout + resource limits (Linux/Mac only)
          5. Optional sandbox user (AGENT_PYTHON3_SANDBOX_USER)
        """
        if not args:
            return "Error [PYTHON3]: Usage: python3 -c 'code' or python3 /path/script.py"

        # Parse a `< /path` stdin redirect (spaced or glued) so it is not passed to the script as a positional arg.
        _stdin_bytes: Optional[bytes] = None
        _new_args: List[str] = []
        _i = 0
        while _i < len(args):
            _a = args[_i]
            if _a == "<" and _i + 1 < len(args):
                _redir = args[_i + 1]
                _i += 2
            elif _a.startswith("<") and len(_a) > 1:
                _redir = _a[1:]
                _i += 1
            else:
                _new_args.append(_a)
                _i += 1
                continue
            try:
                _real = self._resolve_path(_redir)
                _stdin_bytes = _real.read_bytes()
            except Exception as _e:
                return f"Error [PYTHON3]: stdin redirect '{_redir}' failed: {_e}"
        args = _new_args
        if not args:
            return "Error [PYTHON3]: Usage: python3 -c 'code' or python3 /path/script.py"

        if args[0] == "-c":
            code = " ".join(args[1:]).strip().strip('"').strip("'")
            if not code:
                return "Error [PYTHON3]: No code provided after -c"
            _use_script_file = False

            blocked = self._python3_ast_scan(code)
            if blocked:
                return blocked
            sqlite_blocked = self._python3_sqlite_guard(code)
            if sqlite_blocked:
                return sqlite_blocked
            code = self._python3_rewrite_paths(code)
        else:
            script_path_str = args[0]
            try:
                real_script = self._resolve_path(script_path_str)
                if not real_script.is_file():
                    return f"Error [PYTHON3]: '{script_path_str}' is not a file"
                if real_script.suffix != ".py":
                    return f"Error [PYTHON3]: Only .py scripts are allowed, got '{real_script.suffix}'"
                if real_script.is_symlink():
                    return f"Error [PYTHON3]: Symlinked scripts are not allowed"
                _scan_content = real_script.read_text(encoding="utf-8")
            except Exception as e:
                return f"Error [PYTHON3]: Cannot read script '{script_path_str}': {e}"
            _use_script_file = True

            blocked = self._python3_ast_scan(_scan_content)
            if blocked:
                return blocked
            sqlite_blocked = self._python3_sqlite_guard(_scan_content)
            if sqlite_blocked:
                return sqlite_blocked
            # Script runs by path, not via -c.
            del _scan_content
            code = None

        # sys.executable is the running interpreter: trusted, absolute and verified.
        python_exec = str(Path(sys.executable).resolve())
        if not os.path.isfile(python_exec):
            python_exec = shutil.which("python3") or shutil.which("python") or "python3"
        # OS-aware PATH/HOME: on Windows inherit PATH and use a temp dir for HOME.
        if platform.system() == "Windows":
            _clean_path = os.environ.get("PATH", "")
            _clean_home = os.environ.get("TEMP") or os.environ.get("TMP") or os.environ.get("USERPROFILE") or os.getcwd()
        else:
            _clean_path = "/usr/local/bin:/usr/bin:/bin"
            _clean_home = "/tmp"
        clean_env = {
            "PATH": _clean_path,
            "PYTHONPATH": os.pathsep.join(sys.path),
            "HOME": _clean_home,
            "LANG": "en_US.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Credential store decrypt key — not a credential itself, required for
            # CredentialStore to decrypt secret fields inside the sandbox.
            "CREDENTIAL_MASTER_KEY": os.getenv("CREDENTIAL_MASTER_KEY", ""),
            # Credential scope consumer, mirroring the native get_credential tool.
            "IAF_CURRENT_SKILL": self.current_skill or self.agent_id or "",
        }
        if platform.system() == "Windows":
            # Windows needs SystemRoot for python startup (winreg, sockets) and
            # USERPROFILE for tempfile resolution; passing them keeps subprocess healthy.
            for _winvar in ("SYSTEMROOT", "SystemRoot", "USERPROFILE", "TEMP", "TMP", "PATHEXT"):
                _wv = os.environ.get(_winvar)
                if _wv:
                    clean_env[_winvar] = _wv

        sandbox_user = self.python3_sandbox_user
        _use_sudo = bool(sandbox_user) and platform.system() != "Windows"

        # Resource-limit bootstrap for inline -c on POSIX so limits apply as the sandbox user under sudo.
        if not _use_script_file and platform.system() != "Windows":
            limit_bootstrap = (
                "import resource as _agent_resource\n"
                f"_agent_memory={self.python3_max_memory_mb * 1024 * 1024}\n"
                f"_agent_cpu={self.python3_timeout}\n"
                "try:\n"
                " _agent_resource.setrlimit(_agent_resource.RLIMIT_AS, (_agent_memory, _agent_memory))\n"
                " _agent_resource.setrlimit(_agent_resource.RLIMIT_CPU, (_agent_cpu, _agent_cpu))\n"
                "except (ValueError, OSError):\n"
                " pass\n"
            )
            code = limit_bootstrap + code

        # Temp file holding a spilled-to-disk large inline program (see the -c
        # branch below). Removed in the finally after execution.
        _spill_path = None

        if _use_script_file:
            # Execute the validated .py by path rather than via -c.
            script_args = args[1:] if len(args) > 1 else []
            # Rewrite virtual paths in script args as the -c branch does; Windows treats a leading '/' as drive-relative.
            script_args = [self._python3_rewrite_paths(a) for a in script_args]
            try:
                script_args = self._sanitize_python3_script_args(script_args)
            except SecurityError as e:
                return str(e)
            safe_script = self._reconstruct_str(str(real_script))
            if _use_sudo:
                cmd = ["sudo", "-n", "-u", sandbox_user, "--", python_exec, "-I",
                       safe_script] + script_args
            else:
                cmd = [python_exec, "-I", safe_script] + script_args
        else:
            # Spill large inline code to a temp .py on Windows (32767-char command cap); the POSIX sudo sandbox cannot read the 0600 file.
            code = self._reconstruct_str(code)
            if platform.system() == "Windows" and len(code) > 30000:
                import tempfile
                _fd, _spill_path = tempfile.mkstemp(suffix=".py", prefix="iaf_py3_")
                with os.fdopen(_fd, "w", encoding="utf-8") as _sf:
                    _sf.write(code)
                _run_args = [_spill_path]
            else:
                _run_args = ["-c", code]
            if _use_sudo:
                cmd = ["sudo", "-n", "-u", sandbox_user, "--", python_exec, "-I"] + _run_args
            else:
                cmd = [python_exec, "-I"] + _run_args

        def _set_limits():
            try:
                import resource as _res
                mb = self.python3_max_memory_mb * 1024 * 1024
                _res.setrlimit(_res.RLIMIT_AS, (mb, mb))
                _res.setrlimit(_res.RLIMIT_CPU, (self.python3_timeout, self.python3_timeout))
            except Exception:
                pass  # resource module not available (Windows) — skip silently

        use_preexec = platform.system() != "Windows" and not sandbox_user
        preexec = _set_limits if use_preexec else None

        # stdin redirect content came from a file resolved via _resolve_path; it is
        # data for the script (never parsed by a shell). Pass a reconstructed copy.
        _stdin_text: Optional[str] = (
            self._reconstruct_str(_stdin_bytes.decode("utf-8", errors="replace"))
            if _stdin_bytes is not None else None
        )

        logger.debug(
            "SafeKernel._cmd_python3 launching: python_exec=%r argv0=%r "
            "cwd=%r path_set=%s home=%r timeout=%ss",
            python_exec,
            cmd[0],
            str(self.agent_root),
            bool(clean_env.get("PATH")),
            clean_env.get("HOME"),
            self.python3_timeout,
        )
        try:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.python3_timeout,
                    env=clean_env,
                    cwd=str(self.agent_root),
                    preexec_fn=preexec,
                    creationflags=_NO_WINDOW,
                    input=_stdin_text,
                )
            except OSError as _e:
                import errno as _errno
                if _e.errno == _errno.EAGAIN:
                    logger.warning("python3 EAGAIN — retrying once")
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.python3_timeout,
                        env=clean_env,
                        cwd=str(self.agent_root),
                        preexec_fn=preexec,
                        creationflags=_NO_WINDOW,
                        input=_stdin_text,
                    )
                else:
                    raise
            # errors="replace" guarantees string output on non-UTF-8 child bytes; keep the None-guard.
            if result.returncode == 0:
                output = (result.stdout or "").strip()
                return output if output else "(no output)"
            else:
                err = (result.stderr or result.stdout or "unknown error").strip()
                return f"Error [PYTHON3]: {err[:2000]}"

        except subprocess.TimeoutExpired:
            return f"Error [PYTHON3_TIMEOUT]: Execution exceeded {self.python3_timeout}s limit."
        except FileNotFoundError as _fnf:
            # winerror=206 is a too-long command line, not a missing interpreter.
            if getattr(_fnf, "winerror", None) == 206:
                return "Error [PYTHON3]: command line too long for this OS — script too large to launch."
            return "Error [PYTHON3]: python3 not found on this system."
        except PermissionError as e:
            return f"Error [PYTHON3_PERMISSION]: {e}. Check AGENT_PYTHON3_SANDBOX_USER sudoers config."
        except Exception as e:
            return f"Error [PYTHON3]: {e}"
        finally:
            if _spill_path:
                try:
                    os.remove(_spill_path)
                except OSError:
                    pass
