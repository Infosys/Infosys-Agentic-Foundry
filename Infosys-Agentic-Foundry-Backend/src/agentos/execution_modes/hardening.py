# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Production Hardening — Rate limiting, audit trails, and execution sandboxing.

Provides production-grade guardrails for skill execution engines:
  - RateLimiter: Sliding-window rate limiting per user/session
  - ExecutionAudit: Structured audit trail with log rotation
  - ExecutionSandbox: Timeout enforcement and resource gating

These are injected into the execution pipeline at the router level.
"""

import json
import time
import threading
import os
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from .base import log


# ============================================================================
# Rate Limiter
# ============================================================================

class RateLimitExceeded(Exception):
    """Raised when a user/session exceeds the rate limit."""
    def __init__(self, limit: int, window_seconds: int, retry_after: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window_seconds}s. "
            f"Retry after {retry_after:.1f}s."
        )


class RateLimiter:
    """
    Sliding-window rate limiter.

    Tracks request timestamps per key (user_id, session_id, or agent_id).
    Thread-safe via lock.

    Usage:
        limiter = RateLimiter(max_requests=60, window_seconds=60)
        limiter.check("user123")  # raises RateLimitExceeded if over limit
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """
        Check if the key is within rate limits.

        Args:
            key: Rate limit key (user_id, session_id, etc.)

        Returns:
            True if request is allowed

        Raises:
            RateLimitExceeded if over limit
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            if key not in self._windows:
                self._windows[key] = deque()

            window = self._windows[key]

            # Purge old entries
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self.max_requests:
                # Calculate retry-after
                oldest = window[0]
                retry_after = oldest + self.window_seconds - now
                raise RateLimitExceeded(
                    limit=self.max_requests,
                    window_seconds=self.window_seconds,
                    retry_after=max(0.1, retry_after),
                )

            window.append(now)
            return True

    def get_remaining(self, key: str) -> int:
        """Get remaining requests in current window."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            window = self._windows.get(key, deque())
            # Count entries within window
            active = sum(1 for t in window if t >= cutoff)
            return max(0, self.max_requests - active)

    def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        with self._lock:
            self._windows.pop(key, None)

    def cleanup(self) -> int:
        """Remove stale entries. Call periodically. Returns keys removed."""
        now = time.time()
        cutoff = now - self.window_seconds
        removed = 0

        with self._lock:
            stale_keys = [
                k for k, v in self._windows.items()
                if not v or v[-1] < cutoff
            ]
            for k in stale_keys:
                del self._windows[k]
                removed += 1

        return removed


# ============================================================================
# Execution Audit Trail
# ============================================================================

@dataclass
class AuditEntry:
    """Single audit log entry."""
    timestamp: str
    event_type: str          # plan | dispatch | worker_start | worker_done | synthesize | error
    execution_mode: str
    agent_id: str = ""
    session_id: str = ""
    user_id: str = ""
    skill_name: str = ""
    query_preview: str = ""
    result_preview: str = ""
    success: bool = True
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "execution_mode": self.execution_mode,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "skill_name": self.skill_name,
            "query_preview": self.query_preview,
            "result_preview": self.result_preview,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class ExecutionAudit:
    """
    Structured execution audit trail.

    Logs every execution event to a JSONL file with automatic rotation.
    Thread-safe via file locking.

    Log location: <agent_workspace>/.audit/execution_YYYY-MM-DD.jsonl
    """

    MAX_PREVIEW_CHARS = 500
    ROTATION_DAYS = 30

    def __init__(self, audit_dir: Optional[str] = None, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()

        if audit_dir:
            self.audit_dir = Path(audit_dir)
        else:
            self.audit_dir = Path("agent_workspaces/.audit")

        if self.enabled:
            self.audit_dir.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        event_type: str,
        execution_mode: str,
        *,
        agent_id: str = "",
        session_id: str = "",
        user_id: str = "",
        skill_name: str = "",
        query: str = "",
        result: str = "",
        success: bool = True,
        duration_ms: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an execution event to the audit trail."""
        if not self.enabled:
            return

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            execution_mode=execution_mode,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            skill_name=skill_name,
            query_preview=query[:self.MAX_PREVIEW_CHARS] if query else "",
            result_preview=result[:self.MAX_PREVIEW_CHARS] if result else "",
            success=success,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

        self._write_entry(entry)

    def _write_entry(self, entry: AuditEntry) -> None:
        """Write entry to today's JSONL file."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.audit_dir / f"execution_{today}.jsonl"

        try:
            with self._lock:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"[ExecutionAudit] Failed to write audit entry: {e}")

    def rotate_logs(self) -> int:
        """
        Remove audit logs older than ROTATION_DAYS.
        Call periodically (e.g., on server startup).

        Returns:
            Number of files removed.
        """
        if not self.enabled or not self.audit_dir.exists():
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ROTATION_DAYS)
        removed = 0

        for log_file in self.audit_dir.glob("execution_*.jsonl"):
            try:
                # Parse date from filename
                date_str = log_file.stem.replace("execution_", "")
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                if file_date < cutoff:
                    log_file.unlink()
                    removed += 1
            except (ValueError, OSError):
                continue

        if removed:
            log.info(f"[ExecutionAudit] Rotated {removed} old audit log files")
        return removed

    def get_recent_events(
        self,
        agent_id: str = "",
        session_id: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent audit events (for debugging/monitoring)."""
        if not self.enabled:
            return []

        entries: List[Dict[str, Any]] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.audit_dir / f"execution_{today}.jsonl"

        if not log_file.exists():
            return []

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if agent_id and entry.get("agent_id") != agent_id:
                            continue
                        if session_id and entry.get("session_id") != session_id:
                            continue
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning(f"[ExecutionAudit] Failed to read audit log: {e}")

        return entries[-limit:]


# ============================================================================
# Execution Sandbox (Timeout + Resource Gating)
# ============================================================================

@dataclass
class SandboxConfig:
    """Configuration for execution sandbox limits."""
    max_execution_time_seconds: int = 300     # 5 minutes total
    max_worker_time_seconds: int = 120        # 2 minutes per worker
    max_concurrent_workers: int = 8           # Max parallel workers
    max_total_output_chars: int = 100_000     # 100KB output limit
    max_plan_steps: int = 10                  # Max steps in a plan
    max_retries_per_worker: int = 2           # Max retries on failure
    allow_shell_in_workers: bool = True       # Allow shell commands in workers
    allow_network_in_workers: bool = True     # Allow network calls in workers


class ExecutionSandbox:
    """
    Execution sandbox — enforces resource limits and timeouts.

    Wraps execution with:
      - Total execution timeout
      - Per-worker timeout
      - Concurrent worker limit
      - Output size limit
      - Step count limit
    """

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self._active_executions: Dict[str, float] = {}  # session_id → start_time
        self._lock = threading.Lock()

    def check_limits(
        self,
        session_id: str,
        num_workers: int = 0,
        num_steps: int = 0,
    ) -> Optional[str]:
        """
        Check if execution would violate sandbox limits.

        Returns:
            None if OK, error message string if limit would be violated.
        """
        if num_workers > self.config.max_concurrent_workers:
            return (
                f"Too many concurrent workers: {num_workers} "
                f"(max: {self.config.max_concurrent_workers})"
            )

        if num_steps > self.config.max_plan_steps:
            return (
                f"Plan has too many steps: {num_steps} "
                f"(max: {self.config.max_plan_steps})"
            )

        return None

    def start_execution(self, session_id: str) -> None:
        """Mark execution start for timeout tracking."""
        with self._lock:
            self._active_executions[session_id] = time.time()

    def check_timeout(self, session_id: str) -> Optional[str]:
        """Check if total execution time has exceeded the limit."""
        with self._lock:
            start = self._active_executions.get(session_id)
            if start is None:
                return None

            elapsed = time.time() - start
            if elapsed > self.config.max_execution_time_seconds:
                return (
                    f"Execution timed out: {elapsed:.0f}s "
                    f"(max: {self.config.max_execution_time_seconds}s)"
                )

        return None

    def end_execution(self, session_id: str) -> None:
        """Mark execution complete."""
        with self._lock:
            self._active_executions.pop(session_id, None)

    def truncate_output(self, output: str) -> str:
        """Truncate output if it exceeds the maximum size."""
        if len(output) > self.config.max_total_output_chars:
            truncated = output[:self.config.max_total_output_chars]
            truncated += f"\n\n[Output truncated at {self.config.max_total_output_chars} chars]"
            return truncated
        return output

    @property
    def worker_timeout(self) -> int:
        """Get per-worker timeout in seconds."""
        return self.config.max_worker_time_seconds

    @property
    def max_workers(self) -> int:
        """Get max concurrent workers."""
        return self.config.max_concurrent_workers


# ============================================================================
# Global Instances (singleton pattern for shared state)
# ============================================================================

# Default rate limiter: 60 requests per minute per user
_default_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)

# Default audit (enabled if EXECUTION_AUDIT=true in env)
_audit_enabled = os.getenv("EXECUTION_AUDIT", "true").lower() in ("true", "1", "yes")
_default_audit = ExecutionAudit(enabled=_audit_enabled)

# Default sandbox
_default_sandbox = ExecutionSandbox()


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _default_rate_limiter


def get_audit() -> ExecutionAudit:
    """Get the global audit instance."""
    return _default_audit


def get_sandbox() -> ExecutionSandbox:
    """Get the global sandbox instance."""
    return _default_sandbox
