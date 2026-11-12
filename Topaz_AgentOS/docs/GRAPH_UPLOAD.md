# Upload a graph or ontology and ask about it in chat

> **Audience:** people who own a knowledge area (they bring the JSON) and developers who maintain the
> feature. Code and tests define behaviour: `IAF-Agent-Skills/iaf_agent_skills/graph_import/graph_store.py`,
> the `/graph-*` routes in `IAF-Agent-Studio/routers/context_manager.py`,
> `enterprise_root/tenants/company/skills/codebase_graph/`, and the tests
> `IAF-Agent-Skills/tests/test_graph_store.py`, `IAF-Agent-Studio/tests/test_graph_upload.py`.

A **graph** is a set of things (nodes) joined by relationships (edges). This feature lets a user upload one
as a `.json` file and then ask chat questions such as "what is the Ingress Gateway related to?" or "how does
the Ingress Gateway reach CoreDNS?". It needs no server access and no conversion step by hand.

This is **not** the taxonomy. A taxonomy routes a question to a skill. A graph answers questions about
entities and how they connect. They can be used together.

## For the user: upload and ask

1. Open **Skill Builder > Files & Taxonomy** and click **Add → Upload an ontology / graph file** (under *Knowledge graph · answers questions in chat*; the other entries build taxonomies).
   You need the `skills.author` permission.
2. Choose the `.json` file, give the graph a name (letters, digits, `_`, `-`), and click **Upload & Publish**.
3. The screen tells you what it understood: how many nodes and edges, how the file was read, and anything it
   had to skip. Fix the file and upload again with *Replace* ticked if the counts look wrong.
4. Ask in chat. Use `@codebase_graph` or words like "ontology", "knowledge graph", "uploaded graph":
   - `@codebase_graph what graphs are published?`
   - `@codebase_graph what is CoreDNS related to?`
   - `@codebase_graph how does Ingress Gateway reach CoreDNS?`
   - `@codebase_graph give me an overview of it_ops_ontology`

If only one graph is published, the graph name can be left out. With several, name the one you mean.

## Accepted file shapes

| Shape | Example |
|---|---|
| Nodes and edges | `{"nodes":[{"id":"a","label":"A","type":"Component","description":"..."}], "edges":[{"from":"a","to":"b","type":"depends_on"}]}` |
| Entities and relationships | `{"entities":[{"name":"Vendor"}], "relationships":[{"subject":"Invoice","predicate":"billed_by","object":"Vendor"}]}` |
| Triples only | `[{"subject":"A","predicate":"knows","object":"B"}]` (nodes are derived) |
| A tree | `{"name":"Enterprise","children":[{"name":"Finance","children":[...]}]}` (each child gets a `has_child` edge) |
| graphify | A `graph.json` from graphify (`nodes` and `links`), used as is |

Field names that are understood:

- **Node id:** `id`, `@id`, `iri`, `uri`, `key`, `name`, `label`, `title`. **Label:** `label`, `name`, `title`.
  **Type:** `type`, `kind`, `category`, `class`. **Description:** `description`, `definition`, `comment`, `summary`.
- **Edge ends:** `source`/`target`, `from`/`to`, `subject`/`object`, `src`/`dst`. **Relation:** `relation`,
  `relationship`, `predicate`, `type`, `label`.
- An edge end may be a node's id or its label (case-insensitive). A name that appears only in an edge becomes a node.

What is not carried over: other properties on nodes and edges. Only id, label, type, description, source file,
location and community are kept. Edges without a relation are called `related_to`. Every converted edge is
marked `EXTRACTED` (stated in the file).

## What chat can answer

`graph_query` actions: `list`, `stats` (counts, node types, relations, most connected), `search` (keywords in
label, type and description), `explain` (one node and its neighbours by relation), `path` (shortest connection
between two nodes), `community` (members of a group, when the file has a `community` number).

It reads the file only. It does not know current values, it cannot follow links that are not in the file,
and the graph can be out of date: upload again with *Replace* to refresh.

## For developers

```
browser ── POST /api/context-manager/graph-upload {name, content, overwrite}
              └─ graph_store.publish_graph → normalize_graph → <tenant>/shared/graphs/<name>/graph.json
chat ─ codebase_graph skill ─ graph_query (subprocess) ─ reads the same folder
```

| Route | Purpose |
|---|---|
| `GET  /graph-library` | Published graphs with node and edge counts |
| `POST /graph-upload` | Convert and publish. 409 if the name exists and `overwrite` is false |
| `POST /graph-delete` | Remove a published graph |

All three need `skills.author`, bind the tenant like the other routes, and write to the external-access audit
stream (`graph_upload`, `graph_delete`).

Safety properties (each has a test): the name is pattern-checked and the resolved folder must stay under
`shared/graphs`; upload is capped at 16 MB (the tool still reads up to 64 MB for graphs published by hand);
at most 200,000 nodes (counting nodes created from edge ends) and 1,000,000 edges; the converted file must stay
under the tool's 64 MB read limit or the upload is refused with 413 before anything is written; node ids are never
cut, so an id longer than 200 characters is rejected (422) instead of silently merging with another node, while
labels and descriptions are cut to short single lines; nested trees stop at depth 64; the write is atomic and
`overwrite=false` is create-if-absent, so of two concurrent uploads of one name the second gets 409 and a failed
upload leaves nothing behind; `graph_query list` is size-bounded (long lists are cut and flagged with `total` and
`truncated`); errors never contain server paths. Graphs
are data only and never enter the taxonomy or the routing index. If tenant policy denies the caller a graph that is
registered as a connection (`external:graph.<id>`, see `docs/TAXONOMY_GRAPH_IMPORT.md`), chat will not list it, default to it
or reveal it. An uploaded graph is not registered as a connection, so it has no per-graph policy: anyone who can use the
`codebase_graph` skill can query it.

## Limits

- Query answers are only as good as the file. Unnamed or generic relations (`related_to`) give weak answers.
- A graph is queried by the `codebase_graph` skill. The skill name is historical: it covers ontologies too.
- Uploading a graph does not create routing. To send questions to skills, import a taxonomy
  (`docs/TAXONOMY_GRAPH_IMPORT.md`).
- Not verified: the Upload graph screen clicked through in a browser, and the skill through a live LLM turn.
  The upload endpoints and the tool are tested end to end with the same subprocess the loader uses.
