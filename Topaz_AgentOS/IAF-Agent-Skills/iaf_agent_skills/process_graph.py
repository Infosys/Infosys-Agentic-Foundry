"""Process-graph loader + compiler (Phase 1 core).

Loads an authored process-graph YAML (see design/process_graphs/PROCESS_GRAPH_SPEC.md), validates it,
and compiles its NON-CONVERGENT core to a planner plan dict — `{"steps": [{id, skill, task,
depends_on}]}` — which the existing `PlannerEngine.execute_plan` runs (nodes = child skills, in their
own execution modes).

Convergence + conditional semantics are Phase-3 and are intentionally NOT executed here:
  - `when: fail` (loop-back) edges are skipped (a `pass`/`always` edge still forms the DAG).
  - a `converge` block is honored only as "run the DAG once" for now.
This lets an authored graph run its DAG today and gain iteration later WITHOUT changing the file.

Layering: pure/offline — no engine, UI, or network deps (yaml only). The agent's `_run_graph`
dispatch (Studio/engine layer) calls `load_graph` + `compile_to_plan`, then hands the plan to the
existing executor. Fail-safe: every problem raises `ProcessGraphError`, which the caller catches and
falls back to ReAct.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import yaml

logger = logging.getLogger(__name__)

API_VERSION = "agentos/process-graph/v1"


class ProcessGraphError(ValueError):
    """Raised on any load/validation/compile problem (caller falls back to ReAct)."""


def load_graph(path: str) -> dict:
    """Read + validate a process-graph YAML file. Raises ProcessGraphError on any issue."""
    try:
        with open(path, encoding="utf-8") as fh:
            g = yaml.safe_load(fh) or {}
    except FileNotFoundError as e:
        raise ProcessGraphError(f"graph file not found: {path}") from e
    except Exception as e:
        raise ProcessGraphError(f"could not parse graph YAML {path}: {e}") from e
    validate_graph(g)
    return g


def validate_graph(g: dict) -> None:
    """Structural + semantic validation (mirrors the JSON Schema + semantic rules in the spec)."""
    if not isinstance(g, dict):
        raise ProcessGraphError("graph must be a mapping")
    if g.get("apiVersion") != API_VERSION:
        raise ProcessGraphError(f"apiVersion must be '{API_VERSION}'")
    for req in ("name", "nodes", "edges"):
        if req not in g:
            raise ProcessGraphError(f"missing required field: {req}")
    if not g["nodes"]:
        raise ProcessGraphError("graph has no nodes")

    ids = [n.get("id") for n in g["nodes"]]
    if len(ids) != len(set(ids)):
        raise ProcessGraphError("duplicate node id")
    nodes = {n["id"]: n for n in g["nodes"]}
    for n in g["nodes"]:
        if not n.get("id"):
            raise ProcessGraphError("a node is missing 'id'")
        if not n.get("skill"):
            raise ProcessGraphError(f"node '{n['id']}' is missing 'skill'")

    for e in g["edges"]:
        froms = e["from"] if isinstance(e.get("from"), list) else [e.get("from")]
        for f in froms:
            if f not in nodes:
                raise ProcessGraphError(f"edge.from references unknown node: {f}")
        if e.get("to") not in nodes:
            raise ProcessGraphError(f"edge.to references unknown node: {e.get('to')}")
        if e.get("when") in ("pass", "fail"):
            src = e["from"] if isinstance(e["from"], str) else None
            srcnode = nodes.get(src) if src else None
            if not srcnode or srcnode.get("role") != "verifier":
                raise ProcessGraphError(
                    f"edge with when={e['when']} must originate from a single verifier node (got {e.get('from')})")

    # Grounding: independent_verifier — a verifier must not share a skill with a node it grades.
    if (g.get("grounding") or {}).get("independent_verifier"):
        verifiers = {i for i, n in nodes.items() if n.get("role") == "verifier"}
        for e in g["edges"]:
            if e.get("to") in verifiers:
                froms = e["from"] if isinstance(e["from"], list) else [e["from"]]
                vskill = nodes[e["to"]]["skill"]
                if any(nodes[f]["skill"] == vskill for f in froms):
                    raise ProcessGraphError(
                        f"grounding.independent_verifier: verifier '{e['to']}' shares skill "
                        f"'{vskill}' with a node it grades")

    # Grounding: frozen must name real top-level fields.
    for f in (g.get("grounding") or {}).get("frozen", []):
        if f not in g:
            raise ProcessGraphError(f"grounding.frozen names unknown field: {f}")


def compile_to_plan(g: dict, input_overrides: dict | None = None) -> dict:
    """Compile a process graph to a `{"steps": [...]}` plan for the planner executor.

    Each node → a step {id, skill, task, depends_on, role}; `depends_on` is derived from incoming
    `always`/`pass` edges. `when: fail` (loop-back) edges stay OUT of `depends_on` (so the topological
    sort / cycle-check pass); the convergence executor handles them. `{{inputs.<name>}}` in tasks is
    substituted from graph input defaults; `{{<node>.result}}` is left for the executor to interpolate.

    When the graph declares a `converge` block, the returned plan also carries `plan["graph_meta"]`
    (verifier id, pass_when, scope, downstream ids, bounds, grounding) — the signal that
    `agent._run_graph` should use the convergence executor (`PlannerEngine.execute_graph`) instead of
    the one-shot `execute_plan`. No `converge` → no `graph_meta` → the P1 one-shot path (unchanged).
    """
    nodes = {n["id"]: n for n in g["nodes"]}
    deps: dict[str, list] = {nid: [] for nid in nodes}
    skipped_conditional = 0
    for e in g["edges"]:
        if e.get("when") == "fail":
            skipped_conditional += 1
            continue  # loop-back is Phase-3 (convergence executor)
        froms = e["from"] if isinstance(e["from"], list) else [e["from"]]
        for f in froms:
            if f not in deps[e["to"]]:
                deps[e["to"]].append(f)

    inputs = {i["name"]: i.get("default", "") for i in g.get("inputs", [])}
    if input_overrides:
        for k, v in input_overrides.items():
            if k in inputs and v:
                inputs[k] = v

    def _sub_inputs(task: str) -> str:
        return re.sub(r"\{\{\s*inputs\.(\w+)\s*\}\}",
                      lambda m: str(inputs.get(m.group(1), m.group(0))), task or "")

    steps = [
        {"id": nid, "skill": n["skill"], "task": _sub_inputs(n.get("task", "")),
         "depends_on": deps[nid], "role": n.get("role", "worker")}
        for nid, n in nodes.items()
    ]

    plan = {"steps": steps, "goal": g.get("name", "process_graph"), "source": "process_graph"}

    converge = g.get("converge")
    if converge:
        plan["graph_meta"] = _build_graph_meta(g, nodes)
    elif skipped_conditional:
        # No converge block but conditional edges exist — they can't gate without the executor.
        logger.info("process_graph '%s': %d conditional (when:fail) edge(s) ignored (no converge block).",
                    g.get("name"), skipped_conditional)

    return plan


def _build_graph_meta(g: dict, nodes: dict) -> dict:
    """Extract convergence/verifier metadata for the convergence executor (only when `converge` set)."""
    converge = dict(g.get("converge") or {})
    scope = converge.get("scope") or list(nodes.keys())
    verifier_id = str(converge.get("until", "")).split(".")[0]
    vnode = nodes.get(verifier_id, {})
    pass_when = (vnode.get("verdict") or {}).get("pass_when", "PASS")
    grounding = g.get("grounding") or {}

    on_exhausted = converge.get("on_exhausted", "escalate_to_human")
    # Grounding: escalate_on_exhausted is a frozen guard — it OVERRIDES a softer on_exhausted.
    if grounding.get("escalate_on_exhausted"):
        on_exhausted = "escalate_to_human"

    return {
        "converge": {
            "scope": scope,
            "max_loops": int(converge.get("max_loops", 1) or 1),
            "carry_feedback": converge.get("carry_feedback"),
            "on_exhausted": on_exhausted,
            "max_concurrency": int(converge.get("max_concurrency", 1) or 1),
        },
        "verifier_id": verifier_id,
        "pass_when": pass_when,
        "downstream_ids": [nid for nid in nodes if nid not in scope],
        "grounding": grounding,
        "goal": g.get("goal", g.get("name", "")),
    }
