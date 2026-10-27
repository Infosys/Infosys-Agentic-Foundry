# Telemetry — sending Topaz AgentOS traces, metrics and logs to your tools

Topaz AgentOS emits **OpenTelemetry (OTel)**, the vendor-neutral standard for traces,
metrics and logs. Anything that accepts OTLP (the OpenTelemetry protocol) can receive
it. That covers Datadog, Splunk, Dynatrace, New Relic, Elastic, Grafana, Azure Monitor,
Langfuse, Arize Phoenix and the OpenTelemetry Collector.

AgentOS always keeps its own trace store, which powers the in-app execution views.
OpenTelemetry export is an optional mirror of that store, **off by default**.

---

## 1. Turn it on

Install the dependencies once. They are pinned in `requirements.txt` and are available
from the Infosys JFrog PyPI mirror:

```bash
pip install -r IAF-Agent-Studio/requirements.txt
```

Then add these lines to `agent_os/config.env` and restart:

```bash
TELEMETRY_EXPORTERS=local,otel
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318      # your collector or vendor
OTEL_SERVICE_NAME=topaz-agentos
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=prod
```

The startup log confirms the setup:

```
Telemetry: OpenTelemetry export ON — service=topaz-agentos endpoint=http://otel-collector:4318 ...
```

Every other setting uses the **standard OpenTelemetry environment variables**, so your
vendor's own setup guide applies unchanged:

| Variable | Purpose | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector/vendor base URL (OTLP over HTTP) | `http://localhost:4318` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Auth headers, e.g. `Authorization=Basic%20...` | none |
| `OTEL_SERVICE_NAME` | Service name shown in your tool | `iaf-agent-studio` |
| `OTEL_RESOURCE_ATTRIBUTES` | Extra labels (environment, region, …) | none |
| `OTEL_TRACES_SAMPLER` / `_ARG` | Sampling, e.g. `parentbased_traceidratio` + `0.2` | keep all |
| `OTEL_METRICS_EXPORTER` | `otlp` or `none` | `otlp` |
| `OTEL_LOGS_EXPORTER` | `otlp` sends application logs too | `none` |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | Include prompt and response text (see §4) | `false` |
| `TELEMETRY_EXPORT_AUDIT` | Security audit events as logs: `off`, `denials` or `all` (see §5) | `off` |

Export happens on background threads with bounded queues. If your collector is slow or
unreachable, telemetry is dropped (and counted in `agentos.telemetry.dropped`); user
requests are never slowed.

---

## 2. What you get

### Traces: one per agent run, nested

```
invoke_agent invoice_processing_ap           ← root: skill, entrypoint, tokens, cost
├─ chat gpt-5.2-chat                          ← routing call (model, tokens)
├─ knowledge context_loading
├─ chat gpt-5.2-chat                          ← the agent's model call …
│  ├─ execute_tool run_sql_query              ← … and the tools it called
│  └─ execute_tool shell
└─ memory episodic_log
   (hook executions appear as events on the root span)
```

- **Same trace ID as the AgentOS UI.** You can copy an ID from the AgentOS execution
  view and search for it in your tool.
- **Workflows and graphs form one trace.** Each step's sub-agent run is nested under the
  parent run, so a whole workstream item is a single tree.
- **Links to the HTTP request.** Each agent run carries a link to the HTTP request
  span that started it.

### Standard attribute names

AgentOS uses the OpenTelemetry **GenAI semantic conventions**:

- `gen_ai.operation.name`: `invoke_agent`, `chat` or `execute_tool`
- `gen_ai.agent.name`
- `gen_ai.request.model`
- `gen_ai.provider.name`
- `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`
- `gen_ai.tool.name` and `gen_ai.tool.call.id`

It also sets the **OpenInference** names that Phoenix and Langfuse read:
`openinference.span.kind` and `llm.token_count.*`.

AgentOS-specific fields are prefixed `agentos.`:

| Attribute | Meaning |
|---|---|
| `agentos.entrypoint` | Where the run came from: `chat_rest`, `chat_ws`, `cron_iteration`/workstream, `queue`, `observer`, `hitl_resume`, `batch` or `subagent` |
| `agentos.skill`, `agentos.tenant` | Skill and tenant |
| `agentos.execution_mode`, `agentos.status` | How the run executed and how it ended |
| `agentos.cost_usd` | Estimated model cost |
| `agentos.trace_id`, `agentos.parent_trace_id` | IDs as stored in AgentOS |

### Metrics

| Metric | Description |
|---|---|
| `gen_ai.client.token.usage` | Tokens per model call, split by `gen_ai.token.type` (input/output) and model |
| `gen_ai.client.operation.duration` | Model call latency |
| `agentos.agent.runs` | Run count by skill, status and entrypoint |
| `agentos.agent.run.duration` | End-to-end run latency |
| `agentos.llm.cost` | Model cost (USD) |
| `agentos.approvals` | Human-approval steps reached |
| `agentos.telemetry.dropped` | Telemetry the exporter could not deliver |
| `http.server.*` | Standard HTTP server metrics |

The built-in Prometheus endpoint `/metrics` remains available for scrapers.

### Logs

With `OTEL_LOGS_EXPORTER=otlp`, application logs are exported. Each log line carries
the trace ID of the request that produced it.

---

## 3. Vendor recipes

### OpenTelemetry Collector (recommended)

Point AgentOS at a Collector and choose destinations in the Collector, so switching
vendors never requires touching AgentOS. Use the `otelcol-contrib` distribution
(tested with v0.162.0). Example `collector.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
processors:
  batch: {}
exporters:
  otlp_grpc/tempo:            # Grafana Tempo
    endpoint: tempo:4317
    tls: { insecure: true }
  otlp_http/phoenix:          # Arize Phoenix
    endpoint: http://phoenix:6006
  azure_monitor:              # Azure Monitor / Application Insights
    connection_string: ${env:APPLICATIONINSIGHTS_CONNECTION_STRING}
  datadog:
    api: { key: ${env:DD_API_KEY}, site: datadoghq.eu }
  splunk_hec:
    token: ${env:SPLUNK_HEC_TOKEN}
    endpoint: https://splunk.example.com:8088/services/collector
  prometheus:                 # scrape target for Prometheus/Grafana
    endpoint: 0.0.0.0:8889
service:
  pipelines:
    traces:  { receivers: [otlp], processors: [batch], exporters: [otlp_grpc/tempo, otlp_http/phoenix] }
    metrics: { receivers: [otlp], processors: [batch], exporters: [prometheus] }
    logs:    { receivers: [otlp], processors: [batch], exporters: [splunk_hec] }
```

List only the exporters you use. Exporter names follow Collector v0.162; older
releases used `otlp`/`otlphttp`/`azuremonitor`.

### Arize Phoenix

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix-host:6006
OTEL_METRICS_EXPORTER=none        # Phoenix accepts traces only
```

### Langfuse

Langfuse accepts OTLP over HTTP at `/api/public/otel`. Authentication is HTTP Basic,
using your public key and secret key encoded as `base64("pk-lf-...:sk-lf-...")`.

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel   # or your self-hosted URL
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64(pk:sk)>
OTEL_METRICS_EXPORTER=none
```

### Grafana (Tempo + Prometheus)

Send traces to Tempo, either directly (Tempo's OTLP receiver) or through the
Collector. Add Tempo as a Grafana data source, then search by AgentOS trace ID. For
metrics, have Prometheus scrape the Collector's `prometheus` exporter or AgentOS's own
`/metrics`.

### Azure Monitor / Application Insights

Use the Collector's `azure_monitor` exporter with your Application Insights connection
string, as in the Collector example above.

### Datadog, Splunk, Dynatrace, New Relic, Elastic, Honeycomb

Each has either an OTLP endpoint or a Collector exporter. Set
`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` as the vendor documents,
or add the vendor's exporter to the Collector.

---

## 4. Privacy

By default, **no prompt or response text leaves the platform**. Spans carry:

- timings
- model names and token counts
- cost
- skill, tool names and outcome

To include text previews, set
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`. Previews are then:

- length-capped (`TELEMETRY_PREVIEW_LIMIT`, default 512 characters)
- passed through the platform's redaction, which removes passwords, tokens, API keys
  and authorization values

Model reasoning is **never** exported.

---

## 5. Security audit events (SIEM)

Every permission decision and every external-access decision is written to the local
audit files. With `TELEMETRY_EXPORT_AUDIT` set, those decisions are also sent as
OpenTelemetry **log records**:

- `denials` (recommended): only refused actions, at WARN severity.
- `all`: every decision. This is high volume, because every permission check is
  audited.

Each record carries:

- `agentos.audit.category`: `entitlement_decision` or `external_access`
- `agentos.audit.tenant_id`, `.user_id`, `.email`
- `agentos.audit.action`, `.resource`, `.allowed`, `.reason`, `.matched_policy`

Route the logs pipeline to your SIEM (Splunk HEC, Microsoft Sentinel via Azure Monitor,
Elastic, …).

---

## 6. Verifying a deployment

1. Startup log: `Telemetry: OpenTelemetry export ON …`.
2. Run one chat. Copy its trace ID from the AgentOS UI (or `/api/traces`), then find it
   in your tool.
3. Check `agentos.telemetry.dropped` stays at zero.

The repository's own checks:

- `IAF-Agent-Studio/tests/test_otel_bridge.py`
- `tests/test_audit_otel_export.py`
- `tests/run_telemetry_provider_e2e.py`, which decodes real OTLP traffic with the
  official protocol definitions

To turn export off, set `TELEMETRY_EXPORTERS=local` (or remove it) and restart.
