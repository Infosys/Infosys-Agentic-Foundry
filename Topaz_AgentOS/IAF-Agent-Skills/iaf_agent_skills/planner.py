"""
DAG Planner Module — Runtime plan generation and execution for multi-domain queries.

Sits BETWEEN router and ReAct agent. When the router detects a multi-domain query
(or the user explicitly requests a plan), PlannerEngine:
  1. Generates a structured DAG plan via LLM
  2. Presents it for user confirmation
  3. Executes each step by calling agent.run() per skill
  4. Tracks per-step status (pending → running → done/failed/skipped)

Usage:
    from .planner import PlannerEngine

    engine = PlannerEngine(llm=light_llm)
    plan = engine.generate_plan(query, detected_domains, available_skills)
    display = engine.format_plan_for_display(plan)
    # ... user confirms ...
    plan["confirmed"] = True
    result = engine.execute_plan(plan, agent)
"""

import json
import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Hard ceiling on steps in a single plan to prevent runaway LLM output
MAX_PLAN_STEPS = 10


def build_planner_context(ectx: dict) -> str:
    """
    Convert entity_registry.collect_context() output into structured NL text
    suitable for both the planner prompt and the plan critic.

    Extracts only what an LLM needs for planning:
      - Resolved entity names + owning skill (capped at 10)
      - Process relationships / ordering rules (capped at 15)

    Raw json.dumps(_ectx) is intentionally NOT used here because it includes
    routing internals, raw node_ids, embedding metadata, and 50+ tree nodes
    — all of which dilute the LLM context without adding planning value.

    Args:
        ectx: Dict returned by entity_registry.collect_context().

    Returns:
        Multi-line NL string, or "" if ectx is empty/None.
    """
    if not ectx:
        return ""

    lines = []

    # 1. Resolved entities — display name + node type + owning skill (capped)
    tree = ectx.get("tree_context", [])
    if tree:
        lines.append("Resolved entities:")
        for node in tree[:10]:
            name = node.get("display_name") or node.get("node_id", "")
            skill = node.get("skill_name", "")
            ntype = node.get("node_type", "")
            skill_str = f"  → skill: {skill}" if skill else ""
            lines.append(f"  - [{ntype}] {name}{skill_str}")

    # 2. Process relationships — ordering / trigger rules (capped)
    rels = ectx.get("process_relationships", [])
    if rels:
        lines.append("\nProcess relationships:")
        for rel in rels[:15]:
            lines.append(f"  {rel}")

    return "\n".join(lines)


class PlannerEngine:
    """
    Runtime DAG planner for multi-domain/complex queries.

    Generates a structured execution plan via LLM, validates it,
    then executes steps in dependency order by calling agent.run().
    """

    def __init__(self, llm):
        """
        Args:
            llm: LangChain-compatible chat model (e.g. AzureChatOpenAI).
                 Recommend using light_llm (gpt-4o-mini) for fast plan generation.
        """
        self.llm = llm


    def generate_plan(
        self,
        query: str,
        detected_domains: List[str],
        available_skills: List[str],
        skill_descriptions: Optional[Dict[str, str]] = None,
        existing_plan: Optional[Dict[str, Any]] = None,
        entity_context: str = "",
    ) -> Dict[str, Any]:
        """
        Generate a DAG execution plan for a multi-domain query.

        Args:
            query: The original user query.
            detected_domains: Skills detected by the router as relevant.
            available_skills: All skills the agent can access.
            skill_descriptions: Optional {skill_name: description} for better LLM context.
            existing_plan: Optional existing plan dict. When provided, the LLM is
                instructed to preserve all step IDs, skills, and depends_on relationships
                and only apply the user's requested modification.
            entity_context: Raw JSON string from entity_registry.collect_context().
                Passed as-is into the prompt — LLM interprets structure.

        Returns:
            Plan dict with keys: plan_id, goal, steps, created_at, confirmed.
            On error: dict with "error" key.
        """
        # Input validation
        if not query or not query.strip():
            return {"error": "Cannot generate plan for empty query."}

        if not available_skills:
            return {"error": "No available skills to plan with."}

        skills_desc = ""
        for skill in available_skills:
            desc = (skill_descriptions or {}).get(skill, "")
            skills_desc += f"  - {skill}: {desc}\n" if desc else f"  - {skill}\n"

        domains_str = ", ".join(detected_domains) if detected_domains else "auto-detect"

        # When an existing plan is supplied, inject it with strict preservation rules
        # so the LLM makes targeted edits rather than regenerating from scratch.
        existing_plan_block = ""
        if existing_plan:
            existing_steps_json = json.dumps(existing_plan.get("steps", []), indent=2)
            existing_plan_block = f"""
EXISTING PLAN (you are MODIFYING this — do NOT regenerate from scratch):
{existing_steps_json}

Modification rules:
- Preserve ALL step "id" values exactly as-is.
- Preserve ALL "skill" values exactly as-is unless the modification explicitly requires a different skill.
- Preserve ALL "depends_on" references exactly as-is unless the modification changes dependencies.
- Apply ONLY the change the user requested. Leave everything else unchanged.
- If adding a step, assign it a new unique id and update depends_on for affected steps.
- If removing a step, update depends_on references in remaining steps accordingly.
"""

        entity_context_block = f"""
Entity & Process Context (resolved from ontology — use this to assign correct skills and write accurate task descriptions):
{entity_context}
""" if entity_context else ""

        prompt = f"""You are a plan generator for a multi-skill agent system.

The user asked: "{query}"

Detected domains: [{domains_str}]
{entity_context_block}
Available skills:
{skills_desc}
{existing_plan_block}
Generate an execution plan as JSON. Each step runs independently unless it depends on a prior step's output.
Rules:
- Each step MUST have: "id" (unique string), "skill" (from available skills), "task" (what to tell the skill), "depends_on" (list of step ids it needs results from).
- Use "depends_on": [] for independent steps.
- If multiple domains are needed, create one step per domain, then a final synthesis step (skill="general") that depends on all prior steps.
- Keep plans concise — maximum {MAX_PLAN_STEPS} steps.
- Keep each task to 1-2 concise sentences. The skill already has domain expertise — describe WHAT to do, not HOW to format every field.
- Use {{{{step_id.result}}}} in a task to reference a prior step's output.

Respond with ONLY valid JSON (no markdown, no explanation):
{{"steps": [...]}}"""

        try:
            response = self.llm.invoke(prompt)
            try:
                import llm_tracker as _lt
                _lt.record("planner", response, 0.0, getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', '')))
            except Exception:
                pass
            raw = response.content.strip()

            # Strip markdown code blocks if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = json.loads(raw)
            steps = parsed.get("steps", [])

            if not steps:
                return {"error": "LLM returned empty plan."}

        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Planner LLM returned invalid JSON: %s", e)
            return {"error": "Failed to parse plan from LLM"}
        except Exception as e:
            logger.error("Planner LLM call failed: %s", e)
            return {"error": "Plan generation failed"}

        for step in steps:
            step.setdefault("depends_on", [])
            step.setdefault("status", "pending")

        plan = {
            "plan_id": f"plan_{uuid.uuid4().hex[:12]}",
            "goal": query,
            "steps": steps,
            "created_at": datetime.now().isoformat(),
            "confirmed": False,
        }

        errors = self.validate_plan(plan, available_skills=available_skills)
        if errors:
            return {"error": f"Generated plan has issues: {'; '.join(errors)}"}

        return plan


    def validate_plan(
        self,
        plan: Dict[str, Any],
        available_skills: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Validate a plan for structural correctness.

        Returns:
            List of error strings. Empty list = valid.
        """
        errors = []
        steps = plan.get("steps", [])

        if len(steps) > MAX_PLAN_STEPS:
            errors.append(f"Plan exceeds max {MAX_PLAN_STEPS} steps (got {len(steps)}).")

        # Check for duplicate IDs
        seen_ids = set()
        for step in steps:
            sid = step.get("id")
            if not sid:
                errors.append("Step missing 'id' field.")
                continue
            if sid in seen_ids:
                errors.append(f"Duplicate step id '{sid}'.")
            seen_ids.add(sid)

        # Check required fields and dependency references
        for step in steps:
            sid = step.get("id", "<unknown>")
            if not step.get("skill"):
                errors.append(f"Step '{sid}' missing 'skill' field.")
            if not step.get("task"):
                errors.append(f"Step '{sid}' missing 'task' field.")
            for dep in step.get("depends_on", []):
                if dep not in seen_ids:
                    errors.append(f"Step '{sid}' depends on unknown step '{dep}'.")

        # Check for unknown skills
        if available_skills:
            valid_set = set(available_skills)
            for step in steps:
                skill = step.get("skill", "")
                if skill and skill not in valid_set:
                    errors.append(f"Unknown skill '{skill}' in step '{step.get('id', '?')}'.")

        # Check for circular dependencies via topological sort
        if not errors:  # Only check if no structural errors above
            cycle_err = self._detect_cycle(steps)
            if cycle_err:
                errors.append(cycle_err)

        return errors

    def _detect_cycle(self, steps: List[Dict]) -> Optional[str]:
        """Detect circular dependencies using Kahn's algorithm (topological sort)."""
        adjacency = {}  # step_id -> list of step_ids that depend on it
        in_degree = {}

        for step in steps:
            sid = step["id"]
            adjacency.setdefault(sid, [])
            in_degree.setdefault(sid, 0)

        for step in steps:
            sid = step["id"]
            for dep in step.get("depends_on", []):
                adjacency.setdefault(dep, []).append(sid)
                in_degree[sid] = in_degree.get(sid, 0) + 1

        # Start with nodes that have no dependencies
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(steps):
            return "Circular dependency detected in plan steps."
        return None


    def format_plan_for_display(self, plan: Dict[str, Any]) -> str:
        """
        Format a plan as a human-readable numbered list for user confirmation.

        Returns:
            Multi-line string showing each step with skill, task, and dependencies.
        """
        lines = [f"**Execution Plan** — {plan.get('goal', 'N/A')}\n"]

        for i, step in enumerate(plan.get("steps", []), 1):
            deps = step.get("depends_on", [])
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "done": "✅",
                "failed": "❌",
                "skipped": "⏭️",
            }.get(step.get("status", "pending"), "⏳")

            lines.append(f"\n{status_icon} **Step {i}** `[{step.get('skill', '?')}]`")
            lines.append(f"   {step.get('task', '')}")
            if deps:
                lines.append(f"   _depends on: {', '.join(deps)}_")

        lines.append(f"\n---\nPlan ID: `{plan.get('plan_id', 'N/A')}`")
        lines.append("Reply **approve** to execute, **reject** to cancel, or describe modifications.")
        return "\n".join(lines)


    def execute_plan(
        self,
        plan: Dict[str, Any],
        agent,
        agent_factory=None,
        status_callback=None,
    ) -> Dict[str, Any]:
        """
        Execute a confirmed plan by running each step via agent.run().

        Steps are executed in topological order (respecting depends_on).
        Independent steps run sequentially (parallel execution is a future enhancement).
        Results from prior steps are interpolated into subsequent step tasks via {{step_id.result}}.

        Args:
            plan: Confirmed plan dict (must have confirmed=True).
            agent: SkillAgent instance (used as fallback if agent_factory is None).
            agent_factory: Optional callable(skill_name) -> SkillAgent. When provided,
                a fresh agent is created per step, giving each step isolated SQLite
                connections and a clean conversation history. This prevents the
                background memory-logging thread from the previous step racing with
                the next step's SQLite reads (segfault risk on shared connections).
            status_callback: Optional callable for progress updates.

        Returns:
            Updated plan dict with per-step status/results and combined_result.
            On error: dict with "error" key.
        """
        if not plan.get("confirmed"):
            return {"error": "Plan must be confirmed before execution. Send plan to user first."}

        steps = plan.get("steps", [])
        if not steps:
            return {"error": "Plan has no steps."}

        # Pre-validate
        errors = self.validate_plan(plan)
        if errors:
            return {"error": f"Invalid plan: {'; '.join(errors)}"}

        # Build execution order via topological sort
        exec_order = self._topological_sort(steps)
        results_map = {}  # step_id -> result string

        for step_id in exec_order:
            step = next(s for s in steps if s["id"] == step_id)

            # Check if dependencies all succeeded
            failed_deps = [
                dep for dep in step.get("depends_on", [])
                if self._get_step(steps, dep).get("status") == "failed"
            ]
            if failed_deps:
                step["status"] = "skipped"
                step["result"] = f"Skipped: dependency {', '.join(failed_deps)} failed."
                results_map[step_id] = step["result"]
                logger.info("PLANNER: Skipping step '%s' — failed deps: %s", step_id, failed_deps)
                if status_callback:
                    status_callback(f"⏭️ Skipping {step_id} (dependency failed)")
                continue

            # Interpolate {{step_id.result}} templates in the task
            task = step["task"]
            task = self._interpolate_results(task, results_map, exclude=step_id)

            step["status"] = "running"
            logger.info("PLANNER: Running step '%s' [%s]: %s", step_id, step["skill"], task[:100])
            if status_callback:
                status_callback(f"🔄 Running step: {step_id} [{step['skill']}]")

            try:
                _runner = agent_factory(step["skill"]) if agent_factory else agent
                result = _runner.run(task, skill_name=step["skill"])
                # agent.run may return (response, tool_calls) tuple
                if isinstance(result, tuple):
                    result = result[0]
                step["status"] = "done"
                step["result"] = str(result)[:4000]  # Truncate large results
                results_map[step_id] = step["result"]
                logger.info("PLANNER: Step '%s' completed (result: %d chars)", step_id, len(step["result"]))
            except Exception as e:
                step["status"] = "failed"
                step["result"] = f"Error: {e}"
                results_map[step_id] = step["result"]
                logger.error("PLANNER: Step '%s' failed: %s", step_id, e)

            if status_callback:
                icon = "✅" if step["status"] == "done" else "❌"
                status_callback(f"{icon} Step {step_id}: {step['status']}")

        combined_parts = []
        for step in steps:
            status_icon = {"done": "✅", "failed": "❌", "skipped": "⏭️"}.get(step["status"], "❓")
            combined_parts.append(
                f"{status_icon} **{step['id']}** [{step['skill']}]: {step.get('result', 'No result')}"
            )

        plan["combined_result"] = "\n\n".join(combined_parts)

        return plan


    def execute_graph(self, plan, graph_meta, agent, agent_factory=None, status_callback=None):
        """Iterate the converge `scope` until the verifier passes (carrying its feedback forward),
        bounded by max_loops; then run downstream steps. On exhaustion, honor on_exhausted:
        escalate_to_human (returns {escalate:True,...} for the caller to raise a HITL card) | fail
        (skip downstream) | best_effort (run downstream with a caveat). Independent steps within a
        level run concurrently when max_concurrency > 1."""
        errors = self.validate_plan(plan)
        if errors:
            return {"error": f"Invalid plan: {'; '.join(errors)}"}
        steps = plan.get("steps", [])
        if not steps:
            return {"error": "Plan has no steps."}
        step_by_id = {s["id"]: s for s in steps}

        cv = graph_meta.get("converge", {}) or {}
        scope_ids = [sid for sid in (cv.get("scope") or list(step_by_id)) if sid in step_by_id]
        downstream_ids = [sid for sid in graph_meta.get("downstream_ids", []) if sid in step_by_id]
        verifier_id = graph_meta.get("verifier_id")
        pass_when = str(graph_meta.get("pass_when", "PASS"))
        max_loops = max(1, int(cv.get("max_loops", 1) or 1))
        carry = cv.get("carry_feedback")
        on_exhausted = cv.get("on_exhausted", "escalate_to_human")
        max_workers = max(1, int(cv.get("max_concurrency", 1) or 1))

        scope_steps = [step_by_id[sid] for sid in scope_ids]
        base_tasks = {sid: step_by_id[sid].get("task", "") for sid in scope_ids}  # clean base per retry

        results_map: Dict[str, str] = {}
        passed, feedback, iterations = False, "", 0
        for it in range(1, max_loops + 1):
            iterations = it
            for sid in scope_ids:
                task = base_tasks[sid]
                if it > 1 and carry and feedback and step_by_id[sid].get("role") != "verifier":
                    task = (task + f"\n\n[Revision {it}] A prior attempt was rejected by the verifier: "
                            + feedback[:800].strip() + " Address these points and try again.")
                step_by_id[sid]["task"] = task
                step_by_id[sid]["status"] = "pending"
            if status_callback:
                status_callback(f"🔁 Convergence iteration {it}/{max_loops}")
            self._run_level_parallel(scope_steps, results_map, agent, agent_factory,
                                     status_callback, max_workers)
            vout = results_map.get(verifier_id, "") or ""
            passed = pass_when.lower() in vout.lower()
            logger.info("GRAPH converge iter %d/%d verdict=%s (verifier=%s, pass_when=%r)",
                        it, max_loops, "PASS" if passed else "FAIL", verifier_id, pass_when)
            if passed:
                break
            feedback = vout

        def _run_downstream():
            for sid in downstream_ids:
                s = step_by_id[sid]
                s["task"] = self._interpolate_results(s.get("task", ""), results_map, exclude=sid)
                s["depends_on"] = [d for d in s.get("depends_on", []) if d in downstream_ids]
                s["status"] = "pending"
            down = [step_by_id[sid] for sid in downstream_ids]
            if down:
                self._run_level_parallel(down, results_map, agent, agent_factory,
                                         status_callback, max_workers)

        plan["iterations"] = iterations
        if passed:
            _run_downstream()
            plan["converged"] = True
            plan["combined_result"] = self._assemble_combined(steps)
            return plan

        # Verifier never passed within the bound.
        plan["converged"] = False
        if on_exhausted == "best_effort":
            _run_downstream()
            plan["combined_result"] = (
                f"⚠️ Verifier did not pass after {iterations} attempt(s); result produced on a "
                f"best-effort basis.\n\n" + self._assemble_combined(steps))
            return plan
        if on_exhausted == "fail":
            plan["combined_result"] = (
                f"❌ Verifier '{verifier_id}' did not pass after {iterations} attempt(s); downstream "
                f"steps were not run.\n\n" + self._assemble_combined(steps))
            return plan
        # escalate_to_human (default): signal the caller to raise a HITL card.
        plan["escalate"] = True
        plan["reason"] = f"Verifier '{verifier_id}' did not pass after {iterations} attempt(s)."
        plan["feedback"] = feedback
        plan["combined_result"] = self._assemble_combined(steps)
        return plan

    def _run_level_parallel(self, steps, results_map, agent, agent_factory=None,
                            status_callback=None, max_workers=1):
        """Run `steps` respecting `depends_on`, executing independent steps in the same level
        concurrently (bounded by max_workers). max_workers=1 → sequential (parity with execute_plan).
        Mutates each step's status/result and updates results_map under a lock. A failed step marks
        its dependents 'skipped'. Deps outside `steps` are treated as already-satisfied (the caller
        pre-interpolates them), so this never KeyErrors on cross-partition deps."""
        step_by_id = {s["id"]: s for s in steps}
        remaining = [s["id"] for s in steps]
        done_ids: set = set()
        lock = threading.Lock()
        workers = max(1, int(max_workers or 1))

        def _run_one(sid):
            step = step_by_id[sid]
            failed = [d for d in step.get("depends_on", [])
                      if d in step_by_id and step_by_id[d].get("status") == "failed"]
            if failed:
                with lock:
                    step["status"] = "skipped"
                    step["result"] = f"Skipped: dependency {', '.join(failed)} failed."
                    results_map[sid] = step["result"]
                if status_callback:
                    status_callback(f"⏭️ Skipping {sid} (dependency failed)")
                return
            with lock:
                task = self._interpolate_results(step.get("task", ""), dict(results_map), exclude=sid)
            step["status"] = "running"
            logger.info("GRAPH step '%s' [%s]: %s", sid, step["skill"], task[:100])
            if status_callback:
                status_callback(f"🔄 Running step: {sid} [{step['skill']}]")
            try:
                _runner = agent_factory(step["skill"]) if agent_factory else agent
                result = _runner.run(task, skill_name=step["skill"])
                if isinstance(result, tuple):
                    result = result[0]
                with lock:
                    step["status"] = "done"
                    step["result"] = str(result)[:4000]
                    results_map[sid] = step["result"]
            except Exception as e:
                with lock:
                    step["status"] = "failed"
                    step["result"] = f"Error: {e}"
                    results_map[sid] = step["result"]
                logger.error("GRAPH step '%s' failed: %s", sid, e)
            if status_callback:
                icon = "✅" if step_by_id[sid].get("status") == "done" else "❌"
                status_callback(f"{icon} Step {sid}: {step_by_id[sid].get('status')}")

        while remaining:
            level = [sid for sid in remaining
                     if all((d in done_ids) or (d not in step_by_id)
                            for d in step_by_id[sid].get("depends_on", []))]
            if not level:  # unresolved (shouldn't happen post-validate) — avoid deadlock
                level = list(remaining)
            if workers == 1 or len(level) == 1:
                for sid in level:
                    _run_one(sid)
            else:
                with ThreadPoolExecutor(max_workers=min(workers, len(level))) as ex:
                    list(ex.map(_run_one, level))
            for sid in level:
                done_ids.add(sid)
                remaining.remove(sid)
        return results_map

    def _assemble_combined(self, steps) -> str:
        """Build the combined_result string (same shape as execute_plan)."""
        parts = []
        for step in steps:
            icon = {"done": "✅", "failed": "❌", "skipped": "⏭️"}.get(step.get("status"), "❓")
            parts.append(f"{icon} **{step['id']}** [{step['skill']}]: {step.get('result', 'No result')}")
        return "\n\n".join(parts)


    def _topological_sort(self, steps: List[Dict]) -> List[str]:
        """Return step IDs in valid execution order (Kahn's algorithm)."""
        in_degree = {s["id"]: 0 for s in steps}
        adjacency = {s["id"]: [] for s in steps}

        for step in steps:
            for dep in step.get("depends_on", []):
                adjacency[dep].append(step["id"])
                in_degree[step["id"]] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    # Same bounds as WorkflowEngine's mirror of this mechanism (execution.py) — kept identical
    # so behaviour doesn't quietly differ between graph/planned and workflow mode.
    AUTO_CONTEXT_PER_STEP_CHARS = 400
    AUTO_CONTEXT_TOTAL_CHARS = 2500

    def _interpolate_results(self, task: str, results_map: Dict[str, str], exclude: str = "") -> str:
        """Replace {{step_id.result}} placeholders with actual results, THEN prepend an automatic
        summary of every other completed step — same rationale and shape as
        WorkflowEngine._resolve_template in execution.py: an author who never wrote
        `{{step_id.result}}` used to leave a later step with zero knowledge that an earlier one
        ran at all (the INV-2026-500777 class of bug). Covers BOTH execute_plan ("planned" mode)
        and execute_graph ("graph" mode) — they share this one method.

        `exclude` must be the CURRENT step's own id. The converge loop in execute_graph re-runs
        the same step across revision iterations without clearing results_map first, so without
        this the step would see its own previous (possibly rejected-by-the-verifier) attempt
        presented back as if it were a different, trustworthy prior step.
        """
        def _replace(match):
            step_id = match.group(1)
            return results_map.get(step_id, f"[{step_id}: not available]")

        task = re.sub(r"\{\{(\w+)\.result\}\}", _replace, task)

        lines, budget = [], self.AUTO_CONTEXT_TOTAL_CHARS
        for step_id, text in results_map.items():
            if step_id == exclude or not text:
                continue
            text = str(text).strip()
            if len(text) > self.AUTO_CONTEXT_PER_STEP_CHARS:
                text = text[: self.AUTO_CONTEXT_PER_STEP_CHARS].rstrip() + "…"
            line = f"- {step_id}: {text}"
            if budget - len(line) <= 0:
                break
            lines.append(line)
            budget -= len(line)
        if lines:
            task = (task + "\n\n[Context from earlier steps in this run — for reference; use "
                    "{{id.result}} for the exact text]\n" + "\n".join(lines))
        return task

    @staticmethod
    def _get_step(steps: List[Dict], step_id: str) -> Dict:
        """Find a step by ID. Returns empty dict if not found."""
        for s in steps:
            if s["id"] == step_id:
                return s
        return {}
