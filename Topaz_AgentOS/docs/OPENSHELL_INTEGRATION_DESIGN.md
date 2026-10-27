# OpenShell integration + security hardening (Steps 0 / 1a / 1b)

> Status: **Steps 0, 1a and 1b are implemented and verified** (2026-09-30). Step 2
> (routing all egress through the sandbox gateway) remains designed-not-built.
> Companion reading: `SECURITY_DEVELOPER_GUIDE.md` (defense-in-depth model, hard
> gates, secrets) and `PROVIDER_ARCHITECTURE.md` (why the kernel backend is
> deployment config, not a provider slot).

## Why this exists

We evaluated NVIDIA OpenShell (Apache-2.0, 0.1.x — kernel-enforced sandboxes,
policy-checked egress, endpoint-bound credential injection, formally-verified
policy changes) as an optional isolation backend. Before designing anything we
red-teamed our own surfaces and found this deployment was in the most dangerous
configuration the codebase supports — and that several of the worst findings were
our own logic bugs that OpenShell could never fix. So the work split into:
close our bugs (Steps 0 + 1b), and add the durable boundary as an option (Step 1a).

---

## Part 1 — What the review found (all reproduced empirically)

### 1A — Critical: prompt-injection → full host compromise (CLOSED by Step 0)

`AGENT_PYTHON3_ENABLED=true` with an empty `AGENT_PYTHON3_SANDBOX_USER`, and
neither `ENTERPRISE_STRICT_MODE` nor `AGENTOS_UNTRUSTED_EXECUTION_GUARD` set.
Every designed mitigation was simultaneously inert:

| Link | Evidence |
|---|---|
| 39 skills declare `shell` → all reach `python3`; only 10 covered by the allow-list hook | `agent_os/kernel.py` python3 fast path; agent `config.yaml` hook block |
| **No approval gate** — the python3 fast path returns before `_parse_command`, `BLOCKED_COMMANDS` and `_requires_confirmation` | `agent_os/kernel.py` `_execute` fast path |
| **AST denylist is a 2-line bypass** — the blocked-call check string-matches the identifier `"os"`, so `from os import system` / `import os as _o` pass. `open`, `shutil`, `pathlib`, `tempfile`, `getattr`, `importlib` unblocked | `_PYTHON3_BLOCKED_*` + the AST walk |
| **Ran as the server UID** — the `sudo -u` branch was dead code with an empty sandbox user | `_use_sudo` in `_cmd_python3` |
| The one mechanism that would refuse to boot this config was disabled | strict-mode gate in `SafeKernel.__init__` |

Verified exploitable before the fix: `from os import system` executed, `import os
as _o` executed, and python3 **read `agent_os/config.env`** (i.e. every API key).

Also found: scan/execute divergence (code is mutated after the AST scan), TOCTOU
on the script-file path, self-liftable `setrlimit` (the bootstrap is wrapped in
`try/except: pass` and `resource` is importable), and no `RLIMIT_FSIZE`/`NOFILE`/
`NPROC`, namespace, chroot or seccomp.

### 1B — Critical: no HTTP egress was actually blocked (CLOSED by Steps 0 + 1b)

- **The deny decision was discarded.** A registered resource whose entitlement
  check denied was only refused when `EXTERNAL_ACCESS_UNKNOWN_MODE == "deny"`.
  Shipped value was `audit`, so the branch was skipped and the gate returned
  "governance passed" — **while the audit record said `allowed=False`**. The log
  claimed "denied" and the call went out.
- **Target detection was scheme-anchored** (`^https?://`), so `curl example.com/x`
  (curl prepends `http://`), `--url=https://…`, and `file://` / `dict://` /
  `gopher://` skipped governance entirely. `dict://169.254.169.254` was reachable.
- Only **two** call sites invoked the gate, and it self-disables when
  `entitlement_checker` is `None` (the default).
- An http resource with **no `hosts`** matched every host (empty list = wildcard).
- **Zero SSRF controls existed** anywhere: no DNS pre-resolution, no private /
  loopback / link-local / cloud-metadata blocking, no redirect revalidation, no
  scheme allowlist. `CURL_NOPROXY` is injected, *removing* the corporate proxy.
- Worst primitive: `POST /api/context-manager/fetch-url` — authenticated any-role,
  **no identity binding in that router at all**, unvalidated URL, full body returned.
- `curl` could also **write arbitrary files** via unblocked `-K`, `--dump-header`,
  `--cookie-jar`, `--trace-ascii`, and the glued `-o/path` form.

### 1C — High: credentials were visible to the model (CLOSED by Step 1b)

`$CRED_*` was substituted into **every** command before dispatch, so
`echo $CRED_X_TOKEN` reflected the plaintext into model context and
`echo $CRED_X > f` persisted it — contradicting the docstring's "never in LLM
context" claim. Verified leaking before the fix.

### 1D — High: remaining gaps (partially addressed; see "Not yet closed")

Tenant isolation depends on `AUTH_ENABLED` (safe value is opt-in, not default);
`context_manager.py` has no identity binding across ~14 tenant-scoped endpoints;
`config.env` secrets are process-wide with `EnvBackend` consulted first and no
tenant namespacing; the credential-dir fallback hardcodes the `company` tenant.

### 1E — The honest verdict on OpenShell

| Finding | OpenShell fixes it? |
|---|---|
| python3 as server UID, AST bypass, TOCTOU, self-liftable limits | **Yes** — a real boundary makes the guard's weakness irrelevant |
| Bundled tool scripts inheriting the parent env | **Yes** — they execute inside the sandbox |
| Agent egress + endpoint-bound credential injection | **Yes** — gateway policy-checks and the agent never holds the secret |
| Deny fall-through, credential substitution leak, router SSRF, RLM kill switch, tenant isolation | **No — our bugs.** Fixed in Steps 0/1b |

**Conclusion:** OpenShell is the right durable boundary for execution and agent
egress, but roughly five of the worst findings were ours to fix regardless.

---

## Part 2 — In plain English

The agent was a contractor working **inside our house with a master key**. We
handed them a list of rooms to avoid, but the list had a loophole; nobody checked
their bag on the way out; and we handed over the credit card in plain sight. The
logbook did record everything — and sometimes said "we stopped them" when we hadn't.

Steps 0/1b took away the master key, fixed the logbook so "denied" means denied,
and stopped showing the credit card. Step 1a adds the option of moving the
contractor into a **workshop next door** (OpenShell): they work in the workshop,
everything leaving goes through one guarded door, they never hold the card, and
changing the rules needs a signature. Payoff: agents can do *more* with *less*
risk, and there is an isolation story that survives a client security review.

---

## Part 3 — What changed

### Step 0 — configuration (no code)

| File | Change |
|---|---|
| `agent_os/config.env` | `AGENT_PYTHON3_ENABLED=false`; added `AGENTOS_UNTRUSTED_EXECUTION_GUARD=true`; `EXTERNAL_ACCESS_UNKNOWN_MODE=deny`; documented the new `AGENTOS_KERNEL_BACKEND` / `AGENTOS_SANDBOX_*` block |
| `enterprise_root/tenants/company/security/external_access.yaml` | **new** `external:platform.self_api` resource (loopback `:8082`, `/api/workstreams/*`, GET+POST) |

**`ENTERPRISE_STRICT_MODE` was deliberately NOT enabled.** It would refuse to
boot this host: strict mode additionally requires `FILE_URL_SIGNING_SECRET` and
`QUEUE_INGEST_API_KEY` to be ≥32 chars, and both are empty. (`AUTH_ENABLED`,
`JWT_SECRET`, `USE_REDIS_SESSIONS` already satisfy it.) Set all three together
when hardening production — the prerequisites are listed inline in `config.env`.

**Why the self-API registration was mandatory:** Mission Mode reaches the engine
by curling `http://localhost:8082/api/workstreams/<n>/iterate`, which passes
through the egress gate. Flipping to `deny` without registering it would have
silently killed **every cron-driven workstream**.

### Step 1a — the OpenShell backend (modular, off by default)

| File | Change |
|---|---|
| **new** `agent_os/openshell_runtime.py` | `OpenShellKernelRuntime` — the only file that imports the OpenShell SDK |
| `agent_os/kernel_runtime.py` | **one branch** added to `create_kernel_runtime` (`openshell`), lazy import inside the branch, fail-closed `raise` preserved and message updated |
| `IAF-Agent-Studio/shared/config.py` | mirrored `AGENTOS_SANDBOX_*` constants beside the existing `AGENTOS_KERNEL_*` family |
| **new** `IAF-Agent-Studio/tests/test_openshell_kernel_runtime.py` | 13 tests (SDK stubbed) |

We **reused the seam that already existed** rather than inventing one:
`KernelRuntime` (Protocol) + `create_kernel_runtime` + `AGENTOS_KERNEL_BACKEND`
already shipped `local` and `remote` backends, and the whole agent-initiated
execution surface funnels through two lines in `tool_factory.py`
(`run_shell_command`, `write_file`). Consequence: **zero changes** to `SkillAgent`,
`tool_factory.py`, or any of the 6 `create_kernel_runtime` call sites.

**Composed, not a pure proxy.** OpenShell knows nothing about AgentOS governance
(blocked commands, the tenant egress registry, audit). A backend that just
forwarded strings to `session.exec` would have *added* isolation while *removing*
governance — a net regression. So the backend holds a local SafeKernel used
**only for policy decisions** (it never executes agent commands) and delegates
execution to the sandbox.

**Recommended alternative, needing no new code:** run the existing
`IAF-Agent-Studio/kernel_worker.py` *inside* an OpenShell sandbox image and use
`AGENTOS_KERNEL_BACKEND=remote`. That yields OpenShell isolation with a fully
unmodified SafeKernel — the cleanest composition.

### Step 1b — our own fixes

| File | Fix |
|---|---|
| `agent_os/kernel.py` | entitlement **DENY is now honoured in every mode** (removed the `unknown_mode` coupling) |
| `agent_os/kernel.py` | new `_curl_targets()` detects scheme-less hosts, `--url=` forms, and non-HTTP schemes (refused outright); `_curl_urls()` kept as a shim. Value-taking curl options are skipped so header/data payloads are never mistaken for a target |
| `agent_os/kernel.py` | `_cmd_curl` pins `--proto =http,https` + `--proto-redir`, and blocks the file-writing options incl. glued short forms (`-o/path`) |
| `agent_os/kernel.py` | `$CRED_*` substitution scoped to credential-consuming commands (`curl`), so `echo`/`cat` cannot reflect a secret |
| **new** `agent_os/egress_ssrf.py` | reusable SSRF guard: scheme allowlist, resolve-once address pinning, rejects private/loopback/link-local/multicast/reserved/metadata. Step 2 reuses this |
| `IAF-Agent-Studio/routers/context_manager.py` | `_fetch_url` validates via the guard and revalidates redirects instead of following them blindly |
| `agent_os/external_access.py` | validator now **requires `hosts`** on http resources (empty list was a wildcard) |
| `IAF-Agent-Skills/iaf_agent_skills/agent.py` | new `_rlm_execution_enabled()` consulted on the RLM dispatch branch, so `RLM_ENABLED=false` actually disables `execution_mode: rlm`. Deliberately **not** tied to the untrusted guard — that would disable the three shipped RLM skills |
| `IAF-Agent-Skills/iaf_agent_skills/tool_factory.py` | `fetch_canonical` now applies the missing `database_allowed()` check |
| `rl_capture/adapters/agentpro/eval_candidates.py` | routed through `create_kernel_runtime` (was the only production bypass, so evals would stay in-process even with a sandbox backend selected) |
| `IAF-Agent-Studio/routers/context_manager.py` | **tenant isolation**: the file had *zero* identity-binding calls while ~33 endpoints took `tenant_id` from the caller and built filesystem paths from it. Added a router-level `require_context_tenant` dependency that authorises the requested tenant (query **or** JSON body) before any handler runs, plus an explicit `authorise_tenant()` in the two multipart upload handlers (the dependency must not consume the upload stream). Handler bodies are untouched — their `tenant_id` argument is now guaranteed to be one the principal may access |
| **new** `agent_os/tests/test_step1b_hardening.py` | 28 regression tests pinning every defect above |
| **new** `IAF-Agent-Studio/tests/test_context_manager_tenant_isolation.py` | 12 tests: cross-tenant via query/body/multipart → 403; own tenant, no-tenant fallback and multi-tenant principals → allowed; dependency is actually attached to the router; documented auth-off no-op |
| `IAF-Agent-Studio/routers/context_manager.py` + `enterprise_root/tenants/company/security/policies.yaml` | **per-item access** (see below) |
| **new** `IAF-Agent-Studio/tests/test_context_item_access.py` | 13 tests incl. the `manager` role the user API cannot create |

### Per-item context access — allow by default, restrict by exception

A second, separate question from the tenant boundary: *within* a tenant, which
documents may you touch? Previously: all of them, for anyone who could log in.

The entitlement engine is **default-deny** and lets **any matching `deny` win
regardless of rule order** (`security/yaml_provider.py::can`), which makes
"allow broadly, restrict narrowly" expressible with no engine change. The
policies already used a `context:<virtual path>` resource convention, so the
model reuses it rather than inventing per-file metadata:

```yaml
context-default-allow           allow  context:*                              roles: user, manager, auditor
context-restricted-folder-deny  deny   context:/shared/contexts/restricted/*  roles: user, auditor
```

**Restriction is by FOLDER, not per file.** Anything placed under
`/shared/contexts/restricted/` is protected automatically — no tagging, no policy
edit per document. This is the deliberate answer to the main weakness of a
default-allow posture ("someone adds a sensitive doc and forgets to protect it").

Enforcement points in `context_manager.py`: `enforce_context_access()` on
item read/update/delete and `files/read` · `files/save` · `files/delete`, plus
`can_access_context()` used to **filter listings**, so restricted titles are
hidden rather than returned-and-then-refused.

Sample documents shipped to exercise both paths:
`shared/contexts/open_sample_note.md` (open) and
`shared/contexts/restricted/hr_compensation_policy.md` (restricted, synthetic content).

Verified live with a real non-admin account (`role: user`) — admin alone would
mask everything, since admin holds `allow * on *`:

| Request | admin | user |
|---|---|---|
| read open file | 200 | 200 |
| read restricted file | 200 | **403** |
| delete restricted file | — | **403** |
| save restricted file | — | **403** (file verified intact on disk) |
| save open file | — | 200 (write verified) |

Deny reason surfaced to the caller: *"The restricted context folder is limited to
managers and administrators."*

**Known trade-off (documented in the policy file):** because deny beats allow, a
principal holding *both* a denied role (`user`/`auditor`) and an allowed one
(`manager`) is denied. Keep roles single-valued, or grant access via a dedicated
role rather than stacking roles.

---

## Part 4 — Verification performed

**Unit / regression:** `agent_os/tests` 135 passed; Studio kernel+openshell+
entitlements 43 passed; engine provider-slots + tool-factory-golden 31 passed.
Six failures remain and are **all pre-existing** — confirmed by re-running under
the old posture and, for `test_curl_blocked`, by checking git HEAD (`curl` was
never in `BLOCKED_COMMANDS`; that test is stale). The three python3-containment
tests in `test_entitlements.py` now opt into their own posture via
`AGENTOS_UNTRUSTED_EXECUTION_GUARD=false`, since the deployment default forces
python3 off.

**Before/after battery** (execution, egress, credential; both `deny` and forced
`audit` mode, two tenants):

| Case | Before | After |
|---|---|---|
| `python3 -c` inline | RAN | BLOCKED |
| `from os import system` / `import os as _o` | RAN | BLOCKED |
| python3 reads `config.env` | RAN | BLOCKED |
| registered resource + entitlement DENY | **ALLOWED** | DENIED (in *both* modes) |
| scheme-less host / `--url=` form | ALLOWED (ungoverned) | governed → DENIED |
| `file://` , `dict://169.254.169.254` | ALLOWED | DENIED (mode-independent) |
| `echo $CRED_*` | **LEAKED** | MASKED |
| `curl` with `$CRED_*` (happy path) | worked | still works |
| `ls` / `cat` / `grep`, registered SAP GET, self-API POST | worked | still work |

**Live, on the running server** (restarted via `agentosrlm`, clean boot, python3
security warning gone):
- admin login, `/auth/me`, 65 workstreams listed, graph API returns 9 nodes
- **full 9-node graph workstream ran end-to-end**: `INV-2026-500481` pending→done,
  trace recorded, `execution_log`/`execution_ledger.steps` populated
- agent asked to run python3 → `Error [COMMAND_BLOCKED]: 'python3' is disabled for safety.`
- agent `ls /shared/databases` → normal output (positive control)
- agent `curl https://example.com` → `Error [EXTERNAL_ACCESS_DENIED]: external target is not registered`
- SSRF guard: 13/13 cases correct, including the rebind-style `169.254.169.254.nip.io`

## Part 5 — Not yet closed (deliberate)

1. ~~`context_manager.py` identity binding~~ — **CLOSED** (see Step 1b table).
   Verified live: cross-tenant GET/PUT/POST/DELETE and JSON-body tenants all
   return `403 Tenant access denied`, while own-tenant CRUD still returns 200.
   ~~Residual: per-item entitlement~~ — **also CLOSED**, see below.
2. **Per-tenant credential scoping** — `EnvBackend` has no tenant namespace and is
   consulted first; the credential-dir fallback hardcodes `company`.
3. **Audit redaction** — misses `X-API-Key`, `api-key`, and query-string secrets.
4. **`ENTERPRISE_STRICT_MODE`** — blocked on two missing secrets (see Step 0).
5. **Step 2 (egress via the gateway)** — designed; `egress_ssrf.py` is the
   groundwork. Prefer having the sandbox reuse `external_access.match_http_resource`
   so the tenant YAML stays the single source of truth.
6. **Stale test** `agent_os/tests/test_agentos.py::test_curl_blocked` asserts curl
   is blocked, which was never true. It should be rewritten to assert the egress
   gate behaviour (and it incidentally documents that the gate self-disables
   without an entitlement checker). Left unchanged — pre-existing, out of scope.
7. The OpenShell SDK is not installable on this host (PyPI blocked), so Step 1a is
   verified against a stubbed SDK. A live gateway run is still outstanding.
