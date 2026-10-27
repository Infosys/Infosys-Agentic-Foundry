"""Regression tests for Context Manager tenant isolation.

Defect pinned here: `routers/context_manager.py` had NO identity binding at all
(zero calls to bind_request_identity / principal_from_request / enforce_entitlement)
while ~33 endpoints accepted `tenant_id` from the caller and built filesystem
paths from it. An authenticated user of one tenant could read, edit, upload to or
delete another tenant's context items simply by changing the parameter — the 403
guard in security.dependencies was never consulted.

The fix authorises the requested tenant in a router-level dependency that runs
before any handler, so handler bodies stay untouched and each handler's
`tenant_id` argument is guaranteed to be one the principal may access.
"""

from __future__ import annotations

import asyncio
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


def _request(*, allowed=("company",), tenant="company", query=None, body=None, content_type=None):
    """Minimal Request stand-in matching the style used in test_entitlements.py."""
    headers = {}
    if content_type:
        headers["content-type"] = content_type

    class _Req:
        def __init__(self):
            self.state = SimpleNamespace(
                user_id="real-user",
                email="real@example.com",
                role="user",
                tenant_id=tenant,
                groups=[],
                allowed_tenants=list(allowed),
            )
            self.query_params = dict(query or {})
            self.headers = headers

        async def json(self):
            if body is None:
                raise ValueError("no body")
            return body

    return _Req()


class ContextManagerTenantIsolationTest(unittest.TestCase):
    def setUp(self):
        self._old_auth = deps.AUTH_ENABLED
        deps.AUTH_ENABLED = True

    def tearDown(self):
        deps.AUTH_ENABLED = self._old_auth

    def test_cross_tenant_query_param_is_refused(self):
        req = _request(allowed=("company",), query={"tenant_id": "healthpayer"})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(cm.require_context_tenant(req))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_cross_tenant_json_body_is_refused(self):
        """~15 endpoints carry tenant_id inside a pydantic body, not the query."""
        req = _request(
            allowed=("company",),
            body={"query": "x", "tenant_id": "healthpayer"},
            content_type="application/json",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(cm.require_context_tenant(req))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unknown_tenant_is_refused(self):
        req = _request(allowed=("company",), query={"tenant_id": "acme_evil"})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(cm.require_context_tenant(req))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_multipart_handler_guard_refuses_cross_tenant(self):
        """Multipart bodies are not parsed by the dependency, so the upload
        handlers call authorise_tenant() explicitly."""
        req = _request(allowed=("company",))
        with self.assertRaises(HTTPException) as ctx:
            cm.authorise_tenant(req, "healthpayer")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_own_tenant_query_param_is_allowed(self):
        req = _request(allowed=("company",), query={"tenant_id": "company"})
        self.assertEqual(asyncio.run(cm.require_context_tenant(req)), "company")

    def test_no_tenant_param_falls_back_to_principal_tenant(self):
        req = _request(allowed=("company",))
        self.assertEqual(asyncio.run(cm.require_context_tenant(req)), "company")

    def test_own_tenant_json_body_is_allowed(self):
        req = _request(
            allowed=("company",),
            body={"query": "x", "tenant_id": "company"},
            content_type="application/json",
        )
        self.assertEqual(asyncio.run(cm.require_context_tenant(req)), "company")

    def test_multi_tenant_principal_may_reach_each_entitled_tenant(self):
        for target in ("company", "healthpayer"):
            req = _request(allowed=("company", "healthpayer"), query={"tenant_id": target})
            self.assertEqual(asyncio.run(cm.require_context_tenant(req)), target)

    def test_multipart_handler_guard_allows_own_tenant(self):
        req = _request(allowed=("company",))
        self.assertEqual(cm.authorise_tenant(req, "company"), "company")

    def test_router_has_the_dependency_attached(self):
        names = [getattr(d.dependency, "__name__", "") for d in (cm.router.dependencies or [])]
        self.assertIn("require_context_tenant", names)

    def test_authorised_tenant_is_published_on_request_state(self):
        req = _request(allowed=("company",), query={"tenant_id": "company"})
        asyncio.run(cm.require_context_tenant(req))
        self.assertEqual(req.state.context_tenant, "company")
        self.assertIsNotNone(req.state.context_principal)

    def test_guard_no_ops_when_auth_disabled(self):
        deps.AUTH_ENABLED = False
        req = _request(allowed=("company",), query={"tenant_id": "healthpayer"})
        self.assertEqual(asyncio.run(cm.require_context_tenant(req)), "healthpayer")


if __name__ == "__main__":
    unittest.main()
