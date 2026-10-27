# Skill Pack Spec v1.0 — Portable Agents

A **Skill Pack** is a single folder that runs on IAF AgentOS, Claude
Cowork, Claude Code, Anthropic Managed Agents, or any compatible
harness. Build once, run anywhere.

## Why the spec exists

Every harness has the same primitives (system prompt, tool whitelist,
sub-agents, hooks, HITL) but a different file layout. The Skill Pack
spec is a **vendor-neutral container** so authors don't lock into one
platform.

## Folder layout

```
my-skill-pack/
├── manifest.yaml          # portable header (required)
├── SKILL.md               # agent definition (required)
├── contexts/              # reusable Markdown (optional)
├── hooks/                 # lifecycle hooks (optional)
├── tools/                 # custom Python tools (optional)
├── viewers/               # HTML viewers (optional)
├── fixtures/              # demo seed data (optional)
├── tests/smoke.yaml       # portable smoke tests
└── README.md              # walkthrough + screenshots
```

**Minimum:** `manifest.yaml` + `SKILL.md` + at least one of `contexts/`
or `tools/`. Everything else opt-in.

## Minimum viable manifest

```yaml
spec_version: "1.0"
name: month_end_closer
version: "1.0.0"
description: "Close the books for a fiscal month — reconcile and flag variances."
agent_type: orchestrator
requires:
  tools: [shell, run_sql_query]
```

## Key portability fields

- `agent_type` — maps to `execution_mode` in SKILL.md
- `recommended_model: { primary: { provider: any, tier: frontier } }` —
  hint, not lock-in; host picks the closest model it has
- `requires` — hard capability contract (tools, storage, hooks, network)
- `callable_agents` — declared sub-agents with version constraints
- `inputs` / `outputs` — typed contract for chaining packs
- `compatibility.<host>: {}` — per-host shim hints

## How each host adapts

| Host | What happens at install |
|---|---|
| **IAF AgentOS** | Folder drops under tenant `skills/`, loader reads SKILL.md frontmatter directly |
| **Claude Cowork / Code** | Shim reads `manifest.yaml` → generates Cowork `plugin.json` |
| **Managed Agents** | Manifest → cookbook YAML; SKILL.md body → agent prompt |
| **Custom Python loop** | Library reads manifest, validates `requires:` against host |

Read more: docs/SKILL_PACK_SPEC.md · docs/schemas/skillpack.schema.json
