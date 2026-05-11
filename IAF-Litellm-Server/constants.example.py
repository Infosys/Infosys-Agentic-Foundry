"""
Database Configuration Constants for LiteLLM Backend

This module contains all database connection constants and configuration
parameters for PostgreSQL connectivity.

INSTRUCTIONS:
1. Copy this file to 'constants.py'
2. Replace all placeholder values with your actual database credentials
3. Never commit constants.py to git (it's in .gitignore)
"""

# PostgreSQL Connection Parameters
DATABASE_URL = ""
POSTGRESQL_HOST = "YOUR_HOST"
POSTGRESQL_PORT = 5432
POSTGRESQL_USER = "YOUR_USERNAME"
POSTGRESQL_PASSWORD = "YOUR_PASSWORD"
DATABASE = "YOUR_DATABASE"
CONNECTION_POOL_SIZE = "high"
POSTGRESQL_DB_URL_PREFIX = ""
POSTGRESQL_DATABASE_URL = ""
LITELLM_LOGGING = False

# Disable Prisma database for LiteLLM proxy
# This allows running without Prisma dependencies
DISABLE_SPEND_LOGS = True
STORE_MODEL_IN_DB = False

# Connection Pool Settings
# Connection pool size configurations based on CONNECTION_POOL_SIZE setting
CONNECTION_POOL_CONFIGS = {
    "low": {
        "min_size": 2,
        "max_size": 5,
        "max_queries": 50000,
        "max_inactive_connection_lifetime": 300.0
    },
    "medium": {
        "min_size": 5,
        "max_size": 10,
        "max_queries": 50000,
        "max_inactive_connection_lifetime": 300.0
    },
    "high": {
        "min_size": 10,
        "max_size": 20,
        "max_queries": 50000,
        "max_inactive_connection_lifetime": 300.0
    }
}

# Get current pool configuration
CURRENT_POOL_CONFIG = CONNECTION_POOL_CONFIGS.get(CONNECTION_POOL_SIZE.lower(), CONNECTION_POOL_CONFIGS["medium"])

# Database connection timeout (seconds)
DB_CONNECTION_TIMEOUT = 30

# Query timeout (seconds)
DB_QUERY_TIMEOUT = 60
