# src/config/vault_loader.py
import os
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from telemetry_wrapper import logger as log

def load_vault_secrets_into_env():
    """Call this ONCE at app startup before anything else reads env vars."""
    vault_keys = [
        k.strip()
        for k in os.getenv("VAULT_ENABLE_KEYS_LIST", "").split(",")
        if k.strip()
    ]
    client_id = os.getenv("CLIENT_ID")
    if not vault_keys:
        return

    if client_id:
        # Use ManagedIdentityCredential directly to avoid DefaultAzureCredential
        # picking up AZURE_CLIENT_SECRET/AZURE_TENANT_ID from the environment
        # and attempting ClientSecretCredential with the MSI client ID.
        credential = ManagedIdentityCredential(client_id=client_id)
    else:
        credential = ManagedIdentityCredential()
    secret_client = SecretClient(
        vault_url=os.getenv("VAULT_URL"),
        credential=credential
    )

    _vault_debug = os.getenv("ENABLE_VAULT_DEBUG_LOGS", "false").lower() == "true"

    for key in vault_keys:
        vault_name = os.getenv(key)
        if vault_name:
            secret_value = secret_client.get_secret(vault_name).value
            os.environ[key] = secret_value  # overwrite in-process env
            log.info(f"[VAULT] Successfully fetched secret for key='{key}'.")
            if _vault_debug:
                log.info(f"[VAULT DEBUG] Loaded secret for key='{key}', vault_name='{vault_name}', value='{secret_value}'")

    if _vault_debug:
        log.info(f"[VAULT DEBUG] os.environ snapshot after vault load: { {k: v for k, v in os.environ.items()} }")
            
