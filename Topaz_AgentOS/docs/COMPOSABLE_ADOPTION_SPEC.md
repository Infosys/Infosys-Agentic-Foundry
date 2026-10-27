# Composable Adoption & "Bring Your Own Component" — Review Spec

> **Status:** Implementation in progress. Sections marked **Exists today** are
> grounded in current code and are safe to rely on. The first composable package
> slices are implemented: `agentos-contracts`, `agentos-kernel`, and the initial
> `agentos-model` model registry/provider surface. `agentos-engine` exists as a
> compatibility facade over `iaf_agent_skills`. Remaining sections marked
> **Proposed** are still target-state design.
>
> **Audience:** architecture + product. This document decides *which* layers of AgentOS
> become independently consumable, *how* customers replace individual components, and
> *what* we commit to support when we say "yes" to partial adoption.
>
> **Quick start for partner teams:** see **[PARTNER_INSTALL_GUIDE.md](PARTNER_INSTALL_GUIDE.md)** (one-page install paths for Kernel / Engine / Full Studio).

---

## 1. Why this document exists

Enterprise customers do not all want the whole platform. Real requests we expect (and
have already heard) look like:

- *"I just want your **kernel** (the secure execution sandbox)."*
- *"I want your **routing + kernel**, but plug in **my own skill registry**."*
- *"I want the engine embedded in **my** service — I have my own UI and my own model gateway."*
- *"Give me the whole certified product."*

Serving these needs **two distinct mechanisms**, and we must be deliberate about both:

| Mechanism | Answers the request… | Current state |
|---|---|---|
| **A. Composable packages** (install/consume one layer) | "I want *just the kernel* / *routing + kernel*" | Partly there — layering is clean-ish, packaging is missing |
| **B. Replaceable component contracts** (swap one part, keep the rest) | "…but *my* skill registry / *my* model / *my* trace sink" | **Already built** — 5 provider seams + injection |

The good news: mechanism **B is largely done**. The work is mostly mechanism **A**
(packaging + dependency isolation) plus lifting the contract types into a stable SDK.

---

## 2. What exists today (grounded in code)

### 2.1 Five replaceable runtime seams — **Exists today**

`iaf_agent_skills/providers/` defines five `@runtime_checkable` Protocols, each with a
default implementation in `iaf_agent_skills/providers_default/`:

| Provider Protocol | Default implementation | Lets a customer supply… |
|---|---|---|
| `SkillProvider` | `FileSystemSkillProvider` | **their own skill registry / source** |
| `RouterProvider` | `DefaultRouterProvider` | their own routing logic |
| `ToolProvider` | `BuiltinToolProvider` | their own tool set |
| `HookProvider` | `DefaultHookProvider` | their own governance/hook runner |
| `TraceProvider` | `DefaultTraceProvider` | their own trace/telemetry sink |

### 2.2 Injection mechanism — **Exists today**

`iaf_agent_skills/providers/factory.py` selects an implementation by config/env using a
`module:Class` import path. Each slot has an env var:

```
SKILL_PROVIDER    = default | filesystem | my_pkg.providers:MySkillProvider
ROUTER_PROVIDER   = default | my_pkg.providers:MyRouterProvider
TOOL_PROVIDER     = default | my_pkg.providers:MyToolProvider
HOOK_PROVIDER     = default | my_pkg.providers:MyHookProvider
TRACE_PROVIDER    = default | my_pkg.providers:MyTraceProvider
```

Set `SKILL_PROVIDER=acme_skills:AcmeSkillProvider` and the router + kernel keep running
unchanged while skills are loaded from the customer's registry. **This is exactly the
"bring your own skill registry" scenario, and it works today.**

### 2.3 Kernel is standalone-clean — **Exists today**

`agent_os` imports only `agent_os.*` in its runtime code. Its own `requirements.txt`
states: *"The kernel core works standalone with just Python stdlib"* and already
anticipates an `agent_os[credentials]` extra (pyyaml/cryptography imported lazily).

### 2.4 What is NOT there yet — **Gaps**

1. **Per-layer packaging is partial.** `iaf_agent_skills` has a `pyproject.toml`, and
   Phase 2 added `agent_os/pyproject.toml` for the `agentos-kernel` distribution.
   `IAF-Agent-Studio` still ships as the full-product app/source tree.
2. **No dependency isolation (extras), and `langgraph` is wrongly mandatory.**
   `agent.py:29` does a **top-level** `from langgraph.prebuilt import create_react_agent`,
   so importing the engine fails without langgraph installed — even though the **native**
   react runtime (`react_runtime/native.py`) does not use langgraph at all (it uses
   `langchain_core` messages + `llm.bind_tools()`). Reality: `langchain-core` and
   `langchain-openai` are mandatory for **both** runtimes (native included), but `langgraph`
   is only needed for the `react_runtime: langgraph` path. The top-level import must be made
   lazy (moved into the langgraph branch) and the default runtime set to native so
   `langgraph` can become an optional `[langgraph]` extra. Summary: the engine is
   "LangChain-based, LangGraph-optional", not "no LangChain".
3. **Upward Studio-layer leaks — now closed.** `providers/factory.py::_setting()` no
   longer imports `from shared import config`; it falls back to host-registered
   provider config via `iaf_agent_skills.runtime_bridge.get_provider_setting()`. The
   former lazy `shared.*` / `routers.*` engine imports (mission mode, evidence,
   default trace provider) have been replaced by the runtime bridge + host-service
   contracts, so the engine no longer imports any Studio module. See
   [PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md).
4. **Contract types live inside the engine.** `SkillProvider.load()` returns
   `iaf_agent_skills.loader.Skill` — a concrete engine class. A clean SDK must expose the
   descriptor type independently so extenders don't import engine internals.

---

## 3. Proposed package / SKU taxonomy — **Proposed**

Strict **downward-only** dependencies. An arrow may only point down; CI enforces it.

```
                        agentos-studio  (full product; the certified bundle)
                               │
        ┌──────────────────────┼───────────────────────┐
        ▼                      ▼                        ▼
  agentos-engine        agentos-capture          partner-adapters
  (skills, router,      (rl_capture)             (vault/model/SIEM/SSO
   planner, memory,           │                   implementations)
   hooks, exec modes)         │                        │
      │      │                │                        │
      ▼      ▼                │                        │
 agentos-  agentos-model      │                        │
  kernel   (ModelRegistry,    │                        │
 (SafeKernel) pipeline,       │                        │
      │      FinOps tokens)   │                        │
      └──────┬────────────────┴────────────────────────┘
             ▼
       agentos-contracts   (Protocols + descriptor types ONLY, no logic)
```

### 3.1 The consumer-facing SKUs

We do **not** productize all layers at once. We define SKUs and only *support* the ones
customers actually buy.

| SKU | Package(s) | Primary buyer | Support tier |
|---|---|---|---|
| **Full Platform** | `agentos-studio` (bundles all) | Enterprises wanting the product | **Tier 1** — full support, one version number |
| **Embeddable Engine** | `agentos-engine` (+kernel, model, contracts) | Teams embedding in their own backend | **Tier 2** — contract-level support |
| **Secure Kernel** | `agentos-kernel` | Teams needing just the sandbox | **Tier 2** — contract-level support |
| **Extension SDK** | `agentos-contracts` (+ examples) | Anyone replacing a component | **Tier 1** — stable, semver, long support |

> **Rule:** a new *supported* layer is unlocked by a real signed opportunity, not by
> completeness. Architecturally we allow it; commercially we support what is paid for.

---

## 4. `agentos-contracts` — the Extension SDK surface — **Partly implemented**

A tiny package with **no runtime logic**, depended on by every layer. Phase 1 has
created this package at `IAF-Agent-Skills/agentos_contracts/` so it is importable
from the same `IAF-Agent-Skills/` path the current server and tests already use,
while still being independently installable later as `agentos-contracts`.

### 4.1 The five provider Protocols

Now exported from `agentos_contracts`: `SkillProvider`, `RouterProvider`,
`ToolProvider`, `HookProvider`, `TraceProvider`. The historical
`iaf_agent_skills.providers.*` modules remain compatibility shims.

### 4.2 The descriptor types the Protocols reference

The `Skill` dataclass now lives in `agentos_contracts.Skill` so extenders code
against a stable type, not the engine's loader. Its public shape (frozen as SDK
contract):

```
Skill(
  name, version, description,
  files, knowledge, user_data,
  mcp_tools, mcp_connections, tools,
  business_context, approval_rules, evidence_highlights,
  sql_mode, execution_mode, react_runtime,
  steps, worker_skills, max_steps,
  body, path,
)
```

The engine re-exports `Skill` from contracts for backward compatibility, so
existing imports from `iaf_agent_skills.loader.Skill` and
`iaf_agent_skills.Skill` continue to work.

### 4.3 React runtime selector

`resolve_react_runtime`, `ReactRuntimeSelection`, `VALID_REACT_RUNTIMES`, and
`DEFAULT_REACT_RUNTIME` are also exported from `agentos_contracts`. The default
remains `langgraph`; `native` remains opt-in.

### 4.4 The injection convention

The `module:Class` import-path convention (Section 2.2) is documented here as the
official, supported extension mechanism, with the five env vars.

---

## 5. Customer scenarios mapped to the target — **Proposed**

### Scenario A — "I just want your kernel"
```
pip install agentos-kernel            # stdlib-only core
pip install agentos-kernel[credentials]   # + pyyaml/cryptography for the file/Fernet cred store
```
They get `SafeKernel`, `SafePath`, rate limiting, file locking, scoped credential store,
and external-access gates. No LLM, no web server, no Redis.

### Scenario B — "Routing + kernel, but MY skill registry"
```
pip install agentos-engine[routing]   # pulls agentos-kernel + agentos-model + contracts,
                                       # NOT memory/queue/mission extras
```
```python
# acme_skills.py
from agentos_contracts import SkillProvider, Skill

class AcmeSkillProvider:                 # structurally satisfies SkillProvider
    skills_path = ...
    def load(self, name) -> Skill: ...   # read from Acme's registry / DB / service
    def get_prompt(self, skill, include_files=True) -> str: ...
    # ...remaining methods
```
```
SKILL_PROVIDER=acme_skills:AcmeSkillProvider
```
Your `DefaultRouterProvider` + kernel + planner run unchanged; skills come from Acme's
registry. **This is the direct answer to the requirement that prompted this spec.**

### Scenario C — "Embed the engine, my UI, my model gateway"
```
pip install agentos-engine
```
```
MODEL_PROVIDER=...            # point ModelRegistry at their OpenAI-compatible gateway
TRACE_PROVIDER=acme:AcmeTrace # their telemetry sink
```
They call `SkillAgent.run(...)` from their own service.

### Scenario D — "The whole product"
```
# container image + Helm chart (see DEPLOYMENT strategy)
```
Full Studio, UI, queue, cron, security console, dashboards, tenancy.

---

## 6. Dependency isolation (extras) — **Proposed**

Each package declares optional extras so a buyer installs only what they use.

| Package | Base deps | Extras |
|---|---|---|
| `agentos-kernel` | stdlib only | `[credentials]` → pyyaml, cryptography; `[self-auth]` → python-jose[cryptography] for service JWT minting |
| `agentos-model` | contracts, `langchain-core`, `langchain-openai` | implemented for ModelRegistry, ModelProviderAdapter, provider chat adapters, reasoning metadata |
| `agentos-engine` | facade over `iaf_agent_skills` plus contracts/kernel/model deps | implemented as compatibility facade; future work can physically move internals behind this import surface |
| `agentos-contracts` | none | — |
| `agentos-studio` | everything | — (it is the bundle) |

**Constraint:** no base package may hard-require Redis or FastAPI. Those belong to
`agentos-studio` only. Any engine feature needing them must fail soft or sit behind an
extra.

---

## 7. Remaining engineering work — **Proposed**

Bounded and mostly mechanical (no behavior change):

1. **Package the layers customers ask for first:** `agentos-kernel` now has
   package metadata. `agentos-model` owns `ModelRegistry`, model provider
   adapter, provider chat adapters, and reasoning metadata. `agentos-engine`
   exists as a compatibility facade over `iaf_agent_skills`; future work can
   physically move internals behind that facade when customer demand justifies
   the migration cost.
2. **Create `agentos-contracts`** and move the five Protocols + `Skill` descriptor into it;
   re-export from the engine for compatibility.
3. **Add dependency extras** per Section 6; ensure `[routing]` does not pull the full stack.
   As part of this, **make the `langgraph` import lazy** (move `agent.py:29`'s
   `from langgraph.prebuilt import create_react_agent` into the langgraph-runtime branch)
   and default `react_runtime` to native, so `langgraph` becomes an optional `[langgraph]`
   extra. Keep `langchain-core`/`langchain-openai` as base deps (native uses them).
4. **Upward leaks closed (done):** `factory` resolves config through the engine
   runtime bridge (`get_provider_setting`) instead of importing `shared.config`, and the
   remaining `shared.*`/`routers.*` lazy engine imports now route through the
   host-service runtime bridge.
5. **Add an import-linter "layers" contract** in CI so the downward-only rule cannot rot.
6. **Publish the injection recipe** in `ADAPTER_AUTHORING_GUIDE.md` ("Replace a component").

---

## 8. Versioning & compatibility policy — **Proposed**

- **SemVer per package.** Breaking a Protocol method = major bump.
- **`agentos-contracts` is the slowest-moving package** and carries the longest support
  window; extenders depend on it, so stability here is the whole promise.
- **Published, CI-tested compatibility matrix**: which `engine` works with which
  `kernel`/`model`/`contracts`. Customers get a supported combination, not a free-for-all.
- **One certified bundle version** for the Full Platform SKU, even though it is internally
  layered — this is what avoids the version-matrix support trap.

---

## 9. Extension trust & security boundary — **Proposed (required for multi-tenant)**

Because customer devs *and* external partners will write providers/adapters, extension
code is an untrusted-code + supply-chain concern (the gap Pi explicitly leaves to the
user). AgentOS must route extensions through boundaries it already has:

- Extension-supplied providers declare capabilities; the platform grants only what
  entitlements allow.
- Secrets are never handed to extension code directly — the `SecretProvider` masking path
  (`$CRED_*` placeholders) stays authoritative.
- Partner-distributed adapters are signed / reviewed before load in multi-tenant SaaS.
- Provider `health()` / `snapshot()` outputs are bounded and redacted (already required by
  the current Protocols).

---

## 10. Open decisions for reviewers

1. **Delivery unit** (blocks everything): confirm container image + Helm chart as the
   primary artifact, with all-in-one and split-services modes via config. *(Recommended.)*
2. **First productized layers:** confirm `agentos-kernel` and `agentos-engine[routing]`
   as the first two supported à-la-carte SKUs (driven by current demand).
3. **Contracts ownership:** who owns `agentos-contracts` stability and its support window?
4. **Trust model for partner extensions:** signing? review gate? sandboxed vs in-process?
5. **Pricing/support tiers** per SKU — a product decision, not covered here.

---

## 11. Capability → Package / SKU matrix — **Proposed**

Package legend (proposed pip names):

- **K** = `agentos-kernel` (today: `agent_os`)
- **M** = `agentos-model` (today: ModelRegistry, model provider adapter, provider chat adapters, and reasoning metadata extracted; model-call hook pipeline remains inside `iaf_agent_skills`)
- **C** = `agentos-contracts` (implemented — Protocols + `Skill` descriptor)
- **E** = `agentos-engine` (today: `iaf_agent_skills` core)
- **CAP** = `agentos-capture` (today: `rl_capture`)
- **S** = `agentos-studio` (today: `IAF-Agent-Studio` — server, routers, UI, auth, security, queue, emitters)

Dependency direction (downward only): `C` ← `K`, `M` ← `C`; `E` ← `K,M,C`; `CAP` ← `C(+E adapter)`; `S` ← all.

> **"Split" means** the *mechanism* ships in one package but the *UI / storage / enforcement
> service* ships in another (usually Studio). Engine-only buyers get the mechanism and must
> bring their own surface, or add Studio.

| # | Capability (from architecture reference) | Owning module today | Package | In SKU | Split? |
|---|---|---|---|---|---|
| 1 | Chat WebSocket / REST ingress / Queue bus | `IAF-Agent-Studio` (server, routers, cc_queue) | **S** | Full | — |
| 1 | Cron scheduler **engine** (Redis job store) | `iaf_agent_skills/scheduler` | **E** | Engine, Full | Cron *ingress/UI* is S |
| 1 | Workstream / Mission Mode **engine** | `iaf_agent_skills/mission_engine` | **E** | Engine, Full | Ingress + backlog UI is S |
| 2 | Skill Router (entity/taxonomy/keyword/LLM routing) | `iaf_agent_skills/router.py` | **E** | Engine, Full | — |
| 2 | ContextOS (context slicing, taxonomy index) | `iaf_agent_skills` (loader, taxonomy_signal_index) | **E** | Engine, Full | — |
| 3 | SkillAgent + engine dispatch (workflow/parallel/supervisor/orchestrator/planned) | `iaf_agent_skills/agent.py`, `execution.py` | **E** | Engine, Full | — |
| 3 | ReAct loop + Planner (create_plan/invoke_plan/invoke_skill) | `iaf_agent_skills/agent.py`, `planner.py` | **E** | Engine, Full | — |
| 3 | Tool governance (PreToolUse firewall) | `iaf_agent_skills/tool_governance.py` | **E** | Engine, Full | — |
| 3 | Capability adapters (Credential/Evidence/Memory/Model/Taxonomy/Tool) | `iaf_agent_skills/*_adapter.py`, `providers/` | **E** (contracts in **C**) | Engine, Full | Evidence *storage* is S |
| 3 | Model registry + policy/redaction pipeline | `iaf_agent_skills/model_*` | **M** | Engine, Full | — |
| 4 | SafeKernel VFS + RBAC + Python commands + ripgrep | `agent_os/kernel.py` | **K** | Kernel, Engine, Full | — |
| 4 | Credential vault ($CRED_ substitution) | `agent_os/credential_store.py`, `secret_provider.py` | **K** | Kernel, Engine, Full | — |
| 4 | External-access governance (curl/SQL gates + audit) | `agent_os/external_access.py` | **K** | Kernel, Engine, Full | — |
| 5 | Hook harness (runner + platform hooks + trust control plane) | `iaf_agent_skills/hook_runner.py`, `platform_hooks/` | **E** | Engine, Full | Hook-authoring UI + Policy Registry is S |
| 6 | HITL **interception** (pending_tool_call, hold state) | `iaf_agent_skills/agent.py`, `tool_governance.py` | **E** | Engine, Full | Approval store + resume API + UI is S |
| 6 | HITL approval store (Redis) + durable resume + UI | `IAF-Agent-Studio` (routers/approvals, approval store) | **S** | Full | — |
| 7 | Episodic + semantic memory, implicit learning, knowledge CRUD, plan memory | `iaf_agent_skills/memory.py`, learning, knowledge | **E** | Engine, Full | Knowledge-review UI is S |
| 7 | VectorStore (semantic search backend) | `agent_os` (VectorStore) | **K** | Kernel, Engine, Full | — |
| 8 | Self-evolution engine (session analysis, skill-gap) | `iaf_agent_skills/self_evolution.py` | **E** | Engine, Full | Skill Builder / promote UI is S |
| 9 | Traces (traces.db) + FinOps API + dashboards | `IAF-Agent-Studio` (trace_emitter, routers/finops) | **S** | Full | Token usage *produced* by M/E |
| 9 | Evidence bundles (evidence.db) + viewer | `IAF-Agent-Studio` (evidence sinks); collector in E | **S** | Full | Collection mechanism in E |
| 9 | Kernel command audit + external-access audit | `agent_os` (.audit, external_access_audit) | **K** | Kernel, Engine, Full | — |
| 9 | RL / eval capture + export | `rl_capture` | **CAP** | Capture, Full | — |
| 10 | Redis session persistence (horizontal scale) | `iaf_agent_skills/session_store.py` + Redis infra | **E** (code) | Engine, Full | Needs Redis (deploy); wired by S |
| 10 | SQLite tenant DBs (traces/evidence/twin/business) | `IAF-Agent-Studio` emitters + `enterprise_root` data | **S** + data | Full | — |
| 11 | JWT auth + request entitlements + Security Console | `IAF-Agent-Studio` (auth/, security/) | **S** | Full | Kernel enforces file/cmd/cred/external gates |
| 11 | SafeKernel RBAC + hard-deny + injection blocking | `agent_os/kernel.py` | **K** | Kernel, Engine, Full | — |

## 12. SKU capability bundles (what each `pip install` unlocks) — **Proposed**

**`pip install agentos-kernel` (+contracts)** → *Secure Kernel SKU*
- Sandboxed VFS, RBAC per path op, Python-reimplemented commands + ripgrep
- Credential vault with `$CRED_` substitution (real secrets never in LLM context)
- External-access governance (curl/SQL entitlement gates) + kernel & external-access audit
- VectorStore semantic search backend
- **Not included:** any LLM, routing, agent loop, hooks, memory, UI, HITL surface.

**`pip install agentos-engine[...]` (+kernel, model, contracts)** → *Embeddable Engine SKU*
- Everything in Kernel, **plus**: Skill Router + ContextOS, all execution modes, ReAct loop + Planner, tool-governance firewall, **hook harness + platform hooks**, memory & learning, self-evolution engine, model registry + policy/redaction pipeline, cron scheduler engine, mission-mode engine, HITL **interception mechanism**, capability adapters (bring-your-own via `SKILL_PROVIDER` etc.)
- `[routing]` extra = router + kernel only (no memory/queue/mission)
- **Not included (needs Studio):** web UI, chat WS / REST ingress, HITL approval store + resume API + UI, traces.db/evidence.db storage + FinOps API + dashboards, JWT auth + entitlement enforcement service + Security Console, Redis wiring.

**`pip install agentos-capture` (+contracts, +engine adapter)** → *Capture SKU*
- Neutral RL/eval trajectory + reward + preference capture; SFT/DPO/KTO/RFT/eval exporters; PII redaction gate.

**Full Platform (container + Helm; bundles all)** → *Full Platform SKU*
- Everything above **plus** all ingress paths, HITL UI + durable approval store, full observability (traces/evidence/FinOps/dashboards), JWT auth + entitlements + Security Console, multi-tenant isolation, Redis session persistence, all Studio UIs.

## 13. Mapping to the customer scenarios (Section 5)

| Scenario | `pip install` | Capabilities they get | Capabilities they must bring / add Studio for |
|---|---|---|---|
| **A. "Just your kernel"** | `agentos-kernel` | Sandbox, RBAC, credential vault, external-access gates, audit | Everything agentic (LLM, routing, hooks, HITL, UI) |
| **B. "Routing + kernel, my registry"** | `agentos-engine[routing]` + `SKILL_PROVIDER=my:Provider` | Router, ContextOS, kernel, model, tool governance | Memory/queue/mission (other extras), HITL UI, observability, auth |
| **C. "Embed engine, my UI + model gateway"** | `agentos-engine` + `MODEL_PROVIDER`/`TRACE_PROVIDER` | Full agent core, hooks, memory, planner, HITL interception | HITL approval surface, trace/FinOps storage, ingress, auth (or provide own) |
| **D. "Whole product"** | container + Helm | All 12 sections end-to-end | — |

## 14. One-line summary

The replaceable-component contracts customers need (**"bring your own skill registry"**)
**already exist** as five injectable provider Protocols; the remaining work is
**packaging + dependency extras + lifting contract types into a stable SDK + closing two
import leaks** — a bounded, demand-driven effort, delivered as a certified bundle plus a
small set of separately-versioned, contract-supported layers.
