"""Per-item context access: ALLOW BY DEFAULT, RESTRICT BY EXCEPTION.

Companion to test_context_manager_tenant_isolation.py. That file pins the
*tenant* boundary ("whose data?"); this one pins access *within* a tenant
("which documents?").

Model under test (enterprise_root/tenants/company/security/policies.yaml):
  context-default-allow           allow  context:*                              roles user/manager/auditor
  context-restricted-folder-deny  deny   context:/shared/contexts/restricted/*  roles user/auditor

The engine collects every matching policy and lets any DENY win regardless of
order, so dropping a document into the restricted folder protects it with no
code change and no per-file tagging.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills", ROOT / "IAF-Agent-Studio"):
    sys.path.insert(0, str(p))

from fastapi import HTTPException  # noqa: E402

import security.dependencies as deps  # noqa: E402
from routers import context_manager as cm  # noqa: E402
from security.models import Principal, Resource  # noqa: E402
from security.yaml_provider import YamlEntitlementProvider  # noqa: E402

OPEN_PATH = "/shared/contexts/open_sample_note.md"
RESTRICTED_PATH = "/shared/contexts/restricted/hr_compensation_policy.md"


def _principal(role: str) -> Principal:
    return Principal(
        user_id=f"{role}-1", email=f"{role}@example.com", tenant_id="company",
        roles=(role,), groups=(), allowed_tenants=("company",),
    )


def _request(role: str = "user"):
    class _Req:
        def __init__(self):
            self.state = SimpleNamespace(context_principal=_principal(role))
            self.query_params = {}
            self.headers = {}
    return _Req()


class PolicyEngineContextRulesTest(unittest.TestCase):
    """Policy-level truth table — covers `manager`, which the user API cannot create."""

    def setUp(self):
        self.provider = YamlEntitlementProvider()

    def _can(self, role: str, path: str, action: str = "read") -> bool:
        return self.provider.can(
            _principal(role), action, Resource("context", path, tenant_id="company")
        ).allowed

    def test_open_document_is_readable_by_every_role(self):
        for role in ("user", "manager", "auditor", "admin"):
            self.assertTrue(self._can(role, OPEN_PATH), f"{role} should read open doc")

    def test_restricted_document_denied_for_user_and_auditor(self):
        for role in ("user", "auditor"):
            self.assertFalse(self._can(role, RESTRICTED_PATH), f"{role} must be denied")

    def test_restricted_document_allowed_for_manager_and_admin(self):
        for role in ("manager", "admin"):
            self.assertTrue(self._can(role, RESTRICTED_PATH), f"{role} should be allowed")

    def test_restriction_covers_write_and_delete_not_just_read(self):
        for action in ("read", "write", "delete"):
            self.assertFalse(self._can("user", RESTRICTED_PATH, action))
            self.assertTrue(self._can("user", OPEN_PATH, action))

    def test_any_new_file_in_restricted_folder_is_protected_automatically(self):
        """The whole point of folder-based restriction: no per-file tagging."""
        brand_new = "/shared/contexts/restricted/some_future_secret.md"
        self.assertFalse(self._can("user", brand_new))
        self.assertTrue(self._can("manager", brand_new))

    def test_unlisted_document_is_allowed_by_default(self):
        self.assertTrue(self._can("user", "/shared/contexts/never_seen_before.md"))


class ContextAccessHelperTest(unittest.TestCase):
    """Router-level helpers used by the endpoints."""

    def setUp(self):
        self._old = deps.AUTH_ENABLED
        deps.AUTH_ENABLED = True

    def tearDown(self):
        deps.AUTH_ENABLED = self._old

    def test_resource_id_normalisation(self):
        for raw in (
            "/shared/contexts/x.md", "shared/contexts/x.md", "contexts/x.md",
        ):
            self.assertTrue(cm._context_resource_id(raw).startswith("/shared/"))
        self.assertEqual(
            cm._context_resource_id("shared/contexts/x.md"), "/shared/contexts/x.md"
        )

    def test_enforce_raises_403_on_restricted_for_user(self):
        with self.assertRaises(HTTPException) as ctx:
            cm.enforce_context_access(_request("user"), RESTRICTED_PATH, "read")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_enforce_allows_open_document_for_user(self):
        cm.enforce_context_access(_request("user"), OPEN_PATH, "read")  # no raise

    def test_enforce_allows_restricted_for_manager(self):
        cm.enforce_context_access(_request("manager"), RESTRICTED_PATH, "read")  # no raise

    def test_can_access_is_non_raising(self):
        self.assertFalse(cm.can_access_context(_request("user"), RESTRICTED_PATH, "read"))
        self.assertTrue(cm.can_access_context(_request("user"), OPEN_PATH, "read"))

    def test_listing_filter_hides_restricted_titles(self):
        """Restricted items are filtered out of listings, not returned-then-refused,
        so their titles do not leak."""
        req = _request("user")
        items = [{"path": OPEN_PATH}, {"path": RESTRICTED_PATH}]
        visible = [i for i in items if cm.can_access_context(req, i["path"], "read")]
        self.assertEqual(visible, [{"path": OPEN_PATH}])


class SampleFilesPresentTest(unittest.TestCase):
    """The demo files the policy rules are written against must exist."""

    def test_sample_context_files_exist(self):
        base = ROOT / "enterprise_root" / "tenants" / "company" / "shared"
        self.assertTrue((base / "contexts" / "open_sample_note.md").exists())
        self.assertTrue(
            (base / "contexts" / "restricted" / "hr_compensation_policy.md").exists()
        )


if __name__ == "__main__":
    unittest.main()
