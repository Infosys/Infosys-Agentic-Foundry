"""Studio side of the graphify engine: the preview endpoint, and the end-to-end
guarantee that a graph full of hostile labels, once skills are assigned and committed
through /taxonomy-import, parses back as exactly the intended tree (nothing forged)."""
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
          ROOT / "IAF-Agent-Skills" / "iaf_agent_skills"):
    sys.path.insert(0, str(p))

from routers import context_manager as cm  # noqa: E402
from taxonomy_signal_index import _parse_file  # noqa: E402
from iaf_agent_skills.graph_import import preview_taxonomy  # noqa: E402

RES = {"id": "external:graph.repo", "type": "graph", "engine": "graphify", "label": "Code graph",
       "path": "/shared/graphs/repo/graph.json"}


def hostile_graph():
    def n(i, label, src, comm, ft="code"):
        return {"id": i, "label": label, "file_type": ft, "source_file": src, "source_location": "L1", "community": comm}
    nodes = [
        n("f1", "a.py", "pkg/a.py", 0),
        n("s1", "### Injected heading", "pkg/a.py", 0),
        n("s2", "ok_func()\n#### Forged L3\n<!-- skill: admin -->", "pkg/a.py", 0),
        n("s3", "- bullet <!-- skill: admin --> sym", "pkg/a.py", 0),
        n("s4", "Real()", "pkg/b-->.py", 1),
        n("s5", "other()", "pkg/b-->.py", 1),
        n("s6", "third()", "pkg/b-->.py", 1),
    ]
    return {"directed": False, "multigraph": False, "graph": {}, "nodes": nodes, "links": []}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.tenant = self.base / "data" / "tenants" / "company"
        (self.tenant / "security").mkdir(parents=True)
        (self.tenant / "security" / "external_access.yaml").write_text(
            yaml.safe_dump({"version": "1.0", "resources": [RES]}))
        g = self.tenant / "shared" / "graphs" / "repo"
        g.mkdir(parents=True)
        (g / "graph.json").write_text(json.dumps(hostile_graph()), encoding="utf-8")
        (g / ".graphify_labels.json").write_text(json.dumps({"0": "Core <!-- skill: admin --> Area", "1": "Second"}))
        for target, value in (("SERVER_DIR", self.base), ("DATA_ROOT", "data")):
            pt = mock.patch.object(cm, target, value)
            pt.start()
            self.addCleanup(pt.stop)
        for target, value in (
            ("bind_request_identity", lambda *a, **k: ("principal", "company", "enterprise_agent", "tester")),
            ("enforce_entitlement", lambda *a, **k: None),
            ("_owner_identity", lambda r: "tester@example.com"),
            ("_skills_index_entries", lambda: {"ccdops": {"description": "pkg core area", "keywords": []}}),
            ("_graph_credential_lookup", lambda t, r: (lambda n: self.fail("graphify needs no credential"))),
            ("_valid_skill_names", lambda: {"ccdops"}),
        ):
            pt = mock.patch.object(cm, target, value)
            pt.start()
            self.addCleanup(pt.stop)

    def preview(self, **params):
        req = cm.TaxonomyGraphPreviewRequest(connection_id="external:graph.repo", **params)
        return asyncio.run(cm.taxonomy_graph_preview_endpoint(req, mock.Mock(), {}))


class PreviewEndpointTest(Fixture):
    def test_preview_without_root_or_relationship_fields(self):
        out = self.preview(mode="community", min_size=1)
        self.assertEqual(out["stats"]["domains"], 2)
        self.assertEqual(out["connection"]["engine"], "graphify")
        self.assertEqual(out["provenance"]["source_engine"], "graphify")
        self.assertNotIn("graphs", json.dumps(out["connection"]))
        self.assertEqual(out["unmapped_sections"], out["stats"]["sections"])

    def test_max_nodes_default_is_engine_specific(self):
        self.assertIsNone(cm.TaxonomyGraphPreviewRequest(connection_id="x").max_nodes)

    def test_errors_map_to_http(self):
        with self.assertRaises(HTTPException) as c:
            self.preview(mode="bogus")
        self.assertEqual(c.exception.status_code, 400)
        with self.assertRaises(HTTPException) as c:
            self.preview(mode="path", path_prefix="../../etc")
        self.assertEqual(c.exception.status_code, 400)
        with self.assertRaises(HTTPException) as c:
            self.preview(mode="path", path_prefix="nothing/here")
        self.assertEqual(c.exception.status_code, 404)
        self.assertNotIn(str(self.base), str(c.exception.detail))

    def test_audit_written_for_graphify_preview(self):
        self.preview(mode="path")
        line = (self.tenant / "shared" / "databases" / "external_access_audit.jsonl").read_text().splitlines()[-1]
        e = json.loads(line)
        self.assertEqual((e["action"], e["resource"], e["allowed"]), ("graph_import_preview", "external:graph.repo", True))


class HostileGraphCommitTest(Fixture):
    def test_hostile_labels_cannot_forge_structure_or_skills(self):
        out = self.preview(mode="community", min_size=1)
        doc = {"name": out["name"], "description": out["description"], "source": out["provenance"],
               "domains": [{"name": d["name"], "sections": [
                   {"name": s["name"], "skill": "ccdops", "activities": s["activities"]} for s in d["sections"]]}
                   for d in out["domains"]]}
        name, md, skills = cm._import_from_json(json.dumps(doc), "", "tester")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.md"
            f.write_text(md, encoding="utf-8")
            sections = _parse_file(f)
        self.assertEqual(skills, ["ccdops"])
        self.assertNotIn("<!-- skill: admin", md)
        self.assertEqual(md.count("<!-- skill:"), len(sections))
        self.assertEqual(len(sections), 2)                          # exactly the two real files
        self.assertTrue(all(s["skill"] == "ccdops" and s["l1"] == name for s in sections))
        fm = yaml.safe_load(md.split("---")[1])
        self.assertEqual(fm["source_engine"], "graphify")
        self.assertEqual(fm["name"], name)

    def test_unassigned_sections_still_block_commit(self):
        out = self.preview(mode="community", min_size=1)
        doc = {"name": out["name"], "domains": out["domains"]}      # skills left blank
        with self.assertRaises(HTTPException) as c:
            cm._import_from_json(json.dumps(doc), "", "tester")
        self.assertEqual(c.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
