"""Tests for the taxonomy-driven router shortlist and the wrapper readiness proxy.

Background — the bug these guard against:
  `agent._taxonomy_index` is a TaxonomyRoutingCapability *wrapper*. chat.py gated the
  pre-router taxonomy lookup on `getattr(idx, '_ready', None) and idx._ready.is_set()`,
  but the wrapper never defined `_ready`, so getattr returned None and the branch was
  dead in BOTH the REST and WebSocket paths. The router therefore chose among all ~183
  skill descriptions with no semantic signal, and look-alike finance entries won on
  phrasing alone.

Two guarantees are asserted here:
  1. the wrapper exposes the inner index's readiness Event (so the probe cannot
     silently read as "never ready" again), and
  2. the shortlist narrows the catalogue on a confident signal while preserving recall
     inside the chosen domain, and falls back to the full catalogue in every weak,
     unknown, disabled or too-aggressive case.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "IAF-Agent-Skills"))

from iaf_agent_skills.taxonomy_routing_capability import TaxonomyRoutingCapability  # noqa: E402

SKILLS_PATH = ROOT / "enterprise_root" / "tenants" / "company" / "skills"

# The real signal observed for "what are the pending invoices … requires attention?"
REAL_HINTS = [
    {"skill": "fa_ap", "score": 1.075},
    {"skill": "fa_ar", "score": 0.893},
    {"skill": "fa_gl", "score": 0.892},
    {"skill": "ccdops", "score": 0.844},
]


@pytest.fixture(scope="module")
def router():
    if not (SKILLS_PATH / "_index.yaml").exists():
        pytest.skip("tenant skill catalogue not present")
    from iaf_agent_skills.router import SkillRouter
    with patch.object(SkillRouter, "_create_llm", lambda self: None):
        return SkillRouter(str(SKILLS_PATH))


def test_wrapper_exposes_inner_readiness_event():
    """The probe chat.py performs must see the inner Event, not None."""
    class _Inner:
        def __init__(self):
            self._ready = threading.Event()

    inner = _Inner()
    cap = TaxonomyRoutingCapability(inner)

    assert getattr(cap, "_ready", None) is inner._ready
    assert cap.is_ready() is False
    inner._ready.set()
    assert cap.is_ready() is True


def test_readiness_is_safe_when_there_is_no_index():
    cap = TaxonomyRoutingCapability(None)
    assert getattr(cap, "_ready", None) is None
    assert cap.is_ready() is False


def test_confident_signal_narrows_to_the_hinted_domain(router):
    full = router._get_filtered_skills()
    out, note = router._shortlist_by_taxonomy(full, REAL_HINTS)

    assert len(out) < len(full), "a confident signal should narrow the catalogue"
    assert "finance" in note
    # Only the domain above threshold survives; ccdops (0.844 < 0.90) does not.
    assert "ccdops" not in out


def test_shortlist_preserves_recall_inside_the_domain(router):
    """Narrowing must not drop the skill that should win.

    The hints name domain anchors (fa_ap), not executable skills, so both rival AP
    skills have to survive — otherwise the shortlist would merely trade one wrong
    answer for another.
    """
    full = router._get_filtered_skills()
    out, _ = router._shortlist_by_taxonomy(full, REAL_HINTS)

    for survivor in ("rlm_ap_report", "invoice_processing_ap", "fa_ap"):
        assert survivor in out, f"{survivor} must remain selectable"
    assert router.default_skill in out, "the default skill is the 'none of these' escape hatch"


@pytest.mark.parametrize(
    "label, hints, env",
    [
        ("no hints at all",          None,                                       {}),
        ("empty hints",              [],                                         {}),
        ("all below threshold",      [{"skill": "fa_ar", "score": 0.60}],        {}),
        ("hint names unknown skill", [{"skill": "nope", "score": 2.0}],          {}),
        ("explicitly disabled",      REAL_HINTS,  {"ROUTER_SHORTLIST_ENABLED": "false"}),
        ("malformed env value",      REAL_HINTS,  {"ROUTER_SHORTLIST_MIN_SCORE": "abc"}),
    ],
)
def test_falls_back_to_full_catalogue(router, label, hints, env):
    full = router._get_filtered_skills()
    with patch.dict(os.environ, env, clear=False):
        out, note = router._shortlist_by_taxonomy(full, hints)
    assert len(out) == len(full), f"{label}: must not narrow"
    assert note == ""


def test_too_aggressive_a_shortlist_is_refused(router):
    """A tiny shortlist means a bad signal — keep the full catalogue instead.

    This is the guard that let the Kubernetes query route correctly: its domain had
    only 2 skills, below the floor, so narrowing was skipped.
    """
    full = router._get_filtered_skills()
    with patch.dict(os.environ, {"ROUTER_SHORTLIST_MIN_SKILLS": "999"}, clear=False):
        out, note = router._shortlist_by_taxonomy(full, REAL_HINTS)
    assert len(out) == len(full)
    assert note == ""


def test_prompt_carries_the_signal_and_stays_truthful(router):
    """The narrowed prompt must announce itself and must not list dropped skills."""
    wide = router._format_skills_for_prompt(None)
    narrow = router._format_skills_for_prompt(REAL_HINTS)

    assert len(narrow) < len(wide)
    assert "narrowed to" in narrow
    assert "- ccdops:" in wide and "- ccdops:" not in narrow
    assert "- invoice_processing_ap:" in narrow
