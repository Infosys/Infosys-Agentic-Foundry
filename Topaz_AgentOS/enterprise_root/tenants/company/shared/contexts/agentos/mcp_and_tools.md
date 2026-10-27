# MCP Connectors + Tools

How skills reach external systems: built-in tools, MCP connectors, and
custom Python tools.

## Built-in tools (no setup required)

| Tool | Purpose |
|---|---|
| `shell` | Run any shell command in the sandboxed kernel |
| `write_file` | Write files to the kernel sandbox (path-traversal guarded) |
| `run_sql_query` | Execute SQL against tenant DBs (sql_mode gate) |
| `query_memory` | Recall from the 3-layer memory |
| `invoke_skill` | Delegate to another skill (depth-capped) |
| `invoke_plan` | Run a sub-plan inside the same agent |
| `create_plan` | Ask the planner for a step DAG |
| `request_human_approval` | Pause the run and queue an HITL gate |

Many tasks (curl, jq, awk, python) collapse into one `shell` because
the LLM is happy to write the command. Skills typically need only 2–3
tools.

## MCP Connectors — for vendor systems

Use MCP when the external system either:

- Has no clean HTTP API (e.g. Workday's SOAP)
- Needs a maintained adapter with auth/rate limits
- Is offered by a vendor as a managed connector

Declare in SKILL.md:

```yaml
mcp_connections:
  - name: servicenow
    transport: stdio
  - name: gmail
    transport: sse
    url: https://mcp.example.com/gmail
```

The harness binds the connector's tools before the LLM wakes. Failed
connectors degrade gracefully (the rest of the skill still runs).

## Custom Python tools (per skill)

```python
# skills/<name>/tools/fetch_invoice.py
TOOL_NAME = "fetch_invoice"
TOOL_DESCRIPTION = "Fetch a single invoice by ID from the AR ledger."

def run(invoice_id: str) -> str:
    """Return JSON. Raise on failure — the host catches it."""
    ...
```

The harness auto-registers the function. Pack authors don't manage
schema/permissions — that's the host's job.

## Shell vs MCP — when to pick what

- Has REST/JSON API → **`shell` + curl**
- Has SOAP / proprietary protocol → **MCP connector**
- Internal database → **`run_sql_query`** (faster, no extra layer)
- One-off complex Python logic → **custom tool**

Read more: agent_os/docs/tools_reference.md · docs/AUTHORING_GUIDE.md
