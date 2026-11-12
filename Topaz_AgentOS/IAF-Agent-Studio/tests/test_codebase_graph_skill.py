"""codebase_graph skill + graph_query tool: registration, discovery, and behaviour.

The tool is run exactly the way the skill loader runs it: as a subprocess that reads a
JSON object on stdin, with IAF_AGENT_ROOT pointing at the agent folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills"):
    sys.path.insert(0, str(p))

SKILL_DIR = ROOT / "enterprise_root" / "tenants" / "company" / "skills" / "codebase_graph"
TOOL = SKILL_DIR / "tools" / "graph_query.py"
REAL = Path(r"C:\Users\sai.dharmala\Agent_OS_Opensource\graphify-out")


def node(i, label, src, comm, ft="code", loc="L5"):
    return {"id": i, "label": label, "file_type": ft, "source_file": src, "source_location": loc, "community": comm}


def link(a, b, rel="calls", conf="EXTRACTED"):
    return {"source": a, "target": b, "relation": rel, "confidence": conf}


def small_graph():
    nodes = [
        node("f_a", "agent.py", "pkg/agent.py", 0, loc="L1"), node("A", "SkillAgent", "pkg/agent.py", 0),
        node("B", "SafeKernel", "pkg/kernel.py", 1), node("C", "HookRunner", "pkg/hooks.py", 2),
        node("D", "Island", "pkg/island.py", 3), node("R", "Doc note about SkillAgent", "pkg/agent.py", 0, ft="rationale"),
    ]
    links = [link("f_a", "A", "contains"), link("A", "B", "calls"), link("B", "C", "uses", "INFERRED"),
             link("R", "A", "rationale_for")]
    return {"directed": False, "multigraph": False, "graph": {}, "nodes": nodes, "links": links}


class Env:
    def __init__(self, graph=None, labels=None, name="demo"):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name) / "tenants" / "company"
        self.agent = base / "agents" / "enterprise_agent"
        self.agent.mkdir(parents=True)
        g = base / "shared" / "graphs" / name
        g.mkdir(parents=True)
        (g / "graph.json").write_text(json.dumps(graph or small_graph()), encoding="utf-8")
        if labels is not None:
            (g / ".graphify_labels.json").write_text(json.dumps(labels), encoding="utf-8")
        (base / "shared" / "secret.txt").write_text("do not read", encoding="utf-8")

    def run(self, _env=None, **payload):
        payload.setdefault("target", "")
        payload.setdefault("query", "")
        payload.setdefault("graph", "demo")
        env = {**os.environ, "IAF_AGENT_ROOT": str(self.agent), **(_env or {})}
        r = subprocess.run([sys.executable, str(TOOL)], input=json.dumps(payload), capture_output=True,
                           text=True, timeout=60, env=env, cwd=str(self.agent))
        self.last = r
        return json.loads(r.stdout)


class RegistrationTest(unittest.TestCase):
    def test_tool_spec_is_discoverable_by_the_loader(self):
        from iaf_agent_skills.tools.skill_tool_loader import discover_skill_tools
        specs = discover_skill_tools(SKILL_DIR)
        self.assertEqual([s.name for s in specs], ["graph_query"])
        self.assertEqual(set(specs[0].parameters), {"action", "graph", "query", "target"})
        self.assertLessEqual(specs[0].timeout, 60)

    def test_skill_is_indexed_and_well_formed(self):
        idx = yaml.safe_load((ROOT / "enterprise_root/tenants/company/skills/_index.yaml").read_text(encoding="utf-8"))
        self.assertIn("codebase_graph", idx["skills"])
        self.assertIn(idx["skills"]["codebase_graph"]["category"], idx["category_labels"])
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---")[1])
        self.assertEqual(fm["name"], "codebase_graph")
        self.assertEqual(fm["execution_mode"], "react")

    def test_tool_script_has_no_writes_or_network(self):
        src = TOOL.read_text(encoding="utf-8")
        for banned in ("open(", "socket", "urllib", "requests", "subprocess", "os.system", ".write_text", "shutil"):
            self.assertNotIn(banned, src, banned)


class ToolBehaviourTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(labels={"0": "Agent Core", "1": "Kernel"})
        self.addCleanup(self.env.tmp.cleanup)

    def test_stats(self):
        r = self.env.run(action="stats")
        self.assertEqual(r["nodes"], 6)
        self.assertEqual(r["relations"]["calls"], 1)
        self.assertEqual(r["largest_communities"][0][0], "Agent Core")
        self.assertEqual(r["most_connected"][0]["label"], "SkillAgent")

    def test_search_ignores_rationale_nodes(self):
        r = self.env.run(action="search", query="skill agent")
        labels = [m["label"] for m in r["matches"]]
        self.assertEqual(labels[0], "SkillAgent")
        self.assertNotIn("Doc note about SkillAgent", labels)

    def test_explain_groups_neighbours_and_keeps_confidence(self):
        r = self.env.run(action="explain", query="SafeKernel")
        self.assertEqual(r["node"]["label"], "SafeKernel")
        flat = json.dumps(r["neighbours"])
        self.assertIn("SkillAgent", flat)
        self.assertIn("INFERRED", flat)                          # B -uses-> C is a guess and says so

    def test_explain_unknown_node(self):
        self.assertIn("error", self.env.run(action="explain", query="NopeNopeNope"))

    def test_path_found_and_hops(self):
        r = self.env.run(action="path", query="SkillAgent", target="HookRunner")
        self.assertEqual(r["hops"], 2)
        self.assertEqual([s["to"] for s in r["path"]], ["SafeKernel", "HookRunner"])
        self.assertEqual(r["path"][1]["confidence"], "INFERRED")

    def test_path_not_connected(self):
        r = self.env.run(action="path", query="SkillAgent", target="Island")
        self.assertIsNone(r["path"])

    def test_path_never_routes_through_docstring_nodes(self):
        r = self.env.run(action="path", query="SkillAgent", target="SafeKernel")
        self.assertNotIn("rationale", json.dumps(r))

    def test_community_by_name_and_number(self):
        r = self.env.run(action="community", query="agent core")
        self.assertEqual(r["community"], "Agent Core")
        self.assertEqual(self.env.run(action="community", query="1")["community"], "Kernel")
        self.assertIn("error", self.env.run(action="community", query="zzz"))

    def test_bad_action_and_missing_graph(self):
        self.assertIn("action must be", self.env.run(action="drop_table")["error"])
        self.assertIn("no graph named", self.env.run(action="stats", graph="other")["error"])

    def test_graph_name_cannot_escape_the_graphs_folder(self):
        # an empty name is not an escape attempt: it selects the only published graph (test_graph_upload.py)
        for bad in ("../", "../../shared", "..\\..", "demo/../../secret", "/etc", "a b"):
            r = self.env.run(action="stats", graph=bad)
            self.assertIn("error", r, bad)
            self.assertNotIn("do not read", json.dumps(r))
            self.assertNotIn(str(self.env.agent), json.dumps(r))          # errors never leak paths

    def test_output_is_always_valid_json_even_when_large(self):
        nodes = [node(f"n{i}", f"Thing{i}", f"pkg/f{i % 50}.py", 0) for i in range(3000)]
        links = [link("n0", f"n{i}", "calls") for i in range(1, 3000)]
        env = Env(graph={"nodes": nodes, "links": links})
        self.addCleanup(env.tmp.cleanup)
        r = env.run(action="explain", query="Thing0")
        self.assertIn("node", r)                                  # lists are capped, reply stays small
        self.assertLess(len(env.last.stdout), 15000)

    def test_list_stays_valid_json_under_the_cap_with_many_long_names(self):
        env = Env()
        self.addCleanup(env.tmp.cleanup)
        base = env.agent.parents[1] / "shared" / "graphs"
        for i in range(300):
            d = base / (f"graph_{i:03d}_" + "n" * 50)
            d.mkdir()
            (d / "graph.json").write_text("{}", encoding="utf-8")
        r = env.run(action="list")
        self.assertLessEqual(len(env.last.stdout), 10000)
        self.assertEqual(r["total"], 301)
        self.assertTrue(r["truncated"])
        self.assertTrue(0 < len(r["graphs"]) < 301)
        small = Env()
        self.addCleanup(small.tmp.cleanup)
        self.assertEqual(small.run(action="list"), {"graphs": ["demo"]})

    def test_malformed_graph_file(self):
        env = Env()
        self.addCleanup(env.tmp.cleanup)
        gp = Path(env.agent).parents[1] / "shared" / "graphs" / "demo" / "graph.json"
        gp.write_text("{nope", encoding="utf-8")
        self.assertIn("not valid JSON", env.run(action="stats")["error"])
        gp.write_text(json.dumps({"hello": 1}), encoding="utf-8")
        self.assertIn("not a graphify", env.run(action="stats")["error"])

    @unittest.skipUnless((REAL / "graph.json").is_file(), "real graphify graph not present on this machine")
    def test_real_graph(self):
        env = Env(graph=json.loads((REAL / "graph.json").read_text(encoding="utf-8")),
                  labels=json.loads((REAL / ".graphify_labels.json").read_text(encoding="utf-8")), name="agentos")
        self.addCleanup(env.tmp.cleanup)
        s = env.run(action="stats", graph="agentos")
        self.assertGreater(s["nodes"], 6000)
        e = env.run(action="explain", graph="agentos", query="SkillAgent")
        self.assertEqual(e["node"]["label"], "SkillAgent")
        p = env.run(action="path", graph="agentos", query="SkillAgent", target="SafeKernel")
        self.assertIsNotNone(p["path"])


class SkillIsolationAndAccessTest(unittest.TestCase):
    def test_skill_declares_only_its_own_tool_so_it_cannot_inherit_shell_or_write_file(self):
        from iaf_agent_skills.tool_gating import tool_allowed_for_skill
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        declared = yaml.safe_load(text.split("---")[1])["tools"]
        self.assertEqual(declared, ["graph_query"])
        agent_allows = ["shell", "write_file", "query_memory"]
        for powerful in agent_allows:
            self.assertFalse(tool_allowed_for_skill(powerful, agent_allows, declared), powerful)

    def test_denied_graph_is_refused_and_looks_like_a_missing_one(self):
        env = Env()
        self.addCleanup(env.tmp.cleanup)
        self.assertEqual(env.run(action="stats")["nodes"], 6)
        denied = env.run(_env={"IAF_DENIED_GRAPHS": json.dumps(["demo"])}, action="stats")
        missing = env.run(_env={"IAF_DENIED_GRAPHS": json.dumps(["demo"])}, action="stats", graph="nope")
        self.assertIn("no graph named 'demo'", denied["error"])
        self.assertEqual(denied["error"].replace("demo", "X"), missing["error"].replace("nope", "X"))
        self.assertEqual(env.run(_env={"IAF_DENIED_GRAPHS": json.dumps(["other"])}, action="stats")["nodes"], 6)

    def test_wildcard_and_garbage_denylists_deny_everything(self):
        env = Env()
        self.addCleanup(env.tmp.cleanup)
        for value in (json.dumps(["*"]), "{not json", json.dumps({"demo": 1})):
            with self.subTest(value=value):
                self.assertIn("no graph named", env.run(_env={"IAF_DENIED_GRAPHS": value}, action="stats")["error"])

    def test_tool_env_only_accepts_iaf_keys(self):
        from iaf_agent_skills.tools.skill_tool_loader import _tool_env
        env = _tool_env("/x", {"IAF_DENIED_GRAPHS": "[]", "PATH": "evil", "PYTHONPATH": "evil",
                               "IAF_AGENT_ROOT": "evil", "IAF_N": 5})
        self.assertEqual(env["IAF_DENIED_GRAPHS"], "[]")
        self.assertEqual(env["IAF_AGENT_ROOT"], "/x")
        self.assertNotEqual(env.get("PATH"), "evil")
        self.assertNotEqual(env.get("PYTHONPATH"), "evil")
        self.assertNotIn("IAF_N", env)


class AgentGraphDenylistTest(unittest.TestCase):
    """SkillAgent resolves the caller's graph access and hands the tool the denied folders."""

    @staticmethod
    def _res(rid, path="", type_="graph"):
        from agent_os.external_access import ExternalResource
        return ExternalResource(id=rid, type=type_, metadata={"engine": "graphify", "path": path})

    def _call(self, resources, *, enabled=True, checker=True, allow=(), remote=False):
        """remote=True models RemoteKernelRuntime: no governance flag, checker or per-resource
        check on the kernel at all, so the agent's own entitlement context is all there is."""
        import types
        from iaf_agent_skills.agent import SkillAgent
        seen = []

        def decide(action, rtype, rid, ctx):
            seen.append((f"{rtype}:{rid}", action))
            return f"{rtype}:{rid}" in allow

        agent = SkillAgent.__new__(SkillAgent)
        agent.user_id = "u"
        agent.entitlement_checker = decide if checker else None
        if remote:
            agent.kernel = types.SimpleNamespace(tenant_root=Path("x"))
        else:
            agent.kernel = types.SimpleNamespace(
                external_access_enabled=enabled, tenant_root=Path("x"),
                entitlement_checker=agent.entitlement_checker,
                _external_resource_allowed=lambda res, action, ctx: decide(action, res.resource_type, res.resource_id, ctx))
        flag = {"EXTERNAL_ACCESS_ENABLED": "true" if enabled else "false"}
        with mock.patch.dict(os.environ, flag), \
                mock.patch("agent_os.external_access.list_external_resources", lambda root: resources):
            return SkillAgent._graph_denylist_env(agent, "codebase_graph"), seen

    def test_remote_kernel_backend_is_governed_by_the_agents_own_entitlements(self):
        a = self._res("external:graph.repo", "/shared/graphs/repo/graph.json")
        b = self._res("external:graph.hr", "/shared/graphs/hr/graph.json")
        env, _ = self._call([a, b], remote=True, allow={"external:graph.hr"})
        self.assertEqual(json.loads(env["IAF_DENIED_GRAPHS"]), ["repo"])
        self.assertEqual(self._call([a], remote=True, enabled=False)[0], {})           # flag off: nothing to enforce
        self.assertEqual(json.loads(self._call([a], remote=True, checker=False)[0]["IAF_DENIED_GRAPHS"]), ["*"])

    def test_every_spelling_of_a_denied_path_denies_the_folder(self):
        for path in ("/shared/graphs/hr/graph.json", "/shared/graphs/hr/./graph.json",
                     "/shared/graphs//hr/graph.json", "/shared/graphs/./hr//graph.json"):
            with self.subTest(path=path):
                env, _ = self._call([self._res("external:graph.hr", path)])
                self.assertEqual(json.loads(env["IAF_DENIED_GRAPHS"]), ["hr"])

    def test_denied_connection_folder_is_listed_allowed_one_is_not(self):
        a = self._res("external:graph.repo", "/shared/graphs/repo/graph.json")
        b = self._res("external:graph.hr", "/shared/graphs/hr/graph.json")
        env, seen = self._call([a, b], allow={"external:graph.hr"})
        self.assertEqual(json.loads(env["IAF_DENIED_GRAPHS"]), ["repo"])
        self.assertEqual(seen, [("external:graph.repo", "access"), ("external:graph.hr", "access")])

    def test_nothing_to_enforce_returns_empty(self):
        a = self._res("external:graph.repo", "/shared/graphs/repo/graph.json")
        self.assertEqual(self._call([a], allow={"external:graph.repo"})[0], {})
        self.assertEqual(self._call([])[0], {})
        self.assertEqual(self._call([self._res("external:http.x", type_="http")])[0], {})
        self.assertEqual(self._call([a], enabled=False)[0], {})                       # governance off

    def test_governance_on_without_a_principal_fails_closed(self):
        a = self._res("external:graph.repo", "/shared/graphs/repo/graph.json")
        self.assertEqual(json.loads(self._call([a], checker=False)[0]["IAF_DENIED_GRAPHS"]), ["*"])

    def test_registry_read_failure_fails_closed(self):
        import types
        from iaf_agent_skills.agent import SkillAgent
        kernel = types.SimpleNamespace(external_access_enabled=True, tenant_root=Path("x"))
        with mock.patch("agent_os.external_access.list_external_resources", side_effect=RuntimeError("boom")):
            env = SkillAgent._graph_denylist_env(types.SimpleNamespace(kernel=kernel), "codebase_graph")
        self.assertEqual(json.loads(env["IAF_DENIED_GRAPHS"]), ["*"])


class BundledToolLoadingTest(unittest.TestCase):
    """How SkillAgent hands graph access to bundled tools, whichever provider loads them."""

    def setUp(self):
        import types
        from agent_os.external_access import ExternalResource
        from iaf_agent_skills.agent import SkillAgent
        self.allowed = True
        self.agent = SkillAgent.__new__(SkillAgent)
        self.agent.user_id = "u"
        self.agent.entitlement_checker = lambda action, rtype, rid, ctx: self.allowed
        self.agent.kernel = types.SimpleNamespace(tenant_root=Path("x"), agent_root="")
        res = [ExternalResource(id="external:graph.hr", type="graph",
                                metadata={"engine": "graphify", "path": "/shared/graphs/hr/graph.json"})]
        for patcher in (mock.patch.dict(os.environ, {"EXTERNAL_ACCESS_ENABLED": "true"}),
                        mock.patch("agent_os.external_access.list_external_resources", lambda root: res)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _load(self, provider):
        import types
        self.agent.tool_provider = provider
        return self.agent._load_bundled_tools(types.SimpleNamespace(path=Path("skill")), "codebase_graph")

    def test_access_is_resolved_when_the_tool_runs_not_when_it_is_loaded(self):
        seen = []

        class Provider:
            def load_skill_tools(self, skill_path, agent_root=None, env_extra=None):
                seen.append(env_extra)
                return [types_ns(name="graph_query")]

        self._load(Provider())
        resolve = seen[0]
        self.assertTrue(callable(resolve))
        self.assertEqual(resolve(), {})                                   # entitled when loaded
        self.allowed = False                                              # access revoked afterwards
        self.assertEqual(json.loads(resolve()["IAF_DENIED_GRAPHS"]), ["hr"])

    def test_legacy_provider_keeps_unrelated_tools_but_never_serves_graphs(self):
        class Legacy:
            def load_skill_tools(self, skill_path):
                return [types_ns(name="graph_query"), types_ns(name="summarise")]

        self.assertEqual([t.name for t in self._load(Legacy())], ["summarise"])

    def test_legacy_provider_is_untouched_when_graph_governance_is_off(self):
        class Legacy:
            def load_skill_tools(self, skill_path):
                return [types_ns(name="graph_query"), types_ns(name="summarise")]

        with mock.patch.dict(os.environ, {"EXTERNAL_ACCESS_ENABLED": "false"}):
            self.assertEqual([t.name for t in self._load(Legacy())], ["graph_query", "summarise"])


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


class PerCallToolEnvTest(unittest.TestCase):
    """create_skill_tool re-resolves per-caller context on every run, through a real subprocess."""

    def test_callable_env_extra_is_evaluated_on_each_invocation(self):
        from iaf_agent_skills.tools.skill_tool_loader import load_skill_tools
        with tempfile.TemporaryDirectory() as d:
            tools = Path(d) / "tools"
            tools.mkdir()
            (tools / "echo_env.py").write_text(
                'import os, json, sys\n'
                'TOOL_SPEC = {"name": "echo_env", "description": "d", "parameters": {}}\n'
                'sys.stdin.read()\n'
                'print(json.dumps({"denied": os.environ.get("IAF_DENIED_GRAPHS")}))\n', encoding="utf-8")
            state = {"denied": None}
            tool = load_skill_tools(Path(d), env_extra=lambda: (
                {"IAF_DENIED_GRAPHS": state["denied"]} if state["denied"] else {}))[0]
            self.assertIsNone(json.loads(tool.invoke({}))["denied"])
            state["denied"] = '["hr"]'
            self.assertEqual(json.loads(tool.invoke({}))["denied"], '["hr"]')
            state["denied"] = None
            self.assertIsNone(json.loads(tool.invoke({}))["denied"])

    def test_a_failing_resolver_fails_closed_and_keeps_the_tool_from_running(self):
        from iaf_agent_skills.tools.skill_tool_loader import load_skill_tools
        with tempfile.TemporaryDirectory() as d:
            tools = Path(d) / "tools"
            tools.mkdir()
            marker = Path(d) / "ran"
            (tools / "touch.py").write_text(
                'import sys, pathlib\n'
                'TOOL_SPEC = {"name": "touch", "description": "d", "parameters": {}}\n'
                f'pathlib.Path({str(marker)!r}).write_text("x")\n', encoding="utf-8")

            def boom():
                raise RuntimeError("registry down")

            out = json.loads(load_skill_tools(Path(d), env_extra=boom)[0].invoke({}))
            self.assertIn("error", out)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
