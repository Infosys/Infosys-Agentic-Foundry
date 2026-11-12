# Taxonomy graph import (Neo4j / Amazon Neptune / graphify)

> **Audience:** skill authors (admins) and platform devs. **Status:** implemented on
> `feat/taxonomy-graph-import` (stacked on `feat/taxonomy-crud-ui`, PR #141).
> **Verification status:** unit-tested against faked Neo4j and Neptune HTTP endpoints only.
> It has **not** yet been run against a live Neo4j or Neptune; see
> [Smoke test](#smoke-test-against-a-real-instance) before relying on it.
> Code and tests define behaviour: `IAF-Agent-Skills/iaf_agent_skills/graph_import/`,
> `IAF-Agent-Skills/tests/test_graph_import.py`, `IAF-Agent-Studio/tests/test_taxonomy_graph_import.py`.

## What problem this solves

A **taxonomy** answers one question for the router: *given what the user said, which skill
handles it?* An existing enterprise graph (a Neo4j ontology, a Neptune knowledge graph)
answers a different one: *what relates to what?* It has the hierarchy (domains → processes →
tasks) but **no skill information**.

So there are two separate jobs, and one connection definition can serve both:

| Job | Who uses the graph | How |
|---|---|---|
| **A. Build routing structure** | The router (`TaxonomySignalIndex`) | One-time import of the *hierarchy* into a taxonomy `.md` (this doc) |
| **B. Use the graph's data** | A skill at runtime | The skill declares an MCP connection and queries the graph (see [Using the same graph from a skill](#using-the-same-graph-from-a-skill)) |

**The link between graph and skill is made in job A, by a human:** every imported L3 section
carries a `<!-- skill: X -->` tag, assigned in the preview screen. The importer suggests skills
but never assigns one itself.

## How it works

```
external_access.yaml (type: graph)      Credentials (scope: taxonomy_graph_import)
            \                                   /
             v                                 v
   Skill Builder ▸ Taxonomy ▸ "Graph"  ──►  POST /taxonomy-graph-preview   (read-only, writes nothing)
                                              Neo4j / Neptune adapter  →  GraphSnapshot  →  mapper  →  draft
                                              + loss report + skill suggestions
   human assigns a skill to every section
            │
            v
   POST /taxonomy-import (JSON)  ──►  .md file → Enterprise_Context.md → re-index   (existing path from PR #141)
```

Commit deliberately goes through the existing `/taxonomy-import` path so file write,
Enterprise_Context registration, indexing and permission checks stay in one place. The JSON
import now rejects any section without a skill (HTTP 422), so unassigned nodes can never reach the router.

## Setup

### 1. Register the connection (admin)

Add a resource with `type: graph` to the tenant's `security/external_access.yaml`
(the External access registry that already allowlists hosts and credentials for skills):

```yaml
- id: external:graph.corp_ontology
  label: Corporate ontology (Neo4j Aura)
  type: graph
  engine: neo4j                 # neo4j | neptune
  hosts: [abc123.databases.neo4j.io:443]   # exactly one host[:port] - this is the allowlist
  database: neo4j               # neo4j only
  auth: basic                   # basic (neo4j) | sigv4 | none (neptune)
  credentials: [neo4j_corp]     # name of the credential to use
  mcp_connections: [neo4j_corp_mcp]   # optional: the MCP connection skills use for the same graph
  risk: low
  owners: [platform]

- id: external:graph.aws_kg
  label: Knowledge graph (Neptune)
  type: graph
  engine: neptune
  hosts: [my-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com:8182]
  auth: sigv4
  region: us-east-1
  credentials: [aws_neptune_reader]
  # scheme: https is the default. `scheme: http` is accepted only for private/loopback hosts.
```

Validation (`validate_external_access_doc`) requires `engine` ∈ {neo4j, neptune}, exactly one host,
and `auth` ∈ {basic, sigv4, none}.

### 2. Create the credential

Create it in the credential store with **`scope: [taxonomy_graph_import]`** (a credential whose scope
does not list this consumer is refused and the preview says so):

| Engine / auth | Credential `value` fields |
|---|---|
| Neo4j, `basic` | `username`, `password` |
| Neptune, `sigv4` | `access_key_id`, `secret_access_key`, optional `session_token` |
| Neptune, `none` | no credential needed |

Use a **read-only** identity. Neptune cannot enforce read-only per request, so give the IAM user/role
only `neptune-db:ReadDataViaQuery`. Neo4j requests are sent with `accessMode: READ`.

Neptune SigV4 needs the optional `botocore` package: `pip install -r requirements-graph-import.txt`.
Without it the preview returns "needs the optional 'botocore' package". Neo4j needs nothing extra
(it uses the HTTP Query API over the already-pinned `httpx`, not the Bolt driver).

### 3. Reachability

Studio must be able to reach the host:port. Neptune clusters are VPC-only by default, so Studio has to run
inside (or be peered/tunnelled to) that VPC. The Neo4j engine must support the **Query API** (Neo4j 5.19+,
or Aura).

## The graphify engine (file-based)

A third engine, `graphify`, reads a [graphify](https://github.com/safishamsi/graphify) code graph (`graph.json`)
published under the tenant's `shared/graphs/` instead of a database. It needs **no host and no credential**.

```yaml
- id: external:graph.agentos_code
  label: AgentOS code graph
  type: graph
  engine: graphify
  path: /shared/graphs/agentos/graph.json     # /shared/graphs/... and .json only
```

The hierarchy is derived from the graph (there is no root node or relationship to name): *group by communities*
(community → source file → symbols) or *group by folder*. Everything after that (loss report, sanitiser, skill
suggestions, commit through `/taxonomy-import`) is shared with the Neo4j/Neptune engines. Full details, the
`codebase_graph` skill that answers questions from the same graph, and what was verified: see `docs/GRAPHIFY.md`.

## Using it (UI)

Skill Builder → Taxonomy → **Add → Build from a graph database** (visible to users with `skills.author`; the
screen lists Neo4j and graphify; Neptune is supported by the backend but is not offered in the UI for now). To publish
an ontology `.json` for chat questions instead, use **Add → Upload an ontology / graph file** (see `docs/GRAPH_UPLOAD.md`):

1. Pick a connection; enter the **root node label** and **name**, and the **hierarchy relationship**
   (e.g. `PARENT_OF`; choose "child → parent" for relationships like `BROADER`).
2. **Preview** reads the hierarchy and shows domains/sections, a list of anything that could not be
   carried over exactly, and a skill dropdown per section. Ranked suggestions appear as chips;
   **Accept all suggestions** fills blanks with the top suggestion (an explicit action).
3. **Import & Index** is enabled only when every section has a skill.

## Mapping rules

Deterministic (same graph → same draft), so a re-import diffs cleanly.

* Root node = the taxonomy (L1, frontmatter `name`).
* depth 1 → L2 domain; depth 2 → L3 section; depth ≥ 3 → bullet activities under the L3 ancestor
  (`Child / Grandchild`).
* Walk is breadth-first with siblings sorted by name. A node reachable through several parents stays under the
  **first** one; the rest are reported.
* A domain with no children becomes a section of the same name.

Loss report kinds: `multi_parent`, `cycle`, `flattened`, `promoted_leaf`, `duplicate_name` (renamed `X - 2`; a non-parenthetical suffix, because the taxonomy parser drops a trailing `(...)` from domain names, and the base is shortened so the name still fits 120 characters),
`unnamed` (node and its sub-tree skipped), `activities_capped` (30 per section), `truncated` (depth/size limit hit),
`payload_limit` (the draft would exceed the 512 KiB import limit, so trailing domains/sections were left out; narrow the root, depth or path prefix to import them).

Graphify naming: root-level files form a domain called `Root files`, and communities that share a label are told apart with `Label - <community>` (never a trailing `(...)`, which the taxonomy parser would strip). A Neo4j/Neptune child query is ordered (`ORDER BY pid, name, id`) before its row limit, so repeated previews of an unchanged graph keep the same nodes.

Limits: depth ≤ 8 (default 5), nodes ≤ 5000 (default 2000), 20 s request timeout, 10 MB response cap.

## Security model

| Concern | Control |
|---|---|
| SSRF | Callers choose a **registered connection id**, never a URL. The host comes from the admin-controlled registry. `check_endpoint` also runs the shared `agent_os.egress_ssrf` guard with `allow_private=True`: cloud-metadata, link-local, multicast, reserved and unspecified addresses are refused even if registered. Redirects are disabled. Residual risk: the connection is made by hostname after the check (no address pinning). |
| Query injection | No free-text queries. Statements are fixed MATCH/RETURN templates. Label, relationship and property names (which Cypher cannot parameterise) must match `^[A-Za-z_][A-Za-z0-9_]{0,63}$` and are back-tick quoted; values are bound parameters. Validation happens before the first request. |
| Credentials | Resolved only through the `credential_resolver` capability **bound to the requested tenant** (an explicit tenant override, else a resolver over that tenant's own `shared/config`; never the deployment tenant's store), with consumer `taxonomy_graph_import` (scoped, audited). Never returned to the browser. Upstream error bodies and URLs are never forwarded (generic messages only). |
| Markdown / frontmatter injection | Graph labels are untrusted. `sanitize_text` removes control/bidi characters, `<`/`>`/`<!--`/`-->`, back-ticks and leading markdown markers; the committed file is round-trip tested through `TaxonomySignalIndex._parse_file` with hostile labels. Provenance frontmatter uses a fixed key set and a restricted character class. |
| Authorisation / audit | `skills.author` + tenant binding on every endpoint, **plus** an entitlement check (`access` on `external` / `graph.<id>`, the same decision the runtime makes) on the selected connection before any credential is resolved or graph is read; a denied connection is also left out of the connection list. The same decision is applied in chat: the agent resolves, for the current caller, which registered graph folders under `shared/graphs` are denied and passes them to `graph_query` (`IAF_DENIED_GRAPHS`); a denied graph is reported exactly like a missing one. The check runs on every `graph_query` call, so revoking access takes effect on the next call, and it works on the remote kernel backend too (it uses the agent's own entitlement context, not kernel internals). If governance is on but no principal is bound, every graph is denied. A tool provider that predates per-call context still loads the skill's other tools but is not given `graph_query` while graph governance is on. Registry paths must be the canonical `/shared/graphs/<name>/graph.json` spelling (no `.` or empty segments). Graphs that are not registered as a connection carry no per-graph policy.  Each preview is written to the same `external_access_audit.jsonl` stream the kernel uses (user, connection id, allowed/denied; no query text or credentials). |
| Misrouting | Skills are never auto-assigned; commit is blocked until every section has a valid skill (checked against `_index.yaml`). |

Provenance written to the taxonomy frontmatter: `source_connection`, `source_engine`, `source_root`, `imported_at` (quoted when YAML would retype them). Frontmatter `name` and `description` are written through a YAML dumper, so names such as `2026` or `true` stay strings when the indexer reads them back.

A Neo4j response that is HTTP 2xx but carries a non-empty `errors` array is treated as a failed query (`query_failed`, 502), not as an empty result.

## API

All require `skills.author`.

* `GET  /api/context-manager/taxonomy-graph-connections?tenant_id=` → `{connections:[{id,label,engine,auth,has_credential,mcp_connections,risk}]}` (no host, no credential name).
* `POST /api/context-manager/taxonomy-graph-preview` body: `connection_id`, then for Neo4j/Neptune `root_label, root_name, edge_type, direction (out|in), name_property, description_property, max_depth, max_nodes`, or for graphify `mode (community|path), path_prefix, domain_depth, min_size, max_domains`; plus `taxonomy_name, description, tenant_id`
  → draft `{name, description, domains[{name, sections[{name, skill:"", activities[], suggestions[]}]}], loss[], stats, provenance, unmapped_sections, connection}`. Writes nothing.
* Commit: `POST /api/context-manager/taxonomy-import` with the reviewed draft as JSON (plus `source: <provenance>`).

## Using the same graph from a skill

Taxonomy import only brings the *structure*. For a skill to read the graph's **data** at runtime, use the
existing MCP connector mechanism (`mcp_connections` in `SKILL.md`; see `05_agent_config.md`):

```yaml
# skills/<name>/SKILL.md frontmatter
mcp_connections:
  - name: neo4j_corp_mcp
    type: direct
    transport: streamable_http
    url: https://neo4j-mcp.internal.example/mcp
```

Notes:

* In this repo `AGENTOS_UNTRUSTED_EXECUTION_GUARD=true` blocks **local stdio** MCP servers, so run the MCP server as a
  separate service and use `streamable_http`/`sse`.
* Put tokens in `${CRED:name/field}` references, not in SKILL.md.
* List the connection name under `mcp_connections:` on the same `external:graph.*` registry entry so the
  external-access governance covers it (that is why the field exists on the entry above).
* Vendor-maintained MCP servers exist for both products (Neo4j's Cypher MCP server, an AWS Labs Neptune MCP
  server). Check their current names, versions and auth options before adopting one; they are not bundled here.

## Not included (deliberately)

* **Live / scheduled sync.** The `.md` file is the source of truth; a sync would overwrite hand-assigned skills.
  A future re-import should be a manual diff that preserves existing skill tags.
* **Gremlin and SPARQL.** The hierarchy fetch only needs openCypher (Neptune serves it over HTTPS). Add them when
  there is a real graph that needs them.
* **Bolt driver.** Avoided to keep the dependency/CVE surface unchanged.
* Free-text queries, writing back to the graph, other graph vendors.

## Smoke test against a real instance

Before first use against a real service, confirm the wire format (the tests use fakes):

```bash
# Neo4j (Query API v2)
curl -sS -u "$USER:$PASS" -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"statement":"RETURN 1 AS ok","accessMode":"READ"}' "https://$HOST/db/neo4j/query/v2"
# expect: {"data":{"fields":["ok"],"values":[[1]]}, ...}

# Neptune (openCypher, IAM auth off; for IAM use awscurl --service neptune-db)
curl -sS -X POST "https://$HOST:8182/openCypher" -d 'query=RETURN 1 AS ok'
# expect: {"results":[{"ok":1}]}
```

If either differs from the expected shape, adjust `_run` in `neo4j_adapter.py` / `neptune_adapter.py`.
