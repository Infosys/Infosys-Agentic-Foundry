# LLM Request Tracing

## Overview

The LLM Request Tracing feature provides end-to-end visibility into every LLM request made by the platform. It captures request metadata, token usage, latency, and error details — enabling debugging, performance monitoring, and usage analysis across all agent types.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     API Layer                                │
│  M2M / Batch Endpoints → Kafka Message Queue                │
│  • Generates correlation request_id                         │
│  • Sets user_id, session_id in SessionContext               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Kafka Agent Worker                          │
│  • Extracts user_email from Kafka message                   │
│  • Sets full SessionContext (user_id, session_id,           │
│    agent_id, call_category, request_id)                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               LLM Model Layer (TokenLoggingMixin)           │
│  Every LLM call passes through _agenerate():                │
│  • Reads SessionContext for user_id, session_id, request_id │
│  • Logs to llm_request_tracking table                       │
│  • Captures tokens, latency, errors                         │
└─────────────────────────────────────────────────────────────┘
```

---

## What Gets Tracked

Every individual LLM call is recorded in the `llm_request_tracking` table:

| Field | Description |
|-------|-------------|
| `llm_call_id` | Unique ID for this specific LLM call |
| `request_id` | Correlation ID grouping all LLM calls within a single user request |
| `user_id` | User email who triggered the request |
| `session_id` | Session identifier |
| `agent_id` | Agent that made the call |
| `agent_name` | Human-readable agent name |
| `model_name` | LLM model used (e.g., gpt-4o) |
| `request_source` | Code location that triggered the call |
| `input_tokens` | Tokens in the prompt |
| `output_tokens` | Tokens in the response |
| `total_tokens` | Total tokens consumed |
| `duration_ms` | Latency in milliseconds |
| `status` | `success` or `failed` |
| `error_message` | Error details (if failed) |
| `error_type` | Exception class name |
| `stack_trace` | Full traceback (if failed) |
| `request_timestamp` | When the request was sent |
| `response_timestamp` | When the response was received |

---

## How It Works

**Request Correlation**

Every user request generates a unique `request_id` that groups all LLM calls made during that inference:

```
User Request (request_id: req_abc123)
  ├── LLM Call #1: Conversation Summary (llm_call_id: llm_001)
  ├── LLM Call #2: Planner (llm_call_id: llm_002)
  ├── LLM Call #3: Executor (llm_call_id: llm_003)
  └── LLM Call #4: Response Formatter (llm_call_id: llm_004)
```

---

## Dashboard

Access the tracking dashboard at: `/static/llm_tracking_dashboard.html`

**Navigation:** Users → Sessions → Requests → LLM Call Details

The dashboard provides:
- User-level aggregate statistics
- Session-level breakdown
- Per-request LLM call grouping (via `request_id`)
- Detailed view of each LLM call (tokens, duration, errors)

**API Endpoints:**

| Endpoint | Description |
|----------|-------------|
| `GET /llm-tracking/users` | All users with request counts |
| `GET /llm-tracking/users/{user_id}/sessions` | Sessions for a user |
| `GET /llm-tracking/sessions/{session_id}/requests` | Requests grouped by request_id |
| `GET /llm-tracking/requests/{request_id}/llm-calls` | All LLM calls for a request |

---

## Access Control (RBAC)

Access to the LLM Tracker dashboard and its endpoints is governed by the platform's role-based access control:

- Only users with the appropriate role (Admin / SuperAdmin) can open the tracker.
- Results are **filtered by the caller's role and department** — Admins see tracking data for their own department, while SuperAdmin can view data across all departments.
- The RBAC filters applied to the tracking queries ensure users only see LLM request records they are authorized to view.

---

## Configuration

LLM request tracing is always enabled when the platform is running. It requires a PostgreSQL connection (same database used by the platform):

| Environment Variable | Description |
|---------------------|-------------|
| `POSTGRESQL_HOST` | Database host |
| `POSTGRESQL_USER` | Database user |
| `POSTGRESQL_PASSWORD` | Database password |
| `DATABASE` | Database name |

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS llm_request_tracking (
    id SERIAL PRIMARY KEY,
    llm_call_id VARCHAR(255) NOT NULL,
    request_id VARCHAR(255),
    user_id VARCHAR(255),
    session_id VARCHAR(500),
    agent_id VARCHAR(255),
    agent_name VARCHAR(255),
    model_name VARCHAR(255),
    request_source VARCHAR(500),
    request_context TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    request_timestamp TIMESTAMP,
    response_timestamp TIMESTAMP,
    duration_ms FLOAT,
    status VARCHAR(50) DEFAULT 'success',
    error_message TEXT,
    error_type VARCHAR(255),
    stack_trace TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---
