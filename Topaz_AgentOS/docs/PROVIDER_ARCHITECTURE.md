# Runtime Provider Architecture

AgentPro exposes five runtime provider slots so partner teams can bring their
own capability implementations without changing `SkillAgent` orchestration.

## Provider Slots

| Slot | Env Var | Default Wrapper | Wrapped Implementation |
|---|---|---|---|
| Skill | `SKILL_PROVIDER` | `FileSystemSkillProvider` | `SkillLoader` |
| Router | `ROUTER_PROVIDER` | `DefaultRouterProvider` | `SkillRouter` |
| Tool | `TOOL_PROVIDER` | `BuiltinToolProvider` | `tool_factory`, bundled tools, code executor |
| Hook | `HOOK_PROVIDER` | `DefaultHookProvider` | `HookRunner` construction |
| Trace | `TRACE_PROVIDER` | `DefaultTraceProvider` | Studio `TraceEmitter` singleton |

All defaults are selected by `default` and preserve existing behavior. Custom
providers can be supplied as import paths, for example:

```bash
SKILL_PROVIDER=partner_adapters.memory_skill_provider:MemorySkillProvider
TOOL_PROVIDER=partner_adapters.sample_tool_provider:SampleToolProvider
HOOK_PROVIDER=partner_adapters.sample_hook_provider:SampleHookProvider
```

Provider selection is independent of execution-mode rollback.
`DYNAMIC_ORCHESTRATOR_ENABLED=false` keeps the active router provider but makes
router-selected orchestrator hints execute through ReAct instead. Planned mode
and explicitly declared skill execution modes are unaffected.

## Contracts

The stable provider contracts live in the dependency-free extension SDK package
`IAF-Agent-Skills/agentos_contracts/`. The historical
`IAF-Agent-Skills/iaf_agent_skills/providers/` modules remain as compatibility
shims that re-export the same `typing.Protocol` interfaces, so existing engine
and partner imports continue to work while new adapters can depend only on
`agentos-contracts`.

Model provider components live under `IAF-Agent-Skills/agentos_model/`
(`agentos-model`). This package owns provider-neutral reasoning metadata,
`ModelRegistry`, `ModelProviderAdapter`, and the Azure Responses, Vertex/Gemini,
and Anthropic chat adapters. Historical `iaf_agent_skills.model_*` and provider
adapter imports remain compatibility shims.

`ModelProviderAdapter.get(role)` preserves normal `ModelRegistry` semantics by
default. Private Learning Loop recommendations are advisory unless
`EVAL_ROUTER_ENABLED=true`; when enabled, an explicit `EVAL_ROUTER_ROLE_MAP` or
`EVAL_ROUTER_ROLE_<ROLE>` value may redirect a requested role. This keeps
eval-based routing opt-in and reversible.

The engine import surface is exposed as `IAF-Agent-Skills/agentos_engine/`
(`agentos-engine`). It currently re-exports the historical `iaf_agent_skills`
runtime as a low-risk facade, giving adopters the target package name while the
full product continues to use old imports unchanged.

Every provider includes:

- `health()` for bounded operational diagnostics.
- `snapshot()` for redacted capability registry metadata.

The default wrappers live under
`IAF-Agent-Skills/iaf_agent_skills/providers_default/`.

Provider wiring still reads env-style settings (`SKILL_PROVIDER`,
`ROUTER_PROVIDER`, `TOOL_PROVIDER`, `HOOK_PROVIDER`, `TRACE_PROVIDER`) from the
process environment or explicit factory arguments. When neither is set, the
factory falls back to host-registered provider settings from the engine runtime
bridge (see below) rather than importing `shared.config`. The engine
(`iaf_agent_skills`) no longer imports any Studio module.

## Host Service Injection (engine ↔ host boundary)

Beyond the five replaceable provider slots, the engine needs a few services that
an embedding host (Studio) owns: a trace emitter, an LLM-cost function, an
evidence store, and — for Mission Mode — WebSocket push, research synthesis,
per-item HITL checkpointing, and a durable runtime DB. Historically the engine
reached "upward" into Studio for these via lazy `from shared…` / `from
routers…` / `from trace_emitter…` imports. Those upward imports have been
removed.

Instead the engine exposes a process-wide **runtime bridge** and the host
registers implementations of stable host-service contracts:

| Host service | Contract (`agentos_contracts`) | Engine accessor (`iaf_agent_skills.runtime_bridge`) |
|---|---|---|
| Evidence store | `EvidenceSink` | `get_evidence_sink()` |
| Mission runtime services | `MissionRuntimeBridge` | `get_mission_bridge()` |
| Trace emitter | (uses `TraceProvider`) | `get_trace_emitter()` |
| LLM cost function | callable `(model, prompt_tokens, completion_tokens) -> float` | `calculate_cost(...)` |
| Provider config | plain mapping | `get_provider_setting(name)` |
| Deployment identity | plain values | `default_tenant_id()`, `default_agent_id()` |

Key properties:

- The engine never imports the host. The host calls the `register_*` functions
  in `iaf_agent_skills.runtime_bridge` once at startup.
- When nothing is registered (standalone scripts, unit tests, partner
  embeddings), every accessor degrades gracefully — evidence/mission calls
  no-op, the trace emitter is `None`, and `calculate_cost` uses a built-in
  pricing table.
- Studio performs registration in `shared/config.py` (the earliest Studio module
  on `sys.path`) via `shared/engine_bridge.py`. All registered services are
  lazy — heavy imports are deferred to first use — so registration stays
  import-cheap and correct even for a single-module unit test.
- `SERVER_LOG_PATH` lets a host point self-evolution log analysis at its own
  server log instead of the default `IAF-Agent-Studio/logs/server.log`.

## Runtime Wiring

`SkillAgent.__init__` keeps its existing positional signature:

```python
SkillAgent(kernel, skills_path, user_id, trace_emitter, enterprise_root)
```

Provider parameters are optional keyword-only arguments. Existing construction
sites continue to work, while tests or partner integrations can inject:

```python
SkillAgent(
    kernel=kernel,
    skills_path=skills_path,
    skill_provider=my_skill_provider,
    router_provider=my_router_provider,
)
```

`agent.router`, `agent.loader`, `agent.hook_runner`, and `agent.trace_emitter`
remain public compatibility attributes. The router provider must preserve
`match`, `list_skills`, `get_skill_info`, `skill_exists`, `set_skill_filter`,
`set_personal_path`, `reload`, `skills_path`, `index`, and
`_get_filtered_skills`.

Session clones and Redis-restored agents also backfill missing provider
attributes before tool construction, so sessions created before a provider
upgrade can continue without losing the current conversation.

## Registration

Studio startup registers all five slots in `shared/capability_bootstrap.py` with
`mode: adapter_boundary`. The registry is diagnostic; the active runtime wiring
comes from `iaf_agent_skills.providers.factory`.

## Partner Guidance

Start with one slot at a time and leave every other env var at `default`.
Provider implementations should be deterministic, avoid long blocking work in
constructors, and keep `health()`/`snapshot()` free of secrets and large payloads.

The dedicated-enterprise runtime-role split does not add a parallel provider
path. API, scheduler, and queue processes resolve the same registered provider
contracts; role selection controls lifecycle ownership only. Security keys and
role settings are deployment configuration and must not be exposed through
provider health snapshots. The Command Center Postgres claim store is also a
Studio queue backend selected by deployment config, not a provider slot.

The AgentOS kernel backend is also deployment config, not a provider slot.
`AGENTOS_KERNEL_BACKEND=local` returns the in-process `SafeKernel`; `remote`
uses a signed kernel worker for shell/file/Python execution. Tool providers keep
constructing the same tool contracts, and the kernel runtime decides where those
contracts execute.

Recovery verification is likewise a Studio-owned read service, not a provider
slot. It reads an isolated `RECOVERY_VERIFICATION_ROOT` without constructing an
agent or invoking model/tool providers, and its root metadata omits absolute
paths and credentials.
