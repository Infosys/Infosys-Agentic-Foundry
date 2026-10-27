"""Tool-calling SFT exporter (agent distillation).

Where :mod:`rl_capture.exporters.sft` emits ``(user_query -> final_response)``
pairs — *response-quality* SFT — this exporter emits the pairs needed to teach a
small model to **act as a tool-using agent**:

    (context + available tools)  ->  the tool call the agent decided

One training row is produced **per tool-emitting model call**, so a multi-step
agent trajectory yields several ``(state -> action)`` rows — exactly the signal a
tool-calling fine-tune needs.

Row shape (chat + tools JSONL, renderable by an HF/Qwen chat template via
``tokenizer.apply_chat_template(messages, tools=tools, ...)``)::

    {"messages": [ {"role": "system"|"user"|..., "content": "..."},
                   {"role": "assistant", "content": "",
                    "tool_calls": [{"id": ..., "type": "function",
                                    "function": {"name": ..., "arguments": {...}}}]} ],
     "tools":    [ {"type": "function", "function": {"name", "description", "parameters"}} ],
     "metadata": {"trajectory_id", "tenant", "skill", "fidelity", "model_call_id",
                  "reward", "terminal_status"}}

The trajectory's shaped reward (see :mod:`rl_capture.core.reward_shaping`) and
terminal status are carried in each row's metadata so a training script can
filter to successful tool sequences downstream. Pass ``min_reward`` to filter at
export time instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from rl_capture.core.reward_shaping import shape_trajectory_reward


def _render_tool_call(tool_call: dict) -> dict:
    """Convert a stored ``ToolCallSpec`` dict into the HF/OpenAI tool-call shape."""
    return {
        "id": str(tool_call.get("call_id") or tool_call.get("id") or ""),
        "type": "function",
        "function": {
            "name": str(tool_call.get("name") or ""),
            "arguments": tool_call.get("arguments") or tool_call.get("args") or {},
        },
    }


def _plain_message(message: dict) -> dict:
    """Normalize a stored message, preserving tool-call context.

    A multi-step trajectory's input_messages include prior assistant tool-call
    turns and tool-result turns. Dropping ``tool_calls`` / ``tool_call_id`` / ``name``
    would make the exported state no longer reflect what the agent actually saw (and
    may not render as a valid tool-call conversation), so carry those fields through.
    """
    result = {"role": str(message.get("role") or ""), "content": message.get("content") or ""}
    if message.get("name"):
        result["name"] = message["name"]
    if message.get("tool_call_id"):
        result["tool_call_id"] = message["tool_call_id"]
    if message.get("tool_calls"):
        result["tool_calls"] = [_render_tool_call(tc) for tc in message["tool_calls"]]
    return result


def trajectory_to_tool_sft_rows(
    trajectory: dict,
    *,
    reward: Optional[float] = None,
    terminal_status: Optional[str] = None,
) -> list[dict]:
    """Emit one tool-calling SFT row per model call that decided a tool call."""
    rows: list[dict] = []
    traj_metadata = trajectory.get("metadata") or {}
    for model_call in trajectory.get("model_calls") or []:
        output_messages = model_call.get("output_messages") or []
        tool_calls: list[dict] = []
        assistant_content = ""
        for message in output_messages:
            specs = message.get("tool_calls") or []
            if specs:
                tool_calls = specs
                assistant_content = message.get("content") or ""
        if not tool_calls:
            continue

        messages = [_plain_message(m) for m in (model_call.get("input_messages") or [])]
        messages.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [_render_tool_call(tc) for tc in tool_calls],
        })
        tools = (model_call.get("metadata") or {}).get("available_tools") or []
        rows.append({
            "messages": messages,
            "tools": tools,
            "metadata": {
                "trajectory_id": trajectory.get("id"),
                "tenant": trajectory.get("tenant"),
                "skill": traj_metadata.get("skill"),
                "fidelity": trajectory.get("fidelity"),
                "model_call_id": model_call.get("id"),
                "reward": reward,
                "terminal_status": terminal_status,
            },
        })
    return rows


def materialize_tool_sft_rows(
    trajectories: Iterable[dict],
    reward_events_by_trajectory: dict[str, list[dict]] | None = None,
    *,
    category_weights: Optional[dict[str, float]] = None,
    label_values: Optional[dict[str, float]] = None,
    min_reward: Optional[float] = None,
) -> list[dict]:
    """Flatten trajectories into tool-calling SFT rows with carried reward.

    ``min_reward`` (default ``None`` = keep all) drops any trajectory whose shaped
    reward is missing or below the threshold, so callers can export only
    known-good tool sequences when they have judgement signal.
    """
    reward_events_by_trajectory = reward_events_by_trajectory or {}
    rows: list[dict] = []
    for trajectory in trajectories:
        trajectory_id = str(trajectory.get("id") or "")
        rewards = reward_events_by_trajectory.get(trajectory_id, [])
        shaped = shape_trajectory_reward(
            rewards,
            category_weights=category_weights,
            label_values=label_values,
            terminal_status=trajectory.get("terminal_status"),
        )
        reward = shaped["reward"]
        if min_reward is not None and (reward is None or reward < min_reward):
            continue
        rows.extend(
            trajectory_to_tool_sft_rows(
                trajectory,
                reward=reward,
                terminal_status=trajectory.get("terminal_status"),
            )
        )
    return rows


def export_tool_sft_jsonl(
    trajectories: Iterable[dict],
    output_path: str | Path,
    reward_events_by_trajectory: dict[str, list[dict]] | None = None,
    *,
    min_reward: Optional[float] = None,
) -> int:
    rows = materialize_tool_sft_rows(
        trajectories, reward_events_by_trajectory, min_reward=min_reward
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)
