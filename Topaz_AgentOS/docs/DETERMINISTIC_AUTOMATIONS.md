# Deterministic Automations

Deterministic Automations are no-LLM pipelines for running fixed shell and
Python steps. They are separate from Skills and from `execution_mode: workflow`.

## When To Use

Use an Automation when you need a predictable sequence of scripts or commands:

- Run Python programs in order without asking an LLM to decide anything.
- Reuse outputs from earlier steps with `{{step_name.output}}`.
- Schedule the pipeline through standalone cron YAML.
- Attach the pipeline to a Workstream item processor.

Use a Skill when the task needs reasoning, routing, tool selection, evidence
collection, or human approval decisions.

## Storage Layout

Automation definitions live in tenant business state:

```text
enterprise_root/tenants/<tenant_id>/automations/<automation_id>.yaml
enterprise_root/tenants/<tenant_id>/shared/scripts/*.py
enterprise_root/tenants/<tenant_id>/shared/databases/automation_runtime.db
```

The YAML definition is the source of truth. `automation_runtime.db` stores run
and step traces so the UI can show history after refresh or restart.

Enterprise backup manifests include both files. Recovery Readiness parses
restored automation YAML, validates `automation_runtime.db` with SQLite
`PRAGMA quick_check`, and compares capture-time checksums without executing any
restored script.

## YAML Schema

```yaml
id: nightly_close
name: Nightly Close Pipeline
description: Deterministic end-of-day steps, no AI
enabled: true
steps:
  - name: extract
    action: python
    params:
      script: reconcile.py
      args: "--date today"
  - name: publish
    action: shell
    params:
      command: "cp /shared/out/rollup.csv /shared/published/"
  - name: gate
    action: condition
    if: "{{publish.output}}"
    contains: "ERROR"
    then_step: notify_fail
    else_step: done
```

Allowed actions are `shell`, `python`, and `condition`. `skill` actions are
rejected before execution, which guarantees the no-LLM path.

## REST API

- `GET /api/automations`
- `GET /api/automations/{automation_id}`
- `POST /api/automations`
- `DELETE /api/automations/{automation_id}`
- `POST /api/automations/{automation_id}/run`
- `GET /api/automations/{automation_id}/runs`
- `GET /api/automations/runs/{run_id}`

## Cron Trigger

Standalone cron YAML can run an Automation by using `skill_name: automation` and
putting the automation id in `task`:

```yaml
id: nightly_close_cron
name: Nightly Close Cron
skill_name: automation
task: nightly_close
cron: "0 2 * * *"
user_id: scheduler
```

Studio reconciles this YAML into Redis the same way other standalone cron jobs
are reconciled.

## Workstream Trigger

Workstreams can use deterministic processing by declaring `automation` instead
of `skill`:

```yaml
name: close_pipeline
display_name: Close Pipeline
automation: nightly_close
items:
  - id: close_001
    description: Run close pipeline for today's batch
```

Existing skill-backed workstreams continue to use `skill`.

## Python Execution

The `python` action runs scripts through the configured AgentOS kernel runtime
as:

```text
python3 /shared/scripts/<script> <args>
```

Deployments that want to execute Python through the kernel must enable guarded
Python support (`AGENT_PYTHON3_ENABLED=true`) and keep scripts inside
`/shared/scripts`. `AGENTOS_KERNEL_BACKEND=local` uses the in-process
`SafeKernel`; `AGENTOS_KERNEL_BACKEND=remote` sends automation shell/Python
steps to the signed kernel worker while keeping the same virtual paths.

With `ENTERPRISE_STRICT_MODE=true`, Python also requires a provisioned
`AGENT_PYTHON3_SANDBOX_USER`. The kernel uses isolated Python under that OS
identity with a minimal environment and CPU/memory limits. Scheduled automation
reconciliation belongs to the elected scheduler role; API replicas do not start
automation schedulers.

Scheduler/queue automation workers do not depend on the API session store. API
and queue roles may initialize their own durable runtime stores for reads or
processing, but scheduler reconciliation still belongs only to the elected
scheduler role.
Interactive automation calls handled by strict API replicas use shared Redis
sessions and inherit `/health/ready` session dependency checks.
