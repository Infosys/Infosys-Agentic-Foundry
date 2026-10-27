"""Eval/replay JSONL exporter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def trajectory_to_eval_case(trajectory: dict) -> dict:
    model_calls = trajectory.get("model_calls") or []
    final_messages = []
    if model_calls:
        final_messages = model_calls[-1].get("output_messages") or []
    return {
        "id": trajectory.get("id"),
        "input": trajectory.get("task") or "",
        "expected_behavior": "Replay/evaluate captured agent trajectory.",
        "messages": model_calls[-1].get("input_messages") if model_calls else [],
        "actual_output": final_messages,
        "metadata": {
            "tenant": trajectory.get("tenant"),
            "agent_id": (trajectory.get("capture") or {}).get("agent_id"),
            "session_id": trajectory.get("session_id"),
            "fidelity": trajectory.get("fidelity"),
            "terminal_status": trajectory.get("terminal_status"),
        },
    }


def materialize_eval_cases(trajectories: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for trajectory in trajectories:
        row = trajectory_to_eval_case(trajectory)
        if _has_replay_text(row):
            rows.append(row)
    return rows


def export_eval_jsonl(trajectories: Iterable[dict], output_path: str | Path) -> int:
    rows = materialize_eval_cases(trajectories)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def _has_replay_text(row: dict) -> bool:
    if str(row.get("input") or "").strip():
        return True
    for key in ("messages", "actual_output"):
        value = row.get(key)
        if isinstance(value, list) and any(str(item.get("content") or "").strip() for item in value if isinstance(item, dict)):
            return True
    return False
