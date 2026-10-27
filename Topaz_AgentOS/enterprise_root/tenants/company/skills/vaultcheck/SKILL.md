---
name: vaultcheck
version: "1.0"
description: "Verifies that secrets stored in the Infosys HashiCorp Vault are reachable from AgentOS. Loads the F5 network credential from Vault and confirms it resolved — without ever printing the secret."
execution_mode: react
keywords:
  - "vault"
  - "hashicorp"
  - "vault check"
  - "test vault"
  - "f5 credential"
  - "f5 network"
  - "vault secret"
tools:
  - shell
---

# Vault Connectivity Check

You confirm that secrets in the Infosys HashiCorp Vault are reachable from AgentOS.

The F5 network login is stored in Vault at `dcm_staging/network` (KV v2, namespace
`CCD-AI-AgentSecrets`). That secret has two keys — `F5_Username` and `F5_Password` —
so use those **exact** field names (not the generic `username`/`password`).

## When asked to check the Vault credential

1. Load both fields from Vault:
   ```
   get_credential dcm_staging/network F5_Username
   get_credential dcm_staging/network F5_Password
   ```
   Each returns a masked `$CRED_*` placeholder — the real value never enters this
   conversation.

2. Confirm they resolved **without printing the secret**. Verify only the length,
   e.g.:
   ```
   shell(command="printf '%s' \"$CRED_DCM_STAGING/NETWORK_F5_USERNAME\" | wc -c")
   shell(command="printf '%s' \"$CRED_DCM_STAGING/NETWORK_F5_PASSWORD\" | wc -c")
   ```
   The kernel substitutes the real secret at run time; you see only the character
   count.

3. Report: whether each field loaded, its length, and that the value came from
   Vault. **Never echo, print, or repeat the actual username or password.**

## Rules — NON-NEGOTIABLE

- **NEVER print, echo, or paste a secret value.** Only report masked confirmation
  (loaded / not loaded, length).
- If `get_credential` returns `Field '<x>' not found`, the key name is wrong — the
  Vault keys are exactly `F5_Username` and `F5_Password`.
- If it returns `not found` or `secret provider unavailable`, Vault is not configured
  on this server — tell the user to set `VAULT_ENABLED=true` and the `VAULT_*` values
  in `config.env`, then restart.
