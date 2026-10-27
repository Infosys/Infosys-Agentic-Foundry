# Private Learning Loop

The Private Learning Loop is AgentPro's tenant-owned evaluation and learning
surface. It keeps enterprise-specific tests, expected answers, and grading rules
under `enterprise_root` so they can be versioned and promoted with the rest of a
customer solution.

## Phase 1 Scope

Phase 1 adds the registry and rubric foundation:

- Framework-neutral core package: `rl_capture/evals/`
- AgentPro path adapter: `rl_capture/adapters/agentpro/evals_paths.py`
- Thin Studio service/router: `shared/evals_service.py` and `routers/evals.py`
- Tenant eval suites: `enterprise_root/tenants/{tenant}/evals/{suite_id}.yaml`
- Golden sets: `enterprise_root/tenants/{tenant}/golden_sets/{set_id}.jsonl`

The core package does not import Studio or `enterprise_root`; the adapter passes
resolved tenant paths into the core.

Phase 2 adds execution:

- `rl_capture/store/eval_store.py` persists eval run/case rows through the
  injected `StorageEngine` (`DB_BACKEND=sqlite|postgres`).
- `rl_capture/evals/runner.py` runs golden cases, calls a candidate producer,
  scores output with the configured rubric/assertions, and records run traces.
- `rl_capture/adapters/agentpro/eval_candidates.py` produces candidates by
  reusing existing AgentPro paths: `SkillAgent`, `AutomationEngine`, or
  `ModelRegistry` model roles.

Phase 3 adds the continuous eval read model:

- `shared/eval_dashboard_store.py` reads suite definitions and eval run traces
  without running agents.
- `GET /api/evals/dashboard/summary` returns suite counts, latest scores,
  previous-run deltas, regressions, and recent run trend rows.
- `/rl-capture/workbench` includes an `evals` tab beside trajectory details.

Phase 4 adds Learning Signals:

- `shared/learning_inbox_store.py` aggregates counts for pending-review
  knowledge, captured feedback signals, eval failures, and Trace Value Router
  recommendations.
- `GET /api/learning-inbox` returns a governed review queue with provenance.
- Dashboard V2's Knowledge Manager shows a Learning Signals summary panel.
  Governance still happens in the existing knowledge table below it.

Phase 4b adds the advisory Trace Value Router:

- `trace_value_router` scores completed eligible traces for `skill`, `context`,
  `memory`, `golden_eval`, `model_training`, and `debug_only` destinations.
- Reviewers bulk-promote recommendations through `/api/trace-value/promote`.
  Promotions are auditable and delegate to existing golden, knowledge, and export
  paths. No model weights are trained in AgentPro.

Phase 5 adds eval-based model recommendations:

- `rl_capture/evals/recommender.py` ranks model-role eval results by score,
  optional cost, and optional latency.
- `GET /api/evals/recommendations` returns advisory recommendations.
- Runtime routing remains opt-in with `EVAL_ROUTER_ENABLED=true` and an explicit
  `EVAL_ROUTER_ROLE_MAP` or `EVAL_ROUTER_ROLE_<ROLE>` setting.

Phase 6 adds the Fine-tune Export Center:

- Existing `/api/rl-capture/exports` accepts optional `eval_verdict`,
  `golden_set`, `since`, and `until` filters.
- The RL/Eval Center export card exposes those filters before materializing
  SFT/eval/DPO/KTO/rejection-SFT/RFT JSONL.

Continuous scheduling reuses the existing cron scheduler. A standalone cron with
`skill_name: eval_suite` treats `task` as the suite id and runs it with
`trigger="cron"`.

## Eval Suites

An eval suite defines what to test and how to grade it.

```yaml
id: invoice_suite
name: Invoice Suite
target:
  type: skill
  name: invoice_agent
golden_set: invoice_cases
rubric:
  version: invoice_v1
  pass_threshold: 0.4
assertions:
  - type: contains
    value: approved
evaluator:
  type: python
  id: invoice_exception_v1
  version: v1
  weights:
    rule: 0.5
    assertions: 1.0
    python: 2.0
    judge: 1.0
judge:
  mode: hybrid
  sample_size: 0
  max_llm_cases: 5
  borderline_min: 0.2
  borderline_max: 0.7
```

Supported assertion types are `exact`, `contains`, `not_contains`, `numeric`,
and `regex`. Assertions can set `critical: true`; a failed critical assertion
forces a failed case even when the weighted average score is otherwise high.

## Python Evaluators

Suites may reference an allowlisted tenant evaluator:

```yaml
evaluator:
  type: python
  id: invoice_exception_v1
  version: v1
```

Evaluator manifests live under
`enterprise_root/tenants/{tenant}/eval_evaluators/{evaluator_id}/manifest.yaml`
and point to a relative Python entrypoint in the same evaluator directory. Studio
never imports arbitrary module paths from suite YAML. The evaluator runs in a
fresh subprocess with sanitized environment, JSON stdin/stdout, timeout,
output-size limits, and best-effort CPU/memory/file limits. This is isolation for
trusted, admin-approved plug-ins, not a hostile-code sandbox; container/job
execution remains the future hard-isolation option.

The evaluator function receives normalized JSON containing the suite, case,
candidate output, expected result, assertion results, target metadata, tool
summaries, and case metadata. It returns structured JSON:

```json
{"score":0.82,"verdict":"pass","confidence":0.9,"components":{"policy":{"passed":true}},"reasons":["matched policy"],"reward":0.82}
```

The runner combines rule, assertion, Python, and optional LLM judge components by
suite-declared weights and persists every component result for auditability.

## Golden Sets

A golden set is a JSONL answer key. Each line is one case:

```json
{"id":"case_1","task":"approve invoice INV-42","expected":"approved","assertions":[{"type":"contains","value":"approved"}],"tags":["invoice"]}
```

Studio can also promote an existing captured RL trajectory into a golden case,
using the trajectory task and final assistant output as the first expected
answer.

## API

Phase 1 exposes:

- `GET /api/evals`
- `POST /api/evals`
- `POST /api/evals/validate`
- `GET /api/evals/{suite_id}`
- `DELETE /api/evals/{suite_id}`
- `GET /api/evals/evaluators`
- `GET /api/evals/evaluators/{evaluator_id}`
- `POST /api/evals/evaluators/{evaluator_id}/test`
- `GET /api/evals/golden/{set_id}`
- `POST /api/evals/golden/{set_id}`
- `POST /api/evals/golden/{set_id}/promote`
- `POST /api/evals/{suite_id}/run`
- `GET /api/evals/{suite_id}/runs`
- `GET /api/evals/{suite_id}/gates`
- `POST /api/evals/{suite_id}/gates`
- `GET /api/evals/runs/{run_id}`
- `GET /api/evals/dashboard/summary`
- `GET /api/evals/recommendations`
- `GET /api/learning-inbox`
- `GET/POST /api/trace-value/*` for advisory assessment and governed promotion
- `POST /api/rl-capture/exports` with optional eval/golden/date/trace-route filters

The Workbench `evals` tab is an Eval Builder surface for suite editing, golden
case editing, evaluator testing, run inspection, trajectory promotion, and
manual promotion-gate decisions. Gate decisions are recorded as release evidence;
they do not deploy, fine-tune, or auto-promote artifacts.

All planned phases are additive; scheduled evals reuse the existing cron runtime.
