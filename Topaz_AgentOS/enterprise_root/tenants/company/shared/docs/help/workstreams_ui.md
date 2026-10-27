# Workstreams Help

Workstreams turn a multi-item backlog into an autonomous, auditable Mission Mode process. The platform processes items over cron ticks or manual runs, with per-item state, evidence, retry, and HITL approval support.

## Ask Twin Context

Ask Twin is available on:

- Workstreams index
- New Workstream wizard
- Workstream Detail cockpit

It receives current filters, visible workstream counts, draft workstream fields, selected workstream, expanded item, approval blockers, item status counts, and recent activity.

## Workstreams Index

Use the index to see active workstreams, backlog health, exceptions, approvals, agents working, pause/resume actions, and sorting/search filters.

## New Workstream Wizard

Key fields:

- Name
- Display name
- Owner
- Worker skill
- Priority strategy
- Batch size
- Parallelism
- Cron schedule
- Items or dynamic `items_source`

Manual items can be entered one by one, pasted as `id | description`, loaded from YAML, or sourced from SQL/HTTP/directory/skill.

## Workstream Detail

The detail cockpit shows:

- status and schedule
- completion, active workers, approvals, exceptions
- item table with expandable details
- item evidence, ledger, actions, and item-scoped chat
- workstream-level chat

If an item is awaiting human input, approvals can be resolved from the detail page or Dashboard V2.
