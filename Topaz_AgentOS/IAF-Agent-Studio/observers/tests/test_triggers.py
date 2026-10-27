"""Unit tests for the pure deterministic TriggerEngine."""

from observers.models import (
    Approval,
    ObserverSpec,
    TriggerRule,
    TrustTier,
)
from observers.triggers import TriggerEngine


def _spec(*rules: TriggerRule) -> ObserverSpec:
    return ObserverSpec(
        name="ap-monitor",
        trust_tier=TrustTier.recommend,
        triggers=list(rules),
    )


THRESH = TriggerRule(
    name="oversized",
    field="amount",
    op=">=",
    value=50000,
    skill="ap_ops",
    task_template="Flag invoice {invoice_id} — amount {amount}",
    approval=Approval.human,
    cooldown_seconds=3600,
)


def test_threshold_fires_from_text():
    engine = TriggerEngine()
    event = {"type": "observation", "content": "invoice amount=60000 invoice_id=INV-1"}
    fired, _ = engine.match(_spec(THRESH), event, {}, now=100.0)
    assert len(fired) == 1
    act = fired[0]
    assert act.skill == "ap_ops"
    assert act.approval == Approval.human
    assert "60000" in act.task
    assert "INV-1" in act.task


def test_threshold_fires_from_structured_field():
    engine = TriggerEngine()
    event = {"type": "observation", "amount": 75000, "content": "x"}
    fired, _ = engine.match(_spec(THRESH), event, {}, now=1.0)
    assert len(fired) == 1


def test_below_threshold_does_not_fire():
    engine = TriggerEngine()
    event = {"type": "observation", "content": "invoice amount=40000"}
    fired, _ = engine.match(_spec(THRESH), event, {}, now=1.0)
    assert fired == []


def test_cooldown_suppresses_repeat_then_allows_after_window():
    engine = TriggerEngine()
    spec = _spec(THRESH)
    event = {"content": "amount=60000 invoice_id=INV-2"}

    fired1, state = engine.match(spec, event, {}, now=1000.0)
    assert len(fired1) == 1

    # Within cooldown (3600s) — suppressed.
    fired2, state = engine.match(spec, event, state, now=1000.0 + 100)
    assert fired2 == []

    # After cooldown — fires again.
    fired3, state = engine.match(spec, event, state, now=1000.0 + 3601)
    assert len(fired3) == 1


def test_pattern_rule_fires():
    engine = TriggerEngine()
    rule = TriggerRule(
        name="dispute",
        pattern="(?i)dispute|chargeback",
        skill="notify",
        task_template="dispute signal: {matched}",
        approval=Approval.auto,
    )
    event = {"content": "Vendor ACME raised a DISPUTE today"}
    fired, _ = engine.match(_spec(rule), event, {}, now=1.0)
    assert len(fired) == 1
    assert fired[0].skill == "notify"
    assert fired[0].approval == Approval.auto


def test_malformed_rule_ignored():
    engine = TriggerEngine()
    rule = TriggerRule(name="bad", skill="ap_ops")  # no pattern, no threshold
    fired, _ = engine.match(_spec(rule), {"content": "anything"}, {}, now=1.0)
    assert fired == []
