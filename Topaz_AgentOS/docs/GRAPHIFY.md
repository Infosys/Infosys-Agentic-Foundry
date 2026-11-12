# graphify in AgentOS

> **Audience:** developers and skill authors. **Status:** implemented on `feat/graphify-bridge`
> (stacked on the graph-import PR). Code and tests define behaviour:
> `IAF-Agent-Skills/iaf_agent_skills/graph_import/graphify_adapter.py`,
> `enterprise_root/tenants/company/skills/codebase_graph/`,
> `IAF-Agent-Skills/tests/test_graphify_import.py`, `IAF-Agent-Studio/tests/test_taxonomy_graphify_import.py`,
> `IAF-Agent-Studio/tests/test_codebase_graph_skill.py`.

[graphify](https://github.com/safishamsi/graphify) (MIT) builds a knowledge graph from a folder of code:
nodes for files, classes and functions, edges for `calls`, `imports`, `inherits`, `contains` and more
(each marked `EXTRACTED` = read from the code, or `INFERRED` = a guess), grouped into communities.
Code is extracted with an AST pass: **no LLM, no tokens**.

AgentOS never builds a graph. It **reads** one that you publish, and does two things with it.

```
 graphify (CLI / /graphify skill)         AgentOS
 ───────────────────────────────          ─────────────────────────────────────────────
 graphify update .                         shared/graphs/<name>/graph.json   (published, read-only)
   └─► graphify-out/graph.json  ──copy──►  ├─► Taxonomy ▸ Graph   → preview → assign skills → Import
       .graphify_labels.json               │      (engine: graphify, same screen as Neo4j / Neptune)
                                           └─► codebase_graph skill → graph_query tool → answers in chat
```

## 1. Build the graph

Install once: `pip install graphifyy`, then `graphify install` (copies graphify's own `/graphify` skill into
your Claude config). The repo also ships a project skill (`.claude/skills/graphify/SKILL.md`) with these conventions.

The repo's `.graphifyignore` limits a build to `agent_os/`, `IAF-Agent-Skills/` and `IAF-Agent-Studio/`
and leaves out docs, tenant data, HTML and YAML. Measured with graphify's own file detection:
**372 files, all code, 0 documents** → a pure AST build with no token cost.

```bash
graphify update .        # rebuild graph.json + GRAPH_REPORT.md from the code (no LLM)
graphify hook install    # optional: rebuild after every commit
```

Query it directly (no AgentOS needed): `graphify query "..."`, `graphify path "A" "B"`, `graphify explain "X"`.

## 2. Publish it to a tenant

Graphs live in the tenant's shared storage, never in git (`enterprise_root/**/shared/graphs/` is ignored):

```bash
mkdir -p <DATA_ROOT>/tenants/<tenant>/shared/graphs/agentos
cp graphify-out/graph.json graphify-out/.graphify_labels.json <DATA_ROOT>/tenants/<tenant>/shared/graphs/agentos/
```

`.graphify_labels.json` is optional; it holds the human-readable community names. Without it communities are
called `Community 12`.

## 3a. Build a taxonomy from the graph

Register the graph as a connection in the tenant's `security/external_access.yaml`:

```yaml
- id: external:graph.agentos_code
  label: AgentOS code graph
  type: graph
  engine: graphify
  path: /shared/graphs/agentos/graph.json     # must be under /shared/graphs and end in .json
```

There is **no host and no credential**: the engine reads a file, so there is no network or SSRF surface.
The validator rejects a `graphify` entry that has `hosts`, or a path outside `/shared/graphs/`.

Then Skill Builder ▸ Taxonomy ▸ **Graph**, pick the connection, and choose how to group:

| Mode | Domain (L2) | Section (L3) | Activities |
|---|---|---|---|
| **Group by graph communities** | a graphify community (its label) | a source file | classes / functions in that file |
| **Group by folder** | the first N folders of the path (default 2) | a source file | classes / functions in that file |

Options: only under a folder (`path_prefix`), max domains (largest N kept, default 40), community minimum size
(default 3), folder levels per domain (default 2). It is the same preview screen as Neo4j/Neptune:
a loss report, ranked skill suggestions, and **Import stays disabled until every section has a skill**.

Cleaning applied so the result is useful for routing: docstring/rationale nodes are skipped; dunder methods
(`.__init__()`) are skipped; files with no symbols (empty `__init__.py`) are skipped.

> A code graph describes *code structure*, not business processes. A codebase taxonomy is useful for routing
> questions about the code to a skill such as `codebase_graph`; it is not a substitute for a business taxonomy.

## 3b. Ask questions from the graph (`codebase_graph` skill)

> A graph does not have to come from graphify, and publishing does not need server access: **Upload graph** in
> Skill Builder accepts an ontology JSON and converts it. See `docs/GRAPH_UPLOAD.md`.

The `codebase_graph` skill (registered in the tenant `_index.yaml`) bundles a read-only `graph_query` tool:

| action | use |
|---|---|
| `stats` | counts, relation types, largest communities, most-connected nodes |
| `search` | find nodes by keywords |
| `explain` | one node with its neighbours grouped by relation |
| `path` | shortest connection between two nodes |
| `community` | members of a community by name or number |

The tool: stdlib only; finds the graph by **name** under `<tenant>/shared/graphs/<name>/graph.json` (name
pattern-checked, resolved path must stay inside that folder); the `.graphify_labels.json` sidecar gets the same
treatment (resolved path must stay inside the graph's folder, size-capped); errors never include paths and a
malformed file (non-object JSON, bad ids) gives a clean error, never a traceback; never writes; skips docstring
nodes; reports `EXTRACTED`/`INFERRED` on every edge. Replies stay **under the skill loader's 10 KB stdout cap**
(longer ones are shrunk list by list and flagged `truncated`, never cut mid-JSON). `explain` neighbours and every
`path` step carry node id, file and location so same-named symbols (many classes define `.run()`) can be told apart
and cited.
The skill instructs the model to answer only from the tool's output and to quote file and location.

## 4. Optional: Neo4j

graphify can export to Neo4j (`--neo4j`, `--neo4j-push`; see its docs). For *taxonomy import* use the
`graphify` engine above: a code graph is not a hierarchy a Cypher import can walk from one root. Use Neo4j when
you want to run your own Cypher over the code graph, or to share the graph between tools. The Neo4j and Neptune
engines in `docs/TAXONOMY_GRAPH_IMPORT.md` import *hierarchies*; they were also scale-tested against a real
Neo4j (a 6,526-node tree read in about one second with the 5,000-node cap enforced).

## What was verified

| Check | Result |
|---|---|
| Adapter + mapper on the real 6,823-node / 13,721-edge / 329-community AgentOS graph | both modes run in ~0.2 s; sensible domains (e.g. "Agent Memory", "Skill Execution Engine"); capped and flagged `truncated` |
| `graph_query` run as the loader runs it (subprocess, `IAF_AGENT_ROOT`) on that graph | `stats`, `search`, `explain`, `path` (SkillAgent → SafeKernel in 2 hops) all correct |
| Hostile labels (`### x`, `<!-- skill: admin -->`, newlines) in symbols, files and community names | committed through `/taxonomy-import` and parsed with `TaxonomySignalIndex._parse_file`: nothing forged |
| Graph-name traversal (`../`, `..\`, absolute paths) | rejected; no file outside `shared/graphs` is readable; errors do not leak paths |
| Labels sidecar read (adapter and tool) | confined to the graph's folder and size-capped; covered by a simulated-symlink test; a real-symlink test exists but skips on a machine that cannot create symlinks |
| Symlink escape under `shared/graphs` | protected by `resolve()` + `is_relative_to`; **not exercised with a real symlink here** (the test machine cannot create symlinks; the test skips) |
| Reply through the real skill loader (10 KB cap) | a reply that used to be cut into invalid JSON now fits and parses (`test_graphify_review_findings.py`) |

**Not verified:** the Skill Builder screen in a browser (page JavaScript parses; the flow has not been clicked
through), and the skill running inside a live Studio agent (the tool is exercised as a subprocess, and the loader
discovers it, but not through an LLM turn).

## Limits and notes

- graph.json up to 64 MB; up to 5,000 nodes per taxonomy preview.
- The graph can be stale. Re-publish after `graphify update .`.
- graphify's output format is a third-party contract (`nodes[]`/`links[]` node-link JSON). Tested against graphify 0.9.11.
