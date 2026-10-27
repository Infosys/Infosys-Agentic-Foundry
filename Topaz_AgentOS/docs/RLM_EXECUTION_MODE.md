# RLM Execution Mode (Reasoning-as-Code)

> **Audience:** skill authors and platform devs. **Status:** shipped on `feat/rlm-integration`.
> Verify behaviour against `IAF-Agent-Skills/iaf_agent_skills/rlm/` and `agent.py::_run_rlm` — code is the contract.

## What it is
`execution_mode: rlm` runs a skill as a **code-action loop**: the model writes small Python
snippets that call a **governed** set of tools, observes the results, and iterates — instead of the
free-form tool-call loop of `react`. It suits computation, data crunching, and multi-step tool
orchestration where expressing the step as code is clearer than a tool call.

RLM is **not** a bypass of governance. Every tool the code can call goes through the same
`govern_tool_call(agent, tool_call, source="rlm_repl")` firewall as any other mode (entitlements,
write/danger/HITL gates, evidence capture). Arbitrary Python is **not** allowed — an AST guard
(`rlm/engine.py::ast_guard`) rejects imports, dunder-attribute access, and escape names before any
code executes.

## When to use it
- Multi-step numeric/tabular work (aggregations, reconciliations, "compute X from these rows").
- Orchestrating several governed tool calls with intermediate logic.
- Prefer `react` for open-ended Q&A/investigation; `workflow`/`graph` for fixed processes.

## Authoring
```yaml
---
name: rlm_ap_report
description: Summarise overdue AP invoices with RLM.
execution_mode: rlm
tools:                       # the ONLY tools the code loop may call
  - run_sql_query
  - http_get
  - read_document
keywords: [overdue ap, ap aging]
---
# Body = instructions to the model: the goal + the data to work with.
Compute totals, aging buckets, top vendors and risk flags from ap_ops.db.
Return a concise executive summary. Do not propose or execute payments.
```
- `tools` is the allow-list the code loop may call. No `steps`/`worker_skills`.
- Per-agent RLM limits live in the agent's `config.yaml` (`rlm:` block), e.g.
  `max_tool_calls`, `max_wall_s`, `apply_phase`, `docs_dir`, `creds_file`.

## Propose-then-apply (governed side effects)
RLM separates **deciding** from **doing**. When the loop wants a side effect it calls
`propose_action(...)` (a *hold*), which does **not** execute. At turn end,
`checkpoint_rlm_holds_if_needed` persists each hold as a real **HITL approval card** in the
ApprovalStore (Command Center). On **Approve**, `routers/approvals.py::_execute_rlm_hold` performs
the deterministic side effect (with an idempotency guard so a double-approve can't double-apply).
This is the same HITL surface used elsewhere — see [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md).

## Safety model (summary)
| Guard | Where |
|---|---|
| Tool allow-list per skill | `tools:` in SKILL.md |
| Governed tool firewall | `govern_tool_call(..., source="rlm_repl")` |
| AST bouncer (no imports/dunder/escape) | `rlm/engine.py::ast_guard` |
| Side effects gated by HITL | `propose_action` → ApprovalStore card → `_execute_rlm_hold` |
| Per-agent budgets | agent `config.yaml` `rlm:` block |

## Observing a run
RLM emits code-trace events (`_rlm_emit`) that render as collapsible **code cards** in the chat
plus the live **thinking box** (see [KEY_FEATURES.md](KEY_FEATURES.md) → Live thinking box). Run an
RLM skill from chat with `@rlm_ap_report <request>`.

## Related
- Engine: `IAF-Agent-Skills/iaf_agent_skills/rlm/{engine,tools,context_store,shadow}.py`
- Tests: `IAF-Agent-Skills/tests/test_rlm_engine.py`, `test_rlm_tools_governance.py`
- Modes overview: [../IAF-Agent-Skills/docs/execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md)
