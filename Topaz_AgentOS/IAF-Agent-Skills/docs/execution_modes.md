# IAF Agent Skills — Execution Modes

## Overview

Every skill in IAF AgentPro runs in one execution mode declared in `SKILL.md` frontmatter under `execution_mode`. The mode determines how the agent processes a query — from free-form LLM reasoning to deterministic step pipelines to multi-agent orchestration.

```yaml
execution_mode: react        # Default — free-form LLM + tool loop
execution_mode: workflow     # Deterministic sequential steps
execution_mode: parallel     # Concurrent DAG-based steps
execution_mode: supervisor   # Meta-agent delegates to worker skills
execution_mode: rlm          # Reasoning-as-code loop over governed tools
execution_mode: graph        # Stored process-graph (DAG + verifier + convergence)
```

Two additional declarable modes ship on top of the above:
- **`rlm`** — a reasoning-as-code loop where the model writes Python that calls a governed
  tool allow-list; supports propose-then-apply HITL holds. See
  [../../docs/RLM_EXECUTION_MODE.md](../../docs/RLM_EXECUTION_MODE.md).
- **`graph`** — a stored process-graph (`graph_ref: graph.yaml`) of skill-nodes with verifier
  nodes + a convergence loop, executed by `planner.execute_graph`. Authored in the **Graph Studio**.
  See [../../docs/PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](../../docs/PROCESS_GRAPHS_AND_GRAPH_STUDIO.md).

A fifth mode, **planned**, is selected automatically by the router when a query spans 2+ detected domains. It is never declared in SKILL.md.

A sixth mode hint, **orchestrator**, is returned by the router when a query needs sequential skill chaining for a single coherent business request. It is also never declared in SKILL.md.

Dynamic router-selected orchestration is controlled by
`DYNAMIC_ORCHESTRATOR_ENABLED` (default `true`). When set to `false`, an
`orchestrator` mode hint falls back to the selected skill's normal ReAct loop.
Planned mode and explicitly declared workflow, parallel, supervisor, or
orchestrator skill modes are unchanged.

For `execution_mode: react` only, a skill may also declare `react_runtime`:

```yaml
execution_mode: react
react_runtime: langgraph   # Default and rollback path
# react_runtime: native    # Provider-native React runtime when configured
```

`react_runtime` is an implementation selector, not a seventh execution mode. Workflow, parallel, supervisor, orchestrator, and planned modes ignore it.

The runtime selector (`resolve_react_runtime`, `ReactRuntimeSelection`, and the
default/valid runtime constants) is exported by the dependency-free
`agentos-contracts` SDK and re-exported from
`iaf_agent_skills.react_runtime.factory` for compatibility. The default remains
`langgraph`; `native` is opt-in.

Execution mode is independent of optional `SKILL.md` evidence settings such as `evidence_highlights`; those rules only influence Evidence Viewer highlight terms after a run reads documents.

All execution modes still persist downstream memory through the existing `AgentMemory` JSONL/SQLite implementation by default. The staged `MemoryCapability` pass-through can be enabled with `IAF_MEMORY_CAPABILITY_ENABLED=true` for write-path parity validation without changing execution mode semantics.

Execution mode orchestration remains inside `SkillAgent`. Runtime provider slots
only swap boundary implementations: skill lookup, routing, tool construction,
hook runner construction, and trace emitter resolution. Defaults preserve the
same behavior for every execution mode.

---

## Mode 0: ORCHESTRATOR (Auto-selected)

### What it is
Automatically selected by the router when `complexity_class = "multi_step"`. Used when a
query needs sequential calls across 2+ skills where the output of one feeds the next —
but the overall question is a single coherent business request. Never declared in SKILL.md.

### Distinction from PLANNED
| | ORCHESTRATOR | PLANNED |
|---|---|---|
| Trigger | multi_step — one business question, skills chained | multi_domain — separate unrelated domains |
| Example | "Get Northfield Foods AR aging, then cross-check GL entries" | "CrashLoopBackOff pod AND stuck invoices" |
| Skill | Domain skill (e.g. fa_ar) | general |
| mode_hint | orchestrator | planned |

### Flow
Router LLM sees taxonomy hints → determines complexity_class = "multi_step" →
returns mode_hint = "orchestrator" → agent runs orchestrator mode with domain skill.

For a temporary rollback, set `DYNAMIC_ORCHESTRATOR_ENABLED=false` and restart
the runtime. The router still records its complexity decision, but `SkillAgent`
logs the disabled upgrade and continues in ReAct.

---

## Mode 1: REACT (Default)

### What it is
The default free-form React loop. In the default `react_runtime: langgraph` path, LangGraph ReAct drives the LLM/tool loop. The optional `react_runtime: native` path uses the existing Azure OpenAI chat model with native tool calls, captures provider metadata, and keeps LangGraph as the rollback path. Both paths write a bounded, UI-safe `reasoning_summary` from observable runtime/tool metadata after the turn. Best for open-ended, unpredictable tasks.

### How it works internally

```
User query
    ↓
create_react_agent(llm, tools, system_prompt)
    ↓
Loop:
  LLM invocation → response with optional tool_calls
    ↓
  If tool_calls:
    Execute each tool → append result to state
    ↓
  LLM sees tool results → reasons again
    ↓
Until stop_reason == "end_turn" (no more tool calls)
    ↓
Final response returned
```

Both React runtimes use the same structured tool-call governance firewall before execution. The firewall records pre-tool observation, evidence call metadata, PreToolUse hooks, write/danger/HITL gates, entitlement/policy checks, and approval-pending state before any side effect. Native React runtime also records `run_sql_query` results as SQL evidence items at the tool-result boundary, matching the workflow/LangGraph evidence path. A blocking hook configured with `on_block: hitl` can create `approval_pending` from gateable events such as `PreToolUse`, `BeforeTurn`, or `PostTurn`, which lets deterministic business policies pause chat, queue, cron, or Mission Mode work after the relevant evidence is available. When `MODEL_CALL_PIPELINE_ENABLED=true`, the primary chat model is wrapped by `PolicyChatModel` so every LangGraph and native ReAct provider call runs through ordered `BeforeModelCall`, `AroundModelCall`, and `AfterModelCall` phases before the runtime parses tool calls. If `RL_CAPTURE=true`, neutral events emitted through `iaf_agent_skills.capture_events` are mirrored into the independent RL/eval store as incremental model-call rows, tool-call/observation rows, hook outcomes, and evaluator results without exposing RL schema imports to execution-mode code.
The UI reasoning summary is not raw model chain-of-thought. It describes the selected runtime, tools/evidence touched, tool-error status, provider metadata when available, and the fact that the final answer was synthesized from those observable artifacts.

### Key internals
- **Class**: `langchain/langgraph` `create_react_agent` for `react_runtime: langgraph`; `NativeReactRuntime` with `AzureChatOpenAI.bind_tools(...)` for `react_runtime: native`
- **Native reasoning (opt-in)**: When `AZURE_REASONING_ENABLED=true` (and `AZURE_OPENAI_API_VERSION >= 2025-03-01-preview`), the primary Azure reasoning model is built with `reasoning_effort` so it spends extra hidden thinking tokens before each turn. Off by default — the model is built exactly as before. Phase 2 adds a provider-neutral reasoning contract (`NativeTurn.reasoning_items`, `response_id`, and `reasoning_ref`) plus provider adapters for Azure Responses API, Gemini/Vertex thinking, and optional Anthropic thinking. Cross-turn replay remains disabled unless the provider-specific `*_REASONING_REPLAY=true` flag is set. Bounded UI/trace exposure is separately gated by `*_REASONING_EXPOSE=true`, so replay can run internally without logging raw reasoning. The model registry, reasoning capability metadata, and provider chat adapters now live in the composable `agentos-model` package, with historical `iaf_agent_skills.model_*` and provider adapter modules retained as compatibility shims.
- **State**: `{"messages": [...]}` — full conversation thread including tool results
- **Session persistence**: Stored in `RedisSessionStore` as `AgentStateSnapshot`
- **Compaction**: After 30 turns, old history is LLM-summarised; last 8 turns kept verbatim
- **Token guard**: Warns at 60,000 tokens, errors at 100,000 tokens
- **Entitlement filter**: before a skill runs, the request-scoped entitlement checker verifies `skill:{name}` access and filters tools such as `shell`, `run_sql_query`, bundled skill tools, MCP tools, and `invoke_skill` exposure. The same checker is propagated to SafeKernel so `get_credential`, MCP discovery, SQL/database access, and kernel-observed curl targets can be governed by `external:*`, `mcp:*`, and `external:db.*` policy resources.
- **Untrusted multi-tenant guard** (`AGENTOS_UNTRUSTED_EXECUTION_GUARD=true`): in shared/SaaS deployments, on top of the entitlement filter, tenant-reachable arbitrary-code paths are hard-disabled — agent-shell `python3` is forced off (kernel), and **personal** (tenant-authored) skills may not load bundled tool scripts or declare **local `direct+stdio` MCP** servers (brokered `registry`/HTTP MCP and trusted global/agent-level connections still work). Guard off (default) preserves trusted single-tenant behaviour.
- **Binary document guidance**: ReAct prompts steer PDF/Office extraction through SafeKernel `python3` helpers, using Quartz/PDFKit on macOS or MarkItDown when installed, rather than raw `cat` or unavailable host commands.

### When to use
- Tasks where the agent must decide which tools to call based on intermediate results
- Queries that require reading data before knowing what to do next
- Any open-ended business Q&A (AR aging, vendor lookup, invoice status)

### Example SKILL.md
```yaml
---
name: ar_ops
execution_mode: react
tools: [shell, run_sql_query, invoke_skill, query_memory]
# Optional. Omit to keep the default LangGraph runtime.
react_runtime: langgraph
---
You are the AR Operations agent. Answer questions about receivables,
aging, disputes, and collections using the available tools.
```

---

## Mode 2: WORKFLOW

### What it is
Deterministic sequential step execution. Steps are declared in `SKILL.md` and run in order. The LLM is not in the loop for routing — step sequence is fixed. Best for repeatable, auditable processes.

### How it works internally

```
steps: [step1, step2, step3, ...]
    ↓
WorkflowEngine.run(steps, status_callback, initial_context)
    ↓
For each step (in order):
  Resolve template variables: {{step_name.output}} → actual value
    ↓
  Execute based on action type:
    action: shell    → run shell command (only if "shell" ∈ agent allowed_tools; see note below)
    action: skill    → invoke SkillAgent(step.skill).run(step.task, status_callback=tagged_callback)
    action: condition → evaluate check, branch to then_step or else_step
    ↓
  Store result: results[step.name] = StepResult(success, output, error)
    ↓
  If skill returned approval_pending:
    Save remaining_steps
    Set paused_for_approval = True
    Break — await human decision
    ↓
Return results dict
```

> **Tool availability (allowlist intersection).** An `action: shell` step is only
> executable when `shell` is in the agent's `allowed_tools`. `SkillAgent._get_tools_map`
> (which backs the Workflow **and** Parallel engines) registers the `shell` tool only
> when the allowlist permits it — the same gate the ReAct path applies. If an admin
> unchecks *Shell* on the agent (Edit Agent → Allowed Tools), a `shell` step is not
> registered as a callable tool and the step fails rather than silently reaching
> `kernel.run_shell_command` (and `python3`/`curl` through it). Author skills defensively:
> a workflow that requires `shell` should only run under an agent that grants it.

For `action: skill`, the child agent's progress/tool callbacks are tagged with
`workflow_step` and `skill` before being forwarded to the parent callback. This
lets Mission Mode and Workstream Detail show live child-skill activity under the
parent workflow step instead of generic `tool completed` rows. Workflow runs also
return structured step-log dictionaries (`tool_name`, `action`, `skill`, status,
duration, input/output/error previews) when callers request tool calls for audit
or `execution_ledger` persistence.

### Template variable syntax
Steps can reference previous step outputs using `{{step_name.output}}`:
```yaml
steps:
  - name: fetch_invoices
    action: shell
    params:
      command: "sqlite3 /db/ap.db 'SELECT * FROM invoices WHERE status=open'"
  - name: summarise
    action: skill
    skill: general
    task: "Summarise these invoices: {{fetch_invoices.output}}"
  - name: write_report
    action: shell
    params:
      command: "echo '{{summarise.output}}' > /me/report.md"
```

### Conditional branching
```yaml
steps:
  - name: check_amount
    action: condition
    condition_if: "{{get_invoice.output}}"
    contains: "amount > 100000"
    then_step: require_approval
    else_step: auto_process
  - name: require_approval
    action: skill
    skill: general
    task: "Request approval for high-value invoice"
  - name: auto_process
    action: shell
    params:
      command: "python3 /tools/process_invoice.py"
```

### HITL pause and resume
When a step invokes a skill that triggers `request_human_approval`:
1. `paused_for_approval = True` is set on the engine
2. `remaining_steps` stores all steps not yet executed
3. Agent state is checkpointed in Redis (`ApprovalStore`)
4. On human approval: `WorkflowEngine.run(remaining_steps, ...)` resumes
5. Previously completed step outputs are preserved during resume, so remaining
   steps can still resolve references such as `{{approval_gate.output}}`
6. In Mission Mode, workflow child agents inherit the parent workstream and item
   identifiers so prompt/tool/hook approvals appear on the correct workstream item

### When to use
- Month-end close checklists
- Invoice processing pipelines
- Multi-step approval workflows
- Any process where the sequence is fixed and auditable

---

## Mode 3: PARALLEL

### What it is
DAG-based concurrent execution. Steps declare dependencies via `depends_on`. Steps with no dependencies run immediately in parallel. Steps with dependencies wait for their predecessors. Best for independent data gathering followed by aggregation.

### How it works internally

```
ParallelEngine.run(steps, status_callback)
    ↓
Build dependency graph from depends_on fields
    ↓
Wave-based execution:
  Wave 1: All steps with no depends_on → asyncio.gather()
    ↓
  Wave 2: Steps whose depends_on are all in completed → asyncio.gather()
    ↓
  ... until all steps done or circular dependency detected
    ↓
If any step in depends_on is in failed set → skip dependents immediately
    ↓
Return results dict
```

### Dependency syntax
```yaml
execution_mode: parallel
steps:
  - name: get_ar_aging
    action: skill
    skill: ar_ops
    task: "Get AR aging summary"
    # No depends_on → runs in Wave 1

  - name: get_ap_balance
    action: skill
    skill: invoice
    task: "Get AP open balance"
    # No depends_on → runs in Wave 1 concurrently with get_ar_aging

  - name: get_gl_summary
    action: skill
    skill: general
    task: "Get GL trial balance"
    # No depends_on → runs in Wave 1

  - name: generate_report
    action: skill
    skill: general
    task: "Combine AR: {{get_ar_aging.output}}, AP: {{get_ap_balance.output}}, GL: {{get_gl_summary.output}}"
    depends_on: [get_ar_aging, get_ap_balance, get_gl_summary]
    # Runs in Wave 2 after all three complete
```

### Execution timeline
```
t=0s  [get_ar_aging]──────────┐
t=0s  [get_ap_balance]─────── ├── Wave 1 (concurrent)
t=0s  [get_gl_summary]────────┘
           ↓ (all complete ~t=3s)
t=3s  [generate_report]──── Wave 2
```

### Async implementation
- Steps run via `asyncio.to_thread()` to wrap synchronous `SkillAgent.run()`
- `asyncio.gather(*wave_tasks)` executes each wave
- Failure propagation: if `get_ar_aging` fails, `generate_report` is skipped with a dependency-failed error

### When to use
- Dashboard-style reports pulling data from multiple systems
- Compliance checks across multiple domains simultaneously
- Period close that fetches AR + AP + GL in parallel then consolidates

---

## Mode 4: SUPERVISOR

### What it is
A meta-agent that delegates subtasks to worker skills running in parallel threads. The supervisor skill itself is an LLM that receives all worker results and synthesises a final answer. Best for complex multi-domain queries requiring true coordination.

### How it works internally

```
SupervisorEngine.run(task, worker_skills, status_callback)
    ↓
ThreadPoolExecutor(max_workers=len(worker_skills))
    ↓
Submit each worker:
  future = pool.submit(run_worker, worker)
    where run_worker = SkillAgent(worker.skill).run(worker.task or task)
    ↓
as_completed(futures):
  Collect results → worker_results[skill_name] = response
  If worker has approval_pending → propagate to supervisor
    ↓
After all workers complete:
  Supervisor LLM receives aggregated results
  Synthesises final response
    ↓
Return final_response
```

### Worker skill declaration
```yaml
execution_mode: supervisor
worker_skills:
  - name: ar_ops
    task: "Summarise overdue AR above 90 days"
  - name: invoice
    task: "List invoices pending approval"
  - name: period_close_check
    task: "Check if period close is complete"
  # task is optional — if omitted, original user query is passed to worker
```

### HITL propagation
If any worker triggers `request_human_approval`, the first such approval request is propagated up to the supervisor. The supervisor pauses and waits for human decision before continuing.

### Difference from PARALLEL
| | PARALLEL | SUPERVISOR |
|---|---|---|
| Coordination | Template variables | LLM synthesis |
| Steps | Fixed declarations | Worker agents with full autonomy |
| Final answer | Last step output | Supervisor LLM reasoning over all results |
| Flexibility | High (deterministic) | Very high (LLM-driven) |

### When to use
- Executive summary dashboards combining 3+ domain agents
- Cross-domain investigations (AP + AR + GL together)
- Complex orchestration where each domain needs its own full ReAct loop

---

## Mode 5: PLANNED (Automatic + UI Plan Mode)

### What it is
Automatically selected by the router — never declared in SKILL.md. When the query spans 2+ distinct process domains (e.g., both AR and P2P signals detected), the router routes to the `general` skill with `execution_mode: planned`. The `general` skill's ReAct loop calls `create_plan`, which generates a DAG for user approval before execution.

The chat UI **Plan Mode** toggle sends `force_plan: true` on every message. That forces the same path even for single-domain queries: route to `general`, set `execution_mode: planned`, and pin `mode_hint: planned` so the auto-orchestrator upgrade does not bypass `create_plan`.

### Trigger condition

The router LLM sees L5 taxonomy signal hints (from TaxonomySignalIndex) alongside the
query and returns complexity_class: "multi_domain" when it determines the query
explicitly spans 2+ unrelated business domains. This sets execution_mode = "planned".

The taxonomy signal index runs before the router call — its top cosine+term-boost hits
are injected into the router prompt as informational context. The LLM uses this to
classify complexity, not a hard threshold.

UI Plan Mode (`force_plan: true`) always triggers planned mode regardless of router complexity.

### Flow
```
Router detects: AR domain (0.82) + P2P domain (0.79)
    OR user enables Plan Mode toggle (force_plan=true)
    ↓
Routes to general skill with execution_mode="planned", mode_hint="planned"
    ↓
[ROUTING CONTEXT] injected → general LLM calls create_plan(goal)
    ↓
User approves plan in chat UI
    ↓
invoke_plan executes DAG steps across domain skills
    ↓
Aggregates and returns
```

---

## Execution Mode Selection Guide

| Scenario | Recommended Mode |
|---|---|
| Open-ended Q&A, analysis, investigation | `react` |
| Sequential steps chaining across 2+ skills | `orchestrator` (auto-selected) |
| Fixed business process (month-end close) | `workflow` |
| Fetch data from multiple independent sources | `parallel` |
| Multi-domain coordination with LLM synthesis | `supervisor` |
| Query explicitly spans 2+ unrelated domains (auto-detected) | `planned` (automatic) |

---

## Status Callbacks

All execution modes accept a `status_callback(phase, message)` callable:

```python
def my_callback(phase: str, message: str):
    print(f"[{phase}] {message}")

engine.run(steps, status_callback=my_callback)
```

Common phases emitted:
- `"routing"` — skill routing decision
- `"executing"` — step/tool execution started
- `"tool_call"` — tool invoked
- `"approval_required"` — HITL gate triggered
- `"complete"` — execution finished
- `"error"` — execution failed
