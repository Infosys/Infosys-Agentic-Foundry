# Enterprise Adapter Authoring Guide

This guide is for platform engineers adding enterprise provider adapters to AgentOS.

The platform goal is provider-backed replaceability, not instant plug-and-play. An adapter is complete only when a real runtime call site resolves through the normalized boundary, the local/default path remains first-class, tests prove parity and failure behavior, and diagnostics expose safe health without leaking secrets.

The rule is simple:

```text
Normalize inside. Adapt outside.
```

Core runtime modules should consume normalized contracts. Customer SDKs, vendor payload shapes, tokens, retry quirks, and endpoint-specific behavior belong only in provider adapters.

## Adapter Lifecycle

Every adapter follows this lifecycle.

1. Trace the current runtime flow.
   Identify the concrete implementation, existing abstraction, factory or registry seam, and every real call site that must be migrated.

2. Extend the existing abstraction.
   Prefer the current boundary over a new parallel stack. Examples: `TraceEmitter`, `TwinEmitter`, `IdentityContext`, `EntitlementProvider`, `CredentialStoreSecretProvider`, `EvidenceCollectorAdapter`, `MemoryCapability`, `TaxonomyRoutingCapability`, and `ModelProviderAdapter`.

3. Define the minimal contract from actual call sites.
   Do not design broad future interfaces up front. The first contract should contain only the methods and fields the runtime already needs.

4. Keep the local provider authoritative.
   Local SQLite, JSONL, YAML, env/file/Fernet, Redis, and direct in-process defaults must continue working for development, tests, demos, and rollback.

5. Add provider selection and safe config.
   Add env/profile settings in `IAF-Agent-Studio/shared/config.py` or the closest existing factory. Never put bearer tokens, API keys, or client secrets in capability metadata, docs examples, logs, or tests.

6. Route at least one real call site through the boundary.
   Registry registration is discovery only. Runtime adoption requires code such as `get_provider().check(...)`, `fanout.emit(...)`, or `adapter.persist(...)` on an execution path users actually exercise.

7. Add health diagnostics.
   Expose selected provider, degraded state, bounded error type/preview, counters, and redaction policy through capability snapshots. Diagnostics must be safe for startup logs and API responses.

8. Write contract tests before or alongside implementation.
   Cover local parity, provider selection, bounded payloads, redaction, failure behavior, idempotency where relevant, and proof that a real call site used the selected provider.

9. Add sandbox or E2E validation.
   Fake and local collectors can prove contract behavior. Real Entra, Key Vault, Splunk, Azure Monitor, Datadog, OPA, ServiceNow, or customer systems require sandbox credentials and must be called out as validation-dependent.

10. Define fallback and rollback.
    Each adapter needs a default local path, a disable switch or profile fallback, and a clear failure mode: fail closed for security/policy/mandatory audit, fail open or degrade for telemetry and optional mirrors.

## Where To Put Things

| Need | Preferred location |
|---|---|
| Provider contract or fanout | Closest existing module, for example `telemetry_providers.py` or `shared/audit_evidence_sinks.py` |
| Runtime factory/profile selection | Existing factory or `shared/config.py` backed helper |
| Capability discovery metadata | `IAF-Agent-Studio/shared/capability_bootstrap.py` |
| Request identity mapping | `IAF-Agent-Studio/auth/identity.py` |
| Secret resolution | `agent_os/secret_provider.py` and `CredentialResolverAdapter` |
| Entitlement decisions | `IAF-Agent-Studio/security/provider.py` |
| Audit/evidence writes | `IAF-Agent-Studio/shared/audit_evidence_sinks.py` and `EvidenceCollectorAdapter` |
| Adapter tests | `IAF-Agent-Studio/tests/test_<capability>_adapters.py` or closest existing suite |
| Live or local smoke | `IAF-Agent-Studio/tests/run_<capability>_e2e.py` |

## Provider Family Status

| Family | MVP status | Runtime posture |
|---|---|---|
| Telemetry | Implemented | Local SQLite plus optional OTLP JSON fanout; telemetry failures degrade without blocking execution |
| Identity/auth | Implemented | Local JWT remains default; OIDC/JWKS is contract-tested and sandbox-ready |
| Secrets | Implemented | `SafeKernel.get_credential` resolves through `SecretProvider`; local env/file/Fernet remains default |
| Policy/entitlements | Implemented | Runtime checks resolve through `EntitlementProvider`; enforce mode fails closed, observe mode records would-deny |
| Audit/evidence | Implemented | Local JSONL/SQLite remains authoritative; optional redacted JSONL mirrors are log-forwarder friendly |
| Queue/approval | Deferred | Direct local/Redis singletons remain; external workflow providers wait for customer demand |
| Memory/vector | Deferred | Direct `AgentMemory` remains default; `MemoryCapability` is parity guardrail, not a backend swap yet |
| Taxonomy/routing | Deferred | Current taxonomy result is authoritative; shadow mode measures drift only |
| Model provider | Incremental | Runtime roles resolve through `default_model_provider.get(role)`; `execution_mode: react` may select `react_runtime=langgraph|native`, with Azure OpenAI native tool calls implemented for the current provider and LangGraph as rollback |

## Testing Checklist

For every non-deferred adapter, include all applicable checks.

- Local/default behavior is unchanged.
- Provider selection reaches the new provider at runtime.
- A real call site resolves through the provider boundary.
- Provider failure behavior matches the capability risk profile.
- Payloads are bounded and deterministic where ordering matters.
- Tokens, passwords, secrets, bearer values, URLs with credentials, and prompt-sized data are redacted from diagnostics and mirror payloads.
- Idempotent writes remain idempotent.
- Health metadata is safe for capability snapshots.
- E2E smoke validates an observable sink or API response, not just process startup.

## Failure Policy

| Capability | Default failure posture |
|---|---|
| Telemetry mirrors | Degrade; never block chat, queue, cron, or mission execution |
| Identity validation | Fail closed when auth is enabled |
| Secret resolution | Fail closed for missing/unauthorized secrets; never reveal raw values |
| Entitlements | Fail closed in `ENTITLEMENTS_ENFORCEMENT_MODE=enforce`; allow with audit metadata in `observe` |
| Mandatory audit/evidence | Local persistence is authoritative; optional mirrors degrade |
| Queue/approval external providers | Deferred until a target system defines the required delivery and retry semantics |
| Memory/vector providers | Deferred until corpus parity proves no behavior regression |
| Taxonomy/routing providers | Deferred until shadow drift proves routing-quality parity |
| Native React runtime | Uses Azure OpenAI native tool calls through the existing model provider; degrade to `react_runtime=langgraph` unless fallback is explicitly disabled; never bypass tool governance, HITL, policy, audit, or evidence |

## Authoring Template

Use this structure when proposing or implementing a new adapter.

```markdown
### Adapter: <capability> -> <provider>

Runtime call sites:
- <file/function/path that will resolve through the provider>

Existing abstraction extended:
- <existing class/module>

Minimal contract:
- <methods and fields consumed by runtime>

Config:
- <env/profile flags, defaults, disable switch>

Diagnostics:
- <safe health fields, counters, redaction policy>

Failure policy:
- <fail open/closed/degrade, retry/drop behavior>

Tests:
- <unit/contract tests>
- <runtime-resolution test>
- <local or sandbox E2E smoke>

Validation limits:
- <what fake/local tests prove>
- <what requires customer/demo credentials>

Rollback:
- <profile/env/local fallback>
```

## Common Mistakes

- Registering a provider in the capability registry without routing any runtime call site through it.
- Creating a second abstraction when a local one already exists.
- Making remote schemas broad before one real sink or provider is implemented.
- Treating telemetry failure and mandatory audit/policy failure the same way.
- Returning raw exception strings, headers, endpoints, tokens, or large prompts in health metadata.
- Claiming customer validation when only local fake or mocked sandbox tests have run.
