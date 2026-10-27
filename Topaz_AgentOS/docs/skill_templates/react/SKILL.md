# yaml-language-server: $schema=../../schemas/skill.schema.json
---
name: my_react_skill
version: "1.0"
description: >-
  Default conversational skill. The LLM decides which tool to call on each turn
  based on user input and accumulated context. Best for open-ended Q&A,
  exploratory analysis, and tasks where the path isn't known in advance.
execution_mode: react

triggers:
  - "trigger phrase one"
  - "trigger phrase two"

tools:
  - shell
  - query_memory
  - run_sql_query

sql_mode: read_only
max_steps: 10

context_files:
  - shared/contexts/<taxonomy>/<reference>.md

business_context:
  domain: <business domain — e.g. finance, hr, sales>
  process: <process this skill operates on>
  rules:
    - id: r1
      description: <hard rule the skill must never violate>

sufficiency_criteria:
  - "User question is fully answered with cited evidence"
  - "All requested entities are resolved"
---

# Persona

You are a <role> for <domain>. Be concise, ground answers in tool output,
and never invent values.

# Guardrails

- Never <forbidden action>.
- Always <required action>.
- Escalate via `request_human_approval` when <condition>.

# Instructions

1. Understand the user's intent.
2. Use `query_memory` first to check for prior context.
3. Use `run_sql_query` or `shell` to gather facts.
4. Synthesize and answer. Cite the tool calls that produced each fact.
