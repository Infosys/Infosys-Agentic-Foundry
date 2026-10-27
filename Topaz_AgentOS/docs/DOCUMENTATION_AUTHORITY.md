# Documentation Authority

> **Docs explain the system. Code and tests define it.**

Markdown in this repo is maintained for humans and AI assistants, but it can drift after refactors, enterprise hardening, or local-only changes. Before trusting a doc — especially for security, scaling, or production decisions — verify the behaviour in source code and tests.

---

## Source-of-truth order

Use this order when docs and code disagree:

1. **Implementation** — Python modules under `IAF-Agent-Studio/`, `IAF-Agent-Skills/`, and `agent_os/`
2. **Tests** — `IAF-Agent-Studio/tests/`, `IAF-Agent-Skills/tests/`, `agent_os/tests/`, and repo-level `tests/`
3. **Configuration** — `IAF-Agent-Studio/shared/config.py`, `IAF-Agent-Skills/config.env`, tenant `config.yaml`
4. **Documentation** — `docs/`, package docs, and `CODE_DOC_MAP.yaml` mappings
5. **Marketing-style summaries** — `KEY_FEATURES.md`, README feature bullets (verify before citing as fact)

If step 1–3 contradict step 4, treat the doc as stale and fix it (or file a doc bug) before relying on it.

---

## Recommended reading path for another LLM

Start here, then trace every claim into code:

| Order | File | Purpose |
|------:|------|---------|
| 1 | [`../AGENTS.md`](../AGENTS.md) or repo-root `AGENTS.md` | Architecture rules, service boundaries, startup commands |
| 2 | [`README.md`](README.md) | Master doc index and persona paths |
| 3 | [`03_architecture.md`](03_architecture.md) | Layered architecture and request lifecycle |
| 4 | [`CODE_DOC_MAP.yaml`](CODE_DOC_MAP.yaml) | Which docs must change when a code file changes |
| 5 | [`../IAF-Agent-Studio/server.py`](../IAF-Agent-Studio/server.py) | HTTP/WebSocket entry points and router registration |
| 6 | [`../IAF-Agent-Studio/shared/config.py`](../IAF-Agent-Studio/shared/config.py) | Runtime env vars and defaults |
| 7 | [`../IAF-Agent-Skills/iaf_agent_skills/agent.py`](../IAF-Agent-Skills/iaf_agent_skills/agent.py) | Agent execution lifecycle |
| 8 | [`../agent_os/kernel.py`](../agent_os/kernel.py) | Tool execution, path sandbox, credentials |
| 9 | [`../IAF-Agent-Studio/docs/api_reference.md`](../IAF-Agent-Studio/docs/api_reference.md) | External REST surface |
| 10 | [`../IAF-Agent-Studio/docs/websocket_protocol.md`](../IAF-Agent-Studio/docs/websocket_protocol.md) | Streaming chat protocol |

For any fix or architecture review: **read the mapped tests for the module you touch** and run the narrowest relevant test file before claiming behaviour is correct.

---

## Entry and exit points (verify in `server.py`)

Docs describe capabilities at a high level. The authoritative external surface is whatever `server.py` registers at startup:

- **UI pages** — `@app.get(...)` routes under `IAF-Agent-Studio/server.py`
- **REST API** — `app.include_router(...)` modules in `IAF-Agent-Studio/routers/`
- **WebSocket** — primarily `routers/chat.py` and workstream routers
- **Background workers** — queue processor, cron scheduler, optional `kernel_worker.py`
- **CLI / verification** — `scripts/verification/`

Always grep `server.py` and `routers/` before assuming an endpoint exists or is named a certain way.

---

## Known areas where docs easily drift

| Topic | Trust code in | Common doc mistake |
|-------|---------------|-------------------|
| Path sandbox / symlinks | `agent_os/kernel.py` (`_resolve_path`), `agent_os/safe_path.py` | Claiming full symlink containment everywhere |
| Skill hot reload | `iaf_agent_skills/loader.py`, `iaf_agent_skills/router.py`, `IAF-Agent-Studio/shared/state.py` | Saying new skills need no restart when `_index.yaml` routing cache is stale |
| Queue backend | `IAF-Agent-Studio/shared/config.py` (`CC_QUEUE_STORAGE_BACKEND`), `cc_queue/` | Calling the Command Center queue "Redis" (default is SQLite; Postgres optional) |
| Kernel execution mode | `agent_os/kernel_runtime.py`, `IAF-Agent-Studio/kernel_worker.py` | Omitting the optional two-process remote kernel worker |
| Sessions / replicas | `iaf_agent_skills/session_store.py`, `shared/runtime_roles.py` | Assuming in-memory sessions work across API replicas |

---

## Skill and config reload — accurate summary

| Change | Typical effect without server restart |
|--------|---------------------------------------|
| Edit an **existing** `SKILL.md` | Picked up on next load — `SkillLoader` invalidates on file mtime |
| Edit **context files** read at runtime | Picked up on next read |
| Add or change **`_index.yaml`** (new skill, keywords, routing) | **Not automatic** for cached `SkillAgent` instances — restart server or evict cached agents; `SkillRouter.reload()` is not called on every filesystem edit |
| Save hooks / some settings via **Studio API** | Often immediate — APIs evict cached agents where implemented |
| Manual on-disk edit outside API paths | Treat as **restart required** unless you confirm eviction/reload in code |

When in doubt, restart `python3 server.py` (and `kernel_worker.py` when `AGENTOS_KERNEL_BACKEND=remote`).

---

## Maintenance rule for contributors and AI agents

When you change behaviour in code:

1. Find the file in [`CODE_DOC_MAP.yaml`](CODE_DOC_MAP.yaml)
2. Update **every** listed doc for that file
3. If the change affects security or reload semantics, update this file and [`03_architecture.md`](03_architecture.md) if applicable
4. Add or adjust a focused test that encodes the new truth

Never close a code change with stale docs when the map already lists the affected files.
