# Multi-VM Deployment Architecture

## Overview

For load testing and production-readiness validation, the IAF platform was deployed across **3 dedicated Virtual Machines**, each serving a specific role. This document describes the deployment topology, how the components interact, and the request flow across VMs.

---

## VM Layout

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                      VM 1 — Core Services                               │
│                                                                                         │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│   │  IAF Backend │  │  IAF Frontend│  │ Kafka Server │  │   LiteLLM    │                │
│   │  (FastAPI)   │  │  (UI)        │  │ (Broker)     │  │  (LLM Proxy) │                │
│   │  Port: 8000  │  │  Port: 3000  │  │  Port: 9092  │  │  Port: 4000  │                │
│   └──────────────┘  └──────────────┘  └──────┬───────┘  └──────────────┘                │
│                                              │                                          │
│   ┌──────────────────┐                       │   Kafka Broker                           │
│   │  PostgreSQL DB   │                       │   (all workers connect here)             │
│   │  Port: 5432      │                       │                                          │
│   │  (shared across  │                       │                                          │
│   │   all 3 VMs)     │                       │                                          │
│   └──────────────────┘                       │                                          │
└──────────────────────────────────────────────┼──────────────────────────────────────────┘
                                               │
                    ┌───────────────────────────────────────────────────┐
                    │                                                   │
                    ▼                                                   ▼
┌───────────────────────────────────────┐       ┌───────────────────────────────────────┐
│         VM 2 — Agent Workers          │       │         VM 3 — Tool Workers           │
│                                       │       │                                       │
│  ┌────────────┐  ┌────────────┐       │       │  ┌────────────┐  ┌────────────┐       │
│  │  Worker 1  │  │  Worker 2  │       │       │  │  Worker 1  │  │  Worker 2  │       │
│  │  Port: 8102│  │  Port: 8103│       │       │  │  Port: 8101│  │  Port: 8111│       │
│  └────────────┘  └────────────┘       │       │  └────────────┘  └────────────┘       │
│                                       │       │                                       │
│  ┌────────────┐  ┌────────────┐       │       │  ┌────────────┐                       │
│  │  Worker 3  │  │  Worker 4  │       │       │  │  Worker 3  │                       │
│  │  Port: 8104│  │  Port: 8105│       │       │  │  Port: 8121│                       │
│  └────────────┘  └────────────┘       │       │  └────────────┘                       │
│                                       │       │                                       │
│  ┌────────────┐                       │       │  Consumer Group:                      │
│  │  Worker 5  │                       │       │  "tool-executor-workers"              │
│  │  Port: 8106│                       │       │                                       │
│  └────────────┘                       │       └───────────────────────────────────────┘
│                                       │
│  Consumer Group:                      │
│  "agent-executor-workers"             │
│                                       │
└───────────────────────────────────────┘

           All VMs connect to PostgreSQL on VM 1 (Port 5432)
           ┌────────────────────────────────────────────────┐
           │  Shared PostgreSQL Database (hosted on VM 1)   │
           │                                                │
           │  • Task Registry (status tracking)             │
           │  • Chat History                                │
           │  • Agent/Tool configuration                    │
           │  • Token usage logs                            │
           │                                                │
           │  VM 1 (Backend) ──▶ localhost:5432             │
           │  VM 2 (Agent Workers) ──▶ VM1_IP:5432          │
           │  VM 3 (Tool Workers) ──▶ VM1_IP:5432           │
           └────────────────────────────────────────────────┘
```

---

## Request Flow Across VMs

```
 Client / External System
          │
          │  POST /chat/m2m_inference
          ▼
┌──────────────────────┐
│  VM 1 — IAF Backend  │
│                      │
│  1. Registers task   │
│     in shared DB     │
│     (status: queued) │
│                      │
│  2. Publishes to     │─────── iaf_agent_call_requests ──────┐
│     Kafka            │        (Kafka on VM1:9092)           │
│                      │                                      │
│  3. Returns task_id  │                                      │
│     to client        │                                      │
└──────────────────────┘                                      │
                                                              ▼
                                              ┌───────────────────────────┐
                                              │  VM 2 — Agent Worker      │
                                              │  (one of 5 picks it up)   │
                                              │                           │
                                              │  4. Marks task as         │
                                              │     "processing" in DB    │
                                              │                           │
                                              │  5. Runs agent inference  │
                                              │     (calls LiteLLM on     │
                                              │      VM1 for LLM access)  │
                                              │                           │
                                              │  6. Agent needs a tool?   │
                                              │     Publishes to ─────────┼──┐
                                              │     iaf_tool_call_requests│  │
                                              │                           │  │
                                              │  9. Gets tool response    │  │
                                              │     from Kafka            │  │
                                              │     iaf_tool_call_responses  │
                                              │                           │  │
                                              │ 10. Continues inference   │  │
                                              │     (may call more tools) │  │
                                              │                           │  │
                                              │ 11. Marks task as         │  │
                                              │     "completed" in DB     │  │
                                              └───────────────────────────┘  │
                                                                             │
                                                                             ▼
                                              ┌──────────────────────────────────┐
                                              │  VM 3 — Tool Worker              │
                                              │  (one of 3 picks it up)          │
                                              │                                  │
                                              │  7. Executes the tool            │
                                              │     (Python exec or MCP call)    │
                                              │                                  │
                                              │  8. Publishes result to ─────────┼──▶ back to
                                              │     iaf_tool_call_responses      │     Agent Worker
                                              │     (Kafka on VM1:9092)          │     on VM2
                                              └──────────────────────────────────┘


 Client polls:
   GET /chat/task/{task_id}/status  →  VM 1 (reads from shared DB)
   GET /chat/task/{task_id}/result  →  VM 1 (reads from shared DB)
```

---

## Deployment Details

| VM | Components | Instances | Notes |
|---|---|---|---|
| **VM 1** | IAF Backend, Frontend, Kafka Broker, LiteLLM, PostgreSQL | 1 each | Central hub — hosts all shared infrastructure (Kafka, DB, LLM proxy). All traffic from VM 2 and VM 3 routes through this VM. |
| **VM 2** | Agent Worker | 5 instances (ports 8102–8106) | All 5 share the consumer group `agent-executor-workers`. Kafka distributes requests across them automatically. |
| **VM 3** | Tool Worker | 3 instances (ports 8101, 8111, 8121) | All 3 share the consumer group `tool-executor-workers`. Each can execute tool calls independently. |

---

## Shared Resources

The PostgreSQL database runs on **VM 1** and is accessed by all three roles using the same credentials. This is what makes the system work as a cohesive unit:

- **VM 1 (Backend)** connects to PostgreSQL locally (`localhost:5432`) — writes task records to the Task Registry when queuing requests.
- **VM 2 (Agent Workers)** connect remotely to VM 1's PostgreSQL — update task status (`processing` → `completed`/`failed`) and write chat history.
- **VM 3 (Tool Workers)** connect remotely to VM 1's PostgreSQL — read tool definitions and configurations from the database.
- **Client polling** on VM 1 reads the status that VM 2 wrote — no direct communication needed between client and workers.

---

## How Parallel Processing Works

With 5 Agent Workers and 3 Tool Workers:

- Up to **5 agent inference requests** can be processed simultaneously (one per agent worker instance).
- Each agent worker can also handle multiple requests concurrently within its own process.
- Up to **3 tool calls** can execute in parallel across tool workers.
- If an agent invokes multiple tools, those tool calls are distributed across available tool workers.
- Kafka's partition-based load balancing ensures no two workers process the same message.

---

## Network Connectivity Requirements

```
VM 2 (Agent Workers)  ──▶  VM 1:9092   (Kafka broker)
VM 2 (Agent Workers)  ──▶  VM 1:4000   (LiteLLM for LLM calls)
VM 2 (Agent Workers)  ──▶  VM 1:5432   (PostgreSQL)

VM 3 (Tool Workers)   ──▶  VM 1:9092   (Kafka broker)
VM 3 (Tool Workers)   ──▶  VM 1:5432   (PostgreSQL)

VM 1 (Backend)        ──▶  localhost:5432 (PostgreSQL — same machine)
VM 1 (Kafka)          ◀──  VM 2, VM 3    (Workers connect inbound)
VM 1 (PostgreSQL)     ◀──  VM 2, VM 3    (Workers connect inbound)
```

---

## Starting the Services

**VM 1:**
```bash
# Start Kafka broker (system service or manual)
# Start IAF Backend
python run_server.py

# Start LiteLLM proxy
litellm --config litellm_config.yaml --port 4000
```

**VM 2 — Agent Workers (5 instances):**
```bash
python run_agent_worker.py --port 8102
python run_agent_worker.py --port 8103
python run_agent_worker.py --port 8104
python run_agent_worker.py --port 8105
python run_agent_worker.py --port 8106
```

**VM 3 — Tool Workers (3 instances):**
```bash
python tool_worker/main.py --port 8101
python tool_worker/main.py --port 8111
python tool_worker/main.py --port 8121
```

Each worker instance exposes a `/health` endpoint on its respective port for monitoring.
