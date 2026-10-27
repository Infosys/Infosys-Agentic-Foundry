---
name: vault_probe
version: "0.1.0"
description: "Diagnostic skill that reads a secret from a scoped HashiCorp Vault connection to verify the ${VAULT:...} / get_credential vault integration."
execution_mode: react
tools:
  - shell
business_context:
  domain: "Platform"
  tower: "Security"
  process: "Secrets Management"
  subprocess: "Vault connectivity check"
keywords:
  - vault probe
  - vault test
  - read vault secret
  - hashicorp vault
credentials:
  - dcm_vault
---

# Vault Probe (diagnostic)

This skill verifies that a **scoped HashiCorp Vault connection** resolves correctly.

The Vault connection `dcm_vault` is defined in the tenant credential store
(`credentials.yaml`, `type: vault`) and is **scoped to this skill only**.
Connection details (address, namespace, KV mount, AppRole auth) live there —
never in this skill file or the model context.

## How to read a secret

Use the kernel credential tool in a shell step. The **3-argument** form resolves
a key live from Vault via the scoped connection:

```
get_credential dcm_vault <KEY> <KV_PATH>
```

Example — load the F5 username stored at KV path `dcm_staging/network`
(keys are exactly `F5_Username` / `F5_Password`):

```
get_credential dcm_vault F5_Username dcm_staging/network
```

The value is loaded into `$CRED_DCM_VAULT_F5_USERNAME` and substituted into the
next shell command at execution time — it is never shown to the model.

Alternatively, a connection URL/header can embed a placeholder that the platform
expands the same way:

```
${VAULT:dcm_vault@dcm_staging/network#F5_Username}
```

## Guardrails
- Only this skill is in `dcm_vault`'s `scope`; other skills/consumers are denied.
- The secret is fetched **below the agent** and never logged or returned in chat.
- Unresolved refs are left intact so a misconfiguration surfaces as a clear
  connect error rather than a silent empty value.
