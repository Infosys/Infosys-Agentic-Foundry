import os
from dotenv import load_dotenv
from telemetry_wrapper import logger as log

# Load .env once (noop if already loaded elsewhere)
load_dotenv()

# Authentication / JWT settings pulled from environment with safe defaults.
# IMPORTANT: Override JWT_SECRET in production via environment variable.
JWT_SECRET: str = os.getenv("AUTH_JWT_SECRET", os.getenv("JWT_SECRET", "CHANGE_ME_DEV_ONLY"))
JWT_ALGORITHM: str = os.getenv("AUTH_JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_SECONDS: int = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_SECONDS", str(15 * 60)))  # default 15 mins
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("AUTH_REFRESH_TOKEN_EXPIRE_DAYS", "14"))  # default 14 days

# Optional: allow disabling refresh tokens (set to false)
ENABLE_REFRESH_TOKENS: bool = os.getenv("AUTH_ENABLE_REFRESH_TOKENS", "false").lower() == "true"

# Simple validation / warnings
if JWT_SECRET in ("CHANGE_ME_DEV_ONLY", "your_jwt_secret"):
    log.warning("JWT_SECRET is using a development default. Set AUTH_JWT_SECRET in .env for production.")
