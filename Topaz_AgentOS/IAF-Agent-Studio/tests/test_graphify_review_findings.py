"""Regression tests for the Copilot review of the graphify PR (8 findings).

Each test reproduces ONE claim from the review, so a failure before the fix proves the
finding was exact, and a pass afterwards proves it is closed.

  F1  adapter reads the labels sidecar without confining or size-capping it
  F2  graph_query tool does the same
  F3  tool output can exceed the skill loader's 10 KB cap and be cut into invalid JSON
  F4  generated duplicate-label suffixes can collide with a real label and drop a community
  F5  tool crashes (traceback, no JSON) on a graph file whose root is not an object
  F6  explain() neighbours carry no id / source location
  F7  path() intermediate steps carry no id / file / location
  F8  community lookup rejects the generated name "Community 12"
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills"):
    sys.path.insert(0, str(p))

from agentos_contracts.graph_source import FileGraphQuery  # noqa: E402
from iaf_agent_skills.graph_import import GraphifyAdapter  # noqa: E402
from iaf_agent_skills.graph_import import graphify_adapter as ga  # noqa: E402

SKILL = ROOT / "enterprise_root" / "tenants" / "company" / "skills" / "codebase_graph"
TOOL = SKILL / "tools" / "graph_query.py"


def node(i, label, src, comm, ft="code", loc="L5"):
    return {"id": i, "label": label, "file_type": ft, "source_file": src, "source_location": loc, "community": comm}


def link(a, b, rel="calls", conf="EXTRACTED"):
    return {"source": a, "target": b, "relation": rel, "confidence": conf}


class Tenant:
    """<tmp>/tenants/company/{agents/enterprise_agent, shared/graphs/<name>/graph.json}"""

    def __init__(self, graph, labels=None, name="demo", raw=None):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name) / "tenants" / "company"
        self.agent = base / "agents" / "enterprise_agent"
        self.agent.mkdir(parents=True)
        self.gdir = base / "shared" / "graphs" / name
        self.gdir.mkdir(parents=True)
        self.graph_path = self.gdir / "graph.json"
        self.graph_path.write_text(raw if raw is not None else json.dumps(graph), encoding="utf-8")
        if labels is not None:
            (self.gdir / ".graphify_labels.json").write_text(json.dumps(labels), encoding="utf-8")
        self.name = name

    def run_tool(self, **payload):
        payload = {"query": "", "target": "", "graph": self.name, **payload}
        env = {**os.environ, "IAF_AGENT_ROOT": str(self.agent)}
        r = subprocess.run([sys.executable, str(TOOL)], input=json.dumps(payload), capture_output=True,
                           text=True, timeout=60, env=env, cwd=str(self.agent))
        self.last = r
        return r

    def cleanup(self):
        self.tmp.cleanup()


def load_tool_module():
    spec = importlib.util.spec_from_file_location("graph_query_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def base_graph():
    nodes = [node("A", "SkillAgent", "pkg/a.py", 0), node("B", "SafeKernel", "pkg/b.py", 1),
             node("C", "HookRunner", "pkg/c.py", 2)]
    return {"nodes": nodes, "links": [link("A", "B"), link("B", "C", "uses")]}


# ---------------------------------------------------------------- F1 / F2
class F1AdapterSidecar(unittest.TestCase):
    def setUp(self):
        self.t = Tenant(base_graph(), labels={"0": "Real Label"})
        self.addCleanup(self.t.cleanup)

    def test_sidecar_is_read_normally(self):
        self.assertEqual(GraphifyAdapter(self.t.graph_path)._labels(), {0: "Real Label"})

    def test_oversized_sidecar_is_ignored(self):
        with mock.patch.object(ga, "MAX_LABELS_BYTES", 5):
            self.assertEqual(GraphifyAdapter(self.t.graph_path)._labels(), {})

    def test_sidecar_resolving_outside_the_graph_folder_is_ignored(self):
        outside = Path(tempfile.mkdtemp()) / "other.json"
        outside.write_text(json.dumps({"0": "LEAKED"}), encoding="utf-8")
        real_resolve = Path.resolve

        def fake(self_, *a, **k):          # simulate a symlink: the sidecar resolves outside
            return outside if self_.name == ".graphify_labels.json" else real_resolve(self_, *a, **k)

        with mock.patch.object(Path, "resolve", fake):
            self.assertEqual(GraphifyAdapter(self.t.graph_path)._labels(), {})

    def test_real_symlink_if_the_machine_allows_it(self):
        outside = Path(tempfile.mkdtemp()) / "other.json"
        outside.write_text(json.dumps({"0": "LEAKED"}), encoding="utf-8")
        side = self.t.gdir / ".graphify_labels.json"
        side.unlink()
        try:
            os.symlink(outside, side)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted on this machine")
        self.assertEqual(GraphifyAdapter(self.t.graph_path)._labels(), {})


class F2ToolSidecar(unittest.TestCase):
    def setUp(self):
        self.t = Tenant(base_graph(), labels={"0": "Real Label"})
        self.addCleanup(self.t.cleanup)
        self.mod = load_tool_module()

    def _load(self):
        with mock.patch.dict(os.environ, {"IAF_AGENT_ROOT": str(self.t.agent)}):
            return self.mod.load(self.t.name)

    def test_sidecar_is_read_normally(self):
        self.assertEqual(self._load()[2], {0: "Real Label"})

    def test_oversized_sidecar_is_ignored(self):
        with mock.patch.object(self.mod, "MAX_BYTES", 40_000), mock.patch.object(self.mod, "MAX_SIDECAR_BYTES", 5, create=True):
            # graph.json (small) still loads; only the sidecar is over its own cap
            self.assertEqual(self._load()[2], {})

    def test_sidecar_resolving_outside_is_ignored(self):
        outside = Path(tempfile.mkdtemp()) / "other.json"
        outside.write_text(json.dumps({"0": "LEAKED"}), encoding="utf-8")
        real_resolve = Path.resolve

        def fake(self_, *a, **k):
            return outside if self_.name == ".graphify_labels.json" else real_resolve(self_, *a, **k)

        with mock.patch.object(Path, "resolve", fake):
            self.assertEqual(self._load()[2], {})


# ---------------------------------------------------------------- F3
class F3LoaderCap(unittest.TestCase):
    def test_reply_survives_the_skill_loader_as_valid_json(self):
        """Run the tool through the REAL loader wrapper (STDOUT_CAP = 10 KB), not directly."""
        from iaf_agent_skills.tools import skill_tool_loader as L
        nodes = [node("hub", "Hub", "pkg/hub.py", 0)]
        links = []
        for rel_i in range(10):
            for k in range(12):
                nid = f"n{rel_i}_{k}"
                nodes.append(node(nid, f"{'verylongsymbolname_' * 2}{rel_i}_{k}()", f"pkg/{'deep/' * 6}module_{rel_i}.py", 0, loc="L123"))
                links.append(link("hub", nid, f"relation_{rel_i}"))
        t = Tenant({"nodes": nodes, "links": links})
        self.addCleanup(t.cleanup)
        spec = L._parse_tool_spec(TOOL)
        tool = L.create_skill_tool(spec, TOOL, agent_root=str(t.agent))
        out = tool.invoke({"action": "explain", "graph": t.name, "query": "Hub", "target": ""})
        self.assertLessEqual(len(out), L.STDOUT_CAP, "loader would truncate this reply")
        doc = json.loads(out)                                   # must still parse after the loader
        self.assertTrue("node" in doc or doc.get("truncated"))

    def test_tool_limit_is_not_above_the_loaders(self):
        from iaf_agent_skills.tools import skill_tool_loader as L
        mod = load_tool_module()
        self.assertLessEqual(mod.MAX_OUT_CHARS, L.STDOUT_CAP)


# ---------------------------------------------------------------- F4
class F4SuffixCollision(unittest.TestCase):
    def test_generated_suffix_cannot_overwrite_a_real_label(self):
        nodes, ids = [], iter(range(1000))
        for comm in (0, 1, 2):
            for k in range(3):
                nodes.append(node(f"s{comm}{k}", f"sym{comm}_{k}()", f"pkg/f{comm}.py", comm))
        t = Tenant({"nodes": nodes, "links": []}, labels={"0": "Same", "1": "Same", "2": "Same (1)"})
        self.addCleanup(t.cleanup)
        snap = GraphifyAdapter(t.graph_path).fetch_snapshot(FileGraphQuery(mode="community", min_size=1), root_name="R")
        domains = [snap.nodes[e.child_id].name for e in snap.edges if e.parent_id == "root"]
        self.assertEqual(len(domains), 3, domains)                 # one per community, none lost
        self.assertEqual(len({d.casefold() for d in domains}), 3, domains)
        symbols = {n.name for n in snap.nodes.values() if n.name.startswith("sym")}
        self.assertEqual(len(symbols), 9)                          # nothing silently dropped


# ---------------------------------------------------------------- F5
class F5NonObjectRoot(unittest.TestCase):
    def test_non_object_roots_give_a_clean_error_not_a_traceback(self):
        for raw in ("[]", "null", "123", '"text"', "[1,2,3]"):
            t = Tenant(None, raw=raw)
            self.addCleanup(t.cleanup)
            r = t.run_tool(action="stats")
            self.assertNotIn("Traceback", r.stderr, raw)
            self.assertEqual(r.returncode, 0, f"{raw}: {r.stderr[-200:]}")
            doc = json.loads(r.stdout)
            self.assertIn("not a graphify", doc["error"], raw)
            self.assertNotIn(str(t.tmp.name), r.stdout + r.stderr)

    def test_adapter_side_is_already_safe(self):
        from iaf_agent_skills.graph_import.graphify_adapter import read_graph_json
        from iaf_agent_skills.graph_import import GraphImportError
        for raw in ("[]", "null", "123"):
            t = Tenant(None, raw=raw)
            self.addCleanup(t.cleanup)
            with self.assertRaises(GraphImportError) as c:
                read_graph_json(t.graph_path)
            self.assertEqual(c.exception.code, "bad_graph")


# ---------------------------------------------------------------- F6 / F7
class F6F7Citations(unittest.TestCase):
    def setUp(self):
        nodes = [node("hub", "Hub", "pkg/hub.py", 0, loc="L10"),
                 node("m1", ".run()", "pkg/one.py", 0, loc="L40"), node("m2", ".run()", "pkg/two.py", 0, loc="L77"),
                 node("end", "Target", "pkg/end.py", 1, loc="L9")]
        links = [link("hub", "m1", "calls"), link("hub", "m2", "calls"), link("m2", "end", "calls", "INFERRED")]
        self.t = Tenant({"nodes": nodes, "links": links})
        self.addCleanup(self.t.cleanup)

    def test_explain_neighbours_carry_id_and_location(self):
        r = json.loads(self.t.run_tool(action="explain", query="Hub").stdout)
        runs = [n for grp in r["neighbours"].values() for n in grp if n["label"] == ".run()"]
        self.assertEqual({n["id"] for n in runs}, {"m1", "m2"})            # same label, told apart by id
        self.assertEqual({n["location"] for n in runs}, {"L40", "L77"})
        self.assertTrue(all("confidence" in n for n in runs))

    def test_path_steps_identify_every_node_on_the_path(self):
        r = json.loads(self.t.run_tool(action="path", query="Hub", target="Target").stdout)
        self.assertEqual(r["hops"], 2)
        mid = r["path"][0]["to_node"]                                       # the intermediate .run()
        self.assertEqual((mid["id"], mid["file"], mid["location"]), ("m2", "pkg/two.py", "L77"))
        self.assertEqual(r["path"][1]["from_node"]["id"], "m2")
        self.assertEqual(r["path"][1]["to_node"]["id"], "end")
        self.assertEqual(r["path"][1]["confidence"], "INFERRED")


# ---------------------------------------------------------------- F8
class F8CommunityName(unittest.TestCase):
    def test_generated_community_names_are_accepted(self):
        t = Tenant(base_graph())                                # no labels file -> "Community N"
        self.addCleanup(t.cleanup)
        stats = json.loads(t.run_tool(action="stats").stdout)
        name = stats["largest_communities"][0][0]
        self.assertTrue(name.startswith("Community "), name)
        for q in (name, name.lower(), name.split()[-1], f"  {name}  "):
            r = json.loads(t.run_tool(action="community", query=q).stdout)
            self.assertNotIn("error", r, q)
            self.assertEqual(r["community"], name)

    def test_real_labels_and_misses_still_behave(self):
        t = Tenant(base_graph(), labels={"0": "Agent Core"})
        self.addCleanup(t.cleanup)
        self.assertEqual(json.loads(t.run_tool(action="community", query="agent core").stdout)["community"], "Agent Core")
        self.assertIn("error", json.loads(t.run_tool(action="community", query="Community 999").stdout))
        self.assertIn("error", json.loads(t.run_tool(action="community", query="zzz").stdout))


if __name__ == "__main__":
    unittest.main()
