"""Best-effort writers for RL/eval capture events."""

from __future__ import annotations

import atexit
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from rl_capture.core.schema import (
    CandidateOutput,
    DatasetExport,
    EvaluatorResult,
    ModelCall,
    Observation,
    PreferenceSignal,
    RewardEvent,
    ShadowRun,
    ToolCall,
    Trajectory,
)
from rl_capture.store.sqlite_store import RLStore

logger = logging.getLogger(__name__)


class NoOpCaptureWriter:
    def record_trajectory(self, trajectory: Trajectory) -> None:
        return

    def record_model_call(self, trajectory_id: str, model_call: ModelCall) -> None:
        return

    def record_tool_call(self, trajectory_id: str, tool_call: ToolCall) -> None:
        return

    def record_observation(self, trajectory_id: str, observation: Observation) -> None:
        return

    def record_reward_event(self, reward: RewardEvent) -> None:
        return

    def record_preference_signal(self, preference: PreferenceSignal) -> None:
        return

    def record_candidate_output(self, candidate: CandidateOutput) -> None:
        return

    def record_export(self, dataset_export: DatasetExport) -> None:
        return

    def record_evaluator_result(self, evaluator_result: EvaluatorResult) -> None:
        return

    def record_shadow_run(self, shadow_run: ShadowRun) -> None:
        return

    def close(self) -> None:
        return


@dataclass
class SyncCaptureWriter:
    store: RLStore

    def record_trajectory(self, trajectory: Trajectory) -> None:
        self._safe(lambda: self.store.record_trajectory(trajectory))

    def record_model_call(self, trajectory_id: str, model_call: ModelCall) -> None:
        self._safe(lambda: self.store.record_model_call(trajectory_id, model_call))

    def record_tool_call(self, trajectory_id: str, tool_call: ToolCall) -> None:
        self._safe(lambda: self.store.record_tool_call(trajectory_id, tool_call))

    def record_observation(self, trajectory_id: str, observation: Observation) -> None:
        self._safe(lambda: self.store.record_observation(trajectory_id, observation))

    def record_reward_event(self, reward: RewardEvent) -> None:
        self._safe(lambda: self.store.record_reward_event(reward))

    def record_preference_signal(self, preference: PreferenceSignal) -> None:
        self._safe(lambda: self.store.record_preference_signal(preference))

    def record_candidate_output(self, candidate: CandidateOutput) -> None:
        self._safe(lambda: self.store.record_candidate_output(candidate))

    def record_export(self, dataset_export: DatasetExport) -> None:
        self._safe(lambda: self.store.record_export(dataset_export))

    def record_evaluator_result(self, evaluator_result: EvaluatorResult) -> None:
        self._safe(lambda: self.store.record_evaluator_result(evaluator_result))

    def record_shadow_run(self, shadow_run: ShadowRun) -> None:
        self._safe(lambda: self.store.record_shadow_run(shadow_run))

    def close(self) -> None:
        return

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:
            logger.warning("RL capture write failed (non-fatal): %s", exc)


class BufferedCaptureWriter(SyncCaptureWriter):
    def __init__(self, store: RLStore, *, maxsize: int = 1000, shutdown_timeout: float = 10.0):
        super().__init__(store)
        self._shutdown_timeout = shutdown_timeout
        self._closed = False
        self._queue: queue.Queue[Callable[[], None] | None] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._run, name="rl-capture-writer", daemon=True)
        self._thread.start()
        # Daemon worker: flush on normal shutdown so queued events are not lost.
        atexit.register(self.close)

    def record_trajectory(self, trajectory: Trajectory) -> None:
        self._enqueue(lambda: self.store.record_trajectory(trajectory))

    def record_model_call(self, trajectory_id: str, model_call: ModelCall) -> None:
        self._enqueue(lambda: self.store.record_model_call(trajectory_id, model_call))

    def record_tool_call(self, trajectory_id: str, tool_call: ToolCall) -> None:
        self._enqueue(lambda: self.store.record_tool_call(trajectory_id, tool_call))

    def record_observation(self, trajectory_id: str, observation: Observation) -> None:
        self._enqueue(lambda: self.store.record_observation(trajectory_id, observation))

    def record_reward_event(self, reward: RewardEvent) -> None:
        self._enqueue(lambda: self.store.record_reward_event(reward))

    def record_preference_signal(self, preference: PreferenceSignal) -> None:
        self._enqueue(lambda: self.store.record_preference_signal(preference))

    def record_candidate_output(self, candidate: CandidateOutput) -> None:
        self._enqueue(lambda: self.store.record_candidate_output(candidate))

    def record_export(self, dataset_export: DatasetExport) -> None:
        self._enqueue(lambda: self.store.record_export(dataset_export))

    def record_evaluator_result(self, evaluator_result: EvaluatorResult) -> None:
        self._enqueue(lambda: self.store.record_evaluator_result(evaluator_result))

    def record_shadow_run(self, shadow_run: ShadowRun) -> None:
        self._enqueue(lambda: self.store.record_shadow_run(shadow_run))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._enqueue(None)
        self._thread.join(timeout=self._shutdown_timeout)

    def _enqueue(self, fn: Callable[[], None] | None) -> None:
        try:
            self._queue.put_nowait(fn)
        except queue.Full:
            logger.warning("RL capture writer queue full; dropping event")

    def _run(self) -> None:
        while True:
            fn = self._queue.get()
            if fn is None:
                return
            self._safe(fn)
