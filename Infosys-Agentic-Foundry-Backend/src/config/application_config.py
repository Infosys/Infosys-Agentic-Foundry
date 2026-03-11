import os
from typing import Optional, List
from urllib.parse import quote_plus
from dataclasses import dataclass, field
from src.config.constants import PoolSizeConfig, ConnectionPoolSize, DatabaseName
from dotenv import load_dotenv

load_dotenv()


# ============================================================================
# Database Configuration
# ============================================================================

@dataclass
class PostgresDatabaseConfig:
    """
    Centralized PostgreSQL database configuration.
    
    Handles:
    - Connection credentials from environment variables
    - URL-safe encoding of credentials
    - Connection string generation for any database
    - Connection pool size configuration
    - Required database names
    """
    host: str = field(default_factory=lambda: os.getenv("POSTGRESQL_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("POSTGRESQL_PORT", "5432")))
    user: str = field(default_factory=lambda: os.getenv("POSTGRESQL_USER", "postgres"))
    password: str = field(default_factory=lambda: os.getenv("POSTGRESQL_PASSWORD", ""))
    pool_size: ConnectionPoolSize = field(default_factory=ConnectionPoolSize.from_env)
    disable_ssl_for_chat_connections: bool = field(default_factory=lambda: os.getenv("DISABLE_SSL_FOR_CHAT_CONNECTIONS", "true").lower() == "true")

    # Default admin database for initial connections
    admin_database_name: str = "postgres"

    @property
    def _encoded_user(self) -> str:
        """URL-encoded username"""
        return quote_plus(self.user)

    @property
    def _encoded_password(self) -> str:
        """URL-encoded PWD"""
        return quote_plus(self.password)

    @property
    def url_prefix(self) -> str:
        """
        Generate the PostgreSQL URL prefix (without database name).
        This can be used to append any database name.
        
        Returns:
            str: URL prefix like "postgresql://user:pass@host:port/"
        """
        return f"postgresql://{self._encoded_user}:{self._encoded_password}@{self.host}:{self.port}/"

    @property
    def async_url_prefix(self) -> str:
        """
        Generate the async PostgreSQL URL prefix (without database name).
        
        Returns:
            str: URL prefix like "postgresql+asyncpg://user:pass@host:port/"
        """
        return f"postgresql+asyncpg://{self._encoded_user}:{self._encoded_password}@{self.host}:{self.port}/"
    
    def connection_string(self, database: Optional[DatabaseName] = None, db_name: Optional[str] = None, disable_ssl: bool = False, async_str: bool = False) -> str:
        """
        Generate PostgreSQL connection string for a specific database.

        Args:
            database: DatabaseName enum member (preferred)
            db_name: Direct database name string (fallback)
            disable_ssl: If True, appends '?sslmode=disable' to the connection string
            async_str: If True, generates async connection string format

        Returns:
            str: Full connection string

        Examples:
            config.connection_string(DatabaseName.MAIN)
            config.connection_string(db_name="custom_db")
        """
        if database is not None:
            actual_db_name = database.db_name
        elif db_name is not None:
            actual_db_name = db_name
        else:
            actual_db_name = self.admin_database_name

        sslmode_part = f"?sslmode=disable" if disable_ssl else ""

        if async_str:
            return f"{self.async_url_prefix}{actual_db_name}{sslmode_part}"
        return f"{self.url_prefix}{actual_db_name}{sslmode_part}"
    
    @property
    def pool_config(self) -> PoolSizeConfig:
        """Get the current pool size configuration"""
        return self.pool_size.config

    @property
    def required_databases(self) -> List[str]:
        """Get all required database names"""
        return DatabaseName.all_db_names()
    
    @property
    def primary_databases(self) -> List[str]:
        """Get primary databases (used in app_container initialization)"""
        return DatabaseName.primary_databases()


# ============================================================================
# Application Configuration (Main Config Class)
# ============================================================================

@dataclass
class ApplicationConfig:
    """Main application configuration - single source of truth"""
    
    # Sub-configurations
    postgres_db: PostgresDatabaseConfig = field(default_factory=PostgresDatabaseConfig)
    
    # Application settings
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development").lower())

    # Model Server URL for Embeddings and Encoders using remote model server
    model_server_url: str = field(default_factory=lambda: os.getenv("MODEL_SERVER_URL", "").strip())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        return self.environment == "development"


# Global config instance - import this wherever needed
app_config = ApplicationConfig()

