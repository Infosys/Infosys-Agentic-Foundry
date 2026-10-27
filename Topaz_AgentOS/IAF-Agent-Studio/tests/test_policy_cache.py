"""policies.yaml is parsed once and re-read only when it changes.

The YAML entitlement provider used to parse policies.yaml on EVERY check (~37 ms each).
/api/skills makes one check per skill (183), so each call froze the event loop for
~2.5 s. These tests prove the parse is cached AND that an edit — e.g. a new deny rule —
takes effect on the very next check, so caching never serves stale permissions.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from security import yaml_provider  # noqa: E402
from security.models import Principal, Resource  # noqa: E402

ALLOW = """
policies:
  - id: users-can-use-general
    effect: allow
    roles: [user]
    actions: [use]
    resources: ["skill:general"]
"""

DENY_ADDED = ALLOW + """
  - id: deny-general
    effect: deny
    roles: [user]
    actions: [use]
    resources: ["skill:general"]
"""


@pytest.fixture
def provider(tmp_path, monkeypatch):
    policy = tmp_path / "policies.yaml"
    policy.write_text(ALLOW)
    p = yaml_provider.YamlEntitlementProvider()
    monkeypatch.setattr(p, "_policy_file", lambda tenant_id: policy)
    getattr(yaml_provider, "_POLICY_CACHE", {}).clear()
    return p, policy


def _user():
    return Principal(user_id="u1", email="u1@x", tenant_id="t", roles=("user",),
                     allowed_tenants=("t",))


def _allowed(p) -> bool:
    return p.can(_user(), "use", Resource("skill", "general", tenant_id="t")).allowed


def test_repeated_checks_parse_the_file_once(provider, monkeypatch):
    p, _policy = provider
    calls = {"n": 0}
    real = yaml.safe_load

    def counting(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(yaml_provider.yaml, "safe_load", counting)
    for _ in range(200):
        assert _allowed(p)
    assert calls["n"] == 1, f"policies.yaml parsed {calls['n']} times for 200 checks"


def test_an_edit_takes_effect_on_the_next_check(provider):
    p, policy = provider
    assert _allowed(p)
    policy.write_text(DENY_ADDED)
    # Guarantee a different mtime even on coarse-timestamp filesystems.
    st = policy.stat()
    os.utime(policy, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert not _allowed(p), "a newly added deny rule was ignored — the cache served stale policy"


def test_deleting_the_file_is_noticed(provider):
    p, policy = provider
    assert _allowed(p)
    policy.unlink()
    assert p._load_policy("t") == {}


def test_two_hundred_checks_are_fast(provider):
    p, _ = provider
    t = time.perf_counter()
    for _ in range(200):
        _allowed(p)
    assert time.perf_counter() - t < 0.5
