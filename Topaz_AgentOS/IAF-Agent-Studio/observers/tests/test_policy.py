"""Unit tests for the pure trust-tier policy engine."""

from observers import policy
from observers.models import Approval, TrustTier


def test_observe_only_allows_notify_auto():
    d = policy.evaluate(TrustTier.observe_only, "notify", Approval.auto)
    assert d.allow and d.approval == Approval.auto


def test_observe_only_denies_other_skills():
    d = policy.evaluate(TrustTier.observe_only, "ap_ops", Approval.human)
    assert d.denied


def test_recommend_forces_human():
    d = policy.evaluate(TrustTier.recommend, "ap_ops", Approval.auto)
    assert d.allow and d.approval == Approval.human


def test_auto_act_low_risk_keeps_requested():
    d = policy.evaluate(TrustTier.auto_act, "notify", Approval.auto)
    assert d.allow and d.approval == Approval.auto


def test_auto_act_non_low_risk_forced_human():
    d = policy.evaluate(TrustTier.auto_act, "ap_ops", Approval.auto)
    assert d.allow and d.approval == Approval.human


def test_supervised_forces_human():
    d = policy.evaluate(TrustTier.supervised, "ap_ops", Approval.auto)
    assert d.allow and d.approval == Approval.human


def test_allowlist_denies_unlisted_skill():
    d = policy.evaluate(
        TrustTier.recommend, "delete_all", Approval.human, allowed_skills=["ap_ops"]
    )
    assert d.denied


def test_allowlist_still_permits_notify():
    d = policy.evaluate(
        TrustTier.recommend, "notify", Approval.auto, allowed_skills=["ap_ops"]
    )
    assert d.allow
