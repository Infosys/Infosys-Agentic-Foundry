# HashiCorp Vault — Adding a Secret and Using It in a Skill (UI-only)

> How to point a skill at a HashiCorp Vault secret using only the Studio UI —
> no `credentials.yaml` / `SKILL.md` file editing required.
>
> Code of record (if this doc and the code ever disagree, the code wins):
> - [IAF-Agent-Studio/routers/security.py](../IAF-Agent-Studio/routers/security.py) — `/api/credentials` (backs the Credentials page)
> - [IAF-Agent-Studio/static/skill-builder-v2.html](../IAF-Agent-Studio/static/skill-builder-v2.html) — Credentials page + Skill Builder Prompt tab
> - [agent_os/credential_store.py](../agent_os/credential_store.py) — `VaultBackend`, `CredentialStore.resolve_vault_secret`
> - [agent_os/kernel.py](../agent_os/kernel.py) — `_cmd_get_credential` (the `get_credential` shell command)
> - [agent_os/secret_refs.py](../agent_os/secret_refs.py) / [IAF-Agent-Skills/iaf_agent_skills/tool_factory.py](../IAF-Agent-Skills/iaf_agent_skills/tool_factory.py) — `${VAULT:...}` expansion

This covers **one** integration: a `type: vault` **connection** stored as a
credential, scoped to the skills allowed to use it. (There's also an
env-configured global Vault backend for the whole deployment — not covered
here; ask if you need that one.)

It's read-only and fails closed: any auth error, network failure, missing
key, or scope denial simply resolves to "not found" — it never raises, and
the raw secret is never logged or shown to the LLM.

---

## 1. Add the Vault connection — Credentials page

1. Open **Skill Builder v2** → `/skill-builder/v2` → left sidebar → **Credentials**.
   (Any signed-in user can view this page; creating/editing a credential
   requires the `skills.author` capability — same as authoring a skill.)
2. Click **Add Credential**.
3. Fill in:

   | Field | Value |
   |---|---|
   | **Name** | a name you'll reference from the skill, e.g. `dcm_vault` |
   | **Type** | `vault (HashiCorp)` |
   | **Vault Address** | `https://vault.corp.example` |
   | **Namespace** (optional) | e.g. `infosys/dcm` |
   | **KV Mount** | e.g. `dcm_staging` (default `secret`) |
   | **Role ID** / **Secret ID** | AppRole credentials — **or** |
   | **Static Token** | a Vault token instead of AppRole (token wins if both are set) |
   | **Scope** | comma-separated skill names allowed to use this connection, e.g. `dcm_network_skill` |

4. Click **Save**. The connection is written to the tenant's credential
   store, Secret ID / Token encrypted at rest. From then on:
   - The **YAML view** (toggle button) shows the connection with secrets
     masked — for reference/audit, not for editing.
   - Editing later: click **Edit** on the card — Secret ID / Token fields are
     write-only and shown blank; leave them blank to keep the current value,
     or type a new one to rotate it.
   - Only the connection's creator or an admin can edit/delete it afterward;
     any authenticated developer can create a new one.

> **Important — scope it.** Only skills listed in **Scope** can read through
> this connection. A skill not in the list gets a denial (audited), not the
> secret.

---

## 2. Use it in a skill — `get_credential` (verified, works end-to-end)

This is the mechanism to reach for when you need the Vault value inside a
skill's shell commands — e.g. to build an `Authorization` header, a DB
connection string, an env var for a bundled tool script, etc.

1. Open the skill in Skill Builder v2 → **Behavior** tab (the Prompt textbox
   — a plain text field, not a YAML file).
2. Add an instruction telling the agent to run `get_credential` with **three**
   arguments: `<connection name> <key> <vault path>`.

```markdown
When you need the F5 password:
1. Run: get_credential dcm_vault F5_Password network/prod
2. Use the returned variable in your next shell command, e.g.:
   curl -s -H "Authorization: Bearer $CRED_DCM_VAULT_F5_PASSWORD" https://f5.corp.example/mgmt/tm/ltm/virtual
```

3. Save the skill.

**What actually happens at runtime** (traced against the code, not assumed):

```
agent runs: get_credential dcm_vault F5_Password network/prod
  → kernel._cmd_get_credential(["dcm_vault", "F5_Password", "network/prod"])
      → kernel._credential_allowed("dcm_vault")                 # entitlement gate
      → provider.resolve_vault_secret("dcm_vault", "network/prod", "F5_Password",
                                       consumer=<current skill>)
          → scope check: <current skill> ∈ dcm_vault's Scope list  (else DENIED)
          → AppRole (or token) login → GET dcm_staging/data/network/prod
          → returns {"F5_Password": "<real secret>"}
      → session var CRED_DCM_VAULT_F5_PASSWORD = "<real secret>"   (masked)
  → returns to the agent: "✓ Credential loaded as $CRED_DCM_VAULT_F5_PASSWORD"
```

The LLM only ever sees the string `$CRED_DCM_VAULT_F5_PASSWORD` — the kernel
substitutes the real value into the shell command at execution time, never
into the LLM's context.

If the skill isn't in `dcm_vault`'s scope, or the path/key is wrong, you get
an explicit error back (e.g. `Vault secret 'F5_Password' at path
'network/prod' via connection 'dcm_vault' not found (missing / scope-denied /
read failed)`) — never a silent empty value.

---

## 3. `${VAULT:conn@path#key}` in a Connections-tab data connection — partial

The runtime also supports a placeholder syntax — `${VAULT:conn@path#key}` —
that gets expanded automatically wherever a skill's data-connection config is
read (e.g. right before `run_sql_query` connects). **Be precise about what
this currently gets you through the Connections-tab UI**, because it does
not cover every field:

- The Connections-tab **Database**/**API** forms have a plain-text
  **Username** / **Host** / **Base URL** field. Typing
  `${VAULT:dcm_vault@network/prod#F5_Username}` into one of those *does* work
  — those fields are expanded verbatim at query time.
- The **"Credential (password key)"** field in those same forms is **not** a
  free-text value slot — it's a *name* the runtime looks up in the plain
  credential store (`CredentialStore.get()`), and that lookup explicitly
  **refuses** `type: vault` connections (they're only readable through
  `resolve_vault_secret`, i.e. mechanism #2 above). So typing a
  `${VAULT:...}` ref into that field will **not** resolve to your Vault
  secret — don't use it there.
- There is currently no raw "password" text field exposed in the
  Connections-tab modal for non-SQLite engines, so a Vault-sourced DB/API
  **password** can't be wired in through that modal today.

**Practical takeaway:** for anything secret (passwords, tokens, keys), use
mechanism #2 (`get_credential ... <path>` in the skill's Prompt) — it's the
one verified to work fully through the UI. Reserve `${VAULT:...}` in
Connections-tab fields for non-secret values only (e.g. a Vault-managed
username or host), where it is genuinely expanded correctly.

---

## 4. Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Vault secret '...' at path '...' via connection '...' not found (missing / scope-denied / read failed)" | Wrong path/key, the skill isn't in the connection's **Scope**, or the AppRole/token can't read that path. |
| "Vault resolution is not available for this provider" | The secret provider active for this session has no `resolve_vault_secret` — unusual; check the provider setup. |
| Credentials page won't let you Save | You need the `skills.author` capability to create/edit credentials; viewing is open to any signed-in user. |
| Can't edit an existing Vault connection | Only its creator or an admin can edit/delete it. |
| Secret ID / Token appear blank when editing | Expected — they're write-only. Leave blank to keep the current value, or type a new one to rotate it. |
| `${VAULT:...}` in the "Credential (password key)" field does nothing | That field is a name lookup, not an expansion target — see §3. Use `get_credential` instead. |
