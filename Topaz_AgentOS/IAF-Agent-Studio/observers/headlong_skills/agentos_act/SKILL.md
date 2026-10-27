# Skill: agentos_act

Request a **governed action** from AgentOS. This is the ONLY way an observer can
cause anything to happen in the world — you cannot write, modify, or delete
directly. You describe what should happen; a human governs whether it does.

## When to use

Call this when your own judgement says a specific person should act on something
you observed — a correction, an anomaly, a risk, a decision that needs a human.
(Hard, numeric rules are handled automatically by the sidecar; use this for the
softer, judgement calls that only you would notice.)

Do NOT use it for status pings or to re-report something already actioned.

## How to call

```bash
agentos_act --skill <skill_name> --task "<what to do>" [--context "<why / evidence>"]
```

- `--skill`   the AgentOS skill to run (e.g. ap_ops, notify). Must be permitted
              by this observer's trust tier + allowlist, or it will be denied.
- `--task`    a clear, single-sentence instruction for the skill.
- `--context` optional supporting evidence (what you saw, trajectory refs).

The request goes to the AgentOS gateway, is checked against policy, and — if
allowed — routed to a human for approval. You will not see the outcome directly;
the person receives it through AgentOS.

## Example

```bash
agentos_act --skill ap_ops \
  --task "Flag invoice INV-4821 from ACME for manual review" \
  --context "3 ACME invoices today just under the 80k threshold — possible split"
```
