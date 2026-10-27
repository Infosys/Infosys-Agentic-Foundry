# 07 · Authentication, Users & RBAC

Authoritative reference for how AgentOS authenticates users, stores identities,
and projects roles into permissions. Code is the source of truth — see the
modules linked from `docs/CODE_DOC_MAP.yaml`.

## Authentication flow

- `AUTH_PROVIDER=local` (Phase 1) issues Studio JWTs via
  [`auth/local.py`](../IAF-Agent-Studio/auth/local.py) and
  [`auth/tokens.py`](../IAF-Agent-Studio/auth/tokens.py).
- Login / registration / lockout endpoints live in
  [`routers/auth.py`](../IAF-Agent-Studio/routers/auth.py). `/auth/me` and login
  responses include the caller's projected `permissions` array.
- When `AUTH_ENABLED=false`, REST and WebSocket paths run with a dev identity
  (full privileges) for local development.

## User store backends (`AUTH_BACKEND`)

The active store is built once at startup by
[`auth/factory.py`](../IAF-Agent-Studio/auth/factory.py):

| Backend    | Persistence                                   | Use case                    |
|------------|-----------------------------------------------|-----------------------------|
| `sqlite`   | `tenants/<tenant>/config/auth_users.db` (WAL) | Default, single node, dev   |
| `postgres` | `DATABASE_URL` (`auth_users`/`auth_passwords`)| Shared DB across replicas   |
| `redis`    | Configured `REDIS_URL`                        | HA multi-node deployments   |

Switching backends does **not** migrate accounts — pick one and keep it.

### `AUTH_STORE_STRICT` (fail-closed)

If a shared store (`postgres`/`redis`) is unreachable at startup, AgentOS can
either fall back to per-instance SQLite (convenient for local dev) or fail
closed (correct for HA, so an outage never partitions identity across replicas).

- Default: strict whenever a shared backend (`AUTH_BACKEND=postgres`/`redis`) is
  selected, or when TLS is in play (`SSL_CERTFILE` set or `BEHIND_PROXY=true`).
- Local SQLite/HTTP dev keeps the SQLite fallback.
- Override explicitly with `AUTH_STORE_STRICT=true|false`.

Both [`auth/factory.py`](../IAF-Agent-Studio/auth/factory.py) and the admin
bootstrap [`auth/seed_admin.py`](../IAF-Agent-Studio/auth/seed_admin.py) honor
this flag so the admin is never seeded into a different backend than the one
serving requests.

## Roles → permissions (RBAC)

[`security/roles.py`](../IAF-Agent-Studio/security/roles.py) is the
role→permission source of truth used for UI gating, role validation, and
dynamic (runtime-authored) roles. Roles are stored per tenant in
`tenants/<tenant>/security/roles.yaml`; built-in defaults apply when absent.

Built-in roles:

| Role        | Permissions                                                                 |
|-------------|-----------------------------------------------------------------------------|
| `user`      | `agents.use`, `skills.use`                                                   |
| `developer` | `user` + `skills.author`, `agents.author`, `tools.dev`, `knowledge.write`, `evals.run` |
| `admin`     | `*` (wildcard — passes every check)                                          |

`effective_permissions(role, groups, tenant)` returns the permission set for a
role. Callers holding multiple roles receive the **union** across all roles.

`skills.use` grants not just skill access but the **runtime toolset** the ReAct
loop wires by default (`shell`, `write_file`, `run_sql_query`, `query_memory`,
`invoke_skill`, `invoke_plan`, `create_plan`, `request_human_approval`) — so an
invoked skill actually functions for any skill-user rather than silently losing
tools (`SkillAgent._get_allowed_tools` drops any tool the caller isn't entitled
to). This is a baseline **allow**; a tenant locks any tool down with an explicit
`deny` in `policies.yaml` (deny wins). `tools.dev` layers the developer-tier
integrations on top (`mcp:*`, `external:*`). Each tool is still second-gated at
runtime (shell is SafeKernel-sandboxed, `run_sql_query` is read-only unless the
skill opts into `sql_mode: read_write`, writes/invocations respect the HITL gate).

`skills.use` also grants **read** on `context:*`. File-mode agents read the master
`Enterprise_Context.md` (and taxonomy reference files) at routing time, and that
read is entitlement-gated with a *hard* `PermissionError` on denial — so without
this grant a non-developer could not run any query on a file-mode agent. Editing
knowledge/memory/context stays write-gated under `knowledge.write`.

### Route enforcement

- UI projection: the `permissions` array on `/auth/me`.
- Runtime access enforcement stays in the entitlement engine
  ([`security/yaml_provider.py`](../IAF-Agent-Studio/security/yaml_provider.py)),
  which merges curated `policies.yaml` with allow-rules compiled from
  `roles.yaml` (deny-wins preserved).
- **Curated rules take precedence over auto-compiled defaults.** When an admin
  hand-authors an `allow` rule in `policies.yaml` that scopes a *curated access
  class* (`skill`/`agent`) for a role or group — e.g. narrowing `user` to
  `skill:general` — the engine drops that selector's broad auto-compiled
  `<class>:*` grant (`_suppress_curated_access`), so the hand-written scope wins
  instead of being re-granted by the role-derived wildcard (any-allow-wins).
  Only *pure* broad grants are dropped: runtime plumbing (`tool:*`, `context:*`)
  is always kept so permitted skills still run, the built-in admin wildcard
  baseline is never touched, and a curated rule only "owns" a selector when it
  scopes that one dimension alone (a `roles:`+`groups:` or `users:`-scoped rule
  matches a strict subset and so adds access rather than suppressing). Roles with
  no curated rule, and an empty/missing `policies.yaml`, keep their full
  compiled defaults — so new UI roles never lock out.
- `require_permission(<perm>)` in
  [`auth/middleware.py`](../IAF-Agent-Studio/auth/middleware.py) gates mutating
  routes (e.g. `agents.author`). It unions permissions across every assigned
  role before checking.

### Tenant binding

Mutating routes that accept a `tenant_id` bind the requested tenant against the
caller's `allowed_tenants` via `bind_request_identity`
([`security/dependencies.py`](../IAF-Agent-Studio/security/dependencies.py))
before touching tenant-scoped storage, so a principal authorized in one tenant
cannot target another via a query parameter.

## Cookie security

`AUTH_COOKIE_SECURE` controls the `Secure` flag on auth cookies. Browsers drop
`Secure` cookies over plain HTTP on LAN/IP origins (silent 401s), so it
auto-enables only when TLS is in play (`SSL_CERTFILE` set or `BEHIND_PROXY=true`)
and can be forced with `AUTH_COOKIE_SECURE=true|false`.

## Ownership & display names

- `created_by` stores the **stable identity** (email or user_id) and is used for
  owner-or-admin edit/delete gating.
- Skill ownership is an immutable manifest-level `created_by`
  ([`shared/skill_versions.py`](../IAF-Agent-Studio/shared/skill_versions.py)),
  so editing a version's author never transfers ownership. When an admin approves a
  personal-skill submission, `record_promotion()` stamps the submitter's email as
  `created_by`; pre-versioning skills with no manifest still default to `admin@iaf.local`.
- For display, [`shared/user_display.py`](../IAF-Agent-Studio/shared/user_display.py)
  adds a separate `<key>_display` field (e.g. `created_by_display`) and leaves
  the raw identity intact.

## Related configuration

See [`docs/CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md) and
[`IAF-Agent-Studio/config.env.example`](../IAF-Agent-Studio/config.env.example)
for the full list of `AUTH_*` variables.
