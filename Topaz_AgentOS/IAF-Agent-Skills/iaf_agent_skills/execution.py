#!/usr/bin/env python3
"""
Execution Engines for different agentic patterns.

Supports multiple execution modes that can be specified in SKILL.md:
- react: LLM-driven ReAct loop (current default)
- workflow: Deterministic step-by-step execution (no LLM between steps)
- parallel: DAG-based parallel execution
- supervisor: Meta-agent that delegates to worker agents

Usage in SKILL.md:
    ---
    name: ar_ops
    execution_mode: workflow
    steps:
      - name: fetch_data
        action: run_sql_query
        params:
          query: "SELECT * FROM receivables"
      - name: generate_report
        action: shell
        params:
          command: "echo 'Report' > /me/report.md"
    ---
"""

import asyncio
import concurrent.futures
import json
import re
import time
import uuid
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum

import logging
logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Supported execution modes for skills."""
    REACT = "react"           # LLM decides each step (current default)
    WORKFLOW = "workflow"     # Deterministic steps, no LLM between
    PARALLEL = "parallel"     # Run independent steps concurrently
    SUPERVISOR = "supervisor"     # Meta-agent delegates to workers
    PLANNED = "planned"           # DAG planner — runtime multi-skill orchestration
    ORCHESTRATOR = "orchestrator" # Manager LLM loop — goal-driven dynamic dispatch
    RLM = "rlm"                   # Recursive Language Model — code-action over governed tools/sub-LLMs
    GRAPH = "graph"               # Stored, authored process-graph (DAG of skill-nodes) — see process_graph.py


@dataclass
class Step:
    """
    A single step in a workflow or parallel execution.
    
    Supports multiple action types:
    - shell: Execute a shell command
    - skill: Invoke another skill with a specific task
    - condition: Branch based on previous output
    
    Example SKILL.md:
        steps:
          - name: fetch_data
            action: skill
            skill: ar_ops
            task: "Get AR summary for today"
          
          - name: check_threshold
            action: condition
            if: "{{fetch_data.output}}"
            contains: "overdue"
            then: escalate_step
            else: normal_step
          
          - name: normal_step
            action: shell
            params:
              command: "echo 'All good'"
    """
    name: str
    action: str  # 'shell', 'skill', 'condition', 'run_sql_query', etc.
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    # For skill action
    skill: Optional[str] = None
    task: Optional[str] = None
    # For condition action
    condition_if: Optional[str] = None
    contains: Optional[str] = None
    equals: Optional[str] = None
    then_step: Optional[str] = None
    else_step: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Step':
        """Create Step from dictionary (parsed from SKILL.md YAML)."""
        params = data.get('params', {}) or {}
        for _k in ('command', 'script', 'args'):
            if _k in data and _k not in params:
                params = {**params, _k: data[_k]}
        return cls(
            name=data.get('name', 'unnamed'),
            action=data.get('action', 'shell'),
            params=params,
            depends_on=data.get('depends_on', []),
            # Skill action fields
            skill=data.get('skill'),
            task=data.get('task'),
            # Condition action fields
            condition_if=data.get('if'),
            contains=data.get('contains'),
            equals=data.get('equals'),
            then_step=data.get('then'),
            else_step=data.get('else'),
        )


@dataclass
class StepResult:
    """Result from executing a step."""
    name: str
    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: int = 0
    # The task/params AFTER {{step.output}} interpolation — i.e. what the step was
    # actually given. Audit views must show this, not the raw template.
    resolved_input: str = ""


@dataclass
class OrchestratorStep:
    """
    One completed step in an orchestrator run.
    Immutable after being appended to step_log — never modified.
    """
    step_num:    int
    skill_name:  str
    task:        str
    result:      str
    success:     bool
    duration_ms: int
    feedback:    str = ""   # injected by PostStep hook; surfaced to manager LLM
    trace_id:    str = ""   # child trace UUID — links to trace_emitter spans


@dataclass
class OrchestratorDecision:
    """Parsed manager LLM decision for one orchestrator iteration."""
    action:     str         # "call_skill" | "synthesize" | "fail"
    skill_name: str = ""
    task:       str = ""
    reason:     str = ""


class WorkflowEngine:
    """
    Deterministic step execution with skill chaining and conditional branching.
    
    Steps are executed in order. Each step's output is available to subsequent steps
    via the results dictionary. Supports:
    - shell: Execute shell commands
    - skill: Invoke another skill (LLM-powered)
    - condition: Branch based on output content
    
    Example:
        engine = WorkflowEngine(tools_map, agent_factory)
        results = engine.run(steps, status_callback)
    """
    
    def __init__(self, tools_map: Dict[str, Callable], agent_factory: Callable[[str], Any] = None,
                 parent_agent: Any = None):
        """
        Initialize workflow engine.
        
        Args:
            tools_map: Dictionary mapping action names to tool functions
                       e.g., {'shell': shell_func, 'run_sql_query': sql_func}
            agent_factory: Optional function to create skill agents for 'skill' action
        """
        self.tools = tools_map
        self.create_agent = agent_factory
        self.parent_agent = parent_agent
        self.results: Dict[str, StepResult] = {}
        self._steps_by_name: Dict[str, Step] = {}  # For jump targets
        self._skip_until: Optional[str] = None  # For conditional branching
        self.approval_pending = None  # HITL: propagated from child agent
        self.remaining_steps: List[Step] = []  # Steps not yet executed (for HITL resume)
        self.paused_for_approval = False  # True if workflow paused mid-execution
        self.paused_step: Optional[Step] = None  # The step that triggered HITL
        self.paused_child_agent = None  # The child agent that triggered HITL (for state export)
        self._status_callback: Optional[Callable[[Any], None]] = None
    
    def run(
        self,
        steps: List[Step],
        status_callback: Optional[Callable[[str], None]] = None,
        initial_context: Optional[str] = None,
        preserve_existing_results: bool = False,
    ) -> Dict[str, StepResult]:
        """
        Execute all steps in sequence with conditional branching support.

        Args:
            steps: List of Step objects to execute
            status_callback: Optional callback for progress updates
            initial_context: If provided, injected as {{_input.output}} for condition steps
            preserve_existing_results: Keep restored prior step outputs when resuming after HITL

        Returns:
            Dictionary mapping step names to their results
        """
        import time

        if not preserve_existing_results:
            self.results = {}
        self._status_callback = status_callback
        # Inject the original query as _input so condition steps can branch on it
        # (e.g. skip HITL gate on re-run after approval)
        if initial_context is not None:
            self.results["_input"] = StepResult(
                name="_input", success=True, output=initial_context, duration_ms=0
            )
        self._steps_by_name = {s.name: s for s in steps}
        self._skip_until = None
        # Verify-retry (on_block: retry) state — transient, per run. No checkpoint needed for
        # in-run auto-retry; exhaustion re-uses the HITL pause/checkpoint below.
        self._retry_counts = {}       # step.name -> attempts already made
        self._retry_base_tasks = {}   # step.name -> original task (so feedback never compounds)

        i = 0
        while i < len(steps):
            step = steps[i]
            step_num = i + 1
            total = len(steps)
            
            # Handle conditional branching - skip steps until we reach target
            if self._skip_until:
                if step.name == self._skip_until:
                    self._skip_until = None  # Found target, resume execution
                else:
                    logger.debug(f"⏭️ Skipping step '{step.name}' (jumping to '{self._skip_until}')")
                    i += 1
                    continue
            
            if status_callback:
                status_callback(f"Step {step_num}/{total}: {step.name}")
            
            logger.debug(f"⚙️ Workflow step {step_num}/{total}: {step.name} ({step.action})")
            
            start_time = time.time()
            self._last_resolved_input = ""   # reset so a step never inherits the previous one's
            self._retry_requested = None     # cleared each iteration; set by a child on_block:retry

            try:
                result = self._execute_step(step)
                duration_ms = int((time.time() - start_time) * 1000)

                self.results[step.name] = StepResult(
                    name=step.name,
                    success=True,
                    output=result,
                    duration_ms=duration_ms,
                    resolved_input=getattr(self, "_last_resolved_input", "") or "",
                )
                logger.debug(f"✅ Step '{step.name}' completed in {duration_ms}ms")

                rr = getattr(self, "_retry_requested", None)
                if rr:
                    self._retry_requested = None
                    key = step.name
                    self._retry_counts[key] = self._retry_counts.get(key, 0) + 1
                    max_r = max(1, int(rr.get("max_step_retries") or 1))
                    if self._retry_counts[key] <= max_r:
                        base = self._retry_base_tasks.setdefault(key, step.task)
                        fb = str(rr.get("feedback") or rr.get("reason") or "").strip()[:600]
                        step.task = (base + f"\n\n[Verify retry {self._retry_counts[key]}/{max_r}] "
                                     f"The previous attempt FAILED verification: {fb} "
                                     f"Fix this and complete the step correctly.")
                        self.approval_pending = None
                        self.paused_step = None
                        self.paused_child_agent = None
                        if status_callback:
                            status_callback(f"retrying {step.name} ({self._retry_counts[key]}/{max_r}) after verify failure")
                        logger.info("Workflow step '%s' verify-retry %d/%d", step.name, self._retry_counts[key], max_r)
                        continue  # re-run steps[i] WITHOUT advancing i
                    # exhausted → on_exhausted terminal
                    if key in self._retry_base_tasks:
                        step.task = self._retry_base_tasks[key]
                    on_ex = str(rr.get("on_exhausted") or "escalate_to_human").lower()
                    logger.info("Workflow step '%s' verify-retry EXHAUSTED (%d) → %s", step.name, max_r, on_ex)
                    if on_ex == "escalate_to_human" and rr.get("approval_payload"):
                        self.approval_pending = rr["approval_payload"]
                        self.paused_step = step
                        # fall through to the HITL pause block below (sets remaining/paused/break)
                    elif on_ex == "fail":
                        self.results[step.name] = StepResult(
                            name=step.name, success=False, output=str(result or ""),
                            error=f"verify retries exhausted: {rr.get('reason', '')}"[:500],
                            duration_ms=duration_ms,
                            resolved_input=getattr(self, "_last_resolved_input", "") or "",
                        )
                        i += 1
                        continue
                    # best_effort: accept the last output and advance (fall through to i += 1)

                # HITL: Check if this step triggered an approval request
                # If so, pause the workflow — remaining steps run after approval
                if self.approval_pending:
                    self.remaining_steps = steps[i + 1:]
                    self.paused_for_approval = True
                    hitl_msg = (
                        f"awaiting human approval: {self.approval_pending.get('reason', 'Approval required')} "
                        f"approval_id={self.approval_pending.get('approval_id', '')}"
                    )
                    logger.debug(f"⏸️  Workflow PAUSED at step '{step.name}' — {hitl_msg}")
                    logger.debug(f"   Remaining steps: {[s.name for s in self.remaining_steps]}")
                    if status_callback:
                        status_callback(hitl_msg)  # triggers processor HITL detection
                    break  # Exit the loop — don't execute remaining steps
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                error_msg = str(e)
                
                self.results[step.name] = StepResult(
                    name=step.name,
                    success=False,
                    output="",
                    error=error_msg,
                    duration_ms=duration_ms,
                    resolved_input=getattr(self, "_last_resolved_input", "") or "",
                )
                logger.debug(f"❌ Step '{step.name}' failed: {error_msg}")
            
            i += 1
        
        return self.results
    
    def _execute_step(self, step: Step) -> str:
        """Execute a single step based on its action type."""
        
        if step.action == 'skill':
            return self._execute_skill_step(step)
        
        if step.action == 'condition':
            return self._execute_condition_step(step)
        
        # Handle standard tool actions (shell, run_sql_query, etc.)
        tool = self.tools.get(step.action)
        
        if not tool:
            raise ValueError(f"Unknown action: {step.action}. Available: {list(self.tools.keys())}")
        
        # Substitute any {{step_name.output}} references in params
        resolved_params = self._resolve_params(step.params)
        self._last_resolved_input = str(resolved_params)   # audit: post-interpolation

        result = tool(**resolved_params)

        if self.parent_agent is not None and getattr(self.parent_agent, "approval_pending", None):
            self.approval_pending = self.parent_agent.approval_pending
            self.paused_step = step

        return result
    
    def _execute_skill_step(self, step: Step) -> str:
        """Execute a skill step - invoke another skill with a specific task."""
        if not self.create_agent:
            raise ValueError("Skill steps require agent_factory to be provided")
        
        if not step.skill:
            raise ValueError(f"Step '{step.name}' has action='skill' but no 'skill' specified")
        
        task = self._resolve_template(step.task or "Execute skill", exclude=step.name)
        self._last_resolved_input = task   # audit: what the skill actually received

        logger.debug(f"   🎯 Invoking skill '{step.skill}' with task: {task[:80]}...")
        
        agent = self.create_agent(step.skill)
        child_status_callback = self._child_status_callback(step)
        result = agent.run(
            task,
            skill_name=step.skill,
            status_callback=child_status_callback,
        )
        
        # HITL: propagate child approval to engine and save child agent ref
        if getattr(agent, 'approval_pending', None):
            self.approval_pending = agent.approval_pending
            self.paused_step = step
            self.paused_child_agent = agent  # Preserve for state export

        # Verify-retry: propagate a child on_block:retry signal so the loop can re-run this step
        if getattr(agent, '_retry_requested', None):
            self._retry_requested = agent._retry_requested

        return result

    def _child_status_callback(self, step: Step) -> Optional[Callable[[Any], None]]:
        """Tag child skill progress with its workflow step before forwarding."""
        if not self._status_callback:
            return None

        def callback(msg: Any) -> None:
            try:
                if isinstance(msg, dict):
                    enriched = dict(msg)
                    enriched["workflow_step"] = step.name
                    enriched["workflow_action"] = step.action
                    enriched["skill"] = step.skill or ""
                    self._status_callback(enriched)
                else:
                    self._status_callback(f"{step.name}: {msg}")
            except Exception:
                pass

        return callback
    
    def _execute_condition_step(self, step: Step) -> str:
        """Execute a condition step - branch based on output content."""
        check_value = self._resolve_template(step.condition_if or "", exclude=step.name, inject_context=False)
        
        condition_met = False
        
        if step.contains:
            condition_met = step.contains.lower() in check_value.lower()
            logger.debug(f"   🔍 Checking if output contains '{step.contains}': {condition_met}")
        
        elif step.equals:
            condition_met = check_value.strip() == step.equals.strip()
            logger.debug(f"   🔍 Checking if output equals '{step.equals}': {condition_met}")
        
        # Determine which branch to take
        if condition_met and step.then_step:
            self._skip_until = step.then_step
            return f"Condition TRUE → jumping to '{step.then_step}'"
        elif not condition_met and step.else_step:
            self._skip_until = step.else_step
            return f"Condition FALSE → jumping to '{step.else_step}'"
        else:
            return f"Condition evaluated: {condition_met} (no jump specified)"

    AUTO_CONTEXT_PER_STEP_CHARS = 400
    AUTO_CONTEXT_TOTAL_CHARS = 2500

    def _resolve_template(self, template: str, exclude: str = "", inject_context: bool = True) -> str:
        """Resolve {{step_name.output}} references in a string, THEN — for a real task prompt —
        prepend an automatic summary of every other completed step, regardless of whether this
        step's task explicitly referenced any of them.

        Why: the explicit-placeholder mechanism only works if the skill author remembered to
        write `{{intake.output}}` in a later step's task. If they didn't, that step got ZERO
        knowledge that an earlier step ran — this is exactly how INV-2026-500777's case_id
        corruption happened (a step re-derived an identifier from raw text instead of using the
        one an earlier step had already resolved). This makes that class of bug unreachable: a
        step that never wires anything explicitly still sees what ran before it.

        `exclude` must be the CURRENT step's own name. Without it, a verify-retry re-running the
        same step (the retry loop below stores self.results[step.name] BEFORE deciding to retry,
        then re-executes the same step without clearing that entry) would show the step its own
        previous, possibly-wrong attempt as if it were a different, trustworthy prior step —
        reinforcing the same mistake instead of correcting it.

        `inject_context=False` for non-prompt uses — a condition step's `condition_if` is
        compared verbatim against `contains`/`equals`, not read by a model; prepending prose
        there would corrupt the comparison rather than help anything.
        """
        if not template:
            return ""

        result = template
        for step_name, step_result in self.results.items():
            placeholder = f"{{{{{step_name}.output}}}}"
            if placeholder in result:
                result = result.replace(placeholder, step_result.output)

        if not inject_context:
            return result

        auto_context = self._auto_context_block(exclude)
        if auto_context:
            result = f"{result}\n\n{auto_context}"
        return result

    def _auto_context_block(self, exclude: str = "") -> str:
        """Build the '[Context from earlier steps]' block, excluding `exclude` (the step about
        to be resolved) and bounded so a long workflow can't blow out every later step's prompt."""
        lines, budget = [], self.AUTO_CONTEXT_TOTAL_CHARS
        for step_name, step_result in self.results.items():
            if step_name == exclude or step_name == "_input":
                continue
            text = str(step_result.output or "").strip()
            if not text:
                continue
            if len(text) > self.AUTO_CONTEXT_PER_STEP_CHARS:
                text = text[: self.AUTO_CONTEXT_PER_STEP_CHARS].rstrip() + "…"
            line = f"- {step_name}: {text}"
            if budget - len(line) <= 0:
                break
            lines.append(line)
            budget -= len(line)
        if not lines:
            return ""
        return ("[Context from earlier steps in this run — for reference; use "
                "{{name.output}} for the exact text]\n" + "\n".join(lines))
    
    def _resolve_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameter references like {{step_name.output}}.
        
        Allows steps to reference outputs from previous steps:
            command: "echo '{{fetch_data.output}}' > /me/report.md"
        """
        resolved = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                # Replace {{step_name.output}} with actual output
                for step_name, result in self.results.items():
                    placeholder = f"{{{{{step_name}.output}}}}"
                    if placeholder in value:
                        value = value.replace(placeholder, result.output)
            resolved[key] = value
        
        return resolved
    
    def format_summary(self) -> str:
        """Format a summary of all step results."""
        lines = ["## Workflow Execution Summary\n"]
        
        successful = sum(1 for r in self.results.values() if r.success)
        failed = len(self.results) - successful
        total_defined = len(self.results) + len(self.remaining_steps)
        
        lines.append(f"**Total Steps:** {total_defined}")
        lines.append(f"**Executed:** {len(self.results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {failed}")
        
        if self.paused_for_approval:
            lines.append(f"**Status:** ⏸️ PAUSED — awaiting human approval")
            lines.append(f"**Remaining:** {', '.join(s.name for s in self.remaining_steps)}")
        lines.append("")
        
        for name, result in self.results.items():
            status = "✅" if result.success else "❌"
            lines.append(f"{status} **{name}** ({result.duration_ms}ms)")
            
            if result.error:
                lines.append(f"   Error: {result.error}")
            elif result.output:
                # Truncate long outputs
                output = result.output[:200] + "..." if len(result.output) > 200 else result.output
                lines.append(f"   Output: {output}")
        
        return "\n".join(lines)


class ParallelEngine:
    """
    DAG-based parallel execution - run independent steps concurrently.
    
    Steps with no dependencies run in parallel. Steps with depends_on
    wait for their dependencies to complete first.
    
    Supports skill invocation for LLM-powered parallel execution.
    
    Example SKILL.md:
        steps:
          - name: get_ar_data
            action: skill
            skill: ar_ops
            task: "Get AR summary"
          - name: get_invoice_data
            action: skill
            skill: invoice
            task: "Get pending invoices"
          - name: aggregate
            action: skill
            depends_on: [get_ar_data, get_invoice_data]
            skill: general
            task: "Combine: {{get_ar_data.output}} and {{get_invoice_data.output}}"
    """
    
    def __init__(self, tools_map: Dict[str, Callable], agent_factory: Callable[[str], Any] = None,
                 parent_agent: Any = None):
        self.tools = tools_map
        self.create_agent = agent_factory
        self.parent_agent = parent_agent
        self.results: Dict[str, StepResult] = {}
        self.approval_pending = None  # HITL: propagated from child agent
        self.remaining_steps: List[Step] = []   # Steps not yet dispatched (for HITL resume)
        self.paused_for_approval = False        # True if a wave paused mid-execution
        self.paused_step: Optional[Step] = None  # The step that triggered HITL
        self.paused_child_agent = None           # The child agent that triggered HITL (for state export)
        self._step_hitl: Dict[str, tuple] = {}

    async def run(
        self,
        steps: List[Step],
        status_callback: Optional[Callable[[str], None]] = None,
        preserve_existing_results: bool = False,
    ) -> Dict[str, StepResult]:
        """
        Execute steps respecting dependency graph.

        Independent steps run in parallel using asyncio.gather. If any step in a wave
        triggers HITL approval, the engine finishes that wave (already-dispatched
        concurrent steps can't be un-run) then stops before starting the next one —
        `remaining_steps` / `paused_for_approval` / `paused_step` mirror WorkflowEngine's
        pause contract so the same checkpoint/resume shape works for both engines.

        Args:
            preserve_existing_results: keep restored prior-wave results when resuming
                after HITL (mirrors WorkflowEngine.run's parameter of the same name).
        """
        import time

        if not preserve_existing_results:
            self.results = {}
            completed: set = set()   # Successfully completed steps
            failed: set = set()      # Failed steps (dependencies will be skipped)
        else:
            completed = {name for name, r in self.results.items() if r.success}
            failed = {name for name, r in self.results.items() if not r.success}
        self.approval_pending = None
        self.paused_for_approval = False
        self.paused_step = None
        self.paused_child_agent = None
        self.remaining_steps = []
        self._step_hitl = {}
        pending = {s.name: s for s in steps}

        wave = 1
        while pending:
            # Skip steps whose dependencies failed — don't run them at all
            newly_skipped = []
            for name, s in list(pending.items()):
                if s.depends_on and any(d in failed for d in s.depends_on):
                    failed_deps = [d for d in s.depends_on if d in failed]
                    logger.debug(f"⏭️ Skipping step '{name}' — dependency failed: {failed_deps}")
                    self.results[name] = StepResult(
                        name=name,
                        success=False,
                        output="",
                        error=f"Skipped: dependency failed ({', '.join(failed_deps)})",
                        duration_ms=0,
                    )
                    newly_skipped.append(name)
            for name in newly_skipped:
                failed.add(name)
                del pending[name]

            if not pending:
                break

            # Find steps with all dependencies satisfied (successful)
            ready = [
                s for s in pending.values()
                if not s.depends_on or all(d in completed for d in s.depends_on)
            ]

            if not ready:
                # No steps can run — circular dependency
                remaining = list(pending.keys())
                raise ValueError(f"Circular dependency detected. Stuck steps: {remaining}")

            if status_callback:
                step_names = [s.name for s in ready]
                status_callback(f"Wave {wave}: Running {step_names} in parallel")

            logger.debug(f"🔀 Parallel wave {wave}: {[s.name for s in ready]}")

            # Run ready steps in parallel
            async def run_step(step: Step) -> tuple:
                start_time = time.time()
                try:
                    result = await self._execute_step_async(step)
                    duration_ms = int((time.time() - start_time) * 1000)
                    return step.name, StepResult(
                        name=step.name,
                        success=True,
                        output=result,
                        duration_ms=duration_ms
                    )
                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)
                    return step.name, StepResult(
                        name=step.name,
                        success=False,
                        output="",
                        error=str(e),
                        duration_ms=duration_ms
                    )

            batch_results = await asyncio.gather(*[run_step(s) for s in ready])

            for name, result in batch_results:
                self.results[name] = result
                del pending[name]
                if result.success:
                    completed.add(name)
                else:
                    failed.add(name)

                status = "✅" if result.success else "❌"
                logger.debug(f"{status} Parallel step '{name}' completed in {result.duration_ms}ms")

            if self._step_hitl:
                for s in ready:
                    hit = self._step_hitl.get(s.name)
                    if hit and self.approval_pending is None:
                        self.approval_pending, self.paused_child_agent = hit
                        self.paused_step = s
                    elif hit:
                        logger.warning(
                            "Parallel wave %d: step '%s' also triggered HITL approval, but "
                            "this engine only tracks one pending approval at a time — its "
                            "conversation state was not saved and will need to be re-run "
                            "from scratch after the first approval resumes.", wave, s.name,
                        )

            if self.approval_pending:
                self.remaining_steps = list(pending.values())
                self.paused_for_approval = True
                hitl_msg = (
                    f"awaiting human approval: {self.approval_pending.get('reason', 'Approval required')} "
                    f"approval_id={self.approval_pending.get('approval_id', '')}"
                )
                logger.debug(f"⏸️  Parallel execution PAUSED after wave {wave} — {hitl_msg}")
                logger.debug(f"   Remaining steps: {[s.name for s in self.remaining_steps]}")
                if status_callback:
                    status_callback(hitl_msg)  # triggers processor HITL detection
                break  # Don't start the next wave

            wave += 1

        return self.results
    
    async def _execute_step_async(self, step: Step) -> str:
        """Execute a single step - supports skill, shell, and other actions."""
        
        if step.action == 'skill':
            return await self._execute_skill_step_async(step)
        
        # Handle standard tool actions (shell, run_sql_query, etc.)
        tool = self.tools.get(step.action)
        if not tool:
            raise ValueError(f"Unknown action: {step.action}. Available: {list(self.tools.keys())}")
        
        resolved_params = self._resolve_params(step.params)
        result = await asyncio.to_thread(tool, **resolved_params)

        if self.parent_agent is not None and getattr(self.parent_agent, "approval_pending", None):
            self._step_hitl[step.name] = (self.parent_agent.approval_pending, self.parent_agent)

        return result
    
    async def _execute_skill_step_async(self, step: Step) -> str:
        """Execute a skill step in parallel - invoke another skill with a specific task."""
        if not self.create_agent:
            raise ValueError("Skill steps require agent_factory to be provided")
        
        if not step.skill:
            raise ValueError(f"Step '{step.name}' has action='skill' but no 'skill' specified")
        
        # Resolve task template (may reference previous outputs). exclude=step.name for
        # parity with WorkflowEngine, though it's not reachable today (see method docstring).
        task = self._resolve_template(step.task or "Execute skill", exclude=step.name)
        
        logger.debug(f"   🎯 Parallel invoking skill '{step.skill}' with task: {task[:60]}...")
        
        def run_agent():
            agent = self.create_agent(step.skill)
            result = agent.run(task, skill_name=step.skill)
            if getattr(agent, 'approval_pending', None):
                self._step_hitl[step.name] = (agent.approval_pending, agent)
            return result

        return await asyncio.to_thread(run_agent)
    
    # Same bounds as WorkflowEngine's mirror of this mechanism.
    AUTO_CONTEXT_PER_STEP_CHARS = 400
    AUTO_CONTEXT_TOTAL_CHARS = 2500

    def _resolve_template(self, template: str, exclude: str = "") -> str:
        """Resolve {{step_name.output}} references in a string, THEN append an automatic
        summary of every other completed step (from PRIOR waves only — see note below) —
        same mechanism and rationale as WorkflowEngine._resolve_template in this file: an
        author who forgot to write `{{get_ar_data.output}}` in an aggregate step used to leave
        it with zero knowledge that step ever ran (this class's own docstring example needs
        TWO explicit references for a 2-branch aggregate — easy to miss one).

        No self-reference risk exists here today (unlike workflow mode): ParallelEngine has no
        verify-retry, and `self.results[name]` is only written once, in bulk, after a whole
        wave's `asyncio.gather()` completes — never mid-wave. So a step can never see a
        same-wave sibling, and never sees its own name before its first (only) run. `exclude`
        is kept anyway for parity and in case retry is ever added here later.

        Appended, not prepended — proven live on the workflow-mode twin of this method:
        FTS5 entity resolution, the taxonomy-signal matcher, and plan_cache's embedding lookup
        all key off the BEGINNING of the resolved task as a short signature; prepending fed
        them boilerplate instead of the real task.
        """
        if not template:
            return ""

        result = template
        for step_name, step_result in self.results.items():
            placeholder = f"{{{{{step_name}.output}}}}"
            if placeholder in result:
                result = result.replace(placeholder, step_result.output)

        lines, budget = [], self.AUTO_CONTEXT_TOTAL_CHARS
        for step_name, step_result in self.results.items():
            if step_name == exclude:
                continue
            text = str(step_result.output or "").strip()
            if not text:
                continue
            if len(text) > self.AUTO_CONTEXT_PER_STEP_CHARS:
                text = text[: self.AUTO_CONTEXT_PER_STEP_CHARS].rstrip() + "…"
            line = f"- {step_name}: {text}"
            if budget - len(line) <= 0:
                break
            lines.append(line)
            budget -= len(line)
        if lines:
            result = (result + "\n\n[Context from earlier steps in this run — for reference; "
                      "use {{name.output}} for the exact text]\n" + "\n".join(lines))
        return result

    def _resolve_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve parameter references (same as WorkflowEngine)."""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                for step_name, result in self.results.items():
                    placeholder = f"{{{{{step_name}.output}}}}"
                    if placeholder in value:
                        value = value.replace(placeholder, result.output)
            resolved[key] = value
        return resolved


class SupervisorEngine:
    """
    Meta-agent that delegates to worker agents.
    
    The supervisor doesn't execute tasks itself - it spawns child agents
    for each skill and aggregates their results.
    
    Example SKILL.md:
        execution_mode: supervisor
        worker_skills:
          - name: ar_ops
            task: "Generate AR summary..."
          - name: invoice
            task: "List pending invoices..."
    """
    
    def __init__(self, agent_factory: Callable[[str], Any]):
        """
        Initialize supervisor.
        
        Args:
            agent_factory: Function that creates a SkillAgent for a given skill name
        """
        self.create_agent = agent_factory
        self.worker_results: Dict[str, str] = {}
        self.approval_pending = None  # HITL: propagated from child worker
    
    def run(
        self,
        task: str,
        worker_skills: List[Dict[str, str]],
        status_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        Delegate task to each worker skill and aggregate results in parallel.

        Workers run concurrently via ThreadPoolExecutor. If any worker triggers
        HITL approval, it is propagated after all workers complete.

        Args:
            task: The user's original query (fallback if no specific task defined)
            worker_skills: List of worker configs: [{'name': 'ar_ops', 'task': '...'}, ...]
            status_callback: Optional progress callback

        Returns:
            Aggregated response from all workers
        """
        self.worker_results = {}
        valid_workers = [w for w in worker_skills if w.get('name')]

        if not valid_workers:
            return self._aggregate_results()

        if status_callback:
            names = [w['name'] for w in valid_workers]
            status_callback(f"Delegating to workers in parallel: {names}")

        logger.debug(f"👷 Supervisor dispatching {len(valid_workers)} workers in parallel: "
              f"{[w['name'] for w in valid_workers]}")

        def run_worker(worker_config: Dict[str, str]):
            skill_name = worker_config['name']
            specific_task = worker_config.get('task') or task

            logger.debug(f"   🔀 Worker '{skill_name}' started")
            try:
                worker = self.create_agent(skill_name)
                result = worker.run(specific_task, skill_name=skill_name)
                hitl = getattr(worker, 'approval_pending', None)
                logger.debug(f"✅ Worker '{skill_name}' completed")
                return skill_name, result, hitl
            except Exception as e:
                logger.debug(f"❌ Worker '{skill_name}' failed: {e}")
                return skill_name, f"Error: {str(e)}", None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(valid_workers),
            thread_name_prefix="supervisor_worker"
        ) as pool:
            futures = {pool.submit(run_worker, w): w['name'] for w in valid_workers}
            for future in concurrent.futures.as_completed(futures):
                skill_name, result, hitl = future.result()
                self.worker_results[skill_name] = result
                # HITL: propagate any approval from any worker
                if hitl and not self.approval_pending:
                    self.approval_pending = hitl
                    logger.debug(f"⏸️ Worker '{skill_name}' paused for HITL approval")

        # Aggregate results
        return self._aggregate_results()
    
    def _aggregate_results(self) -> str:
        """Combine results from all workers into a single response."""
        lines = ["## Results from Workers\n"]
        
        for skill, result in self.worker_results.items():
            lines.append(f"### {skill.upper()}")
            lines.append(result)
            lines.append("")
        
        return "\n".join(lines)



ORCHESTRATOR_MANAGER_PROMPT = """\
You are an orchestration manager. Your job is to achieve a goal by calling the right \
skills in the right order, one skill at a time.

Available skills:
{skills_list}

Work completed so far:
{step_log}

Original goal:
{goal}

Decide what to do next. Respond with ONLY valid JSON — no markdown, no explanation:

If you need more information from a skill:
{{"action": "call_skill", "skill_name": "<skill>", "task": "<specific task for this skill>", "reason": "<why this skill next>"}}

If you have enough information to answer the goal completely:
{{"action": "synthesize", "reason": "<brief summary of what you have>"}}

If you cannot proceed (repeated failures, required skill unavailable):
{{"action": "fail", "reason": "<what went wrong>"}}

Rules:
- skill_name must be exactly one of the available skill names listed above
- task must be self-contained — include all relevant context, the skill has no memory of prior steps unless you put it in the task
- Do not call the same skill with the identical task twice
- You may call the same skill multiple times with different tasks if needed
- CRITICAL: You are running in a fully automated pipeline. Child skills CANNOT interact with the user. \
Never call a skill asking it to "ask the user" or "request clarification" — the user is not present. \
Instead, make reasonable assumptions about missing parameters (e.g. use the entity name from the goal, \
default to current date, default to all company codes) and call the domain skill directly with those assumptions. \
State your assumptions in the task text.
- If data is unavailable (API down, no results), synthesize with what you have rather than looping on the same failure.
- Call "synthesize" as soon as you have enough data to give a useful answer — do not over-call skills.
"""


class OrchestratorEngine:
    """
    Goal-driven orchestrator — a manager LLM decides which skill to call next
    based on accumulated step results. The execution path is determined at
    runtime, not at design time.

    Unlike SupervisorEngine (fixed parallel fan-out), OrchestratorEngine runs
    steps sequentially and adapts after each result before deciding the next.

    External hooks (PreStep / PostStep / OnExecutionFailure) fire around each step
    for policy enforcement — circuit breaking, scope validation, result validation,
    audit, compensation. Configure hook scripts in the agent's config.yaml.

    Example SKILL.md:
        execution_mode: orchestrator
        worker_skills:
          - name: invoice
            description: "Invoice lookup, aging analysis, overdue flagging"
          - name: payment_processing
            description: "Payment status, clearing history, remittance"
        max_steps: 8
    """

    def __init__(
        self,
        manager_llm,
        agent_factory: Callable[[str], Any],
        available_skills: List[Dict[str, str]],  # [{"name": "...", "description": "..."}]
        max_steps: int = 10,
        hook_runner=None,
        status_callback: Optional[Callable[[str], None]] = None,
        session_ctx: Optional[Dict[str, str]] = None,
    ):
        self.manager_llm      = manager_llm
        self.create_agent     = agent_factory
        self.available_skills = available_skills
        self.max_steps        = max_steps
        self.hooks            = hook_runner
        self.emit_status      = status_callback or (lambda msg: None)
        self.run_id           = str(uuid.uuid4())
        self.step_log: List[OrchestratorStep] = []   # immutable: append-only
        self._skill_names     = {s["name"] for s in available_skills}
        self._session_ctx     = session_ctx or {}     # user_id, tenant_id, agent_id, session_id


    def run(self, goal: str) -> str:
        """
        Execute the orchestrator loop. Returns the final synthesised answer.
        Fully synchronous — runs in the caller's thread.
        """
        logger.debug(
            f"🎯 Orchestrator start | run_id={self.run_id[:8]} | goal={goal[:80]}",
        )
        self.emit_status("Orchestrator started — analysing goal...")

        step_num = 0
        while step_num < self.max_steps:
            decision = self._decide(goal)

            if decision.action == "synthesize":
                self.emit_status("Synthesising final answer...")
                return self._synthesize(goal)

            if decision.action == "fail":
                logger.debug(f"❌ Orchestrator failed: {decision.reason}")
                return f"Orchestrator could not complete the goal: {decision.reason}"

            # action == "call_skill"
            step_num += 1
            self._execute_step(step_num, decision)

        # Reached max_steps — synthesise with whatever we have
        logger.debug(f"⚠️ Orchestrator hit max_steps={self.max_steps} — synthesising")
        self.emit_status(f"Reached step limit ({self.max_steps}) — synthesising...")
        return self._synthesize(goal)


    def _decide(self, goal: str) -> OrchestratorDecision:
        """Call manager LLM and parse its decision JSON. Retries once on parse failure."""
        from langchain_core.messages import HumanMessage
        prompt = self._build_manager_prompt(goal)

        for attempt in range(2):
            try:
                response = self.manager_llm.invoke([HumanMessage(content=prompt)])
                raw = response.content.strip()

                # Strip markdown code fences if the LLM wraps the JSON
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
                    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
                    raw = raw.strip()

                data, _ = json.JSONDecoder().raw_decode(raw)
                action = data.get("action", "fail")
                if action not in ("call_skill", "synthesize", "fail"):
                    action = "fail"

                if action == "call_skill":
                    skill = data.get("skill_name", "")
                    if skill not in self._skill_names:
                        return OrchestratorDecision(
                            action="fail",
                            reason=(
                                f"Manager requested unknown skill '{skill}'. "
                                f"Available: {sorted(self._skill_names)}"
                            ),
                        )

                return OrchestratorDecision(
                    action=action,
                    skill_name=data.get("skill_name", ""),
                    task=data.get("task", ""),
                    reason=data.get("reason", ""),
                )

            except (json.JSONDecodeError, AttributeError) as exc:
                if attempt == 0:
                    logger.debug(
                        f"⚠️ Orchestrator: manager JSON parse failed ({exc}) — retrying",
                    )
                    continue
                logger.debug(
                    f"❌ Orchestrator: manager JSON parse failed after retry — failing",
                )
                return OrchestratorDecision(
                    action="fail",
                    reason=f"Manager LLM returned unparseable response: {exc}",
                )

        return OrchestratorDecision(action="fail", reason="Unexpected _decide() exit")

    def _execute_step(self, step_num: int, decision: OrchestratorDecision) -> None:
        """
        Execute one orchestrator step:
          1. Fire PreStep hooks  — blocking, can abort the step
          2. Run isolated subagent
          3. Fire PostStep hooks — synchronous, collect feedback for manager LLM
          4. Append immutable OrchestratorStep to step_log
        """
        skill_name = decision.skill_name
        task       = decision.task
        step_ctx   = self._build_step_ctx(step_num, skill_name)

        self.emit_status(f"Step {step_num}: calling {skill_name}...")
        logger.debug(f"  🔀 Orchestrator step {step_num}: {skill_name} | task={task[:80]}")

        if self.hooks:
            pre = self.hooks.run_pre_step(
                step_num=step_num,
                skill_name=skill_name,
                session_ctx=step_ctx,
            )
            if pre.blocked:
                logger.debug(
                    f"  🚫 PreStep blocked step {step_num} ({skill_name}): {pre.reason}",
                )
                self.step_log.append(OrchestratorStep(
                    step_num=step_num, skill_name=skill_name, task=task,
                    result=f"[Blocked by hook: {pre.reason}]",
                    success=False, duration_ms=0, feedback=pre.reason,
                ))
                return

        result         = ""
        success        = False
        duration_ms    = 0
        child_trace_id = ""
        t0             = time.time()

        try:
            child = self.create_agent(skill_name)
            result = child.run(
                task,
                skill_name=skill_name,
                skip_memory=True,   # isolated — no memory read/write
                light_mode=True,    # skip heavy context loading
            )
            duration_ms    = int((time.time() - t0) * 1000)
            success        = True
            child_trace_id = getattr(child, "_last_trace_id", "")
            logger.debug(
                f"  ✅ Step {step_num} done | {skill_name} | {duration_ms}ms",
            )
        except Exception as exc:
            duration_ms = int((time.time() - t0) * 1000)
            result      = f"Error: {exc}"
            success     = False
            logger.debug(f"  ❌ Step {step_num} failed | {skill_name}: {exc}")
            if self.hooks:
                self.hooks.run_on_exec_failure(
                    step_num=step_num,
                    skill_name=skill_name,
                    error_msg=str(exc),
                    session_ctx=step_ctx,
                )

        feedback = ""
        if self.hooks:
            post = self.hooks.run_post_step(
                step_num=step_num,
                skill_name=skill_name,
                step_result=result,
                success=success,
                duration_ms=duration_ms,
                trace_id=child_trace_id,
                session_ctx=step_ctx,
            )
            feedback = post.feedback or ""

        self.step_log.append(OrchestratorStep(
            step_num=step_num,
            skill_name=skill_name,
            task=task,
            result=result,
            success=success,
            duration_ms=duration_ms,
            feedback=feedback,
            trace_id=child_trace_id,
        ))

    def _synthesize(self, goal: str) -> str:
        """Final LLM call — reads full step_log, produces user-facing answer."""
        from langchain_core.messages import HumanMessage
        if not self.step_log:
            return "No steps were executed — unable to answer the goal."

        prompt = (
            f"You have completed an orchestrated task. Based on the results below, "
            f"provide a clear, complete answer to the original goal.\n\n"
            f"Original goal:\n{goal}\n\n"
            f"Results gathered:\n{self._format_step_log()}\n\n"
            f"Synthesise a clear final answer. Do not prefix with 'based on the results' "
            f"— just answer directly and completely."
        )
        response = self.manager_llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def _build_manager_prompt(self, goal: str) -> str:
        skills_list  = "\n".join(
            f"  - {s['name']}: {s.get('description', '(no description)')}"
            for s in self.available_skills
        )
        step_log_text = self._format_step_log() if self.step_log else "  (none yet)"
        return ORCHESTRATOR_MANAGER_PROMPT.format(
            skills_list=skills_list,
            step_log=step_log_text,
            goal=goal,
        )

    def _format_step_log(self) -> str:
        lines = []
        for s in self.step_log:
            status = "✓" if s.success else "✗"
            lines.append(f"  Step {s.step_num} [{status}] {s.skill_name}: {s.task}")
            preview = s.result[:500] + ("…" if len(s.result) > 500 else "")
            lines.append(f"    Result: {preview}")
            if s.feedback:
                lines.append(f"    Note:   {s.feedback}")
        return "\n".join(lines)

    def _build_step_ctx(self, step_num: int, skill_name: str) -> dict:
        """Build session context dict passed to hook env — merges session identity."""
        return {
            **self._session_ctx,                 # user_id, tenant_id, agent_id, session_id
            "execution_mode":   "orchestrator",
            "run_id":           self.run_id,
            "step_num":         step_num,
            "step_name":        skill_name,
            "skill_name":       skill_name,
            "available_skills": ",".join(s["name"] for s in self.available_skills),
        }


def get_execution_mode(mode_str: str) -> ExecutionMode:
    """
    Parse execution mode string from SKILL.md.
    
    Args:
        mode_str: Mode string like 'react', 'workflow', 'parallel', 'supervisor'
        
    Returns:
        ExecutionMode enum value, defaults to REACT if invalid
    """
    if not mode_str:
        return ExecutionMode.REACT
    try:
        return ExecutionMode(mode_str.lower())
    except ValueError:
        logger.warning(
            "Unknown execution_mode %r — falling back to 'react'. The skill's configured "
            "orchestration will NOT run. Valid values: %s",
            mode_str, ", ".join(m.value for m in ExecutionMode),
        )
        return ExecutionMode.REACT
