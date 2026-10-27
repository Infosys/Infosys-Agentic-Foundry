# IAF AgentOS — Documentation Index

**Infosys Agentic Foundry** | Agentic Harness Platform

This is the master index for all IAF AgentOS documentation. Find your persona below, follow the reading path, then use the full inventory at the bottom for deep dives.

**Start here for current architecture:** [03_architecture.md](03_architecture.md)

**Before trusting any doc for fixes or production decisions:** read [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md). Documentation is a map, not the contract — **verify behaviour in code and tests** (`server.py`, mapped modules, and the relevant test file) whenever docs and runtime disagree.

---

## Reading Paths by Persona

### Skill Author — adding domain capabilities (no Python needed)

> You want to teach the agent a new business domain. All you need to write is markdown.

| Step | Document | What you do here |
|------|----------|-----------------|
| 1 | [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) | **Canonical** — SKILL.md, taxonomy.md, Enterprise_Context.md format rules and a copy-paste AI prompt block |
| 2 | [skill_templates/](skill_templates/) | Starter SKILL.md per execution_mode (react / workflow / parallel / supervisor / orchestrator) + JSON Schema for IDE validation |
| 3 | [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | End-to-end developer flow: register the skill, add tools, hooks, agent config |
| 4 | [IAF-Agent-Skills/docs/execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md) | When to use react vs workflow vs parallel vs supervisor vs orchestrator |

**Done in ~2 hours.** Test your skill from the Taxonomy Graph simulator at `/skill-builder/v2`.

---

### Platform Developer — extending the Python engine

> You want to write a new tool, hook, execution mode, or modify core agent behaviour.

| Step | Document | What you do here |
|------|----------|-----------------|
| 1 | [03_architecture.md](03_architecture.md) | **Canonical** layered architecture, composable packages, startup behaviour |
| 2 | [PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md) | Replaceable provider seams and partner adapter contracts |
| 3 | [COMPOSABLE_ADOPTION_SPEC.md](COMPOSABLE_ADOPTION_SPEC.md) | Bring-your-own-component packaging and adoption SKUs |
| 4 | [ADAPTER_AUTHORING_GUIDE.md](ADAPTER_AUTHORING_GUIDE.md) | Enterprise adapter lifecycle: route a real call site, add diagnostics/tests, define validation and rollback |
| 5 | [IAF-Agent-Skills/docs/DEVELOPER_QUICKSTART.md](../IAF-Agent-Skills/docs/DEVELOPER_QUICKSTART.md) | Get the engine running locally — includes an AI-assist prompt block for Copilot |
| 6 | [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Parts 4–9: write tools (Python), write hooks, configure agents, add databases |
| 7 | [IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md](../IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md) | Hook contract, pre/post-step lifecycle, circuit breaker pattern |
| 8 | [SOLUTION_MODULES.md](SOLUTION_MODULES.md) | Optional domain accelerators such as IRIS Finance Intelligence |

---

### Integration Developer — calling the API or building a frontend

> You want to call IAF from an external system or embed the agent in your own UI.

| Step | Document | What you do here |
|------|----------|-----------------|
| 1 | [IAF-Agent-Studio/docs/api_reference.md](../IAF-Agent-Studio/docs/api_reference.md) | All REST endpoints — request/response shapes, auth headers |
| 2 | [IAF-Agent-Studio/docs/websocket_protocol.md](../IAF-Agent-Studio/docs/websocket_protocol.md) | WebSocket event types, streaming format, error codes |
| 3 | [IAF-Agent-Studio/docs/evidence_viewer.md](../IAF-Agent-Studio/docs/evidence_viewer.md) | Evidence bundle schema, content APIs, and local source resolution |
| 4 | [IAF-Agent-Studio/docs/context_loading_architecture.md](../IAF-Agent-Studio/docs/context_loading_architecture.md) | FILE MODE vs TABLE MODE — how context is loaded end-to-end; essential for debugging agent responses |

---

### Platform Operator — deployment and infrastructure

> You want to deploy, configure, scale, or schedule agent jobs.

| Step | Document | What you do here |
|------|----------|-----------------|
| 1 | [02_quick_start.md](02_quick_start.md) | Fast local bring-up and first chat |
| 2 | [AGENTPRO_SETUP.md](AGENTPRO_SETUP.md) | Full setup, env vars, directory layout, startup expectations |
| 3 | [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | Server setup, environment variables, Redis config |
| 4 | [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) | Runtime env vars, provider slots, cron reconciliation, module notes |
| 5 | [IAF-Agent-Studio/docs/CRON_SCHEDULER.md](../IAF-Agent-Studio/docs/CRON_SCHEDULER.md) | Redis-backed cron scheduler — syntax, distributed workers, monitoring |
| 6 | [IAF-Agent-Studio/docs/cc_queue.md](../IAF-Agent-Studio/docs/cc_queue.md) | Command Centre queue — HITL approvals, batch jobs, queue draining |
| 7 | [SECURITY_TESTING_GUIDE.md](SECURITY_TESTING_GUIDE.md) | Security validation flows and verification scripts |

---

## Full Document Inventory

### `docs/` — Top-level guides

| Document | Audience | What's in it |
|----------|----------|-------------|
| [README.md](README.md) | All | **This file** — master doc index and reading paths |
| [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md) | Platform devs, AI agents | **Code/tests over docs** — source-of-truth order, entry points, reload semantics, drift checklist |
| [02_quick_start.md](02_quick_start.md) | Operators, developers | Fast local setup, startup output, first chat |
| [03_architecture.md](03_architecture.md) | Platform devs | **Canonical** layered architecture, composable packages, cron reconcile, solution modules |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Platform devs | Compatibility redirect to `03_architecture.md` |
| [AGENTPRO_SETUP.md](AGENTPRO_SETUP.md) | Operators | Full setup guide, env vars, directory layout |
| [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) | Operators, platform devs | Runtime env vars, provider slots, cron reconciliation |
| [PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md) | Platform devs | Provider Protocols, replaceable seams, package boundaries |
| [COMPOSABLE_ADOPTION_SPEC.md](COMPOSABLE_ADOPTION_SPEC.md) | Architecture, product | Bring-your-own-component packaging and adoption SKUs |
| [SOLUTION_MODULES.md](SOLUTION_MODULES.md) | Platform devs, solution authors | Optional domain accelerators and installed-asset policy |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Skill authors, platform devs | End-to-end guide: SKILL.md, context files, tools, hooks, agent config, databases, testing |
| [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) | Skill authors | Exact format rules for taxonomy.md, Enterprise_Context.md, and SKILL.md; includes copy-paste AI assistant prompt block for Claude / GitHub Copilot |
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | Operators | Server setup, env vars, Redis, production checklist |
| [ADAPTER_AUTHORING_GUIDE.md](ADAPTER_AUTHORING_GUIDE.md) | Platform devs | Enterprise adapter lifecycle, provider-backed replaceability, diagnostics, tests, validation limits, rollback |
| [EXTENDING.md](EXTENDING.md) | Platform devs | Hook and capability extension overview; use ADAPTER_AUTHORING_GUIDE for enterprise provider adapters |
| [KEY_FEATURES.md](KEY_FEATURES.md) | All | Full feature list — taxonomy signal routing, three-layer memory, self-evolution, entity registry, hooks |
| [RLM_EXECUTION_MODE.md](RLM_EXECUTION_MODE.md) | Skill authors, platform devs | `execution_mode: rlm` reasoning-as-code loop, governed tools + AST guard, propose-then-apply HITL holds |
| [PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md) | Skill authors (admin), platform devs | `execution_mode: graph` process graphs (verifier + convergence) + the visual Graph Studio tab |
| [SKILL_DESIGNER.md](SKILL_DESIGNER.md) | Developers, admins | NL authoring in Dev Mode — draft any artifact from English, validate, and save via the governed review-queue flow |
| [WORKSTREAMS_AS_RECURRING_OPERATIONS.md](WORKSTREAMS_AS_RECURRING_OPERATIONS.md) | Operators, workstream authors | Workstreams / Mission Mode — recurring autonomous operations over item backlogs |
| [DETERMINISTIC_AUTOMATIONS.md](DETERMINISTIC_AUTOMATIONS.md) | Operators, platform devs | No-LLM shell/python pipelines run from REST, cron, or Workstreams |
| [SKILL_PACK_SPEC.md](SKILL_PACK_SPEC.md) | Skill authors, platform devs | Skill Pack import/export format for sharing capabilities across tenants |
| [RL_EVAL_CAPTURE.md](RL_EVAL_CAPTURE.md) | Platform devs, ML | Opt-in RL/eval trajectory capture — flags, schema, exporters (SFT/DPO/RFT/…) |
| [PRIVATE_LEARNING_LOOP.md](PRIVATE_LEARNING_LOOP.md) | Platform devs, ML | Eval suites, golden sets, evaluators, promotion gates, Trace Value Router |
| [STORAGE_BACKENDS.md](STORAGE_BACKENDS.md) | Operators, platform devs | SQLite / Postgres / Redis / pgvector backends and selection |
| [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md) | Skill authors, operators | All 4 HITL mechanisms, approval rules, queue monitor, decision guide |
| [MISSION_MODE_GUIDE.md](MISSION_MODE_GUIDE.md) | Operators, workstream authors | Mission Mode workstreams, cron-backed schedules, finance demo surfaces |
| [WORKSTREAM_SKILL_CONTRACT_GUIDE.md](WORKSTREAM_SKILL_CONTRACT_GUIDE.md) | Workstream authors | Generic workstream/skill contract and packaged workstream guidance |
| [SECURITY_TESTING_GUIDE.md](SECURITY_TESTING_GUIDE.md) | Operators, security reviewers | Security validation flows and verification script usage |
| [TAXONOMY_AUTHORING.md](TAXONOMY_AUTHORING.md) | Skill authors | Taxonomy scoring internals, structure rules, monitoring (see AUTHORING_GUIDE.md for format rules) |
| [CODE_DOC_MAP.yaml](CODE_DOC_MAP.yaml) | Platform devs | Maps every source file to the docs that cover it — tells you which docs to update after a code change |
| [generated/README.md](generated/README.md) | All | Convention for generated HTML review artifacts |

---

### Repo support folders documented here

| Path | Document | What's in it |
|------|----------|-------------|
| [scripts/verification/](../scripts/verification/) | [scripts/verification/README.md](../scripts/verification/README.md) | Ad-hoc live smoke and security verification scripts |
| [solution_modules/](../solution_modules/) | [SOLUTION_MODULES.md](SOLUTION_MODULES.md) | Optional solution accelerators built on core AgentPro |
| [docs/generated/](generated/) | [generated/README.md](generated/README.md) | Ignored generated HTML review artifacts |

---

### `docs/` — Additional guides, references & runbooks

The curated persona paths above cover the common cases. These are the remaining reference docs and runbooks, grouped by theme. (Historical implementation plans, investigations, and audit reports are intentionally excluded from this index — browse `docs/` directly for those.)

**Setup, deployment & operations**

| Document | Audience | What's in it |
|----------|----------|-------------|
| [AGENTPRO_SETUP.md](AGENTPRO_SETUP.md) | Platform devs | Setup and developer reference — four core components, dependency install, environment configuration |
| [START_STOP.md](START_STOP.md) | Operators | Local-dev runbook: bring the stack up in order (Postgres → Redis → server) via the `ops/` scripts |
| [DEPLOYMENT_SSL_AND_OFFLINE_UI_FIX.md](DEPLOYMENT_SSL_AND_OFFLINE_UI_FIX.md) | Operators | Deploying on the corporate (Zscaler) network: outbound SSL trust + CDN-blocked offline UI |
| [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) | Operators | Resumable runbook to migrate a deployment from SQLite to PostgreSQL |
| [STORAGE_BACKENDS.md](STORAGE_BACKENDS.md) | Platform devs | SQLite vs PostgreSQL storage abstraction; what stays authoritative vs rebuildable cache |
| [ENTERPRISE_OPERATIONS_PROFILE.md](ENTERPRISE_OPERATIONS_PROFILE.md) | Operators | P0 operating baseline topology (ingress, API/scheduler/queue/kernel roles, Redis/Postgres) |
| [SHARED_STORAGE_CUTOVER_RUNBOOK.md](SHARED_STORAGE_CUTOVER_RUNBOOK.md) | Operators | Running across a server fleet: enterprise_root on shared storage, state on Postgres/Redis |
| [HARNESS_PROFILES.md](HARNESS_PROFILES.md) | Platform devs | The five named execution-profile presets and how one is selected by precedence |
| [HARNESS_CONFIGURATION_CATALOG.md](HARNESS_CONFIGURATION_CATALOG.md) | Platform devs | Exhaustive catalog of every runtime-execution knob, its binding layer, and source location |

**Authoring & automations**

| Document | Audience | What's in it |
|----------|----------|-------------|
| [04_skill_authoring.md](04_skill_authoring.md) | Skill authors | What a skill is and the full SKILL.md structure (frontmatter + prompt body) |
| [AGENTPRO_SKILL_AUTHOR.md](AGENTPRO_SKILL_AUTHOR.md) | Skill authors | Drop-in coding-agent context: exact SKILL.md and Enterprise_Context.md formats to generate skills |
| [DETERMINISTIC_AUTOMATIONS.md](DETERMINISTIC_AUTOMATIONS.md) | Skill authors | No-LLM pipelines of fixed shell/Python steps — when to use them vs skills |
| [WORKSTREAMS_AS_RECURRING_OPERATIONS.md](WORKSTREAMS_AS_RECURRING_OPERATIONS.md) | Operators | Workstreams as the business control plane over cron/queue for recurring operations |
| [STANDALONE_CRON_JOBS.md](STANDALONE_CRON_JOBS.md) | Operators | Scheduled jobs not attached to a workstream; enterprise_root YAML source + Redis reconciliation |
| [SKILL_PACK_SPEC.md](SKILL_PACK_SPEC.md) | Integration devs | Draft spec for packaging an agent into a portable folder runnable across harnesses |

**Platform internals**

| Document | Audience | What's in it |
|----------|----------|-------------|
| [05_agent_config.md](05_agent_config.md) | Platform devs | The agent as a configuration boundary (skills, tools, MCP, hooks, memory) + feature flags |
| [06_memory_and_learning.md](06_memory_and_learning.md) | Platform devs | Three-layer memory (episodic, knowledge records, per-skill learnings) + shared knowledge bundles |
| [HOOK_EVENT_REFERENCE.md](HOOK_EVENT_REFERENCE.md) | Platform devs | Every hook event: firing point, context payload, gateability, fail policy |
| [HOOK_BASED_HITL_FLOW.md](HOOK_BASED_HITL_FLOW.md) | Platform devs | How a PreToolUse hook deterministically forces HITL approval before a risky tool call |
| [RL_EVAL_CAPTURE.md](RL_EVAL_CAPTURE.md) | Platform devs | Opt-in, framework-neutral RL/eval capture: runtime flags, redaction, per-tenant storage |
| [PRIVATE_LEARNING_LOOP.md](PRIVATE_LEARNING_LOOP.md) | Platform devs | Tenant-owned eval/learning surface: enterprise tests, golden sets, rubrics under enterprise_root |

**Security, partners & decisions**

| Document | Audience | What's in it |
|----------|----------|-------------|
| [07_auth_and_users.md](07_auth_and_users.md) | Security reviewers | Authoritative reference: authentication, user-store backends, roles → permissions |
| [SECURITY_DEVELOPER_GUIDE.md](SECURITY_DEVELOPER_GUIDE.md) | Security reviewers | Layered defense-in-depth model (auth, entitlements, hooks, kernel gates, secrets) + recipes |
| [PARTNER_INSTALL_GUIDE.md](PARTNER_INSTALL_GUIDE.md) | Partners | Adopting AgentOS layers via editable installs; choosing among the three SKUs |

---

### `IAF-Agent-Skills/docs/` — Engine deep dives

| Document | Audience | What's in it |
|----------|----------|-------------|
| [DEVELOPER_QUICKSTART.md](../IAF-Agent-Skills/docs/DEVELOPER_QUICKSTART.md) | Platform devs | Get the engine running locally in 10 minutes; includes Copilot/Claude prompt block |
| [SKILL_DEVELOPMENT.md](../IAF-Agent-Skills/docs/SKILL_DEVELOPMENT.md) | _redirect_ | Stub → see [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) for the canonical SKILL.md reference |
| [execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md) | Skill authors, platform devs | react / workflow / parallel / supervisor / orchestrator / planned — when each fires, how to declare |
| [memory_schema.md](../IAF-Agent-Skills/docs/memory_schema.md) | Platform devs | Three-layer memory architecture: episodic JSONL (Layer 1), knowledge records + SQLite FTS5 (Layer 2), Redis session state (Layer 3) |
| [entity_registry.md](../IAF-Agent-Skills/docs/entity_registry.md) | Platform devs | Entity resolution pipeline, alias longest-match sorting, TIER1 xref log, entity guide seeder, fragment dedup |
| [HOOK_SYSTEM_DESIGN.md](../IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md) | Platform devs | Hook contract (pre/post-step), circuit breaker pattern, PII redaction, audit logging hooks |
| [AGENT_CUSTOMIZATION.md](../IAF-Agent-Skills/docs/AGENT_CUSTOMIZATION.md) | _redirect_ | Stub → see [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) + [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) |
| [TESTING.md](../IAF-Agent-Skills/docs/TESTING.md) | Platform devs | Unit-testing skills in isolation, integration test patterns, test fixtures |
| [CONTRIBUTING.md](../IAF-Agent-Skills/docs/CONTRIBUTING.md) | Platform devs | PR standards, branch naming, code style, review checklist |
| [INVOKE_TOOLS_CHANGESET.md](../IAF-Agent-Skills/docs/INVOKE_TOOLS_CHANGESET.md) | Platform devs | Changeset log for tool invocation API changes — read before upgrading |

---

### `IAF-Agent-Studio/docs/` — API and UI

| Document | Audience | What's in it |
|----------|----------|-------------|
| [api_reference.md](../IAF-Agent-Studio/docs/api_reference.md) | Integration devs | All REST endpoints — skills, chat, knowledge, auth, evolution, queue, cron |
| [websocket_protocol.md](../IAF-Agent-Studio/docs/websocket_protocol.md) | Integration devs | WebSocket event types, streaming format, connection lifecycle, error codes |
| [context_loading_architecture.md](../IAF-Agent-Studio/docs/context_loading_architecture.md) | Platform devs, integration devs | FILE MODE vs TABLE MODE end-to-end flow diagram, downstream storage verified |
| [file_mode_regression.md](../IAF-Agent-Studio/docs/file_mode_regression.md) | Platform devs, operators | Non-interactive P0/P1 file-mode regression runner, isolation model, and automation commands |
| [evidence_viewer.md](../IAF-Agent-Studio/docs/evidence_viewer.md) | Integration devs, platform devs | Enterprise evidence schema, content retrieval API, and source resolution strategy |
| [CRON_SCHEDULER.md](../IAF-Agent-Studio/docs/CRON_SCHEDULER.md) | Operators | Redis-backed cron scheduler: syntax, distributed workers, job monitoring, failure handling |
| [cc_queue.md](../IAF-Agent-Studio/docs/cc_queue.md) | Operators, skill authors | Command Centre queue: HITL approvals, batch job submission, queue draining |
| [CONTRIBUTING.md](../IAF-Agent-Studio/docs/CONTRIBUTING.md) | Platform devs | Studio-specific contribution guidelines — UI conventions, router patterns |

---

### `agent_os/docs/` — SafeKernel internals

| Document | Audience | What's in it |
|----------|----------|-------------|
| [kernel_internals.md](../agent_os/docs/kernel_internals.md) | Platform devs | Sandbox architecture, tool execution pipeline, process isolation |
| [tools_reference.md](../agent_os/docs/tools_reference.md) | Skill authors, platform devs | All built-in tool signatures, return formats, error behaviour |
| [safe_path_design.md](../agent_os/docs/safe_path_design.md) | Platform devs | Virtual path resolution (`/shared/`, `/me/`, `/workspace/`), SafePath.resolve() contract |
| [DEVELOPER_GUIDE.md](../agent_os/docs/DEVELOPER_GUIDE.md) | Platform devs | Adding new SafeKernel tools, extending the sandbox |
| [CONTRIBUTING.md](../agent_os/docs/CONTRIBUTING.md) | Platform devs | agent_os contribution guidelines |

---

## Quick Reference — Most-Used Docs

| I want to… | Go to |
|------------|-------|
| Understand the current architecture | [03_architecture.md](03_architecture.md) |
| Set up locally fast | [02_quick_start.md](02_quick_start.md) |
| Configure env vars and startup behaviour | [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) |
| Add a new skill | [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) Part 1 |
| Write a taxonomy file correctly | [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) Part 1 |
| Add a new business domain to Enterprise_Context.md | [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md) Part 2 |
| Understand why a query routed to the wrong skill | [TAXONOMY_AUTHORING.md](TAXONOMY_AUTHORING.md) + Taxonomy Graph simulator at `/skill-builder/v2` |
| Understand orchestrator vs planned vs react routing | [IAF-Agent-Skills/docs/execution_modes.md](../IAF-Agent-Skills/docs/execution_modes.md) Mode 0 and Mode 5 |
| Author an RLM (reasoning-as-code) skill | [RLM_EXECUTION_MODE.md](RLM_EXECUTION_MODE.md) |
| Build a process graph / use the Graph Studio | [PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md) |
| Design a skill / graph from plain English | [SKILL_DESIGNER.md](SKILL_DESIGNER.md) |
| Run a skill as a recurring operation (Mission Mode) | [MISSION_MODE_GUIDE.md](MISSION_MODE_GUIDE.md), [WORKSTREAMS_AS_RECURRING_OPERATIONS.md](WORKSTREAMS_AS_RECURRING_OPERATIONS.md) |
| Build a no-LLM deterministic pipeline | [DETERMINISTIC_AUTOMATIONS.md](DETERMINISTIC_AUTOMATIONS.md) |
| Export / import skills across environments | [SKILL_PACK_SPEC.md](SKILL_PACK_SPEC.md) |
| Capture traces for eval / SFT / DPO / RFT | [RL_EVAL_CAPTURE.md](RL_EVAL_CAPTURE.md) |
| Run eval suites / golden sets / promotion gates | [PRIVATE_LEARNING_LOOP.md](PRIVATE_LEARNING_LOOP.md) |
| Understand the full capability set | [KEY_FEATURES.md](KEY_FEATURES.md) |
| Write a Python tool | [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) Part 4 |
| Write a pre/post-step hook | [IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md](../IAF-Agent-Skills/docs/HOOK_SYSTEM_DESIGN.md) |
| Add an enterprise provider adapter | [ADAPTER_AUTHORING_GUIDE.md](ADAPTER_AUTHORING_GUIDE.md) |
| Understand composable packaging / kernel-only adoption | [COMPOSABLE_ADOPTION_SPEC.md](COMPOSABLE_ADOPTION_SPEC.md) |
| Understand optional solution modules | [SOLUTION_MODULES.md](SOLUTION_MODULES.md) |
| Understand FILE MODE vs TABLE MODE | [IAF-Agent-Studio/docs/context_loading_architecture.md](../IAF-Agent-Studio/docs/context_loading_architecture.md) |
| Call the agent from my own app | [IAF-Agent-Studio/docs/api_reference.md](../IAF-Agent-Studio/docs/api_reference.md) |
| Set up human approval gates | [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md) |
| Schedule a skill to run on a cron | [IAF-Agent-Studio/docs/CRON_SCHEDULER.md](../IAF-Agent-Studio/docs/CRON_SCHEDULER.md) |
| Run ad-hoc live verification scripts | [scripts/verification/README.md](../scripts/verification/README.md) |
| Understand memory and learning | [IAF-Agent-Skills/docs/memory_schema.md](../IAF-Agent-Skills/docs/memory_schema.md) |
| Know which doc to update after a code change | [CODE_DOC_MAP.yaml](CODE_DOC_MAP.yaml) |
| Verify docs against code (AI agents / reviewers) | [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md) |
| Deploy to production | [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) |

---

## Documentation Maintenance

**Authority:** See [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md) for source-of-truth order, entry-point verification, and known drift areas. Another LLM (or human) fixing the product should start there, then follow the Platform Developer path below and confirm each claim in code/tests.

When you change a source file, check [CODE_DOC_MAP.yaml](CODE_DOC_MAP.yaml) to find which docs need updating. Never leave a doc with stale parameter names, wrong defaults, or missing fields after a code change.

Generated HTML review artifacts belong under [docs/generated/](generated/) and are ignored by git. Ad-hoc verification scripts belong under [scripts/verification/](../scripts/verification/).
