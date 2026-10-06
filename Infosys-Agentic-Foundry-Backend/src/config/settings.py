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

# Keycloak Configuration
KEYCLOAK_SERVER_URL: str = os.getenv("KEYCLOAK_SERVER_URL", "")
KEYCLOAK_REALM: str = os.getenv("KEYCLOAK_REALM", "")
KEYCLOAK_CLIENT_ID: str = os.getenv("KEYCLOAK_CLIENT_ID", "")
KEYCLOAK_CLIENT_SECRET: str = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_ADMIN_USERNAME: str = os.getenv("KEYCLOAK_ADMIN_USERNAME", "")
KEYCLOAK_ADMIN_PASSWORD: str = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")

# Enable Keycloak authentication (set to true to use Keycloak instead of local auth)
KEYCLOAK_ENABLED: bool = os.getenv("KEYCLOAK_ENABLED", "false").lower() == "true"

# OAuth Authorization Code Flow Settings (Required for MFA/OTP support)
# Redirect URI where Keycloak will send the authorization code after login
KEYCLOAK_REDIRECT_URI: str = os.getenv("KEYCLOAK_REDIRECT_URI", "http://localhost:8000/auth/callback")
# Post-logout redirect URI - where to redirect after Keycloak logout
KEYCLOAK_POST_LOGOUT_REDIRECT_URI: str = os.getenv("KEYCLOAK_POST_LOGOUT_REDIRECT_URI", "http://localhost:8000")
# Frontend redirect URI - where to redirect the browser after successful OAuth callback
FRONTEND_REDIRECT_URI: str = os.getenv("FRONTEND_REDIRECT_URI", "http://localhost:3000")
# Comma-separated list of allowed frontend origins for OAuth redirect (multi-UI support).
# Example: ALLOWED_FRONTEND_URLS=http://localhost:3000,http://localhost:4000,https://ui1.example.com,https://ui2.example.com
# Defaults to FRONTEND_REDIRECT_URI when not set (single-UI backwards-compatible).
ALLOWED_FRONTEND_URLS: list = [
    u.strip()
    for u in os.getenv("ALLOWED_FRONTEND_URLS", FRONTEND_REDIRECT_URI).split(",")
    if u.strip()
]
# OAuth state expiry in seconds (how long the state token is valid)
OAUTH_STATE_EXPIRY_SECONDS: int = int(os.getenv("OAUTH_STATE_EXPIRY_SECONDS", "600"))  # 10 minutes

# ─── Azure AD / MSAL Token Passthrough ───────────────────────────────────────
# Enable full RS256 signature verification for tokens issued by Infosys Azure AD.
# Used when an external application (e.g. DILO, SMART PM) passes its Infosys SSO
# token to IAF. IAF validates the token using Microsoft's public JWKS keys.
# Set AZURE_AD_ENABLED=true and fill in the values below to activate this path.
AZURE_AD_ENABLED: bool = os.getenv("AZURE_AD_ENABLED", "false").lower() == "true"

# Azure AD Tenant ID of the organization (Infosys)
# Visible in the JWKS URL: https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys
AZURE_TENANT_ID: str = os.getenv("AZURE_TENANT_ID", "")

# JWKS endpoint to fetch Microsoft's RSA public keys for signature verification.
# Auto-constructed from AZURE_TENANT_ID if not explicitly set.
AZURE_JWKS_URL: str = os.getenv(
    "AZURE_JWKS_URL",
    f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID', '')}/discovery/v2.0/keys"
    if os.getenv("AZURE_TENANT_ID") else ""
)

# Expected issuer (iss) claim in the incoming token.
# Auto-constructed from AZURE_TENANT_ID if not explicitly set.
AZURE_ISSUER: str = os.getenv(
    "AZURE_ISSUER",
    f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID', '')}/v2.0"
    if os.getenv("AZURE_TENANT_ID") else ""
)

# Expected audience (aud) claim — Client ID of the calling application.
# Typically: api://{client_id} or the client_id itself.
# Obtain this from the team whose token you are accepting.
AZURE_AUDIENCE: str = os.getenv("AZURE_AUDIENCE", "")

# App ID (appid claim) of the trusted calling application.
# Used as an additional check after signature verification.
TRUSTED_AZURE_APP_ID: str = os.getenv("TRUSTED_AZURE_APP_ID", "")

# Enable direct PWD login (ROPC grant) - DISABLE THIS when MFA is enabled in Keycloak
# When set to false, only Authorization Code Flow is allowed (required for MFA)
KEYCLOAK_ALLOW_DIRECT_LOGIN: bool = os.getenv("KEYCLOAK_ALLOW_DIRECT_LOGIN", "false").lower() == "true"

# Session cookie settings for OAuth flow
SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "iaf_session")
SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"  # Set to true in production (HTTPS)
SESSION_COOKIE_HTTPONLY: bool = True  # Always true for security
SESSION_COOKIE_SAMESITE: str = os.getenv("SESSION_COOKIE_SAMESITE", "lax")  # 'lax', 'strict', or 'none'

# OAuth Token Delivery Method - How to send tokens to frontend after successful OAuth callback
# Options:
#   - "code": MOST SECURE - One-time authorization code exchange (recommended for production)
#              Backend stores tokens in PostgreSQL with one-time code, frontend exchanges code for tokens
#              Works in pods/distributed architecture, tokens never in URL
#   - "post": Secure - Uses POST with auto-submit form (tokens in request body, not URL)
#   - "cookie": Secure for same-domain - Stores tokens in HTTP-Only cookies (requires same domain as frontend)
#   - "fragment": Legacy - Uses URL fragment (#) - tokens visible in browser address bar (NOT RECOMMENDED)
#
# RECOMMENDED: Use "code" for production (best security, works cross-domain, scalable)
OAUTH_TOKEN_DELIVERY_METHOD: str = os.getenv("OAUTH_TOKEN_DELIVERY_METHOD", "code").lower()

# Validate token delivery method
if OAUTH_TOKEN_DELIVERY_METHOD not in ("code", "post", "cookie", "fragment"):
    error_msg = (
        f"INVALID OAUTH_TOKEN_DELIVERY_METHOD: '{OAUTH_TOKEN_DELIVERY_METHOD}' is not valid. "
        "Valid values are 'code' (recommended), 'post', 'cookie', or 'fragment' (legacy). "
        "Set OAUTH_TOKEN_DELIVERY_METHOD in your .env file."
    )
    log.error(error_msg)
    raise ValueError(error_msg)

# Keycloak validation
if KEYCLOAK_ENABLED:
    if not all([KEYCLOAK_SERVER_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID]):
        error_msg = (
            "KEYCLOAK CONFIGURATION ERROR: Keycloak is enabled but required settings are missing. "
            "Set KEYCLOAK_SERVER_URL, KEYCLOAK_REALM, and KEYCLOAK_CLIENT_ID in your .env file."
        )
        log.error(error_msg)
        raise ValueError(error_msg)
    log.info(f"Keycloak authentication enabled for realm: {KEYCLOAK_REALM}")
    if KEYCLOAK_ALLOW_DIRECT_LOGIN:
        log.warning("Direct password login (ROPC) is enabled. This does NOT support MFA. Set KEYCLOAK_ALLOW_DIRECT_LOGIN=false for MFA.")

# Mutual exclusivity: KEYCLOAK_ENABLED and AZURE_AD_ENABLED cannot both be true
if KEYCLOAK_ENABLED and AZURE_AD_ENABLED:
    error_msg = (
        "CONFIGURATION ERROR: KEYCLOAK_ENABLED and AZURE_AD_ENABLED cannot both be set to true. "
        "Choose one authentication provider: set either KEYCLOAK_ENABLED=true or AZURE_AD_ENABLED=true in your .env file, not both."
    )
    log.error(error_msg)
    raise ValueError(error_msg)
