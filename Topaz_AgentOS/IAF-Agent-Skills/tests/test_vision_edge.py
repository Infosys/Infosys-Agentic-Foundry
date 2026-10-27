"""Tests for vision_edge — the config-driven producer.

Verifies registry loading, the trigger rule (gate + fire_on), deterministic frame
paths, event construction, and submission — all with a fake submit (no Redis).

Run:
    cd IAF_AgentOS_Harness_rlm
    PYTHONPATH="$PWD:$PWD/IAF-Agent-Skills" \
      <venv>/bin/python3 \
      -m pytest IAF-Agent-Skills/tests/test_vision_edge.py -v
"""

from __future__ import annotations

import pytest

from iaf_agent_skills.vision_edge import (
    CameraSpec,
    QueueSubmitter,
    VisionEdge,
    build_event,
    frame_path,
    load_camera_registry,
    should_fire,
)


# A small multi-use-case registry, as it would appear in camera_registry.yaml.
REGISTRY_ROWS = {
    "aisle-A12": {
        "workstream": "retail_shelf_exception",
        "question": "Is the shelf out of stock?",
        "options": ["stocked", "low", "empty"],
        "gate": 0.7,
        "fire_on": ["low", "empty"],
    },
    "dock-3": {
        "workstream": "warehouse_damage",
        "question": "Is the package visibly damaged?",  # yes/no
        "gate": 0.6,
    },
    "floor-cam-1": {
        "workstream": "ppe_compliance",
        "question": "Is the worker wearing a hard hat?",
        "options": "yes|no",       # delimited-string form
        "gate": 0.5,
        "fire_on": "no",           # only fire on non-compliance
    },
}


class FakeSubmitter:
    def __init__(self):
        self.tasks = []

    def __call__(self, task):
        self.tasks.append(task)
        return f"task-{len(self.tasks)}"


def _registry():
    return load_camera_registry(REGISTRY_ROWS)



def test_registry_loads_all_cameras():
    reg = _registry()
    assert set(reg) == {"aisle-A12", "dock-3", "floor-cam-1"}
    assert isinstance(reg["aisle-A12"], CameraSpec)


def test_registry_parses_options_forms():
    reg = _registry()
    assert reg["aisle-A12"].options == ("stocked", "low", "empty")
    assert reg["floor-cam-1"].options == ("yes", "no")   # from "yes|no"
    assert reg["dock-3"].options == ()                    # noul


def test_registry_accepts_list_form():
    rows = [dict(camera_id="c1", workstream="ws_a", question="Q?")]
    reg = load_camera_registry(rows)
    assert reg["c1"].workstream == "ws_a"



def test_registry_rejects_missing_camera_id():
    with pytest.raises(ValueError):
        load_camera_registry([{"workstream": "w", "question": "Q?"}])


def test_registry_rejects_missing_workstream():
    with pytest.raises(ValueError):
        load_camera_registry({"c1": {"question": "Q?"}})


def test_registry_rejects_missing_question():
    with pytest.raises(ValueError):
        load_camera_registry({"c1": {"workstream": "w"}})



def test_frame_path_is_deterministic():
    spec = _registry()["aisle-A12"]
    assert frame_path(spec, "evt-9") == "shared/frames/retail_shelf_exception/evt-9.jpg"



def test_should_fire_above_gate_and_in_fire_on():
    spec = _registry()["aisle-A12"]
    assert should_fire(spec, "empty", 0.9) is True


def test_should_not_fire_below_gate():
    spec = _registry()["aisle-A12"]
    assert should_fire(spec, "empty", 0.5) is False


def test_should_not_fire_verdict_not_in_fire_on():
    spec = _registry()["aisle-A12"]
    assert should_fire(spec, "stocked", 0.95) is False   # stocked not in fire_on


def test_should_not_fire_missing_confidence():
    spec = _registry()["dock-3"]
    assert should_fire(spec, "damaged", None) is False


def test_should_fire_no_fire_on_list_any_verdict():
    spec = _registry()["dock-3"]         # no fire_on → any verdict above gate
    assert should_fire(spec, "damaged", 0.7) is True



def test_build_event_uses_deterministic_frame_when_absent():
    spec = _registry()["aisle-A12"]
    ev = build_event(spec, event_id="evt-5", observed_verdict="empty", observed_confidence=0.8)
    assert ev["image_ref"] == "shared/frames/retail_shelf_exception/evt-5.jpg"
    assert ev["options"] == ["stocked", "low", "empty"]
    assert ev["observed_verdict"] == "empty"
    assert ev["workstream"] == "retail_shelf_exception"


def test_build_event_generates_event_id_when_absent():
    spec = _registry()["dock-3"]
    ev = build_event(spec, observed_confidence=0.7)
    assert ev["event_id"].startswith("dock-3-")
    assert "options" not in ev   # noul mode



def test_emit_fires_and_submits_when_gate_met():
    sub = FakeSubmitter()
    edge = VisionEdge(_registry(), sub)
    res = edge.emit("aisle-A12", observed_verdict="empty", observed_confidence=0.85)
    assert res.fired is True
    assert res.task_id == "task-1"
    assert len(sub.tasks) == 1
    assert sub.tasks[0].task_type == "vision_event"
    assert sub.tasks[0].payload["workstream"] == "retail_shelf_exception"


def test_emit_force_bypasses_gate():
    sub = FakeSubmitter()
    edge = VisionEdge(_registry(), sub)
    res = edge.emit("dock-3", observed_confidence=0.1, force=True)
    assert res.fired is True
    assert len(sub.tasks) == 1


@pytest.mark.parametrize("camera,ws", [
    ("aisle-A12", "retail_shelf_exception"),
    ("dock-3", "warehouse_damage"),
    ("floor-cam-1", "ppe_compliance"),
])
def test_emit_routes_each_use_case(camera, ws):
    sub = FakeSubmitter()
    edge = VisionEdge(_registry(), sub)
    verdict = {"aisle-A12": "empty", "dock-3": "damaged", "floor-cam-1": "no"}[camera]
    res = edge.emit(camera, observed_verdict=verdict, observed_confidence=0.99)
    assert res.fired is True
    assert sub.tasks[0].payload["workstream"] == ws



def test_emit_unknown_camera_does_not_submit():
    sub = FakeSubmitter()
    edge = VisionEdge(_registry(), sub)
    res = edge.emit("ghost-cam", observed_confidence=0.99)
    assert res.fired is False
    assert "unknown camera" in res.reason
    assert sub.tasks == []


def test_emit_below_gate_does_not_submit():
    sub = FakeSubmitter()
    edge = VisionEdge(_registry(), sub)
    res = edge.emit("aisle-A12", observed_verdict="empty", observed_confidence=0.3)
    assert res.fired is False
    assert sub.tasks == []


def test_emit_wrong_verdict_does_not_submit():
    sub = FakeSubmitter()
    edge = VisionEdge(_registry(), sub)
    res = edge.emit("floor-cam-1", observed_verdict="yes", observed_confidence=0.99)
    assert res.fired is False   # compliant → not in fire_on ("no")
    assert sub.tasks == []



class FakeAsyncQueue:
    """Mimics TaskQueue.submit (async) without Redis."""
    def __init__(self):
        self.submitted = []
    async def submit(self, task):
        self.submitted.append(task)
        return f"qid-{len(self.submitted)}"


def test_queue_submitter_submits_via_background_loop():
    q = FakeAsyncQueue()
    sub = QueueSubmitter(q)
    try:
        edge = VisionEdge(_registry(), sub)
        res = edge.emit("dock-3", observed_verdict="damaged", observed_confidence=0.9)
        assert res.fired is True
        assert res.task_id == "qid-1"
        assert len(q.submitted) == 1
        assert q.submitted[0].task_type == "vision_event"
        assert q.submitted[0].lane == "vision"
    finally:
        sub.close()


def test_queue_submitter_handles_multiple_submits():
    q = FakeAsyncQueue()
    sub = QueueSubmitter(q)
    try:
        edge = VisionEdge(_registry(), sub)
        edge.emit("dock-3", observed_verdict="damaged", observed_confidence=0.9)
        edge.emit("aisle-A12", observed_verdict="empty", observed_confidence=0.9)
        assert len(q.submitted) == 2
    finally:
        sub.close()
