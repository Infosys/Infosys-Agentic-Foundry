# yaml-language-server: $schema=../../schemas/skill.schema.json
---
name: my_supervisor_skill
version: "1.0"
description: >-
  Fixed fan-out to worker skills. The SupervisorEngine dispatches the same
  goal (or per-worker tasks) to every worker in worker_skills concurrently,
  then synthesises a final answer. Use this when you know up-front which
  workers should weigh in (e.g. compliance + legal + finance review in one
  shot).
execution_mode: supervisor

triggers:
  - "review deal from all angles"
  - "cross-functional check"

worker_skills:
  - name: compliance_check
    task: "Assess regulatory exposure for the proposed deal"
  - name: legal_review
    task: "Flag contractual risks in the term sheet"
  - name: finance_check
    task: "Evaluate IRR and capital impact"

max_steps: 1

tools:
  - invoke_skill
---

# Persona

You are the supervisor coordinating a fixed set of expert workers. After
all workers respond, synthesise a recommendation citing each worker's input.

# Synthesis rules

1. Lead with the headline recommendation.
2. Group findings by worker so reviewers can see each perspective.
3. Surface contradictions explicitly — don't average them away.
4. If any worker returns "blocker", recommend pause and escalate.
