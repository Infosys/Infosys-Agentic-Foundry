"""graph_store: convert an uploaded graph/ontology JSON to graphify node-link format, and
publish / list / delete it under <tenant>/shared/graphs/<name>/."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills"):
    sys.path.insert(0, str(p))

from iaf_agent_skills.graph_import import (  # noqa: E402
    GraphImportError, delete_graph, list_graphs, normalize_graph, publish_graph,
)


def ids(g):
    return {n["id"] for n in g["nodes"]}


def edge_set(g):
    return {(l["source"], l["relation"], l["target"]) for l in g["links"]}


class NormalizeTest(unittest.TestCase):
    def test_nodes_and_edges_with_from_to_and_type(self):
        g, rep = normalize_graph({
            "nodes": [{"id": "ingress", "label": "Ingress Gateway", "type": "Component", "description": "Entry point"},
                      {"id": "dns", "name": "CoreDNS", "type": "Component"}],
            "edges": [{"from": "ingress", "to": "dns", "type": "depends_on"}]})
        self.assertEqual(rep["format"], "ontology")
        self.assertEqual(edge_set(g), {("ingress", "depends_on", "dns")})
        n = {x["id"]: x for x in g["nodes"]}
        self.assertEqual(n["ingress"]["label"], "Ingress Gateway")
        self.assertEqual(n["ingress"]["file_type"], "Component")
        self.assertEqual(n["ingress"]["description"], "Entry point")
        self.assertEqual(n["dns"]["label"], "CoreDNS")           # label falls back to name
        self.assertEqual(g["links"][0]["confidence"], "EXTRACTED")

    def test_entities_relationships_and_endpoints_by_name(self):
        g, _ = normalize_graph({
            "entities": [{"name": "Vendor"}, {"name": "Invoice"}],
            "relationships": [{"subject": "Invoice", "predicate": "billed_by", "object": "Vendor"}]})
        self.assertEqual(edge_set(g), {("Invoice", "billed_by", "Vendor")})

    def test_endpoint_matched_by_label_case_insensitively(self):
        g, _ = normalize_graph({
            "nodes": [{"id": "n1", "label": "Purchase Order"}, {"id": "n2", "label": "Vendor"}],
            "edges": [{"source": "purchase order", "target": "VENDOR", "relation": "from"}]})
        self.assertEqual(edge_set(g), {("n1", "from", "n2")})

    def test_bare_triples_derive_nodes(self):
        g, rep = normalize_graph([{"subject": "A", "predicate": "knows", "object": "B"},
                                  {"subject": "B", "predicate": "knows", "object": "C"}])
        self.assertEqual(ids(g), {"A", "B", "C"})
        self.assertEqual(len(g["links"]), 2)
        self.assertEqual(rep["edges"], 2)

    def test_stub_nodes_for_endpoints_only_in_edges_are_reported(self):
        g, rep = normalize_graph({"nodes": [{"id": "A"}], "edges": [{"source": "A", "target": "Ghost"}]})
        self.assertEqual(ids(g), {"A", "Ghost"})
        self.assertTrue(any("created from names" in n for n in rep["notes"]))

    def test_children_tree_becomes_has_child_edges(self):
        g, rep = normalize_graph({"name": "Enterprise", "children": [
            {"name": "Finance", "children": [{"name": "AP"}, {"name": "AR"}]}, {"name": "IT"}]})
        self.assertEqual(rep["format"], "tree")
        self.assertEqual(ids(g), {"Enterprise", "Finance", "AP", "AR", "IT"})
        self.assertIn(("Finance", "has_child", "AP"), edge_set(g))
        self.assertIn(("Enterprise", "has_child", "IT"), edge_set(g))

    def test_graphify_graph_passes_through_with_code_type(self):
        doc = {"directed": False, "nodes": [{"id": "a", "label": "A", "source_file": "x.py", "community": 3}],
               "links": []}
        g, rep = normalize_graph(doc)
        self.assertEqual(rep["format"], "graphify")
        self.assertEqual(g["nodes"][0]["file_type"], "code")
        self.assertEqual(g["nodes"][0]["community"], 3)
        self.assertEqual(g["nodes"][0]["source_file"], "x.py")

    def test_unmatched_edges_and_idless_nodes_are_counted_not_fatal(self):
        g, rep = normalize_graph({"nodes": [{"id": "A"}, {"label": ""}, 5.5],
                                  "edges": [{"source": "A"}, "junk", {"source": "A", "target": "A"}]})
        self.assertEqual(ids(g), {"A"})
        self.assertEqual(len(g["links"]), 1)
        self.assertTrue(any("had no id" in n or "have no id" in n or "no id" in n for n in rep["notes"]))
        self.assertTrue(any("skipped" in n for n in rep["notes"]))

    def test_rejects_unusable_input(self):
        for bad in (123, "x", None, {}, {"foo": 1}, {"nodes": [], "edges": []}, []):
            with self.subTest(bad=bad):
                with self.assertRaises(GraphImportError) as c:
                    normalize_graph(bad)
                self.assertEqual(c.exception.status, 422)

    def test_values_are_sanitised_to_short_single_lines(self):
        g, _ = normalize_graph({"nodes": [{"id": "A", "label": "Line one\nLine two  " + "x" * 500}]})
        self.assertNotIn("\n", g["nodes"][0]["label"])
        self.assertLessEqual(len(g["nodes"][0]["label"]), 200)

    def test_deep_tree_is_bounded(self):
        node = {"name": "leaf"}
        for i in range(500):
            node = {"name": f"n{i}", "children": [node]}
        g, _ = normalize_graph(node)
        self.assertLessEqual(len(g["nodes"]), 70)


class ReviewFindingsNormalizeTest(unittest.TestCase):
    def test_overlong_ids_are_rejected_not_merged(self):
        a, b = "x" * 200 + "A", "x" * 200 + "B"           # share their first 200 chars
        with self.assertRaises(GraphImportError) as c:
            normalize_graph({"nodes": [{"id": a}, {"id": b}], "edges": [{"source": a, "target": b}]})
        self.assertEqual((c.exception.status, c.exception.code), (422, "bad_graph"))
        self.assertIn("200", c.exception.message)
        with self.assertRaises(GraphImportError):          # also when only named in a triple
            normalize_graph([{"subject": a, "predicate": "p", "object": "Z"}])
        g, _ = normalize_graph({"nodes": [{"id": "x" * 200}]})   # exactly 200 is fine
        self.assertEqual(len(g["nodes"][0]["id"]), 200)

    def test_node_limit_counts_nodes_created_from_edge_endpoints(self):
        triples = [{"subject": f"s{i}", "predicate": "p", "object": f"o{i}"} for i in range(6)]   # 12 nodes
        with mock.patch("iaf_agent_skills.graph_import.graph_store.MAX_NODES", 10):
            with self.assertRaises(GraphImportError) as c:
                normalize_graph(triples)
            self.assertEqual((c.exception.status, c.exception.code), (413, "graph_too_large"))
            normalize_graph(triples[:5])                    # exactly 10 nodes is allowed


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "tenants" / "company"
        self.root.mkdir(parents=True)
        self.doc = json.dumps({"nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                               "edges": [{"source": "A", "target": "B"}, {"source": "A", "target": "C"}]})

    def graph_file(self, name="demo"):
        return self.root / "shared" / "graphs" / name / "graph.json"

    def test_publish_writes_graphify_json_where_graph_query_reads_it(self):
        out = publish_graph(self.root, "demo", self.doc)
        self.assertEqual((out["nodes"], out["edges"], out["format"]), (3, 2, "ontology"))
        self.assertEqual(out["example"], "A")                    # the most connected node
        written = json.loads(self.graph_file().read_text(encoding="utf-8"))
        self.assertEqual(len(written["nodes"]), 3)
        self.assertEqual(written["links"][0]["relation"], "related_to")

    def test_duplicate_needs_overwrite(self):
        publish_graph(self.root, "demo", self.doc)
        with self.assertRaises(GraphImportError) as c:
            publish_graph(self.root, "demo", self.doc)
        self.assertEqual(c.exception.status, 409)
        publish_graph(self.root, "demo", json.dumps({"nodes": [{"id": "Z"}]}), overwrite=True)
        self.assertEqual(len(json.loads(self.graph_file().read_text())["nodes"]), 1)

    def test_bad_names_are_rejected_and_nothing_escapes(self):
        for name in ("", "../x", "a/b", "a\\b", "x" * 65, "..", "with space", "C:\\evil"):
            with self.subTest(name=name):
                with self.assertRaises(GraphImportError) as c:
                    publish_graph(self.root, name, self.doc)
                self.assertEqual(c.exception.code, "bad_name")
        graphs = self.root / "shared" / "graphs"
        self.assertEqual(list(graphs.glob("*")) if graphs.exists() else [], [])      # nothing was written

    def test_invalid_json_and_oversize(self):
        with self.assertRaises(GraphImportError) as c:
            publish_graph(self.root, "demo", "{not json")
        self.assertEqual(c.exception.status, 422)
        with self.assertRaises(GraphImportError) as c:
            publish_graph(self.root, "demo", " " * (16 * 1024 * 1024 + 1))
        self.assertEqual(c.exception.status, 413)
        self.assertFalse(self.graph_file().exists())             # a failed upload leaves nothing behind

    def test_loser_of_an_overwrite_false_race_gets_409_and_first_graph_is_untouched(self):
        publish_graph(self.root, "demo", self.doc)
        before = self.graph_file().read_bytes()
        # simulate the race: the loser's exists() pre-check ran before the winner's write landed
        with mock.patch.object(Path, "exists", return_value=False):
            with self.assertRaises(GraphImportError) as c:
                publish_graph(self.root, "demo", json.dumps({"nodes": [{"id": "Z"}]}))
        self.assertEqual((c.exception.status, c.exception.code), (409, "exists"))
        self.assertEqual(self.graph_file().read_bytes(), before)
        self.assertEqual([p.name for p in self.graph_file().parent.iterdir()], ["graph.json"])   # no temp left

    def test_concurrent_uploads_exactly_one_wins(self):
        results, barrier = [], threading.Barrier(8)

        def go(i):
            barrier.wait()
            try:
                publish_graph(self.root, "race", json.dumps({"nodes": [{"id": f"N{i}"}]}))
                results.append("ok")
            except GraphImportError as exc:
                results.append(exc.status)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count(409), 7)
        self.assertEqual([p.name for p in self.graph_file("race").parent.iterdir()], ["graph.json"])

    def test_converted_graph_over_the_query_limit_is_refused_before_writing(self):
        publish_graph(self.root, "demo", self.doc)
        before = self.graph_file().read_bytes()
        with mock.patch("iaf_agent_skills.graph_import.graph_store.MAX_QUERY_BYTES", 50):
            with self.assertRaises(GraphImportError) as c:
                publish_graph(self.root, "demo", self.doc, overwrite=True)      # must not replace the old one
            self.assertEqual((c.exception.status, c.exception.code), (413, "graph_too_large"))
            with self.assertRaises(GraphImportError):
                publish_graph(self.root, "new", self.doc)
        self.assertEqual(self.graph_file().read_bytes(), before)
        self.assertFalse(self.graph_file("new").exists())

    def test_list_and_delete(self):
        publish_graph(self.root, "beta", self.doc)
        publish_graph(self.root, "alpha", self.doc)
        listed = list_graphs(self.root)
        self.assertEqual([g["name"] for g in listed], ["alpha", "beta"])
        self.assertEqual((listed[0]["nodes"], listed[0]["edges"]), (3, 2))
        delete_graph(self.root, "alpha")
        self.assertEqual([g["name"] for g in list_graphs(self.root)], ["beta"])
        with self.assertRaises(GraphImportError) as c:
            delete_graph(self.root, "alpha")
        self.assertEqual(c.exception.status, 404)

    def test_list_empty_when_nothing_published(self):
        self.assertEqual(list_graphs(self.root), [])

    def test_list_ignores_foreign_folders_and_marks_unreadable(self):
        publish_graph(self.root, "ok", self.doc)
        (self.root / "shared" / "graphs" / "no_file").mkdir()
        bad = self.root / "shared" / "graphs" / "broken"
        bad.mkdir()
        (bad / "graph.json").write_text("{nope", encoding="utf-8")
        got = {g["name"]: g for g in list_graphs(self.root)}
        self.assertEqual(set(got), {"ok", "broken"})
        self.assertEqual(got["broken"].get("error"), "unreadable")


if __name__ == "__main__":
    unittest.main()
