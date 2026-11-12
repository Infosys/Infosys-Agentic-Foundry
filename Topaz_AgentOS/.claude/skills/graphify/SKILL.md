---
name: graphify
description: Build, refresh and query the AgentOS codebase knowledge graph with graphify, and publish it into AgentOS (taxonomy import from the graph, and the codebase_graph skill). Use when the user says /graphify, asks how the code fits together (what calls X, how A reaches B, which files belong together), or wants the graph loaded into AgentOS or Neo4j.
---

# /graphify for this repository

[graphify](https://github.com/safishamsi/graphify) turns the code into a queryable knowledge graph
(communities, call/import/inheritance edges, an EXTRACTED vs INFERRED confidence on every edge).
This skill holds the **AgentOS conventions**; the graphify tool does the work.

## Prerequisites (once per machine)

```bash
pip install graphifyy          # the graphify CLI + library
graphify install               # copies graphify's own /graphify skill to your Claude config
```

If you already installed graphify's skill, yours takes precedence over this project skill. That is fine:
everything below still applies, because the scope and publish steps live in this repo.

## Scope: `.graphifyignore`

The repo ships a `.graphifyignore` that limits a build to first-party code
(`agent_os/`, `IAF-Agent-Skills/`, `IAF-Agent-Studio/`, about 370 files) and leaves out
docs, tenant data, HTML and YAML. That is a **pure AST pass: no LLM, no tokens**. Remove lines from
`.graphifyignore` only if you want prose and config in the graph (that needs semantic extraction, which costs tokens).

## Build and refresh

From the repo root:

```bash
graphify update .              # re-extract code and rebuild graph.json + GRAPH_REPORT.md (no LLM)
graphify cluster-only .        # re-run clustering on the existing graph
graphify hook install          # optional: rebuild automatically after every commit
```

Output goes to `graphify-out/` (git-ignored; never commit it). A first full build with community
names uses the `/graphify` skill itself, which may call a model to label communities.

## Ask questions (no rebuild)

```bash
graphify query "how does SkillAgent reach the kernel"
graphify path "SkillAgent" "SafeKernel"
graphify explain "HookRunner"
```

Answer only from what the graph returns, quote the file and location, and say when an edge is `INFERRED`.
If `graphify-out/graph.json` does not exist, say so and build it first; do not guess.

## Publish into AgentOS

AgentOS reads graphs from the tenant's shared storage. It never builds them.

1. Copy the build output to the tenant's graph folder (runtime data, not committed):

   ```bash
   mkdir -p <DATA_ROOT>/tenants/<tenant>/shared/graphs/agentos
   cp graphify-out/graph.json graphify-out/.graphify_labels.json <DATA_ROOT>/tenants/<tenant>/shared/graphs/agentos/
   ```

2. Register it once as a `type: graph` resource in the tenant's `security/external_access.yaml`:

   ```yaml
   - id: external:graph.agentos_code
     label: AgentOS code graph
     type: graph
     engine: graphify
     path: /shared/graphs/agentos/graph.json
   ```

3. Use it:
   - **Skill Builder > Taxonomy > Graph**: choose the connection, group by communities or by folder,
     preview, assign a skill to every section, then Import. (graphify has no skill information, so a
     person assigns the skills.)
   - **Ask in chat**: the `codebase_graph` skill answers questions from the published graph
     (`graph_query` tool, graph name `agentos`).

## Optional: Neo4j

graphify can also export to Neo4j (see its `--neo4j` / `--neo4j-push` options). A code graph is not a
business hierarchy, so for taxonomy import prefer the `graphify` engine above. Use Neo4j when you want
to run your own Cypher queries over the code graph.

## Rules

- `graphify-out/` and the tenant `shared/graphs/` folders are generated data: do not commit them.
- The graph is structural and can be stale. Rebuild after large changes (`graphify update .`).
- Never put credentials or secrets into the corpus; graphify skips files it detects as sensitive,
  but check `GRAPH_REPORT.md` after a build.

Full runbook: `docs/GRAPHIFY.md`.
