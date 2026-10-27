# Granting a Workstream Access to Run (Entitlements)

How to make a workstream **Run** succeed when `ENTITLEMENTS_ENABLED=true`.

## Symptom

Clicking **Run** on a workstream (or `POST /api/workstreams/{name}/run`) returns
`HTTP 200`, but the item ends `failed` with:

```
Access denied: skill '<worker_skill>' is not permitted for this user
```

…even though the same skill works fine when you invoke it from **chat**.

## Why this happens

The failure is an **entitlements** decision, not a bug in the skill, and it has
nothing to do with the agent's `context_loading_mode` (file / rlm / table).

1. `ENTITLEMENTS_ENABLED=true` in `agent_os/config.env` turns the policy gate on.
2. Chat runs as **you** — an interactive JWT. An `admin` role has
   `admin-full-access` (`actions: ['*']`, `resources: ['*']`), so every skill is
   allowed. That is why chat "just works."
3. The workstream **Run / mission engine** does **not** run as you. It executes
   each item under a **service principal**:
   - `IAF-Agent-Studio/routers/workstreams.py:1419` →
     `make_service_principal(tenant_id, "cron", user_id=owner)` → group
     `service:cron`.
   - Scheduled/queued/HITL-resumed runs use `service:queue` and
     `service:hitl_resume` the same way.
4. Each service group has an **explicit skill allowlist** in the tenant policy
   file. If the worker skill matches none of the allowed patterns, the check at
   `IAF-Agent-Skills/iaf_agent_skills/agent.py:1550` raises the `PermissionError`
   above and the item fails after its retry attempts.

So: **the human is allowed, but the service principal that actually drains the
queue is not.**

## The policy file

```
enterprise_root/tenants/{tenant_id}/security/policies.yaml
```

The three relevant policies are the service **skill-use** grants:

| Policy id | Group | Used by |
|---|---|---|
| `service-cron-skill-use` | `service:cron` | manual **Run** button + cron schedules |
| `service-queue-skill-use` | `service:queue` | Command Center queue drains |
| `service-hitl-resume-skill-use` | `service:hitl_resume` | resuming after a human approval |

Each lists the skill families the service principal may invoke, e.g.:

```yaml
  - id: service-cron-skill-use
    effect: allow
    groups:
      - service:cron
    actions:
      - use
      - call
    resources:
      - skill:mission_mode
      - skill:general
      - skill:fa_ap
      - skill:ntt_*
      - skill:fin_*
      # ...
    reason: Cron may invoke only reconciled platform jobs and tenant workstream skill families.
```

> **Why all three?** A workstream that pauses for approval is drained by
> `service:cron` on the first Run, then continued by `service:hitl_resume` after
> the human decides, and by `service:queue` if it was queued. Grant the worker
> skill to **all three** or the run will stall at whichever stage lacks it.

## Grant the access

Pick the smallest pattern that covers your workstream's worker skill **and** every
leaf skill it chains. A `workflow`-mode orchestrator invokes its leaf skills, so
those must be entitled too — a glob is usually cleanest.

1. **Back up the file** (never edit a security file in place without a copy):

   ```bash
   cd enterprise_root/tenants/<tenant_id>/security
   cp policies.yaml policies.yaml.bak_$(date +%Y%m%d_%H%M%S)
   ```

2. **Add one resource line** to each of the three `service-*-skill-use` policies.
   For a family of skills named `ntt_*`:

   ```yaml
       resources:
         - skill:fin_*
         - skill:o2c_*
         - skill:ntt_*          # <-- add this line to each of the 3 service policies
   ```

   Use a specific name (`- skill:ntt_quote_workstream`) if you want to grant a
   single skill instead of a family.

3. **No restart needed.** The entitlement provider re-reads the policy file on
   **every** check — `IAF-Agent-Studio/security/yaml_provider.py:_load_policy`
   does `yaml.safe_load(policy_file.read_text(...))` per call, with no cache. The
   grant is live on the next Run.

## Verify

```bash
# 1. log in (admin)
TOKEN=$(curl -s -X POST http://localhost:8082/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@iaf.local","password":"<IAF_ADMIN_PASSWORD>"}' \
  | sed -E 's/.*"access_token":"([^"]+)".*/\1/')

# 2. drain one pending item through the real Run path
curl -s -X POST http://localhost:8082/api/workstreams/<name>/run \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"count":1,"parallel":1}'
```

A successful grant returns a result whose `reason` is **not** an
`Access denied … not permitted` string — the item advances (e.g. to
`item_paused` awaiting approval, or `item_completed`) instead of `item_failed`.

If an earlier attempt already marked items `failed`, reset them to `pending`
before re-running (a `failed` item is not re-drained). Use the tenant's demo
reset script, or set the item `status: pending` in
`enterprise_root/tenants/{tenant_id}/workstreams/{name}.yaml`.

## What NOT to do

- **Do not set `ENTITLEMENTS_ENABLED=false`** just to make one workstream run —
  that turns off the whole governance layer (skill filtering, tool/credential/
  context gating) the platform is meant to demonstrate. Grant the specific skill
  instead.
- **Do not grant `skill:*` to the service groups.** That gives the queue/cron
  principals every installed skill and defeats the point of the allowlist. Grant
  the narrowest pattern that covers your workstream.
- **Do not rely on the human's role.** The Run principal is always a
  `service:*` account, regardless of who clicked Run.

## Related

- `docs/SECURITY_DEVELOPER_GUIDE.md` — full entitlement model, `policies.yaml` schema.
- `docs/WORKSTREAMS_AS_RECURRING_OPERATIONS.md` — how workstreams drain items.
- `docs/WORKSTREAM_SKILL_CONTRACT_GUIDE.md` — worker-skill / leaf-skill contract.
