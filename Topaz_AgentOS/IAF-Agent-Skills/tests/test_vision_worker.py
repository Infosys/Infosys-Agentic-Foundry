"""Tests for vision_worker — the durable-queue handler for vision events.

Uses real TaskDefinition/TaskContext (pure dataclasses — no Redis) plus a fake
store, so the queue→handler→TaskResult mapping is verified in isolation.

Run:
    cd IAF_AgentOS_Harness_rlm
    PYTHONPATH="$PWD:$PWD/IAF-Agent-Skills" \
      <venv>/bin/python3 \
      -m pytest IAF-Agent-Skills/tests/test_vision_worker.py -v
"""

from __future__ import annotations

import asyncio

import pytest

from iaf_agent_skills.vision_worker import (
    VISION_TASK_TYPE,
    VisionEventHandler,
    VisionTransientError,
    make_vision_task,
    make_platform_entitlement_check,
)
from iaf_agent_skills.vision_event_handler import normalize_event
from iaf_agent_skills.task_system.models import TaskStatus, TaskPriority


class FakeStore:
    """Mirrors WorkstreamStore.append_item contract (dup → ValueError)."""

    def __init__(self, known=("retail_shelf_exception", "warehouse_damage")):
        self.items = {n: [] for n in known}
        self.known = set(known)

    def append_item(self, name, item):
        if name not in self.known:
            raise FileNotFoundError(f"workstream {name!r} not found")
        if any(it["id"] == item["id"] for it in self.items[name]):
            raise ValueError(f"item id {item['id']!r} already present")
        stored = dict(item, status="pending")
        self.items[name].append(stored)
        return stored


def _event(**over):
    base = dict(
        event_id="evt-1",
        workstream="retail_shelf_exception",
        image_ref="/shared/frames/retail_shelf_exception/evt-1.jpg",
        question="Is the shelf empty?",
        camera_id="A12",
        options=["stocked", "empty"],
    )
    base.update(over)
    return base


def _run(coro):
    return asyncio.run(coro)



def test_handler_requires_a_wiring():
    with pytest.raises(ValueError):
        VisionEventHandler()  # neither append_item nor resolver


def test_task_type_is_vision_event():
    h = VisionEventHandler(append_item=FakeStore().append_item)
    assert h.task_types == [VISION_TASK_TYPE]



def test_make_vision_task_shape():
    task = make_vision_task(_event(), tenant_id="acme")
    assert task.task_type == VISION_TASK_TYPE
    assert task.lane == "vision"
    assert task.priority == TaskPriority.HIGH
    assert task.context.tenant_id == "acme"
    assert task.payload["event_id"] == "evt-1"



def test_execute_materialized_is_completed():
    store = FakeStore()
    h = VisionEventHandler(append_item=store.append_item)
    task = make_vision_task(_event())
    res = _run(h.execute(task))
    assert res.status == TaskStatus.COMPLETED
    assert res.output["outcome"] == "materialized"
    assert res.output["materialized"] is True
    assert len(store.items["retail_shelf_exception"]) == 1


def test_execute_duplicate_is_completed_deduped():
    store = FakeStore()
    h = VisionEventHandler(append_item=store.append_item)
    _run(h.execute(make_vision_task(_event())))
    res = _run(h.execute(make_vision_task(_event())))  # same event_id
    assert res.status == TaskStatus.COMPLETED
    assert res.output["outcome"] == "deduped"
    assert res.output["materialized"] is True
    assert len(store.items["retail_shelf_exception"]) == 1


def test_execute_uses_task_context_tenant_default():
    store = FakeStore()
    h = VisionEventHandler(append_item=store.append_item)
    ev = _event()
    ev.pop("tenant_id", None)
    task = make_vision_task(ev, tenant_id="company")
    res = _run(h.execute(task))
    assert res.status == TaskStatus.COMPLETED



def test_execute_rejected_is_completed_but_not_materialized():
    store = FakeStore()
    h = VisionEventHandler(append_item=store.append_item)
    task = make_vision_task(_event(event_id=""))  # invalid → REJECTED
    res = _run(h.execute(task))
    assert res.status == TaskStatus.COMPLETED       # acked, no pointless retries
    assert res.output["materialized"] is False
    assert res.output["outcome"] == "rejected"


def test_execute_unknown_workstream_is_rejected():
    store = FakeStore()
    h = VisionEventHandler(append_item=store.append_item)
    task = make_vision_task(_event(workstream="nope"))
    res = _run(h.execute(task))
    assert res.status == TaskStatus.COMPLETED
    assert res.output["materialized"] is False
    assert "not found" in res.output["reason"].lower()


def test_execute_denied_is_completed_not_materialized():
    store = FakeStore()
    h = VisionEventHandler(append_item=store.append_item,
                           entitlement_check=lambda evt: (False, "vision_allowed missing"))
    res = _run(h.execute(make_vision_task(_event())))
    assert res.status == TaskStatus.COMPLETED
    assert res.output["outcome"] == "denied"
    assert store.items["retail_shelf_exception"] == []



def test_execute_transient_store_error_raises():
    def boom(name, item):
        raise RuntimeError("YAML lock timeout")
    h = VisionEventHandler(append_item=boom)
    with pytest.raises(VisionTransientError):
        _run(h.execute(make_vision_task(_event())))


def test_execute_broken_entitlement_raises_transient():
    store = FakeStore()
    def broken(evt):
        raise RuntimeError("policy provider down")
    h = VisionEventHandler(append_item=store.append_item, entitlement_check=broken)
    with pytest.raises(VisionTransientError):
        _run(h.execute(make_vision_task(_event())))
    assert store.items["retail_shelf_exception"] == []



def test_entitlement_factory_allows_when_enforce_passes():
    seen = {}
    def fake_enforce(principal, action, rtype, rid):
        seen["args"] = (principal, action, rtype, rid)  # no raise == allowed
    check = make_platform_entitlement_check("company", _enforce=fake_enforce, _principal="P")
    allowed, reason = check(normalize_event(_event()))
    assert allowed is True and reason == ""
    assert seen["args"] == ("P", "run", "vision", "retail_shelf_exception")


def test_entitlement_factory_denies_when_enforce_raises():
    class Denied(Exception):
        detail = "403: vision_allowed not granted"
    def fake_enforce(principal, action, rtype, rid):
        raise Denied()
    check = make_platform_entitlement_check("company", _enforce=fake_enforce, _principal="P")
    allowed, reason = check(normalize_event(_event()))
    assert allowed is False
    assert "vision_allowed" in reason


def test_entitlement_factory_wired_into_handler_denies():
    store = FakeStore()
    def fake_enforce(principal, action, rtype, rid):
        raise Exception("denied")
    check = make_platform_entitlement_check("company", _enforce=fake_enforce, _principal="P")
    h = VisionEventHandler(append_item=store.append_item, entitlement_check=check)
    res = _run(h.execute(make_vision_task(_event())))
    assert res.output["outcome"] == "denied"
    assert store.items["retail_shelf_exception"] == []
