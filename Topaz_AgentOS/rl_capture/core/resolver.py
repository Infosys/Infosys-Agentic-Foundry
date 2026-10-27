"""Resolve TargetRef records into exportable text and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rl_capture.core.schema import TargetRef, TargetType
from rl_capture.store.sqlite_store import RLStore


@dataclass
class ResolvedTarget:
    target: TargetRef
    text: str
    messages: list[dict]
    metadata: dict[str, Any]


class TargetResolver:
    def __init__(self, store: RLStore):
        self.store = store

    def resolve(self, target: TargetRef | dict) -> ResolvedTarget | None:
        ref = self._target_from_dict(target) if isinstance(target, dict) else target
        if ref.target_type == TargetType.TRAJECTORY:
            return self._resolve_trajectory(ref)
        if ref.target_type == TargetType.MODEL_CALL:
            return self._resolve_model_call(ref)
        if ref.target_type == TargetType.TOOL_CALL:
            return self._resolve_tool_call(ref)
        if ref.target_type == TargetType.OBSERVATION:
            return self._resolve_observation(ref)
        return self._resolve_candidate_or_step(ref)

    def prompt_for_context(self, target: TargetRef | dict) -> str:
        ref = self._target_from_dict(target) if isinstance(target, dict) else target
        trajectory = self.store.get_trajectory(ref.trajectory_id) or {}
        model_calls = trajectory.get("model_calls") or []
        if model_calls:
            messages = model_calls[-1].get("input_messages") or []
            return self._messages_text(messages)
        return str(trajectory.get("task") or "")

    def _resolve_trajectory(self, ref: TargetRef) -> ResolvedTarget | None:
        trajectory = self.store.get_trajectory(ref.trajectory_id)
        if not trajectory:
            return None
        model_calls = trajectory.get("model_calls") or []
        messages: list[dict] = []
        text = str(trajectory.get("task") or "")
        if model_calls:
            output_messages = model_calls[-1].get("output_messages") or []
            messages = output_messages
            text = self._messages_text(output_messages) or text
        return ResolvedTarget(ref, text, messages, {"kind": "trajectory", "trajectory_id": ref.trajectory_id})

    def _resolve_model_call(self, ref: TargetRef) -> ResolvedTarget | None:
        if not ref.target_id:
            return None
        model_call = self.store.get_model_call(ref.target_id)
        if not model_call:
            return None
        messages = model_call.get("output_messages") or []
        return ResolvedTarget(ref, self._messages_text(messages), messages, {"kind": "model_call", "model_call_id": ref.target_id})

    def _resolve_tool_call(self, ref: TargetRef) -> ResolvedTarget | None:
        if not ref.target_id:
            return None
        tool_call = self.store.get_tool_call(ref.target_id)
        if not tool_call:
            return None
        return ResolvedTarget(ref, str(tool_call.get("output") or ""), [], {"kind": "tool_call", "tool_call_id": ref.target_id})

    def _resolve_observation(self, ref: TargetRef) -> ResolvedTarget | None:
        if not ref.target_id:
            return None
        observation = self.store.get_observation(ref.target_id)
        if not observation:
            return None
        return ResolvedTarget(ref, str(observation.get("payload") or ""), [], {"kind": "observation", "observation_id": ref.target_id})

    def _resolve_candidate_or_step(self, ref: TargetRef) -> ResolvedTarget | None:
        if ref.target_id:
            candidate = self.store.get_candidate_output(ref.target_id)
            if candidate:
                messages = candidate.get("messages") or []
                return ResolvedTarget(ref, self._messages_text(messages), messages, {"kind": "candidate", "candidate_id": ref.target_id})
        return None

    @staticmethod
    def _messages_text(messages: list[dict]) -> str:
        parts = []
        for message in messages:
            content = message.get("content")
            if content:
                parts.append(str(content))
        return "\n".join(parts)

    @staticmethod
    def _target_from_dict(value: dict) -> TargetRef:
        return TargetRef(
            trajectory_id=str(value.get("trajectory_id") or ""),
            target_type=TargetType(str(value.get("target_type") or TargetType.TRAJECTORY.value)),
            target_id=value.get("target_id"),
            turn=value.get("turn"),
        )
