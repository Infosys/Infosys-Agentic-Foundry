# yaml-language-server: $schema=../../schemas/skill.schema.json
---
name: my_parallel_skill
version: "1.0"
description: >-
  Fan-out skill. The ParallelEngine runs independent steps concurrently and
  waits for all to finish before the next dependency. Use this when sub-tasks
  don't share data and you want wall-clock speedup (e.g. fetch from 3 systems
  at once, run 5 different checks in parallel).
execution_mode: parallel

triggers:
  - "run all checks"
  - "fetch from all systems"

tools:
  - run_sql_query
  - shell

steps:
  - name: fetch_ar
    action: run_sql_query
    params:
      query: "SELECT count(*) FROM ar_open"

  - name: fetch_ap
    action: run_sql_query
    params:
      query: "SELECT count(*) FROM ap_open"

  - name: fetch_gl
    action: run_sql_query
    params:
      query: "SELECT count(*) FROM gl_pending"

  - name: summarize
    action: shell
    depends_on: [fetch_ar, fetch_ap, fetch_gl]
    params:
      command: "echo 'AR={{fetch_ar.output}} AP={{fetch_ap.output}} GL={{fetch_gl.output}}'"
---

# Notes

- Steps without `depends_on` start in parallel.
- The engine joins at any step that lists predecessors in `depends_on:`.
- Useful pattern: 3-5 parallel fetches followed by a single LLM step that
  synthesises across them (set `action: skill` with a small react skill).
