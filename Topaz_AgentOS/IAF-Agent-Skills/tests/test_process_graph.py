"""Offline tests for the process-graph loader/compiler (Phase 1 core).

Run: python3 tests/test_process_graph.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iaf_agent_skills")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SKILL_GRAPH = os.path.join(
    _REPO, "enterprise_root", "tenants", "company", "skills",
    "ap_ccd_morning_briefing", "graph.yaml")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_BASE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pg = _load("process_graph_under_test", "process_graph.py")
planner = _load("planner_under_test", "planner.py")


class _FakeRunner:
    def __init__(self, factory, skill):
        self._f, self._skill = factory, skill

    def run(self, task, skill_name=None):
        return self._f._respond(self._skill, task)


class FakeFactory:
    """agent_factory(skill) -> runner. Scripts the verifier's verdicts; logs every (skill, task)."""
    def __init__(self, verifier_verdicts, worker_sleep=0.0):
        self.verdicts = list(verifier_verdicts)
        self.vcount = 0
        self.calls = []            # [(skill, task)]
        self.worker_sleep = worker_sleep

    def __call__(self, skill):
        return _FakeRunner(self, skill)

    def _respond(self, skill, task):
        self.calls.append((skill, task))
        if skill == "verifier_skill":
            v = self.verdicts[min(self.vcount, len(self.verdicts) - 1)]
            self.vcount += 1
            return v
        if skill == "synth_skill":
            return "SYNTHESIS OUTPUT"
        if self.worker_sleep:
            import time as _t
            _t.sleep(self.worker_sleep)
        return f"worker-ok:{skill}"


def _converge_graph(max_loops=3, on_exhausted="escalate_to_human", pass_when="PASS", max_concurrency=1):
    return {
        "apiVersion": "agentos/process-graph/v1", "name": "cg",
        "nodes": [
            {"id": "w1", "skill": "worker_a", "role": "worker", "task": "do w1"},
            {"id": "w2", "skill": "worker_b", "role": "worker", "task": "do w2"},
            {"id": "v", "skill": "verifier_skill", "role": "verifier",
             "task": "check {{w1.result}} {{w2.result}}", "verdict": {"pass_when": pass_when}},
            {"id": "s", "skill": "synth_skill", "role": "worker", "task": "synth {{w1.result}} {{w2.result}}"},
        ],
        "edges": [
            {"from": ["w1", "w2"], "to": "v"},
            {"from": "v", "to": "s", "when": "pass"},
            {"from": "v", "to": "w1", "when": "fail", "max_loops": max_loops},
        ],
        "converge": {"until": "v.pass", "scope": ["w1", "w2", "v"], "max_loops": max_loops,
                     "carry_feedback": "v", "on_exhausted": on_exhausted, "max_concurrency": max_concurrency},
        "grounding": {"independent_verifier": True},
    }


def _run(g, factory):
    pg.validate_graph(g)                       # graph must be well-formed
    plan = pg.compile_to_plan(g)
    plan["confirmed"] = True
    eng = planner.PlannerEngine(llm=None)
    return eng.execute_graph(plan, plan["graph_meta"], agent=None, agent_factory=factory)


class TestConverge(unittest.TestCase):
    def test_converges_after_retries(self):
        f = FakeFactory(["FAIL: fix it", "FAIL: still", "PASS good"])
        res = _run(_converge_graph(max_loops=3), f)
        self.assertTrue(res.get("converged"))
        self.assertEqual(res["iterations"], 3)
        s = next(x for x in res["steps"] if x["id"] == "s")
        self.assertEqual(s["status"], "done")                       # downstream ran on PASS
        self.assertIn("SYNTHESIS OUTPUT", res["combined_result"])

    def test_feedback_carried_into_retry(self):
        f = FakeFactory(["FAIL: fix the total", "PASS ok"])
        _run(_converge_graph(max_loops=3), f)
        worker_tasks = [t for (sk, t) in f.calls if sk in ("worker_a", "worker_b")]
        self.assertTrue(any("[Revision 2]" in t for t in worker_tasks))
        self.assertTrue(any("FAIL: fix the total" in t for t in worker_tasks))

    def test_exhausted_escalates_and_gates_downstream(self):
        f = FakeFactory(["FAIL: a", "FAIL: b", "FAIL: c"])
        res = _run(_converge_graph(max_loops=2, on_exhausted="escalate_to_human"), f)
        self.assertTrue(res.get("escalate"))
        self.assertEqual(res["iterations"], 2)
        s = next(x for x in res["steps"] if x["id"] == "s")
        self.assertNotEqual(s.get("status"), "done")                # synthesis NOT run on exhaustion
        self.assertIn("did not pass", res["reason"])

    def test_best_effort_runs_downstream_with_caveat(self):
        f = FakeFactory(["FAIL: x"])
        res = _run(_converge_graph(max_loops=1, on_exhausted="best_effort"), f)
        self.assertIsNone(res.get("escalate"))
        self.assertIn("best-effort", res["combined_result"])
        s = next(x for x in res["steps"] if x["id"] == "s")
        self.assertEqual(s["status"], "done")

    def test_fail_skips_downstream(self):
        f = FakeFactory(["FAIL: x"])
        res = _run(_converge_graph(max_loops=1, on_exhausted="fail"), f)
        self.assertIsNone(res.get("escalate"))
        s = next(x for x in res["steps"] if x["id"] == "s")
        self.assertNotEqual(s.get("status"), "done")
        self.assertIn("did not pass", res["combined_result"])

    def test_parallel_branches_overlap(self):
        import time as _t
        seq_f = FakeFactory(["PASS"], worker_sleep=0.2)
        t0 = _t.time(); _run(_converge_graph(max_loops=1, max_concurrency=1), seq_f); seq = _t.time() - t0
        par_f = FakeFactory(["PASS"], worker_sleep=0.2)
        t0 = _t.time(); _run(_converge_graph(max_loops=1, max_concurrency=2), par_f); par = _t.time() - t0
        self.assertGreater(seq, 0.35)      # two 0.2s workers sequentially
        self.assertLess(par, 0.35)         # concurrent → ~0.2s
        self.assertLess(par, seq)

    def test_escalate_on_exhausted_grounding_override(self):
        # grounding.escalate_on_exhausted must override a softer on_exhausted at compile time.
        g = _converge_graph(max_loops=1, on_exhausted="best_effort")
        g["grounding"]["escalate_on_exhausted"] = True
        plan = pg.compile_to_plan(g)
        self.assertEqual(plan["graph_meta"]["converge"]["on_exhausted"], "escalate_to_human")


class TestP1Regression(unittest.TestCase):
    def test_no_converge_has_no_graph_meta(self):
        g = _converge_graph()
        g.pop("converge")                  # a plain DAG (no convergence)
        plan = pg.compile_to_plan(g)
        self.assertNotIn("graph_meta", plan)   # → dispatch uses the one-shot execute_plan (P1)


def _good_graph():
    return {
        "apiVersion": "agentos/process-graph/v1",
        "name": "t",
        "nodes": [
            {"id": "a", "skill": "rlm_ap_report", "role": "worker", "task": "do A for {{inputs.d}}"},
            {"id": "b", "skill": "ccdops", "role": "worker", "task": "do B"},
            {"id": "v", "skill": "general", "role": "verifier", "task": "check", "verdict": {"pass_when": "PASS"}},
            {"id": "s", "skill": "general", "role": "worker", "task": "use {{a.result}} and {{b.result}}"},
        ],
        "edges": [
            {"from": ["a", "b"], "to": "v"},
            {"from": "v", "to": "s", "when": "pass"},
            {"from": "v", "to": "a", "when": "fail", "max_loops": 1},
        ],
        "inputs": [{"name": "d", "default": "today"}],
        "grounding": {"independent_verifier": True, "frozen": ["grounding"]},
    }


class TestValidate(unittest.TestCase):
    def test_good(self):
        pg.validate_graph(_good_graph())  # no raise

    def test_bad_apiversion(self):
        g = _good_graph(); g["apiVersion"] = "x"
        self.assertRaises(pg.ProcessGraphError, pg.validate_graph, g)

    def test_unknown_edge_node(self):
        g = _good_graph(); g["edges"].append({"from": "a", "to": "nope"})
        self.assertRaises(pg.ProcessGraphError, pg.validate_graph, g)

    def test_when_pass_must_be_verifier(self):
        g = _good_graph(); g["edges"].append({"from": "a", "to": "s", "when": "pass"})  # a is a worker
        self.assertRaises(pg.ProcessGraphError, pg.validate_graph, g)

    def test_independent_verifier_violation(self):
        g = _good_graph()
        g["nodes"][2]["skill"] = "rlm_ap_report"  # verifier now shares a graded node's skill
        self.assertRaises(pg.ProcessGraphError, pg.validate_graph, g)


class TestCompile(unittest.TestCase):
    def test_depends_on_and_skips_failedge(self):
        plan = pg.compile_to_plan(_good_graph())
        steps = {s["id"]: s for s in plan["steps"]}
        self.assertEqual(set(steps), {"a", "b", "v", "s"})
        self.assertEqual(steps["a"]["depends_on"], [])            # loop-back (when:fail) skipped
        self.assertEqual(sorted(steps["v"]["depends_on"]), ["a", "b"])   # fan-in
        self.assertEqual(steps["s"]["depends_on"], ["v"])          # when:pass edge kept
        self.assertIn("rlm_ap_report", steps["a"]["skill"])

    def test_inputs_interpolated(self):
        plan = pg.compile_to_plan(_good_graph())
        a = next(s for s in plan["steps"] if s["id"] == "a")
        self.assertIn("today", a["task"])                          # {{inputs.d}} -> today
        self.assertNotIn("{{inputs", a["task"])

    def test_result_refs_left_for_executor(self):
        plan = pg.compile_to_plan(_good_graph())
        s = next(x for x in plan["steps"] if x["id"] == "s")
        self.assertIn("{{a.result}}", s["task"])                   # left for PlannerEngine to interpolate


class TestRealSkillGraph(unittest.TestCase):
    def test_load_and_compile(self):
        if not os.path.exists(_SKILL_GRAPH):
            self.skipTest("skill graph.yaml not present")
        g = pg.load_graph(_SKILL_GRAPH)
        plan = pg.compile_to_plan(g)
        ids = {s["id"] for s in plan["steps"]}
        self.assertEqual(ids, {"ap_report", "ccd_status", "verify", "synthesis"})
        verify = next(s for s in plan["steps"] if s["id"] == "verify")
        self.assertEqual(sorted(verify["depends_on"]), ["ap_report", "ccd_status"])
        synth = next(s for s in plan["steps"] if s["id"] == "synthesis")
        self.assertEqual(synth["depends_on"], ["verify"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
