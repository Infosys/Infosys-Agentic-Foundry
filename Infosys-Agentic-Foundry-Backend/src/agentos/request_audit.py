# -*- coding: utf-8 -*-
# (c) 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
RequestAuditTrail -- capture a complete, structured record of every
inference request's lifecycle: routing, LLM calls, tool invocations,
data accessed, errors, and final response.

Unlike ShellAuditLogger (which only captures shell commands), this module
tracks the FULL request pipeline for compliance, debugging, and
observability.

Usage inside skill_agent_inference.py:

    from src.agentos.request_audit import RequestAuditTrail

    audit = RequestAuditTrail(
        request_id=f"{session_id}_{turn}",
        agent_id=agent_id,
        session_id=session_id,
        user_email=user_email,
        model_name=model_name,
    )
    audit.record_routing(skill_name, method, confidence)
    audit.record_llm_call(iteration, prompt_tokens, completion_tokens, duration_ms)
    audit.record_tool_call(tool_name, args_preview, result_preview, duration_ms, success)
    audit.record_error("context_length", "prompt exceeds 128k tokens")
    audit.finalize(response_preview, total_duration_ms)
    # audit auto-flushes on finalize; can also flush manually via audit.flush()
"""

import os
import json
import time
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config.application_config import app_config
try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_AUDIT_DIR_RAW = app_config.REQUEST_AUDIT_DIR
# Sanitize: resolve to absolute, reject if it escapes expected base
_AUDIT_DIR = Path(os.path.realpath(_AUDIT_DIR_RAW))
# Containment: verify resolved path is under project root
_PROJECT_ROOT = Path(os.path.realpath("."))
if not str(_AUDIT_DIR).startswith(str(_PROJECT_ROOT)):
    import logging as _logging
    _logging.getLogger(__name__).warning(
        f"REQUEST_AUDIT_DIR escapes project root, using default: {_AUDIT_DIR}"
    )
    _AUDIT_DIR = _PROJECT_ROOT / "audit_logs" / "requests"
_ENABLE_REQUEST_AUDIT = os.getenv(
    "ENABLE_REQUEST_AUDIT", "true"
).lower() in ("true", "1", "yes")
# Maximum entries kept in memory before auto-flush
_MAX_EVENTS_BEFORE_FLUSH = 200
# Maximum tool arg / result preview length
_PREVIEW_LEN = 500


class RequestAuditTrail:
    """Captures an immutable, append-only audit record for a single request."""

    def __init__(
        self,
        request_id: str = "",
        agent_id: str = "",
        session_id: str = "",
        user_email: str = "",
        model_name: str = "",
        query: str = "",
    ):
        self.request_id = request_id or str(uuid.uuid4())[:12]
        self.agent_id = agent_id
        self.session_id = session_id
        self.user_email = user_email
        self.model_name = model_name
        self.query = query[:1000]  # Truncate very long queries

        self._start_time = time.time()
        self._events: List[Dict[str, Any]] = []
        self._finalized = False
        self._lock = threading.Lock()

        # Summary counters
        self._llm_call_count = 0
        self._tool_call_count = 0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._error_count = 0
        self._truncation_applied = False

        if _ENABLE_REQUEST_AUDIT:
            self._append_event("request_start", {
                "query": self.query,
                "model_name": self.model_name,
            })

    # ------------------------------------------------------------------
    # Public recording methods
    # ------------------------------------------------------------------

    def record_routing(
        self,
        skill_name: str,
        method: str,
        confidence: float,
        candidate_skills: Optional[List[str]] = None,
    ):
        """Record which skill was selected and how."""
        self._append_event("routing", {
            "skill_name": skill_name,
            "method": method,
            "confidence": round(confidence, 4),
            "candidate_skills": candidate_skills or [],
        })

    def record_prompt_budget(
        self,
        original_tokens: int,
        final_tokens: int,
        truncation_log: List[str],
    ):
        """Record prompt budget enforcement results."""
        self._truncation_applied = original_tokens != final_tokens
        self._append_event("prompt_budget", {
            "original_tokens_est": original_tokens,
            "final_tokens_est": final_tokens,
            "truncated": self._truncation_applied,
            "actions": truncation_log,
        })

    def record_llm_call(
        self,
        iteration: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: float = 0.0,
        model_name: str = "",
        has_tool_calls: bool = False,
    ):
        """Record a single LLM invocation."""
        self._llm_call_count += 1
        self._total_prompt_tokens += prompt_tokens
        self._total_completion_tokens += completion_tokens
        self._append_event("llm_call", {
            "iteration": iteration,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "duration_ms": round(duration_ms, 1),
            "model": model_name or self.model_name,
            "has_tool_calls": has_tool_calls,
        })

    def record_tool_call(
        self,
        tool_name: str,
        args_preview: str = "",
        result_preview: str = "",
        duration_ms: float = 0.0,
        success: bool = True,
        blocked: bool = False,
        blocked_reason: str = "",
    ):
        """Record a tool invocation."""
        self._tool_call_count += 1
        self._append_event("tool_call", {
            "tool_name": tool_name,
            "args_preview": str(args_preview)[:_PREVIEW_LEN],
            "result_preview": str(result_preview)[:_PREVIEW_LEN],
            "duration_ms": round(duration_ms, 1),
            "success": success,
            "blocked": blocked,
            "blocked_reason": blocked_reason,
        })

    def record_data_access(
        self,
        source: str,
        operation: str = "read",
        details: str = "",
    ):
        """Record data accessed (DB query, file read, API call)."""
        self._append_event("data_access", {
            "source": source,
            "operation": operation,
            "details": details[:_PREVIEW_LEN],
        })

    def record_error(
        self,
        error_type: str,
        message: str,
        recoverable: bool = True,
    ):
        """Record an error encountered during processing."""
        self._error_count += 1
        self._append_event("error", {
            "error_type": error_type,
            "message": str(message)[:1000],
            "recoverable": recoverable,
        })

    def record_knowledge_context(
        self,
        entries_used: int,
        source: str = "knowledge_store",
    ):
        """Record knowledge context injection."""
        self._append_event("knowledge_context", {
            "entries_used": entries_used,
            "source": source,
        })

    def record_session_restore(self, restored: bool, source: str = "redis"):
        """Record whether session state was restored."""
        self._append_event("session_restore", {
            "restored": restored,
            "source": source,
        })

    def finalize(
        self,
        response_preview: str = "",
        total_duration_ms: float = 0.0,
        skill_name: str = "",
        success: bool = True,
    ):
        """Finalize and flush the audit record."""
        if self._finalized:
            return

        if total_duration_ms == 0.0:
            total_duration_ms = (time.time() - self._start_time) * 1000

        self._append_event("request_end", {
            "response_preview": response_preview[:_PREVIEW_LEN],
            "total_duration_ms": round(total_duration_ms, 1),
            "skill_name": skill_name,
            "success": success,
            "summary": {
                "llm_calls": self._llm_call_count,
                "tool_calls": self._tool_call_count,
                "errors": self._error_count,
                "total_prompt_tokens": self._total_prompt_tokens,
                "total_completion_tokens": self._total_completion_tokens,
                "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
                "prompt_truncated": self._truncation_applied,
            },
        })
        self._finalized = True
        self.flush()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def flush(self):
        """Write accumulated events to the JSONL audit log."""
        if not _ENABLE_REQUEST_AUDIT:
            return
        with self._lock:
            if not self._events:
                return
            events_to_write = list(self._events)
            self._events.clear()

        try:
            _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = _AUDIT_DIR / f"request_audit_{date_str}.jsonl"

            # Build the audit record as a single JSON line
            record = {
                "request_id": self.request_id,
                "agent_id": self.agent_id,
                "session_id": self.session_id,
                "user_email": self.user_email,
                "model_name": self.model_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "events": events_to_write,
            }

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")

            log.debug(
                f"[RequestAudit] Flushed {len(events_to_write)} events "
                f"for request {self.request_id}"
            )
        except Exception as e:
            log.error(f"[RequestAudit] Failed to write audit log: {e}")

    # ------------------------------------------------------------------
    # Query (for admin/debug endpoints)
    # ------------------------------------------------------------------

    @staticmethod
    def get_logs(
        date: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_email: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve request audit logs with optional filtering.

        Args:
            date: Date string (YYYY-MM-DD). Defaults to today.
            agent_id: Filter by agent ID.
            session_id: Filter by session ID.
            user_email: Filter by user email.
            limit: Maximum entries to return.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Validate date format to prevent path traversal via malicious input
        import re as _re
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            log.warning(f"[RequestAudit] Invalid date format rejected: {date!r}")
            return []

        log_file = _AUDIT_DIR / f"request_audit_{date}.jsonl"
        if not log_file.exists():
            return []

        from collections import deque
        entries: deque = deque(maxlen=limit)
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if agent_id and record.get("agent_id") != agent_id:
                        continue
                    if session_id and record.get("session_id") != session_id:
                        continue
                    if user_email and record.get("user_email") != user_email:
                        continue
                    entries.append(record)
        except Exception as e:
            log.error(f"[RequestAudit] Error reading audit log: {e}")

        return list(entries)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append_event(self, event_type: str, data: Dict[str, Any]):
        """Thread-safe event append."""
        if not _ENABLE_REQUEST_AUDIT:
            return
        event = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        with self._lock:
            self._events.append(event)
            # Auto-flush if too many events in memory (safety valve)
            if len(self._events) >= _MAX_EVENTS_BEFORE_FLUSH:
                pass  # Will flush on next finalize or manual flush
