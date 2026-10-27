# IAF AgentPro — Help Guide Index

This index is used by the `iaf_guide` skill that powers Ask Twin. Ask Twin passes page-scoped current page context into the chat prompt, then this guide helps the skill find the right product documentation.

## Documentation Map

| Page | URL | Help File | Covers |
|---|---|---|---|
| Chat UI | `/` | `chat_ui.md` | Chat, sessions, routing, approvals, memory, Ask Twin |
| Dashboard V2 | `/dashboard/v2` | `dashboard_ui.md` | Overview, approvals, knowledge, cron, traces, command-center operations |
| Skill Builder V2 | `/skill-builder/v2` | `skill_builder_ui.md` | Skills, execution modes, agent config, tools, MCP, testing |
| Workstreams | `/static/workstreams.html` | `workstreams_ui.md` | Workstream index, creation wizard, detail cockpit, item context |
| FinOps | `/finops` | `optimization_ui.md` | LLM cost analytics, model/user/skill costs |
| Optimization | `/twin/optimization` | `optimization_ui.md` | ESAA recommendations and Discuss with Ask Twin |

## Ask Twin Context

When the prompt includes `[ASKTWIN PAGE CONTEXT]`, answer for that live page first. Common fields include:

- `source_page`: route or page id, such as `dashboard_v2`, `skill_builder_v2`, `workstream_detail`, or `finops`
- `page`: active tab or screen
- selected skill, agent, workstream, item, recommendation, or filter
- visible KPI summaries, counts, and generic `visibleRecords` / `visibleRecordKeys`

Use the context to avoid generic answers. If the user asks "what is this?", refer to the current page/tab/item from the context. Current page context overrides earlier AskTwin topics from other pages.

## Common Questions

| Question | Look in |
|---|---|
| How do I create or edit a skill? | `skill_builder_ui.md` |
| Why is my agent routing to the wrong skill? | `chat_ui.md`, `skill_builder_ui.md` |
| How do approvals work? | `chat_ui.md`, `dashboard_ui.md`, `workstreams_ui.md` |
| What am I seeing on Dashboard V2? | `dashboard_ui.md` |
| How do I create or monitor a Workstream? | `workstreams_ui.md` |
| What does this FinOps/optimization metric mean? | `optimization_ui.md` |

## Answer Style

- Keep Ask Twin answers compact and readable in a side panel.
- Use short headings, bullets, and numbered steps.
- Avoid wide tables unless needed.
- If the docs do not cover the question, say that directly.
