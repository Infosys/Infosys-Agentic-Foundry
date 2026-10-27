# AGENTS.md

> Repo-wide guidance for AI coding agents working in AgentPro.
> More specific `AGENTS.md` files in subdirectories may add local details, but
> these principles apply to all future changes unless the user explicitly says
> otherwise.

## Architecture Principles

- Prefer the established AgentOS composable architecture: stable contracts,
  provider/adapter boundaries, service modules, and thin routers/UI.
- Do not bypass existing services, providers, or capability adapters for quick
  fixes. If a route needs a model, tool, credential, evidence store, entitlement
  check, or runtime service, use the registered provider/service API.
- Keep runtime behavior and dashboard read behavior separate. Runtime endpoints
  may use `SkillAgent`, `SafeKernel`, tools, memory, approvals, and hooks.
  Read-only dashboard endpoints should use lightweight read models or service
  stores when possible, not cold-start a full agent just to render a table.
- Preserve tenant-aware paths and config. Resolve roots from existing config
  helpers (`DATA_ROOT`, `SKILLS_PATH`, tenant/agent/user ids) instead of
  hardcoding local absolute paths or a single tenant layout.
- Favor small, explicit service modules over adding more logic directly into
  FastAPI routers, Alpine UI blocks, or monolithic runtime classes.

## Contracts And Providers

- Use `agentos_contracts` descriptors and Protocols for shared extension points.
  Do not invent parallel data shapes when a stable contract exists.
- Model calls must go through the model provider layer (`ModelProviderAdapter`,
  `ModelRegistry` via the approved provider path, or the active capability).
  Do not call provider SDKs or deployment APIs directly from routers or UI code.
- Tool construction should go through the active `ToolProvider`/runtime factory.
  Do not instantiate ad hoc tools in unrelated modules.
- Evidence, credentials, entitlements, hooks, traces, queues, and scheduler work
  should use their registered adapters/capabilities. Direct store/API calls are
  acceptable only inside the adapter implementation itself or in explicit tests.

## Service Boundaries

- Routers should validate identity/permissions, bind request parameters, call a
  service/read model/runtime API, and shape the response. They should not own
  domain workflows, persistence rules, or provider-specific logic.
- UI files should stay thin: call APIs and render state. Avoid embedding business
  rules or API orchestration in Alpine handlers when a backend service can own it.
- For dashboard list/stat/status views, prefer read models such as
  `KnowledgeDashboardStore`: fast, read-only, no agent side effects.
- For mutations, preserve the authoritative runtime path so indexes, lifecycle
  events, memory side effects, and approvals remain consistent.

## Knowledge And Memory

- Keep the three-layer knowledge model clear:
  - `Enterprise_Context.md` routes intent and domain context.
  - Knowledge Bundles under `/shared/knowledge/<bundle_id>/` are curated domain
    wiki/runbook/policy pages.
  - `MEMORY.md` and memory topic files are operational learned memory.
- Confirmed knowledge may be written to bundles, memory topics, context files,
  or explicitly selected `SKILL.md` operating notes. Do not silently promote
  ordinary knowledge into skill definitions.

## Documentation Authority

- Documentation explains the system; **code and tests define it**. When docs and
  implementation disagree, treat the doc as stale until verified and updated.
- For onboarding another LLM or reviewer, start with
  `IAF_AgentOS_Harness_latest/docs/DOCUMENTATION_AUTHORITY.md`, then
  `docs/README.md`, `docs/03_architecture.md`, and `docs/CODE_DOC_MAP.yaml`.
- Trace every architectural claim from `IAF-Agent-Studio/server.py` through the
  relevant router/service/runtime module and run the mapped tests before
  asserting behaviour — especially for security, sandboxing, reload semantics,
  queue backends, and multi-replica session rules.

## Change Discipline

- Before changing code, check existing local patterns and use the nearest
  service/provider abstraction instead of adding a direct call.
- Add or update focused tests for changed behavior. Prefer narrow tests around
  the service/read model/provider boundary being changed.
- For code changes, check `docs/CODE_DOC_MAP.yaml` and update every mapped doc.
  If you add a new code file, add a mapping unless the file is purely test-only.
- Keep changes scoped. Do not refactor unrelated modules while fixing a local
  issue unless the refactor is necessary to preserve the architecture boundary.

## Local Runtime Commands

- This repo uses system Python, not the checked-in venv. Start Studio from
  `IAF-Agent-Studio` with `python3 server.py`.
- For the hardened remote kernel sandbox mode, run two processes with the same
  `AGENTOS_KERNEL_TOKEN_SECRET`:
  - Kernel worker:
    `AGENTOS_KERNEL_TOKEN_SECRET=<32+ chars> python3 kernel_worker.py`
  - Studio server:
    `AGENTOS_KERNEL_BACKEND=remote AGENTOS_KERNEL_TOKEN_SECRET=<32+ chars> python3 server.py`
- In that mode, Studio serves the app/API/UI on `http://127.0.0.1:8081`, and
  the kernel worker serves the internal kernel boundary on
  `http://127.0.0.1:18081`.

## Quick Checks Before Implementing

- Am I bypassing an existing provider, service, adapter, read model, or contract?
- Am I putting domain logic in a router or UI handler that belongs in a service?
- Does this read-only endpoint need a full `SkillAgent`, or can it use a read
  model?
- Are paths tenant/config driven rather than hardcoded?
- Did I update tests and mapped docs for the behavior I changed?
