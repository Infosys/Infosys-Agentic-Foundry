# Partner Install Guide

One-page reference for teams adopting AgentOS layers without the full Studio product.

**Distribution today:** clone the repo and use **editable installs** (`pip install -e`). Packages are metadata-ready (`agentos-kernel`, `agentos-contracts`, `agentos-model`, `agentos-engine`, `iaf-agent-skills`) but are **not yet published to PyPI**. Use an internal artifact registry when your org publishes them.

**Architecture rule:** dependencies flow **downward only** — Studio → Engine → Kernel → Contracts. The engine never imports Studio. Your host app registers services through `iaf_agent_skills.runtime_bridge`.

---

## Choose your SKU

| SKU | Who it's for | You get | You bring |
|---|---|---|---|
| **A — Secure Kernel** | Platform / security teams | `SafeKernel`, sandboxed paths, command gates, credential store | Your own agent loop, LLM, UI |
| **B — Embeddable Engine** | Backend teams embedding agents | SKU A + skill routing, `SkillAgent`, hooks, memory, providers | Your UI, auth, trace store, evidence DB (optional) |
| **C — Full Platform** | Product / ops teams | SKU B + Studio server, dashboards, queue, cron, RL capture, auth | LLM keys, Redis, deployment config |

---

## SKU A — Secure Kernel only

**Python:** 3.11+ (3.13 recommended)

```bash
git clone https://github.com/Infosys-Generative-AI/IAF_AgentOS.git
cd IAF_AgentOS   # or your harness root (e.g. IAF_AgentOS_Harness_latest)

pip install -e agent_os/
# Optional credential store (YAML + Fernet):
pip install -e "agent_os/[credentials]"
```

**Verify:**

```bash
python3 -c "from agent_os import SafeKernel; print('kernel OK', SafeKernel)"
```

**Docs:** `agent_os/README.md`, `agent_os/docs/DEVELOPER_GUIDE.md`

---

## SKU B — Embed the engine (no Studio)

Install kernel + engine and their runtime dependencies:

```bash
git clone https://github.com/Infosys-Generative-AI/IAF_AgentOS.git
cd IAF_AgentOS

pip install -r IAF-Agent-Skills/requirements.txt
pip install -e agent_os/
pip install -e IAF-Agent-Skills/
```

Copy and configure LLM credentials:

```bash
cp IAF-Agent-Skills/config.env.example IAF-Agent-Skills/config.env
# Edit: Azure OpenAI, OpenAI-compatible, or Vertex — see docs/DEPLOYMENT_GUIDE.md
```

**Minimal embed (standalone — no host bridge required):**

```python
from agent_os import SafeKernel
from iaf_agent_skills import SkillAgent

kernel = SafeKernel(workspace="/path/to/workspace", user_id="partner-user")
agent = SkillAgent(
    kernel=kernel,
    skills_path="/path/to/skills",
    user_id="partner-user",
    enterprise_root="/path/to/enterprise_root",
)
result = agent.run("Hello", skill_name="your_skill")
```

Without a registered host bridge, evidence/mission features **degrade gracefully** (no-op or built-in defaults). Trace emitter is optional.

**Register your own host services** (recommended for production embeds):

Implement `agentos_contracts.EvidenceSink` and/or `MissionRuntimeBridge`, then register at process startup **before** running agents:

```python
from iaf_agent_skills.runtime_bridge import (
    register_cost_function,
    register_default_identity,
    register_evidence_sink,
    register_mission_bridge,
    register_provider_config,
    register_trace_emitter_factory,
)

register_default_identity(tenant_id="acme", agent_id="acme_agent")
register_provider_config({"SKILL_PROVIDER": "default", "TRACE_PROVIDER": "default"})
register_evidence_sink(MyEvidenceSink())      # optional
register_mission_bridge(MyMissionBridge())    # optional if using Mission Mode
register_trace_emitter_factory(lambda: my_emitter)  # optional
register_cost_function(my_cost_fn)            # optional
```

Studio's reference implementation lives in `IAF-Agent-Studio/shared/engine_bridge.py`.

**Replace components via providers** (no fork required):

```bash
export SKILL_PROVIDER=acme.adapters:AcmeSkillProvider
export TOOL_PROVIDER=default
export TRACE_PROVIDER=acme.adapters:AcmeTraceProvider
```

Provider contracts: `IAF-Agent-Skills/agentos_contracts/`. Full seam reference: `docs/PROVIDER_ARCHITECTURE.md`.

**Verify boundary (engine must not need Studio on path):**

```bash
PYTHONPATH="agent_os:IAF-Agent-Skills" python3 -c \
  "import iaf_agent_skills.agent; print('engine OK without Studio')"
```

**Docs:** `docs/PROVIDER_ARCHITECTURE.md`, `docs/COMPOSABLE_ADOPTION_SPEC.md`, `docs/CONFIG_REFERENCE.md`

---

## SKU C — Full AgentPro platform (Studio)

Everything in SKU B, plus the web host:

```bash
git clone https://github.com/Infosys-Generative-AI/IAF_AgentOS.git
cd IAF_AgentOS

pip install -r IAF-Agent-Skills/requirements.txt
pip install -r IAF-Agent-Studio/requirements.txt
pip install -e agent_os/
pip install -e IAF-Agent-Skills/

cp IAF-Agent-Skills/config.env.example IAF-Agent-Skills/config.env
# Edit LLM credentials

cd IAF-Agent-Studio
python3 server.py
```

Open **http://localhost:8080** (or `PORT=8081 python3 server.py`).

**Also required for full product:** Redis (`REDIS_URL`, default `redis://localhost:6379`), tenant data under `enterprise_root/tenants/<tenant>/`.

Studio registers all host bridge services automatically via `shared/config.py` → `shared/engine_bridge.py`.

**Docs:** `README.md`, `docs/DEPLOYMENT_GUIDE.md`, `docs/AGENTPRO_SETUP.md`

---

## Package map

| Pip name (target) | Repo path | Import surface |
|---|---|---|
| `agentos-kernel` | `agent_os/` | `from agent_os import SafeKernel` |
| `agentos-contracts` | `IAF-Agent-Skills/agentos_contracts/` | `from agentos_contracts import EvidenceSink, …` |
| `agentos-model` | `IAF-Agent-Skills/agentos_model/` | `from agentos_model import ModelRegistry, …` |
| `iaf-agent-skills` | `IAF-Agent-Skills/` (`iaf_agent_skills/`) | `from iaf_agent_skills import SkillAgent` |
| `agentos-engine` | `IAF-Agent-Skills/agentos_engine/` | Facade re-export (compatibility) |
| *(application)* | `IAF-Agent-Studio/` | Run `server.py` — not a pip library |

---

## What is not included per SKU

| Capability | SKU A | SKU B | SKU C |
|---|---|---|---|
| LLM / model gateway | — | You configure | You configure |
| Web UI / dashboards | — | — | Studio |
| Redis sessions / queue | — | Optional extra | Built-in |
| Auth / entitlements | — | You implement | Studio |
| Mission Mode HITL UI | — | Register bridge or skip | Studio |
| RL capture / training traces UI | — | — | Studio (`/rl-capture`) |

---

## Support expectations

- **SKU A & B:** Supported via `agentos_contracts` Protocols and provider env vars. Breaking a Protocol method is a **major** version bump.
- **SKU C:** Certified full-product bundle — use pinned `requirements.txt` versions from the repo.
- **PyPI one-liners** (`pip install agentos-kernel`): planned; use git clone + editable install until your org publishes packages.

**Questions / adapters:** `docs/COMPOSABLE_ADOPTION_SPEC.md` (strategy), `docs/PROVIDER_ARCHITECTURE.md` (runtime seams), `docs/ADAPTER_AUTHORING_GUIDE.md` (enterprise adapters).
