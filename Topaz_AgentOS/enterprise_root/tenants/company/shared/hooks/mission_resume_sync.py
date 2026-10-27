#!/usr/bin/env python3
"""
Mission Mode — AfterApprovalResume sync hook.

Fires after any HITL approval resume completes. The approval router now owns
Mission Mode workstream state transitions directly: approval moves the item
to in_progress, and the background resume helper marks it done/failed only
after resumed execution returns.

This hook remains as an observe-only compatibility probe. It still resolves
which workstream item belongs to the approval and writes an audit line, but it
does not patch YAML. Keeping one writer avoids duplicate or premature item
finalization.

Hook contract:
- exits 0 always (observe-only; doesn't gate the resume)
- reads IAF_APPROVAL_ID / IAF_APPROVAL_DECISION / IAF_APPROVAL_DECIDED_BY
  and IAF_TENANT_ID env vars (set by hook_runner._build_env)
- no-ops cleanly if the approval isn't tied to a workstream
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


# Use the platform temp dir so this works on Windows (no /tmp/) as well as Unix.
LOG_PATH = os.path.join(tempfile.gettempdir(), "mission_resume_sync.log")


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"{ts} mission_resume_sync event\n"
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass


def _enterprise_root() -> Path:
    """
    Best-effort: derive enterprise_root from IAF_AGENT_ROOT
    (=enterprise_root/tenants/<id>/agents/<agent_id>). Falls back to a
    conventional path so the hook still works in a stripped CLI env.
    """
    return Path(__file__).resolve().parents[4]


def _workstreams_dir(tenant_id: str) -> Path:
    return _enterprise_root() / "tenants" / tenant_id / "workstreams"


def _load_approval_context(approval_id: str, tenant_id: str) -> dict:
    """
    Read the resolved approval back from Redis to extract its context.
    Returns {} on any failure — caller falls back to scanning workstreams.
    """
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://localhost:6379")
        # Strip auth fragments redis-py can parse
        r = redis.from_url(url, decode_responses=True)
        raw = r.hget(f"iaf:approval:{approval_id}", "context")
        if not raw:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}
    except Exception as exc:
        log(f"  ctx_lookup_failed approval={approval_id[:8]} err={type(exc).__name__}")
        return {}


def _find_workstream_for_approval(
    approval_id: str, tenant_id: str
) -> tuple[str, str] | tuple[None, None]:
    """
    Scan all workstream YAMLs in the tenant for an item whose
    escalated_approval_id matches. Returns (workstream_name, item_id) or
    (None, None) if no match.

    Used as the legacy fallback when the approval's context dict doesn't
    carry workstream_name (older approvals predating the engine's context
    injection).
    """
    ws_dir = _workstreams_dir(tenant_id)
    if not ws_dir.exists():
        return None, None
    for path in sorted(ws_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for it in data.get("items", []):
            if it.get("escalated_approval_id") == approval_id:
                return data.get("name") or path.stem, it.get("id")
    return None, None


def _patch_workstream_item(
    tenant_id: str,
    workstream_name: str,
    item_id: str | None,
    *,
    decision: str,
    decided_by: str,
    approval_id: str,
) -> bool:
    """
    Observe the matching item in the workstream YAML. The approval router owns
    final status writes, so this hook intentionally avoids changing item state.
    """
    log(
        f"  observe_only workstream={workstream_name} item={item_id or '?'} "
        f"decision={decision!r} decided_by={decided_by or 'unknown'} "
        f"approval={approval_id[:8]}"
    )
    return True


def main() -> int:
    approval_id = os.getenv("IAF_APPROVAL_ID", "").strip()
    decision = os.getenv("IAF_APPROVAL_DECISION", "").strip()
    decided_by = os.getenv("IAF_APPROVAL_DECIDED_BY", "").strip()
    tenant_id = os.getenv("IAF_TENANT_ID", "").strip() or "company"
    resume_status = os.getenv("IAF_RESUME_STATUS", "").strip()

    log(
        f"AfterApprovalResume approval={approval_id[:8] if approval_id else '?'} "
        f"decision={decision!r} decided_by={decided_by!r} tenant={tenant_id} "
        f"resume_status={resume_status!r}"
    )

    if not approval_id or not decision:
        log("  missing approval_id or decision — no-op")
        logger.debug(json.dumps({"blocked": False}))
        return 0

    # Method A: approval's context dict (injected by mission_engine for new runs)
    ctx = _load_approval_context(approval_id, tenant_id)
    ws_name = ctx.get("workstream_name")
    item_id = ctx.get("mission_item_id")

    # Method B: scan all workstreams (legacy approvals + safety net)
    if not ws_name:
        ws_name, item_id = _find_workstream_for_approval(approval_id, tenant_id)

    if not ws_name:
        log(f"  no_workstream_match approval={approval_id[:8]} — not a Mission Mode approval")
        logger.debug(json.dumps({"blocked": False}))
        return 0

    _patch_workstream_item(
        tenant_id, ws_name, item_id,
        decision=decision, decided_by=decided_by, approval_id=approval_id,
    )

    logger.debug(json.dumps({"blocked": False}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sys.exit(main())
