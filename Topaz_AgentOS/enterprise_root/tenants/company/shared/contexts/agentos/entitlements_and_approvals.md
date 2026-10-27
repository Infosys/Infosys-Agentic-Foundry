# Entitlements + HITL Approvals

Two layers of control around what an agent can do: **entitlements**
(policy, fully automated) and **HITL approvals** (humans in the loop).

## Entitlements — XACML-style policy

The provider answers `can(principal, action, resource, context)` for
every gated operation. Policies live at
`enterprise_root/tenants/<tenant>/security/policies.yaml`.

```yaml
# Example policy snippet
- effect: allow
  principal: { role: ar_analyst }
  action:    use
  resource:  { type: tool, id: run_sql_query }
- effect: deny
  principal: { role: ar_analyst }
  action:    use
  resource:  { type: skill, id: payroll_orchestrator }
```

Checked at:

- **Tool invocation** — pre_tool hook
- **Skill dispatch** — pre_step hook (orchestrator/supervisor only)
- **External access** — every outbound HTTP / SQL / MCP call is matched
  against `external_access.yaml` (audit-only or hard-deny mode via
  `EXTERNAL_ACCESS_UNKNOWN_MODE` env var)

## HITL approvals — humans in the loop

Declared in SKILL.md:

```yaml
approval_rules:
  request_human_approval:
    when_amount_gt: 100000           # auto-call approval for > $100k
    approver_role: controller
  shell:
    when_command_contains: ["DELETE", "DROP"]
    approver_role: dba
```

At runtime:

1. Skill calls `request_human_approval` tool (or hits an approval rule).
2. Workflow checkpoints — engine pauses and saves state.
3. Approval queue at `/api/approvals` lists pending items.
4. Approver clicks Approve/Reject → engine resumes from checkpoint.

## Difference between the two

- **Entitlements** = policy decisions (allow/deny) made automatically.
- **Approvals** = decisions a human must make, queued and surfaced.

Use entitlements for rules ("AR analysts can't touch payroll"). Use
approvals for judgements ("this $250k write-off needs the CFO").

Read more: IAF-Agent-Studio/security/ · docs/HITL_DESIGN_GUIDE.md
