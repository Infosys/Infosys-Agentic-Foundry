"""Offline tests for the Skill Designer pure helpers (envelope parse + validate dispatch).

Run: python3 tests/test_designer_core.py   (Homebrew python recommended)
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

_STUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # IAF-Agent-Studio
_REPO = os.path.dirname(_STUDIO)
# validators live in the sibling engine package (which imports agent_os); make both importable.
sys.path.insert(0, os.path.join(_REPO, "IAF-Agent-Skills"))
sys.path.insert(0, _REPO)
sys.path.insert(0, _STUDIO)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = _load("designer_core_under_test", os.path.join(_STUDIO, "routers", "designer_core.py"))

# The graph/workstream validators live in the engine package; it may not import in a bare offline
# env. Probe once and skip those (only those) if it can't — the pure parse/skill/cron tests always run.
try:
    import iaf_agent_skills.process_graph  # noqa: F401
    import iaf_agent_skills.workstream_store  # noqa: F401
    _ENGINE_OK = True
except Exception as _e:  # noqa: BLE001
    _ENGINE_OK = False

_GRAPH_YAML = """
apiVersion: agentos/process-graph/v1
name: cg
nodes:
  - {id: a, skill: rlm_ap_report, role: worker, task: do a}
  - {id: v, skill: general, role: verifier, task: "check {{a.result}}", verdict: {pass_when: PASS}}
  - {id: s, skill: general, role: worker, task: "use {{a.result}}"}
edges:
  - {from: [a], to: v}
  - {from: v, to: s, when: pass}
grounding: {independent_verifier: true}
"""


class TestParseEnvelope(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(core.parse_envelope('{"artifact_type":"skill","name":"x"}')["name"], "x")

    def test_fenced_json(self):
        txt = "Here you go:\n```json\n{\"artifact_type\":\"cron\",\"name\":\"c\"}\n```\nthanks"
        self.assertEqual(core.parse_envelope(txt)["artifact_type"], "cron")

    def test_prose_wrapped(self):
        txt = 'sure — {"artifact_type":"skill","name":"y"} done'
        self.assertEqual(core.parse_envelope(txt)["name"], "y")

    def test_empty_raises(self):
        self.assertRaises(ValueError, core.parse_envelope, "")


class TestValidateDispatch(unittest.TestCase):
    def test_skill_ok(self):
        env = {"artifact_type": "skill", "skill": {"name": "my_skill", "execution_mode": "react"}}
        self.assertEqual(core.validate_envelope(env), [])

    def test_skill_bad_name(self):
        env = {"artifact_type": "skill", "skill": {"name": "Bad Name"}}
        self.assertTrue(any("snake_case" in e for e in core.validate_envelope(env)))

    def test_workflow_requires_steps(self):
        env = {"artifact_type": "skill", "skill": {"name": "wf", "execution_mode": "workflow"}}
        self.assertTrue(any("requires steps" in e for e in core.validate_envelope(env)))

    @unittest.skipUnless(_ENGINE_OK, "engine package not importable offline")
    def test_graph_valid(self):
        env = {"artifact_type": "graph_skill", "skill": {"name": "gskill", "execution_mode": "graph"},
               "graph_yaml": _GRAPH_YAML}
        self.assertEqual(core.validate_envelope(env), [])

    @unittest.skipUnless(_ENGINE_OK, "engine package not importable offline")
    def test_graph_invalid(self):
        bad = _GRAPH_YAML.replace("to: v", "to: NOPE")   # dangling edge target
        env = {"artifact_type": "graph_skill", "skill": {"name": "gskill", "execution_mode": "graph"},
               "graph_yaml": bad}
        self.assertTrue(any("graph invalid" in e for e in core.validate_envelope(env)))

    def test_graph_missing_yaml(self):
        env = {"artifact_type": "graph_skill", "skill": {"name": "g", "execution_mode": "graph"}}
        self.assertTrue(any("requires graph_yaml" in e for e in core.validate_envelope(env)))

    def test_cron_missing_fields(self):
        errs = core.validate_envelope({"artifact_type": "cron", "cron": {}})
        self.assertTrue(any("skill_name" in e for e in errs))
        self.assertTrue(any("expression" in e for e in errs))

    def test_unknown_type(self):
        self.assertTrue(any("unknown artifact_type" in e for e in core.validate_envelope({"artifact_type": "zzz"})))

    @unittest.skipUnless(_ENGINE_OK, "engine package not importable offline")
    def test_workstream(self):
        # validate_workstream requires name + (skill|automation); an empty ws must error.
        errs = core.validate_envelope({"artifact_type": "workstream", "workstream": {}})
        self.assertTrue(len(errs) >= 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
