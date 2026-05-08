# Kafka Message Queue Architecture

## Overview

The IAF platform supports **asynchronous, queue-based inference** using Apache Kafka. This allows you to submit agent or workflow requests without waiting for a real-time response. Requests are placed into a Kafka queue and picked up by dedicated **worker processes** that run independently of the main application.

This is especially useful for:

- **Machine-to-Machine (M2M) integrations** where a calling system doesn't need to hold an open connection.
- **Batch processing** of multiple queries against the same or different agents.
- **Horizontal scaling** — you can spin up as many worker instances as needed to handle load in parallel.

---

## How It Works — High-Level Flow

```
┌──────────────┐       Kafka Topic            ┌─────────────────┐
│  API Request  │ ──▶ iaf_agent_call_requests ──▶ │  Agent Worker   │
│  (Main App)   │                               │  (picks up task) │
└──────────────┘                               └────────┬────────┘
       │                                                │
       │  Returns task_id                               │ Runs inference
       │  immediately                                   │ (agent / workflow)
       ▼                                                │
┌──────────────┐                                        │
│  Client polls │                                        │
│  /task/status │                                        ▼
│  /task/result │                               ┌─────────────────┐
└──────────────┘                               │  Task Registry   │
                                               │  (DB — tracks    │
                                               │   status & result)│
                                               └─────────────────┘
```

When an agent needs to call a tool during inference, the tool call itself is also routed through Kafka:

```
┌─────────────────┐       Kafka Topic              ┌─────────────────┐
│  Agent Worker    │ ──▶ iaf_tool_call_requests ───▶ │  Tool Worker     │
│  (needs a tool)  │                                │  (executes tool)  │
└─────────────────┘                                └────────┬─────────┘
       ▲                                                    │
       │         Kafka Topic                                │
       └──── iaf_tool_call_responses ◀──────────────────────┘
```

**In short:** 

The main application queues the request → an Agent Worker picks it up and runs inference → if tools are needed, they are dispatched to Tool Workers via Kafka → results flow back and are stored in the Task Registry for the client to retrieve.

---

## The Three Roles of the Codebase

This project has **three entry points** that define three distinct runtime roles, all from the same codebase:

| Role | How to Start | Default Port | Purpose |
|---|---|---|---|
| **Main Application** | `python run_server.py` or `python main.py` | 8000 | The primary FastAPI server. Exposes all REST APIs, handles real-time streaming inference, and queues M2M requests into Kafka. |
| **Agent Worker** | `python run_agent_worker.py` or `python agent_worker/main.py` | 8102 | A standalone FastAPI service that consumes agent/workflow requests from Kafka, runs inference, and writes results back to the Task Registry. |
| **Tool Worker** | `python tool_worker/main.py` | 8101 | A standalone FastAPI service that consumes tool execution requests from Kafka, runs the tool (Python-based or MCP), and publishes the result back to Kafka. |

You can run **multiple instances** of Agent Workers and Tool Workers. Kafka's consumer-group mechanism ensures each request is processed by exactly one worker, and adding more workers increases throughput.

---

## Kafka Topics

Three Kafka topics are automatically created on startup:

| Topic | Description |
|---|---|
| `iaf_agent_call_requests` | Agent/workflow inference requests queued by the main application. |
| `iaf_tool_call_requests` | Tool execution requests sent by Agent Workers when an agent needs to invoke a tool. |
| `iaf_tool_call_responses` | Tool execution results published by Tool Workers, consumed by the Agent Worker that requested them. |

---

## API Endpoints

All endpoints are under the `/chat` prefix.

**Submitting Requests**

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/m2m_inference` | Submit a single M2M inference request. Returns a `task_id` immediately. The request is queued in Kafka and processed asynchronously by an Agent Worker. |
| `POST` | `/chat/batch_m2m_inference` | Submit multiple M2M inference requests in one call. Each request becomes an individual task sharing a common `batch_id`. All are queued for parallel processing. |

**Tracking Tasks**

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/chat/task/{task_id}/status` | Check the current status of a task. Returns one of: `queued`, `processing`, `completed`, or `failed`. |
| `GET` | `/chat/task/{task_id}/result` | Retrieve the full result of a completed task, including the conversation history. Returns status-only for tasks still in progress. |
| `GET` | `/chat/tasks/me` | List all M2M tasks created by the current authenticated user. Supports optional `limit` and `status` filters. |
| `GET` | `/chat/tasks/agent/{agent_id}` | List all M2M tasks for a specific agent or workflow. Supports optional `limit` and `status` filters. |

**Tracking Batches**

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/chat/batch/{batch_id}/status` | Get an aggregated status summary for a batch — total count, counts by status, average response time, and whether all tasks are complete. |
| `GET` | `/chat/batch/{batch_id}/tasks` | List all individual tasks belonging to a batch with their individual statuses. |
| `GET` | `/chat/batch/{batch_id}/get-excel-report` | Download an Excel report for the batch containing each task's query, response, status, timing, and error details (if any). |

---

## Request Lifecycle

Here is what happens from the moment you call the API to when you get your result:

- **Client calls** `POST /chat/m2m_inference` (or the batch variant) with the agent ID, model, and query.
- **Main Application** generates a unique `task_id`, registers it in the **Task Registry** (database) with status `queued`, and publishes the request to the `iaf_agent_call_requests` Kafka topic.
- The API returns the `task_id` **immediately** — no waiting.
- An **Agent Worker** picks up the message from Kafka and marks the task as `processing` in the Task Registry.
- The Agent Worker runs the inference. If the agent needs to call tools, those tool calls are published to `iaf_tool_call_requests` and the worker waits for results on `iaf_tool_call_responses`.
- A **Tool Worker** picks up each tool request, executes it, and publishes the result back.
- Once inference is complete, the Agent Worker marks the task as `completed` (or `failed` if an error occurred) in the Task Registry, along with the response time.
- The **client polls** `GET /chat/task/{task_id}/status` or `/result` to retrieve the outcome.

---

## Scaling

- **Agent Workers** share the Kafka consumer group `agent-executor-workers`. Adding more agent worker instances automatically distributes the load across them.
- **Tool Workers** share the Kafka consumer group `tool-executor-workers`. Same principle — more instances means more tools can be executed in parallel.
- Each worker can also handle **multiple requests concurrently** within a single instance (configurable via `WORKER_MAX_PARALLEL_EXECUTIONS`).
- The `iaf_agent_call_requests` topic is configured with multiple partitions (default: 10) to support parallel consumption.

---

## Health Checks

Both the Agent Worker and Tool Worker expose a `GET /health` endpoint that returns whether the Kafka consumer loop is running. This can be used for liveness/readiness probes in container orchestration platforms like Kubernetes.

---

## What to Expect

- **No streaming for M2M:** M2M inference is non-streaming. The full response is available once the task completes.
- **Fault tolerance:** If a worker crashes mid-processing, a recovery mechanism detects stuck tasks and makes them available for re-processing.
- **Same inference quality:** The Agent Worker runs the exact same inference logic as the main application's real-time endpoint — same models, same tools, same workflows.
- **Batch reporting:** For batch runs, you can download a consolidated Excel report with all queries, responses, statuses, and timings in one file.
