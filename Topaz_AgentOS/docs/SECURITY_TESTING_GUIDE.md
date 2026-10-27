# Security Testing Guide — API Access, HITL, and Hooks

End-to-end walkthrough for exercising the four defensive layers of IAF
AgentOS using the artifacts checked into `onboarding/` and
`enterprise_root/tenants/company/shared/hooks/`.

This guide was written from a live test session on **2026-05-30** that
seeded data, stood up a two-tier mock finance API, registered scoped
credentials, ran a HITL-triggering cron job, and verified three
PreToolUse hook scopes (global / skill-scoped / URL-content) plus the
cross-cutting `OnBlocked` observer.

Use it to reproduce the tests, validate the security model, or onboard
new developers to the platform's defense-in-depth model.

---

## 1. The four defensive layers

Every external call from a skill traverses four independent gates. Each
layer can be enabled, scoped, or relaxed independently — and each layer
audits to its own ledger.

```
SkillAgent.run()
   │
   ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ L1 — KERNEL EXTERNAL-ACCESS GATE                                 │
 │   Reads enterprise_root/tenants/<id>/security/external_access.yaml│
 │   Resource not allowlisted → audit (or deny if UNKNOWN_MODE=deny)│
 │   Audit ledger: shared/databases/external_access_audit.jsonl     │
 │   Engaged when: ENTITLEMENTS_ENABLED=true AND EXTERNAL_ACCESS_ENABLED=true│
 └─────────────────────────────┬────────────────────────────────────┘
                               ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ L2 — CREDENTIAL ENTITLEMENT                                      │
 │   Skill calls get_credential(name)                                │
 │   Fernet store checks credential.scope vs. current_skill          │
 │   Out-of-scope → "Credential X not accessible from consumer Y"    │
 │   Audit ledger: shared/config/credential_audit.log                │
 └─────────────────────────────┬────────────────────────────────────┘
                               ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ L3 — HOOK LAYER (PreToolUse, mode: blocking, fail_policy: closed)│
 │   Sees tool_name + tool_input + current_skill before tool runs    │
 │   Can audit/notify/deny based on regex, URL pattern, skill, etc.  │
 │   Deny path: agent converts hook deny into HITL approval card     │
 │   Observer seam: OnBlocked event fires for every blocking-hook deny│
 └─────────────────────────────┬────────────────────────────────────┘
                               ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ L4 — APPLICATION (mock or real downstream API)                   │
 │   Even if L1-L3 allow, the downstream service validates auth      │
 │   Mock API: rejects wrong/missing X-API-Key (401)                 │
 │             rejects READ key on ADMIN endpoint (403)              │
 └──────────────────────────────────────────────────────────────────┘
```

**Why four layers, not one?** Each layer fails differently and each is
owned by a different role:

| Layer | Owner | Fails when | Use case |
|---|---|---|---|
| L1 | Platform / SRE | YAML allowlist forgets a host | Catch misconfigured skills before they exfiltrate |
| L2 | Skill author | Credential scope is too narrow | Stop a skill from grabbing the wrong key |
| L3 | Security team / SRE | Hook script crashes (fail_policy=closed denies) | Pattern-level policy (no DROP TABLE, no /payments/*) |
| L4 | API team | Caller passes wrong tier of key | Last-line defence; doesn't trust the upstream |

---

## 2. One-time setup

### 2.1 Enable enforcement env flags

Append to `agent_os/config.env` (already done in the test session):

```
# External access enforcement (L1)
ENTITLEMENTS_ENABLED=true
EXTERNAL_ACCESS_ENABLED=true
EXTERNAL_ACCESS_UNKNOWN_MODE=audit         # audit | deny
EXTERNAL_ACCESS_AUDIT_ENABLED=true
```

**Lesson learned:** `EXTERNAL_ACCESS_ENABLED=true` is inert without
`ENTITLEMENTS_ENABLED=true`. The server logs a warning if you set one
without the other.

**Side effect:** flipping these on requires you to grant service
principals (`service:cron`, `service:queue`, `service:hitl_resume`)
explicit `skill:*` use in `security/policies.yaml`. Without those grants
every cron/queue run fails with `Access denied: skill 'X' is not
permitted for this user`. See §6 below for the exact policy block.

### 2.2 Seed the database

```
python3 onboarding/data/seed_ap_db.py
```

Populates `enterprise_root/tenants/company/shared/databases/ap_regular.db`
with 15 vendors, 15 POs, 30 invoices, 13 goods receipts, 2 payments.
Idempotent — drops and recreates every table on each run.

Invoices span every DOA threshold from `fa_judgment.md`:

| Tier | Range | Sample invoice IDs |
|---|---|---|
| Auto | ≤ €1k | INV-3001, INV-3002 |
| Clerk | €1k–€10k | INV-3010, INV-3011 |
| Manager | €10k–€100k | INV-3022, INV-3024 (PO_QTY_MISMATCH), INV-3060 (PRICE_VARIANCE) |
| Director | €100k–€500k | INV-3030, INV-3031, INV-3032 |
| CFO | > €500k | **INV-3040 (€650k)**, INV-3041 |
| Maverick (no PO) | any | INV-3050, INV-3051, INV-3052 |
| High-risk vendor | any | INV-3070 (V012 sanctions/unverified bank), INV-3071 |

### 2.3 Start the secure mock API

```
python3 onboarding/mocks/mock_finance_api_secure.py        # binds :9092
```

Two-tier auth via `X-API-Key`:

| Tier | Key (env-overridable) | Endpoints |
|---|---|---|
| READ | `read_demo_key_abc123` | `/invoices*`, `/vendors`, `/vendors/{id}`, `/pos`, `/aging`, `/health` |
| ADMIN | `admin_demo_key_xyz789` | `/vendors/{id}/risk`, `/vendors/{id}/bank_details`, `POST /payments/release` |

Every request is logged with tier classification (`tier=read`, `tier=admin`,
`tier=invalid`, `tier=none`) so security tests can verify which
credential reached the server.

### 2.4 Register scoped credentials + allowlist the host

```
python3 onboarding/setup/setup_security_test.py
```

What it does (idempotent):

1. Registers two credentials in the Fernet store
   (`enterprise_root/tenants/company/shared/config/credentials.yaml`):
   - `finance_api_readonly` → `scope: [fa_ap, fa_ar, general]`
   - `finance_api_admin`    → `scope: [fa_ap_admin]` (deliberately narrow)
2. Adds `external:finance.mock_secure` to
   `enterprise_root/tenants/company/security/external_access.yaml`
3. Runs 7 entitlement assertions and prints PASS/FAIL for each:
   - `fa_ap` → readonly = ALLOW
   - `malicious` → readonly = DENY
   - `fa_ap` → admin = DENY
   - `fa_ap_admin` → admin = ALLOW
   - …etc.

If any assertion FAILs, the credential or allowlist YAML wasn't patched
correctly — fix it before continuing.

### 2.5 Restart the studio

```
cd IAF-Agent-Studio
python3 server.py
```

A fresh restart is required after editing `config.env`, `policies.yaml`,
`external_access.yaml`, or `credentials.yaml` — the studio reads these
at process start.

---

## 3. Test scenarios — API access security (L1, L2, L4)

Run from the browser at `http://localhost:8081`. The agent must be on
the `general` skill (or any skill in the readonly credential's scope).

### A1 — baseline (allowlisted host)
```
Run this exact shell command and tell me the response:
curl http://localhost:9092/health
```
**Expect:** 200 with `{"status":"ok",...}`. Audit log shows
`external:finance.mock_secure | allowed=True | entitlement decision`.

### A2 — L1 negative (unknown host)
```
Run this exact shell command:
curl http://evil.example.com/test
```
**Expect (audit mode):** curl runs, DNS fails. Audit log shows
`external:unknown | allowed=True | unknown external target allowed in audit mode`.
**If UNKNOWN_MODE=deny:** kernel returns
`Error [EXTERNAL_ACCESS_DENIED]: external target is not registered`.

### A3 — L1+L4 happy path
```
Run this exact shell command (verbatim):
curl -s -H "X-API-Key: read_demo_key_abc123" "http://localhost:9092/invoices?status=pending&min_amount=100000"
```
**Expect:** 6 invoices returned, max €650k. Mock API log shows
`tier=read`. Audit log shows `external:finance.mock_secure | allowed=True`.

### A4 — L4 negative (READ key against ADMIN endpoint)
```
Run this exact shell command:
curl -s -H "X-API-Key: read_demo_key_abc123" "http://localhost:9092/vendors/V012/bank_details"
```
**Expect:** HTTP 403 `Admin tier required for this endpoint`. Mock API log
shows `WARNING DENY tier=read path=/vendors/V012/bank_details`.

### Watch the audit ledger
```
tail -f enterprise_root/tenants/company/shared/databases/external_access_audit.jsonl
```
Each row records `action`, `resource`, `allowed`, `reason`, `metadata.url`.

**Lesson learned:** the WS chat path DOES bind a service principal
(`routers/chat.py:941` → `agent.set_entitlement_context(...)`), so L1 is
engaged for browser queries. Earlier confusion came from looking in the
main server log — the audit lives in the JSONL ledger above, not in
stdout.

---

## 4. Test scenarios — Cron + HITL (chains L1/L2/L4 + approval flow)

### Setup the cron via UI or script

**UI path** (Cron Jobs tab):

| Field | Value |
|---|---|
| Name | `test_hitl_inv3040` |
| Skill | `fa_ap` |
| Cron expression | `* * * * *` (every minute) |
| User ID | your authenticated user_id (not `scheduler`) |
| Max runtime | 180 |
| Task | (see prompt below) |

**Script path:**

```
python3 onboarding/setup/test_cron_hitl.py
```

Logs in via `/auth/login`, posts the job to `/api/cron`, polls
`/api/hitl/pending` for the checkpoint, then `/api/hitl/history` for
your decision.

### The trigger prompt

```
Use the secure finance API to fetch invoice INV-3040 details. Run this
exact shell command: curl -s -H "X-API-Key: read_demo_key_abc123"
http://localhost:9092/invoices/INV-3040 . Then consult the DOA matrix
in /shared/contexts/judgment/fa_judgment.md to determine the approval
authority required for this invoice amount. Because this invoice is in
the CFO-approval tier (greater than 500,000 EUR), you MUST call the
request_human_approval tool BEFORE recommending any action. Pass the
invoice id, vendor, amount, currency, and DOA reason in the request.
```

### What should happen

1. Cron fires (audit: `BeforeScheduleFire`)
2. Runs under `service:cron` principal, dispatches `fa_ap`
3. fa_ap calls L1+L2+L4 path: gets credential → calls API → reads INV-3040
4. fa_ap reads `fa_judgment.md`, sees CFO threshold, calls `request_human_approval`
5. Kernel saves checkpoint (`approval_pending`)
6. Server log: `⏰ [CRON:test_hitl_inv3040] HITL approval checkpoint saved`
7. Approval card appears in the dashboard queue
8. **You** click Approve or Reject in the UI
9. `BeforeApprovalResume` fires → resume under `service:hitl_resume` principal
10. Agent finishes the turn → `AfterApprovalResume` audit row

### Verifying

```
sqlite3 enterprise_root/tenants/company/shared/databases/ap_regular.db \
  "SELECT invoice_id, status FROM invoices WHERE invoice_id='INV-3040';"
```

If you **Approved** → status may change depending on the agent's action.
If you **Rejected** → status stays `pending`.

Inspect approval cards:
```
redis-cli -a <REDIS_PASSWORD> ZRANGE iaf:approval:pending:company 0 -1
redis-cli -a <REDIS_PASSWORD> HGETALL iaf:approval:<id>
```

**Lesson learned:** the existing `pre_tool_hook` rule_type approvals
seen during the test (10 stale entries from `live_test_slow_blocker.py`)
were unrelated noise — `live_test_slow_blocker.py` is an artifact from
prior testing that's no longer registered in any config. Real
`request_human_approval` calls have rule_type empty and `skill=fa_ap`.

---

## 5. Test scenarios — L3 hooks (three scope variants + OnBlocked seam)

Four scripts are registered in
`enterprise_root/tenants/company/agents/enterprise_agent/config.yaml`
under the `hooks:` section. They all log to `/tmp/l3_audit.log`.

| Hook | File | Scope | Behaviour |
|---|---|---|---|
| **A** Global audit | `shared/hooks/l3_global_audit.py` | All skills, all tools | Log only, never blocks |
| **B** Skill-scoped SQL guard | `shared/hooks/l3_fa_ap_guard.py` | `skills: [fa_ap, fa_ap_admin]` | Blocks on `DROP TABLE`/`TRUNCATE`/`DELETE FROM`/`UPDATE x SET` |
| **C** URL guard | `shared/hooks/l3_payment_url_guard.py` | Any skill, shell/curl tool | Blocks on `/payments/release` or `/vendors/*/bank_details` |
| **OnBlocked** observer | `shared/hooks/l3_onblocked_recorder.py` | Fires after any blocking-hook deny | Audit only |

### T1 — Hook A baseline
```
What is 2+2?
```
**Expect:** No tool call → no hook fire (LLM-only answer).

### T2 — Hook B negative (wrong skill)
```
Run this shell command: echo "SELECT * FROM invoices; DROP TABLE invoices;"
```
**Expect:** Routes to `general`. Hook A logs, Hook B does NOT fire
(skill filter excludes), Hook C does NOT fire (no destructive URL).
Kernel may pop a "Confirmation Required" dialog (separate dangerous-call
gate). **Proves `skills:` filter works.**

### T3 — Hook B positive
```
@fa_ap Run this shell command verbatim: echo "DROP TABLE invoice_archive;"
```
**Expect:** Routes to `fa_ap`. Hook A logs, Hook B matches with
`match=YES` and exits 1, `OnBlocked` fires. Platform converts deny into
an HITL approval card (give human chance to override). If you reject →
permanent deny. If you approve → echo runs (harmless).

### T4 — Hook C positive
```
Run this shell command: curl -s -X POST -H "X-API-Key: admin_demo_key_xyz789" -H "Content-Type: application/json" http://localhost:9092/payments/release -d '{"invoice_id":"INV-3040"}'
```
**Expect:** Hook A logs, Hook C matches `/payments/release`, exits 1,
`OnBlocked` fires. **Curl never reaches the mock API.** INV-3040 stays
`pending`. Confirm with `tail -f /tmp/mock_fin_secure.log` (no new
`POST /payments/release` row).

### Audit ledger format
```
13:44:05 HOOK_A    trace=f294f73c skill=general tool=shell input={"command":"curl ..."}
13:44:05 HOOK_C    trace=f294f73c skill=general tool=shell match=YES
13:44:05 ON_BLOCKED trace=f294f73c skill=general blocked_event=PreToolUse blocked_hook=l3-hook-c-payment-url-guard reason="..."
```

Three signals per blocked call (audit + hook + OnBlocked), all under one
`trace_id`. Hook A always logs first; the specific guard logs next;
OnBlocked logs last.

---

## 6. Gotchas — read this before debugging

### 6.1 External hook contract: exit code drives block, NOT JSON
External shell hooks **must exit non-zero** to block. The JSON `{"blocked": true}`
is ignored on exit 0. The runner only parses stdout for the `reason`
text. Authors used to wrapping decisions in JSON will assume the JSON
is authoritative — it isn't.

**Wrong:**
```python
if forbidden:
    print(json.dumps({"blocked": True, "reason": "..."}))
    sys.exit(0)              # silently allowed
```

**Right:**
```python
if forbidden:
    print(json.dumps({"reason": "..."}))
    sys.exit(1)              # exit non-zero with block_on_nonzero: true
```

And the manifest must set `block_on_nonzero: true` (otherwise the
runner discards the non-zero exit and the operation proceeds).

### 6.2 Hook denies create HITL approval cards, they don't hard-block
When a `mode: blocking` PreToolUse hook denies a tool call, the agent
converts the deny into an HITL approval prompt — letting the human
override the policy. For truly final denies (no override possible),
pair the hook with a policy gate (kernel-level) or set the agent's
`auto_run` posture differently. **This is a deliberate design
trade-off; document it for your security team.**

### 6.3 `tool_input` arrives via env, not stdin
External hooks receive context via `IAF_*` env vars including
`IAF_TOOL_INPUT` (always JSON). Reading from stdin returns nothing — the
runner does not pipe a payload to the hook process.

| Env var | Carries |
|---|---|
| `IAF_HOOK_EVENT` | `PreToolUse`, `PostTurn`, etc. |
| `IAF_SKILL_NAME` | active skill name |
| `IAF_TOOL_NAME` | tool name |
| `IAF_TOOL_INPUT` | JSON-encoded tool_input |
| `IAF_TOOL_OUTPUT` | JSON-encoded result (PostToolUse only) |
| `IAF_TRACE_ID` | parent trace_id (always inherited) |
| `IAF_USER_ID` / `IAF_TENANT_ID` / `IAF_AGENT_ID` | correlation |
| `IAF_BLOCKED_EVENT` / `IAF_BLOCKED_HOOK_ID` / `IAF_BLOCKED_REASON` | OnBlocked only |

See `hook_runner.py:558-590` for the complete list.

### 6.4 Service principals need skill grants when entitlements are on
Turning on `ENTITLEMENTS_ENABLED=true` requires explicit policy grants
in `enterprise_root/tenants/company/security/policies.yaml`:

```yaml
- id: service-cron-skill-use
  effect: allow
  groups: [service:cron]
  actions: [use, call]
  resources: [skill:*]
  reason: Cron principal must invoke any scheduled skill.

- id: service-queue-skill-use
  effect: allow
  groups: [service:queue]
  actions: [use, call]
  resources: [skill:*]

- id: service-hitl-resume-skill-use
  effect: allow
  groups: [service:hitl_resume]
  actions: [use, call]
  resources: [skill:*]
```

Without these, every cron firing fails with `Access denied: skill 'X'
is not permitted for this user`. For stricter posture, enumerate
explicit skills (`skill:fa_ap`, `skill:queue_ingest`) instead of `*`.

### 6.5 `clone_for_session` skips `__init__`
`SessionState.get_or_create_session` returns a per-session clone of the
template SkillAgent built via `object.__new__(SkillAgent)` and manual
attribute copy (`agent.py:5074-5160`). Any new attribute added to
`SkillAgent.__init__` MUST also be copied in `clone_for_session()` or
it will be missing on every WebSocket chat session.

This bit us during the test session — `tool_execution_capability` and
`_active_trace_id` were added to `__init__` but not copied to the clone,
producing `AttributeError` on every WS chat run until both were added
to the clone path.

### 6.6 Audit data lives in multiple places
| What | Where |
|---|---|
| L1 external-access decisions | `enterprise_root/tenants/<id>/shared/databases/external_access_audit.jsonl` |
| L2 credential resolution decisions | `enterprise_root/tenants/<id>/shared/config/credential_audit.log` |
| L3 hook audit (our test) | `/tmp/l3_audit.log` (configurable per hook) |
| Mock API requests + denies | `/tmp/mock_fin_secure.log` |
| HITL approvals | Redis keys `iaf:approval:*` |
| Cron schedule + runs | Redis keys `iaf:scheduler:*` |
| Trace spans | `enterprise_root/tenants/<id>/shared/databases/traces.db` |
| Evidence bundles | `enterprise_root/tenants/<id>/shared/databases/evidence.db` |

Don't expect everything in the main `/tmp/iaf_claude_server.log` — most
security audit data goes to dedicated stores.

### 6.7 Document path regex misses `.pptx` / `.ppt`
A pre-existing bug discovered during the session: `EvidenceCollector`'s
`_QUOTED_DOC_PATH_RE` in `IAF-Agent-Skills/iaf_agent_skills/document_evidence.py`
didn't include `pptx`/`ppt` in its file-extension whitelist. PowerPoint
files opened via `MarkItDown.convert(...)` were therefore not captured
in evidence bundles, even though the agent answered correctly. Fixed
during the session — added `pptx|ppt|xlsm` to the regex and to the MIME
map.

---

## 7. Files inventory

### Created in this session

| Path | Purpose |
|---|---|
| `onboarding/data/seed_ap_db.py` | Seed ap_regular.db with realistic F&A test data |
| `onboarding/mocks/mock_finance_api_secure.py` | Two-tier mock finance API on port 9092 |
| `onboarding/setup/setup_security_test.py` | Register credentials + patch allowlist YAML |
| `onboarding/setup/test_cron_hitl.py` | End-to-end cron→HITL test driver |
| `enterprise_root/tenants/company/shared/hooks/l3_global_audit.py` | Hook A |
| `enterprise_root/tenants/company/shared/hooks/l3_fa_ap_guard.py` | Hook B |
| `enterprise_root/tenants/company/shared/hooks/l3_payment_url_guard.py` | Hook C |
| `enterprise_root/tenants/company/shared/hooks/l3_onblocked_recorder.py` | OnBlocked observer |
| `docs/SECURITY_TESTING_GUIDE.md` | This document |

### Modified in this session

| Path | Change |
|---|---|
| `agent_os/config.env` | Added `ENTITLEMENTS_ENABLED`, `EXTERNAL_ACCESS_ENABLED`, `EXTERNAL_ACCESS_UNKNOWN_MODE`, `EXTERNAL_ACCESS_AUDIT_ENABLED` |
| `enterprise_root/tenants/company/security/policies.yaml` | Added 3 service-principal `skill:*` grants |
| `enterprise_root/tenants/company/security/external_access.yaml` | Added `external:finance.mock_secure` resource (via setup script) |
| `enterprise_root/tenants/company/shared/config/credentials.yaml` | Added `finance_api_readonly` + `finance_api_admin` (via setup script, encrypted) |
| `enterprise_root/tenants/company/agents/enterprise_agent/config.yaml` | Registered 3 L3 PreToolUse hooks + 1 OnBlocked observer |
| `IAF-Agent-Skills/iaf_agent_skills/agent.py` | Added `tool_execution_capability` + `_active_trace_id` to `clone_for_session()` |
| `IAF-Agent-Skills/iaf_agent_skills/document_evidence.py` | Added `pptx`, `ppt`, `xlsm` to `_QUOTED_DOC_PATH_RE` and `_MIME_MAP` |

---

## 8. Cleanup / reset

### Stop generating new approvals
Pause or delete the test cron via the dashboard, or in Redis:
```
redis-cli -a <REDIS_PASSWORD> HSET iaf:scheduler:job:<job_id> enabled 0
```

### Purge stale HITL approvals
```
for K in $(redis-cli -a <REDIS_PASSWORD> ZRANGE iaf:approval:pending:company 0 -1); do
  redis-cli -a <REDIS_PASSWORD> DEL iaf:approval:$K iaf:approval:agent_state:$K
done
redis-cli -a <REDIS_PASSWORD> DEL iaf:approval:pending:company
```

### Revert side-effects in the seeded DB
```
sqlite3 enterprise_root/tenants/company/shared/databases/ap_regular.db \
  "UPDATE invoices SET status='pending' WHERE invoice_id='INV-3040'; \
   DELETE FROM payments WHERE invoice_id='INV-3040' AND payment_id NOT IN ('PAY-9001','PAY-9002');"
```

Or just rerun the seed script — it drops and recreates every table.

### Stop the mock API
```
pkill -f mock_finance_api_secure.py
```

### Turn enforcement back off (for demos that don't need security gates)
In `agent_os/config.env`:
```
ENTITLEMENTS_ENABLED=false
EXTERNAL_ACCESS_ENABLED=false
```

Restart studio after the change.

---

## 9. Related reading

- [EXTENDING.md](EXTENDING.md) — how to write hooks and capability adapters
- [HOOK_EVENT_REFERENCE.md](HOOK_EVENT_REFERENCE.md) — full catalogue of 24 hook events
- [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md) — HITL approval flow design
- [03_architecture.md](03_architecture.md) — overall request flow
- `enterprise_root/tenants/company/shared/contexts/judgment/fa_judgment.md` — DOA matrix consulted by fa_ap
