"""SFT exporters for chat and prompt/completion formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def trajectory_to_chat_sft_row(trajectory: dict) -> dict | None:
    model_calls = trajectory.get("model_calls") or []
    if not model_calls:
        return None
    final_call = model_calls[-1]
    output_messages = final_call.get("output_messages") or []
    # Require a non-empty assistant target (text or tool call); mirrors the prompt/completion exporter.
    if not any((m.get("content") or "").strip() or m.get("tool_calls") for m in output_messages):
        return None
    messages = (final_call.get("input_messages") or []) + output_messages
    if not messages:
        return None
    return {
        "messages": messages,
        "metadata": {
            "trajectory_id": trajectory.get("id"),
            "tenant": trajectory.get("tenant"),
            "skill": (trajectory.get("metadata") or {}).get("skill"),
            "fidelity": trajectory.get("fidelity"),
        },
    }


def trajectory_to_prompt_completion_row(trajectory: dict) -> dict | None:
    model_calls = trajectory.get("model_calls") or []
    if not model_calls:
        return None
    final_call = model_calls[-1]
    prompt = _messages_text(final_call.get("input_messages") or []) or str(trajectory.get("task") or "")
    completion = _messages_text(final_call.get("output_messages") or [])
    if not prompt or not completion:
        return None
    return {
        "prompt": prompt,
        "completion": completion,
        "metadata": {
            "trajectory_id": trajectory.get("id"),
            "tenant": trajectory.get("tenant"),
            "skill": (trajectory.get("metadata") or {}).get("skill"),
            "fidelity": trajectory.get("fidelity"),
        },
    }


def materialize_sft_rows(trajectories: Iterable[dict], *, format: str = "chat") -> list[dict]:
    rows: list[dict] = []
    for trajectory in trajectories:
        row = (
            trajectory_to_prompt_completion_row(trajectory)
            if format == "prompt_completion"
            else trajectory_to_chat_sft_row(trajectory)
        )
        if row:
            rows.append(row)
    return rows


def export_sft_jsonl(trajectories: Iterable[dict], output_path: str | Path, *, format: str = "chat") -> int:
    rows = materialize_sft_rows(trajectories, format=format)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def _messages_text(messages: list[dict]) -> str:
    return "\n".join(str(message.get("content") or "") for message in messages if message.get("content"))
