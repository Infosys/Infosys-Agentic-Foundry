# Observability — Traces, Evidence, FinOps

Every agent run is fully observable. Nothing is hidden in a black box.

## What's recorded per request

| Recorded | Where | Granularity |
|---|---|---|
| Trace (top-level run) | `traces.db.traces` | Per user query |
| Spans (each step / tool call) | `traces.db.spans` | Per step |
| Tokens (prompt + completion) | `traces.traces.{prompt,completion}_tokens` | Per trace |
| Cost (USD) | `traces.traces.cost_usd` | Per trace, priced from `model_pricing.yaml` |
| Evidence (source files cited) | Linked from spans | Per file reference |
| Errors | Span `status` + `metadata` | Per failure point |

## FinOps Dashboard — `/finops`

Live view of:

- Total spend (today / week / month)
- Tokens by skill, by user, by tenant
- Latency p50 / p95 / p99
- Cost per request, avg + max
- Top expensive runs (click into trace for forensics)

Backed entirely by the same `traces.db` — no separate metrics pipeline.

## Evidence Viewer

Each agent response includes inline source attributions. Click a span
in the viewer to see:

- The exact tool call (shell command, SQL, etc.)
- The output that informed the next step
- The context files cited
- The trace_id for cross-system correlation

This is the **"prove your work"** layer that converts demo → trust →
sale in customer conversations.

## Trace IDs

A new `trace_id` is minted at the start of every run. It's propagated
through:

- Logs (every line carries it)
- Hooks (`ctx["trace_id"]`)
- Queue records
- FinOps line items

Grep for the trace_id across the system to reconstruct exactly what
happened.

## Recent typical numbers (518 traces, production)

- Avg ~30,000 input + ~716 output tokens / request
- Median 26k tokens · p95 63k · max 263k
- Avg cost $0.08 at GPT-4o tier
- Avg latency 39.5s end-to-end

See the token economics one-pager at `docs/iaf_token_economics.html`
for customer-facing detail.

Read more: docs/iaf_token_economics.html · `/finops`
