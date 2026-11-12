"""graphify engine for taxonomy graph import (file-based; no network, no credentials)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills"):
    sys.path.insert(0, str(p))

from agentos_contracts.graph_source import FileGraphQuery  # noqa: E402
from iaf_agent_skills.graph_import import (  # noqa: E402
    GraphifyAdapter, GraphImportError, build_file_query, get_connection, list_connections,
    preview_taxonomy, resolve_graph_path,
)
from iaf_agent_skills.graph_import.graphify_adapter import read_graph_json  # noqa: E402

REAL_GRAPH = Path(r"C:\Users\sai.dharmala\Agent_OS_Opensource\graphify-out\graph.json")


def node(id_, label, src, comm, ftype="code", loc="L10"):
    return {"id": id_, "label": label, "file_type": ftype, "source_file": src,
            "source_location": loc, "community": comm, "_origin": "ast"}


def sample_graph():
    nodes = [
        # file containers (label == basename)
        node("f_agent", "agent.py", "IAF-Agent-Skills/iaf_agent_skills/agent.py", 0, loc="L1"),
        node("f_router", "router.py", "IAF-Agent-Skills/iaf_agent_skills/router.py", 0, loc="L1"),
        node("f_auth", "auth.py", "IAF-Agent-Studio/routers/auth.py", 1, loc="L1"),
        node("f_ghost", "ghost.py", ".github/x/ghost.py", 2, loc="L1"),
        # symbols
        node("s1", "SkillAgent", "IAF-Agent-Skills/iaf_agent_skills/agent.py", 0),
        node("s2", ".run()", "IAF-Agent-Skills/iaf_agent_skills/agent.py", 0),
        node("s3", "SkillRouter", "IAF-Agent-Skills/iaf_agent_skills/router.py", 0),
        node("s4", "login()", "IAF-Agent-Studio/routers/auth.py", 1),
        node("s5", "logout()", "IAF-Agent-Studio/routers/auth.py", 1),
        node("s6", "refresh()", "IAF-Agent-Studio/routers/auth.py", 1),
        node("s7", "lonely()", ".github/x/ghost.py", 2),
        # docstring/rationale nodes must never become activities
        node("r1", "Strict login rate limit", "IAF-Agent-Studio/routers/auth.py", 1, ftype="rationale"),
        # dunder noise, and a file that is left with no symbols (an empty package __init__)
        node("d1", ".__init__()", "IAF-Agent-Skills/iaf_agent_skills/agent.py", 0),
        node("d2", "__all__", "IAF-Agent-Skills/iaf_agent_skills/agent.py", 0),
        node("f_empty", "__init__.py", "IAF-Agent-Skills/iaf_agent_skills/__init__.py", 0, loc="L1"),
    ]
    links = [{"source": "f_agent", "target": "s1", "relation": "contains", "confidence": "EXTRACTED"},
             {"source": "s1", "target": "s3", "relation": "calls", "confidence": "EXTRACTED"}]
    return {"directed": False, "multigraph": False, "graph": {}, "nodes": nodes, "links": links}


def make_graph_dir(graph=None, labels=None):
    d = tempfile.TemporaryDirectory()
    gdir = Path(d.name)
    (gdir / "graph.json").write_text(json.dumps(graph or sample_graph()), encoding="utf-8")
    if labels is not None:
        (gdir / ".graphify_labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return d, gdir / "graph.json"


class AdapterTests(unittest.TestCase):
    def snap(self, graph_path, **kw):
        return GraphifyAdapter(graph_path).fetch_snapshot(FileGraphQuery(**kw), root_name="Repo")

    def test_community_mode_uses_labels_files_and_symbols(self):
        d, gp = make_graph_dir(labels={"0": "Agent Core", "1": "Auth Routes"})
        with d:
            s = self.snap(gp, mode="community", min_size=1)
        names = {n.id: n.name for n in s.nodes.values()}
        domains = [names[e.child_id] for e in s.edges if e.parent_id == "root"]
        self.assertEqual(set(domains), {"Agent Core", "Auth Routes", "Community 2"})
        flat = set(names.values())
        self.assertIn("IAF-Agent-Skills/iaf_agent_skills/agent.py", flat)         # file = section
        self.assertIn("SkillAgent", flat)                                          # symbol = activity
        self.assertNotIn("agent.py", flat)                                         # file container is not a symbol
        self.assertNotIn("Strict login rate limit", flat)                          # rationale skipped
        self.assertNotIn(".__init__()", flat)                                      # dunder noise skipped
        self.assertNotIn("__all__", flat)
        self.assertNotIn("IAF-Agent-Skills/iaf_agent_skills/__init__.py", flat)    # symbol-less file skipped
        # leading './' normalised, dot-dirs preserved
        self.assertIn(".github/x/ghost.py", flat)
        self.assertFalse(s.truncated)

    def test_min_size_and_max_domains(self):
        d, gp = make_graph_dir(labels={"0": "Agent Core", "1": "Auth Routes"})
        with d:
            s = self.snap(gp, mode="community", min_size=3)      # sizes: c0=3 symbols, c1=3, c2=1
            doms = [n.name for n in s.nodes.values() if n.id.startswith("d") and "f" not in n.id[1:]]
            self.assertEqual(sorted(doms), ["Agent Core", "Auth Routes"])
            s = self.snap(gp, mode="community", min_size=1, max_domains=1)
            self.assertTrue(s.truncated)
            self.assertEqual(len([e for e in s.edges if e.parent_id == "root"]), 1)

    def test_duplicate_community_labels_stay_distinct(self):
        d, gp = make_graph_dir(labels={"0": "Same", "1": "Same"})
        with d:
            s = self.snap(gp, mode="community", min_size=1)
        doms = sorted(s.nodes[e.child_id].name for e in s.edges if e.parent_id == "root")
        self.assertEqual(len(set(doms)), len(doms))
        self.assertIn("Same", doms)

    def test_path_mode_groups_by_directory(self):
        d, gp = make_graph_dir()
        with d:
            s = self.snap(gp, mode="path", domain_depth=2)
        doms = sorted(s.nodes[e.child_id].name for e in s.edges if e.parent_id == "root")
        self.assertEqual(doms, [".github/x", "IAF-Agent-Skills/iaf_agent_skills", "IAF-Agent-Studio/routers"])

    def test_prefix_filter_and_validation(self):
        d, gp = make_graph_dir()
        with d:
            s = self.snap(gp, mode="path", path_prefix="IAF-Agent-Studio")
            files = [n.name for n in s.nodes.values() if n.name.endswith(".py")]
            self.assertEqual(files, ["IAF-Agent-Studio/routers/auth.py"])
            with self.assertRaises(GraphImportError) as c:
                self.snap(gp, mode="path", path_prefix="nothing/here")
            self.assertEqual((c.exception.code, c.exception.status), ("root_not_found", 404))
            for bad in ("../etc", "a/../b", "x;rm -rf", "a`b"):
                with self.assertRaises(GraphImportError, msg=bad) as c:
                    self.snap(gp, mode="path", path_prefix=bad)
                self.assertEqual(c.exception.code, "bad_prefix")

    def test_node_cap_flags_truncation(self):
        d, gp = make_graph_dir()
        with d:
            s = self.snap(gp, mode="path", max_nodes=10)
        self.assertTrue(s.truncated)
        self.assertLessEqual(len(s.nodes), 10)

    def test_bad_mode_and_bad_files(self):
        d, gp = make_graph_dir()
        with d:
            with self.assertRaises(GraphImportError) as c:
                self.snap(gp, mode="nope")
            self.assertEqual(c.exception.code, "bad_mode")
            gp.write_text("{not json", encoding="utf-8")
            with self.assertRaises(GraphImportError) as c:
                self.snap(gp, mode="path")
            self.assertEqual(c.exception.code, "bad_graph")
            gp.write_text(json.dumps({"nodes": [], "something": 1}), encoding="utf-8")
            with self.assertRaises(GraphImportError) as c:
                read_graph_json(gp)
            self.assertEqual(c.exception.code, "bad_graph")
            with self.assertRaises(GraphImportError) as c:
                read_graph_json(gp, max_bytes=3)
            self.assertEqual(c.exception.code, "graph_too_large")
        with self.assertRaises(GraphImportError) as c:
            read_graph_json(Path("does-not-exist.json"))
        self.assertEqual(c.exception.code, "graph_not_found")

    def test_accepts_edges_key_variant(self):
        g = sample_graph()
        g["edges"] = g.pop("links")
        d, gp = make_graph_dir(graph=g)
        with d:
            self.assertEqual(GraphifyAdapter(gp).health()["status"], "ok")

    @unittest.skipUnless(REAL_GRAPH.is_file(), "real graphify graph not present on this machine")
    def test_real_graph_both_modes(self):
        a = GraphifyAdapter(REAL_GRAPH)
        for mode in ("community", "path"):
            s = a.fetch_snapshot(FileGraphQuery(mode=mode), root_name="AgentOS")
            self.assertGreater(len(s.nodes), 100, mode)
            self.assertLessEqual(len(s.nodes), 5000, mode)
        c = a.fetch_snapshot(FileGraphQuery(mode="community"), root_name="AgentOS")
        self.assertLessEqual(len([e for e in c.edges if e.parent_id == "root"]), 40)


class ConfinementAndServiceTests(unittest.TestCase):
    def tenant(self, resources, graph=None, labels=None, name="repo"):
        d = tempfile.TemporaryDirectory()
        root = Path(d.name)
        (root / "security").mkdir()
        (root / "security" / "external_access.yaml").write_text(yaml.safe_dump({"version": "1.0", "resources": resources}))
        gdir = root / "shared" / "graphs" / name
        gdir.mkdir(parents=True)
        (gdir / "graph.json").write_text(json.dumps(graph or sample_graph()), encoding="utf-8")
        if labels:
            (gdir / ".graphify_labels.json").write_text(json.dumps(labels), encoding="utf-8")
        return d, root

    RES = {"id": "external:graph.repo", "type": "graph", "engine": "graphify", "label": "AgentOS code graph",
           "path": "/shared/graphs/repo/graph.json"}

    def test_path_confinement(self):
        d, root = self.tenant([self.RES])
        with d:
            self.assertTrue(resolve_graph_path(root, "/shared/graphs/repo/graph.json").is_file())
            for bad in ("/shared/graphs/../security/external_access.yaml", "/etc/passwd.json",
                        "/shared/graphs/repo/../../x.json", "shared/graphs/repo/graph.json",
                        "/shared/graphs/repo/graph.txt", "/shared/graphs//graph.json", ""):
                with self.assertRaises(GraphImportError, msg=bad):
                    resolve_graph_path(root, bad)
            with self.assertRaises(GraphImportError) as c:
                resolve_graph_path(root, "/shared/graphs/missing/graph.json")
            self.assertEqual(c.exception.code, "graph_not_found")

    def test_symlink_escape_blocked(self):
        d, root = self.tenant([self.RES])
        with d:
            outside = Path(tempfile.mkdtemp()) / "secret.json"
            outside.write_text("{}", encoding="utf-8")
            link = root / "shared" / "graphs" / "repo" / "evil.json"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not permitted on this machine")
            with self.assertRaises(GraphImportError):
                resolve_graph_path(root, "/shared/graphs/repo/evil.json")

    def test_registry_lists_graphify_connection_without_exposing_path(self):
        d, root = self.tenant([self.RES, {"id": "external:graph.bad", "type": "graph", "engine": "graphify"}])
        with d:
            conns = list_connections(root)
            self.assertEqual([c.id for c in conns], ["external:graph.repo"])         # entry without a path is ignored
            pub = get_connection(root, "graph.repo").public()
            self.assertEqual(pub["engine"], "graphify")
            self.assertNotIn("graphs", json.dumps(pub))
            self.assertFalse(pub["has_credential"])

    def test_preview_end_to_end_no_credentials_needed(self):
        d, root = self.tenant([self.RES], labels={"0": "Agent Core", "1": "Auth Routes"})
        skills = {"auth_ops": {"description": "login logout refresh authentication routes", "keywords": ["auth"]}}
        with d:
            out = preview_taxonomy(
                root, connection_id="external:graph.repo",
                params={"mode": "community", "min_size": 1, "taxonomy_name": "Repo map"},
                credential_lookup=lambda n: self.fail("graphify needs no credential"), skills_index=skills)
        self.assertEqual(out["name"], "Repo map")
        by = {x["name"]: x for x in out["domains"]}
        self.assertEqual(set(by), {"Agent Core", "Auth Routes", "Community 2"})
        sec = by["Auth Routes"]["sections"][0]
        self.assertEqual(sec["name"], "IAF-Agent-Studio/routers/auth.py")
        self.assertEqual(sec["skill"], "")                                           # never auto-assigned
        self.assertEqual(sec["suggestions"][0]["skill"], "auth_ops")
        self.assertEqual(sorted(sec["activities"]), ["login()", "logout()", "refresh()"])
        self.assertEqual(out["provenance"]["source_engine"], "graphify")
        self.assertTrue(out["provenance"]["source_root"].startswith("community"))
        self.assertEqual(out["unmapped_sections"], out["stats"]["sections"])

    def test_preview_errors_are_generic(self):
        d, root = self.tenant([self.RES])
        with d:
            for params, code in (({"mode": "bogus"}, "bad_mode"),
                                 ({"mode": "path", "path_prefix": "../x"}, "bad_prefix"),
                                 ({"mode": "path", "path_prefix": "zzz"}, "root_not_found")):
                with self.assertRaises(GraphImportError) as c:
                    preview_taxonomy(root, connection_id="graph.repo", params=params,
                                     credential_lookup=lambda n: None, skills_index={})
                self.assertEqual(c.exception.code, code)
                self.assertNotIn(str(root), c.exception.message)

    def test_build_file_query_clamps(self):
        q = build_file_query({"mode": "PATH", "domain_depth": 99, "max_domains": 10**6, "max_nodes": 10**9, "min_size": -5})
        self.assertEqual((q.mode, q.domain_depth, q.max_domains, q.max_nodes, q.min_size), ("path", 6, 200, 5000, 1))

    def test_validator_rules_for_graphify_resources(self):
        from agent_os.external_access import validate_external_access_doc as v
        self.assertTrue(v({"resources": [self.RES]})["valid"])
        for bad in (dict(self.RES, path="/etc/passwd"), dict(self.RES, path="/shared/graphs/../x.json"),
                    dict(self.RES, hosts=["h:1"]), {k: v_ for k, v_ in self.RES.items() if k != "path"}):
            self.assertFalse(v({"resources": [bad]})["valid"], bad)

    def test_validator_rejects_non_canonical_graph_paths(self):
        # These all resolve to the same file as /shared/graphs/repo/graph.json, so a connection
        # registered under them would dodge any rule keyed on the canonical spelling.
        from agent_os.external_access import validate_external_access_doc as v
        for p in ("/shared/graphs/repo/./graph.json", "/shared/graphs//repo/graph.json",
                  "/shared/graphs/./repo/graph.json", "/shared/graphs/repo//graph.json",
                  "/shared/graphs\\repo/graph.json"):
            with self.subTest(path=p):
                self.assertFalse(v({"resources": [dict(self.RES, path=p)]})["valid"], p)


class DomainNamingTests(unittest.TestCase):
    """Domain names must survive the taxonomy parser, which drops a trailing "(...)" from L2 headings."""

    @staticmethod
    def _graph(files):
        nodes = [{"id": f"n{i}", "label": f"Sym{i}()", "file_type": "code", "source_file": src,
                  "source_location": "L1", "community": comm} for i, (src, comm) in enumerate(files)]
        return {"directed": False, "multigraph": False, "graph": {}, "nodes": nodes, "links": []}

    def _domains(self, graph, labels=None, **kw):
        d, gp = make_graph_dir(graph=graph, labels=labels)
        with d:
            s = GraphifyAdapter(gp).fetch_snapshot(FileGraphQuery(**kw), root_name="Repo")
        names = {n.id: n.name for n in s.nodes.values()}
        return [names[e.child_id] for e in s.edges if e.parent_id == "root"]

    def test_root_level_files_get_a_visible_domain_name(self):
        names = self._domains(self._graph([("top.py", 0), ("pkg/a.py", 0)]), mode="path", min_size=1)
        self.assertIn("Root files", names)
        self.assertFalse(any(n.endswith(")") for n in names), names)

    def test_community_suffix_is_not_parenthetical(self):
        import re
        g = self._graph([("a.py", 3), ("b.py", 3), ("c.py", 4), ("d.py", 4)])
        names = self._domains(g, labels={"3": "Core", "4": "Core"}, mode="community", min_size=1)
        parsed = {re.sub(r"\s*\([^)]*\)\s*$", "", n).casefold() for n in names}
        self.assertEqual(len(parsed), len(names), names)       # still distinct after the parser strips "(...)"
        self.assertEqual(len(names), 2)


if __name__ == "__main__":
    unittest.main()
