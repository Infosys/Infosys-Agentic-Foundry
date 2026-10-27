# AgentOS — Overview

IAF AgentOS is the **operating system for agents**. You write apps (skills),
the harness handles every concern that's not specific to your app:
execution, memory, models, governance, HITL, scheduling, observability.

## The two layers

```
LAYER 2 — Apps on top         IAF-Agent-Studio + tenant data
                              (UI, routers, auth, finops, etc.)
LAYER 1 — Core harness        IAF-Agent-Skills/ + agent_os/
                              (loader, kernel, models, hooks, memory)
```

You never edit Layer 1. You drop a `SKILL.md` and it works.

## What the harness gives you for free

- Sandboxed shell + Python execution (kernel)
- Multi-provider model selection (Azure / OpenAI / Vertex)
- Skill router (taxonomy + keywords + semantic)
- 5 execution modes (react / workflow / parallel / supervisor / orchestrator)
- 7 lifecycle hook points (pre/post tool & step, pre/post turn, on-failure)
- 3-layer memory (episodic JSONL + knowledge index + Redis session)
- ContextOS taxonomy + Enterprise_Context.md injection
- Entitlements (XACML-style) + external-access governance
- HITL approvals queue with workflow checkpoints
- Cron scheduler + async job queue
- Live FinOps dashboard at `/finops`
- Doc → Skill pipeline at `/skill-creator`
- Portable Skill Pack Spec v1.0 (run anywhere)

## Audience fit

- **Domain experts** — author SKILL.md in Markdown; no Python required.
- **Platform devs** — extend tools, hooks, execution modes in Python.
- **Operators** — deploy, schedule, monitor, govern.

Read more: docs/03_architecture.md · docs/KEY_FEATURES.md
