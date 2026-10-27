# IAF Hook System — Design Document

**Status:** Approved for implementation (Phase 1)  
**Last updated:** 2026-06-01
**Related files:** `iaf_agent_skills/hook_runner.py` (new), `iaf_agent_skills/agent.py`, `iaf_agent_skills/trace_callback.py`

---

## Why This Exists

`agent.py run()` is a monolith that mixes two concerns:

```
CORE (must stay in agent.py)        SIDE EFFECTS (can move to hooks)
────────────────────────────        ────────────────────────────────
Context loading                     Episodic memory logging
Prompt assembly                     Implicit feedback extraction
Compaction check                    Plan cache write
Rate limit retry                    Trace span emission
HITL stream gate                    Audit logging
Parse result messages               Tool learning (append_learning)
                                    External notifications
                                    Compliance policy checks
```

The hook system gives side effects a proper home. Phase 1 builds the infrastructure
for external customer hooks. Phase 2 migrates internal side effects into the same
system, shrinking agent.py significantly.

When `DYNAMIC_ORCHESTRATOR_ENABLED=false`, router-selected multi-step turns fall
back to the normal ReAct lifecycle. ReAct hooks continue to run normally; the
flag does not disable hook governance or Planned mode.

`DefaultHookProvider` now owns HookRunner construction for `SkillAgent`. The
default provider preserves platform hook merge, kernel attachment, background
runner registration, and model-call policy hook registration. Partner deployments
can select a custom hook provider with `HOOK_PROVIDER=module:Class` when they
need a different policy engine.

The `HookProvider` Protocol itself is exported by the dependency-free
`agentos-contracts` SDK. The historical
`iaf_agent_skills.providers.hook_provider.HookProvider` path remains a
compatibility shim for existing code.

---

## Comparison: Claude Code Hooks vs IAF HITL Gate

Claude Code has 25+ lifecycle events where users configure shell commands in settings.json.
Most of those events are for its terminal UI (spinner, key events, screen rendering) —
not relevant to IAF.

IAF already has a PreToolUse equivalent: `_is_dangerous_call()` + `_run_with_stream_intercept()`
in agent.py. This is a pattern-matching GATE that pauses for human approval.

```
Claude Code hooks:                IAF HITL gate (existing):
─────────────────                 ────────────────────────
Tool call detected                Tool call detected in stream
        ↓                                   ↓
Run external shell script         Match against regex patterns
(user-defined, does anything)     (config.yaml hitl: section)
        ↓                                   ↓
Exit 0 → allow                    Match → show approval dialog
Exit 1 → block                    No match → allow through
        ↓                                   ↓
Tool executes                     Human clicks approve/reject
```

Key difference: Claude Code hooks run external scripts (audit, notify, call APIs).
IAF HITL is a human decision gate. Both are PreToolUse — the hook system unifies them.

---

## Lifecycle Events

The original tool/turn surface has two synchronous gate points and two async
audit points. The same runner now also carries step, model-call, approval-resume,
schedule, background-task, mission, research, and queue execution events.

```
Turn starts
    │
    ▼
[PreTurn — NOT implemented, see note below]
    │
    ▼
LLM called → starts tool loop
    │
    ├──► LLM picks a tool
    │         │
    │         ▼
    │    [PreToolUse]  ◄── SYNCHRONOUS — can block execution
    │         │
    │         ▼
    │    Tool executes
    │         │
    │         ▼
    │    [PostToolUse] ◄── ASYNC fire-and-forget
    │         │
    │         ▼
    │    Result back to LLM
    │         │
    └── (loop until no more tools)
    │
    ▼
LLM produces final text response
    │
    ▼
[PostTurn]   ◄── SYNCHRONOUS — can validate/block response before user sees it
    │
    ▼
Response sent to user
    │
    ▼
[PostSampling] ◄── ASYNC fire-and-forget (same bg thread as episodic log)
```

### Why NOT PreTurn (before agent.run())?

Before `agent.run()` is called:
- **Routing** runs in `chat.py` — a different architectural layer. Hooks there would
  be chat-layer hooks, not agent hooks. Not in scope.
- **Context loading and prompt assembly** — these are CORE orchestration. The LLM call
  depends on their exact output. Allowing external hooks to modify the assembled prompt
  would be unpredictable in an enterprise system.
- **query_memory** — this IS a tool call. PreToolUse already covers it.

### Why PostTurn IS needed

PostTurn fires synchronously after `agent.run()` returns but BEFORE the HTTP response
goes to the user. Unlike PostSampling (async logging), PostTurn can:
- Validate that the response doesn't contain sensitive data patterns
- Add mandatory compliance disclaimers
- Block a response that violates output policy
- Raise a HITL checkpoint when a blocking hook is configured with
  `on_block: hitl`

This is the enterprise response compliance gate. PostSampling cannot do this because
it is async and the response is already sent by the time it runs.

**PostTurn is Phase 1 scope.** PostSampling remains async for logging/notification.

---

## Event Families

| Family | Events | Can Block | Fires When |
|-------|--------|-----------|------------|
| Tool/turn | `PreToolUse`, `PostToolUse`, `PostTurn`, `PostSampling` | `PreToolUse`, `PostTurn` | Tool execution and final response boundaries |
| Turn/model/schedule | `BeforeTurn`, `OnTurnEnd`, `OnError`, `BeforeModelCall`, `AroundModelCall`, `AfterModelCall`, `BeforeScheduleFire`, `AfterScheduleFire`, `OnScheduleError` | Caller-controlled for `Before*`; observe-only by default; `AroundModelCall` is in-process only | Agent turn, model call, and cron lifecycle boundaries |
| Approval resume | `OnApprovalResolved`, `BeforeApprovalResume`, `AfterApprovalResume` | `BeforeApprovalResume` | HITL decision and checkpoint resume flow |
| Background/mission/research | Background task, mission, and research orchestration events | Mixed by caller | Non-tool side effects and long-running workstreams |
| Queue execution | `BeforeQueueItemStart`, `AfterQueueItemComplete`, `OnQueueItemError`, `BeforeQueueRetry`, `OnQueueDLQ`, `OnQueueHITLPending` | No in Phase 1 | Skill-scoped queue execution lifecycle after a `SkillAgent` is resolved |

For workflow-mode HITL resumes, the checkpoint includes completed step outputs as
well as remaining steps. After approval, later workflow steps can still resolve
`{{step_name.output}}` references produced before the pause.

Queue received/routed notifications are deliberately not HookRunner events. The
queue processor writes those pre-skill records to a structured audit sink so it
does not create a second hook ownership path before a per-item `SkillAgent`
exists.

When `RL_CAPTURE=true`, hook audit outcomes with a trace ID are also emitted
through `iaf_agent_skills.capture_events` and projected into the independent
RL/eval store as raw `hook` reward events. HookRunner never imports RL schema
types directly; the bridge suppresses capture failures so hooks keep their
existing allow/block/HITL behavior.

---

## Model-Call Policy Pipeline

`MODEL_CALL_PIPELINE_ENABLED=false` keeps model calls on the legacy path. When
enabled, `SkillAgent` wraps the primary chat model with `PolicyChatModel`, and
every provider `invoke()` inside LangGraph or native ReAct passes through
`iaf_agent_skills/model_call_pipeline.py`.

The pipeline is phase-ordered:

1. `BeforeModelCall` in-process mutators run by priority.
2. `AroundModelCall` in-process wrappers compose around the provider call; lower
   priority is outermost.
3. The provider call runs unless a hook returns a cached response.
4. `AfterModelCall` in-process mutators run before ReAct parses tool calls.

When `RL_CAPTURE=true`, each completed or blocked pipeline invocation is also
mirrored best-effort into the framework-neutral RL/eval capture store as a
`ModelCall` row. Hook audit entries that redact, block, short-circuit, or allow a
model call are mapped to raw `model_call_policy` reward events for export-time
shaping.

The first implementation keeps model-call mutation on in-process hooks only.
External shell hooks still observe through the existing coarse
`run_before_model_call()` and `run_after_model_call()` lifecycle methods, but
external hot-path mutation is not enabled until payload limits and latency
budgets are proven.

`model_call_policy_hooks.py` bridges active central policies from
`security/policy_control.yaml` into in-process `AfterModelCall` hooks. Policies
with `event: AfterModelCall` and `decision: redact` can mutate
`response_content` before the answer is returned. The initial real policy is
`model_response_sensitive_data_redaction` for `enterprise_agent`, which redacts
email, SSN, card, token, API key, secret, and password-looking values from model
responses.

---

## New File: `iaf_agent_skills/hook_runner.py`

### Data Classes

```python
@dataclass
class ExternalHook:
    event:            str           # "PreToolUse"|"PostToolUse"|"PostTurn"|"PostSampling"
    matcher:          str           # regex matched against tool_name
    command:          str           # shell command to execute
    block_on_nonzero: bool = False  # PreToolUse/PostTurn only
    on_block: str = "deny"          # "deny" | "hitl"
    approval: dict = field(default_factory=dict)
    fail_policy: str = "open"       # "open" | "closed" — see fail_policy semantics
    timeout_seconds:  int  = 10     # subprocess timeout
    # On timeout: fail_policy governs — "open" (default) logs + continues,
    #             "closed" denies the operation (blocked=True)
    # On exit 0:  pass through
    # On exit 1+: block if block_on_nonzero=True; otherwise fail_policy governs
    #             ("open" continues, "closed" denies)

@dataclass
class InternalHook:
    event:     str           # same event names
    matcher:   str           # regex or ".*" for all
    handler:   callable      # Python function — receives ctx dict
    can_block: bool = False  # if True, handler may return HookResult(blocked=True)
    mutates:   list[str] = field(default_factory=list)
    can_short_circuit: bool = False
    lock_fields: list[str] = field(default_factory=list)
    hot_path: bool = False
    external_mutation_allowed: bool = False
    # can_block=True used in Phase 2 for HITL migration

@dataclass
class HookResult:
    blocked: bool
    reason:  str = ""
    # blocked=True only meaningful for PreToolUse and PostTurn
    # PostToolUse and PostSampling results are ignored
    on_block: str = "deny"          # copied from ExternalHook
    approval: dict = field(default_factory=dict)
```

`on_block` controls what callers do with a blocking hook:

- `deny` blocks the turn/tool without creating an approval. This is the safe
  default for `PostTurn`, `BeforeTurn`, and other gateable events.
- `hitl` converts the block into `agent.approval_pending` when the execution
  surface can pause and persist a checkpoint. `PreToolUse` keeps `hitl` as its
  default for backward compatibility with existing tool-approval behavior.

`approval` is optional metadata used only with `on_block: hitl`. Supported
fields are `urgency`, `options`, `sla_minutes`, `reason_from`, `rule_type`,
`resume_kind`, and `context`.

### HookRunner Methods

```
__init__(hooks_config: dict, agent_root: str)
    Parse config.yaml hooks: section into ExternalHook list
    Compile all matchers as re.compile() once at startup
    Internal hook list starts empty
    If hooks_config absent → all methods are no-ops (zero overhead)

register_internal(event, handler, matcher=".*", can_block=False)
    Append InternalHook to internal list
    Called from agent.py __init__ after HookRunner is built
    This is the Phase 2 migration path
    Model-call hooks may also declare mutates/can_short_circuit/lock_fields metadata

_match(hook, tool_name) -> bool
    re.search(hook.matcher, tool_name, re.IGNORECASE)
    For PostTurn/PostSampling: always True (no tool_name)

_build_env(event, tool_name, tool_input, tool_output, session_ctx) -> dict
    Copy of os.environ + IAF_* vars (see Environment Variables section)

_run_external(hook, env) -> HookResult
    subprocess.run(hook.command, shell=True, env=env,
                   capture_output=True, text=True, timeout=hook.timeout_seconds)
    On TimeoutExpired: log warning, then apply fail_policy — "open" returns
                       HookResult(blocked=False); "closed" returns blocked=True
    On exit != 0 and block_on_nonzero: parse stdout as JSON for structured reason
    On exception: log warning, then apply fail_policy ("open" → blocked=False,
                  "closed" → blocked=True)

_parse_hook_output(stdout, stderr) -> str
    Try json.loads(stdout) → look for "reason" or "message" key
    Fallback to stderr then stdout as plain string
    Max 500 chars

_run_internal(hook, ctx) -> HookResult
    Call hook.handler(ctx) wrapped in try/except
    If can_block and result is HookResult: return it
    On exception: log warning, return HookResult(blocked=False)

iter_model_call_hooks(event, skill_name="") -> list[InternalHook]
    Returns ordered in-process hooks for BeforeModelCall/AroundModelCall/AfterModelCall
    Used only by the opt-in model-call policy pipeline

run_model_call_hook(hook, ctx)
    Calls an in-process model-call hook and returns its raw typed mutation/result

run_pre_tool(tool_name, tool_input, session_ctx) -> HookResult
    All PreToolUse hooks where matcher matches tool_name
    Order: internal first, then external (config.yaml order)
    Short-circuit: first hook that returns blocked=True stops remaining hooks
    Synchronous — agent waits for result

run_post_tool(tool_name, tool_input, tool_output, session_ctx)
    All PostToolUse hooks where matcher matches tool_name
    Each runs in daemon thread — agent never waits
    Called from trace_callback.on_tool_end() AND on_tool_error()

run_post_turn_result(response, session_ctx) -> HookResult
    All PostTurn hooks (no matcher — fires for every turn)
    Synchronous — returns block reason and the potentially modified response
    External hook: exit 0 = pass through, exit 1 = block
    External hook stdout = replacement response if non-empty and exit 0
    If blocked, returns on_block/approval metadata so agent.run() can deny or HITL

run_post_turn(response, session_ctx) -> str
    Backward-compatible wrapper around run_post_turn_result()
    Callers that do not inspect HookResult receive the compliance error string on block
    Internal hook with can_block=True can return modified response

run_post_sampling(session_ctx, external_only=False)
    external_only=True during Phase 1 transition (avoids double-firing)
    external_only=False in Phase 2 after inline code is deleted
    All runs in daemon threads — fire-and-forget
```

---

## Environment Variables Passed to External Commands

```
IAF_HOOK_EVENT    = "PreToolUse" | "PostToolUse" | "PostTurn" | "PostSampling"
IAF_TOOL_NAME     = "run_sql_query"           (empty for PostTurn/PostSampling)
IAF_TOOL_INPUT    = '{"database": "...", "query": "..."}' (JSON string)
IAF_TOOL_OUTPUT   = "..."                     (PostToolUse only)
IAF_RESPONSE      = "..."                     (PostTurn/PostSampling only, first 4096 chars)
IAF_RESPONSE_PREVIEW = "..."                  (bounded response preview)
IAF_QUERY        = "..."                      (turn query/prompt when available)
IAF_TASK         = "..."                      (task/query alias for hook scripts)
IAF_WORKSTREAM_NAME = "..."                   (Mission Mode attribution, if present)
IAF_MISSION_ITEM_ID = "..."                   (Mission Mode attribution, if present)
IAF_SESSION_ID    = "abc123-..."
IAF_AGENT_ID      = "gbs_agent_fa"
IAF_TENANT_ID     = "company"
IAF_SKILL_NAME    = "invoice_processing_ap"
IAF_USER_ID       = "demo"
IAF_AGENT_ROOT    = "/path/to/enterprise_root/tenants/company/agents/gbs_agent_fa"
IAF_ENTRYPOINT    = "chat" | "queue" | "cron" | ...
IAF_QUEUE_ITEM_ID = "CC-..."                  (queue execution only)
IAF_QUEUE_EXEC_ID = "uuid"                    (queue execution only)
IAF_QUEUE_STATUS  = "running|done|failed|dlq|awaiting_human"
IAF_QUEUE_RETRY_COUNT = "0"
IAF_QUEUE_WILL_DLQ = "true|false"
IAF_QUEUE_PRIORITY = "P1|P2|P3"
IAF_QUEUE_EVIDENCE_COUNT = "0"
IAF_ERROR_TYPE    = "TimeoutError|RuntimeError|..."
# TODO Phase 2: IAF_CONVERSATION_ID for cross-turn audit correlation
```

### Structured Output from Hook Scripts (JSON stdout)

Hook scripts can return structured reasons by writing JSON to stdout:

```json
{"blocked": true, "reason": "Violates SOX §302 — DELETE not permitted on production data"}
{"blocked": false, "message": "Audit logged: ref=AUD-2026-001"}
```

If stdout is not valid JSON, plain text is used as the reason string.

---

## Config Design (per agent config.yaml)

```yaml
# enterprise_root/tenants/company/agents/<agent_name>/config.yaml

hooks:
  PreToolUse:
    - matcher: "run_sql_query"
      command: "python3 /hooks/audit_sql.py"
      block_on_nonzero: true      # exit 1 = block, show approval dialog
      timeout_seconds: 10         # default if omitted

    - matcher: "shell"
      command: "bash /hooks/policy_check.sh"
      block_on_nonzero: true

    - matcher: ".*"               # ALL tools
      command: "curl -X POST https://audit.company.com/pretool"
      block_on_nonzero: false     # log only, never block

  PostToolUse:
    - matcher: ".*"
      command: "python3 /hooks/splunk_log.py"
      # block_on_nonzero not relevant — PostToolUse never blocks

  PostTurn:
    - command: "python3 /hooks/response_compliance.py"
      block_on_nonzero: true
      on_block: deny             # exit 1 = compliance denial only

    - command: "python3 /hooks/business_approval.py"
      block_on_nonzero: true
      on_block: hitl             # exit 1 = create approval_pending
      approval:
        urgency: high
        options: [Approve, Reject]
        sla_minutes: 60
        reason_from: hook_output

  PostSampling:
    - command: "python3 /hooks/notify_slack.py"
```

Config rules:
- `hooks:` section absent → HookRunner is a complete no-op, zero overhead
- Per-agent config — `gbs_agent_fa` can have strict SQL hooks, `enterprise_agent` none
- `matcher` uses `re.search()` (case-insensitive) against tool name
- `block_on_nonzero` only meaningful for PreToolUse and PostTurn
- `on_block` is `deny | hitl`; `PreToolUse` defaults to `hitl`, later turn
  gates default to `deny` unless configured
- PostToolUse and PostSampling are always fire-and-forget regardless of flag
- Hooks fire in config.yaml declaration order
- First PreToolUse hook that blocks short-circuits — remaining hooks don't run

### Authoring from the UI

This `hooks:` section can be authored from the Security Console's **Hooks** panel (admin-only) instead of hand-editing YAML — see `IAF-Agent-Studio/static/skill-builder-v2.html` (`currentPage==='hooks'`) backed by `IAF-Agent-Studio/routers/agents.py` (`GET/PUT /api/agents/{id}/config/hooks`, `POST .../config/hooks/validate`):

- **Validation:** `IAF-Agent-Studio/shared/hooks_validation.py::validate_hooks_doc` mirrors `hook_runner._validate_external_manifest`'s field rules but returns per-entry messages (the parser itself only logs + drops bad entries). Keep the two in sync if the accepted field set changes.
- **Safe write:** `PUT` does a locked read-merge-write (`shared/file_utils.locked_rmw_yaml`) that replaces **only** the `hooks:` key — every other section (`context`/`sufficiency`/`hitl`/...) is preserved. An empty doc removes the `hooks:` key entirely.
- **Reload without restart:** after writing, the handler evicts the cached agent + kernel (`state.agents` / `state.kernels` keys containing `:{agent_id}:`), so the next chat/cron run rebuilds the agent and re-reads config. (Direct on-disk edits are still NOT auto-reloaded.)
- **Audit:** each save writes an `agent_config_change` audit row (no full command bodies). `command` runs unsandboxed on the server, so the panel is admin-gated and a soft warning flags dangerous patterns without blocking the save.

### Policy Control Authoring

Dashboard V2's **Policy Control** tab is the business-friendly authoring layer for
managed hooks. It stores structured policy definitions in the tenant policy
registry, validates them, simulates deterministic condition matching, and compiles
active policies into the same `hooks:` runtime shape.

Policy Control uses the HookRunner event catalog so it can show both gateable and
observe-only lifecycle events. Blocking decisions (`deny`, `approve`, `escalate`)
are valid only on gateable events; observe-only events are intended for audit,
evidence capture, and scoring.

When a managed policy uses `decision: approve`, the generated hook explicitly sets
`on_block: hitl` and includes an `approval` payload. The hook still runs the fixed
`policy_engine.py` evaluator; Policy Control never emits arbitrary shell commands
from chat or form input. The Create With Assistant flow runs the `policy_authoring`
skill to draft managed policy YAML, then the admin reviews it in Form View or YAML
View and must validate, simulate, save, and publish before the hook is written.
For readability, YAML View renders a compiled bundle containing both the managed
`policy:` section and the generated `hooks:` preview; the managed policy remains
the source of truth.

### Platform vs tenant hooks

There are two ownership layers, merged into the effective hook set at HookRunner construction:

| | Platform hooks | Tenant hooks |
|---|---|---|
| Source | framework package `iaf_agent_skills/platform_hooks/hooks.yaml` (+ `scripts/`) | per-agent `config.yaml` `hooks:` |
| Owner | `owner: platform` (forced by loader) | `owner: tenant` (forced on save) |
| Editable from UI/API? | **No** — read-only; change only via a platform release | Yes — admin-editable |
| Priority band | clamped to **≤99** (runs first) | clamped to **≥100** (runs after platform) |
| Scope | `applies_to: { scope: all \| tenants \| agents }` | the agent it's configured on |

- **Merge:** `iaf_agent_skills/platform_hooks/resolve_effective_hooks(tenant_hooks, agent_id, tenant_id)` loads the manifest, filters by `applies_to`, strips manifest-only fields (`applies_to`/`source`) via `to_runtime_hook`, forces owner, clamps priorities, and returns `{event:[platform..., tenant...]}`. Wired at `agent.py` HookRunner construction.
- **Why:** built-in governance (orchestrator circuit-breaker/audit/validator) can't be silently deleted from the tenant UI/API because it isn't stored in tenant `config.yaml`. A tenant reusing a platform `hook_id` is dropped (de-dupe); the PUT endpoint also rejects reserved platform ids (400).
- **Scripts:** referenced via `$IAF_PLATFORM_HOOKS_DIR` (framework dir, same across tenants); they still use `$IAF_AGENT_ROOT` for per-tenant output (e.g. the audit DB).
- **Runtime fields:** platform hooks preserve `on_block` and `approval` metadata
  so built-in policy hooks can deny or request HITL through the same contract as
  tenant hooks.
- **Fail-loud:** `IAF_PLATFORM_HOOKS_REQUIRED=true` (default) — a corrupt/missing manifest raises rather than silently dropping governance. `IAF_PLATFORM_HOOKS_MANIFEST` is a privileged dev/test override.
- **Reload:** the manifest is cached at import → **restart** to apply manifest edits (per-agent config.yaml edits still apply live via cache eviction).
- The UI shows platform hooks in a read-only "Platform governance (built-in)" section; the editable form binds to tenant hooks only.

---

## Wire Points in Existing Code

### Wire 1 — `agent.py __init__` (~line 200)

After config is loaded, create HookRunner and register internal stubs:

```python
self.hook_runner = HookRunner(
    hooks_config = self.config.get("hooks", {}),
    agent_root   = str(self.kernel.agent_root)
)

# Register internal hooks as stubs — same functions as today's inline code
# These are no-ops until Phase 2 activates them (external_only flag)
self.hook_runner.register_internal("PostSampling",  self._internal_episodic_log)
self.hook_runner.register_internal("PostSampling",  self._internal_implicit_feedback)
self.hook_runner.register_internal("PostSampling",  self._internal_plan_cache_write)
self.hook_runner.register_internal("PostToolUse",   self._internal_tool_learning, matcher=".*")
# can_block=True — activated in Phase 2 when HITL moves into hooks
self.hook_runner.register_internal("PreToolUse",    self._internal_hitl_gate,
                                   matcher=".*", can_block=True)
```

### Wire 2 — `agent.py _build_session_ctx()` — new helper method

```python
def _build_session_ctx(self) -> dict:
    return {
        "session_id":  self.session_id,
        "agent_id":    self.agent_id,
        "tenant_id":   getattr(self.kernel, "tenant_id", ""),
        "skill_name":  getattr(self, "current_skill", "") or "",
        "user_id":     self.user_id,
        "agent_root":  str(self.kernel.agent_root),
        # TODO: add stable conversation_id for cross-turn audit correlation
    }
```

### Wire 3 — `agent.py _run_with_stream_intercept()` (~line 424)

Hooks fire for ALL tool calls (not just dangerous ones). Placed BEFORE existing HITL check:

```python
for tc in msg.tool_calls:
    tc_name = tc.get("name", "")
    tc_args = tc.get("args", {})

    # HOOKS: PreToolUse fires for ALL tool calls
    hook_result = self.hook_runner.run_pre_tool(
        tool_name   = tc_name,
        tool_input  = tc_args,
        session_ctx = self._build_session_ctx()
    )
    if hook_result.blocked:
        if self.pending_tool_call is not None:
            return "__PENDING__"
        self.pending_tool_call = tc
        collected.extend(agent_msgs)
        reason = hook_result.reason or f"Hook blocked {tc_name}"
        logger.info("PreToolUse hook blocked: %s — %s", tc_name, reason)
        # on_block=hitl: set approval_pending and return "__PENDING__"
        # on_block=deny: return a policy-blocked response with no approval

    # EXISTING HITL check — unchanged, runs after hooks
    is_write = (not self.auto_run) and self._is_write_call(tc_name, tc_args)
    is_dangerous, danger_reason = self._is_dangerous_call(tc_name, tc_args)
    if is_write or is_dangerous:
        # ... all existing code untouched
```

Critical: hooks are OUTSIDE the `if is_write or is_dangerous:` block.
This is the fix for the Issue 2 from external review — hooks see ALL tool calls,
not just the HITL-intercepted subset.

### Wire 4 — REMOVED

Original design had Wire 4 firing PostToolUse from the result-parsing loop in agent.py.
REMOVED per review Issue 1. Wire 5 (trace_callback) is the single PostToolUse fire point.

### Wire 5 — `trace_callback.py on_tool_end() + on_tool_error()` — single PostToolUse point

```python
# __init__ gets two new optional params
def __init__(self, trace_id, trace_emitter, progress_tracker,
             hook_runner=None, session_ctx=None):   # NEW
    self._hook_runner = hook_runner
    self._session_ctx = session_ctx

# on_tool_end() — at end, after existing timing/progress code
if self._hook_runner and self._session_ctx:
    self._hook_runner.run_post_tool(
        tool_name   = self._tools[rid].get("name", ""),
        tool_input  = self._tools[rid].get("input_str", ""),
        tool_output = str(output)[:2000],
        session_ctx = self._session_ctx
    )

# on_tool_error() — same pattern
if self._hook_runner and self._session_ctx:
    self._hook_runner.run_post_tool(
        tool_name   = self._tools[rid].get("name", ""),
        tool_input  = self._tools[rid].get("input_str", ""),
        tool_output = f"ERROR: {type(error).__name__}: {str(error)[:500]}",
        session_ctx = self._session_ctx
    )
```

TraceToolCallback created at agent.py ~line 3196:
```python
_tool_cb = TraceToolCallback(
    trace_id         = _trace_id if _te else None,
    trace_emitter    = _te,
    progress_tracker = tracker,
    hook_runner      = self.hook_runner,         # NEW
    session_ctx      = self._build_session_ctx() # NEW
)
```

The passive tool observer receives structured LangChain `inputs` when they carry more than the plain command string, while the hook runner keeps the legacy string input contract for existing hooks. Hook context previews redact structured mappings, JSON-like strings, Python-dict-like strings, bearer/basic authorization values, and assignment-style secrets before they are exposed to diagnostics or external hook environments.

### Kernel Bridge — `SafeKernel.attach_hook_runner()`

`SkillAgent` attaches the same `HookRunner` to `SafeKernel` with a session-context provider. Kernel-internal `get_credential` calls fire `PreToolUse` before credential resolution and `PostToolUse` after every return path. Hook payloads include only credential name/field metadata and safe status summaries such as `DENIED`, `NOT_FOUND`, `FIELD_NOT_FOUND`, `BLOCKED`, or `LOADED:$CRED_NAME_FIELD`; real credential values remain inside the kernel session variable store and are never sent to hooks.

### Wire 6 — `agent.py run()` — PostTurn (new, synchronous)

After `agent.run()` result parsing, before returning response to caller:

```python
# After response is built, before return
result = self.hook_runner.run_post_turn_result(
    response    = response,
    session_ctx = {
        **self._build_session_ctx(),
        "query": query,
    }
)
# blocked + on_block=hitl: set approval_pending
# blocked + on_block=deny: return compliance-blocked response
# otherwise response may be modified or replaced by PostTurn hook
```

### Wire 7 — `agent.py _async_extract_and_log()` (~line 3666) — PostSampling

At the END of the existing background thread function:

```python
# After existing Steps 1 & 2 (episodic log + implicit feedback)
_sampling_ctx = {
    **self._build_session_ctx(),
    "query":            query,
    "response":         response,
    "tool_calls_log":   tool_calls_log,
    "tool_error_count": tool_error_count,
}
# external_only=True during Phase 1 — internal hooks not yet activated
# Switch to external_only=False in Phase 2 when inline code is deleted
self.hook_runner.run_post_sampling(_sampling_ctx, external_only=True)
```

---

## Internal Wrapper Methods (thin wrappers for Phase 2 migration)

These live on `SkillAgent`. Each wraps the EXACT code that runs inline today.
During Phase 1: registered but never called (external_only=True blocks them).
During Phase 2: activated one at a time, inline code deleted.

```python
def _internal_episodic_log(self, ctx: dict):
    """Phase 2 target: move from _async_extract_and_log() inline block."""
    self.memory.log_episode(
        user_input=ctx["query"], response=ctx["response"],
        skill=ctx["skill_name"], tool_calls=ctx["tool_calls_log"], ...
    )

def _internal_implicit_feedback(self, ctx: dict):
    """Phase 2 target: move from _async_extract_and_log() inline block."""
    signals = self._analyze_implicit_feedback(...)
    ...

def _internal_plan_cache_write(self, ctx: dict):
    """Phase 2 target: move from inline code after invoke() ~line 3620."""
    ...

def _internal_tool_learning(self, ctx: dict):
    """Phase 2 target: move from result loop ~line 3441 (append_learning call)."""
    self.append_learning("tool_execution", {...})

def _internal_hitl_gate(self, ctx: dict) -> HookResult:
    """Phase 2 target: move from _run_with_stream_intercept() HITL check.
    can_block=True. When activated, _is_dangerous_call + _is_write_call
    move here and inline code in _run_with_stream_intercept is deleted."""
    is_write = (not self.auto_run) and self._is_write_call(
        ctx["tool_name"], ctx["tool_input"])
    is_dangerous, reason = self._is_dangerous_call(
        ctx["tool_name"], ctx["tool_input"])
    if is_write or is_dangerous:
        return HookResult(blocked=True, reason=reason)
    return HookResult(blocked=False)
```

---

## File Change Summary

| File | What changes | Lines added |
|------|-------------|-------------|
| `iaf_agent_skills/hook_runner.py` | **New file** — HookRunner, ExternalHook, InternalHook, HookResult, JSON parsing | ~160 lines |
| `iaf_agent_skills/agent.py` | `__init__`: create HookRunner + register 5 internal stubs | ~20 lines |
| `iaf_agent_skills/agent.py` | `_build_session_ctx()` new helper | ~10 lines |
| `iaf_agent_skills/agent.py` | `_run_with_stream_intercept()`: hook check for ALL tools before HITL | ~15 lines |
| `iaf_agent_skills/agent.py` | PostTurn wire in `run()` after response built | ~5 lines |
| `iaf_agent_skills/agent.py` | PostSampling wire in `_async_extract_and_log` | ~6 lines |
| `iaf_agent_skills/agent.py` | `_internal_*` wrapper methods (5 thin wrappers) | ~40 lines |
| `iaf_agent_skills/trace_callback.py` | `__init__` new params, `on_tool_end` + `on_tool_error` fire PostToolUse | ~15 lines |
| `config.yaml` (per agent) | Optional `hooks:` section | Config only |

**Zero behaviour change in Phase 1.** All existing logic runs identically.

---

## Phase 2 Migration Checklist (future, one at a time)

For each internal hook migration:
1. Change `external_only=True` → `external_only=False` for that specific handler
2. Delete the inline code doing the same work
3. Test — behaviour identical, agent.py shrinks

Recommended migration order (lowest risk first):

```
[ ] _internal_tool_learning      — smallest, append_learning call only
[ ] _internal_plan_cache_write   — self-contained, no LLM call
[ ] _internal_episodic_log       — straightforward memory write
[ ] _internal_implicit_feedback  — uses light_llm, test carefully
[ ] _internal_hitl_gate          — last, most critical, thorough testing required
```

After all 5 are migrated, `agent.py run()` becomes:
1. Build prompt
2. Call LLM (stream intercept handles PreToolUse)
3. Parse response
4. PostTurn
5. Start bg thread (PostToolUse via trace_callback, PostSampling at thread end)

---

## What Was Reviewed and Why Decisions Were Made

### External LLM Review Feedback — Accepted / Rejected

| Issue | Decision | Reason |
|-------|----------|--------|
| Issue 1: PostToolUse fires twice (Wire 4 + Wire 6) | **ACCEPT** — removed Wire 4 | trace_callback is the right single fire point |
| Issue 2: PreToolUse only fires for write/dangerous tools | **ACCEPT PROBLEM, REJECT FIX** | Fix in stream intercept (move hook check outside if-block), not in tool_factory.py |
| Issue 3: Timeout silently blocks | **ACCEPT** — timeout always continues | Broken hook script must never take down agent |
| Issue 4: Missing conversation_id | **ACCEPT AS TODO** | Valid for enterprise audit, not Phase 1 blocking |
| Issue 5: Internal hooks can't block | **ACCEPT** — added can_block flag | Needed for HITL migration in Phase 2 |
| Refinement 1: on_tool_error event | **DEFER to Phase 2** | trace_callback.on_tool_error already exists, add later |
| Refinement 2: Execution order guarantee | **ACCEPT** — documented above | Config declaration order, short-circuit on first block |
| Refinement 3: JSON stdout from hooks | **ACCEPT** — _parse_hook_output() added | High value for enterprise policy engines |

### PreTurn hooks discussion

User asked: "what if we need hooks even before agent runs like routing, query memory?"

Decision: **No PreTurn event needed** because:
- Routing runs in `chat.py` before `agent.run()` — different architectural layer
- Context loading / prompt assembly are CORE — cannot be hooked safely
- `query_memory` is a tool call — PreToolUse already covers it
- PostSampling IS "after agent runs" — it fires after LLM final response

**PostTurn WAS added** as the 4th event based on this discussion. It is synchronous,
fires after agent response is built but before HTTP response is sent, and can
validate/modify/block the response. This is the enterprise compliance gate on output.
PostSampling remains async for logging side effects.

---

## Example Use Cases by Event

### PreToolUse
- Block `DELETE FROM` SQL queries on production databases
- Require approval for any `kubectl` command
- Log all tool calls to external audit system before execution
- Check external policy engine (ServiceNow, OPA) before executing

### PostToolUse
- Log tool execution to Splunk/Datadog
- Alert on tool errors via PagerDuty
- Track tool usage metrics per tenant

### PostTurn
- Validate response doesn't contain PII before sending to user
- Add mandatory compliance disclaimers to financial advice
- Block responses that reference internal system paths
- Log complete turn (query + response) to immutable audit trail

### PostSampling
- Send turn summary to Slack channel
- Update external dashboard with agent activity
- Trigger downstream workflows based on agent output
- Non-blocking background analytics
