import logging
import os

logger = logging.getLogger(__name__)


def load_db_password_from_vault() -> None:
    """When READ_DB_VAULT=true, resolve POSTGRESQL_PASSWORD from Azure Key Vault."""
    if os.getenv("READ_DB_VAULT", "").lower() != "true":
        return

    secret_name = os.getenv("POSTGRESQL_PASSWORD", "").strip()
    vault_url = os.getenv("VAULT_URL", "").strip()
    if not secret_name:
        raise ValueError(
            "READ_DB_VAULT=true requires POSTGRESQL_PASSWORD to be set as the Key Vault secret name"
        )
    if not vault_url:
        raise ValueError("READ_DB_VAULT=true requires VAULT_URL")

    from azure_vault.vault_loader import get_secret_value

    logger.info("READ_DB_VAULT=true: loading POSTGRESQL_PASSWORD from Azure Key Vault")
    os.environ["POSTGRESQL_PASSWORD"] = get_secret_value(secret_name, vault_url)
