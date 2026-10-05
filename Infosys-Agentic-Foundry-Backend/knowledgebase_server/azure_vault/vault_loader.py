import os


def _build_secret_client(vault_url: str):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    client_id = os.getenv("CLIENT_ID", "").strip()
    if client_id:
        credential = DefaultAzureCredential(
            managed_identity_client_id=client_id,
            exclude_environment_credential=True,
        )
    else:
        credential = DefaultAzureCredential()
    return SecretClient(vault_url=vault_url, credential=credential)


def get_secret_value(secret_name: str, vault_url: str | None = None) -> str:
    """Fetch a single secret_value from Azure Key Vault."""
    resolved_vault_url = (vault_url or os.getenv("VAULT_URL", "")).strip()
    if not resolved_vault_url:
        raise ValueError("VAULT_URL is required")
    secret_client = _build_secret_client(resolved_vault_url)
    return secret_client.get_secret(secret_name).value
