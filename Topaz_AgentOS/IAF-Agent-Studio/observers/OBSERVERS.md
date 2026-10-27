# Observers — Headlong companion agents + console (feature map)

> **What this is:** a subsystem that runs **Headlong** (an open-source persistent-agent
> microharness) as scoped "observer" agents that *watch* a source (folder/DB/API),
> *detect* patterns, and request **governed** AgentOS skill actions through the existing
> HITL approval machinery — with a workstream-styled **console UI** to design, operate,
> chat with, and approve them.
>
> **Where it lives:** `IAF_AgentOS_Harness_rlm/IAF-Agent-Studio` (this tree). The Headlong
> runtime lives at `~/headlong` (identities under `~/headlong/.identities/<name>`).
>
> **One-line model:** perception loop (watch → detect → escalate) that feeds the shared
> HITL/approval + trace surface. Observers are **not** workstreams (missions); they reuse
> the governance layer, not the mission model.

---

## Quick start / how to run + test

```bash
# Start AgentOS (RLM clone) with observers ENABLED, on :8082
OBSERVERS_ENABLED=true OBSERVERS_API_KEY=obs-test-key-123 bash ~/agentos_rlm.sh

# Console UI (workstream-styled, light theme):
#   http://localhost:8082/observers            (fleet list)
#   http://localhost:8082/observers/{name}     (detail: Runtime + Configure)
# Also linked from /dashboard/v2 and /skill-builder/v2 (Operate group).
# Login: admin@iaf.local / <IAF_ADMIN_PASSWORD>

# End-to-end smoke test (creates an observer approval, approves, prints outcome):
~/test_observer_hitl.sh auto

# Unit tests (pure engines):
PYTHONPATH=IAF-Agent-Studio /usr/local/bin/python3 -m pytest IAF-Agent-Studio/observers/tests/ -q
```

Feature flags (in `shared/config.py`): `OBSERVERS_ENABLED`, `OBSERVERS_API_KEY`,
`OBSERVERS_RUNTIME` (dev|container), `HEADLONG_APP_DIR` (default `~/headlong`).

---

## Programs / files

### Backend package — `IAF-Agent-Studio/observers/`
| File | Role |
|---|---|
| `models.py` | Pydantic contracts: `ObserverSpec`, `WatchScope`, `TriggerRule`, `TrustTier`, `ActRequest/ActResponse`. |
| `policy.py` | Pure trust-tier gate (observe_only / recommend / auto_act / supervised + allowlist). |
| `triggers.py` | Pure deterministic `TriggerEngine` (threshold + pattern rules, cooldown, template rendering). |
| `store.py` | `ObserverStore(ABC)` → `YamlObserverStore` (reads `spec/*.yaml`), `save_spec`/`delete_spec`, `get_observer_store()`. |
| `service.py` | `ObserverService` — the **only write path**: policy gate → run skill via lane queue **or** create a gateway HITL approval; `resolve()` runs the deferred skill on approve. |
| `runtime.py` | `ObserverRuntime(ABC)` → `DevRuntime` / `ContainerRuntime`. Compiles a spec → Headlong identity; real `start()/stop()` (spawns `thinkers` + sidecar), `status()`, trajectory helpers, `_headlong_shell`, `chat/.chatrc` provisioning. |
| `sidecar.py` | Out-of-process deterministic detector: tails the identity's `trajectory.jsonl`, matches triggers, POSTs to the gateway. Run: `python -m observers.sidecar <name>`. |
| `headlong_skills/agentos_act/` | The Headlong **skill** (`SKILL.md` + `agentos_act` bash) the mind calls to request a governed action (POSTs to `/api/observers/act` with `X-API-Key`; builds JSON with `jq`). |
| `spec/*.yaml` | Sample/observer definitions: `ap-watch`, `ap-monitor`, `guide-watch`, `hitl-demo`, `watch-lite`. |
| `tests/test_policy.py`, `tests/test_triggers.py` | Unit tests for the pure engines (14 tests). |

### HTTP + UI
| File | Role |
|---|---|
| `routers/observers.py` | All `/api/observers*` endpoints + `WS /ws/observers/{name}` (see API below). |
| `static/bp_observers.html` | Console **list** page (KPI tiles, filters, needs-attention list, observer cards). |
| `static/bp_observer_detail.html` | Console **detail** page (KPIs, narrative, next-best-actions, **live WS stream**, detections **workbench** [Overview/Evidence/Execution Trace/Actions/Ask], right-rail "Ask this observer", Configure tab). |

### Modified integration files
| File | Change |
|---|---|
| `server.py` | `include_router(observers_router.router)`; page routes `@app.get("/observers")` + `/observers/{name}`. |
| `shared/config.py` | `OBSERVERS_ENABLED/API_KEY/RUNTIME`, `HEADLONG_APP_DIR`. |
| `auth/middleware.py` | `/api/observers/act` + `/observers/` in public lists; `/observers` in `_PUBLIC_EXACT`. |
| `routers/approvals.py` | **Quick-Win-A**: `_annotate_outcome_sync` in the HITL resume; `/api/hitl/history` enriched with outcome. |
| `../IAF-Agent-Skills/iaf_agent_skills/approval_store.py` | **Quick-Win-A**: outcome fields on `ApprovalRequest` (`execution_status`, `result_summary`, `trace_id`, …) + `annotate_outcome()`. |
| `static/dashboard_v2.html`, `static/skill-builder-v2.html` | Nav links to `/observers` (Operate group). |

### Headlong runtime (separate from this tree)
- Install: `~/headlong` (Apache-2.0). Identities: `~/headlong/.identities/<name>/` (e.g. `ap-watch`).
- Patched CLI: `~/.local/bin/llm` (added an **Azure OpenAI** branch so the mind can run on `gpt-5-nano`). `~/.local/bin/agentos_act` symlink.

---

## API (all under `/api/observers`, JWT unless noted)

| Method / path | Purpose |
|---|---|
| `GET  /api/observers` | list specs |
| `GET/POST/PUT/DELETE /api/observers[/{name}]` | spec CRUD (admin) |
| `GET  /api/observers/{name}/status` | running state + last activity |
| `POST /api/observers/{name}/start` \| `/stop` | lifecycle (spawn/stop mind + sidecar) |
| `GET  /api/observers/{name}/trajectory?limit=N` | tail live trajectory steps |
| `GET  /api/observers/{name}/detections` | detections view (source=observer approvals + outcomes/trace) |
| `GET  /api/observers/{name}/metrics` | detection/approval KPIs |
| `WS   /ws/observers/{name}` | live trajectory stream (SEC-6: authenticated via the httponly `iaf_access_token` cookie sent automatically on the WS upgrade; `?token=…` still accepted as a fallback) |
| `POST /api/observers/act` | **the governed write path** — `X-API-Key` (public prefix) |
| `POST /api/observers/approvals/{id}/resolve` | approve/reject → runs deferred skill |
| `POST /api/observers/{name}/detections/{id}/chat` | per-detection chat (reuses `routers.chat.chat_endpoint`) |
| `POST /api/observers/{name}/chat` | observer copilot (`mode=copilot`) or talk-to-the-mind (`mode=mind`) |

**Reused (not observer-owned):** `/api/hitl/*` (approvals), `/api/traces/{id}` (Execution Trace),
`routers.chat.chat_endpoint` (chat), Headlong `bin/chat` (mind chat).

---

## Design docs (plans)
`~/.claude/plans/`: `observer-subsystem-plan.md`, `hitl-outcome-quickwin-A.md`,
`observers-console-build.md`, `unified-approvals-console-northstar.md`.

## Notes for another agent
- The subsystem is **feature-flagged**: if `OBSERVERS_ENABLED` is false, `/api/observers*`
  returns 404 and the console is empty — that's why it may look "missing." Set the flag.
- Search anchors: the package dir `observers/`, `routers/observers.py`, the string
  `source="observer"` in `approval_store`/`service.py`, and `/api/observers` in the router.
- Container mode (read-only mount fence + `--network none`) is implemented in
  `runtime.py` but **not yet tested on Docker** (dev mode runs unsandboxed with a warning).
