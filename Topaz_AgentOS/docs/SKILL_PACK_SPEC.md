# Skill Pack Spec — Portable Agent Packages

**Version:** 1.0
**Status:** Draft
**Schema:** [schemas/skillpack.schema.json](schemas/skillpack.schema.json)

A **Skill Pack** is a single folder containing everything needed to deploy
one agent (or one family of cooperating agents) on any compatible harness:
IAF AgentOS, Claude Cowork, Claude Code, Anthropic Managed Agents, or a
custom Python loop.

> *Author once. Run anywhere a harness supports the spec.*

---

## 1. Why this spec exists

The agentic ecosystem has converged on roughly the same primitives —
system prompts, tool whitelists, sub-agent delegation, lifecycle hooks,
HITL — but every harness stores them in a different file layout. Today,
moving an agent from one platform to another means rewriting the
plumbing.

A Skill Pack is a vendor-neutral container. The harness reads the
manifest, plugs the pieces into its own runtime, and runs the agent.

---

## 2. Folder layout

```
my-skill-pack/                          ← one folder = one deployable
│
├── manifest.yaml                       ← portable header (required)
├── SKILL.md                            ← agent definition (required)
│
├── contexts/                           ← reusable Markdown (optional)
│   ├── policy.md
│   ├── playbook.md
│   └── glossary.md
│
├── hooks/                              ← lifecycle hooks (optional)
│   ├── pre_tool.py
│   ├── post_step.py
│   └── on_failure.py
│
├── tools/                              ← custom Python tools (optional)
│   ├── __init__.py
│   └── my_tool.py
│
├── viewers/                            ← HTML viewers (optional)
│   ├── result_card.html
│   └── standalone.html
│
├── fixtures/                           ← demo seed data (optional)
│   ├── seed.csv
│   └── mock_responses.yaml
│
├── tests/                              ← portable smoke tests (optional)
│   └── smoke.yaml
│
└── README.md                           ← walkthrough + screenshots
```

### 2.1 Required files

Only **three** items are mandatory:

1. `manifest.yaml` — the portable header (this spec)
2. `SKILL.md` — agent persona + instructions + frontmatter (see
   [schemas/skill.schema.json](schemas/skill.schema.json))
3. Either `contexts/`, `tools/`, or both — at least one source of
   knowledge or capability beyond the prompt body

Everything else is opt-in capability. Hosts that don't support a
capability MUST politely degrade rather than reject the pack outright,
unless the manifest declares the capability as required (see
[§3 `requires:`](#3-the-manifest)).

---

## 3. The manifest

`manifest.yaml` is the portability layer. It declares **what the pack
expects** so the host can decide whether to install, refuse, or shim.

### 3.1 Minimum viable manifest

```yaml
spec_version: "1.0"
name: month_end_closer
version: "1.0.0"
description: "Close the books for a fiscal month — reconcile, flag variances, draft entries."
agent_type: orchestrator
requires:
  tools: [shell, run_sql_query]
```

That's it. With that file plus a `SKILL.md`, the pack will install on
IAF AgentOS today.

### 3.2 Full manifest example

```yaml
spec_version: "1.0"

# Identity
name: month_end_closer
version: "1.0.0"
description: >-
  Close the books for a fiscal month — reconcile bank-to-GL, flag
  variances above threshold, draft journal entries, and route to
  controller approval for items above $100k.
authors: ["finance-platform@example.com"]
licence: "Apache-2.0"
homepage: "https://example.com/agents/month-end"
tags: [finance, close, reconciliation, HITL]

# Execution
agent_type: orchestrator                # react | workflow | parallel | supervisor | orchestrator | planned

# Model preference (host resolves provider+tier to a concrete model)
recommended_model:
  primary:   { provider: any, tier: frontier }
  light:     { provider: any, tier: fast }
  fallback:  { provider: any, tier: any }

# What the host must provide
requires:
  tools:        [shell, run_sql_query, write_file, request_human_approval]
  storage:      [sqlite]
  hooks:        [pre_step, post_step]
  ui:           optional
  network:      [outbound_http]
  mcp_servers:  [servicenow]            # optional — degrades if missing
  min_harness_version: "0.9.0"

# Sub-agents this pack invokes (skill packs themselves)
callable_agents:
  - doc_summarizer  >= 1.0
  - approval_router >= 1.0

# Inputs the deployer sets at install time
inputs:
  - name: ledger_db_url
    type: secret
    required: true
    description: "Connection string for the GL database."
  - name: variance_threshold_usd
    type: number
    default: 10000

# Structured outputs the pack produces
outputs:
  - name: close_report
    type: file
    format: pdf
    description: "Signed off close report PDF, suitable for audit."
  - name: variance_findings
    type: json
    description: "Machine-readable findings for downstream chaining."

# UI viewers
viewers:
  - name: result_card
    file: viewers/result_card.html
    mode: inline
    renders_output: close_report

# Portable smoke tests
tests:
  - name: happy_path
    input: "Close April 2026"
    expects: ["close_report", "variance_findings"]
    rejects: ["Error", "Traceback"]
    max_latency_ms: 60000

# Per-host hints (used by host shims; ignored by hosts that don't need them)
compatibility:
  iaf_agentos:
    register_in_index: true
  claude_cowork:
    plugin_category: "finance"
```

### 3.3 Field reference

Every field is documented in the JSON Schema at
[schemas/skillpack.schema.json](schemas/skillpack.schema.json). Authors
get autocomplete and validation in VS Code by adding to the top of
`manifest.yaml`:

```yaml
# yaml-language-server: $schema=https://iaf-agentos.local/schemas/skillpack.schema.json
```

---

## 4. The SKILL.md body

`SKILL.md` is the canonical agent definition (frontmatter + persona +
instructions). Its frontmatter schema is at
[schemas/skill.schema.json](schemas/skill.schema.json) and the starter
templates per execution mode live at
[skill_templates/](skill_templates/).

The `agent_type` in `manifest.yaml` MUST match `execution_mode` in
SKILL.md frontmatter. Hosts MAY warn or refuse on mismatch.

---

## 5. Hooks — lifecycle handlers

A file under `hooks/` is a Python module exporting a function whose
filename matches the hook point declared in `requires.hooks`:

```python
# hooks/pre_step.py
def hook(ctx: dict) -> dict:
    """
    Fires before each orchestrator/workflow step.
    Return {"allow": False, "reason": "..."} to block the step.
    Return {"allow": True}  or {} to permit.
    """
    if ctx["step"]["skill"] == "danger_skill":
        return {"allow": False, "reason": "Forbidden in this pack."}
    return {"allow": True}
```

**Standard hook points** (host MUST support if it advertises the hook
capability):

| Point | When it fires | Can block? |
|---|---|---|
| `pre_tool` | Before every tool invocation | Yes |
| `post_tool` | After every tool invocation | No (post-mortem only) |
| `pre_step` | Before each orchestrator/workflow step | Yes |
| `post_step` | After each step | No |
| `pre_turn` | Before each LLM call | Yes |
| `post_turn` | After each LLM call | No |
| `on_failure` | When a tool/step throws or times out | Compensation only |

### 5.1 Sync vs async

A hook is **sync** by default. If the function name ends with `_async`
or returns an awaitable, the host MUST await it. `post_tool` and
`post_step` are typically async (audit writes); `pre_*` are sync (must
gate before proceeding).

---

## 6. Custom tools — Python entry points

```python
# tools/my_tool.py
TOOL_NAME = "fetch_invoice"
TOOL_DESCRIPTION = "Fetch a single invoice by ID from the AR ledger."

def run(invoice_id: str) -> str:
    """Return a JSON string. Raise on failure — host catches and feeds to LLM."""
    ...
```

The host registers the function under the declared `TOOL_NAME`, exposes
the docstring to the LLM, and routes calls through whatever sandbox /
entitlement layer it provides.

Pack authors MUST NOT assume any particular sandbox. Treat all I/O as
gated.

---

## 7. Viewers — embeddable HTML

A viewer is a self-contained HTML file the host MAY render to show
results to the user. Two modes:

- **inline** — rendered inside the host chat UI as a card. Communicates
  with the host via `window.postMessage({type:"skillpack:request", ...})`.
- **standalone** — opens in a new tab/window with the pack's output URL.

Inline viewer message contract:

```js
// From viewer → host
parent.postMessage({type: "skillpack:ready", viewer: "result_card"}, "*");
parent.postMessage({type: "skillpack:request", op: "fetch", key: "close_report"}, "*");

// From host → viewer (in response)
{type: "skillpack:result", key: "close_report", value: "<base64-or-url>"}
```

Hosts that don't render HTML simply ignore viewers (the pack still
runs).

---

## 8. Fixtures and tests

`fixtures/` is seed data the pack ships with for demos. Common shapes:
CSV (loaded into the host's SQL store), YAML (loaded into the host's
mock API), JSON (general-purpose state).

`tests/smoke.yaml` is the portable equivalent of a smoke test. Each
test names an input, expected substrings, and rejected substrings.
A host's CI MAY run these as install-time validation.

---

## 9. How hosts adapt packs

| Host | What it does at install |
|---|---|
| **IAF AgentOS** | Drops folder into `enterprise_root/tenants/<t>/skills/<name>/`, reads SKILL.md frontmatter directly, optionally consults `manifest.yaml` for inputs/outputs/viewers. Adds entry to `_index.yaml`. |
| **Claude Cowork** | Shim reads `manifest.yaml` → generates Cowork `plugin.json`. SKILL.md body → system prompt. `contexts/*.md` → bundled resources. `viewers/*.html` → Cowork side-panel. |
| **Claude Code** | Manifest → `.claude/plugins/<name>/`. SKILL.md → command + system prompt. Hooks → Claude Code hooks JSON. |
| **Anthropic Managed Agents** | Manifest → cookbook YAML. SKILL.md body → agent prompt. `callable_agents:` → Managed Agent sub-agents. |
| **Custom Python loop** | Library reads the manifest, validates `requires:` against host capabilities, dispatches. |

A reference shim per host lives in `samples/host_shims/<host>/` once the
spec ships.

---

## 10. Versioning

Packs declare their own `version` (semver). Hosts MUST refuse to install
a pack whose `spec_version` they don't recognize.

Breaking changes to this spec increment the major version. Additive
changes increment the minor.

---

## 11. Security guarantees the host MUST provide

A pack assumes (and the host MUST provide):

1. **Sandbox** for shell/code execution — no direct host FS access.
2. **Path safety** — `write_file` cannot escape the pack's allotted dir.
3. **Credential vault** — secrets named in `inputs[].type == secret` are
   never embedded in prompts or logs.
4. **Entitlement enforcement** — declared `requires.network`,
   `requires.storage`, `requires.tools` are the *upper bound* of what
   the pack may use; the host MAY further restrict per-tenant policy.
5. **Audit log** — every tool call, step, and approval is recorded with
   `trace_id` + `pack name@version`.

If a host can't provide any of the above, it MUST flag the pack as
"untrusted mode" before running, so the deployer is aware.

---

## 12. What a pack MUST NOT assume

- Specific filesystem layout outside its own folder
- A specific LLM provider — use `recommended_model.tier` not exact IDs
- That hooks fire synchronously in any particular thread
- That `mcp_servers` listed in `requires` will be available — degrade
  gracefully if missing
- That viewers will be rendered — pack must work headless

---

## 13. Reference implementations (post-1.0)

Living locations after the spec ships:

- `samples/skillpacks/<name>/` — reference packs maintained by the IAF team
- `samples/host_shims/<host>/` — adapter code for each host
- `docs/skillpack_validator.py` — CLI: `python validator.py path/to/pack`

---

## 14. FAQ

**Q: What's the difference between a Skill Pack and a SKILL.md?**
A SKILL.md is one agent definition. A Skill Pack is a deployable folder
that bundles a SKILL.md with the surrounding context, hooks, tools,
viewers, and a manifest that tells hosts how to install it.

**Q: Do I need both `manifest.yaml` and SKILL.md frontmatter?**
Yes. SKILL.md frontmatter is consumed by the agent runtime (loaded into
the prompt assembly). `manifest.yaml` is consumed by the host installer
(read once at install time). They overlap intentionally — the manifest
is the source of truth for the host, frontmatter is the source of truth
for the LLM.

**Q: Can a pack contain multiple skills?**
A pack contains **one primary SKILL.md** at the root. If you need
multiple agents that work together, ship them as separate packs and
declare the relationship via `callable_agents:`. This keeps the unit of
versioning, installation, and trust well-defined.

**Q: What about MCP servers?**
A pack MAY require MCP servers (`requires.mcp_servers:`). It MUST NOT
bundle an MCP server — those are environmental concerns the host
manages. If a required MCP server is missing, the host SHOULD refuse
to install.

---

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | (TBD) | Initial spec |
