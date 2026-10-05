# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Startup Configuration Validator — Fail-fast with clear error messages.

Called once at the very beginning of the FastAPI lifespan.
Groups env vars into REQUIRED / RECOMMENDED / OPTIONAL tiers
and validates types, formats, and value ranges.

Exit-code 1 with descriptive message for any missing REQUIRED var.
"""

import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env-var declarations: (name, tier, validator, description)
# ---------------------------------------------------------------------------

def _is_nonempty(v: str) -> bool:
    return bool(v.strip())

def _is_int(v: str) -> bool:
    try: int(v); return True
    except ValueError: return False

def _is_port(v: str) -> bool:
    try: return 1 <= int(v) <= 65535
    except (ValueError, TypeError): return False

def _is_bool_like(v: str) -> bool:
    return v.lower() in ("true", "false", "1", "0", "yes", "no")

def _is_url(v: str) -> bool:
    return bool(re.match(r'^https?://', v, re.I))


# Tier constants
REQUIRED = "REQUIRED"
RECOMMENDED = "RECOMMENDED"
OPTIONAL = "OPTIONAL"

# (env_var_name, tier, validator_fn_or_None, description)
_CONFIG_SCHEMA: List[Tuple[str, str, Any, str]] = [
    # -- Database --
    ("POSTGRESQL_HOST",     REQUIRED,    _is_nonempty,  "PostgreSQL host address"),
    ("POSTGRESQL_PORT",     REQUIRED,    _is_port,      "PostgreSQL port (1-65535)"),
    ("POSTGRESQL_USER",     REQUIRED,    _is_nonempty,  "PostgreSQL username"),
    ("POSTGRESQL_PASSWORD", REQUIRED,    _is_nonempty,  "PostgreSQL password"),

    # -- Environment / Security --
    ("ENVIRONMENT",         REQUIRED,    lambda v: v.lower().strip() in ("development", "production"), "Must be 'development' or 'production'"),

    # -- Redis (required if session store enabled) --
    ("REDIS_HOST",          RECOMMENDED, _is_nonempty,  "Redis host address"),
    ("REDIS_PORT",          RECOMMENDED, _is_port,      "Redis port (1-65535)"),

    # -- LLM / Model --
    ("MODEL_SERVER_URL",    RECOMMENDED, _is_url,       "LiteLLM / model server URL (http[s]://...)"),

    # -- Auth --
    ("AUTH_JWT_SECRET",     RECOMMENDED, lambda v: v not in ("CHANGE_ME_DEV_ONLY", ""), "JWT secret (must be changed from default in production)"),

    # -- Server --
    ("SERVER_NAME",         OPTIONAL,    _is_nonempty,  "Server display name for telemetry"),
    ("USE_LITELLM_PROXY_FLAG", OPTIONAL, _is_bool_like, "Whether to use LiteLLM proxy (true/false)"),
    ("ENABLE_SESSION_STORE", OPTIONAL,   _is_bool_like, "Enable Redis session store (true/false)"),
    ("USE_OTEL_LOGGING",    OPTIONAL,    _is_bool_like, "Enable OpenTelemetry logging (true/false)"),
    ("SESSION_STORE_TTL",   OPTIONAL,    _is_int,       "Session TTL in seconds"),
]


# ---------------------------------------------------------------------------
# Validation runner
# ---------------------------------------------------------------------------

class ConfigValidationResult:
    """Holds the results of configuration validation."""

    def __init__(self):
        self.errors: List[str] = []       # REQUIRED missing/invalid
        self.warnings: List[str] = []     # RECOMMENDED missing/invalid
        self.info: List[str] = []         # OPTIONAL notes
        self.validated: List[str] = []    # Successfully validated vars

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def validate_startup_config() -> ConfigValidationResult:
    """Validate all env vars against the schema.

    Returns a ``ConfigValidationResult``.
    Logs all issues at the appropriate level.
    """
    result = ConfigValidationResult()

    for name, tier, validator, description in _CONFIG_SCHEMA:
        value = os.getenv(name)

        if value is None or value.strip() == "":
            msg = f"  {tier}: '{name}' is not set — {description}"
            if tier == REQUIRED:
                result.errors.append(msg)
            elif tier == RECOMMENDED:
                result.warnings.append(msg)
            else:
                result.info.append(msg)
            continue

        # Validate format if validator is provided
        if validator and not validator(value):
            msg = f"  {tier}: '{name}' has invalid value '{value[:30]}' — {description}"
            if tier == REQUIRED:
                result.errors.append(msg)
            elif tier == RECOMMENDED:
                result.warnings.append(msg)
            else:
                result.info.append(msg)
            continue

        result.validated.append(name)

    # --- Log results ---
    if result.errors:
        log.error("[ConfigValidator] REQUIRED configuration errors:")
        for e in result.errors:
            log.error(e)

    if result.warnings:
        log.warning("[ConfigValidator] RECOMMENDED configuration warnings:")
        for w in result.warnings:
            log.warning(w)

    if result.info:
        log.info("[ConfigValidator] Optional configuration notes:")
        for i in result.info:
            log.info(i)

    log.info(
        f"[ConfigValidator] Validated {len(result.validated)}/{len(_CONFIG_SCHEMA)} env vars. "
        f"Errors={len(result.errors)} Warnings={len(result.warnings)}"
    )

    return result


def validate_or_exit():
    """Run validation and exit(1) if any REQUIRED vars are missing/invalid.

    Safe to call from lifespan startup — prints clear diagnostics then exits.
    """
    result = validate_startup_config()
    if not result.ok:
        log.critical(
            "[ConfigValidator] FATAL: Missing or invalid REQUIRED configuration. "
            "Fix the issues above and restart."
        )
        # Don't sys.exit in test — raise instead
        if os.getenv("_IAF_TESTING"):
            raise SystemExit(1)
        sys.exit(1)
    return result


__all__ = [
    "validate_startup_config",
    "validate_or_exit",
    "ConfigValidationResult",
    "REQUIRED",
    "RECOMMENDED",
    "OPTIONAL",
]
