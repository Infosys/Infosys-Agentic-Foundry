# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
ApprovalManager - Human-in-the-Loop (HITL) approval system.

Provides:
- Rule-based gating: intercept tool calls before execution based on hook exit codes
- Threshold checks: field-based rules (e.g., amount > 10000 → require approval)
- Condition checks: context-based rules (e.g., blocked_vendor → require approval)
- Approval queue: pending approvals are stored and can be approved/rejected via API
- Audit trail: every approval/rejection is logged

Approval flow:
1. Agent calls a tool → ApprovalManager intercepts
2. Check hook exit codes (exit 2 = approval required)
3. If approval required → park the action as "pending", return gating message
4. User approves/rejects via API endpoint
5. On approve → execute the parked tool call
6. On reject → discard and inform agent
"""

import os
import json
import uuid
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Enums & Data Models
# ============================================================================

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    AUTO_APPROVED = "auto_approved"


class ApprovalUrgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Per-urgency SLA defaults (minutes)
SLA_DEFAULTS_MINUTES: Dict[str, int] = {
    ApprovalUrgency.LOW: 480,       # 8 hours
    ApprovalUrgency.MEDIUM: 120,    # 2 hours
    ApprovalUrgency.HIGH: 30,       # 30 minutes
    ApprovalUrgency.CRITICAL: 10,   # 10 minutes
}


def get_sla_minutes(urgency: str) -> int:
    """Return SLA minutes for a given urgency level."""
    return SLA_DEFAULTS_MINUTES.get(urgency, SLA_DEFAULTS_MINUTES[ApprovalUrgency.MEDIUM])


@dataclass
class ApprovalRequest:
    """A pending approval request."""
    request_id: str
    agent_id: str
    session_id: str
    user_email: str
    skill_name: str
    tool_name: str
    tool_args: Dict[str, Any]
    reason: str
    urgency: str = ApprovalUrgency.MEDIUM
    status: str = ApprovalStatus.PENDING
    created_at: str = ""
    sla_deadline: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_note: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.sla_deadline:
            from datetime import timedelta
            created = datetime.fromisoformat(self.created_at)
            sla_mins = get_sla_minutes(self.urgency)
            self.sla_deadline = (created + timedelta(minutes=sla_mins)).isoformat()

    @property
    def is_past_sla(self) -> bool:
        """Check if this request has exceeded its SLA deadline."""
        if not self.sla_deadline:
            return False
        try:
            deadline = datetime.fromisoformat(self.sla_deadline)
            return datetime.now(timezone.utc) > deadline
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["is_past_sla"] = self.is_past_sla
        d["sla_minutes"] = get_sla_minutes(self.urgency)
        return d


@dataclass 
class ApprovalRule:
    """Parsed approval rule from SKILL.md frontmatter."""
    always_require: List[str] = field(default_factory=list)
    thresholds: List[Dict[str, Any]] = field(default_factory=list)
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    never_require: List[str] = field(default_factory=list)


# ============================================================================
# ApprovalManager
# ============================================================================

class ApprovalManager:
    """
    Manages HITL approvals for agent tool calls.
    
    Usage:
        manager = ApprovalManager(storage_path="./approvals")
        
        # Check if a tool call needs approval
        result = manager.check_approval(
            rules=None,
            tool_name="delete_record",
            tool_args={"record_id": "123"},
            agent_id="agent_1",
            session_id="sess_1",
            user_email="user@company.com",
            skill_name="data_cleanup",
        )
        
        if result is not None:
            # Approval is required — result is the ApprovalRequest
            return f"⏸️ Action paused: {result.reason}. Approval ID: {result.request_id}"
        
        # No approval needed — proceed with tool execution
    """

    def __init__(
        self,
        storage_path: str = "./agent_workspaces/approvals",
        expiry_hours: int = 24,
    ):
        """
        Initialize ApprovalManager.
        
        Args:
            storage_path: Directory to persist approval requests.
            expiry_hours: Hours before a pending approval expires.
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.expiry_hours = expiry_hours
        self._pending: Dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._load_pending()
        log.info(f"ApprovalManager initialized: storage={self.storage_path}, pending={len(self._pending)}")

    # ---- Public API ----

    def check_approval(
        self,
        rules: Any,
        tool_name: str,
        tool_args: Dict[str, Any],
        agent_id: str,
        session_id: str,
        user_email: str,
        skill_name: str,
    ) -> Optional[ApprovalRequest]:
        """
        Check if a tool call requires approval.
        
        Args:
            rules: Approval rules object or None.
            tool_name: Name of the tool being called.
            tool_args: Arguments to the tool.
            agent_id: The agent's ID.
            session_id: The session ID.
            user_email: The user's email.
            skill_name: The active skill name.
            
        Returns:
            ApprovalRequest if approval is needed, None if auto-approved.
        """
        # ── Recently-approved fast path ──────────────────────────────
        # If the same tool was already approved in this session within
        # the last 60 minutes, auto-approve so the user doesn't get
        # stuck in a park → approve → re-park loop.
        import datetime as _dt
        _now = _dt.datetime.now(_dt.timezone.utc)
        _grace_minutes = 60
        with self._lock:
            for _req in self._pending.values():
                if (
                    _req.status == ApprovalStatus.APPROVED
                    and _req.agent_id == agent_id
                    and _req.session_id == session_id
                    and _req.tool_name == tool_name
                    and _req.resolved_at is not None
                ):
                    try:
                        _resolved = (
                            _dt.datetime.fromisoformat(_req.resolved_at)
                            if isinstance(_req.resolved_at, str)
                            else _req.resolved_at
                        )
                        # Ensure both are timezone-aware for comparison
                        if _resolved.tzinfo is None:
                            _resolved = _resolved.replace(tzinfo=_dt.timezone.utc)
                        if (_now - _resolved).total_seconds() < _grace_minutes * 60:
                            log.info(
                                f"Auto-approve: tool '{tool_name}' was approved "
                                f"{int((_now - _resolved).total_seconds())}s ago "
                                f"in session {session_id}"
                            )
                            return None  # honour the earlier approval
                    except Exception as _grace_err:
                        log.debug(f"Grace period check failed for {_req.request_id}: {_grace_err}")

        # Convert to standard format
        if hasattr(rules, "always_require"):
            always_require = rules.always_require
            thresholds = rules.thresholds
            conditions = rules.conditions
            never_require = rules.never_require
        elif isinstance(rules, dict):
            always_require = rules.get("always_require", [])
            thresholds = rules.get("thresholds", [])
            conditions = rules.get("conditions", [])
            never_require = rules.get("never_require", [])
        else:
            return None  # No rules → auto-approve

        # Check never_require first (whitelist)
        if tool_name in never_require:
            return None

        # Check always_require (blacklist)
        if tool_name in always_require:
            return self._create_request(
                agent_id=agent_id,
                session_id=session_id,
                user_email=user_email,
                skill_name=skill_name,
                tool_name=tool_name,
                tool_args=tool_args,
                reason=f"Tool '{tool_name}' always requires approval",
                urgency=ApprovalUrgency.MEDIUM,
            )

        # Check threshold rules
        for threshold in thresholds:
            field_name = threshold.get("field", "")
            operator = threshold.get("operator", ">=")
            value = threshold.get("value", 0)
            reason = threshold.get("reason", f"Threshold exceeded: {field_name} {operator} {value}")
            urgency = threshold.get("urgency", ApprovalUrgency.MEDIUM)

            # Check if the field exists in tool_args
            field_value = tool_args.get(field_name)
            if field_value is not None:
                try:
                    field_value = float(field_value)
                    value = float(value)
                    triggered = False
                    if operator == ">=" and field_value >= value:
                        triggered = True
                    elif operator == ">" and field_value > value:
                        triggered = True
                    elif operator == "<=" and field_value <= value:
                        triggered = True
                    elif operator == "<" and field_value < value:
                        triggered = True
                    elif operator == "==" and field_value == value:
                        triggered = True
                    
                    if triggered:
                        return self._create_request(
                            agent_id=agent_id,
                            session_id=session_id,
                            user_email=user_email,
                            skill_name=skill_name,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            reason=reason,
                            urgency=urgency,
                        )
                except (ValueError, TypeError):
                    pass

        # Check condition rules
        for condition in conditions:
            when = condition.get("when", "")
            reason = condition.get("reason", f"Condition triggered: {when}")
            urgency = condition.get("urgency", ApprovalUrgency.MEDIUM)

            # Check if the condition field is truthy in tool_args
            if when in tool_args and tool_args[when]:
                return self._create_request(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_email=user_email,
                    skill_name=skill_name,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    reason=reason,
                    urgency=urgency,
                )

        return None  # No rules triggered → auto-approve

    def approve(
        self,
        request_id: str,
        approved_by: str,
        note: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """
        Approve a pending request.
        
        Returns:
            The updated ApprovalRequest, or None if not found.
        """
        return self._resolve(request_id, ApprovalStatus.APPROVED, approved_by, note)

    def reject(
        self,
        request_id: str,
        rejected_by: str,
        note: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """
        Reject a pending request.
        
        Returns:
            The updated ApprovalRequest, or None if not found.
        """
        return self._resolve(request_id, ApprovalStatus.REJECTED, rejected_by, note)

    def get_pending(
        self,
        agent_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> List[ApprovalRequest]:
        """
        Get all pending approval requests, optionally filtered.
        
        Args:
            agent_id: Filter by agent ID.
            user_email: Filter by user email.
            
        Returns:
            List of pending ApprovalRequests.
        """
        with self._lock:
            results = []
            for req in self._pending.values():
                if req.status != ApprovalStatus.PENDING:
                    continue
                if agent_id and req.agent_id != agent_id:
                    continue
                if user_email and req.user_email != user_email:
                    continue
                results.append(req)
            return sorted(results, key=lambda r: r.created_at, reverse=True)

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get a specific approval request by ID."""
        with self._lock:
            return self._pending.get(request_id)

    def expire_stale(self) -> int:
        """Expire pending requests that have passed their SLA deadline.

        Returns:
            Number of requests expired.
        """
        count = 0
        with self._lock:
            for req in list(self._pending.values()):
                if req.status == ApprovalStatus.PENDING and req.is_past_sla:
                    req.status = ApprovalStatus.EXPIRED
                    req.resolved_at = datetime.now(timezone.utc).isoformat()
                    req.resolution_note = "Auto-expired: SLA deadline exceeded"
                    self._audit_log(req, "expired")
                    count += 1
            if count:
                self._persist_pending()
                log.info(f"Auto-expired {count} stale approval requests")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics on approvals."""
        with self._lock:
            pending = sum(1 for r in self._pending.values() if r.status == ApprovalStatus.PENDING)
            past_sla = sum(
                1 for r in self._pending.values()
                if r.status == ApprovalStatus.PENDING and r.is_past_sla
            )
        return {
            "pending_total": pending,
            "pending_past_sla": past_sla,
            "sla_defaults": dict(SLA_DEFAULTS_MINUTES),
        }

    @staticmethod
    def merge_rules(skill_rules: Any, agent_rules: Any) -> Optional[Dict[str, Any]]:
        """Merge skill-level and agent-level approval rules.

        Priority:
          - skill-level ``never_require`` wins over everything (whitelist)
          - skill-level ``always_require`` wins over agent-level
          - agent-level rules act as global fallback

        Returns ``None`` if both are empty, otherwise a merged dict.
        """
        def _to_dict(rules) -> Dict[str, Any]:
            if rules is None:
                return {}
            if hasattr(rules, "always_require"):
                return {
                    "always_require": list(rules.always_require or []),
                    "thresholds": list(rules.thresholds or []),
                    "conditions": list(rules.conditions or []),
                    "never_require": list(rules.never_require or []),
                }
            if isinstance(rules, dict):
                return {
                    "always_require": list(rules.get("always_require") or []),
                    "thresholds": list(rules.get("thresholds") or []),
                    "conditions": list(rules.get("conditions") or []),
                    "never_require": list(rules.get("never_require") or []),
                }
            return {}

        sd = _to_dict(skill_rules)
        ad = _to_dict(agent_rules)

        # If both are empty, no rules at all
        if not any(sd.values()) and not any(ad.values()):
            return None

        # Merge: union of lists, skill-level takes priority for conflicts
        merged = {
            "always_require": list(set(sd.get("always_require", []) + ad.get("always_require", []))),
            "thresholds": sd.get("thresholds", []) + ad.get("thresholds", []),
            "conditions": sd.get("conditions", []) + ad.get("conditions", []),
            "never_require": list(set(sd.get("never_require", []) + ad.get("never_require", []))),
        }
        # never_require overrides always_require (whitelist wins)
        if merged["never_require"] and merged["always_require"]:
            merged["always_require"] = [
                t for t in merged["always_require"]
                if t not in merged["never_require"]
            ]
        return merged if any(merged.values()) else None

    def get_history(
        self,
        limit: int = 50,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get approval history (all statuses) from audit log.
        
        Args:
            limit: Maximum number of entries.
            agent_id: Filter by agent ID.
            
        Returns:
            List of approval records.
        """
        history_file = self.storage_path / "audit_log.jsonl"
        if not history_file.exists():
            return []

        entries = []
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if agent_id and entry.get("agent_id") != agent_id:
                        continue
                    entries.append(entry)
        except Exception as e:
            log.error(f"Error reading approval audit log: {e}")

        return entries[-limit:]

    # ---- Internal ----

    def _create_request(
        self,
        agent_id: str,
        session_id: str,
        user_email: str,
        skill_name: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        reason: str,
        urgency: str,
    ) -> ApprovalRequest:
        """Create and store a new approval request."""
        request = ApprovalRequest(
            request_id=str(uuid.uuid4()),
            agent_id=agent_id,
            session_id=session_id,
            user_email=user_email,
            skill_name=skill_name,
            tool_name=tool_name,
            tool_args=tool_args,
            reason=reason,
            urgency=urgency,
        )

        with self._lock:
            self._pending[request.request_id] = request
            self._persist_pending()

        self._audit_log(request, "created")
        log.info(f"Approval required: {request.request_id} - {tool_name} - {reason}")
        return request

    def _resolve(
        self,
        request_id: str,
        status: str,
        resolved_by: str,
        note: Optional[str],
    ) -> Optional[ApprovalRequest]:
        """Resolve (approve/reject) a pending request."""
        with self._lock:
            request = self._pending.get(request_id)
            if not request:
                return None
            if request.status != ApprovalStatus.PENDING:
                return request  # Already resolved

            request.status = status
            request.resolved_at = datetime.now(timezone.utc).isoformat()
            request.resolved_by = resolved_by
            request.resolution_note = note
            self._persist_pending()

        self._audit_log(request, status)
        log.info(f"Approval {status}: {request_id} by {resolved_by}")
        return request

    def _persist_pending(self):
        """Save pending requests to disk."""
        pending_file = self.storage_path / "pending.json"
        try:
            data = {rid: req.to_dict() for rid, req in self._pending.items()}
            pending_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._schedule_blob_sync()
        except Exception as e:
            log.error(f"Error persisting pending approvals: {e}")

    def _load_pending(self):
        """Load pending AND recently-resolved requests from disk on startup.

        We keep resolved requests so the "recently approved" fast-path in
        check_approval() survives server restarts.  Old resolved entries
        (>2 hours) are dropped to avoid unbounded growth.
        """
        pending_file = self.storage_path / "pending.json"
        if not pending_file.exists():
            return

        try:
            data = json.loads(pending_file.read_text(encoding="utf-8"))
            _now = datetime.now(timezone.utc)
            for rid, req_data in data.items():
                status = req_data.get("status", ApprovalStatus.PENDING)
                if status == ApprovalStatus.PENDING:
                    self._pending[rid] = ApprovalRequest(**req_data)
                elif status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED):
                    # Keep recently-resolved entries (< 2 hours old)
                    resolved_at_str = req_data.get("resolved_at")
                    if resolved_at_str:
                        try:
                            resolved_at = datetime.fromisoformat(resolved_at_str)
                            if (_now - resolved_at).total_seconds() < 7200:
                                self._pending[rid] = ApprovalRequest(**req_data)
                        except Exception:
                            pass
            log.info(f"Loaded {len(self._pending)} approval records from disk")
        except Exception as e:
            log.error(f"Error loading pending approvals: {e}")

    def _audit_log(self, request: ApprovalRequest, action: str):
        """Append to the audit trail."""
        audit_file = self.storage_path / "audit_log.jsonl"
        try:
            entry = request.to_dict()
            entry["audit_action"] = action
            entry["audit_timestamp"] = datetime.now(timezone.utc).isoformat()
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self._schedule_blob_sync()
        except Exception as e:
            log.error(f"Error writing approval audit log: {e}")

    def _schedule_blob_sync(self):
        """Best-effort push of approvals dir to blob storage."""
        try:
            import os
            _sp = os.getenv('STORAGE_PROVIDER', '')
            if _sp:
                from src.utils.workspace_blob_sync import WorkspaceBlobSync
                from src.storage import get_storage_client
                _client = get_storage_client(_sp)
                _syncer = WorkspaceBlobSync(
                    storage_client=_client,
                    workspace_root=str(self.storage_path.parent.parent),
                    project_root=os.path.abspath("."),
                )
                _syncer.schedule_approvals_sync()
        except Exception:
            pass  # non-critical
