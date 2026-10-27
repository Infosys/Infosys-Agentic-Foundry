# Enterprise Root — Multi-Tenant Design

## Overview

IAF AgentPro uses a filesystem-based multi-tenancy model. Each tenant gets a fully isolated directory subtree under `enterprise_root/tenants/{tenant_id}/`. All agent memory, user data, knowledge records, and configuration are scoped within this subtree — tenants cannot access each other's data.

---

## Tenant Isolation

### Filesystem Isolation

```
enterprise_root/
└── tenants/
    ├── company/           ← Tenant A (fully isolated)
    │   ├── config/
    │   ├── agents/
    │   ├── shared/
    │   └── users/
    ├── acmecorp/          ← Tenant B (fully isolated)
    │   ├── config/
    │   ├── agents/
    │   ├── shared/
    │   └── users/
    └── globex/            ← Tenant C (fully isolated)
```

The `tenant_id` is encoded in the directory path. It flows through every layer of the system:

1. **API layer** — All REST endpoints accept `tenant_id` as a query parameter (defaults to `"company"`)
2. **Agent initialization** — `SkillAgent(tenant_id=...)` resolves all paths relative to the tenant root
3. **Kernel** — `SafeKernel(data_root=enterprise_root, tenant_id=...)` sandboxes agents within their tenant
4. **Auth** — `auth_users.db` is per-tenant (`tenants/{tenant_id}/config/auth_users.db`)
5. **Memory** — All JSONL, SQLite, and MD files live under `tenants/{tenant_id}/`

### What Is Per-Tenant

| Resource | Location | Isolated? |
|---|---|---|
| User credentials | `config/auth_users.db` | ✅ Yes |
| Auth audit log | `config/auth_audit.db` | ✅ Yes |
| Admin config | `config/admin_config.json` | ✅ Yes |
| Agent configs | `agents/` | ✅ Yes |
| Agent memory | `agents/{id}/memory/` | ✅ Yes |
| User profiles | `users/`, `agents/{id}/users/` | ✅ Yes |
| Knowledge records | `agents/{id}/memory/context_graph/` | ✅ Yes |
| Shared contexts | `shared/contexts/` | ✅ Yes |
| Business databases | `shared/databases/` | ✅ Yes |
| Entity registry | `agents/{id}/memory/knowledge_index.db` | ✅ Yes |
| Local mount config | `config/tenant_local_mount.json` | ✅ Yes |

### What Is Global (Cross-Tenant)

| Resource | Location | Notes |
|---|---|---|
| Global shared docs | `global_shared/` | Read-only, system-level |
| Model pricing config | `agent_os/model_pricing.yaml` | Not in enterprise_root |

Skill definitions (SKILL.md folders) are **per-tenant**, stored under `tenants/{tenant_id}/skills/` (the default `SKILLS_PATH` resolves to `tenants/company/skills`). A small fallback skill library also ships in `IAF-Agent-Skills/skills/`. Per-tenant customisation is achieved by editing a tenant's own skill folders and by modifying the `context_file` each skill loads.

---

## Agent Isolation Within a Tenant

Within a tenant, agents are also isolated from each other:

```
tenants/company/agents/
├── enterprise_agent/    ← Full ReAct orchestrator (all skills)
│   └── memory/
├── finance_agents/      ← Finance & Accounting domain
│   └── memory/
└── my_personal_agent/   ← Personal assistant agent
    └── memory/
```

Each agent has its own:
- Conversation history
- Knowledge records (context graph)
- User workspaces
- Audit log
- Entity registry (knowledge_index.db)

Agents share the tenant-level `/shared/` directory (read-only from the agent's perspective), which contains the common knowledge base.

---

## User Isolation

Two tiers of user storage exist within a tenant:

### Tier 1: Tenant-Wide User Profile

```
tenants/company/users/{user_id}/profile.md
```

Contains identity, global communication preferences, and cross-agent facts. This is the file agents access as `/me/global.md`.

### Tier 2: Agent-Scoped User Workspace

```
tenants/company/agents/{agent_id}/users/{user_id}/
```

Contains agent-specific context: domain knowledge, working preferences for this agent, notes, uploads, and tasks. This is the file agents access as `/me/profile.md`.

### RBAC Enforcement

The SafeKernel enforces user isolation via `_check_user_access()`:

| Role | Can access |
|---|---|
| `USER` | `/me/` (own folder only) |
| `MANAGER` | Own folder + team members' folders |
| `ADMIN` | All user folders in the agent |
| `AUDITOR` | All user folders (read-only) |

Role is set per-session when the agent is initialized and flows through all path checks.

---

## Shared Resources Within a Tenant

The `tenants/{tenant_id}/shared/` directory is the tenant's shared knowledge base. It is:

- **Read-only for agents** — agents cannot write to `/shared/` directly (enforced by SafeKernel)
- **Writable by admins** — via the Studio UI's Context Manager or File Explorer
- **Loaded as context** — skills declare `context_file: /shared/contexts/p2p_context.md` and it is injected into their system prompt

### Shared Directory Contents

| Path | Purpose | Who writes it |
|---|---|---|
| `Enterprise_Context.md` | Master routing index | Admin (Context Manager) |
| `contexts/*.md` | Process context documents | Admin (Context Manager) |
| `databases/*.db` | Business data | Admin / ETL jobs |
| `policies/*.md` | Business policies | Admin |
| `entities/*.md` | Per-entity knowledge | Agent (via `/learn`) |
| `hooks/*.py` | Automation hooks | Admin (File Explorer) |
| `transcripts/` | Meeting transcripts | Admin / upload |
| `knowledge/` | Miscellaneous KB files | Admin / upload |

---

## Session Scoping

Sessions are scoped to `(tenant_id, agent_id, user_id)`:

**Session ID format:** `{user_id}_{YYYYMMDD}_{HHMMSS}_{random_6hex}`

**Example:** `demo_20260413_092341_a1b2c3`

All conversation history, approval states, and in-flight memory are keyed by this triplet. This means:
- The same user has separate conversation histories per agent
- Multiple users on the same agent have separate histories
- Queue items use `queue_{item_id}` as the user_id for isolation

### Redis Session Store (When Available)

When Redis is running, live session state is stored in Redis for horizontal scaling:

| Key Pattern | Type | TTL | Content |
|---|---|---|---|
| `iaf:session:{tenant}:{user}:state` | HASH | 24h | `AgentStateSnapshot` |
| `iaf:session:{tenant}:{user}:history` | LIST | 24h | Recent messages |
| `iaf:session:index:{tenant}` | ZSET | 24h | Users by `last_active_at` |

When Redis is unavailable, sessions fall back to in-memory storage (lost on server restart).

---

## Adding a New Tenant

To add a new tenant named `acmecorp`:

1. **Create the directory structure:**
   ```bash
   mkdir -p enterprise_root/tenants/acmecorp/config
   mkdir -p enterprise_root/tenants/acmecorp/agents
   mkdir -p enterprise_root/tenants/acmecorp/shared/contexts
   mkdir -p enterprise_root/tenants/acmecorp/shared/databases
   mkdir -p enterprise_root/tenants/acmecorp/shared/policies
   mkdir -p enterprise_root/tenants/acmecorp/users
   ```

2. **Create Enterprise_Context.md** with the tenant's process taxonomy.

3. **Initialize auth database** (automatic on first login attempt when `AUTH_ENABLED=true`).

4. **Create at least one agent** via `POST /api/agents?tenant_id=acmecorp`.

5. **Configure admin_config.json** if needed:
   ```json
   {"CONTEXT_LOADING_MODE": "file"}
   ```

6. **Access the tenant** by passing `tenant_id=acmecorp` in all API calls.

---

## Tenant Configuration (`admin_config.json`)

Stored at `tenants/{tenant_id}/config/admin_config.json`. Parameters set here override server defaults for this tenant.

| Parameter | Type | Description |
|---|---|---|
| `QUEUE_BACKEND` | string | `"redis"` or `"sqlite"` |
| `CONTEXT_LOADING_MODE` | string | `"file"` or `"db"` |
| `ROUTER_CONFIDENCE_THRESHOLD` | float | Minimum routing confidence (0-1) |
| `MAX_TURNS_BEFORE_COMPACTION` | int | Turns before session history is summarised |
| `KNOWLEDGE_AUTO_CONFIRM_THRESHOLD` | float | Confidence above which knowledge is auto-confirmed |

Changes take effect on next agent initialization or via `POST /api/admin-config/reload`.
