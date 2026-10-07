# Azure Monitoring

## Overview

The Agentic Workflow Framework uses **Azure Application Insights** for centralized logging, tracing, and observability — alternative for the previous Elasticsearch + Grafana + Phoenix stack with a single Microsoft-managed service.

---

## Architecture

**backend_telemetry = elasticsearch (3 backend services):**
```
App → OpenTelemetry SDK → OTel Collector → Elasticsearch → Phoenix UI / Grafana
```

**backend_telemetry=azure:**
```
App → azure-monitor-opentelemetry → Azure Application Insights → Azure Workbooks
```

---

## Setup

**1. Install**

```bash
pip install azure-monitor-opentelemetry>=1.6.4
```

**2. Configure Environment Variables**

| Variable | Description |
|----------|-------------|
| `TELEMETRY_BACKEND` | Set to `azure` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Connection string from Azure Portal → Application Insights → Overview |

**3. How It Works**

In `telemetry_wrapper.py`, when `TELEMETRY_BACKEND=azure`:

```python
from azure.monitor.opentelemetry import configure_azure_monitor

configure_azure_monitor(
    connection_string="InstrumentationKey=...",
    service_name="agentic-workflow-service",
)
```

All existing `trace_operation()`, `create_otel_hooks()`, and `with_logging_span()` functions work identically — only the export destination changes.

---

## Backend Toggle

| `TELEMETRY_BACKEND` | Traces | Logs | Backend Services Needed |
|---------------------|--------|------|------------------------|
| `elasticsearch` | OTel Collector → ES | OTel Collector → ES | Yes (3 services) |
| `azure` | Azure App Insights | Azure App Insights | **No** |

---

## What Gets Captured

**Application Logs (via `telemetry_wrapper.py`)**

All logs include metadata in `customDimensions`: `session_id`, `user_id`, `agent_name`, `agent_id`, `action_type`, `action_on`, `log_level`, `model_used`, `tool_name`, `funcName`, `module`, `request_id`.

---

## Azure Workbook Dashboard

An `Agent Action Dashboard` workbook provides Grafana-equivalent monitoring.

**Parameters / Filters**

Time Range, Session ID, User ID, Agent, Severity, Server — all multi-select dropdowns populated via KQL queries.

**Panels**

| Panel | Visualization | Purpose |
|-------|---------------|---------|
| Filtered Logs | Table | Full log table with all metadata columns |
| Error Count by Agent | Table | Error/warning counts grouped by agent |
| Errors per User | Table | Error/warning counts per user and severity |
| User Error Logs | Table | Detailed error logs for debugging |

---

## Migration Checklist

- [ ] Set `TELEMETRY_BACKEND=azure` in environment
- [ ] Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in environment
- [ ] `pip install azure-monitor-opentelemetry`
- [ ] Verify traces in Azure Portal → App Insights → Transaction Search
- [ ] Create workbook dashboard

---

## Deployment

**Prerequisites**

- Azure Application Insights resource created
- Connection string obtained
- Python package installed

**Rollback**

Change `TELEMETRY_BACKEND=elasticsearch` and restart — reverts to the previous stack immediately.
