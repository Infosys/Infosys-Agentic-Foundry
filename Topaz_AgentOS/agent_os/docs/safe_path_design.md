# AgentOS — Safe Path Design

## Overview

`SafePath` is the path sandboxing layer in AgentOS. Every path reference in a command — whether typed by an LLM or constructed programmatically — is resolved through `SafePath.resolve()` before any file I/O occurs. This ensures that agents can never read or write outside their authorised filesystem boundary, regardless of what paths the LLM generates.

---

## Design Principles

1. **LLM-friendly virtual paths** — The LLM writes natural, human-readable paths like `/me/notes.md` or `/shared/policies/sox.md`. The kernel translates these to real filesystem paths transparently.
2. **Strict sandboxing** — Resolved paths must stay within authorised roots. The `..` component is rejected before I/O. Full post-resolution containment (including symlink following) is implemented in `SafePath.resolve()`; the kernel's primary virtual-path mapper (`SafeKernel._resolve_path()`) is a separate code path — verify both in code before assuming identical guarantees.
3. **Read-only zones** — Shared and global paths are always read-only, even if the LLM attempts a write.
4. **RBAC layered on top** — After path resolution, user role checks add a second permission layer for multi-user paths.

---

## Virtual Namespace

The virtual namespace is the path vocabulary the LLM uses. It maps to real filesystem paths on resolution:

```
Virtual Path                   → Real Filesystem Path
─────────────────────────────────────────────────────────────────
/workspace/                    → {agent_root}/workspace/
/memory/                       → {agent_root}/memory/
/users/{user_id}/              → {agent_root}/users/{user_id}/
/me/                           → {agent_root}/users/{current_user_id}/
/me/global.md                  → {tenant_user_root}/{user_id}/profile.md
/team/                         → {agent_root}/teams/{current_team_id}/
/teams/{team_id}/              → {agent_root}/teams/{team_id}/
/shared/                       → {tenant_root}/shared/
/global/                       → {data_root}/global_shared/
/local/                        → {local_mount_path}/  (if configured)
```

### Sandbox Root Hierarchy

```
{data_root}/                              Enterprise root
  global_shared/                          /global/ → read-only
  tenants/
    {tenant_id}/
      shared/                             /shared/ → read-only
      users/
        {user_id}/
          profile.md                      /me/global.md
      agents/
        {agent_id}/                       ← agent_root (sandbox boundary)
          workspace/                      /workspace/
          memory/                         /memory/
          users/
            {user_id}/                    /me/ and /users/{id}/
          teams/
            {team_id}/                    /team/ and /teams/{id}/
          .audit/                         (not accessible via virtual paths)
          .index/                         (not accessible via virtual paths)
```

---

## `SafePath.resolve()` Algorithm

```python
def resolve(path: str, cwd: Path) → Path:
```

**Step 1 — Special-case shortcuts:**
- `/me/global.md` → directly maps to tenant-level user profile
- `/me/` prefix → rewritten to `/users/{current_user_id}/`
- `/team/` prefix → rewritten to `/teams/{current_team_id}/`

**Step 2 — `..` blocking:**
If `..` appears anywhere in the path, raises `SecurityError("path traversal not allowed")` immediately, before any filesystem access.

**Step 3 — Absolute path rewriting:**
Paths starting with `/` are treated as sandbox-relative (not filesystem-root-relative). The leading `/` is stripped and the path is joined to the sandbox root.

**Step 4 — Relative path resolution:**
Relative paths are resolved against `cwd` (the current working directory within the virtual namespace, defaulting to `/workspace/`).

**Step 5 — Sandbox escape check (SafePath.resolve() only):**
The resolved real path is checked via `resolved_path.relative_to(sandbox_root)`. If this raises `ValueError` (path is outside the sandbox root), `SecurityError` is raised.

> **Implementation note:** `SafeKernel._resolve_path()` in `kernel.py` performs virtual-prefix routing and blocks `..`, but most tool I/O uses that mapper rather than calling `SafePath.resolve()` directly. Treat this step as guaranteed for `SafePath.resolve()` callers; for kernel virtual paths, confirm behaviour in `kernel.py` and tests.

**Step 6 — Return:**
The real, validated `Path` object is returned for I/O operations.

---

## Permission Zones

### Read-Only Paths

The following virtual paths are always read-only regardless of role:

| Virtual Path | Reason |
|---|---|
| `/shared/` | Tenant-wide shared resources — curated by admins |
| `/global/` | Enterprise-wide resources — system-level |

Any write attempt to these paths returns:
```
Permission denied: /shared/ is read-only
```

### Read-Write Paths

| Virtual Path | Who can write |
|---|---|
| `/workspace/` | All users in this agent |
| `/memory/` | All users in this agent |
| `/me/` | Current user only |
| `/me/global.md` | Current user only |
| `/users/{id}/` | RBAC: same user, or MANAGER/ADMIN for subordinates |
| `/team/` | RBAC: team members and MANAGER/ADMIN |
| `/local/` | All users if `local_mount` configured and enabled |

### `_is_writable(virtual_path) → bool`

Internal check that runs after `SafePath.resolve()`. Returns `False` for:
- Any path resolving under `/shared/` real path
- Any path resolving under `/global/` real path
- Configured `readonly_paths` set

---

## RBAC Path Checks

After `SafePath.resolve()`, `_check_user_access(virtual_path)` runs for multi-user paths:

```
/users/alice/notes.md  accessed by user bob (role=USER)
    → AccessDeniedError: user bob cannot access /users/alice/

/users/alice/notes.md  accessed by manager carol (role=MANAGER, manages=[alice, dave])
    → alice is in managed_users → ACCESS GRANTED

/users/alice/notes.md  accessed by auditor eve (role=AUDITOR)
    → read → ACCESS GRANTED
    → write → AccessDeniedError: AUDITOR role is read-only
```

---

## Local Mount

An optional external filesystem can be mounted at `/local/`:

**Configuration:** `enterprise_root/tenants/company/config/tenant_local_mount.json`
```json
{
  "path": "/Users/madhan/Documents/Company_Docs",
  "enabled": true
}
```

**Behaviour:**
- When enabled, `/local/` → the configured real path
- No `relative_to()` sandbox check applies — path is outside the normal tree
- Read-Write when `enabled: true`
- Useful for accessing local databases, exported files, or mounted NFS shares

**Security note:** The local mount bypasses the normal sandbox boundary. Keep `enabled: false` in production unless the mount path is itself restricted.

---

## Path Traversal Prevention

### What's blocked

```
# All of these raise SecurityError:
cat ../../etc/passwd
cat /workspace/../../tenant2/shared/secrets.md
cat /me/../users/admin/passwords.txt
find /shared/../../../ -name "*.md"
```

### How it works

The `..` check is a string-level pre-validation — it fires **before** any filesystem access.

`SafePath.resolve()` adds a second layer: after `pathlib.Path.resolve()` (which follows symlinks), it checks `relative_to(sandbox_root)`.

**Current kernel caveat:** `SafeKernel._resolve_path()` blocks `..` and maps virtual prefixes, but does **not** call `SafePath.resolve()` or perform the same post-resolution `relative_to()` check on every returned path. A symlink inside an allowed directory could therefore be followed by the OS when a tool opens the resolved path. Do not document or assume full symlink containment for all kernel operations until that path is unified or covered by tests.

### What's allowed

```
# Absolute virtual paths (treated as sandbox-relative):
cat /shared/Enterprise_Context.md    → OK
cat /me/profile.md                   → OK

# Relative paths from workspace:
cat report.md          → resolves to /workspace/report.md
cat notes/today.md     → resolves to /workspace/notes/today.md
```

---

## Security Error Hierarchy

| Error | Trigger |
|---|---|
| `SecurityError` | Path traversal (`..`), dangerous operator in command, blocked command |
| `AccessDeniedError` | RBAC check failed for multi-user path |
| `PermissionError` | Write to read-only zone (`/shared/`, `/global/`) |

All three are caught by the kernel and returned as error strings to the LLM — the agent loop continues.

---

## Design Rationale

**Why virtual paths instead of real paths?**

Real paths are environment-specific and leak internal deployment details. Virtual paths (`/me/`, `/shared/`) are stable across deployments, meaningful to LLMs, and encode the permission model directly in the path name. `/shared/` *sounds* shared — the LLM correctly infers it should not write there.

**Why block `..` as a string, not only via `relative_to()`?**

Blocking `..` early produces clear, actionable errors before any I/O. In `SafePath.resolve()`, `pathlib.Path.resolve()` follows symlinks and the subsequent `relative_to()` check is the containment backstop. The kernel's `_resolve_path()` currently relies primarily on the string-level `..` block plus prefix routing — keep docs and security reviews aligned with that split until the resolver paths are unified.

**Why read-only for `/shared/`?**

Shared context documents (Enterprise_Context.md, policy files, process context files) are curated assets that affect all agents and users in the tenant. If any agent could overwrite them, a single compromised or misconfigured skill could corrupt tenant-wide behaviour. Admin writes to `/shared/` go through the Studio UI or direct filesystem access, not the agent kernel.

**How does Python isolation relate to SafePath?**

Virtual-path rewriting remains the logical tenant boundary. In strict
enterprise mode, Python execution adds an OS boundary by requiring a restricted
`AGENT_PYTHON3_SANDBOX_USER`, isolated interpreter mode, a minimal environment,
and resource limits. Filesystem ACLs for that account must mirror the SafePath
zones; the OS account is defense in depth, not a replacement for path checks.
