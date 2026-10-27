# Enterprise Root — Directory Structure

## Overview

`enterprise_root` is the data store for IAF AgentPro. It is a filesystem-based database: all agent state, user memory, knowledge records, conversation history, and business databases live here. The structure is hierarchical: data flows from the global level down through tenants → agents → users.

**Default location:** `enterprise_root/` in the AgentPro project root.

---

## Top-Level Layout

```
enterprise_root/
├── docs/                           Documentation
├── global_shared/                  Cross-tenant shared resources (read-only for agents)
├── recyclebin/                     Soft-deleted enterprise resources
│   └── agents/
│       └── {agent_id}/             Tombstone with full agent structure
└── tenants/                        PRIMARY: One directory per tenant
    └── company/                    Default tenant
        ├── config/                 Tenant-level configuration
        ├── agents/                 Agents for this tenant
        ├── skills/                 Tenant-scoped skill library (SKILL.md folders)
        ├── workstreams/            Workstream/automation definitions (*.yaml)
        ├── security/               Entitlement policies and roles
        ├── scheduler/              Scheduled job definitions
        ├── automations/            Automation runtime state
        ├── shared/                 Tenant-wide shared resources
        └── users/                  Global user profiles (tenant-level)
```

---

## Tenant Structure

```
tenants/{tenant_id}/
├── config/
│   ├── tenant_local_mount.json     Local filesystem mount config
│   ├── admin_config.json           Admin parameter overrides
│   ├── harness_profiles.yaml       Harness run profiles
│   ├── privacy_notice.md           Data privacy notice text
│   ├── auth_users.db               User credentials (SQLite)
│   └── auth_audit.db               Authentication audit log (SQLite)
│
├── agents/
│   ├── enterprise_agent/           Master orchestrator (primary agent)
│   ├── finance_agents/             Finance & Accounting domain agent
│   └── my_personal_agent/          Personal assistant agent
│
├── shared/
│   ├── Enterprise_Context.md       Master routing index (L1/L2 taxonomy)
│   ├── context_registry.json       Structured registry of all context items
│   ├── context_tree_cache.json     LLM-clustered tree (1h cache)
│   ├── entity_validation.yaml      Entity allowlist/blocklist for registry
│   ├── config/                     Shared configuration
│   ├── contexts/                   Process context documents
│   │   ├── p2p_context.md          Procure-to-Pay context
│   │   ├── o2c_context.md          Order-to-Cash context
│   │   ├── r2r_context.md          Record-to-Report context
│   │   ├── fpa_context.md          FP&A context
│   │   ├── i2c_package_context.md  Invoice-to-Cash package
│   │   ├── i2p_package_context.md  Invoice-to-Pay package
│   │   ├── p2p_package_context.md  P2P package
│   │   ├── discovery_context.md    Discovery methodology
│   │   ├── ccdops_context.md       CCD Operations
│   │   ├── itops_context.md        IT Operations
│   │   ├── ccdops_apis.md          CCD API reference
│   │   ├── p2p_apis.md             P2P API reference
│   │   ├── itops_apis.md           IT Ops API reference
│   │   └── entities/               Per-entity knowledge files (e.g. CUST_001_<Name>.md)
│   ├── databases/                  Business data stores
│   │   ├── automation_runtime.db   Automation runtime state
│   │   ├── command_center.db       Command Center / queue
│   │   ├── connections_demo.db     Demo connection configs
│   │   ├── evidence.db             Enterprise evidence store
│   │   ├── fpna.db                 FP&A data
│   │   ├── r2r.db                  Record-to-Report data
│   │   ├── rl.db                   Reinforcement-learning capture
│   │   ├── traces.db               Execution traces
│   │   ├── twin_telemetry.db       Agent telemetry
│   │   ├── workstream_runtime.db   Workstream runtime state
│   │   └── *_schema.md             Auto-generated table schemas
│   ├── component_templates/        Reusable component templates
│   ├── docs/                       Shared documentation
│   ├── scripts/                    Shared helper scripts
│   ├── hooks/                      Automation hooks (Python/Shell)
│   ├── knowledge/                  Shared knowledge base files
│   ├── policies/                   Business policy documents (currently empty)
│   └── skill_submissions/          Skill contribution review queue
│
└── users/
    ├── demo/                       Human user — global profile
    ├── madhan/
    ├── admin/
    ├── queue_processor/            System user for queue processing
    └── ...
```

---

## Agent Structure

Each agent has an identical directory structure:

```
agents/{agent_id}/
│
├── memory/
│   ├── master_index.json           Session index (topics, entities, timestamps)
│   ├── conversations_index.json    Conversation list (titles, turn counts, skills used)
│   ├── knowledge_index.db          SQLite FTS5 + vector index for knowledge records
│   ├── MEMORY.md                   Auto-generated memory index (max 500 lines)
│   │
│   ├── history/                    Conversation history (Layer 1 memory)
│   │   └── {YYYY-MM-DD}/
│   │       └── {user_id}_{session_id}.jsonl   One file per session
│   │
│   ├── learnings/                  Per-skill learning artifacts (Layer 3)
│   │   └── {skill_id}/
│   │       ├── tool_execution.jsonl
│   │       └── agent_error.jsonl
│   │
│   ├── context_graph/              Knowledge records (Layer 2 memory)
│   │   ├── knowledge.jsonl         Current confirmed knowledge
│   │   ├── knowledge_pending.jsonl Awaiting review
│   │   └── archive/
│   │       └── knowledge_{timestamp}.jsonl   Snapshots
│   │
│   ├── org/                        Org-level entity memory (enterprise_agent only)
│   │   ├── shared_context.md
│   │   ├── p2p_context.md
│   │   ├── o2c_context.md
│   │   └── ...
│   │
│   ├── users/
│   │   └── {user_id}/
│   │       └── preferences/        Per-user learning preferences
│   │
│   └── skills/
│       └── {skill_id}.md           Skill capability descriptions (34 for enterprise_agent)
│
├── users/                          Agent-scoped user workspaces
│   └── {user_id}/
│       ├── profile.md              Agent-specific user profile
│       ├── tasks/                  User's task list
│       ├── uploads/                Files uploaded by user
│       ├── discovery/              Discovery work artifacts
│       ├── notes/                  User notes
│       ├── logs/                   User-level activity logs
│       ├── escalations/            Escalation records
│       └── settings/               User preferences
│
├── teams/                          Team workspaces (RBAC-controlled)
│   └── {team_id}/
│
├── workspace/                      Agent scratchpad (writable by all users)
│
├── .audit/                         Audit trail (not accessible via virtual paths)
│   └── commands_{YYYY-MM-DD}.jsonl
│
└── .index/                         Vector store index (not accessible via virtual paths)
```

---

## User Hierarchy

### Global User (`tenants/company/users/{user_id}/`)

Tenant-level user profile applying across all agents:
- `profile.md` — identity, communication style, global preferences

### Agent-Scoped User (`agents/{agent_id}/users/{user_id}/`)

Per-agent workspace with agent-specific profile:
- `profile.md` — domain context and preferences for this specific agent
- `tasks/` — in-flight task notes
- `uploads/` — files the user has uploaded for processing
- `notes/` — persistent notes and observations
- `escalations/` — escalation records created by this user

### User Types

| Type | Examples | Notes |
|---|---|---|
| Human | `demo`, `madhan`, `admin` | Interactive users |
| System | `queue_processor`, `scheduler` | Automated processes |
| Queue | `queue_CC-A1B2C3D4` | One per queue item, auto-created |
| Service | `skill_tester`, `twin_user` | Internal service accounts |

---

## Key Files Reference

### `Enterprise_Context.md`

The master routing index. Contains:
- L1 process taxonomy (Finance & Accounting, IT Operations)
- L2 domain → context file mappings
- Routing keywords per domain
- Links to policy documents

Skills use this file via the `context_file` SKILL.md frontmatter field.

### `context_registry.json`

Structured metadata for all context items managed by the Context Manager:

```json
{
  "version": "1.0",
  "items": [
    {
      "id": "Enterprise_Context",
      "name": "Enterprise Context",
      "type": "root",
      "path": "/shared/Enterprise_Context.md",
      "status": "active",
      "created_at": "2026-03-31T15:13:45Z",
      "updated_at": "2026-04-05T17:30:12Z"
    }
  ]
}
```

### `entity_validation.yaml`

Controls which entity names can be auto-registered in the Entity Registry:

```yaml
entity_types: [vendor, customer]
allowlist: ["Acme Supplies", "Meridian Trust Bank", ...]
blocklist_extra: []
entity_memory:
  enabled: true
  storage_dir: "entities"
  id_patterns: ['^[A-Z]{2,6}-\w+']
```

### `admin_config.json`

Admin parameter overrides that take effect on startup:

```json
{
  "_updated_at": "2026-03-21T06:57:06Z",
  "QUEUE_BACKEND": "redis",
  "CONTEXT_LOADING_MODE": "file"
}
```

### `tenant_local_mount.json`

Optional external filesystem accessible to agents as `/local/`:

```json
{
  "path": "/Users/me/Documents/CompanyDocs",
  "enabled": true
}
```

---

## Data Volumes

Approximate sizes for a production deployment after 2 months of usage:

| Path | Approximate Size | Growth Rate |
|---|---|---|
| `shared/databases/traces.db` | 15 MB | ~200KB/day |
| `shared/databases/twin_telemetry.db` | 1.5 MB | ~20KB/day |
| `shared/databases/ap_regular.db` | 164 KB | Static (seeded) |
| `agents/enterprise_agent/memory/history/` | 2–5 MB | ~50KB/day |
| `agents/enterprise_agent/memory/context_graph/` | 100–500 KB | ~5KB/day |
| `.audit/` per agent | 100 KB/month | Auto-compressed |

---

## Recyclebin

Deleted agents are moved to `recyclebin/agents/{agent_id}/` rather than permanently deleted. The full directory structure is preserved. To restore, move the directory back to `tenants/company/agents/`.

The recyclebin is never purged automatically — manual cleanup is required.
