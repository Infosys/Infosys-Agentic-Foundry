# SKILL.md Authoring Templates

Starter `SKILL.md` files for the five core `execution_mode` values. Copy the
folder matching the mode you want, rename it to your skill name, and edit.

The loader also supports a sixth mode, `planned` (DAG planner), which does not
ship a starter template yet — author its frontmatter by hand.

## Pick a template

| Mode | When to use | Template |
|---|---|---|
| `react` | LLM picks tools each turn. Default for chat-style and exploratory skills. | [react/SKILL.md](react/SKILL.md) |
| `workflow` | Deterministic DAG. No LLM between steps. Cheap and reproducible. | [workflow/SKILL.md](workflow/SKILL.md) |
| `parallel` | Fan out independent steps for wall-clock speedup. | [parallel/SKILL.md](parallel/SKILL.md) |
| `supervisor` | Fixed fan-out to a known set of workers, then synthesise. | [supervisor/SKILL.md](supervisor/SKILL.md) |
| `orchestrator` | Manager LLM dynamically dispatches workers based on prior results. | [orchestrator/SKILL.md](orchestrator/SKILL.md) |

## IDE validation

The first line of each template references the JSON Schema:

```yaml
# yaml-language-server: $schema=../../schemas/skill.schema.json
```

With the [YAML Language Server](https://github.com/redhat-developer/yaml-language-server)
extension installed in VS Code (or any compatible editor) the frontmatter
gets autocomplete, hover docs, and red-squiggle validation for typos and
missing required fields.

To validate skills outside your tenant tree, copy the same line into your
SKILL.md and adjust the relative path to point to
`docs/schemas/skill.schema.json` in this repo.

## Schema source

The authoritative schema lives at [../schemas/skill.schema.json](../schemas/skill.schema.json).
It is generated from the fields read by `IAF-Agent-Skills/iaf_agent_skills/loader.py` —
update the schema whenever a new field is added there.

## Where to put the finished skill

After editing, drop the folder under your tenant tree:

```
enterprise_root/tenants/<tenant>/skills/<your_skill_name>/SKILL.md
```

Then add an entry to `enterprise_root/tenants/<tenant>/skills/_index.yaml`
so the loader and router discover it.
