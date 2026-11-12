"""Upload a graph/ontology JSON through the Studio endpoints, then query it with the
`graph_query` tool exactly the way the skill loader runs it (subprocess, IAF_AGENT_ROOT)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills", ROOT / "IAF-Agent-Studio"):
    sys.path.insert(0, str(p))

from routers import context_manager as cm  # noqa: E402

TOOL = ROOT / "enterprise_root" / "tenants" / "company" / "skills" / "codebase_graph" / "tools" / "graph_query.py"

ONTOLOGY = {
    "entities": [
        {"id": "ingress", "name": "Ingress Gateway", "type": "Component", "description": "Public entry point for 5xx and routing issues"},
        {"id": "dns", "name": "CoreDNS", "type": "Component", "description": "Resolves service names inside the cluster"},
        {"id": "pod", "name": "Pod", "type": "Workload"},
        {"id": "svc", "name": "Service", "type": "Workload"},
        {"id": "lonely", "name": "Island", "type": "Workload"},
    ],
    "relationships": [
        {"from": "ingress", "to": "svc", "type": "routes_to"},
        {"from": "svc", "to": "pod", "type": "selects"},
        {"from": "pod", "to": "dns", "type": "depends_on"},
    ],
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.tenant = self.base / "data" / "tenants" / "company"
        (self.tenant / "agents" / "enterprise_agent").mkdir(parents=True)
        for target, value in (("SERVER_DIR", self.base), ("DATA_ROOT", "data"),
                              ("bind_request_identity", lambda *a, **k: None),
                              ("_owner_identity", lambda r: "tester@example.com")):
            pt = mock.patch.object(cm, target, value)
            pt.start()
            self.addCleanup(pt.stop)

    def upload(self, name="it_ops", doc=ONTOLOGY, overwrite=False, content=None):
        req = cm.GraphUploadRequest(name=name, content=content if content is not None else json.dumps(doc),
                                    overwrite=overwrite)
        return asyncio.run(cm.graph_upload_endpoint(req, mock.Mock(), {}))

    def library(self):
        return asyncio.run(cm.graph_library_endpoint(mock.Mock(), "company", {}))["graphs"]

    def delete(self, name):
        return asyncio.run(cm.graph_delete_endpoint(cm.GraphDeleteRequest(name=name), mock.Mock(), {}))

    def query(self, _env=None, **payload):
        payload.setdefault("target", "")
        payload.setdefault("query", "")
        payload.setdefault("graph", "")
        env = {**os.environ, "IAF_AGENT_ROOT": str(self.tenant / "agents" / "enterprise_agent"), **(_env or {})}
        r = subprocess.run([sys.executable, str(TOOL)], input=json.dumps(payload), capture_output=True,
                           text=True, timeout=60, env=env)
        return json.loads(r.stdout)

    def audit_lines(self):
        f = self.tenant / "shared" / "databases" / "external_access_audit.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


class EndpointTest(Fixture):
    def test_upload_reports_what_was_understood_and_lists_it(self):
        out = self.upload()
        self.assertTrue(out["ok"])
        self.assertEqual((out["nodes"], out["edges"], out["format"]), (5, 3, "ontology"))
        self.assertEqual(out["example"], "Service")        # tied for most connected; first by degree order
        self.assertIn("routes_to", out["relations"])
        got = self.library()
        self.assertEqual([(g["name"], g["nodes"], g["edges"]) for g in got], [("it_ops", 5, 3)])

    def test_errors_map_to_http_without_leaking_paths(self):
        for kwargs, status in (({"name": "../x"}, 422), ({"content": "{nope"}, 422), ({"doc": {"foo": 1}}, 422)):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(HTTPException) as c:
                    self.upload(**kwargs)
                self.assertEqual(c.exception.status_code, status)
                self.assertNotIn(str(self.base), str(c.exception.detail))
        self.upload()
        with self.assertRaises(HTTPException) as c:
            self.upload()
        self.assertEqual(c.exception.status_code, 409)
        self.upload(overwrite=True)

    def test_delete(self):
        self.upload()
        self.assertEqual(self.delete("it_ops"), {"ok": True})
        self.assertEqual(self.library(), [])
        with self.assertRaises(HTTPException) as c:
            self.delete("it_ops")
        self.assertEqual(c.exception.status_code, 404)

    def test_actions_are_audited(self):
        self.upload()
        with self.assertRaises(HTTPException):
            self.upload(name="bad name")
        self.delete("it_ops")
        got = [(e["action"], e["resource"], e["allowed"]) for e in self.audit_lines()]
        self.assertEqual(got, [("graph_upload", "it_ops", True), ("graph_upload", "bad name", False),
                               ("graph_delete", "it_ops", True)])

    def test_endpoints_require_skills_author(self):
        # the permission is declared on the route's dependencies, not just trusted to the UI
        for route in ("/graph-library", "/graph-upload", "/graph-delete"):
            r = next(x for x in cm.router.routes if x.path.endswith(route))
            self.assertTrue(r.dependant.dependencies, route)


class QueryUploadedGraphTest(Fixture):
    def setUp(self):
        super().setUp()
        self.upload()

    def test_list_and_default_to_the_only_graph(self):
        self.assertEqual(self.query(action="list"), {"graphs": ["it_ops"]})
        self.assertEqual(self.query(action="stats")["nodes"], 5)      # graph name left empty

    def test_several_graphs_need_a_name(self):
        self.upload(name="second", doc={"nodes": [{"id": "x"}], "edges": []})
        out = self.query(action="stats")
        self.assertIn("it_ops", out["error"])
        self.assertIn("second", out["error"])
        self.assertEqual(self.query(action="stats", graph="second")["nodes"], 1)

    def test_unknown_graph_names_the_published_ones(self):
        out = self.query(action="stats", graph="nope")
        self.assertIn("published: it_ops", out["error"])

    def test_stats_work_for_non_code_nodes(self):
        out = self.query(action="stats", graph="it_ops")
        self.assertEqual(out["edges"], 3)
        self.assertEqual(out["node_types"], {"Component": 2, "Workload": 3})
        self.assertTrue(out["most_connected"])                        # used to be code-only
        self.assertEqual(out["relations"].get("depends_on"), 1)

    def test_search_uses_descriptions(self):
        out = self.query(action="search", graph="it_ops", query="5xx routing")
        self.assertEqual(out["matches"][0]["label"], "Ingress Gateway")
        self.assertIn("Public entry point", out["matches"][0]["description"])

    def test_explain_shows_relations(self):
        out = self.query(action="explain", graph="it_ops", query="Service")
        self.assertEqual(out["node"]["label"], "Service")
        self.assertIn("selects (->)", out["neighbours"])
        self.assertIn("routes_to (<-)", out["neighbours"])

    def test_path_between_entities(self):
        out = self.query(action="path", graph="it_ops", query="Ingress Gateway", target="CoreDNS")
        self.assertEqual(out["hops"], 3)
        self.assertEqual([s["relation"] for s in out["path"]], ["routes_to", "selects", "depends_on"])

    def test_path_with_no_connection(self):
        out = self.query(action="path", graph="it_ops", query="Island", target="CoreDNS")
        self.assertIsNone(out["path"])

    def test_a_graph_the_caller_is_denied_is_neither_listed_nor_defaulted_nor_revealed(self):
        self.upload(name="second", doc={"nodes": [{"id": "x"}], "edges": []})
        deny = {"IAF_DENIED_GRAPHS": json.dumps(["it_ops"])}
        self.assertEqual(self.query(_env=deny, action="list"), {"graphs": ["second"]})
        self.assertEqual(self.query(_env=deny, action="stats")["nodes"], 1)          # only "second" is left: default
        denied = self.query(_env=deny, action="stats", graph="it_ops")
        missing = self.query(_env=deny, action="stats", graph="nope")
        self.assertEqual(denied["error"].replace("it_ops", "X"), missing["error"].replace("nope", "X"))
        self.assertNotIn("it_ops", missing["error"])
        everything = {"IAF_DENIED_GRAPHS": json.dumps(["*"])}
        self.assertEqual(self.query(_env=everything, action="list"), {"graphs": []})

    def test_deleted_graph_is_gone_for_the_tool(self):
        self.delete("it_ops")
        self.assertEqual(self.query(action="list"), {"graphs": []})
        self.assertIn("none is published", self.query(action="stats")["error"])


if __name__ == "__main__":
    unittest.main()
