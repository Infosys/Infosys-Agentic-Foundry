import os
from dotenv import load_dotenv
from telemetry_wrapper import logger as log

# Load .env once (noop if already loaded elsewhere)
load_dotenv()

# Environment Configuration
# Controls application behavior for different deployment environments
# REQUIRED: Must be explicitly set in .env file - no defaults allowed for security
ENVIRONMENT_RAW: str = os.getenv("ENVIRONMENT")

# Force explicit environment configuration - prevent accidental defaults
if ENVIRONMENT_RAW is None or ENVIRONMENT_RAW.strip() == "":
    error_msg = (
        "CRITICAL CONFIGURATION ERROR: ENVIRONMENT variable is not set or is empty. "
        "You MUST explicitly set ENVIRONMENT in your .env file to either 'development' or 'production'. "
        "This is required for security reasons to prevent accidental deployment with wrong settings. "
        "Add 'ENVIRONMENT=development' or 'ENVIRONMENT=production' to your .env file."
    )
    log.error(error_msg)
    raise ValueError(error_msg)

ENVIRONMENT: str = ENVIRONMENT_RAW.lower().strip()

# Validate environment setting
if ENVIRONMENT not in ("development", "production"):
    error_msg = (
        f"INVALID ENVIRONMENT SETTING: '{ENVIRONMENT}' is not a valid environment. "
        "Valid values are 'development' or 'production'. "
        "Set ENVIRONMENT environment variable to 'development' or 'production' in your .env file."
    )
    log.error(error_msg)
    raise ValueError(error_msg)

# Environment-based feature flags
IS_DEVELOPMENT: bool = ENVIRONMENT == "development"
IS_PRODUCTION: bool = ENVIRONMENT == "production"

log.info(f"Application running in {ENVIRONMENT} environment")

# Authentication / JWT settings pulled from environment with safe defaults.
# IMPORTANT: Override JWT_SECRET in production via environment variable.
JWT_SECRET: str = os.getenv("AUTH_JWT_SECRET", os.getenv("JWT_SECRET", "CHANGE_ME_DEV_ONLY"))
JWT_ALGORITHM: str = os.getenv("AUTH_JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_SECONDS: int = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_SECONDS", str(15 * 60)))  # default 15 mins
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("AUTH_REFRESH_TOKEN_EXPIRE_DAYS", "14"))  # default 14 days

# Optional: allow disabling refresh tokens (set to false)
ENABLE_REFRESH_TOKENS: bool = os.getenv("AUTH_ENABLE_REFRESH_TOKENS", "false").lower() == "true"

# Critical security validation - prevent server startup with insecure JWT secrets
if JWT_SECRET in ("CHANGE_ME_DEV_ONLY", "your_jwt_secret"):
    error_msg = (
        "CRITICAL SECURITY ERROR: JWT_SECRET is using an insecure development default. "
        "This poses a severe security risk in production. "
        "Set AUTH_JWT_SECRET environment variable to a secure random string before starting the server. Refer Readme.md file for more details."
    )
    log.error(error_msg)
    raise ValueError(error_msg)

# Additional validation for short/weak secrets
if len(JWT_SECRET) < 32:
    error_msg = (
        "CRITICAL SECURITY ERROR: JWT_SECRET is too short (minimum 32 characters required). "
        "Use a cryptographically secure random string for AUTH_JWT_SECRET environment variable. Refer Readme.md file for more details."
    )
    log.error(error_msg)
    raise ValueError(error_msg)
