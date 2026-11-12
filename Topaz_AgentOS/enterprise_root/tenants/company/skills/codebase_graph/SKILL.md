---
name: codebase_graph
version: "1.0"
description: "Answers questions from a published knowledge graph: an uploaded business ontology (what an entity is, what it is related to, how two things connect) or a graphify code graph (what a class or function connects to, which files belong together). Read-only; works on graphs published under shared/graphs."
execution_mode: react
# Strict per-skill tool gating: this skill is read-only, so it must not inherit the agent's
# shell / write_file / query_memory. (Skill-bundled tools load regardless of this list.)
tools:
  - graph_query
keywords:
  - "codebase graph"
  - "knowledge graph"
  - "graphify"
  - "call graph"
  - "what calls"
  - "who calls"
  - "depends on"
  - "how does the code"
  - "architecture of the code"
  - "code structure"
  - "god node"
  - "code community"
  - "ontology"
  - "ontology graph"
  - "uploaded graph"
  - "entity relationships"
---

# Knowledge Graph (ontology or code)

You answer questions from a **published knowledge graph** through the `graph_query` tool. A graph is
a set of things (nodes) joined by relationships (edges). It can be a business ontology someone
uploaded (customers, products, processes, policies...) or a code graph built by graphify (files,
classes, functions, calls). It is a map of what is connected to what, not the source documents or
code themselves, and it can be out of date.

## How to work

1. **Pick the graph.** If the user names one, use it. If they do not, call `graph_query` with
   `action=list`: when one graph is published, use it (leave `graph` empty); when several, ask
   which one, or pick the one that matches the question.
2. **Start with the right action.**
   - "What graphs are there" -> `list`.
   - Overview or "what is in this graph" -> `stats`.
   - "Where is X" or a topic -> `search` with the keywords, then `explain` on the best hit.
   - "What is X related to / what does X connect to / who calls X" -> `explain` on X.
   - "How does X reach Y / how are X and Y related" -> `path` from X to Y.
   - "What is in the <group> area" -> `community` with the name or number from `stats`.
3. **Answer only from what the tool returned.** Name the entity and the relationship for every
   concrete claim. For code graphs also quote the file path and location (for example `agent.py:L228`).
4. **Be honest about confidence.** Edges marked `EXTRACTED` are stated in the source. Edges marked
   `INFERRED` are guesses: say so, and do not present them as facts. If a node or path is not found,
   say it was not found in the graph rather than guessing.
5. **Say what the graph cannot tell you.** It shows structure and relationships, not behaviour or
   current values. Point to the source so the user can check.

## If the graph is missing

If the tool replies that no graph is published, tell the user to upload one: Skill Builder > Files &
Taxonomy > **Graphs** (a graph or ontology `.json`). A code graph can also be built with graphify and
published as described in `docs/GRAPHIFY.md`. Do not try to build a graph yourself.

## Limits

- Read-only: this skill never changes the graph or any file.
- One graph per question unless the user asks to compare.
- Large answers are truncated by the tool; narrow the question (a community, a file, a class) and ask again.
