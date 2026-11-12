"""Graph import: Neo4j / Neptune adapters, mapper, safety, service.

No network. The two engines are faked at the HTTP layer with ``httpx.MockTransport``
so the tests exercise the real request construction (statement text, bound
parameters, auth, content types) and the real response parsing.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "IAF-Agent-Skills"):
    sys.path.insert(0, str(p))

from agentos_contracts.graph_source import (  # noqa: E402
    GraphEdge, GraphNode, GraphSnapshot, HierarchyQuery,
)
from iaf_agent_skills.graph_import import (  # noqa: E402
    GraphImportError, Neo4jAdapter, NeptuneAdapter, build_adapter, build_query,
    get_connection, list_connections, map_snapshot, preview_taxonomy, sanitize_text,
    suggest_skills,
)
from iaf_agent_skills.graph_import.mapper import _domain_key  # noqa: E402
from iaf_agent_skills.graph_import.safety import check_endpoint, split_host_port  # noqa: E402

def dns(ip):
    """Make the shared SSRF guard resolve every host to ``ip`` (no real DNS)."""
    return mock.patch("agent_os.egress_ssrf.socket.getaddrinfo",
                      lambda host, port, **kw: [(2, 1, 6, "", (ip, port))])


# parent -> children; names are what the "graph" stores in the `name` property.
TREE = {
    "root": ["fin", "it"],
    "fin": ["ap", "ar"],
    "it": ["k8s"],
    "ap": ["invoice", "payment"],
    "ar": [], "k8s": [], "invoice": [], "payment": [],
}
NAMES = {
    "root": "Enterprise Ops", "fin": "Finance", "it": "IT Operations", "ap": "Accounts Payable",
    "ar": "Accounts Receivable", "k8s": "Kubernetes", "invoice": "Invoice Processing",
    "payment": "Payment Runs",
}


class FakeGraph:
    """Answers the adapter's fixed statements from an in-memory adjacency map."""

    def __init__(self, tree=TREE, names=NAMES, direction="out"):
        self.tree, self.names, self.direction = tree, names, direction
        self.statements = []

    def children_rows(self, ids, idkey):
        rows = []
        for pid in ids:
            for cid in self.tree.get(pid, []):
                rows.append({"pid": pid, "id": cid, "name": self.names[cid], "description": None})
        return rows

    def answer(self, statement, params):
        self.statements.append((statement, params))
        if "RETURN 1 AS ok" in statement:
            return [{"ok": 1}]
        if "$root_name" in statement:
            hits = [k for k, v in self.names.items() if v == params["root_name"]]
            return [{"id": k, "name": self.names[k], "description": None} for k in hits]
        return self.children_rows(params["ids"], None)


def neo4j_client(graph, *, status=200, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if capture is not None:
            capture.append((request, body))
        if status != 200:
            return httpx.Response(status, json={"errors": [{"code": "Neo.Secret", "message": "boom http://internal"}]})
        rows = graph.answer(body["statement"], body["parameters"])
        fields = list(rows[0].keys()) if rows else ["id"]
        return httpx.Response(202, json={"data": {"fields": fields, "values": [[r[f] for f in fields] for r in rows]}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def neptune_client(graph, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if capture is not None:
            capture.append((request, form))
        rows = graph.answer(form["query"], json.loads(form["parameters"]))
        return httpx.Response(200, json={"results": rows})
    return httpx.Client(transport=httpx.MockTransport(handler))


def query(**kw):
    base = dict(root_label="Domain", root_name="Enterprise Ops", edge_type="PARENT_OF")
    base.update(kw)
    return HierarchyQuery(**base)


class AdapterTests(unittest.TestCase):
    def test_neo4j_fetches_tree_with_bound_params_and_read_mode(self):
        cap, g = [], FakeGraph()
        snap = Neo4jAdapter("https://x.example:443", "neo4j", "u", "p", client=neo4j_client(g, capture=cap)).fetch_hierarchy(query())
        self.assertEqual(set(snap.nodes), set(TREE))
        self.assertEqual(len(snap.edges), 7)
        self.assertFalse(snap.truncated)
        req, body = cap[0]
        self.assertEqual(req.url.path, "/db/neo4j/query/v2")
        self.assertEqual(body["accessMode"], "READ")
        self.assertTrue(req.headers["authorization"].startswith("Basic "))
        root_stmt, root_params = g.statements[0]
        self.assertIn("MATCH (r:`Domain`)", root_stmt)
        self.assertIn("elementId(r)", root_stmt)
        self.assertEqual(root_params, {"root_name": "Enterprise Ops"})   # value is bound, not interpolated
        self.assertNotIn("Enterprise Ops", root_stmt)

    def test_neo4j_errors_array_on_a_2xx_is_a_failure_not_an_empty_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(202, json={"data": {"fields": ["id"], "values": []},
                                             "errors": [{"code": "Neo.Secret", "message": "boom http://internal"}]})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(GraphImportError) as c:
            Neo4jAdapter("https://x", "neo4j", "u", "p", client=client).fetch_hierarchy(query())
        self.assertEqual((c.exception.code, c.exception.status), ("query_failed", 502))
        self.assertNotIn("internal", c.exception.message)                  # upstream text is never forwarded
        self.assertEqual(Neo4jAdapter("https://x", "neo4j", "u", "p", client=client).health()["status"], "error")

    def test_neo4j_empty_errors_array_is_fine(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(202, json={"data": {"fields": ["ok"], "values": [[1]]}, "errors": []})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertEqual(Neo4jAdapter("https://x", "neo4j", "u", "p", client=client).health()["status"], "ok")

    def test_children_statement_has_a_deterministic_order_before_the_limit(self):
        g = FakeGraph()
        Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(g)).fetch_hierarchy(query())
        stmt = g.statements[1][0]
        self.assertIn("ORDER BY pid, name, id LIMIT", stmt)

    def test_direction_in_reverses_pattern(self):
        g = FakeGraph()
        Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(g)).fetch_hierarchy(query(direction="in"))
        self.assertIn("(c)-[:`PARENT_OF`]->(p)", g.statements[1][0])

    def test_depth_limit_flags_truncation_without_adding_nodes(self):
        g = FakeGraph()
        snap = Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(g)).fetch_hierarchy(query(max_depth=1))
        self.assertTrue(snap.truncated)
        self.assertEqual(set(snap.nodes), {"root", "fin", "it"})

    def test_node_cap_flags_truncation(self):
        g = FakeGraph()
        snap = Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(g)).fetch_hierarchy(query(max_nodes=10))
        self.assertEqual(len(snap.nodes), 8)       # whole tree fits in 10
        self.assertFalse(snap.truncated)
        big = {"root": [f"n{i}" for i in range(30)], **{f"n{i}": [] for i in range(30)}}
        names = {"root": "Enterprise Ops", **{f"n{i}": f"Node {i:02d}" for i in range(30)}}
        snap = Neo4jAdapter("https://x", "neo4j", "u", "p",
                            client=neo4j_client(FakeGraph(big, names))).fetch_hierarchy(query(max_nodes=10))
        self.assertTrue(snap.truncated)
        self.assertEqual(len(snap.nodes), 10)

    def test_root_not_found_and_ambiguous(self):
        a = Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(FakeGraph()))
        with self.assertRaises(GraphImportError) as c:
            a.fetch_hierarchy(query(root_name="Nope"))
        self.assertEqual(c.exception.code, "root_not_found")
        names = dict(NAMES, fin="Enterprise Ops")      # two nodes share the root name
        a = Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(FakeGraph(TREE, names)))
        with self.assertRaises(GraphImportError) as c:
            a.fetch_hierarchy(query())
        self.assertEqual(c.exception.code, "root_ambiguous")

    def test_upstream_errors_are_generic(self):
        a = Neo4jAdapter("https://secret-host.example", "neo4j", "u", "p", client=neo4j_client(FakeGraph(), status=401))
        with self.assertRaises(GraphImportError) as c:
            a.fetch_hierarchy(query())
        self.assertEqual(c.exception.code, "auth_failed")
        self.assertNotIn("secret-host", c.exception.message)
        self.assertNotIn("boom", c.exception.message)

    def test_identifier_injection_rejected_before_any_request(self):
        g = FakeGraph()
        a = Neo4jAdapter("https://x", "neo4j", "u", "p", client=neo4j_client(g))
        for bad in ("Domain`) DETACH DELETE (n) //", "a b", "1abc", "", "x" * 65):
            with self.assertRaises(GraphImportError):
                a.fetch_hierarchy(query(root_label=bad))
        with self.assertRaises(GraphImportError):
            a.fetch_hierarchy(query(edge_type="PARENT_OF]-() MATCH (x)"))
        self.assertEqual(g.statements, [])

    def test_response_size_cap(self):
        def handler(request):
            return httpx.Response(200, content=b"x" * 64)
        import iaf_agent_skills.graph_import.http_util as hu
        old, hu.MAX_RESPONSE_BYTES = hu.MAX_RESPONSE_BYTES, 10
        try:
            with self.assertRaises(GraphImportError) as c:
                hu.post_capped(httpx.Client(transport=httpx.MockTransport(handler)), "https://x/", max_bytes=10)
            self.assertEqual(c.exception.code, "response_too_large")
        finally:
            hu.MAX_RESPONSE_BYTES = old

    def test_neptune_open_cypher_no_iam(self):
        cap, g = [], FakeGraph()
        snap = NeptuneAdapter("https://n.example:8182", auth="none", client=neptune_client(g, cap)).fetch_hierarchy(query())
        self.assertEqual(set(snap.nodes), set(TREE))
        req, form = cap[0]
        self.assertEqual(req.url.path, "/openCypher")
        self.assertEqual(req.headers["content-type"], "application/x-www-form-urlencoded")
        self.assertIn("id(r)", form["query"])
        self.assertNotIn("elementId", form["query"])
        self.assertNotIn("authorization", req.headers)

    def test_neptune_sigv4_requires_credentials_and_botocore(self):
        with self.assertRaises(GraphImportError) as c:
            NeptuneAdapter("https://n", auth="sigv4", region="us-east-1")
        self.assertEqual(c.exception.code, "missing_credentials")
        a = NeptuneAdapter("https://n", auth="sigv4", region="us-east-1", access_key_id="AKIAEXAMPLE",
                           secret_access_key="s3cr3t", client=neptune_client(FakeGraph()))
        try:
            import botocore  # noqa: F401
        except ImportError:
            with self.assertRaises(GraphImportError) as c:
                a.fetch_hierarchy(query())
            self.assertEqual(c.exception.code, "sigv4_unavailable")
        else:
            cap = []
            a = NeptuneAdapter("https://n", auth="sigv4", region="us-east-1", access_key_id="AKIAEXAMPLE",
                               secret_access_key="s3cr3t", client=neptune_client(FakeGraph(), cap))
            a.fetch_hierarchy(query())
            self.assertIn("AWS4-HMAC-SHA256", cap[0][0].headers["authorization"])
            self.assertIn("neptune-db", cap[0][0].headers["authorization"])


def snapshot(edges, names, root="r", truncated=False):
    nodes = {k: GraphNode(id=k, name=v) for k, v in names.items()}
    return GraphSnapshot(root=nodes[root], nodes=nodes, edges=[GraphEdge(a, b) for a, b in edges], truncated=truncated)


class MapperTests(unittest.TestCase):
    def test_levels_and_flattening(self):
        snap = snapshot(
            [("r", "d"), ("d", "s"), ("s", "a"), ("a", "b")],
            {"r": "Root", "d": "Domain", "s": "Section", "a": "Task", "b": "Subtask"},
        )
        d = map_snapshot(snap)
        self.assertEqual(d.name, "Root")
        sec = d.domains[0]["sections"][0]
        self.assertEqual((d.domains[0]["name"], sec["name"]), ("Domain", "Section"))
        self.assertEqual(sec["activities"], ["Task", "Task / Subtask"])
        self.assertEqual(sec["skill"], "")                       # never auto-assigned
        self.assertIn("flattened", [l.kind for l in d.loss])

    def test_leaf_domain_is_promoted_to_routable_section(self):
        d = map_snapshot(snapshot([("r", "d")], {"r": "Root", "d": "Lonely"}))
        self.assertEqual(d.domains[0]["sections"][0]["name"], "Lonely")
        self.assertIn("promoted_leaf", [l.kind for l in d.loss])

    def test_multi_parent_and_cycle_reported_not_silent(self):
        snap = snapshot(
            [("r", "a"), ("r", "b"), ("a", "x"), ("b", "x"), ("x", "a")],
            {"r": "Root", "a": "Alpha", "b": "Beta", "x": "Shared"},
        )
        d = map_snapshot(snap)
        kinds = [l.kind for l in d.loss]
        self.assertIn("multi_parent", kinds)
        self.assertIn("cycle", kinds)
        placed = [s["name"] for dom in d.domains for s in dom["sections"]]
        self.assertEqual(placed.count("Shared"), 1)              # kept once, under first parent (Alpha)
        self.assertEqual(d.domains[0]["name"], "Alpha")
        self.assertEqual(d.domains[0]["sections"][0]["name"], "Shared")

    def test_deterministic_regardless_of_edge_order(self):
        edges = [("r", "b"), ("r", "a"), ("a", "x"), ("b", "x"), ("a", "y")]
        names = {"r": "Root", "a": "Alpha", "b": "Beta", "x": "Shared", "y": "Why"}
        one = map_snapshot(snapshot(edges, names)).to_dict()
        two = map_snapshot(snapshot(list(reversed(edges)), names)).to_dict()
        self.assertEqual(one, two)

    def test_unnamed_and_duplicate_names(self):
        snap = snapshot(
            [("r", "a"), ("r", "b"), ("r", "c"), ("a", "s1")],
            {"r": "Root", "a": "Same", "b": "same", "c": "", "s1": "Sec"},
        )
        d = map_snapshot(snap)
        names = [dom["name"] for dom in d.domains]
        self.assertEqual(names, ["Same", "same - 2"])
        kinds = [l.kind for l in d.loss]
        self.assertIn("unnamed", kinds)
        self.assertIn("duplicate_name", kinds)

    def test_domains_that_parse_to_the_same_name_are_kept_apart(self):
        # The taxonomy parser drops a trailing "(...)" from a domain heading, so these
        # would be one domain in the index (and their same-named sections would merge).
        snap = snapshot(
            [("r", "a"), ("r", "b"), ("r", "c"), ("a", "s1"), ("b", "s2"), ("c", "s3")],
            {"r": "Root", "a": "Ops (EU)", "b": "Ops (US)", "c": "Ops", "s1": "Incidents", "s2": "Incidents", "s3": "Incidents"},
        )
        d = map_snapshot(snap)
        names = [dom["name"] for dom in d.domains]
        self.assertEqual(names, ["Ops", "Ops (EU) - 2", "Ops (US) - 2"])
        self.assertEqual(len({_domain_key(n) for n in names}), 3)          # distinct once parsed back

    def test_dedupe_suffix_survives_the_name_length_cap(self):
        long = "x" * 120
        d = map_snapshot(snapshot([("r", "a"), ("r", "b")], {"r": "Root", "a": long, "b": long}))
        names = [dom["name"] for dom in d.domains]
        self.assertTrue(all(len(n) <= 120 for n in names))
        self.assertEqual(len({n.casefold() for n in names}), 2)           # still different after any 120-char cut
        self.assertEqual(names[1], "x" * 116 + " - 2")

    def test_duplicate_sections_get_unique_names_within_the_cap(self):
        long = "y" * 120
        d = map_snapshot(snapshot([("r", "a"), ("a", "s1"), ("a", "s2")], {"r": "Root", "a": "Dom", "s1": long, "s2": long}))
        sec = [s["name"] for s in d.domains[0]["sections"]]
        self.assertTrue(all(len(n) <= 120 for n in sec))
        self.assertEqual(len(set(sec)), 2)

    def test_oversized_draft_is_trimmed_to_the_import_limit_with_a_loss_entry(self):
        from iaf_agent_skills.graph_import.mapper import IMPORT_PAYLOAD_MAX_BYTES, fit_import_payload
        n = 3000
        names = {"r": "Root"}
        names.update({f"d{i}": f"Domain {i}" for i in range(n)})
        names.update({f"s{i}": ("S" * 100) + f" {i}" for i in range(n)})
        edges = [("r", f"d{i}") for i in range(n)] + [(f"d{i}", f"s{i}") for i in range(n)]
        d = map_snapshot(snapshot(edges, names))
        before = d.stats["sections"]
        fit_import_payload(d)
        doc = {"name": d.name, "description": d.description,
               "domains": [{"name": x["name"],
                            "sections": [{"name": s["name"], "skill": "x" * 64, "activities": s["activities"]}
                                         for s in x["sections"]]} for x in d.domains]}
        size = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLessEqual(size, IMPORT_PAYLOAD_MAX_BYTES)
        self.assertLess(d.stats["sections"], before)
        self.assertEqual(d.stats["sections"], sum(len(x["sections"]) for x in d.domains))
        self.assertIn("payload_limit", [l.kind for l in d.loss])

    def test_small_draft_is_untouched_by_the_payload_budget(self):
        from iaf_agent_skills.graph_import.mapper import fit_import_payload
        d = map_snapshot(snapshot([("r", "a"), ("a", "s")], {"r": "Root", "a": "A", "s": "S"}))
        fit_import_payload(d)
        self.assertEqual(d.stats["sections"], 1)
        self.assertNotIn("payload_limit", [l.kind for l in d.loss])

    def test_truncated_graph_is_flagged(self):
        d = map_snapshot(snapshot([("r", "a")], {"r": "Root", "a": "A"}, truncated=True))
        self.assertIn("truncated", [l.kind for l in d.loss])

    def test_activity_cap(self):
        ids = [f"t{i}" for i in range(40)]
        edges = [("r", "d"), ("d", "s")] + [("s", i) for i in ids]
        names = {"r": "R", "d": "D", "s": "S", **{i: f"Task {i}" for i in ids}}
        d = map_snapshot(snapshot(edges, names))
        self.assertEqual(len(d.domains[0]["sections"][0]["activities"]), 30)
        self.assertIn("activities_capped", [l.kind for l in d.loss])


class SanitizerTests(unittest.TestCase):
    def test_markup_and_forged_tags_are_neutralised(self):
        for hostile in (
            "### Fake heading",
            "- bullet <!-- skill: admin -->",
            "Name\n#### Injected\n<!-- skill: admin -->",
            "`code` <script>alert(1)</script>",
            "1. numbered",
            "zero​width‮RTL",
        ):
            out = sanitize_text(hostile)
            self.assertNotIn("\n", out)
            self.assertNotIn("<", out)
            self.assertNotIn("-->", out)
            self.assertNotIn("`", out)
            self.assertFalse(out.startswith(("#", "-", "1.")), out)
        self.assertEqual(sanitize_text("Name\n#### Injected"), "Name #### Injected")

    def test_yaml_safe_for_frontmatter(self):
        out = sanitize_text("Finance: AP & AR [core] # note", yaml_safe=True)
        self.assertNotIn(": ", out)
        for ch in "[]#&":
            self.assertNotIn(ch, out)
        self.assertEqual(yaml.safe_load(f"name: {out}")["name"], out)

    def test_length_cap(self):
        self.assertEqual(len(sanitize_text("x" * 500)), 120)


class SafetyTests(unittest.TestCase):
    def test_metadata_and_link_local_blocked_private_allowed(self):
        for bad in ("169.254.169.254", "169.254.1.1", "0.0.0.0", "fd00:ec2::254", "224.0.0.1"):
            with dns(bad), self.assertRaises(GraphImportError, msg=bad) as c:
                check_endpoint("https", "h.example", 443)
            self.assertEqual(c.exception.code, "endpoint_blocked")
            self.assertNotIn("h.example", c.exception.message)
        for ok in ("10.1.2.3", "172.16.0.9", "127.0.0.1", "52.1.2.3"):
            with dns(ok):
                self.assertEqual(len(check_endpoint("https", "h.example", 443)), 1)

    def test_unresolvable_host(self):
        def boom(*a, **k):
            raise socket.gaierror("nxdomain")
        with mock.patch("agent_os.egress_ssrf.socket.getaddrinfo", boom):
            with self.assertRaises(GraphImportError) as c:
                check_endpoint("https", "h.example", 443)
        self.assertEqual(c.exception.code, "unreachable")

    def test_shared_guard_default_still_blocks_private(self):
        from agent_os.egress_ssrf import SSRFBlocked, assert_safe_url
        with dns("10.1.2.3"):
            with self.assertRaises(SSRFBlocked):
                assert_safe_url("https://h.example/")          # default behaviour unchanged
            assert_safe_url("https://h.example/", allow_private=True)
        with dns("169.254.169.254"), self.assertRaises(SSRFBlocked):
            assert_safe_url("https://h.example/", allow_private=True)

    def test_split_host_port(self):
        self.assertEqual(split_host_port("a.b:8182", 443), ("a.b", 8182))
        self.assertEqual(split_host_port("a.b", 443), ("a.b", 443))
        self.assertEqual(split_host_port("[::1]:7474", 443), ("::1", 7474))
        for bad in ("", "a.b/path", "user@a.b", "a b", "a.b:notaport"):
            with self.assertRaises(GraphImportError):
                split_host_port(bad, 443)


def tenant_with(resources):
    d = tempfile.TemporaryDirectory()
    root = Path(d.name)
    (root / "security").mkdir()
    (root / "security" / "external_access.yaml").write_text(yaml.safe_dump({"version": "1.0", "resources": resources}))
    return d, root


NEO = {"id": "external:graph.corp", "type": "graph", "label": "Corp ontology", "engine": "neo4j",
       "hosts": ["corp.example:443"], "database": "neo4j", "auth": "basic",
       "credentials": ["neo4j_corp"], "mcp_connections": ["neo4j_corp_mcp"], "risk": "low"}
NPT = {"id": "external:graph.aws", "type": "graph", "engine": "neptune", "hosts": ["n.example:8182"],
       "auth": "none"}


class Cred:
    def __init__(self, **v):
        self.value = v


class ServiceTests(unittest.TestCase):
    def setUp(self):
        p = dns("10.0.0.5")
        p.start()
        self.addCleanup(p.stop)

    SKILLS = {
        "ap_ops": {"description": "Accounts payable invoice processing and payment runs", "keywords": ["invoice", "payables"]},
        "ccdops": {"description": "Kubernetes cluster operations and pod incidents", "keywords": ["k8s", "pod"]},
        "general": {"description": "General assistant", "keywords": []},
    }

    def test_connections_come_from_registry_and_hide_secrets(self):
        d, root = tenant_with([NEO, NPT, {"id": "external:http.x", "type": "http", "hosts": ["a"]}])
        with d:
            conns = list_connections(root)
            self.assertEqual([c.id for c in conns], ["external:graph.aws", "external:graph.corp"])
            pub = get_connection(root, "graph.corp").public()
            self.assertEqual(pub["mcp_connections"], ["neo4j_corp_mcp"])
            self.assertNotIn("neo4j_corp", json.dumps({k: v for k, v in pub.items() if k != "mcp_connections"}))
            with self.assertRaises(GraphImportError) as c:
                get_connection(root, "external:graph.missing")
            self.assertEqual(c.exception.status, 404)

    def test_preview_end_to_end_neo4j(self):
        d, root = tenant_with([NEO])
        looked_up = []
        def lookup(name):
            looked_up.append(name)
            return Cred(username="neo4j", password="pw")
        with d:
            out = preview_taxonomy(
                root, connection_id="external:graph.corp",
                params={"root_label": "Domain", "root_name": "Enterprise Ops", "edge_type": "PARENT_OF"},
                credential_lookup=lookup, skills_index=self.SKILLS,
                client=neo4j_client(FakeGraph()),
            )
        self.assertEqual(looked_up, ["neo4j_corp"])
        self.assertEqual(out["name"], "Enterprise Ops")
        self.assertEqual([x["name"] for x in out["domains"]], ["Finance", "IT Operations"])
        finance = out["domains"][0]
        ap = next(s for s in finance["sections"] if s["name"] == "Accounts Payable")
        self.assertEqual(ap["skill"], "")                                 # nothing auto-assigned
        self.assertEqual(ap["suggestions"][0]["skill"], "ap_ops")          # but hinted
        k8s = out["domains"][1]["sections"][0]
        self.assertEqual(k8s["suggestions"][0]["skill"], "ccdops")
        self.assertEqual(out["unmapped_sections"], out["stats"]["sections"])
        self.assertEqual(out["provenance"]["source_connection"], "external:graph.corp")
        self.assertNotIn("pw", json.dumps(out))
        self.assertNotIn("corp.example", json.dumps(out))

    def test_preview_neptune_no_credential_needed(self):
        d, root = tenant_with([NPT])
        with d:
            out = preview_taxonomy(
                root, connection_id="graph.aws",
                params={"root_label": "Domain", "root_name": "Enterprise Ops", "edge_type": "PARENT_OF"},
                credential_lookup=lambda n: self.fail("no credential should be requested"),
                skills_index=self.SKILLS, client=neptune_client(FakeGraph()),
            )
        self.assertEqual(out["stats"]["domains"], 2)

    def test_scope_denied_credential_gives_actionable_error(self):
        d, root = tenant_with([NEO])
        with d:
            with self.assertRaises(GraphImportError) as c:
                build_adapter(get_connection(root, "graph.corp"), lambda n: None)
        self.assertEqual(c.exception.code, "credential_unavailable")
        self.assertIn("taxonomy_graph_import", c.exception.message)

    def test_blocked_endpoint_and_plain_http_policy(self):
        d, root = tenant_with([NEO, dict(NEO, id="external:graph.plain", scheme="http")])
        cred = lambda n: Cred(username="a", password="b")
        with d:
            with dns("169.254.169.254"), self.assertRaises(GraphImportError) as c:
                build_adapter(get_connection(root, "graph.corp"), cred)
            self.assertEqual(c.exception.code, "endpoint_blocked")
            with dns("52.1.2.3"), self.assertRaises(GraphImportError) as c:
                build_adapter(get_connection(root, "graph.plain"), cred)
            self.assertEqual(c.exception.code, "insecure_scheme")      # creds would cross the net in clear
            build_adapter(get_connection(root, "graph.plain"), cred)    # private address: fine

    def test_build_query_validation_and_clamps(self):
        q = build_query({"root_label": "Domain", "root_name": "X", "edge_type": "BROADER",
                         "direction": "in", "max_depth": 99, "max_nodes": 10**9})
        self.assertEqual((q.max_depth, q.max_nodes, q.direction), (8, 5000, "in"))
        for bad in ({"root_label": "Domain", "root_name": "", "edge_type": "E"},
                    {"root_label": "Do main", "root_name": "x", "edge_type": "E"},
                    {"root_label": "D", "root_name": "x", "edge_type": "E", "direction": "sideways"},
                    {"root_label": "D", "root_name": "x", "edge_type": "E", "name_property": "a-b"}):
            with self.assertRaises(GraphImportError):
                build_query(bad)

    def test_registry_validation_for_graph_type(self):
        from agent_os.external_access import validate_external_access_doc
        ok = validate_external_access_doc({"resources": [NEO, NPT]})
        self.assertTrue(ok["valid"], ok)
        bad = validate_external_access_doc({"resources": [
            {"id": "external:graph.z", "type": "graph", "engine": "mongo", "hosts": []}]})
        self.assertFalse(bad["valid"])


    def test_malformed_hosts_is_a_validation_error_not_a_crash(self):
        from agent_os.external_access import validate_external_access_doc
        for hosts in (443, "db.example:443", {"a": 1}, True):
            with self.subTest(hosts=hosts):
                out = validate_external_access_doc({"resources": [
                    {"id": "external:graph.z", "type": "graph", "engine": "neo4j", "hosts": hosts}]})
                self.assertFalse(out["valid"])
                self.assertTrue(any("hosts must be a list" in e for e in out["errors"]), out["errors"])
                self.assertTrue(any("exactly one host" in e for e in out["errors"]), out["errors"])


class SuggestTests(unittest.TestCase):
    def test_no_hint_when_nothing_overlaps(self):
        doms = [{"name": "Zebra", "sections": [{"name": "Quux", "activities": ["flarp"]}]}]
        suggest_skills(doms, ServiceTests.SKILLS)
        self.assertEqual(doms[0]["sections"][0]["suggestions"], [])
        self.assertNotIn("skill", doms[0]["sections"][0])      # suggest never assigns


if __name__ == "__main__":
    unittest.main()
