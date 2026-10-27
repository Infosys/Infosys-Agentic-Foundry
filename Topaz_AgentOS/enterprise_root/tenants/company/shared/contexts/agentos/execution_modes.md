# Execution Modes

Declared in `SKILL.md` frontmatter as `execution_mode:`. Picks which
engine the harness uses to run the skill.

## The five modes

| Mode | Engine | When to use |
|---|---|---|
| `react` | LLM picks tool each turn | Chat, exploration, open-ended Q&A |
| `workflow` | Deterministic DAG, no LLM between steps | Fixed flow, cheap, reproducible |
| `parallel` | Independent steps run concurrently | Wall-clock speedup for fan-out |
| `supervisor` | Fixed fan-out to known workers, then synthesise | Cross-functional review |
| `orchestrator` | Manager LLM dynamically dispatches workers | Path depends on prior result |

## Trade-offs at a glance

- `react` — most flexible, most tokens, least deterministic
- `workflow` — least tokens, most deterministic, least flexible
- `orchestrator` — adaptive but the manager LLM adds latency and cost
- `supervisor` ≈ parallel + LLM workers; useful when each worker has a
  distinct perspective on the same goal
- `parallel` — pure speedup pattern; no synthesis step

## Orchestrator pattern (Anthropic-style)

```yaml
execution_mode: orchestrator
worker_skills:
  - name: invoice_lookup
    description: "Invoice lookup, aging analysis"
  - name: customer_credit
    description: "Credit profile, payment history"
max_steps: 8
```

The manager LLM returns strict JSON each turn:

```json
{ "action": "call_skill", "skill_name": "invoice_lookup",
  "task": "list overdue > 60d", "reason": "need exposure first" }
```

A skill name not in `worker_skills` is rejected by the engine —
prompt-injection can't escape the allowlist.

## Workflow pattern (deterministic)

```yaml
execution_mode: workflow
steps:
  - name: fetch
    action: run_sql_query
    params: { query: "SELECT * FROM ar_aging" }
  - name: alert
    action: shell
    depends_on: [fetch]
    params: { command: "echo done" }
```

Read more: docs/AUTHORING_GUIDE.md · IAF-Agent-Skills/docs/execution_modes.md
