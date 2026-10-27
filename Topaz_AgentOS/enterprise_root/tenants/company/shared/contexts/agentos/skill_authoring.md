# Skill Authoring

A skill is **one Markdown file** with YAML frontmatter + a body. Drop it
under `enterprise_root/tenants/<tenant>/skills/<name>/SKILL.md`, register
in `_index.yaml`, and the loader hot-reloads it.

## Minimum viable SKILL.md

```yaml
---
name: my_skill
execution_mode: react
description: "What this skill does in one sentence."
tools: [shell, query_memory]
---
# Persona
You are a <role>. Be concise and ground answers in tool output.

# Instructions
1. ...
2. ...
```

## Common frontmatter fields

| Field | Purpose |
|---|---|
| `name` | Skill identifier (matches folder name) |
| `execution_mode` | react · workflow · parallel · supervisor · orchestrator |
| `tools` | Whitelist of tool names the agent may bind |
| `triggers` | Phrases the router matches against user queries |
| `context_files` | Reusable markdown to inject into the prompt |
| `worker_skills` | For supervisor/orchestrator — names of workers |
| `steps` | For workflow/parallel — declared DAG |
| `approval_rules` | HITL gates per tool/action |
| `sql_mode` | `read_only` (default) or `read_write` |
| `max_steps` | Cap iterations / steps |
| `entitlements` | Policy hints for the entitlement layer |

Full schema: docs/schemas/skill.schema.json

## Authoring shortcuts

- VS Code: install YAML extension → add `# yaml-language-server: $schema=...`
  comment at top of SKILL.md → autocomplete + validation.
- Templates per execution mode: `docs/skill_templates/{react,workflow,parallel,supervisor,orchestrator}/SKILL.md`
- Auto-generate from a PDF/transcript/SOP: open `/skill-creator` and upload.

## Where authored skills live

```
enterprise_root/tenants/<tenant>/skills/<skill_name>/
└── SKILL.md
```

Plus an entry under `skills:` in `enterprise_root/tenants/<tenant>/skills/_index.yaml`.

Read more: docs/AUTHORING_GUIDE.md · docs/skill_templates/README.md
