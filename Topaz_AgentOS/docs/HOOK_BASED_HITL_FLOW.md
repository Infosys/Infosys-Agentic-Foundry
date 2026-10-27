# Hook-Based HITL Flow

This document explains how a `PreToolUse` hook can force Human-in-the-Loop (HITL) approval programmatically before a risky tool call executes.

## Purpose

The goal is to make HITL deterministic and programmatic, instead of relying only on prompt instructions such as "call `request_human_approval` before payment release".

With hook-based HITL, the platform inspects the actual tool call before execution. If the tool call matches a high-risk pattern, the hook blocks the call. The governance layer then converts that block into a pending human approval.

## Configured Hook

The hook was configured on the tenant agent config:

`enterprise_root/tenants/company/agents/enterprise_agent/config.yaml`

```yaml
hooks:
  PreToolUse:
    - command: python3 $IAF_AGENT_ROOT/../../shared/hooks/l3_payment_url_guard.py
      matcher: shell
      mode: blocking
      fail_policy: closed
      block_on_nonzero: true
      skills:
        - fa_ap
        - invoice_processing_ap
      hook_id: tenant_fa_ap_payment_release_hitl
```

### Why `PreToolUse`

`PreToolUse` is the correct event because the approval must happen before the tool executes.

For payment release, the risky action is a shell command such as:

```text
curl -s -X POST -H "X-API-Key: <admin-key>" http://localhost:9092/payments/release -d '{"invoice_id":"INV-3040"}'
```

A `PostToolUse` hook would be too late because the payment release command could already have executed. `AfterApprovalResume` is also not suitable for forcing approval because it runs only after a human decision has already been recorded and resume has happened.

## Hook Script

The hook uses the existing script:

`enterprise_root/tenants/company/shared/hooks/l3_payment_url_guard.py`

The script checks the pending tool call input for destructive finance endpoints:

```python
DESTRUCTIVE = re.compile(
    r"(?:/payments/release\b|/vendors/[^/\s\"']+/bank_details\b)",
    re.IGNORECASE,
)
```

When the command contains `/payments/release` or a vendor bank detail endpoint, the script prints a JSON reason and exits with code `1`:

```python
print(json.dumps({
    "reason": (
        "L3 Hook C (skill-agnostic URL guard) denied destructive "
        "endpoint ... requires explicit HITL approval"
    ),
}))
return 1
```

Because the hook config has `block_on_nonzero: true`, exit code `1` means the tool call is blocked.

Because the hook config has `fail_policy: closed`, hook execution failure is also treated safely: the protected tool call is denied rather than silently allowed.

## Runtime Flow

1. A queue item starts and routes to a skill, for example `invoice_processing_ap`.

2. The agent decides to call the `shell` tool.

3. Before the shell tool executes, the tool governance layer calls the hook runner:

```python
hook_result = agent.hook_runner.run_pre_tool(
    tool_name=tool_name,
    tool_input=tool_args,
    session_ctx=session_ctx,
)
```

4. The hook runner checks matching `PreToolUse` hooks.

The configured hook matches when:

- `tool_name` matches `shell`
- the active skill is `fa_ap` or `invoice_processing_ap`

5. The hook script receives the tool context through environment variables, including:

```text
IAF_TOOL_NAME=shell
IAF_SKILL_NAME=invoice_processing_ap
IAF_TOOL_INPUT=<serialized tool input containing the shell command>
```

6. The hook script detects `/payments/release`, prints the reason, and exits `1`.

7. The hook runner converts that nonzero exit into:

```python
HookResult(blocked=True, reason=<hook reason>)
```

8. The tool governance layer sees that the hook blocked the call. It holds the original tool call and creates an approval payload on the agent:

```python
agent.pending_tool_call = tool_call
agent.approval_pending = {
    "approval_id": <uuid>,
    "reason": reason,
    "context": {
        "tool": tool_name,
        "command": <bounded command preview>,
        "skill": current_skill,
    },
    "options": ["Approve", "Reject"],
    "urgency": "high",
    "rule_type": "pre_tool_hook",
}
```

9. The queue processor sees `agent.approval_pending` after the agent pauses.

10. The queue processor persists the approval into Redis through the ApprovalStore and updates the queue item:

```text
queue_items.status = awaiting_human
job_executions.status = awaiting_human
```

11. The Queue Monitor / approval UI shows the pending approval with Approve / Reject actions.

12. When a human approves, the platform resumes the held `pending_tool_call`.

## Key Difference From Prompt-Based HITL

Prompt-based HITL depends on the model deciding to call `request_human_approval` based on skill instructions and approval rules.

Hook-based HITL does not depend on the model making that decision. The actual tool call is inspected before execution. If it matches the deterministic hook logic, the platform blocks it and creates approval.

In short:

```text
PreToolUse hook detects risky command
-> hook exits 1 with reason
-> HookRunner blocks tool call
-> tool_governance converts block into agent.approval_pending
-> queue processor persists approval and marks item awaiting_human
-> UI shows approval action
```

## Validated Example

A live queue test was run against `invoice_processing_ap`, which has shell access but does not rely on the `request_human_approval` prompt path for this scenario.

Queue item:

```text
CC-ED14E9E9
```

Result:

```text
status = awaiting_human
routed_skill = invoice_processing_ap
```

Execution summary:

```text
Awaiting approval

Reason: L3 Hook C (skill-agnostic URL guard) denied destructive endpoint '/payments/release' -- requires explicit HITL approval
```

ApprovalStore record:

```text
approval_id = 43a0562c-02c8-4f64-abe8-8b915523a986
user_id     = queue_CC-ED14E9E9
skill       = invoice_processing_ap
options     = ["Approve", "Reject"]
urgency     = high
```

This validates that the HITL trigger came from the programmatic `PreToolUse` hook path.

## Notes

A separate test item routed to `fa_ap` paused through the skill's own prompt approval rules before reaching the shell command. That item still demonstrated HITL, but it was not the clean proof of hook-only HITL.

For clean hook-only validation, use a shell-capable skill without prompt approval rules, or ensure the task reaches the protected tool call before any prompt-based approval rule fires.
