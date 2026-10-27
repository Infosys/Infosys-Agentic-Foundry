# Designer Studio Help

Designer Studio is the design studio for creating skills, workstreams, cron jobs, and configuring agents.
It also includes an Automations tab for deterministic no-LLM shell/python
pipelines stored under `enterprise_root/tenants/<tenant>/automations/`.

The theme selector supports dark and light views. In light mode,
hover states in dense panes such as Context Explorer use light blue surfaces
with dark text so file names remain readable. The `SKILL.md` preview uses a
light preview surface in light mode so the generated YAML and prompt text
remain legible.

## Ask Twin Context

Ask Twin on Skill Builder V2 receives:

- active designer tab
- selected or editing skill
- execution mode
- skill category
- agent config draft
- workstream create/edit draft
- skills mode, selected skills, allowed tools, and MCP connection count
- library counts for skills, workstreams, agents, and tools

Use this context to answer questions about the current form or selected skill.

## Skills

Use the Skills tab to create or edit skill definitions. Key fields include:

- Name and description
- Execution mode: REACT, WORKFLOW, PARALLEL, SUPERVISOR
- Prompt
- Tools
- Context file
- Knowledge files
- Component HTML
- Worker skills or steps for non-REACT modes

Use **Context Explorer** to browse and edit enterprise context, knowledge,
policies, standards, and skill files from one place. The older Context Manager
surface is no longer shown as a separate navigation item.

## Automations

Use Automations for fixed shell/python pipelines that should not involve an LLM.

- Create or edit ordered `shell`, `python`, and `condition` steps
- Run the pipeline immediately and inspect recent run traces
- Reference earlier output with `{{step_name.output}}`
- Use standalone cron jobs with `skill_name: automation` and `task: <automation_id>`
- Use Workstreams with `automation: <automation_id>` instead of `skill`

Skill steps are intentionally rejected in Automations. Use workflow-mode Skills
when a step needs to call another Skill or use LLM reasoning.

Some platform workflows call tenant skills directly. `policy_authoring` is used
by Dashboard V2 Policy Control to draft managed policy YAML, then the Policy
Control backend validates, simulates, saves, and publishes the resulting hook.
`component_authoring` is used by the Skills editor's Component sub-section (part
of the Capabilities accordion) to draft skill-local HTML components for human
review; it does not save files directly.

## Component (part of Capabilities)

Use the Component sub-section, inside the Capabilities accordion of a saved
skill, to manage `skills/<skill>/component.html`.

- Load and manually edit the current `component.html`
- Create or revise a component with AI, then review before saving
- Preview the component with sample props
- Compare the `skill_component` JSON contract in the prompt with HTML
  `{{placeholder}}` values and `data-field` attributes
- See the served runtime URL: `/api/skills/<skill>/component`

The component displays in chat only when the skill response includes a fenced
`skill_component` block with the skill name and matching props. Informational
answers from the same skill do not automatically show HTML.

For non-admin users, submitting a skill for review first saves the current
personal `SKILL.md` draft and any edited component HTML, then copies both files
into the shared review queue. When the draft was opened from an existing shared
skill, approval updates that shared skill in place so chat can load the expected
`skills/<skill>/component.html`. The submitter is recorded as the skill's owner, so they keep edit access after approval; updating an existing shared skill keeps its original owner and adds the approval as a new version. Brand-new personal skills still use
conflict-safe names when approval would collide with an unrelated shared skill.

## Agent Config

Use Agent Config to manage:

- skills mode: all, allowlist, denylist
- allowed platform tools
- MCP connections
- agent description and metadata

## Workstreams

Use Workstreams to create a Mission Mode workstream or edit supported metadata for an existing workstream.

- Create workstreams with worker skill, priority strategy, batch size, parallelism, cron schedule, optional `items_source`, `business_lens`, and escalation JSON
- Edit existing display name, owner, description, worker skill, `items_source`, execution settings, cron metadata, business lens, and escalation rules
- Review the generated YAML preview before saving
- Use Cron Jobs for paired schedule updates after a workstream has already been created

## Skill Creator And Studio

The Skill Creator wizard and Studio/customize pages also expose Ask Twin context for wizard step, uploaded files, selected skills, review submissions, and draft metadata.
