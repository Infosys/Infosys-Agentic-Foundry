# Hooks — Lifecycle Handlers

Hooks fire at well-defined lifecycle points and let you add policy
checks, audit, redaction, retries, and compensation **without modifying
the agent or the harness**.

## The seven hook points

| Point | When it fires | Can block? | Typical use |
|---|---|---|---|
| `pre_tool` | Before every tool invocation | Yes | Entitlement check, scope guard |
| `post_tool` | After every tool invocation | No (audit) | Redact output, log |
| `pre_step` | Before each workflow/orchestrator step | Yes | Approve skill dispatch |
| `post_step` | After each step | No | Persist step result, telemetry |
| `pre_turn` | Before each LLM call | Yes | Inject extra context, refuse |
| `post_turn` | After each LLM call | No | Token accounting, learning extract |
| `on_failure` | On tool/step exception or timeout | Compensate | Cleanup, retry decision |

## Hook signature

```python
# hooks/pre_tool.py
def hook(ctx: dict) -> dict:
    """
    ctx contains: tool, args, skill, user_id, tenant, trace_id, ...
    Return {"allow": False, "reason": "..."} to block.
    Return {"allow": True}  or {} to permit.
    """
    if ctx["tool"] == "shell" and "rm -rf" in ctx["args"].get("command", ""):
        return {"allow": False, "reason": "Destructive command blocked"}
    return {"allow": True}
```

## Sync vs async

- Sync by default.
- If the function name ends with `_async` or returns an awaitable, the
  harness awaits it.
- `post_tool` and `post_step` are commonly async (audit DB writes).
- `pre_*` should stay sync — they gate the next step.

## Circuit breaker via on_failure

```python
# hooks/on_failure.py
_consecutive_failures = 0

def hook(ctx: dict) -> dict:
    global _consecutive_failures
    _consecutive_failures += 1
    if _consecutive_failures > 3:
        return {"action": "halt", "reason": "Too many failures"}
    return {"action": "retry", "backoff_ms": 2000}
```

## Where hooks live

Per skill: `enterprise_root/tenants/<tenant>/skills/<skill>/hooks/`.
Or tenant-wide: `enterprise_root/tenants/<tenant>/hooks/`.

Read more: IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md
