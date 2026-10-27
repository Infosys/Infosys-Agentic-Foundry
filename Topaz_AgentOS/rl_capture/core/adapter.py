"""Framework-neutral adapter protocol for RL/eval capture."""

from __future__ import annotations

from typing import Protocol

from rl_capture.core.schema import (
    CandidateOutput,
    ModelCall,
    Observation,
    PreferenceSignal,
    RewardEvent,
    ToolCall,
    Trajectory,
)


class CaptureAdapter(Protocol):
    """Contract implemented by framework-specific adapters."""

    def on_trajectory_start(self, trajectory: Trajectory) -> None:
        ...

    def on_model_call(self, trajectory_id: str, model_call: ModelCall) -> None:
        ...

    def on_tool_call(self, trajectory_id: str, tool_call: ToolCall) -> None:
        ...

    def on_observation(self, trajectory_id: str, observation: Observation) -> None:
        ...

    def on_candidate_output(self, candidate: CandidateOutput) -> None:
        ...

    def on_reward(self, reward: RewardEvent) -> None:
        ...

    def on_preference(self, preference: PreferenceSignal) -> None:
        ...

    def on_trajectory_end(self, trajectory: Trajectory) -> None:
        ...
