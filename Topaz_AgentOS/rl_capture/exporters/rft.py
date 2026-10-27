"""RFT trajectory exporter.

Emits one row per trajectory carrying the full state (task/model-calls/tools/
observations) plus a **shaped scalar reward** in ``[-1, 1]`` derived only from
judgement-channel signals (see :mod:`rl_capture.core.reward_shaping`). The naive
"sum every label" behaviour was replaced in Phase 3 to stop operational
`allow`/`ok` traces from polluting the RL reward.
"""

from __future__ import annotations

from typing import Iterable, Optional

from rl_capture.core.reward_shaping import shape_trajectory_reward


def materialize_rft_rows(
    trajectories: Iterable[dict],
    reward_events_by_trajectory: dict[str, list[dict]] | None = None,
    *,
    category_weights: Optional[dict[str, float]] = None,
    label_values: Optional[dict[str, float]] = None,
) -> list[dict]:
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
        rows.append({
            "trajectory_id": trajectory_id,
            "state": {
                "task": trajectory.get("task"),
                "session_id": trajectory.get("session_id"),
                "metadata": trajectory.get("metadata") or {},
            },
            "steps": trajectory.get("steps") or [],
            "model_calls": trajectory.get("model_calls") or [],
            "tool_calls": trajectory.get("tool_calls") or [],
            "observations": trajectory.get("observations") or [],
            "reward_events": rewards,
            "reward": shaped["reward"],
            "reward_components": shaped["components"],
            "reward_shaping": {
                "policy": shaped["policy"],
                "n_judgement": shaped["n_judgement"],
                "n_operational": shaped["n_operational"],
                "by_category": shaped["by_category"],
            },
            "terminal_status": trajectory.get("terminal_status"),
        })
    return rows
