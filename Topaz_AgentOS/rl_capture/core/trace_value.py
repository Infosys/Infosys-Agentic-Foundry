"""Trace value assessment contracts and deterministic guards.

The semantic "valuable for what?" judgement is intentionally delegated to a
tenant skill. This module owns only deterministic eligibility, prompt-safe
evidence packaging, strict JSON validation, and destination normalization.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from rl_capture.core.redaction import redact_value, scan_pii


RUBRIC_VERSION = "trace_value_router_v1"
TRACE_VALUE_DESTINATIONS = (
    "skill",
    "context",
    "memory",
    "golden_eval",
    "model_training",
    "debug_only",
)
QUALITY_VERDICTS = {"pass", "partial", "fail"}


def final_response_text(detail: dict[str, Any]) -> str:
    trajectory = _trajectory(detail)
    calls = trajectory.get("model_calls") or []
    if not calls:
        candidates = detail.get("candidates") or []
        for candidate in candidates:
            messages = candidate.get("messages") or []
            text = "\n".join(str(m.get("content") or "") for m in messages if isinstance(m, dict)).strip()
            if text:
                return text
        return ""
    last = calls[-1] or {}
    return "\n".join(
        str(m.get("content") or "")
        for m in (last.get("output_messages") or [])
        if isinstance(m, dict)
    ).strip()


def eligibility(detail: dict[str, Any]) -> dict[str, Any]:
    trajectory = _trajectory(detail)
    task = str(trajectory.get("task") or "").strip()
    response = final_response_text(detail)
    status = str(trajectory.get("terminal_status") or "").lower()
    reasons: list[str] = []

    if not str(trajectory.get("id") or "").strip():
        reasons.append("missing_trajectory_id")
    if status not in {"success", "done"}:
        reasons.append(f"terminal:{status or 'unknown'}")
    if not task:
        reasons.append("missing_task")
    if not response:
        reasons.append("missing_response")
    if any((tool or {}).get("status") == "error" or (tool or {}).get("error") for tool in trajectory.get("tool_calls") or []):
        reasons.append("tool_error")
    packet = build_evidence_packet(detail, max_chars=16000)
    residual = scan_pii(json.dumps(packet, ensure_ascii=False, default=str))
    if residual:
        reasons.append("residual_pii:" + ",".join(sorted(residual)))

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "debug_only": bool(reasons),
        "task": task,
        "response_chars": len(response),
    }


def build_evidence_packet(detail: dict[str, Any], *, max_chars: int = 12000) -> dict[str, Any]:
    """Return a redacted, bounded packet for the semantic judge skill."""
    trajectory = _trajectory(detail)
    task = str(trajectory.get("task") or "")[:2000]
    response = final_response_text(detail)[:4000]
    tools = []
    for tool in (trajectory.get("tool_calls") or [])[:8]:
        tools.append({
            "id": tool.get("id"),
            "name": tool.get("name"),
            "status": tool.get("status"),
            "arguments": _truncate(tool.get("arguments"), 1000),
            "output": _truncate(tool.get("output"), 1500),
            "error": _truncate(tool.get("error"), 500),
        })
    observations = []
    for obs in (trajectory.get("observations") or [])[:5]:
        observations.append({
            "id": obs.get("id"),
            "source": obs.get("source"),
            "payload": _truncate(obs.get("payload"), 1500),
            "error": _truncate(obs.get("error"), 500),
        })
    rewards = [
        {
            "channel": reward.get("channel"),
            "label": reward.get("raw_label"),
            "value": reward.get("raw_value"),
            "confidence": reward.get("confidence"),
            "judge_id": reward.get("judge_id"),
        }
        for reward in (detail.get("rewards") or [])[:12]
    ]
    packet = {
        "trajectory_id": trajectory.get("id"),
        "tenant_id": (trajectory.get("capture") or {}).get("tenant_id") or trajectory.get("tenant"),
        "agent_id": (trajectory.get("capture") or {}).get("agent_id"),
        "skill": (trajectory.get("metadata") or {}).get("skill"),
        "terminal_status": trajectory.get("terminal_status"),
        "task": task,
        "final_response": response,
        "tools": tools,
        "observations": observations,
        "rewards": rewards,
        "preferences_count": len(detail.get("preferences") or []),
    }
    redacted = redact_value(packet).value
    text = json.dumps(redacted, ensure_ascii=False, default=str)
    if len(text) > max_chars:
        redacted["truncated"] = True
        redacted["final_response"] = str(redacted.get("final_response") or "")[:2000]
        redacted["tools"] = redacted.get("tools", [])[:4]
        redacted["observations"] = redacted.get("observations", [])[:3]
    return redacted


def input_hash(packet: dict[str, Any]) -> str:
    canonical = json.dumps(packet, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_assessment_response(text: str, *, trajectory_id: str, packet_hash: str) -> dict[str, Any]:
    """Parse and normalize the trace_value_router skill's strict JSON output."""
    match = re.search(r"\{.*\}", str(text or ""), re.DOTALL)
    if not match:
        raise ValueError("trace value response contained no JSON object")
    data = json.loads(match.group(0))

    quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
    score = _clamp_float(quality.get("score", data.get("score", 0.0)), -1.0, 1.0)
    confidence = _clamp_float(quality.get("confidence", data.get("confidence", 0.5)), 0.0, 1.0)
    verdict = str(quality.get("verdict") or data.get("verdict") or "").lower()
    if verdict not in QUALITY_VERDICTS:
        verdict = "pass" if score >= 0.3 else ("fail" if score <= -0.3 else "partial")

    raw_destinations = data.get("destinations") if isinstance(data.get("destinations"), dict) else {}
    destinations = {name: _clamp_float(raw_destinations.get(name, 0.0), 0.0, 1.0) for name in TRACE_VALUE_DESTINATIONS}
    if verdict == "fail" and destinations["debug_only"] < 0.5:
        destinations["debug_only"] = 0.5

    rationale = data.get("rationale") if isinstance(data.get("rationale"), dict) else {}
    risks = data.get("risks") if isinstance(data.get("risks"), list) else []
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"tva_{trajectory_id}_{packet_hash[:12]}",
        "trajectory_id": trajectory_id,
        "input_hash": packet_hash,
        "rubric": str(data.get("rubric") or RUBRIC_VERSION),
        "quality": {"score": score, "verdict": verdict, "confidence": confidence},
        "destinations": destinations,
        "learning": str(data.get("learning") or "").strip()[:2000],
        "rationale": {str(k): str(v)[:500] for k, v in rationale.items()},
        "risks": [str(r)[:300] for r in risks[:20]],
        "evidence_refs": data.get("evidence_refs") if isinstance(data.get("evidence_refs"), list) else [],
        "human_approval_required": bool(data.get("human_approval_required", True)),
        "created_at": now,
        "metadata": {
            "scope": data.get("scope"),
            "stability": data.get("stability"),
            "generalizability": data.get("generalizability"),
        },
    }


def debug_assessment(detail: dict[str, Any], *, packet_hash: str, reasons: list[str]) -> dict[str, Any]:
    trajectory = _trajectory(detail)
    tid = str(trajectory.get("id") or "unknown")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"tva_{tid}_{packet_hash[:12]}",
        "trajectory_id": tid,
        "input_hash": packet_hash,
        "rubric": RUBRIC_VERSION,
        "quality": {"score": -1.0, "verdict": "fail", "confidence": 1.0},
        "destinations": {name: (1.0 if name == "debug_only" else 0.0) for name in TRACE_VALUE_DESTINATIONS},
        "learning": "",
        "rationale": {"debug_only": "; ".join(reasons)[:500]},
        "risks": reasons,
        "evidence_refs": [],
        "human_approval_required": False,
        "created_at": now,
        "metadata": {"eligible": False, "reasons": reasons},
    }


def _trajectory(detail: dict[str, Any]) -> dict[str, Any]:
    return detail.get("trajectory") if isinstance(detail, dict) and isinstance(detail.get("trajectory"), dict) else detail


def _truncate(value: Any, limit: int) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit] + ("..." if len(text) > limit else "")


def _clamp_float(value: Any, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = lower
    return round(max(lower, min(upper, parsed)), 3)
