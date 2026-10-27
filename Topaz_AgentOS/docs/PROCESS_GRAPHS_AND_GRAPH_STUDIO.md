# Process Graphs & Graph Studio

> **Audience:** skill authors (admins) and platform devs. **Status:** shipped on `feat/rlm-integration`.
> Verify against `IAF-Agent-Skills/iaf_agent_skills/process_graph.py`, `planner.py::execute_graph`, and
> `routers/skills.py`. Full schema: [design/process_graphs/PROCESS_GRAPH_SPEC.md](../design/process_graphs/PROCESS_GRAPH_SPEC.md).

## What it is
A **process graph** is a *stored* DAG of skill-nodes — a governed, versioned, reusable business
process. It runs as a skill with `execution_mode: graph`, whose `SKILL.md` points at a sibling
`graph.yaml` via `graph_ref: graph.yaml`. Unlike **plan mode** (the router builds a DAG on the fly
per query), a graph is authored once and reused deterministically, and it adds **verifier nodes**
and a **convergence loop** on top of the plain planner.

> Plan vs graph: they share the same engine — `compile_to_plan(graph)` produces the same plan dict
> `execute_plan` consumes; a graph merely adds `plan["graph_meta"]` (verifier + convergence), which
> routes it to `execute_graph`. Plan = *discovery* (ephemeral, LLM-built); graph = *codification*
> (governed, reusable).

## graph.yaml schema (v1)
```yaml
apiVersion: agentos/process-graph/v1
name: ap_ccd_morning_briefing
nodes:
  - {id: ap_report,  skill: rlm_ap_report, role: worker,   task: "Summarise overdue AP…"}
  - {id: ccd_status, skill: ccdops,        role: worker,   task: "Report CCD infra status…"}
  - {id: verify,     skill: general,       role: verifier, task: "Review {{ap_report.result}} and
        {{ccd_status.result}}; reply PASS or FAIL", verdict: {pass_when: PASS}}
  - {id: briefing,   skill: general,       role: worker,   task: "Summarise both artifacts"}
edges:
  - {from: [ap_report, ccd_status], to: verify}   # a level runs in parallel
  - {from: verify, to: briefing, when: pass}       # a when: pass/fail edge MUST start at a verifier
converge:            # optional loop-to-goal
  max_loops: 3
  on_exhausted: escalate_to_human   # escalate_to_human | stop | accept_best
grounding: {independent_verifier: true}            # a verifier can't reuse a node's own skill
```
Rules enforced by `validate_graph` (errors surface verbatim in the UI): required
`apiVersion`/`name`/`nodes`/`edges`; unique node ids; each node needs a `skill`; edges reference
existing nodes; `when: pass|fail` edges must originate from a `role: verifier` node; grounding checks
the independent-verifier rule.

## Execution (P3 convergence)
`planner.py::execute_graph` iterates the `converge` scope until the verifier's output contains
`verdict.pass_when`, carrying the verifier's feedback forward each round. Independent levels run in
parallel. On exhaustion it applies `on_exhausted` — `escalate_to_human` posts a HITL card to Command
Center (see [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md)).

## Authoring options
1. **Graph Studio (recommended)** — the admin-only **🕸 Graphs** tab in `/skill-builder/v2`:
   - **Gallery** of all graph skills (Open / Clone / Delete / Run).
   - **Structured visual editor**: forms for nodes (id, skill palette, worker/verifier, task,
     verdict), edges (from → to, when), and convergence/grounding — kept in sync with a live
     **Mermaid diagram** and an editable **YAML pane** (edit either side).
   - **Draft with AI**: describe the process in English → the [Skill Designer](SKILL_DESIGNER.md)
     drafts the `graph.yaml`.
   - **Templates + cheat-sheet**, inline **Validate**, and **Run ▸** (hands off to the main chat so
     the run streams live in the thinking box + execution trace).
2. **Skill builder mode picker** — pick **🕸 Graph** on the Create/Edit form for a plain
   YAML-editor + live diagram.
3. **By hand** — write `SKILL.md` (`execution_mode: graph`, `graph_ref: graph.yaml`) + `graph.yaml`
   in the skill folder.

## Persistence & governance
`POST/PUT /api/skills` (admin) validate the graph (`validate_graph` + `compile_to_plan`) and write
`graph.yaml` next to `SKILL.md`; `GET /api/skills/{name}` returns `graph_yaml` for editing; clone
copies the graph. Non-admin developers author graphs via the [Skill Designer](SKILL_DESIGNER.md)
review-queue flow (graph.yaml rides through submit → approve).

## Related
- Engine: `process_graph.py`, `planner.py::execute_graph`; UI: `static/js/graph-studio.js`
- Tests: `IAF-Agent-Skills/tests/test_process_graph.py`
- Modes overview: [../IAF-Agent-Skills/docs/execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md)
