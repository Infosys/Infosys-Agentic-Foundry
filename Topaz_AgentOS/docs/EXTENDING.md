# Extending IAF AgentOS

This guide shows how to extend the platform without modifying the core
ReAct loop. Two extension surfaces exist:

1. **Hooks** — lifecycle gates / side effects / enrichment / observation.
   Decision-shape: "given context, allow/deny/modify."
2. **Capabilities** — resolver-shape replacements for whole subsystems
   (policy engine, credential resolver, model provider, evidence store,
   trace emitter, …). "Given a name, return the typed thing the runtime
   needs."

Both share one principle: **the core `SkillAgent` / ReAct loop never
changes** when you swap a layer.

For replaceable provider seams and composable package boundaries, also read:

- [PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md)
- [COMPOSABLE_ADOPTION_SPEC.md](COMPOSABLE_ADOPTION_SPEC.md)
- [03_architecture.md](03_architecture.md)

---

## Quick reference

| Task | Surface | Where to put code |
|---|---|---|
| Veto a tool call before it runs | `PreToolUse` hook (Python or shell) | `hooks/pre_tool_*.py` or `config.yaml: hooks: PreToolUse` |
| Audit every model call | `AfterModelCall` hook | as above |
| Replace policy engine with OPA | `policy_engine` capability | New adapter class + registry override |
| Add Vault as a credential backend | `credential_resolver` capability | New adapter wrapping VaultClient |
| Halt a cron firing during a freeze window | `BeforeScheduleFire` hook | as above |
| Slack alert on any blocking-hook deny | `OnBlocked` hook | as above |
| Single kill switch to bypass all hooks | `CAPABILITY_HOOKS_ENABLED=false` env var | shell / systemd unit |

---

## Part 1 — Writing a hook

### Step 1: pick the event

See [HOOK_EVENT_REFERENCE.md](HOOK_EVENT_REFERENCE.md) for the full list of
22 events and what context each carries. The most common are:

- `PreToolUse` — gate any tool (shell, curl, SQL, MCP, code executor, …)
- `PostToolUse` — audit tool outputs (fire-and-forget)
- `PostTurn` — final compliance / PII pass on the response
- `BeforeTurn` — gate or instrument every turn
- `BeforeScheduleFire` — skip cron firings during freeze windows
- `OnMemoryWrite` — audit background memory mutations
- `OnBlocked` — react to any blocking-hook deny in one place

### Step 2: choose internal (Python) or external (shell)

**Internal (recommended for tight integration):**

```python
# my_agent/hooks/pre_tool_audit.py
from iaf_agent_skills.hook_runner import HookResult

def audit_sql(ctx: dict) -> HookResult:
    if ctx["tool_name"] != "run_sql_query":
        return HookResult(blocked=False)
    sql = (ctx.get("tool_input") or {}).get("query", "")
    if "DROP TABLE" in sql.upper():
        return HookResult(blocked=True, reason="DROP TABLE forbidden by policy")
    return HookResult(blocked=False)
```

Register it in `SkillAgent.__init__` or wherever you build the agent:

```python
agent.hook_runner.register_internal(
    "PreToolUse",
    audit_sql,
    can_block=True,
    priority=10,       # lower runs earlier
    fail_policy="closed",  # if THIS hook raises, deny the operation
    hook_id="audit-sql-no-drop",
)
```

**External (recommended for ops / SRE):**

```yaml
# agent_root/config.yaml
hooks:
  PreToolUse:
    - id: redact-pii
      matcher: ".*"
      command: "python3 /opt/iaf/hooks/redact.py"
      mode: blocking
      fail_policy: closed
      timeout_seconds: 5
      max_output_chars: 4096
```

External hooks receive `IAF_*` env vars (full list in
[HOOK_EVENT_REFERENCE.md](HOOK_EVENT_REFERENCE.md)) and may emit JSON on
stdout to communicate `blocked: true / false`, `reason`, or a replacement
`response` (for `PostTurn`).

### Step 3: pick `fail_policy`

| If your hook is for | Use |
|---|---|
| Security (policy check, credential check, compliance) | `fail_policy="closed"` — deny on failure |
| Telemetry, notification, audit logging | `fail_policy="open"` — proceed on failure |

### Step 4: test

Write a tiny test that constructs a fresh `HookRunner`, registers your
hook, and calls the relevant `run_*` method. See
`IAF-Agent-Skills/tests/test_hook_runner.py` for examples of every
pattern.

---

## Part 2 — Writing a capability adapter

When you want to replace an entire subsystem (not gate a specific call),
write a capability adapter. Examples shipped today:

- `iaf_agent_skills.credential_resolver_adapter.CredentialResolverAdapter`
- `iaf_agent_skills.evidence_collector_adapter.EvidenceCollectorAdapter`
- `iaf_agent_skills.model_provider.ModelProviderAdapter`

For enterprise provider adapters, use [ADAPTER_AUTHORING_GUIDE.md](ADAPTER_AUTHORING_GUIDE.md)
as the canonical lifecycle. Capability registration is discovery only; the adapter is not done
until a real runtime call site resolves through the provider boundary and tests prove local
parity, diagnostics, validation limits, and rollback behavior.

### Step 1: define the contract

The capability registry stores instances behind a name. The "contract" is
just the set of methods the rest of the codebase calls on that name. Look
at the existing adapter for the capability you want to replace — that's
the interface to honour. Example for `credential_resolver`:

```python
class MyVaultResolver:
    def resolve(self, name: str, *, consumer: str,
                accessor: str = "", purpose: str = "") -> Optional[Credential]:
        ...
    def list_names(self, consumer: str = "") -> list[str]:
        ...
    def get_metadata(self, name: str) -> Optional[dict]:
        ...
```

### Step 2: register it

Either swap the default in `capability_bootstrap.py`:

```python
from my_vault_resolver import MyVaultResolver

registry.register(
    "credential_resolver",
    MyVaultResolver(...),
    implementation="MyVaultResolver",
    owner="my-org",
    metadata={"backing": "vault"},
)
```

…or use a per-tenant override (preferred if some tenants stay on the
default):

```python
registry.register_tenant_override(
    "credential_resolver",
    "tenant-acme",
    MyVaultResolver(...),
    implementation="MyVaultResolver",
)
```

### Step 3: declare dependencies

If your capability depends on another (e.g. `policy_engine` needs
`credential_resolver` to fetch the policy bundle from a secret), declare
the dependency so the registry validates it at startup:

```python
registry.register(
    "policy_engine",
    OpaPolicyEngine(...),
    implementation="OpaPolicyEngine",
    dependencies=("credential_resolver",),
)
```

Missing or cyclic dependencies raise `CapabilityDependencyError` at
startup — fail fast.

### Step 4: test

See `IAF-Agent-Studio/tests/test_phase5_adapters.py` for round-trip
tests against fake backends. The pattern: hand the adapter a fake
backend object that records calls, then assert the adapter delegates
correctly without touching real infra.

---

## Part 3 — Feature flag

`CAPABILITY_HOOKS_ENABLED` (env var, read once at process start, default
`"true"`):

- `true` — all hook fan-outs fire normally.
- `false` — every `HookRunner.run_*` short-circuits to a no-op. The
  kernel's own credential / external-access hard-gates still run.

Flip at runtime (e.g. from an admin endpoint):

```python
from iaf_agent_skills.hook_runner import HookRunner
HookRunner.set_capability_hooks_enabled(False)   # disable
HookRunner.set_capability_hooks_enabled(True)    # re-enable
```

Use the flag for production rollback or A/B baseline comparison without a
code change.

---

## Part 4 — Background-task instrumentation

Code that runs outside any `SkillAgent` context (self-evolution sweeps,
seeders, scheduled audit jobs) cannot use `agent.hook_runner` directly.
Use the `iaf_agent_skills.background_hooks` module:

```python
from iaf_agent_skills import background_hooks

background_hooks.fire_on_self_evolution_pass(
    pass_id="job-2026-05-30-001",
    skills_analyzed=42,
    gaps_found=7,
    duration_ms=12500,
)
```

`background_hooks` routes through the most recently registered SkillAgent
HookRunner (last-writer-wins). If no SkillAgent has been constructed yet
(e.g. a CLI script), the call is a silent no-op.

---

## Part 5 — Kernel-side hook fire (advanced)

`agent_os.kernel.SafeKernel` exposes `attach_hook_runner(runner,
session_ctx_provider)` so direct kernel commands (`_cmd_get_credential`,
future direct kernel paths) can fire `PreToolUse` / `PostToolUse` with
the right `tool_name`. `SkillAgent.__init__` does this automatically;
standalone kernel uses (tests, CLI tools) don't need to wire it.

---

## What you CANNOT extend (yet)

The Hooked ReAct Harness migration explicitly preserves these as direct
implementations — they remain swappable in the future but no adapter
contract has been frozen:

- `skill_router` (SkillRouter — taxonomy + entity + LLM routing)
- `skill_loader` (SKILL.md parsing + frontmatter)
- `memory_store` / `session_store` (the 3-layer memory architecture)
- `context_loader` (ContextOS FILE/TABLE modes)
- `execution_engine_factory` (workflow / parallel / supervisor /
  orchestrator / planner engines)

If you have a concrete need to swap one of these, open an issue with the
target use case — the plan defers the adapter work, not the
functionality.
