# Cron Scheduler — Functionality Guide

## Overview

The IAF Cron Scheduler allows you to run agents on a recurring schedule without manual intervention. You define **when** and **how often** an agent should be invoked, and the platform takes care of dispatching, tracking, retrying logic, and auto-pausing on repeated failures.

Scheduled jobs are stored in a PostgreSQL table, and the scheduler runner ticks every minute to fire due jobs. Each fire dispatches the agent request through the **Kafka message queue** and records the execution outcome in a separate history table.

---

## Prerequisites — Kafka Workers Must Be Running

!!! warning "Hard Requirement"
    The Cron Scheduler dispatches work through Kafka. If the Kafka infrastructure and the worker processes are not running, scheduled jobs will **queue tasks but never execute them**.

The following components **must be operational** for end-to-end scheduled execution:

| Component | Role |
|-----------|------|
| **Apache Kafka broker** | Message bus between the scheduler and workers. |
| **Agent Worker** (`kafka_agent_worker.py`) | Picks up agent inference tasks from the `iaf_agent_call_requests` topic, runs the agent, and publishes results. Also notifies the scheduler of success/failure via the `finalize_worker_outcome` callback. |
| **Tool Worker** (`kafka_tool_worker.py`) | Picks up tool-call sub-requests from the `iaf_tool_call_requests` topic when an agent needs to invoke an onboarded tool during inference. |

If the workers are stopped, the scheduler will still fire and mark executions as `dispatched`, but they will never transition to `succeeded` or `failed` because no worker processes the Kafka messages.

---

## How It Works — End-to-End Lifecycle

```
┌──────────────────────┐
│  Scheduler Runner    │  (ticks every 60 s)
│  checks next_run_at  │
└──────────┬───────────┘
           │  job is due
           ▼
┌──────────────────────┐       Kafka                  ┌───────────────────┐
│  Publish task to     │ ──────────────────────────▶ │  Agent Worker      │
│  iaf_agent_call_     │                              │  runs inference   │
│  requests topic      │                              └─────────┬─────────┘
└──────────┬───────────┘                                        │
           │                                                    │  success / failure
           │  Execution record:                                 │
           │  queued → dispatched                               ▼
           │                                           ┌──────────────────┐
           │                                           │ finalize_worker_ │
           │                                           │ outcome callback │
           │                                           └────────┬─────────┘
           ▼                                                    │
┌───────────────────────┐                                       │
│  History table update │ ◀─────────────────────────────────────┘
│  dispatched →         │
│  succeeded / failed   │
└───────────────────────┘
```

**Execution States**

| State | Meaning |
|-------|---------|
| `queued` | Execution record created; task is about to be published to Kafka. |
| `dispatched` | Task successfully published to Kafka; waiting for the worker to finish. |
| `succeeded` | Worker completed the inference without error. |
| `failed` | Worker encountered an error (response error, exception, timeout). |

---

## Key Concepts

**Page Visibility**

The Scheduler page is conditionally rendered based on feature availability. When the message queue is disabled (`KAFKA_ENABLED=false`), the Scheduler page is automatically hidden from the navigation, since scheduled jobs depend on Kafka for dispatch.

**Searching Scheduled Jobs**

The Scheduler page includes a built-in search feature for locating scheduled jobs. Use the search bar to filter jobs by name, agent, or status — useful when managing a large number of scheduled tasks.

**Creating a Scheduler**

The `New Scheduler` form is accessible from the Scheduler page. Specify a name, select the model and agent to invoke, provide the prompt/query, and configure the timing settings (timezone, mode, frequency, interval, and execution time).


!!! note "Access Control"

    Only users with the **Developer** or **Admin** role can create and manage scheduled jobs. Standard users do not have permission to create, modify, or delete schedules.

**Structured vs. Custom Scheduling**

The scheduler accepts schedules in two forms:

**1. Structured mode** 

pick a frequency (`minutely`, `hourly`, `daily`, `weekly`, `monthly`, `yearly`) and fill in the relevant fields. The backend converts it to a cron expression automatically.

In Structured mode, after selecting a frequency and filling in the fields (e.g., daily with interval 3, hour 9, minute 0), click **Validate** to preview and see the next five upcoming run times.

**2. Custom mode** 

supply a raw 5-field Unix cron expression directly for advanced patterns that the structured form cannot represent.

These two modes are mutually exclusive per schedule.

**Frequency → Required Fields Mapping**

| Frequency | Required Fields | Optional Fields | Example |
|-----------|----------------|-----------------|---------|
| `minutely` | `interval` | — | Every 5 minutes |
| `hourly` | `interval` | `minute` | Every 2 hours at minute :15 |
| `daily` | `interval` | `hour`, `minute` | Every day at 09:30 |
| `weekly` | `days_of_week` | `hour`, `minute` | Mon/Wed/Fri at 20:30 |
| `monthly` | `days_of_month` | `hour`, `minute` | 1st and 15th at midnight |
| `yearly` | `month`, `day_of_month` | `hour`, `minute` | June 15 at 09:00 |
| `custom` | — | — | Raw cron expression required |

In Raw mode, enter a 5-field cron expression directly (e.g., `*/15 9-17 * * MON-FRI`). After validation, the system displays a human-readable interpretation ("Every 15 minutes, between 09:00 AM and 05:59 PM, Monday through Friday") along with the next scheduled runs.


**Auto-Pause on Failures**

Each schedule tracks a `consecutive_failure_count`. When it reaches `max_consecutive_failures` (default: 5), the schedule is automatically paused (`is_active = false`). This prevents runaway broken agents from consuming resources indefinitely.

The counter resets to 0 on any successful execution.

A schedule that has been auto-paused (or manually paused) shows an orange "PAUSED" badge. Click the `Resume` (play) button to reactivate it.

**Auto-Disable Conditions**

A schedule will also self-disable when:

- `max_runs` is set and `run_count` reaches it.
- `end_date` is set and the current time passes it.

The **Advanced Settings** section (collapsed by default) allows you to configure Max Runs (unlimited by default), Max Consecutive Failures (default 5), an optional End Date, temperature for inference, and Inference Flags (Evaluation, Validator, Context, Response Formatting).


**Timezone Handling**

Cron expressions are interpreted in the timezone specified on the schedule (default: `Asia/Kolkata`). All stored timestamps (`next_run_at`, `last_run_at`, execution times) are in UTC for consistency. The conversion happens at fire-time evaluation.

**Task ID Format**

Scheduled tasks use the format `cron_<framework>_<uuid12>` (e.g., `cron_langgraph_a1b2c3d4e5f6`). This prefix allows the agent worker to identify cron-originated tasks and trigger the outcome callback automatically.

Each active schedule card provides a `Run Now` (lightning bolt) button to trigger an immediate execution outside the regular cron cycle. This is useful for testing or on-demand invocations.


---

## Writing Custom Cron Expressions (Advanced)

The standard 5-field Unix cron format is:

```
┌───────────── minute (0–59)
│ ┌───────────── hour (0–23)
│ │ ┌───────────── day of month (1–31)
│ │ │ ┌───────────── month (1–12 or JAN–DEC)
│ │ │ │ ┌───────────── day of week (0–7 or SUN–SAT; 0 and 7 = Sunday)
│ │ │ │ │
* * * * *
```

**Special Characters**

| Character | Meaning | Example |
|-----------|---------|---------|
| `*` | Any value | `* * * * *` = every minute |
| `,` | List of values | `1,15 * * * *` = minute 1 and 15 |
| `-` | Range | `9-17 * * * *` = minutes 9 through 17 |
| `/` | Step (interval) | `*/10 * * * *` = every 10 minutes |

**Practical Examples**

| Expression | Meaning |
|-----------|---------|
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Every hour on the hour |
| `0 9 * * *` | Every day at 09:00 |
| `30 9 * * MON-FRI` | Weekdays at 09:30 |
| `0 0 1 * *` | First of every month at midnight |
| `0 9 15 JUN *` | June 15 at 09:00 (yearly) |
| `0 */2 * * *` | Every 2 hours at minute :00 |
| `0,30 * * * *` | Every half-hour (:00 and :30) |
| `0 9-17 * * *` | Every hour from 09:00 to 17:00 |
| `0 9-17 * * MON-FRI` | Every hour 9–5, weekdays only |
| `*/15 9-17 * * MON-FRI` | Every 15 min during business hours, weekdays |
| `0 0 1,15 * *` | 1st and 15th of each month at midnight |
| `0 6 * * 1,3,5` | Mon/Wed/Fri at 06:00 |
| `0 0 L * *` | Last day of every month at midnight (croniter extension) |
| `0 0 * */3 *` | Every 3 months on the 1st day at midnight |
| `0 22 * * 5` | Every Friday at 22:00 |
| `5 4 * * SUN` | Every Sunday at 04:05 |

**Tips for Complex Schedules**

- **Business hours only**: Use a range in the hour field — `0 9-17 * * MON-FRI`.
- **Multiple specific times**: Separate with commas — `0 8,12,18 * * *` (8 AM, noon, 6 PM).
- **Quarterly**: Step in the month slot — `0 0 1 */3 *` (every 3 months, 1st day).
- **Bi-weekly**: Cron has no native bi-weekly. Use `max_runs` or an external flag. Alternatively, fire weekly and handle alternation in application logic.
- **Day-of-week names**: `SUN`, `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT` (case-insensitive in most implementations, but our system normalizes to uppercase).
- **Month names**: `JAN` through `DEC`.
- **Combining day-of-month and day-of-week**: In standard cron, when both are specified (not `*`), the job fires when *either* condition is met (OR logic), not both. Be cautious — this can produce unexpected fire times.

**Expressions That Cannot Be Structured**

The following patterns require the `Custom` mode (raw `cron_expression`) because the structured form cannot represent them:

- Ranges: `9-17`, `MON-FRI`
- Lists in minute or hour slots: `0,15,30,45`
- Step values in month or day-of-week: `*/3` in month
- Mixed day-of-month + day-of-week constraints
- Extensions: `L` (last), `#` (nth weekday), `W` (nearest weekday)
- Multiple months for yearly: `JAN,JUL`

---

## Failure Handling & Observability

The **History** panel displays all past executions for a schedule, including the timestamp, task ID, execution ID, and outcome (succeeded or dispatched). The total execution count is shown in the top-right corner.

Clicking on an individual execution entry opens the **Execution Detail** view, which shows the complete metadata for a single run — including Execution ID, Task ID, Session ID, Status, Scheduled/Dispatched/Completed timestamps, and Duration — along with the full chat history (user query and agent response) produced during that execution.


**What Counts as a Failure?**

The **agent worker** determines success or failure based on the inference response:

- If the response contains `"error"`, `"errors"`, or `"status": "error"` → marked as `failed` with the error message stored.
- If the worker throws an exception during processing → marked as `failed` with the exception message.
- Otherwise → marked as `succeeded`.

**Counter Behaviour**

| Counter | Incremented When | Reset When |
|---------|-----------------|------------|
| `run_count` | Every dispatch (regardless of outcome) | Never |
| `success_count` | Worker reports success | Never |
| `failure_count` | Worker reports failure | Never |
| `consecutive_failure_count` | Worker reports failure | Worker reports success (reset to 0) |

**Auto-Pause Trigger**

When `consecutive_failure_count >= max_consecutive_failures`:

1. The schedule's `is_active` is set to `false`.
2. A log entry is emitted.
3. The schedule stops firing until manually resumed via the `/resume` endpoint.

---

## Data Retention

**Cascade Deletion**

The `scheduled_jobs` table has a foreign key to `agent_table` with `ON DELETE CASCADE`. This means:

- If an agent is deleted (moved to recycle bin), **all its schedules and execution history are permanently removed**.
- The `schedule_execution_history` table also cascades from `scheduled_jobs`, so deleting a schedule removes all its history entries.

---

## Summary

| Aspect | Detail |
|--------|--------|
| Scheduling engine | Cron-based (5-field Unix), evaluated via `croniter` |
| Dispatch mechanism | Kafka topic (`iaf_agent_call_requests`) |
| Worker requirement | Agent Worker + Tool Worker must be running |
| Timezone | Per-schedule, defaults to `Asia/Kolkata` |
| Failure protection | Auto-pause after N consecutive failures |
| Deletion | Cascades with agent deletion |
| Advanced scheduling | Use raw `cron_expression` with Custom frequency |
