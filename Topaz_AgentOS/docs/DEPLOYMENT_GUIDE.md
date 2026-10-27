# IAF AgentOS — Deployment Guide

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.13 recommended |
| Redis | 6+ | AOF persistence enabled recommended |
| **LLM provider** | one of: Azure OpenAI · OpenAI-compatible (vLLM, Ollama, etc.) · Google Vertex AI (Gemini) | GPT-4o or Gemini 2.5 Flash recommended |
| OS | macOS, Ubuntu, Windows (WSL2) | |

---

## Fresh Install

Partner / partial adoption (kernel-only or embed engine without Studio) → **[PARTNER_INSTALL_GUIDE.md](PARTNER_INSTALL_GUIDE.md)**.

### 1. Clone the repo
```bash
git clone https://github.com/Infosys-Generative-AI/IAF_AgentOS.git
cd IAF_AgentOS
```

### 2. Install Python dependencies
```bash
pip install -r IAF-Agent-Skills/requirements.txt
pip install -r IAF-Agent-Studio/requirements.txt
pip install -e IAF-Agent-Skills/
```

### 3. Create LLM config
```bash
cp IAF-Agent-Skills/config.env.example IAF-Agent-Skills/config.env
```

Edit `IAF-Agent-Skills/config.env`. Pick **one** of the three provider blocks below.

**Option A — Azure OpenAI** (default, requires Azure resource):
```env
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

**Option B — OpenAI-compatible** (vLLM, Ollama, OpenAI direct, etc.):
```env
OPENAI_BASE_URL=http://<vllm-host>:8004/v1
OPENAI_MODEL_NAME=google/gemma-3-27b
OPENAI_API_KEY=<key-or-none>
```

**Option C — Google Vertex AI (Gemini)** — service-account auth, no API key:
```env
LLM_PRIMARY_PROVIDER=vertex
LLM_PRIMARY_MODEL=gemini-2.5-flash
VERTEX_PROJECT=<your-gcp-project>
VERTEX_LOCATION=us-central1
VERTEX_SA_KEY_PATH=/absolute/path/to/sa-key.json
# Optional — only if your corporate proxy does SSL inspection (e.g. Zscaler):
# VERTEX_CA_BUNDLE=/path/to/combined-ca-bundle.pem
```

To use **mixed providers per role** (e.g. Gemini for primary, Azure for fallback), use the hybrid block in `config.env.example` — set `LLM_PRIMARY_PROVIDER=vertex` and `LLM_FALLBACK_PROVIDER=azure` etc.

### 4. Create credentials file (for skills that call external systems)
```bash
mkdir -p IAF-Agent-Skills/config
```

Create `IAF-Agent-Skills/config/credentials.yaml`:
```yaml
<service_name>:
  token: <value>
<another_service>:
  username: <value>
  password: <value>
```

### 5. Start Redis
```bash
# macOS
brew install redis && brew services start redis

# Ubuntu/Debian
sudo apt install redis-server && sudo systemctl start redis-server

# Verify
redis-cli ping   # should return PONG
```

### 6. Start the server
```bash
cd IAF-Agent-Studio
python3 server.py
```

Open **http://localhost:8080** for chat, or **http://localhost:8080/studio** for the unified Studio/Customize surface for skills, schedules, knowledge, connectors, agents, and run monitoring. Domain-specific dashboards can be added as an optional solution module under `solution_modules/`; see [SOLUTION_MODULES.md](SOLUTION_MODULES.md).

For ad-hoc live smoke and security validation after deployment, use the scripts
under `scripts/verification/` and follow [SECURITY_TESTING_GUIDE.md](SECURITY_TESTING_GUIDE.md).

---

## Running Multiple Instances

Each instance needs a unique port. Use the `PORT` env var:

```bash
# Terminal 1
cd IAF_AgentOS_8081/IAF-Agent-Studio && PORT=8081 python3 server.py

# Terminal 2
cd IAF_AgentOS_8082/IAF-Agent-Studio && PORT=8082 python3 server.py
```

All instances can share the same Redis (sessions and cron jobs are tenant-scoped).

---

## Environment Variables Reference

All vars are loaded from the first `config.env` found in this order:
`IAF-Agent-Studio/config.env` → `agent_os/config.env` → `IAF-Agent-Skills/config.env` → `.env`

### Required — pick one provider's variables

**For Azure OpenAI (default):**
| Variable | Description |
|---|---|
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | Primary model deployment name |

**For OpenAI-compatible (vLLM/Ollama/OpenAI direct):**
| Variable | Description |
|---|---|
| `OPENAI_BASE_URL` | Base URL of the OpenAI-compatible server |
| `OPENAI_MODEL_NAME` | Model identifier (e.g. `google/gemma-3-27b`) |
| `OPENAI_API_KEY` | API key (use `none` for local servers) |

**For Google Vertex AI (Gemini) — service-account auth:**
| Variable | Description |
|---|---|
| `LLM_PRIMARY_PROVIDER` | Set to `vertex` |
| `LLM_PRIMARY_MODEL` | Gemini model (e.g. `gemini-2.5-flash`, `gemini-2.5-pro`) |
| `VERTEX_PROJECT` | GCP project id |
| `VERTEX_SA_KEY_PATH` | Absolute path to the service-account JSON key file |
| `VERTEX_LOCATION` | GCP region (default `us-central1`) |
| `VERTEX_CA_BUNDLE` | (optional) PEM bundle for corporate SSL inspection — Zscaler/MITM environments |
| `VERTEX_TEMPERATURE` | (optional, default `0.7`) |

### Optional (defaults shown)
| Variable | Default | Description |
|---|---|---|
| `PORT` | `8081` | Server port |
| `HOST` | `127.0.0.1` | Bind address (`0.0.0.0` for network access) |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `DB_BACKEND` | `sqlite` | Relational store: `sqlite` (single-node) or `postgres` (multi-node/HA). See **[STORAGE_BACKENDS.md](STORAGE_BACKENDS.md)**; to switch, follow **[POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md)** |
| `DATABASE_URL` | empty | Postgres DSN; required when `DB_BACKEND=postgres` |
| `DB_POOL_SIZE` | `10` | Max pooled Postgres connections |
| `VECTOR_BACKEND` | `brute_force` | `brute_force` \| `sqlite_vec` \| `pgvector` (pgvector needs `DB_BACKEND=postgres`) |
| `DATA_ROOT` | `../enterprise_root` | Path to enterprise_root |
| `SKILLS_PATH` | `../enterprise_root/tenants/company/skills` | Path to skills folder |
| `TENANT_ID` | `company` | Tenant under enterprise_root/tenants/ |
| `AGENT_ID` | `enterprise_agent` | Agent config folder name |
| `QUEUE_BACKEND` | `memory` | `memory` or `redis` |
| `AUTH_ENABLED` | `false` | Enable JWT login |
| `AUTH_PROVIDER` | `local` | Access-token identity provider: `local` for Studio-issued HS JWTs, or `microsoft`/`entra`/`oidc`/`okta` for OIDC/JWKS validation |
| `AUTH_OIDC_ISSUER` | empty | Expected OIDC issuer when an enterprise provider is selected |
| `AUTH_OIDC_AUDIENCE` | empty | Expected OIDC audience/client ID when an enterprise provider is selected |
| `AUTH_OIDC_JWKS_URL` | empty | JWKS endpoint used to validate RS256 OIDC access tokens |
| `AUTH_OIDC_JWKS_CACHE_SECONDS` | `300` | JWKS cache TTL; clamped between 30 seconds and 24 hours |
| `AUTH_OIDC_ROLE_CLAIMS` | `roles role` | Space-separated claim names used to map token roles into `IdentityContext.roles` |
| `AUTH_OIDC_GROUP_CLAIMS` | `groups` | Space-separated claim names used to map token groups into `IdentityContext.groups` |
| `AUTH_OIDC_TENANT_CLAIMS` | `tenant_id tid` | Space-separated claim names used to map token tenant into `IdentityContext.tenant_id` |
| `ENTITLEMENTS_ENABLED` | `false` | Enable policy checks for tenants, agents, skills, tools, credentials, context, and Studio operations |
| `ENTITLEMENTS_PROVIDER` | `yaml` | Policy provider; YAML reads `enterprise_root/tenants/{tenant_id}/security/policies.yaml` |
| `ENTITLEMENTS_FAIL_CLOSED` | `true` | Deny access when no matching policy exists |
| `ENTITLEMENTS_ENFORCEMENT_MODE` | `enforce` | Policy enforcement mode: `enforce` fails closed on denies/provider errors; `observe` records would-deny decisions but allows execution for rollout validation |
| `ENTITLEMENTS_AUDIT_ENABLED` | `true` | Write entitlement decisions to `shared/databases/entitlements_audit.jsonl` |
| `AUDIT_EVIDENCE_MIRROR_ENABLED` | `false` | Mirror bounded audit/evidence summaries to log-compatible JSONL files while preserving local authoritative stores |
| `AUDIT_EVIDENCE_MIRROR_DIR` | empty | Directory for optional mirror files; records are written per tenant and redacted before write |
| `AUDIT_EVIDENCE_PREVIEW_LIMIT` | `1024` | Maximum string preview length emitted to audit/evidence mirror records; clamped by the sink layer |
| `EXTERNAL_ACCESS_ENABLED` | follows `ENTITLEMENTS_ENABLED` | Enable governance for external credentials, DBs, MCP connections, and audited curl targets |
| `EXTERNAL_ACCESS_UNKNOWN_MODE` | `audit` | Behaviour for unregistered external targets: `allow`, `audit`, or `deny` |
| `EXTERNAL_ACCESS_ENFORCE_CREDENTIALS` | follows `EXTERNAL_ACCESS_ENABLED` | Require entitlement to a linked `external:*` resource before `get_credential` returns a masked variable |
| `EXTERNAL_ACCESS_ENFORCE_MCP` | follows `EXTERNAL_ACCESS_ENABLED` | Require `mcp:*` or linked `external:*` access before MCP discovery/execution |
| `EXTERNAL_ACCESS_ENFORCE_SQL` | follows `EXTERNAL_ACCESS_ENABLED` | Require `external:db.<name>` access for `run_sql_query` and Python `sqlite3` database access |
| `SECRET_PROVIDER` | `local` | Secret provider selected by `SafeKernel.get_credential`; only `local`/`credential_store` is implemented in this MVP and delegates to the existing env/file/Fernet `CredentialStore` |
| `IAF_REACT_RUNTIME` | `langgraph` | Implementation runtime for `execution_mode=react`: `langgraph` preserves the current path; `native` uses Azure OpenAI native tool calls through the configured primary model |
| `IAF_REACT_NATIVE_FALLBACK_ON_ERROR` | `true` | When `native` is selected but unavailable or malformed, fall back to LangGraph for that request instead of failing the turn |
| `IAF_REACT_NATIVE_MAX_ITERATIONS` | `8` | Maximum model/tool turns in one native React request before failing safely |
| `TRACE_TELEMETRY` | `true` | Enable local execution trace writes to `traces.db` |
| `TWIN_TELEMETRY` | `true` | Enable local operational twin writes to `twin_telemetry.db` |
| `TELEMETRY_EXPORTERS` | `local` | Comma-separated telemetry mirrors. `local` preserves SQLite-only default; add `otlp` to mirror sanitized events to OTLP JSON HTTP |
| `TELEMETRY_OTLP_ENDPOINT` | empty | OTLP JSON HTTP collector endpoint used only when `TELEMETRY_EXPORTERS` includes `otlp` |
| `TELEMETRY_OTLP_SERVICE_NAME` | `iaf-agent-studio` | Service name included in mirrored telemetry payloads |
| `TELEMETRY_TIMEOUT_SECONDS` | `2.0` | Per-call timeout for external telemetry providers |
| `TELEMETRY_PREVIEW_LIMIT` | `512` | Maximum string preview length forwarded to external telemetry providers; clamped between 64 and 4096 |
| `LOG_LEVEL` | `INFO` | Logging level |

Telemetry provider smoke validation can be run without external credentials:

```bash
cd IAF-Agent-Studio && python3 tests/run_telemetry_provider_e2e.py
```

The script starts a local HTTP collector, sends real trace and twin events through the OTLP JSON adapter, and verifies the mirrored payloads are redacted while `traces.db` and `twin_telemetry.db` still persist locally. Trace rows that pause for approval finalize as `awaiting_human` with token/cost totals; old unfinished rows are surfaced to the dashboard as `stale`.

Identity provider smoke validation can be run against a live auth-enabled server:

```bash
AUTH_ENABLED=true AUTH_BACKEND=sqlite AUTH_REGISTRATION_MODE=open JWT_SECRET=identity-e2e-secret PORT=18080 python3 IAF-Agent-Studio/server.py 2>&1
AGENTPRO_BASE_URL=http://127.0.0.1:18080 python3 IAF-Agent-Studio/tests/run_identity_provider_e2e.py
```

The live smoke exercises registration, login, protected `/auth/me`, and a tenant-bound conversation-list call through the middleware. OIDC/Entra/Okta validation is sandbox-ready through mocked JWKS contract tests; full enterprise validation requires a customer or demo tenant issuer, audience, and JWKS endpoint.

Secret provider smoke validation can be run without cloud vault credentials:

```bash
PYTHONPATH="IAF-Agent-Studio:IAF-Agent-Skills:." python3 IAF-Agent-Studio/tests/run_secret_provider_e2e.py
```

The script creates a temporary tenant root, writes a real local `credentials.yaml`, loads it through the default `CredentialStoreSecretProvider`, and verifies `SafeKernel.run_shell_command("get_credential ...")` returns only the masked placeholder while provider health/audit output stays redacted.

When YAML entitlements are enabled, admins can operate the same tenant policy file from Studio's Security Console. The console validates policy YAML before saving, simulates decisions for roles/groups/resources, shows effective access across live agents, skills, tools, and context files, and reads recent entitlement decisions from `enterprise_root/tenants/{tenant_id}/shared/databases/entitlements_audit.jsonl`.

Policy provider smoke validation can be run without OPA/Azure credentials:

```bash
PYTHONPATH="IAF-Agent-Studio:IAF-Agent-Skills:." python3 IAF-Agent-Studio/tests/run_policy_provider_e2e.py
```

The script creates a temporary tenant policy, routes decisions through the real security dependency helper and selected YAML provider, verifies fail-closed deny behaviour, then switches to observe mode and verifies the same denied policy is allowed with audit metadata showing the observed deny. Audit context is bounded and redacts token/secret-shaped keys.

Audit/evidence sink smoke validation can be run without enterprise log collector credentials:

```bash
PYTHONPATH="IAF-Agent-Studio:IAF-Agent-Skills:." python3 IAF-Agent-Studio/tests/run_audit_evidence_sink_e2e.py
```

The script creates a temporary tenant, writes an entitlement audit decision through the audit sink fanout, persists a real evidence bundle through `EvidenceCollectorAdapter`, and verifies local JSONL, local SQLite, and optional JSONL mirror records. Mirror output is bounded and redacts bearer tokens, password/token/secret-shaped fields, and prompt-sized strings before write.

Deferred provider-family guardrails can be run without external systems:

```bash
PYTHONPATH="IAF-Agent-Studio:IAF-Agent-Skills:." python3 -m pytest IAF-Agent-Studio/tests/test_deferred_provider_boundaries.py -q
```

These tests intentionally do not introduce queue, approval, memory/vector, or taxonomy provider adapters. They verify the capability snapshot marks those families as deferred, keeps queue/cron and HITL approval on existing local/Redis singletons, keeps memory writes direct unless `IAF_MEMORY_CAPABILITY_ENABLED=true`, and confirms taxonomy shadow comparisons never replace the current routing result. Future Azure Service Bus, Kafka, SQS, ServiceNow, Jira, Teams workflow, vector DB, or alternate taxonomy providers should start from these tests and change the runtime-resolution contract deliberately.

For any new enterprise provider adapter, follow [ADAPTER_AUTHORING_GUIDE.md](ADAPTER_AUTHORING_GUIDE.md). Treat local/fake/sandbox tests as contract validation only; real Entra, Key Vault, Vault, OPA, Splunk, Azure Monitor, Datadog, ServiceNow, or customer workflow validation requires a customer or demo environment with approved credentials. Production rollout should include a local-provider fallback, safe capability diagnostics, and a documented rollback profile.

External access governance uses `enterprise_root/tenants/{tenant_id}/security/external_access.yaml` to map business systems to credentials, MCP connections, databases, context files, and tools. Normal policies grant `external:*` resources; the kernel enforces credential loading by checking the linked external resource and returns only masked `$CRED_*` variables to the LLM. Direct `credential:*` policy grants are reserved for exceptional secret-specific overrides.

The default `company` policy intentionally avoids a broad `skill:*` grant for standard users. Authenticated users can use the default `general` skill, while domain skills require JWT group claims: `finance` for all F&A skills plus finance external systems and governed tenant DB access, `finance-ap`, `finance-ar`, or `finance-gl` for specialist finance access, `it-ops`/`sre`/`platform-ops` for `ccdops` plus Kubernetes/CheckMK external access, and `ai-programs`/`executive`/`leadership` with the `manager` role for `ai_pursuit_to_deployment_pods`.

### Service Principals for Non-Interactive Entry Points

Cron jobs, queue items, and HITL resume operations run without an HTTP request — no JWT, no
header-based identity. To ensure external access gates still enforce, each entry point creates a
service `IdentityContext` and exports it as a **service principal** before calling `agent.run()`:

| Entry Point | Group | Default User ID | Source |
|---|---|---|---|
| Cron executor | `service:cron` | Job's `user_id` or `system:cron` | `shared/state.py` |
| Queue processor | `service:queue` | `system:queue` | `cc_queue/processor.py` |
| HITL resume | `service:hitl_resume` | Approval's `user_id` or `system:hitl_resume` | `routers/approvals.py`; approval resume also passes through `OnApprovalResolved`, `BeforeApprovalResume`, and `AfterApprovalResume` hooks; Mission Mode resumes are item-anchored, run in fresh mode, and finalize `done`/`failed` only after resumed work returns; successful resumes update the visible item result and append a `hitl_resume` execution-ledger row; follow-up approvals re-pause the item |

Workstream-linked HITL decisions also write a non-blocking
`source=hitl_feedback`, `status=pending_review` Knowledge Manager candidate from
the approval decision, optional approver note, approval reason, and item context.

The default `company` tenant ships with broad `external:*` grants for all three groups. **In
production, tighten these policies** to the specific external resources each background path
actually needs.

> **Config footgun:** Setting `EXTERNAL_ACCESS_ENABLED=true` without `ENTITLEMENTS_ENABLED=true`
> has no effect — the server logs a startup warning when this misconfiguration is detected.

For release validation, `IAF-Agent-Studio/tests/run_security_entitlements_live.py` runs a reversible live integration check against a running server. It backs up the active tenant policy through `/api/security/policies`, applies a temporary restrictive policy, verifies allow/deny decisions and the effective-access endpoint, then restores the original YAML byte-for-byte.

### Central Policy & Control Registry

Dashboard V2's Policy Control page stores business-friendly governance policies in:

```text
enterprise_root/tenants/{tenant_id}/security/policy_control.yaml
```

The registry page also reads the selected agent's existing `config.yaml` `hooks:` section and displays tenant-authored Skill Builder hooks as read-only unmanaged hook-backed controls. These controls are visible in the central inventory immediately; use **Adopt as Policy Draft** to copy one into `policy_control.yaml` with owner, risk, evidence, and HITL metadata before publishing it as a managed policy.

Published active policies compile into the selected agent's existing `config.yaml` `hooks:` section. The publish path preserves manual hooks and replaces only the generated hook whose id matches `policy.{policy_id}.v{version}`. Generated hooks call:

```bash
python3 $IAF_AGENT_ROOT/../../shared/hooks/policy_engine.py --policy-id <policy_id>
```

The policy engine evaluates deterministic condition operators (`contains`, `regex`, numeric comparisons, `exists`, and membership checks) against hook environment context such as `IAF_TOOL_INPUT`, `IAF_TOOL_NAME`, `IAF_CURRENT_SKILL`, `IAF_TRACE_ID`, and extracted values like command amount. It returns the normal hook JSON result and exit code; no policy-authored Python is executed.

Use `decision: approve` with `event: PreToolUse` for HITL controls. The blocking hook result is converted by the existing tool governance path into the current Redis-backed HITL checkpoint/resume flow, so approval cards, queue/workstream pauses, and exact pending-tool replay remain unchanged.

---

## Using Google Vertex AI (Gemini)

The Vertex provider uses a **service-account JSON key file** for authentication — no API keys, no `gcloud` CLI required at runtime. The implementation lives in [vertex_chat.py](IAF-Agent-Skills/iaf_agent_skills/vertex_chat.py) and is registered in [model_registry.py](IAF-Agent-Skills/iaf_agent_skills/model_registry.py).

### Prerequisites

1. A GCP project with the **Vertex AI API enabled**
2. A service account in that project granted **`roles/aiplatform.user`**
3. A downloaded JSON key for that service account (from IAM & Admin → Service Accounts → Keys → ADD KEY)
4. `PyJWT` and `cryptography` packages installed (both standard in IAF AgentOS requirements)

### Supported models

| Model | Status | Notes |
|---|---|---|
| `gemini-2.5-flash` | ✅ Fast, cheap | Recommended default |
| `gemini-2.5-pro` | ✅ Most capable | Higher latency + cost |
| `gemini-1.5-*`, `gemini-2.0-*` | ⚠ May 404 | Older models require explicit project enablement |

### Configuration

```env
LLM_PRIMARY_PROVIDER=vertex
LLM_PRIMARY_MODEL=gemini-2.5-flash
VERTEX_PROJECT=<your-gcp-project>
VERTEX_LOCATION=us-central1
VERTEX_SA_KEY_PATH=/absolute/path/to/sa-key.json
VERTEX_TEMPERATURE=0.7
```

You'll see on startup:
```
🏭 ModelRegistry: 'primary' → gemini-2.5-flash [vertex/hybrid]
```

### Mixed providers (Gemini + Azure)

You can mix providers per role. Common pattern: Gemini for primary reasoning, cheap Azure for the light classifier:

```env
LLM_PRIMARY_PROVIDER=vertex
LLM_PRIMARY_MODEL=gemini-2.5-flash
VERTEX_PROJECT=<your-gcp-project>
VERTEX_SA_KEY_PATH=/path/to/sa-key.json

LLM_LIGHT_PROVIDER=azure
LLM_LIGHT_MODEL=gpt-4o-mini
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
```

### Corporate proxy / SSL inspection (Zscaler, etc.)

If your network does SSL interception, the standard cert chain validation will fail with errors like *"Basic Constraints of CA cert not marked critical"*. You need to point IAF AgentOS at a CA bundle that includes the corporate root certificate:

1. Build a combined PEM bundle (mac example):
   ```bash
   # Export trusted roots from the macOS system keychain (includes the corporate CA)
   security find-certificate -a -p /Library/Keychains/System.keychain > /tmp/sys_certs.pem
   # Combine with certifi's default bundle
   python3 -c "
   import certifi, pathlib
   pathlib.Path('/tmp/combined_ca_bundle.pem').write_text(
       pathlib.Path(certifi.where()).read_text() + '\n' +
       pathlib.Path('/tmp/sys_certs.pem').read_text()
   )"
   ```
2. Point IAF at it:
   ```env
   VERTEX_CA_BUNDLE=/tmp/combined_ca_bundle.pem
   ```

The wrapper auto-relaxes Python's strict X.509 validation (still verifies chain + hostname) so corporate certs with non-critical Basic Constraints are accepted. See [vertex_chat.py](IAF-Agent-Skills/iaf_agent_skills/vertex_chat.py) `_get_ssl_context()`.

### Limitations (Phase 1)

- **No streaming yet** — responses arrive whole-message, not token-by-token. The UI shows the answer when fully ready.
- **Tool calling works** — `invoke_skill`, `create_plan`, etc. all execute correctly through the Vertex function-calling API.
- **No async/`_agenerate`** — `_generate` is called synchronously. Sufficient for normal request flow.

A future Phase 2 may add `_stream()` via Vertex's `streamGenerateContent` SSE endpoint.

---

## Folder Structure — What Must Exist

```
enterprise_root/
└── tenants/
    └── {TENANT_ID}/
        ├── agents/
        │   └── {AGENT_ID}/
        │       └── config.yaml          # Required
        ├── skills/
        │   ├── _index.yaml              # Required — skill registry
        │   └── {skill}/SKILL.md         # One per skill
        └── shared/
            ├── Enterprise_Context.md    # Required — routing index
            ├── contexts/                # Domain knowledge files
            ├── databases/evidence.db    # Auto-created evidence audit store
            └── hooks/                   # Hook scripts (optional)
```

**Hardcoded folder names** (cannot rename): `tenants/`, `agents/`, `shared/`, `users/`, `memory/`, `SKILL.md`, `_index.yaml`

**Configurable via env**: `DATA_ROOT`, `SKILLS_PATH`, `TENANT_ID`, `AGENT_ID`

---

## Evidence Source Providers

Evidence originals are streamed through `IAF-Agent-Studio/shared/document_source.py`.

Built-in behavior:

- `LocalSource` is production-ready for tenant-scoped SafeKernel paths: `/shared/...`, `/me/...`, `/local/...`, and `file://...`.
- `/local/...` can use `users/{user_id}/local_mount.json` or `config/tenant_local_mount.json` to map evidence originals to enterprise file shares.
- Remote provider classes are registered as explicit integration points: `SharePointSource`, `AzureBlobSource`, `S3Source`, and `URLSource`.

Remote provider URI conventions:

| Source | URI Prefix | Developer Implementation Point |
|---|---|---|
| SharePoint / OneDrive | `sharepoint://tenant/site/library/path/file.ext` | Implement Microsoft Graph download in `SharePointSource.resolve()` |
| Azure Blob | `azblob://account/container/path/file.ext` | Implement Azure SDK BlobClient download in `AzureBlobSource.resolve()` |
| AWS S3 | `s3://bucket/key` | Implement boto3 `get_object` download in `S3Source.resolve()` |
| HTTP(S) URL | `https://host/path/file.ext` | Implement allowlisted HTTP fetch in `URLSource.resolve()` |

Remote providers should return `DocumentContent(payload=downloaded_bytes, display_name=..., mime_type=...)`. Keep credentials in the platform credential store or environment, not in `SKILL.md`. For URL sources, add SSRF controls before enabling: host allowlists, blocked private IP ranges, redirect limits, file size limits, and content-type validation.

---

## Upgrading an Existing Install

```bash
cd IAF_AgentOS
git pull origin main

# Clear Python cache to avoid stale bytecode
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true

cd IAF-Agent-Studio && python3 server.py
```

---

## Migrating Skills from Old Install

If upgrading from a version where skills lived in `IAF-Agent-Skills/skills/`:

```bash
# Copy your custom skills to the new location
cp -r <old-install>/IAF-Agent-Skills/skills/<skill-name>/ \
      enterprise_root/tenants/company/skills/
```

Skills now live in `enterprise_root/tenants/company/skills/` — the engine package ships without any skill definitions.

---

## Production Checklist

- [ ] Redis persistence enabled (`appendonly yes` in redis.conf)
- [ ] `HOST=0.0.0.0` if serving on a network interface
- [ ] `AUTH_ENABLED=true` with a strong `JWT_SECRET`
- [ ] `ENTITLEMENTS_ENABLED=true` with tenant policy files reviewed; do not rely on entitlements with `AUTH_ENABLED=false` outside local development
- [ ] `AGENT_PYTHON3_SANDBOX_USER` set to a restricted OS user
- [ ] SSL cert configured (`SSL_CERTFILE`, `SSL_KEYFILE`) for HTTPS
- [ ] Log rotation configured (server writes rotating JSON logs to `logs/`)
- [ ] Redis password set (`REDIS_URL=redis://:password@host:6379`)

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Error: Unexpected token 'I'...` in UI | Redis not running | Start Redis — `brew services start redis` |
| `401 Unauthorized` on all API calls | Auth enabled, no token | Set `AUTH_ENABLED=false` or login first |
| `Token expired` from K8s skill | Bearer token expired | Contact cluster admin to regenerate |
| Skills not loading | Wrong `SKILLS_PATH` | Verify path points to folder containing skill subfolders |
| Stale behaviour after update | `.pyc` cache | `find . -name "*.pyc" -delete` then restart |
| `ConnectionRefusedError` | Redis not running | `redis-cli ping` to verify |
