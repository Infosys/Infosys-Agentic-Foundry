# Workstream Skill Contract Guide

This guide explains how to create a Workstream and the worker `SKILL.md` that
populates the Analyst Case Workbench in Workstream Detail.

For no-LLM processing, a Workstream may declare `automation: <automation_id>`
instead of `skill: <skill_name>`. Automation-backed Workstreams still get item
claiming, retry, status, and execution-trace persistence, but they do not use
the Workstream Skill contract because no LLM worker produces case metadata. See
`DETERMINISTIC_AUTOMATIONS.md`.

## Mental Model

A Workstream is the backlog and execution loop. A Skill is the worker that
processes each item. The Skill should produce domain-aware case metadata, while
the Workstream UI renders it in a domain-neutral way.

```text
Workstream YAML/API item
  -> mission_mode selects one item
  -> worker SKILL.md processes it
  -> status_callback streams live execution steps to Workstream Detail
  -> workstream state carries business_lens metrics
  -> item state is saved with evidence, result, actions, case_summary, case_insights
  -> Workstream Detail renders Business Impact, Agent Execution, and Analyst Case Workbench views
```

The Workstream Detail `Execution Trace` tab is populated by Mission Mode rather
than by skill-authored YAML. When a worker skill reads context, runs SQL/API
tools, invokes a workflow child step, or pauses for HITL, the agent runtime emits
progress/tool callbacks. Mission Mode streams those callbacks live over the
workstream WebSocket, writes durable Studio runtime rows in
`workstream_runtime.db`, and persists bounded previews in
`execution_ledger[].steps` for later review. Workstream Detail refetches the
expanded item's execution context while it runs, deduplicates step events by
stored step id, and renders source badges, formatted JSON/pre output, and
markdown result summaries. Skill authors should focus on using real tools and
evidence sources; the trace is captured from runtime behavior.

## Create The Workstream Business Lens

Use `business_lens` for metrics that describe the whole backlog or business
outcome. These appear above the agent execution cards in Workstream Detail.

```yaml
business_lens:
  title: AR Business Impact
  subtitle: Cash exposure and aging risk across the dispute backlog
  primary_entity_label: Customer
  secondary_entity_label: Invoice
  value_label: Exposure
  metrics:
    - id: total_exposure
      label: Total Exposure
      value: "$390.2K"
      unit: currency
      trend: "+8%"
      severity: high
      explanation: Open disputed receivable value across visible cases.
    - id: sla_risk
      label: SLA / Aging Risk
      value: "2 cases"
      severity: critical
      explanation: Cases breaching or nearing SLA.
```

Use these fields for domain-neutral rendering:

- `label`: business-friendly metric name.
- `value`: initial seed value. The backend refresh overwrites it from item state
  when the workstream is saved, run by cron/run-now, or changed by item actions.
- `unit`: optional category such as `currency`, `cases`, `tickets`, `users`, or `hours`.
- `trend`: optional movement indicator such as `+8%`, `-2 days`, or `flat`.
- `severity`: `low`, `medium`, `high`, or `critical`.
- `explanation`: one-line reason the metric matters.

Use `business_lens` for workstream-wide questions like “How much cash is at
risk?” or “How many SLA breaches are in this backlog?” Use `case_summary` and
`case_insights` for individual case rows.

See the worked `ar_dispute_resolution` example later in this guide for a
domain-specific walkthrough using the same generic contract.

For packaged Workstreams that should appear in the Cron page after install or
restore, include both `cron_schedule` and `cron_user_id` at the YAML top level.
Studio startup reconciles those fields into a `ws_<workstream_name>` cron job
and persists the live `cron_job_id` back into the YAML.

At runtime, `WorkstreamStore` calls `refresh_business_lens()` after state writes.
The aggregator preserves the workstream's `business_lens` title, labels, units,
and explanations, but recomputes metric `value` and `severity` from active item
metadata. It uses generic fields such as `case_summary.primary_entity`,
`case_summary.impact_value`, `case_summary.age_or_sla`,
`case_summary.risk_level`, `case_summary.recommended_action`,
`case_summary.policy_trigger`, item `status`, and approval markers. Completed
items are excluded from active business-impact rollups so values reduce as the
workstream closes work.

In Workstream Detail, each `business_lens.metrics` card is also an AskTwin entry
point. When a user clicks a metric, the page opens the shared AskTwin side panel
in a docked Workstream mode that follows the current page theme, and sends a
short visible question such as “Explain the Customers Impacted metric for this
workstream.” The selected metric, workstream, visible cases, status counts, and
current lens mode travel separately as page context, so follow-up questions can
ask for contributing customers, pending invoices, cases, or other domain records
without exposing raw JSON in the chat. Write `label` and
`explanation` values as business-facing phrases that are useful in a question,
for example:

- Good: `90+ Day Exposure` with `Aged dispute value requiring approval before credit or write-off.`
- Good: `SLA / Aging Risk` with `Cases breaching or nearing SLA.`
- Avoid: internal-only labels such as `metric_2`, `bucket_a`, or `calc_value`.

## Create The Worker Skill

Create the skill at:

```text
IAF-Agent-Skills/skills/<skill_name>/SKILL.md
```

Minimum frontmatter:

```yaml
---
name: ar_dispute_resolution
version: "1.0"
description: "Resolve AR dispute workstream items and recommend next governed action."
execution_mode: react
tools:
  - run_sql_query
  - query_memory
  - request_human_approval
keywords:
  - ar dispute
  - receivable
  - customer dispute
business_context:
  domain: "Finance & Accounting"
  tower: "Order-to-Cash"
  process: "Accounts Receivable"
  subprocess: "Dispute Resolution"
  entity_type: "case"
  sla_days: 3
approval_rules:
  default_urgency: medium
  thresholds:
    - field: "amount"
      operator: ">="
      value: 100000
      reason: "High-value dispute requires manager approval"
      urgency: high
---
```

In the body of `SKILL.md`, include an output instruction like this:

````markdown
## Workstream Item Output

When processing a workstream item, return a clear result summary and include
domain-neutral case metadata whenever the facts are available.

Use this shape:

```yaml
case_summary:
  case_id: string
  case_type: string
  title: string
  primary_entity: string
  secondary_entity: string
  category: string
  impact_label: string
  impact_value: string
  age_or_sla: string
  risk_level: low | medium | high | critical
  priority_reason: string
  recommended_action: string
  recommendation_confidence: number
  policy_trigger: string
  evidence_summary: string
  resolution_mode: string
  auto_resolution_status: string
  auto_resolution_reason: string
  analyst_action: string
  audit_summary: string
case_insights:
  current_findings:
    - string
  historical_patterns:
    - label: string
      value: string
      explanation: string
  recommendation_reasoning:
    - string
  prevention_opportunities:
    - string
  research_pack:
    - label: string
      source_type: string
      status: checked | missing | blocked
      confidence: string
      findings:
        - string
      source_refs:
        - string
  next_best_action: string
  similar_cases:
    - id: string
      summary: string
      outcome: string
      resolution_time: string
```

Populate values from live data, policy, memory, evidence, and prior case
patterns. Do not hardcode invoice-specific labels in the UI contract.
````

## Create The Workstream

Workstreams live at:

```text
enterprise_root/tenants/company/workstreams/<name>.yaml
```

Example:

```yaml
name: ar_dispute_resolution
display_name: AR Dispute Resolution
description: Resolve high-priority receivable dispute cases.
skill: ar_dispute_resolution
status: active
priority_strategy: highest_amount
max_attempts_per_item: 2
batch_size: 1
parallelism: 1
business_lens:
  title: AR Business Impact
  subtitle: Cash exposure and aging risk across the dispute backlog
  primary_entity_label: Customer
  secondary_entity_label: Invoice
  value_label: Exposure
  metrics:
    - id: total_exposure
      label: Total Exposure
      value: "$390.2K"
      unit: currency
      severity: high
      explanation: Open disputed receivable value across unresolved cases.
items:
  - id: inv-ar-0093
    description: Resolve disputed receivable INV-AR-2026-0093.
    priority_metric: 118200
    acceptance_criteria:
      - Dispute category recorded
      - Resolution recommended
      - Approval obtained if policy requires it
    case_summary:
      case_id: INV-AR-2026-0093
      case_type: AR dispute
      title: Cascade Union Bank high-value aged dispute
      primary_entity: Cascade Union Bank
      secondary_entity: INV-AR-2026-0093
      category: Aged high-value receivable
      impact_label: Exposure
      impact_value: "$118,200"
      age_or_sla: 90+ days
      risk_level: critical
      priority_reason: Highest value item and aged 90+ days
      recommended_action: Escalate for AR Manager approval before credit or write-off
      recommendation_confidence: 0.89
      policy_trigger: Amount >$100k and 90+ days requires approval
      evidence_summary: Review receivable record, dispute notes, and supporting invoice evidence.
    case_insights:
      current_findings:
        - Dispute exceeds the AR Manager threshold.
      historical_patterns:
        - label: 90+ day disputes
          value: Elevated write-off risk
          explanation: Aged disputes usually need a clear collect vs credit vs write-off path.
      recommendation_reasoning:
        - Amount is above the approval threshold.
        - Aging is 90+ days.
      prevention_opportunities:
        - Capture dispute category and supporting documents earlier.
      similar_cases:
        - id: INV-AR-2026-0074
          summary: Large-bank short-pay dispute resolved after documentation pack.
          outcome: Partial credit approved
          resolution_time: 6 days
```

The `case_summary` and `case_insights` blocks are optional. If they are missing,
the Workstream Detail UI falls back to `id`, `description`, `priority_metric`,
`status`, evidence, suggested actions, and acceptance criteria. When
`case_insights.research_pack` is present, Workstream Detail renders a generic
Research Pack tab that shows checked systems, findings, confidence, source refs,
and the next-best action. When `case_summary.resolution_mode` is `auto_resolved`, the Overview tab shows an auto-resolution callout so the analyst can review audit evidence instead of reworking the case.

## Field Rules

- `case_summary.case_id` should be the business-facing case identifier.
- `case_summary.case_type` should stay domain-neutral enough for the workbench,
  such as `AR dispute`, `IT ticket`, `reconciliation break`, or `policy exception`.
- `primary_entity` is the main party or system, such as customer, supplier,
  application, account, project, or owner.
- `secondary_entity` is the related record, such as invoice, ticket, PO, document,
  alert, journal, or incident id.
- `impact_value` should be human-readable, for example `$118,200`, `P1 outage`,
  `4 users blocked`, or `SLA breached`.
- `risk_level` must be one of `low`, `medium`, `high`, or `critical`.
- `recommended_action` should describe the next governed action, not a UI label.
- `recommendation_confidence` can be `0.0` to `1.0` or a percentage-like number.
- `case_insights.prevention_opportunities` should capture future-of-work or
  upstream process improvements, not just the current fix.
- `case_insights.research_pack` should describe pre-research already completed
  by the agent across systems or evidence sources. Keep source names domain-aware,
  but keep the field names generic.
- `case_summary.resolution_mode = auto_resolved` should mean the agent completed
  routine work inside policy and the analyst only needs audit review. Do not use
  it for approval-gated, fraud-risk, or novel judgement cases.

## API Shape

When creating a workstream through the API, pass the same item fields:

```json
{
  "name": "ar_dispute_resolution",
  "skill": "ar_dispute_resolution",
  "priority_strategy": "highest_amount",
  "items": [
    {
      "id": "inv-ar-0093",
      "description": "Resolve disputed receivable INV-AR-2026-0093",
      "priority_metric": 118200,
      "acceptance_criteria": ["Resolution recommended"],
      "case_summary": {
        "case_id": "INV-AR-2026-0093",
        "case_type": "AR dispute",
        "title": "Cascade Union Bank high-value aged dispute",
        "risk_level": "critical",
        "recommended_action": "Escalate for AR Manager approval"
      },
      "case_insights": {
        "current_findings": ["Amount and aging cross approval thresholds"],
        "recommendation_reasoning": ["Policy requires approval"]
      }
    }
  ]
}
```

Item and workstream continuation chats store only the most recent transcript
turns on the workstream YAML, with item response previews bounded at 8,000
characters so normal operator answers are not clipped. The Workstream Detail UI also uses the full
response returned by the chat API for the just-submitted turn, so long answers
are visible immediately and then remain available after refresh through the
bounded transcript preview.

Item chat requests may include `skill_name` to force a specific AgentPro skill
for that turn. The endpoint still attaches bounded workstream item context before
delegating to `/api/chat`, so explicit skill invocation keeps the case context
while using the selected skill's normal routing, entitlement, tool, and HITL
controls.
When that chat turn raises a business HITL approval, the REST chat checkpoint is
persisted to the shared approval store and the item is stamped with
`status=awaiting_human`, `escalated_approval_id`, and `last_approval_context`.
This makes the approval appear in both Command Center and the workstream-filtered
approval inbox. The stamp is applied only when the approval context matches the
current `workstream_name` and `mission_item_id`, so stale approvals from another
item cannot relink the current case.
Governed connector components can also raise linked approvals. For example,
`post_to_sap` sends `metadata.workstream_name` and `metadata.mission_item_id`
with the payload; high-value connector submissions create a Command Center HITL
approval and stamp the same item as `awaiting_human`.

## Validation Checklist

- The skill exists in `IAF-Agent-Skills/skills/<skill_name>/SKILL.md`.
- The workstream `skill:` value matches the skill `name`.
- Each item has a stable `id` and useful `description`.
- High-priority sorting has `priority_metric` where applicable.
- `case_summary` uses generic fields, not invoice-only UI names.
- `case_insights` explains current findings, patterns, reasoning, prevention,
  and similar cases where available.
- Any side-effecting action is routed through governed actions or HITL approval.
- Evidence and audit trail remain attached to the item.
- REST and live WebSocket access use the authenticated tenant identity and
  `workstream` entitlement; client-supplied user/tenant values are not authority
  in authenticated deployments.
- Cron/queue service principals can use only the explicit skills, tools, and
  external resources enumerated in tenant policy.
