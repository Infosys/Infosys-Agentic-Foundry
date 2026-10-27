# Security — Developer Guide

*How the platform secures agent execution, and how you (a developer) configure and extend it.*

This guide is grounded in the actual code paths in this repo. It explains the security model from the basics, then gives concrete recipes. Read Part 1 for the mental model; jump to Part 8 for "I just need to do X."

---

## Part 1 — The mental model: defense in depth

Security is **layered** — a request passes through several independent controls, and lower layers cannot be bypassed by higher ones. No single check is the whole story.

```
   Request (Chat · API · Cron · Queue)
        │
   1. AUTHENTICATION        who are you?            → IdentityContext (roles, groups, tenant)
        │
   2. ENTITLEMENTS / POLICY may you do this?        → enforce_entitlement(skill/tool/context/data)
        │
   3. LIFECYCLE HOOKS       should this proceed?    → HookRunner (observe / gate, skill-scoped)
        │
   4. HARD GATES            is it intrinsically safe? → SafeKernel (sandbox, path, creds, approval)
        │
   5. SECRETS               give the secret safely   → SecretProvider (masked, never in prompt/log)
        │
   6. AUDIT / EVIDENCE      record what happened     → AuditSink / EvidenceSink (bounded, redacted)
```

Three rules underpin everything:
1. **The reasoning core (LLM) is never a security control.** A prompt saying "only approve under €25k" is guidance, not enforcement. Real limits live in layers 2–4.
2. **Default-deny for what matters.** Skills, tools, context files, external resources, and credentials are denied unless a policy grants them.
3. **Defense in depth.** A capability may be checked by both a hook *and* a hard gate — keep both.

### In plain words — the office-building analogy
If the platform were a secure office building:

| Security layer | Like… | In our system |
|---|---|---|
| **Authentication** | the **badge** at the front door — proves who you are and what department (group) you're in | a signed token → `IdentityContext` |
| **Entitlements** | the **access list on each door** — your badge opens only the rooms your department is allowed into. *A skill is a room.* | `policies.yaml` rules |
| **Hooks** | a **security guard** at certain doors who can stop you and ask for a sign-off | `HookRunner` (gating hooks) |
| **Hard gates** | the **vault locks that cannot be forced** — not even a guard can wave you past | `SafeKernel` |
| **Secrets** | the **key cabinet** — a key is handed over only at the moment it's used, you never get to copy it or see it written down | `SecretProvider` |
| **Audit / Evidence** | the **CCTV + visitor log** — every door opened (or refused) is recorded, sensitive details blurred | audit / evidence sinks |

The one idea behind all of it: **the agent (the visitor) is never trusted to police itself — the building's systems do.**

---

## Part 1.5 — Where you actually change things: the Security Console UI

You don't have to hand-edit YAML for most of this. Open the **Security Console** at:

> **`http://localhost:8082/skill-builder/v2`**  *(admin login required)*

Its panels write the underlying files for you:

| Panel | What you do there | Underlying file / endpoint |
|---|---|---|
| **Entitlement Policies** | Add/edit *allow* rules — who (role/group) may `use` which `skill:` / `tool:` / `context:` / `external:` resource. "Validate" before save. | writes `security/policies.yaml` (`PUT /api/security/policies`, admin-only) |
| **Access Simulator** | Test **one** decision: pick a principal (who) + action + resource → get **ALLOW/DENY** + the matched rule, **without running anything**. | `POST /api/security/simulate` |
| **Effective Access** | See everything a given principal *can* do. | `POST /api/security/effective-access` |
| **Users & Access** | Consolidated roster of **every user** × what they can reach (allowed/total per resource type); click a row for the full per-resource allow/deny detail. | composes `GET /auth/users` (roster) + `POST /api/security/effective-access` per user |
| **External Access Registry** | Register external systems agents may reach (APIs, DBs, MCP), then grant them in Policies as `external:*`. | `security/external_access.yaml` |
| **Credentials** | Store / rotate / delete secrets — no file editing; values are never displayed back. | credential store (`/api/credentials`) |
| **Entitlement Audit Log** | Search who accessed what, allow/deny, when. | `GET /api/security/audit` |
| **Hooks** (admin) | Author lifecycle hooks for an agent — e.g. a one-click **blocking PreToolUse (HITL)** gate — without hand-editing YAML. | writes the `hooks:` subtree of `config.yaml` (`PUT /api/agents/{id}/config/hooks`); validates via `POST .../config/hooks/validate` |
| **Context Manager** | Author/organize the context files skills read (ContextOS / L1–L5). | `/shared/contexts/…` |

**Recommended UI workflow to onboard a new skill securely:**
1. **External Access Registry** → register any API/DB the skill needs.
2. **Credentials** → store that system's key (referenced later as `$CRED_*`, never inline).
3. **Entitlement Policies** → add a rule granting the right **group** `use` on `skill:<name>` (and the `external:`/`context:` it needs).
4. **Access Simulator** → enter `principal = that user`, `action = use`, `resource = skill:<name>` → confirm **ALLOW** (and that an unentitled user gets **DENY**).
5. Ship, then watch the **Audit Log**.

### Is the Console sufficient? Mostly — here's the honest split
**You can do in the UI (no YAML):** entitlement policies · external-resource registry · credentials · decision simulation · audit review · context files. That's the bulk of day-to-day security.

**Still done in files / env (not in this Console):**
- **Master switches** — `AUTH_ENABLED`, `ENTITLEMENTS_ENABLED`, `ENTITLEMENTS_ENFORCEMENT_MODE` (`enforce`/`observe`), `EXTERNAL_ACCESS_*` → `agent_os/config.env` *(see Part 9)*. These are deployment config, intentionally not click-editable.
- **Per-skill HITL & tools** — which tools a skill binds, `approval_rules`, `hitl.dangerous_tools` / `hitl_skills` / `sql_patterns` → the skill's **`SKILL.md`** (the skill-builder's skill editor) + agent **`config.yaml`**.
- **Lifecycle hooks** — the `hooks:` section → agent **`config.yaml`** (file).
- **User → group assignment** — in your **identity provider** (the token's `groups` claim), not this Console.

> Rule of thumb: **"who can use what" lives in the Console; "how the system runs and what each skill is allowed to do internally" lives in files/env.**

---

## Part 2 — Authentication (who are you?)

The platform normalizes every caller into an **`IdentityContext`** (`auth/identity.py`): `tenant_id`, `user_id`, `roles`, `groups`, `scopes`, `auth_method`, service-principal flag, expiry. Everything downstream (policy, memory, audit) consumes this — not raw provider tokens.

**Config:**
| Env var | Default | Meaning |
|---|---|---|
| `AUTH_ENABLED` | `false` | When `true`, `/api/*` requires a valid bearer token; the server ignores browser-supplied `user_id` and uses the token's `sub`. |
| `AUTH_PROVIDER` | `local` | `local` (JWT) · OIDC providers (Entra/Okta) via the auth factory. |
| `JWT_SECRET` | random | **Must be set explicitly in production** (otherwise tokens don't survive a restart). |

- **Local dev:** `AUTH_ENABLED=false` — everyone is an implicit admin. Fine for development; never for prod.
- **Production:** `AUTH_ENABLED=true` + a real `JWT_SECRET` (or an OIDC provider). Provider-specific claims (e.g., Entra group GUIDs) are mapped to platform roles/groups at the **auth-adapter boundary**, so policy stays vendor-neutral.
- **Service principals** (cron/queue/HITL-resume) get a synthetic identity (`service:cron`, etc.) — they are subject to the same policy as users.

> ⚠️ The server warns at startup if `ENTITLEMENTS_ENABLED=true` while `AUTH_ENABLED=false` — entitlements without authentication is only safe for local dev.

---

## Part 3 — Entitlements / Policy (may you do this?)  ← the layer you'll touch most

This is the authorization engine. It answers: *may this identity perform this action on this resource?* It governs **skills, tools, context files, agents, external resources, and credentials**.

### The vocabulary
- **Actions:** `use`, `call`, `access`, `read`, `write`, `delete`, `test`.
- **Resource types:** `skill:<name>`, `tool:<name>`, `context:<path>`, `agent:<id>`, `external:<id>`, `credential:<name>`, `mcp:<server>`, `external:db.<name>`.

### Where it's declared — `enterprise_root/tenants/<t>/security/policies.yaml`
Declarative **allow** rules keyed by `roles` and/or `groups`. Default-deny: if no rule grants it, it's denied.

```yaml
- id: authenticated-users-can-use-default-agent
  effect: allow
  roles: [user, manager, auditor]
  actions: [use, call, read, test]
  resources: [agent:*, skill:general, context:/shared/Enterprise_Context.md, tool:shell, tool:query_memory]
- id: finance-ap-group-can-use-ap-skill
  effect: allow
  groups: [finance-ap]
  actions: [use, call, read]
  resources: [skill:fa_ap, context:/shared/contexts/fa_environment.md]
- id: admin-full-access
  effect: allow
  roles: [admin]
  actions: ['*']
  resources: ['*']
```

### Where it's enforced (multiple layers — defense in depth)
| Layer | Code | Effect |
|---|---|---|
| **Route gate** | `routers/chat.py` → `enforce_entitlement(principal, "use", "agent"/"skill", …)` | Blocks the request before the agent runs. |
| **Router pre-filter** | `iaf_agent_skills/router.py` (`_allowed_skills`) | Non-entitled skills aren't even routing candidates. |
| **Execution hard check** | `agent.py` → `_entitlement_allowed("use","skill",name)` → `PermissionError: Access denied: skill '…' is not permitted` | In-process; also fires for `invoke_skill` delegation. |
| **Per-tool / per-context** | `agent.py` → `_entitlement_allowed("use","tool",…)` / `("read","context",…)` | Tools and context files are filtered per skill too. |
| **Context Manager tenant gate** | `routers/context_manager.py` → router-level `require_context_tenant` dependency | Authorises the *requested tenant* before any handler runs → `403 Tenant access denied`. |
| **Context Manager per-item gate** | `routers/context_manager.py` → `enforce_context_access` / `can_access_context` | Gates read/write/delete of an individual document, and filters listings so restricted titles don't leak. |

### Context documents — allow by default, restrict by exception

Context items use the standard `context:<virtual path>` resource type in a
deliberately **permissive-by-default** posture: the engine is default-deny, so
enforcing without a broad allow would refuse every document and break the UI.

Two rules in the tenant's `policies.yaml` express the whole model:

```yaml
- id: context-default-allow            # everything readable/editable by default
  effect: allow
  roles: [user, manager, auditor]
  actions: [read, write, delete, access, use]
  resources: ['context:*']
- id: context-restricted-folder-deny   # …except the sensitive folder
  effect: deny
  roles: [user, auditor]
  actions: ['*']
  resources: ['context:/shared/contexts/restricted/*']
```

**Restriction is by FOLDER, not per file.** Anything placed under
`/shared/contexts/restricted/` is protected automatically — no per-file tagging,
no policy edit per document. This is intentional: the weak point of a
default-allow posture is someone adding a sensitive document and forgetting to
protect it, and *"move it into this folder"* is far more reliable than
remembering to tag it.

Because **any matching `deny` wins regardless of rule order**
(`security/yaml_provider.py::can`), the carve-out is fail-closed once a document
sits in that folder.

> **Trade-off to know:** since deny beats allow, a principal holding *both* a
> denied role (`user`/`auditor`) and an allowed one (`manager`) is **denied**.
> Keep roles single-valued, or grant access through a dedicated role rather than
> stacking roles.

Reference documents shipped for this model:
`shared/contexts/open_sample_note.md` (open) and
`shared/contexts/restricted/hr_compensation_policy.md` (restricted).

### Config
| Env var | Default | Meaning |
|---|---|---|
| `ENTITLEMENTS_ENABLED` | `false` | Master switch. Off = all allowed (dev). |
| `ENTITLEMENTS_ENFORCEMENT_MODE` | `enforce` | `enforce` = deny is denied. `observe` = **log the deny but allow** — use this to roll out new policy safely and watch what *would* break before flipping to `enforce`. |

Provider behavior: a provider **error** is treated **fail-closed** (deny), not fail-open. In the Adapter, this runs through the normalized `PolicyProvider` (`security/provider.py`) so the backend (YAML today, Entra-RBAC/OPA later) is swappable without changing call sites.

---

## Part 4 — Lifecycle hooks (should this proceed?)

Hooks (`HookRunner`) wrap capability boundaries so you can **observe** or **gate** without editing the core. They are how domain-specific governance is added.

- **Events:** `PreToolUse`, `PostToolUse`, `PreStep`, `PostStep`, `BeforeModelCall`, `OnError`, approval-resume, schedule, queue.
- **Scoping:** a hook carries a `matcher` (tool-name regex) **and** a `skills: [...]` filter, so it can fire only for one tool in one skill.
- **Semantics:** `mode: blocking` hooks can **deny**; each declares a `fail_policy` (`open` = proceed-with-warning, `closed` = deny on hook error). Security-relevant hooks should be `closed`.
- **Master switch:** `CAPABILITY_HOOKS_ENABLED` (default `true`).

**The tool firewall:** every tool call — in *both* the LangGraph and native React runtimes — flows through `tool_governance.govern_tool_call`, which runs the pre-tool observer, evidence record, the `PreToolUse` hook, and the write/dangerous/HITL gates. One firewall, no drift between runtimes.

Hooks are declared in the agent's `config.yaml` `hooks:` section (shell hooks) and run as subprocesses with bounded, redacted I/O.

**Platform vs tenant hooks.** Built-in governance (the orchestrator circuit-breaker/audit/validator set) is **framework-owned** — it lives in `iaf_agent_skills/platform_hooks/hooks.yaml`, NOT in any tenant `config.yaml`, and is merged in at load time (`resolve_effective_hooks`). It is **read-only / structurally non-editable** from the tenant UI/API, always runs **before** tenant hooks (priority band ≤99 vs ≥100), and a tenant cannot reuse a reserved platform `hook_id` (PUT → 400). Tenant hooks remain admin-editable in `config.yaml`. A corrupt/missing platform manifest **fails loud** (`IAF_PLATFORM_HOOKS_REQUIRED=true` by default) rather than silently dropping governance.

**Authoring tenant hooks from the UI (no YAML by hand):** the Security Console has a **Hooks** panel (admin-only) that reads/writes just the tenant `hooks:` subtree of an agent's `config.yaml` (platform hooks appear in a separate read-only section). It validates the document server-side (`shared/hooks_validation.py`, mirroring `hook_runner._validate_external_manifest`), shows the `CAPABILITY_HOOKS_ENABLED` state, and has a one-click **"blocking PreToolUse (HITL)"** preset (`mode: blocking`, `fail_policy: closed`, `block_on_nonzero: true`). Endpoints: `GET/PUT /api/agents/{id}/config/hooks` and `POST .../config/hooks/validate`. The save does a locked **read-merge-write** (only the `hooks:` key changes — `context`/`sufficiency`/`hitl`/etc. are preserved), **evicts the cached agent** so the change applies on the next run with no restart, and writes an audit row (`category="agent_config_change"`). The `command` field runs a shell command on the server (**not sandboxed**) — it stays **admin-only**; the validator flags obviously dangerous commands with a non-blocking warning but never refuses the save.

---

## Part 5 — Hard gates (is it intrinsically safe?)  ← always on, cannot be bypassed

`SafeKernel` (`agent_os/kernel.py`) enforces these regardless of what the planner or a hook decides:

| Gate | Code | What it blocks |
|---|---|---|
| **Command allow/deny** | `BLOCKED_COMMANDS`, command parser | Interpreters (`python`, `python3`, `bash`, `sh`, `node`, …) and destructive commands are refused. |
| **Path safety** | `_resolve_path` → `Error [PATH_ESCAPE]` | File reads/writes cannot escape the agent's allotted dir. |
| **Write confirmation** | `_requires_confirmation` / `require_confirmation` | Writes/deletes require approval in ask-first (non-`auto_run`) mode. |
| **External access** | `_curl_targets`, `_external_resource_allowed`, `database_allowed` | Outbound HTTP / DB / MCP must be a registered+granted resource; non-HTTP(S) schemes are refused outright. |
| **Credential authorization** | `_cmd_get_credential`, `_substitute_session_vars` | A credential resolves only after an entitlement check, and the value is injected **only** into credential-consuming commands. |

> **Accuracy note (corrected 2026-09-30).** This table previously claimed a
> *"Sandbox — shell/code runs in a constrained space, no ambient host access."*
> That was **not true** for `python3`: with `AGENT_PYTHON3_ENABLED=true` and an
> empty `AGENT_PYTHON3_SANDBOX_USER`, model-generated Python ran as the **server
> process user** with full filesystem access, the AST denylist was bypassable
> (`from os import system`), and the python3 fast path skipped the approval gate
> entirely. There is **no in-process sandbox**. Containment comes from the
> command allow/deny list plus the execution backend you choose (below).

### Execution backend — where agent code actually runs

Selected by `AGENTOS_KERNEL_BACKEND` (`agent_os/kernel_runtime.py`), **fail-closed**:
an unknown value refuses to start rather than silently degrading to in-process.

| Backend | What it is | Isolation |
|---|---|---|
| `local` (default) | in-process `SafeKernel` | Command allow/deny + path jail only — **same OS user as the server**. |
| `remote` | signed HTTP to `kernel_worker.py` | Separate process; full SafeKernel governance preserved. |
| `openshell` | NVIDIA OpenShell sandbox (`agent_os/openshell_runtime.py`) | Kernel-enforced sandbox; policy decisions still made host-side so governance is not lost. |

For code execution specifically, the real controls are:

| Env var | Default (this repo) | Meaning |
|---|---|---|
| `AGENT_PYTHON3_ENABLED` | `false` | Allow `python3` in agent shell commands. **Do not enable without a sandbox user.** |
| `AGENT_PYTHON3_SANDBOX_USER` | *(empty)* | Restricted OS user to `sudo -u` into. Empty ⇒ code runs as the server user. |
| `AGENTOS_UNTRUSTED_EXECUTION_GUARD` | `true` | Forces python3 **off** regardless of the above; also blocks personal-skill bundled tools and local stdio MCP. |
| `ENTERPRISE_STRICT_MODE` | `false` | Makes the sandbox user **mandatory** (kernel refuses to boot otherwise). Also requires `FILE_URL_SIGNING_SECRET` and `QUEUE_INGEST_API_KEY` ≥32 chars. |

**External-access config:**
| Env var | Default (this repo) | Meaning |
|---|---|---|
| `EXTERNAL_ACCESS_ENABLED` | `true` | Master switch for outbound gating. |
| `EXTERNAL_ACCESS_UNKNOWN_MODE` | `deny` | For an *unregistered* target: `allow` · `audit` (allow + log) · `deny`. |
| `EXTERNAL_ACCESS_ENFORCE_CREDENTIALS` / `_MCP` / `_SQL` | track enabled | Per-channel enforcement toggles. |

Two behaviours worth knowing (both fixed 2026-09-30):

- **An explicit entitlement DENY is honoured in every mode.** It previously only
  took effect when `unknown_mode == "deny"`, so in `audit` mode a denied request
  still went out *while the audit record said `allowed=False`*. `unknown_mode`
  now governs only *unregistered* targets.
- **Target detection covers more than `https://…`.** A scheme-less host
  (`curl example.com/x`, which curl silently prefixes), the `--url=` form, and
  non-HTTP schemes (`file://`, `dict://`, `gopher://`) previously skipped the
  gate entirely. `_curl_targets` now detects all three, non-HTTP(S) schemes are
  refused outright, and curl is pinned with `--proto =http,https`.
- The gate is **inert without an entitlement context** (`entitlement_checker`
  is `None`), so any code path that builds a kernel without
  `set_entitlement_context` gets no HTTP/credential/SQL governance.

Registered external resources (APIs, DBs, MCP) live in `security/external_access.yaml`;
grants are `external:<id>` entries in `policies.yaml`. An `http` resource **must**
declare `hosts` — an empty list matches every host, and the validator now rejects it.

> **Loopback matters:** Mission Mode reaches the workstream engine by curling
> `http://localhost:8082/api/workstreams/*/iterate`. That target is registered as
> `external:platform.self_api`. Remove it and every cron-driven workstream stops
> under `unknown_mode=deny`.

---

## Part 6 — Secrets (give the secret safely)

Credentials never enter prompts, logs, diagnostics, or the LLM.

- Stored in `agent_os/credential_store.py` (env / file / Fernet), wrapped by **`SecretProvider`** (`agent_os/secret_provider.py`) — the Adapter's seam for Azure Key Vault / HashiCorp Vault.
- In a skill, you reference a credential by name; the kernel substitutes it **only at execution** of a `curl`/tool call (the `$CRED_*` / `$IAF_AGENT_SELF_AUTH_TOKEN` pattern). The model sees a **masked** placeholder, never the value.
- Access is entitlement-checked (`credential:<name>`) and audited.

> **How that guarantee is actually enforced (fixed 2026-09-30).** Substitution is
> scoped by `SafeKernel._CRED_SUBSTITUTION_COMMANDS` — only credential-consuming
> commands (today: `curl`) get the real value. Previously `$CRED_*` was expanded
> into **every** command before dispatch, so `echo $CRED_X_TOKEN` reflected the
> plaintext straight back into the model's context and `echo $CRED_X > f`
> persisted it to a readable file. If you add a new command that legitimately
> needs a secret, add it to that tuple — do not widen the substitution.
>
> Audit redaction currently covers `Bearer …`, `-u …` and `Authorization: Basic …`.
> It does **not** yet redact `X-API-Key:` / `api-key:` headers or secrets embedded
> in a query string — avoid putting credentials in URLs.

**Rule:** never hardcode a secret in a SKILL.md, prompt, context file, or tool. Declare it as a credential and reference it.

---

## Part 7 — Audit & Evidence (record what happened)

Every consequential action is recorded — **bounded and redacted**:
- **Audit** (`security/audit.py`): policy decisions and tool/skill access. `_is_sensitive_key` redacts password/token/secret-shaped keys; `Bearer …` / `Basic …` headers → `[REDACTED]`; long values truncated.
- **Evidence** (`shared/audit_evidence_sinks.py`): what the agent read/produced, under a `trace_id`, with the same redaction + a `preview_limit` (`AUDIT_EVIDENCE_PREVIEW_LIMIT`, default 1024).
- Optional enterprise mirror: `AUDIT_EVIDENCE_MIRROR_ENABLED` → bounded/redacted JSONL for a log forwarder (Splunk/Sentinel). Local storage stays authoritative.

**Guarantee:** no secret value, bearer token, or unbounded prompt ever lands in audit/evidence/diagnostics.

---

## Part 8 — How you go about it (recipes)

> Recipes **A** and **C** are fastest in the **Security Console** (Part 1.5) — the file edits below are shown for reference, automation, or when you don't have the UI. Recipes **B** and **D** are file-based (per-skill HITL, hooks).

### A. Entitle a group to a specific skill
1. Ensure the user's token carries the right `groups` claim (e.g., `finance-ap`).
2. In `policies.yaml`, add:
   ```yaml
   - id: finance-ap-can-use-ap
     effect: allow
     groups: [finance-ap]
     actions: [use, call, read]
     resources: [skill:fa_ap, context:/shared/contexts/fa_environment.md]
   ```
3. Done — the user can now invoke `fa_ap` and nothing else beyond the authenticated baseline. Other skills are filtered by the router and hard-denied at execution.

### B. Make a tool/skill require human approval (HITL)
- Per skill: list the skill in the agent config `hitl.hitl_skills`, or the tool in `hitl.dangerous_tools`, or add a `shell_patterns`/`sql_patterns` match. The firewall sets `approval_pending` and the run pauses until a human resolves it. (Writes already pause in ask-first mode.)

### C. Allow an agent to call an external API/DB
1. Register it in `security/external_access.yaml` (`external:<id>` with allowed methods/paths).
2. Grant it in `policies.yaml`: `resources: [external:<id>]` (or `external:db.<name>` for SQL).
3. Store any API key as a **credential** and reference it via `$CRED_*` — never inline.

### D. Add a governance hook (e.g., audit every SQL write in one skill)
```yaml
# agent config.yaml
hooks:
  PostToolUse:
    - command: python3 $IAF_AGENT_ROOT/../../shared/hooks/sql_audit.py
      matcher: run_sql_query
      skills: [fa_ap]          # only this skill
      timeout_seconds: 5
```
For a gating hook, use `PreToolUse`, `block_on_nonzero: true`, and decide `fail_policy: closed`.

### E. Roll out new/stricter policy safely
Set `ENTITLEMENTS_ENFORCEMENT_MODE=observe` → denies are **logged but allowed**. Watch the audit log for what *would* be blocked, fix the gaps, then flip to `enforce`.

### F. Restrict a sensitive context document
**Move the file into the restricted folder.** That's the whole recipe — no policy
edit, no per-file tagging:

```bash
mv  enterprise_root/tenants/<t>/shared/contexts/salary_bands.md \
    enterprise_root/tenants/<t>/shared/contexts/restricted/salary_bands.md
```

It is now denied to the `user` and `auditor` roles (managers and admins keep
access), the deny is fail-closed, and the document disappears from listings for
unentitled callers rather than 403-ing after the title has already leaked.

To restrict to a *different* audience, add one rule rather than widening the
existing one — remember deny beats allow, so express the new audience as its own
folder + deny pair instead of stacking roles on one principal:

```yaml
- id: context-legal-folder-deny
  effect: deny
  roles: [user, auditor, manager]     # everyone except admin + the legal group
  actions: ['*']
  resources: ['context:/shared/contexts/legal/*']
```

### G. Allow `python3` (or another interpreter) safely
Do **not** just set `AGENT_PYTHON3_ENABLED=true` — that runs model-generated code
as the server OS user, and the AST denylist is not a boundary. Either:
1. create a restricted OS user and set `AGENT_PYTHON3_SANDBOX_USER=<user>`, set
   `AGENTOS_UNTRUSTED_EXECUTION_GUARD=false`, and set `ENTERPRISE_STRICT_MODE=true`
   so the combination can never boot without the sandbox user; **or**
2. leave python3 off and run the whole kernel in a sandbox via
   `AGENTOS_KERNEL_BACKEND=openshell` (or `remote` with the worker inside a sandbox).

### H. Register a new outbound host
Under `unknown_mode=deny`, an unregistered target returns
`Error [EXTERNAL_ACCESS_DENIED]`. Add it to `security/external_access.yaml`
(`hosts` is **required**) and grant `external:<id>` in `policies.yaml`:

```yaml
- id: external:vendor.pricing_api
  type: http
  hosts: [api.vendor.example]      # required — an empty list matches every host
  paths: ['/v1/prices/*']
  methods: [GET]
  tools: [shell]
```

---

## Part 9 — Config reference (security-relevant env)

| Env var | Default | Prod recommendation |
|---|---|---|
| `AUTH_ENABLED` | `false` | `true` |
| `AUTH_PROVIDER` | `local` | OIDC (Entra/Okta) for SSO |
| `JWT_SECRET` | random | **set explicitly** |
| `ENTITLEMENTS_ENABLED` | `false` | `true` |
| `ENTITLEMENTS_ENFORCEMENT_MODE` | `enforce` | `enforce` (start `observe`) |
| `EXTERNAL_ACCESS_ENABLED` | tracks entitlements | `true` |
| `EXTERNAL_ACCESS_UNKNOWN_MODE` | **`deny`** (this repo) | `deny` |
| `CAPABILITY_HOOKS_ENABLED` | `true` | `true` |
| `AUDIT_EVIDENCE_MIRROR_ENABLED` | `false` | `true` (point at SIEM) |
| `AGENT_PYTHON3_ENABLED` | **`false`** (this repo) | `false`, or `true` **only** with a sandbox user |
| `AGENT_PYTHON3_SANDBOX_USER` | *(empty)* | a restricted OS user |
| `AGENTOS_UNTRUSTED_EXECUTION_GUARD` | **`true`** (this repo) | `true` unless you need interpreters |
| `ENTERPRISE_STRICT_MODE` | `false` | `true` (needs `FILE_URL_SIGNING_SECRET` + `QUEUE_INGEST_API_KEY` ≥32 chars) |
| `AGENTOS_KERNEL_BACKEND` | `local` | `remote` or `openshell` for multi-tenant / untrusted code |
| `AGENTOS_SANDBOX_URL` / `_TOKEN` / `_WORKSPACE` / `_ROOT` / `_TIMEOUT_SECONDS` | *(unset)* | required when backend is `openshell` |

---

## Part 10 — Golden rules

- **Never** put a secret, token, or password in a prompt, SKILL.md, context file, or tool argument — use a credential reference.
- **Never** rely on the LLM to enforce a limit — encode it in policy / hard gate / HITL.
- **Default-deny:** grant the *minimum* skills/tools/resources per group; widen only as needed.
- **Start in `observe` mode** when introducing or tightening policy; promote to `enforce` after watching the audit log.
- **Keep `AUTH_ENABLED=true` whenever `ENTITLEMENTS_ENABLED=true`** outside local dev.
- **Service principals are not exempt** — cron/queue identities need explicit grants too.
- **Never enable an interpreter without an OS boundary.** `AGENT_PYTHON3_ENABLED=true`
  with an empty `AGENT_PYTHON3_SANDBOX_USER` runs model-generated code as the server
  user. The AST denylist is a speed bump, not a boundary.
- **Protect a sensitive document by moving it into `shared/contexts/restricted/`**,
  not by trusting that nobody will look. Restriction is folder-based so it cannot
  be forgotten on the next file.
- **Register every outbound host** (`hosts` is required — an empty list matches
  everything). Don't relax `EXTERNAL_ACCESS_UNKNOWN_MODE` to make a call work.
- **Never test authorisation as `admin`** — admin holds `allow * on *`, so it masks
  every per-item and per-tenant rule. Use a `user`-role account.
- **A kernel built without `set_entitlement_context` has no governance** — HTTP,
  credential and SQL gates all self-disable. Always bind identity.

---

*Adapter note:* identity, policy, secrets, and audit/evidence run through normalized **provider boundaries** (`PolicyProvider`, `SecretProvider`, `AuditSink`/`EvidenceSink`), so the same security model can bind to Entra ID, Okta, Azure Key Vault, HashiCorp Vault, Splunk, or Sentinel without changing the core. See `docs/ADAPTER_AUTHORING_GUIDE.md` for adding a provider.
