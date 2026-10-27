# yaml-language-server: $schema=../../schemas/skill.schema.json
---
name: my_workflow_skill
version: "1.0"
description: >-
  Deterministic, step-by-step skill. The WorkflowEngine executes the declared
  steps in order with no LLM between steps. Use this when the path is fixed
  and you want reproducible, cheap, auditable runs (e.g. nightly close,
  daily reports, scheduled health checks).
execution_mode: workflow

triggers:
  - "run nightly close"
  - "generate daily report"

tools:
  - shell
  - run_sql_query
  - write_file

sql_mode: read_only

steps:
  - name: fetch_data
    action: run_sql_query
    params:
      query: "SELECT * FROM ar_aging WHERE days_overdue > 60"

  - name: check_threshold
    action: condition
    if: "{{fetch_data.output}}"
    contains: "row"
    then: escalate
    else: normal_finish

  - name: escalate
    action: skill
    skill: dunning_letter
    task: "Draft escalation letter for accounts in fetch_data.output"

  - name: normal_finish
    action: shell
    params:
      command: "echo 'No overdue accounts above threshold.'"

  - name: write_report
    action: write_file
    depends_on: [escalate, normal_finish]
    params:
      path: "/tmp/ar_nightly_report.md"
      content: "{{escalate.output || normal_finish.output}}"
---

# Notes

- Workflow steps are referenced as `{{step_name.output}}` in later steps.
- Use `depends_on:` to express ordering when a step has multiple inputs.
- For HITL gates, set `action: request_human_approval` and the engine pauses
  until the approval is granted (resumed from checkpoint).
- No LLM is invoked between steps — the body below is documentation only,
  not a prompt.
