"""Studio side of taxonomy graph import.

Pins the contract that matters end to end: a draft built from a (hostile) external
graph, once its skills are assigned and it is committed through the existing
``/taxonomy-import`` JSON path, must parse back through ``TaxonomySignalIndex`` as
exactly the intended L1/L2/L3 + skill tree -- with nothing forged by node labels --
and unassigned sections must never be committable.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills", ROOT / "IAF-Agent-Studio",
          ROOT / "IAF-Agent-Skills" / "iaf_agent_skills", ROOT / "IAF-Agent-Skills" / "tests"):
    sys.path.insert(0, str(p))

from routers import context_manager as cm  # noqa: E402
from taxonomy_signal_index import _parse_file  # noqa: E402
from agentos_contracts.graph_source import GraphEdge, GraphNode, GraphSnapshot  # noqa: E402
from iaf_agent_skills import graph_import as gi  # noqa: E402
from iaf_agent_skills.graph_import import neo4j_adapter  # noqa: E402
from test_graph_import import FakeGraph, neo4j_client  # noqa: E402

HOSTILE = {
    "r": "Ops: Platform [core]",
    "d1": "### Injected heading",
    "d2": "Normal\n#### Forged L3\n<!-- skill: admin -->",
    "s1": "- bullet <!-- skill: admin --> name",
    "s2": "Real Section",
    "t1": "`task` with <b>html</b>",
}
EDGES = [("r", "d1"), ("r", "d2"), ("d1", "s1"), ("d2", "s2"), ("s2", "t1")]


def hostile_draft():
    nodes = {k: GraphNode(id=k, name=v) for k, v in HOSTILE.items()}
    snap = GraphSnapshot(root=nodes["r"], nodes=nodes, edges=[GraphEdge(a, b) for a, b in EDGES])
    return gi.map_snapshot(snap)


def commit_payload(draft, skill="ccdops", provenance=None):
    d = draft.to_dict()
    for dom in d["domains"]:
        for sec in dom["sections"]:
            sec["skill"] = skill
    body = {"name": d["name"], "description": d["description"], "domains": d["domains"]}
    if provenance is not None:
        body["source"] = provenance
    return json.dumps(body)


class CommitRoundTripTest(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(cm, "_valid_skill_names", return_value={"ccdops", "ap_ops"})
        self._p.start()
        self.addCleanup(self._p.stop)

    def _parse(self, md):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.md"
            f.write_text(md, encoding="utf-8")
            return _parse_file(f), f.read_text(encoding="utf-8")

    def test_hostile_labels_cannot_forge_structure_or_skills(self):
        draft = hostile_draft()
        name, md, skills = cm._import_from_json(commit_payload(draft), "", "tester")
        sections, text = self._parse(md)

        self.assertEqual(skills, ["ccdops"])
        self.assertNotIn("<!-- skill: admin", text)
        self.assertEqual(text.count("<!-- skill:"), len(sections))
        self.assertEqual(len(sections), 2)                       # exactly the two real sections
        self.assertTrue(all(s["skill"] == "ccdops" for s in sections))
        self.assertTrue(all(s["l1"] == name for s in sections))
        # frontmatter survived a colon / brackets in the root label
        fm = yaml.safe_load(text.split("---")[1])
        self.assertEqual(fm["name"], name)
        self.assertNotIn("admin", [s["skill"] for s in sections])

    def test_unassigned_sections_are_rejected_on_commit(self):
        draft = hostile_draft().to_dict()
        payload = json.dumps({"name": draft["name"], "domains": draft["domains"]})   # skills still blank
        with self.assertRaises(HTTPException) as c:
            cm._import_from_json(payload, "", "tester")
        self.assertEqual(c.exception.status_code, 422)

    def test_partially_assigned_is_still_rejected(self):
        d = hostile_draft().to_dict()
        d["domains"][0]["sections"][0]["skill"] = "ccdops"       # others remain blank
        with self.assertRaises(HTTPException):
            cm._import_from_json(json.dumps({"name": d["name"], "domains": d["domains"]}), "", "tester")

    def test_unknown_skill_rejected(self):
        with self.assertRaises(HTTPException) as c:
            cm._import_from_json(commit_payload(hostile_draft(), skill="not_a_skill"), "", "tester")
        self.assertEqual(c.exception.status_code, 422)

    def test_provenance_written_and_constrained(self):
        prov = {
            "source_connection": "external:graph.corp",
            "source_engine": "neo4j",
            "source_root": "Domain:Enterprise Ops",
            "imported_at": "2026-10-16T06:07:42Z",
            "created_by": "evil@example.com",                  # not an allowed key
            "status": "deleted",                               # not an allowed key
        }
        _, md, _ = cm._import_from_json(commit_payload(hostile_draft(), provenance=prov), "", "tester")
        fm = yaml.safe_load(md.split("---")[1])
        self.assertEqual(fm["source_connection"], "external:graph.corp")
        self.assertEqual(fm["source_engine"], "neo4j")
        self.assertEqual(fm["created_by"], "tester")
        self.assertEqual(fm["status"], "active")

    def test_provenance_values_cannot_break_frontmatter(self):
        prov = {"source_connection": "x\n---\nname: pwned\n<!-- skill: admin -->", "source_engine": "neo4j"}
        _, md, _ = cm._import_from_json(commit_payload(hostile_draft(), provenance=prov), "", "tester")
        head = md.split("\n---\n")[0]
        self.assertEqual(md.splitlines().count("---"), 2)         # opening + closing only
        fm = yaml.safe_load(head.removeprefix("---\n"))           # still valid YAML
        self.assertNotEqual(fm["name"], "pwned")
        self.assertEqual(fm["type"], "taxonomy")
        self.assertNotIn("<!--", head)

    def test_plain_import_without_provenance_unchanged(self):
        _, md, _ = cm._import_from_json(commit_payload(hostile_draft()), "", "tester")
        self.assertNotIn("source_connection", md)


class ScalarLookingNamesTest(unittest.TestCase):
    """A name YAML would retype (`2026`, `true`, a date) must survive write -> index parse."""

    NAMES = ["2026", "true", "null", "1e3", "2026-01-01", "0x1F", "HR: Payroll", "yes"]

    def test_taxonomy_name_round_trips_through_the_indexer_parser(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                domain = cm.TaxonomyDomainSpec(
                    name="Ops", sections=[cm.TaxonomySectionSpec(name="Incidents", skill="ccdops")])
                md = cm._build_taxonomy_md(name, "", ["ccdops"], [domain], "tester")
                with tempfile.TemporaryDirectory() as d:
                    f = Path(d) / "t.md"
                    f.write_text(md, encoding="utf-8")
                    sections = _parse_file(f)
                self.assertEqual([s["l1"] for s in sections], [name])
                self.assertEqual(cm._fm_fields(md)["name"], name)          # the router's own readers agree

    def test_provenance_values_stay_strings(self):
        md = cm._build_taxonomy_md("T", "", [], [], "tester", provenance={
            "source_connection": "external:graph.x", "source_root": "2026", "imported_at": "2026-10-16T06:07:42Z"})
        fm = yaml.safe_load(md.split("---")[1])
        self.assertEqual(fm["source_root"], "2026")
        self.assertEqual(fm["imported_at"], "2026-10-16T06:07:42Z")


class PreviewEndpointTest(unittest.TestCase):
    NEO = {"id": "external:graph.local", "type": "graph", "label": "Local Neo4j", "engine": "neo4j",
           "hosts": ["127.0.0.1:443"], "auth": "basic", "credentials": ["neo_local"]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        tenant = base / "data" / "tenants" / "company"
        (tenant / "security").mkdir(parents=True)
        (tenant / "security" / "external_access.yaml").write_text(
            yaml.safe_dump({"version": "1.0", "resources": [self.NEO]}))
        self.tenant = tenant
        for target, value in (("SERVER_DIR", base), ("DATA_ROOT", "data")):
            p = mock.patch.object(cm, target, value)
            p.start()
            self.addCleanup(p.stop)
        for target, value in (
            ("bind_request_identity", lambda *a, **k: ("principal", "company", "enterprise_agent", "tester")),
            ("enforce_entitlement", lambda *a, **k: None),
            ("_owner_identity", lambda r: "tester@example.com"),
            ("_skills_index_entries", lambda: {"ccdops": {"description": "Kubernetes cluster operations", "keywords": ["k8s"]}}),
            ("_graph_credential_lookup", lambda t, r: (lambda n: type("C", (), {"value": {"username": "u", "password": "p"}})())),
        ):
            p = mock.patch.object(cm, target, value)
            p.start()
            self.addCleanup(p.stop)

    def _req(self, **kw):
        base = dict(connection_id="external:graph.local", root_label="Domain",
                    root_name="Enterprise Ops", edge_type="PARENT_OF")
        base.update(kw)
        return cm.TaxonomyGraphPreviewRequest(**base)

    def _call(self, req, client):
        with mock.patch.object(neo4j_adapter, "new_client", return_value=client):
            return asyncio.run(cm.taxonomy_graph_preview_endpoint(req, mock.Mock(), {}))

    def test_preview_returns_draft_and_writes_nothing_but_audit(self):
        out = self._call(self._req(), neo4j_client(FakeGraph()))
        self.assertEqual(out["stats"]["domains"], 2)
        self.assertEqual(out["unmapped_sections"], out["stats"]["sections"])
        self.assertEqual(out["connection"]["label"], "Local Neo4j")
        self.assertNotIn("127.0.0.1", json.dumps(out))
        self.assertFalse((self.tenant / "shared" / "contexts").exists())          # no taxonomy file
        audit = (self.tenant / "shared" / "databases" / "external_access_audit.jsonl").read_text()
        entry = json.loads(audit.splitlines()[-1])
        self.assertEqual((entry["action"], entry["allowed"], entry["user_id"]),
                         ("graph_import_preview", True, "tester@example.com"))
        self.assertNotIn("p", entry["metadata"])

    def test_preview_requires_entitlement_on_the_selected_connection(self):
        seen = []

        def deny(principal, action, rtype, rid, context=None):
            seen.append((action, rtype, rid))
            raise HTTPException(403, "policy says no")

        creds = mock.Mock(side_effect=AssertionError("credential must not be resolved when access is denied"))
        with mock.patch.object(cm, "enforce_entitlement", deny),                 mock.patch.object(cm, "_graph_credential_lookup", creds):
            with self.assertRaises(HTTPException) as c:
                self._call(self._req(), neo4j_client(FakeGraph()))
        self.assertEqual(c.exception.status_code, 403)
        self.assertEqual(seen, [("access", "external", "graph.local")])      # same resource the runtime checks
        creds.assert_not_called()
        entry = json.loads((self.tenant / "shared" / "databases" / "external_access_audit.jsonl")
                           .read_text().splitlines()[-1])
        self.assertEqual((entry["action"], entry["allowed"], entry["reason"]),
                         ("graph_import_preview", False, "access_denied"))

    def test_connection_list_hides_connections_the_caller_cannot_access(self):
        def deny(principal, action, rtype, rid, context=None):
            raise HTTPException(403, "no")

        got = asyncio.run(cm.taxonomy_graph_connections_endpoint(mock.Mock(), "company", {}))
        self.assertEqual([c["id"] for c in got["connections"]], ["external:graph.local"])
        with mock.patch.object(cm, "enforce_entitlement", deny):
            got = asyncio.run(cm.taxonomy_graph_connections_endpoint(mock.Mock(), "company", {}))
        self.assertEqual(got["connections"], [])

    def test_unknown_connection_is_404_before_any_entitlement_check(self):
        with mock.patch.object(cm, "enforce_entitlement", side_effect=AssertionError("not reached")):
            with self.assertRaises(HTTPException) as c:
                self._call(self._req(connection_id="external:graph.nope"), neo4j_client(FakeGraph()))
        self.assertEqual(c.exception.status_code, 404)

    def test_preview_payload_budget_matches_the_import_limit(self):
        from iaf_agent_skills.graph_import.mapper import IMPORT_PAYLOAD_MAX_BYTES
        self.assertEqual(IMPORT_PAYLOAD_MAX_BYTES, cm._TAXONOMY_IMPORT_MAX_BYTES)

    def test_errors_map_to_safe_http_errors(self):
        with self.assertRaises(HTTPException) as c:
            self._call(self._req(connection_id="external:graph.nope"), neo4j_client(FakeGraph()))
        self.assertEqual(c.exception.status_code, 404)
        with self.assertRaises(HTTPException) as c:
            self._call(self._req(root_label="Bad Label`"), neo4j_client(FakeGraph()))
        self.assertEqual(c.exception.status_code, 400)
        with self.assertRaises(HTTPException) as c:
            self._call(self._req(root_name="Missing"), neo4j_client(FakeGraph()))
        self.assertEqual(c.exception.status_code, 404)
        with self.assertRaises(HTTPException) as c:
            self._call(self._req(), neo4j_client(FakeGraph(), status=401))
        self.assertEqual(c.exception.status_code, 502)
        self.assertNotIn("127.0.0.1", str(c.exception.detail))
        lines = (self.tenant / "shared" / "databases" / "external_access_audit.jsonl").read_text().splitlines()
        self.assertTrue(all(json.loads(l)["allowed"] is False for l in lines))

    def test_connections_listing(self):
        out = asyncio.run(cm.taxonomy_graph_connections_endpoint(mock.Mock(), "company", {}))
        self.assertEqual(out["connections"][0]["id"], "external:graph.local")
        self.assertNotIn("host", out["connections"][0])
        self.assertNotIn("neo_local", json.dumps(out))




class TenantCredentialResolverTest(unittest.TestCase):
    """The deployment tenant's resolver must never serve another tenant's preview."""

    def setUp(self):
        from iaf_agent_skills.capability_registry import CapabilityRegistry
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg = CapabilityRegistry()
        self.default = object()
        self.reg.register("credential_resolver", self.default, implementation="Default")
        for target, value in (("SERVER_DIR", Path(self.tmp.name)), ("DATA_ROOT", "data")):
            p = mock.patch.object(cm, target, value)
            p.start()
            self.addCleanup(p.stop)
        for target, value in (("shared.state.capability_registry", self.reg), ("shared.config.TENANT_ID", "company")):
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def test_deployment_tenant_uses_the_default_resolver(self):
        self.assertIs(cm._tenant_credential_resolver("company"), self.default)

    def test_other_tenant_never_gets_the_deployment_tenants_resolver(self):
        got = cm._tenant_credential_resolver("acme")
        self.assertIsNot(got, self.default)
        self.assertEqual(Path(got._config_dir),
                         Path(self.tmp.name) / "data" / "tenants" / "acme" / "shared" / "config")

    def test_explicit_tenant_override_wins(self):
        override = object()
        self.reg.register_tenant_override("acme", "credential_resolver", override)
        self.assertIs(cm._tenant_credential_resolver("acme"), override)

    def test_lookup_resolves_through_the_requested_tenants_resolver(self):
        seen = {}

        class R:
            def resolve(self, name, **kw):
                seen.update(name=name, **kw)
                return "cred"

        self.reg.register_tenant_override("acme", "credential_resolver", R())
        with mock.patch.object(cm, "_owner_identity", lambda r: "tester@example.com"):
            lookup = cm._graph_credential_lookup("acme", mock.Mock())
        self.assertEqual(lookup("neo_local"), "cred")
        self.assertEqual((seen["name"], seen["consumer"], seen["accessor"]),
                         ("neo_local", "taxonomy_graph_import", "tester@example.com"))


if __name__ == "__main__":
    unittest.main()
