"""Governance-invariant tests for rlm/tools.py.

Requires the framework on the path (run under the AgentOS venv):
  PYTHONPATH=<IAF-Agent-Skills> <venv>/python3 tests/test_rlm_tools_governance.py
"""
from __future__ import annotations

import os
import sys
import unittest

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_here))                       # IAF-Agent-Skills → iaf_agent_skills
sys.path.insert(0, os.path.dirname(os.path.dirname(_here)))      # repo root → agent_os, agentos_model

import iaf_agent_skills.rlm.tools as tools  # noqa: E402


class _Decision:
    def __init__(self, allowed, status="allowed", reason=""):
        self.allowed = allowed
        self.status = status
        self.reason = reason


class TestGovernAndRun(unittest.TestCase):
    """Invariant: a wrapped tool executes ONLY when governance returns allowed."""

    def setUp(self):
        self._orig = tools.govern_tool_call

    def tearDown(self):
        tools.govern_tool_call = self._orig

    def test_allowed_executes(self):
        tools.govern_tool_call = lambda agent, tc, source: _Decision(True)
        ran = []
        r = tools.govern_and_run(object(), "t", {}, lambda: (ran.append(1), "ok")[1])
        self.assertEqual(r, "ok")
        self.assertEqual(ran, [1])

    def test_blocked_does_not_execute(self):
        tools.govern_tool_call = lambda agent, tc, source: _Decision(False, "blocked", "nope")
        ran = []
        r = tools.govern_and_run(object(), "t", {}, lambda: ran.append(1))
        self.assertEqual(ran, [])
        self.assertIn("blocked", r)

    def test_pending_does_not_execute(self):
        tools.govern_tool_call = lambda agent, tc, source: _Decision(False, "pending", "approve me")
        ran = []
        r = tools.govern_and_run(object(), "t", {}, lambda: ran.append(1))
        self.assertEqual(ran, [])
        self.assertIn("approval", r)


class TestBuildTools(unittest.TestCase):
    def test_propose_action_present_and_records(self):
        class FakeAgent:
            def _get_allowed_tools(self):
                return []  # nothing else allowed → only propose_action is built
        tools_dict, prompt, proposed = tools.build_rlm_tools(FakeAgent())
        self.assertIn("propose_action", tools_dict)
        self.assertNotIn("run_sql_query", tools_dict)
        self.assertNotIn("invoke_skill", tools_dict)
        msg = tools_dict["propose_action"]("release_payment", "inv=A-7731", "overdue")
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["kind"], "release_payment")
        self.assertIn("recorded", msg)


class TestDemoTools(unittest.TestCase):
    _BASE = os.path.join(os.path.dirname(os.path.dirname(_here)),
                          "enterprise_root", "tenants", "company", "shared", "rlm_demo")

    def test_http_get_and_read_document_built(self):
        base = self._BASE
        class FakeAgent:
            _rlm_cfg = {"docs_dir": base + "/docs", "creds_file": base + "/credentials.json"}
            def _get_allowed_tools(self):
                return ["http_get", "read_document"]
        td, prompt, _ = tools.build_rlm_tools(FakeAgent())
        self.assertIn("http_get", td)
        self.assertIn("read_document", td)
        self.assertIn("propose_action", td)
        self.assertIn("ap_payment_policy.md", prompt)  # docs enumerated in the prompt

    def test_read_document_path_jail(self):
        base = self._BASE
        class FakeAgent:
            _rlm_cfg = {"docs_dir": base + "/docs"}
            def _get_allowed_tools(self):
                return ["read_document"]
        td, _, _ = tools.build_rlm_tools(FakeAgent())
        r = td["read_document"]("../credentials.json")   # escape attempt → blocked BEFORE govern
        self.assertIn("blocked", r)

    def test_tools_absent_without_config(self):
        class FakeAgent:
            _rlm_cfg = {}                       # no docs_dir/creds_file
            def _get_allowed_tools(self):
                return ["http_get", "read_document"]
        td, _, _ = tools.build_rlm_tools(FakeAgent())
        self.assertNotIn("http_get", td)        # gated by config presence
        self.assertNotIn("read_document", td)
        self.assertIn("propose_action", td)


if __name__ == "__main__":
    unittest.main()
