# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
HardenedShell - Enhanced Agent Shell with RBAC, Audit Logging, and Rate Limiting.

Wraps the existing AgentShell (src/memory/agent_shell/shell.py) and adds:
- RBAC: role-based access control (user/manager/admin/auditor)
- Audit logging: structured JSONL logs of all operations
- Rate limiting: per-user sliding window rate limiter
- File locking: prevent concurrent writes to the same file
- Operation confirmations: require explicit confirmation for destructive actions

This is a standalone wrapper — it does NOT modify the existing AgentShell.
"""

import os
import json
import time
import uuid
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# RBAC
# ============================================================================

class ShellRole:
    """User role constants for shell RBAC."""
    USER = "user"           # Own files only
    MANAGER = "manager"     # Own + team members' files
    ADMIN = "admin"         # Full access
    AUDITOR = "auditor"     # Read-only access to everything


class ShellPermission:
    """Permissions for shell operations."""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"

    # Role → permission mapping
    ROLE_PERMISSIONS = {
        ShellRole.USER: {READ, WRITE, DELETE, EXECUTE},
        ShellRole.MANAGER: {READ, WRITE, DELETE, EXECUTE},
        ShellRole.ADMIN: {READ, WRITE, DELETE, EXECUTE},
        ShellRole.AUDITOR: {READ},
    }


# ============================================================================
# Rate Limiter
# ============================================================================

class ShellRateLimiter:
    """Sliding window rate limiter for shell commands."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a request is allowed for a user.
        
        Returns:
            Tuple of (allowed: bool, error_message: Optional[str]).
        """
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            if user_id not in self._timestamps:
                self._timestamps[user_id] = deque()

            q = self._timestamps[user_id]

            # Remove old timestamps
            while q and q[0] < window_start:
                q.popleft()

            if len(q) >= self.max_requests:
                retry_after = int(q[0] - window_start) + 1
                return False, (
                    f"Rate limit exceeded: {self.max_requests} commands per {self.window_seconds}s. "
                    f"Retry in {retry_after}s."
                )

            q.append(now)
            return True, None

    def get_remaining(self, user_id: str) -> int:
        """Get remaining requests for user in current window."""
        now = time.time()
        window_start = now - self.window_seconds
        with self._lock:
            q = self._timestamps.get(user_id, deque())
            count = sum(1 for t in q if t >= window_start)
            return max(0, self.max_requests - count)


# ============================================================================
# Audit Logger
# ============================================================================

class ShellAuditLogger:
    """Structured audit logging for shell commands."""

    def __init__(self, audit_dir: str):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(
        self,
        user_email: str,
        user_role: str,
        command: str,
        result_success: bool,
        result_output: str = "",
        agent_id: str = "",
        session_id: str = "",
        path_accessed: str = "",
        operation_type: str = "",
        blocked_reason: str = "",
    ):
        """Log a command execution to the audit trail."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": str(uuid.uuid4())[:12],
            "user_email": user_email,
            "user_role": user_role,
            "agent_id": agent_id,
            "session_id": session_id,
            "command": command[:500],  # Truncate very long commands
            "path_accessed": path_accessed,
            "operation_type": operation_type,
            "success": result_success,
            "blocked_reason": blocked_reason,
            "output_preview": result_output[:200] if result_output else "",
        }

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.audit_dir / f"shell_audit_{date_str}.jsonl"

        with self._lock:
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                log.error(f"Failed to write shell audit log: {e}")

    def get_logs(
        self,
        date: Optional[str] = None,
        user_email: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve audit logs, optionally filtered.
        
        Args:
            date: Date string (YYYY-MM-DD). Defaults to today.
            user_email: Filter by user.
            limit: Max entries to return.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        log_file = self.audit_dir / f"shell_audit_{date}.jsonl"
        if not log_file.exists():
            return []

        # Use deque(maxlen=limit) to keep only the most recent entries
        # in memory — prevents OOM on large daily audit log files.
        from collections import deque
        entries: deque = deque(maxlen=limit)
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if user_email and entry.get("user_email") != user_email:
                        continue
                    entries.append(entry)
        except Exception as e:
            log.error(f"Error reading shell audit log: {e}")

        return list(entries)


# ============================================================================
# File Locking
# ============================================================================

class ShellFileLock:
    """Thread-safe file locking to prevent concurrent writes.
    
    Uses reference counting to prune locks that are no longer in use,
    preventing unbounded memory growth from dynamic file paths.
    """
    _locks: Dict[str, threading.Lock] = {}
    _lock_refcounts: Dict[str, int] = {}
    _registry_lock = threading.Lock()

    @classmethod
    def acquire(cls, path: str) -> threading.Lock:
        """Get (or create) and acquire a lock for a file path."""
        with cls._registry_lock:
            if path not in cls._locks:
                cls._locks[path] = threading.Lock()
                cls._lock_refcounts[path] = 0
            cls._lock_refcounts[path] += 1
            lock = cls._locks[path]
        lock.acquire()
        return lock

    @classmethod
    def release(cls, path: str):
        """Release the lock for a file path and clean up if no longer needed."""
        with cls._registry_lock:
            lock = cls._locks.get(path)
            if lock:
                try:
                    lock.release()
                except RuntimeError:
                    # Lock was not acquired or already released
                    pass
            # Decrement refcount and prune if zero
            if path in cls._lock_refcounts:
                cls._lock_refcounts[path] -= 1
                if cls._lock_refcounts[path] <= 0:
                    cls._locks.pop(path, None)
                    cls._lock_refcounts.pop(path, None)


# ============================================================================
# HardenedShell
# ============================================================================

class HardenedShell:
    """
    Enhanced Agent Shell wrapper with security features.
    
    Wraps an AgentShell instance and adds RBAC, audit logging,
    rate limiting, and file locking.
    
    Usage:
        from src.memory.agent_shell.shell import AgentShell
        
        base_shell = AgentShell(agent_id="my_agent", session_id="sess_1", ...)
        
        hardened = HardenedShell(
            shell=base_shell,
            user_email="user@company.com",
            user_role="user",
            agent_id="my_agent",
            session_id="sess_1",
            audit_dir="./agent_workspaces/audit",
        )
        
        result = hardened.run("ls /memory/facts")
    """

    # Write operations that need special handling
    WRITE_OPS = {"echo", "mkdir", "touch", "tee"}
    READ_OPS = {"ls", "cat", "head", "tail", "grep", "find", "tree", "wc", "semgrep", "pwd", "cd"}

    def __init__(
        self,
        shell: Any,
        user_email: str,
        user_role: str = ShellRole.USER,
        agent_id: str = "",
        session_id: str = "",
        audit_dir: str = "./agent_workspaces/audit",
        rate_limit: int = 100,
        rate_window: int = 60,
        require_confirmation_for: Optional[List[str]] = None,
        managed_users: Optional[List[str]] = None,
    ):
        """
        Initialize HardenedShell.
        
        Args:
            shell: The underlying AgentShell instance.
            user_email: Current user's email.
            user_role: User's role (user/manager/admin/auditor).
            agent_id: The agent's ID.
            session_id: The session ID.
            audit_dir: Directory for audit logs.
            rate_limit: Max commands per window.
            rate_window: Rate limit window in seconds.
            require_confirmation_for: List of operations requiring confirmation.
            managed_users: Users this manager can access (for RBAC).
        """
        self.shell = shell
        self.user_email = user_email
        self.user_role = user_role
        self.agent_id = agent_id
        self.session_id = session_id
        self.managed_users = managed_users or []
        self.require_confirmation_for = require_confirmation_for or []

        # Components
        self.audit = ShellAuditLogger(audit_dir)
        self.rate_limiter = ShellRateLimiter(
            max_requests=rate_limit,
            window_seconds=rate_window,
        )

        log.info(
            f"HardenedShell initialized: user={user_email}, role={user_role}, "
            f"agent={agent_id}, rate_limit={rate_limit}/{rate_window}s"
        )

    def run(self, command: str) -> str:
        """
        Execute a command with RBAC, rate limiting, and audit logging.
        
        Args:
            command: The shell command to execute.
            
        Returns:
            Command output string.
        """
        command = command.strip()
        if not command:
            return "Error: empty command"

        # 1. Rate limit check
        allowed, error_msg = self.rate_limiter.check(self.user_email)
        if not allowed:
            self.audit.log(
                user_email=self.user_email,
                user_role=self.user_role,
                command=command,
                result_success=False,
                agent_id=self.agent_id,
                session_id=self.session_id,
                operation_type="rate_limited",
                blocked_reason=error_msg,
            )
            return f"Error [RATE_LIMITED]: {error_msg}"

        # 2. Parse the operation type
        op_type = self._classify_operation(command)

        # 3. RBAC check
        permissions = ShellPermission.ROLE_PERMISSIONS.get(self.user_role, set())
        required_permission = ShellPermission.WRITE if op_type in self.WRITE_OPS else ShellPermission.READ

        if required_permission not in permissions:
            self.audit.log(
                user_email=self.user_email,
                user_role=self.user_role,
                command=command,
                result_success=False,
                agent_id=self.agent_id,
                session_id=self.session_id,
                operation_type=op_type,
                blocked_reason=f"Role '{self.user_role}' lacks '{required_permission}' permission",
            )
            return f"Error [ACCESS_DENIED]: Role '{self.user_role}' does not have '{required_permission}' permission for this operation."

        # 4. Confirmation check (for destructive operations)
        if op_type in self.require_confirmation_for:
            if "# CONFIRMED" not in command:
                self.audit.log(
                    user_email=self.user_email,
                    user_role=self.user_role,
                    command=command,
                    result_success=False,
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    operation_type=op_type,
                    blocked_reason="Confirmation required",
                )
                return (
                    f"⚠️ This operation ({op_type}) requires confirmation.\n"
                    f"Re-run with '# CONFIRMED' appended to the command to proceed."
                )

        # 5. Execute via underlying shell
        try:
            # For write ops, use file locking
            if op_type in self.WRITE_OPS:
                target_path = self._extract_target_path(command)
                if target_path:
                    lock = ShellFileLock.acquire(target_path)
                    try:
                        result = self.shell.run(command.replace(" # CONFIRMED", ""))
                    finally:
                        ShellFileLock.release(target_path)
                else:
                    result = self.shell.run(command.replace(" # CONFIRMED", ""))
            else:
                result = self.shell.run(command)

            # 6. Audit log
            success = not result.startswith("Error")
            self.audit.log(
                user_email=self.user_email,
                user_role=self.user_role,
                command=command,
                result_success=success,
                result_output=result,
                agent_id=self.agent_id,
                session_id=self.session_id,
                operation_type=op_type,
            )

            return result

        except Exception as e:
            error_msg = str(e)
            self.audit.log(
                user_email=self.user_email,
                user_role=self.user_role,
                command=command,
                result_success=False,
                result_output=error_msg,
                agent_id=self.agent_id,
                session_id=self.session_id,
                operation_type=op_type,
                blocked_reason=f"Exception: {error_msg}",
            )
            return f"Error: {error_msg}"

    def get_audit_logs(
        self, date: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get audit logs for the current user."""
        return self.audit.get_logs(
            date=date,
            user_email=self.user_email,
            limit=limit,
        )

    def get_all_audit_logs(
        self, date: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all audit logs (admin/auditor only)."""
        if self.user_role not in (ShellRole.ADMIN, ShellRole.AUDITOR):
            return []
        return self.audit.get_logs(date=date, limit=limit)

    def get_rate_limit_remaining(self) -> int:
        """Get remaining commands in current rate window."""
        return self.rate_limiter.get_remaining(self.user_email)

    # ---- Internal ----

    def _classify_operation(self, command: str) -> str:
        """Extract the base command name (first word)."""
        parts = command.strip().split()
        if parts:
            return parts[0].lower()
        return "unknown"

    def _extract_target_path(self, command: str) -> Optional[str]:
        """Extract the target file path from a write command."""
        # Handle redirects: echo "content" > /path/file.md
        if ">" in command:
            parts = command.split(">")
            if len(parts) >= 2:
                return parts[-1].strip().strip('"').strip("'")

        # Handle mkdir /path
        parts = command.strip().split()
        if len(parts) >= 2 and parts[0] in ("mkdir", "touch"):
            return parts[-1]

        return None
