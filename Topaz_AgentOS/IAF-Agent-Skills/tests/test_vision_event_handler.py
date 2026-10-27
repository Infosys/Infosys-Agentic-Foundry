"""Tests for vision_event_handler — the queue→workstream materializer.

Run (no Redis, no live server needed — pure fakes):
    cd IAF_AgentOS_Harness_rlm
    PYTHONPATH="$PWD:$PWD/IAF-Agent-Skills" \
      <venv>/bin/python3 \
      -m pytest IAF-Agent-Skills/tests/test_vision_event_handler.py -v

Coverage is organized as a positive/negative matrix across THREE physical-AI
use cases (retail shelf, warehouse damage, PPE compliance) to prove the handler
is use-case agnostic and robust to bad input.
"""

from __future__ import annotations

import pytest

from iaf_agent_skills.vision_event_handler import (
    VisionOutcome,
    VisionEvent,
    VisionEventError,
    normalize_event,
    build_item,
    handle_vision_event,
)



class FakeStore:
    """Minimal stand-in for WorkstreamStore, mirroring its real contract:

    * append_item raises ValueError('... already present') on duplicate id
    * append_item raises FileNotFoundError for an unknown workstream
    """

    def __init__(self, known=("retail_shelf_exception", "warehouse_damage", "ppe_compliance")):
        self.known = set(known)
        self.items: dict[str, list[dict]] = {name: [] for name in known}

    def append_item(self, name: str, item: dict) -> dict:
        if name not in self.known:
            raise FileNotFoundError(f"workstream {name!r} not found")
        if not item.get("id") or not item.get("description"):
            raise ValueError("item must have id and description")
        if any(it["id"] == item["id"] for it in self.items[name]):
            raise ValueError(f"item id {item['id']!r} already present")
        stored = dict(item, status="pending")
        self.items[name].append(stored)
        return stored


def _deny_all(evt: VisionEvent):
    return (False, "vision_allowed not granted")


def _allow_all(evt: VisionEvent):
    return (True, "")



def retail_event(**over):
    base = dict(
        event_id="evt-shelf-001",
        workstream="retail_shelf_exception",
        image_ref="/shared/frames/retail_shelf_exception/evt-shelf-001.jpg",
        question="Is the shelf out of stock?",
        camera_id="aisle-A12",
        options=["stocked", "low", "empty"],
        observed_verdict="empty",
        observed_confidence=0.82,
        priority_metric=3.0,
    )
    base.update(over)
    return base


def warehouse_event(**over):
    base = dict(
        event_id="evt-dmg-77",
        workstream="warehouse_damage",
        image_ref="/shared/frames/warehouse_damage/evt-dmg-77.jpg",
        question="Is the package visibly damaged?",  # yes/no → noul mode
        camera_id="dock-3",
    )
    base.update(over)
    return base


def ppe_event(**over):
    base = dict(
        event_id="evt-ppe-9",
        workstream="ppe_compliance",
        image_ref="/shared/frames/ppe_compliance/evt-ppe-9.jpg",
        question="Is the worker wearing a hard hat?",
        camera_id="floor-cam-1",
        options="yes,no",  # delimited-string form
    )
    base.update(over)
    return base



def test_normalize_choice_mode_retail():
    evt = normalize_event(retail_event())
    assert evt.mode == "choice"
    assert evt.options == ("stocked", "low", "empty")
    assert evt.priority_metric == 3.0
    assert evt.observed_confidence == 0.82


def test_normalize_noul_mode_warehouse():
    evt = normalize_event(warehouse_event())
    assert evt.mode == "noul"          # no options → calibrated yes/no
    assert evt.options == ()
    assert evt.camera_id == "dock-3"


def test_normalize_options_from_delimited_string_ppe():
    evt = normalize_event(ppe_event())
    assert evt.options == ("yes", "no")
    assert evt.mode == "choice"


def test_normalize_defaults_camera_and_tenant():
    evt = normalize_event(warehouse_event())
    assert evt.camera_id == "dock-3"
    assert evt.tenant_id == "company"



def test_build_item_encodes_frame_and_question():
    evt = normalize_event(retail_event())
    item = build_item(evt)
    assert item["id"] == "evt-shelf-001"
    assert "frame=/shared/frames/retail_shelf_exception/evt-shelf-001.jpg" in item["description"]
    assert "Q: Is the shelf out of stock?" in item["description"]
    assert "options: stocked | low | empty" in item["description"]
    assert "observed: empty (0.82)" in item["description"]
    assert item["priority_metric"] == 3.0


def test_build_item_default_acceptance_when_absent():
    evt = normalize_event(warehouse_event())
    item = build_item(evt)
    assert len(item["acceptance_criteria"]) == 2
    assert "priority_metric" not in item  # not supplied → omitted


def test_build_item_respects_supplied_acceptance():
    evt = normalize_event(ppe_event(acceptance_criteria=["Hard hat clearly visible"]))
    item = build_item(evt)
    assert item["acceptance_criteria"] == ["Hard hat clearly visible"]



@pytest.mark.parametrize("factory,ws", [
    (retail_event, "retail_shelf_exception"),
    (warehouse_event, "warehouse_damage"),
    (ppe_event, "ppe_compliance"),
])
def test_materialize_each_use_case(factory, ws):
    store = FakeStore()
    res = handle_vision_event(factory(), append_item=store.append_item)
    assert res.outcome == VisionOutcome.MATERIALIZED
    assert res.ok is True
    assert res.workstream == ws
    assert len(store.items[ws]) == 1
    assert store.items[ws][0]["status"] == "pending"


def test_materialize_with_entitlement_allowed():
    store = FakeStore()
    res = handle_vision_event(retail_event(), append_item=store.append_item,
                              entitlement_check=_allow_all)
    assert res.outcome == VisionOutcome.MATERIALIZED



def test_duplicate_event_is_deduped_not_doubled():
    store = FakeStore()
    first = handle_vision_event(retail_event(), append_item=store.append_item)
    second = handle_vision_event(retail_event(), append_item=store.append_item)
    assert first.outcome == VisionOutcome.MATERIALIZED
    assert second.outcome == VisionOutcome.DEDUPED
    assert second.ok is True                       # dedup is a safe terminal state
    assert len(store.items["retail_shelf_exception"]) == 1  # only one row



@pytest.mark.parametrize("bad", [
    {},  # everything missing
    retail_event(event_id=""),
    retail_event(event_id="   "),
    retail_event(workstream=""),
    retail_event(image_ref=""),
    retail_event(question=""),
])
def test_normalize_rejects_missing_required(bad):
    with pytest.raises(VisionEventError):
        normalize_event(bad)


def test_normalize_rejects_bad_workstream_slug():
    with pytest.raises(VisionEventError):
        normalize_event(retail_event(workstream="bad name/../etc"))


def test_normalize_rejects_single_option():
    with pytest.raises(VisionEventError):
        normalize_event(retail_event(options=["onlyone"]))


def test_normalize_rejects_non_numeric_priority():
    with pytest.raises(VisionEventError):
        normalize_event(retail_event(priority_metric="high"))


def test_normalize_rejects_non_dict():
    with pytest.raises(VisionEventError):
        normalize_event("not-a-dict")  # type: ignore[arg-type]



def test_handler_rejects_malformed_to_dead_letter():
    store = FakeStore()
    res = handle_vision_event({"event_id": "x"}, append_item=store.append_item)
    assert res.outcome == VisionOutcome.REJECTED
    assert res.ok is False
    assert "missing required" in res.reason


def test_handler_rejects_unknown_workstream():
    store = FakeStore()
    res = handle_vision_event(retail_event(workstream="does_not_exist"),
                              append_item=store.append_item)
    assert res.outcome == VisionOutcome.REJECTED
    assert "not found" in res.reason.lower()


def test_handler_denies_when_entitlement_refuses():
    store = FakeStore()
    res = handle_vision_event(retail_event(), append_item=store.append_item,
                              entitlement_check=_deny_all)
    assert res.outcome == VisionOutcome.DENIED
    assert res.ok is False
    assert store.items["retail_shelf_exception"] == []  # nothing written


def test_handler_marks_transient_store_error_as_error():
    def boom(name, item):
        raise RuntimeError("YAML lock timeout")
    res = handle_vision_event(retail_event(), append_item=boom)
    assert res.outcome == VisionOutcome.ERROR       # → worker will retry
    assert res.ok is False
    assert "append failed" in res.reason


def test_handler_treats_broken_entitlement_checker_as_transient():
    store = FakeStore()
    def broken(evt):
        raise RuntimeError("policy provider down")
    res = handle_vision_event(retail_event(), append_item=store.append_item,
                              entitlement_check=broken)
    assert res.outcome == VisionOutcome.ERROR       # retry, don't silently deny
    assert store.items["retail_shelf_exception"] == []


def test_denied_event_can_still_be_retried_after_grant():
    # deny first (nothing written), then allow (materializes) — same event_id.
    store = FakeStore()
    denied = handle_vision_event(retail_event(), append_item=store.append_item,
                                 entitlement_check=_deny_all)
    assert denied.outcome == VisionOutcome.DENIED
    allowed = handle_vision_event(retail_event(), append_item=store.append_item,
                                  entitlement_check=_allow_all)
    assert allowed.outcome == VisionOutcome.MATERIALIZED
    assert len(store.items["retail_shelf_exception"]) == 1
