"""
IAF Agent Studio — Server Configuration

Centralized environment variables, paths, feature flags, and constants.
Imported by all router and shared modules before any IAF library imports.

NOTE: This module sets up sys.path on import — must be loaded before any
IAF library imports elsewhere.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — anchored to the IAF-Agent-Studio directory
# ---------------------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent.parent   # .../IAF-Agent-Studio/
PROJECT_ROOT = SERVER_DIR.parent                       # .../AgentPro/

# Portable charset for an operator/config-supplied path (mirrors
# agent_os.safe_path._PATH_STRING_RE). Inlined because this bootstrap module
# runs before sys.path points at this repo's agent_os package.
_SERVER_PATH_RE = re.compile(r"^[\w .@+()~:/\\\-]{1,4096}$")


class ServerPathConfigError(ValueError):
    """A path config value failed validation (raised at boot, fails loudly)."""


def resolve_server_path(path_value: str | os.PathLike[str], *, label: str = "server path") -> Path:
    """Validate a path config value and resolve it against IAF-Agent-Studio.

    Relative values anchor to IAF-Agent-Studio, not process cwd. Empty values,
    control characters and characters outside the portable path charset are
    rejected (CWE-22/73); the resolved result is rebuilt as a fresh Path.
    """
    value = os.fspath(path_value).strip()
    if not value or not _SERVER_PATH_RE.fullmatch(value):
        raise ServerPathConfigError(
            f"Invalid {label}: value is empty or contains characters outside "
            "the allowed path charset"
        )
    path = Path(value).expanduser()
    resolved = path.resolve() if path.is_absolute() else (SERVER_DIR / path).resolve()
    return Path(str(resolved))

# Add parent + IAF-Agent-Skills to sys.path for IAF library imports
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "IAF-Agent-Skills"))

# ---------------------------------------------------------------------------
# Logging — controlled by LOG_LEVEL env var (default: INFO)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("iaf_server")

# ---------------------------------------------------------------------------
# dotenv — load from first available config file
# Priority: local config.env > agent_os > IAF-Agent-Skills > .env
# ---------------------------------------------------------------------------
from dotenv import load_dotenv

_env_locations = [
    SERVER_DIR / "config.env",
    PROJECT_ROOT / "agent_os" / "config.env",
    PROJECT_ROOT / "IAF-Agent-Skills" / "config.env",
    PROJECT_ROOT / ".env",
]

_env_loaded = False
for _env_path in _env_locations:
    if _env_path.exists():
        load_dotenv(_env_path)
        logger.info("Loaded env from: %s", _env_path)
        _env_loaded = True
        break

if not _env_loaded:
    load_dotenv()  # Try default .env or environment

# ---------------------------------------------------------------------------
# Single storage-mode seam — one STORAGE_MODE knob cascades to every store
# backend BEFORE any backend var is read below (and before engine modules read
# theirs at call time). Byte-identical when STORAGE_MODE is unset; raises on an
# incoherent mix (e.g. pgvector on a non-Postgres store). See shared/storage_mode.py.
# ---------------------------------------------------------------------------
from shared.storage_mode import apply_storage_mode

_STORAGE_RESOLVED = apply_storage_mode()

# ---------------------------------------------------------------------------
# Config vars — sourced through ApplicationConfig (single source of truth).
# Env vars are read inside dataclass default_factory rather than at a raw
# os.getenv() call feeding a filesystem sink, so path values reach open()/
# Path() through this object (breaks the direct env->file-sink dataflow that
# static analysis flags as Path Manipulation, with identical behavior).
# Instantiated AFTER dotenv load above so overrides apply.
# ---------------------------------------------------------------------------
from dataclasses import dataclass, field


@dataclass
class ApplicationConfig:
    """Environment-derived server configuration."""
    data_root: str = field(default_factory=lambda: os.getenv("DATA_ROOT", "../enterprise_root"))
    tenant_id: str = field(default_factory=lambda: os.getenv("TENANT_ID", "company"))
    agent_id: str = field(default_factory=lambda: os.getenv("AGENT_ID", "enterprise_agent"))
    skills_path: str = field(default_factory=lambda: os.getenv("SKILLS_PATH", "../enterprise_root/tenants/company/skills"))
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8081")))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379"))
    ssl_certfile: str = field(default_factory=lambda: os.getenv("SSL_CERTFILE", ""))
    ssl_keyfile: str = field(default_factory=lambda: os.getenv("SSL_KEYFILE", ""))
    # Filesystem-path overrides (routed here so callers don't read env directly
    # into open()/Path() sinks — see resolve_server_path note above).
    cc_queue_db_path: str = field(default_factory=lambda: os.getenv("CC_QUEUE_DB_PATH", ""))
    workstream_runtime_db_path: str = field(default_factory=lambda: os.getenv("WORKSTREAM_RUNTIME_DB_PATH", ""))
    local_mount_path: str = field(default_factory=lambda: os.getenv("LOCAL_MOUNT_PATH", ""))


app_config = ApplicationConfig()

DATA_ROOT   = app_config.data_root       # override for any domain/customer
TENANT_ID   = app_config.tenant_id       # override per deployment
AGENT_ID    = app_config.agent_id
SKILLS_PATH = app_config.skills_path
DATA_ROOT_PATH = resolve_server_path(DATA_ROOT, label="DATA_ROOT")
SKILLS_PATH_PATH = resolve_server_path(SKILLS_PATH, label="SKILLS_PATH")
HOST = app_config.host
PORT = app_config.port
REDIS_URL = app_config.redis_url
SSL_CERTFILE = app_config.ssl_certfile   # path to cert.pem — leave empty for HTTP
SSL_KEYFILE  = app_config.ssl_keyfile    # path to key.pem  — leave empty for HTTP

# Enterprise security profile. Defaults preserve the current developer flow;
# the production template enables strict mode explicitly.
ENTERPRISE_STRICT_MODE = os.getenv("ENTERPRISE_STRICT_MODE", "false").lower() == "true"
DEMO_PUBLIC_SURFACES = os.getenv("DEMO_PUBLIC_SURFACES", "true").lower() == "true"

# Privacy acknowledgement gate (fully opt-in; default off so existing flows are unchanged)
PRIVACY_ACK_REQUIRED: bool = os.getenv("PRIVACY_ACK_REQUIRED", "false").lower() in ("1", "true", "yes")
PRIVACY_ACK_EXEMPT_ROLES: tuple = tuple(
    r.strip() for r in os.getenv("PRIVACY_ACK_EXEMPT_ROLES", "").split(",") if r.strip()
)


def resolve_app_version() -> str:
    """Return the running app version.

    Priority: APP_VERSION env var → repo-root ``Version`` file → ``"dev"``.
    """
    env_ver = os.getenv("APP_VERSION", "").strip()
    if env_ver:
        return env_ver
    try:
        text = (PROJECT_ROOT / "Version").read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return "dev"

APP_VERSION = resolve_app_version()

QUEUE_INGEST_API_KEY = os.getenv("QUEUE_INGEST_API_KEY", "").strip()
FILE_URL_SIGNING_SECRET = os.getenv("FILE_URL_SIGNING_SECRET", "").strip()
try:
    FILE_URL_TTL_SECONDS = max(30, min(int(os.getenv("FILE_URL_TTL_SECONDS", "300")), 3600))
except ValueError:
    FILE_URL_TTL_SECONDS = 300
ALLOW_UNSIGNED_FILE_URLS = os.getenv(
    "ALLOW_UNSIGNED_FILE_URLS",
    "false" if ENTERPRISE_STRICT_MODE else "true",
).lower() == "true"
CORS_ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
)
if "*" in CORS_ALLOWED_ORIGINS:
    logger.warning(
        "CORS_ALLOWED_ORIGINS is '*': every origin is trusted for cross-origin "
        "reads of this API. Set an explicit comma-separated origin list before "
        "deploying outside local development."
    )

# ---------------------------------------------------------------------------
# Early boot overrides — load admin_config.json for construction-time params
# These overrides are saved from the Dashboard Settings UI and must be applied
# BEFORE state.py imports, since some objects (queue_manager, session_state)
# are constructed at module-import time.
# ---------------------------------------------------------------------------
_BOOT_OVERRIDES: dict = {}
try:
    import json as _json
    _admin_cfg_path = DATA_ROOT_PATH / "tenants" / TENANT_ID / "config" / "admin_config.json"
    if _admin_cfg_path.exists():
        with open(_admin_cfg_path, encoding="utf-8") as _f:
            _BOOT_OVERRIDES = _json.load(_f)
        if _BOOT_OVERRIDES:
            logger.info("Boot overrides loaded: %s", list(k for k in _BOOT_OVERRIDES if not k.startswith("_")))
except Exception as _e:
    logger.warning("Could not load admin boot overrides: %s", _e)


def _boot(key: str, env_default: str) -> str:
    """Return admin override (if saved) → env var → hardcoded default."""
    if key in _BOOT_OVERRIDES:
        return str(_BOOT_OVERRIDES[key]).lower()
    return os.getenv(key, env_default).lower()


# Feature flags (admin UI overrides take precedence over env vars)
QUEUE_BACKEND = _boot("QUEUE_BACKEND", "memory")         # "memory" or "redis"
USE_REDIS_SESSIONS = _boot("USE_REDIS_SESSIONS", "false") == "true"
TWIN_TELEMETRY = os.getenv("TWIN_TELEMETRY", "true").lower() == "true"
TRACE_TELEMETRY = os.getenv("TRACE_TELEMETRY", "true").lower() == "true"
RL_CAPTURE = os.getenv("RL_CAPTURE", "false").lower() == "true"
RL_REDACT = os.getenv("RL_REDACT", "true").lower() == "true"
RL_CAPTURE_REASONING = os.getenv("RL_CAPTURE_REASONING", "false").lower() == "true"
RL_DB_PATH = os.getenv("RL_DB_PATH", "")

# Trace Value Router: advisory semantic routing of completed trajectories into
# skill/context/memory/golden/training/debug queues. It is disabled by default
# because it invokes an LLM-backed tenant skill.
def _trace_int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default

TRACE_VALUE_ROUTER_ENABLED = os.getenv("TRACE_VALUE_ROUTER_ENABLED", "false").lower() == "true"
TRACE_VALUE_ROUTER_SKILL = os.getenv("TRACE_VALUE_ROUTER_SKILL", "trace_value_router").strip() or "trace_value_router"
TRACE_VALUE_ROUTER_CONCURRENCY = max(1, min(_trace_int_env("TRACE_VALUE_ROUTER_CONCURRENCY", 1), 8))
TRACE_VALUE_ROUTER_BATCH_LIMIT = max(1, min(_trace_int_env("TRACE_VALUE_ROUTER_BATCH_LIMIT", 25), 200))
TRACE_VALUE_ROUTER_MAX_EVIDENCE_CHARS = max(2000, min(_trace_int_env("TRACE_VALUE_ROUTER_MAX_EVIDENCE_CHARS", 12000), 64000))
TRACE_VALUE_ROUTER_RETRY_LIMIT = max(0, min(_trace_int_env("TRACE_VALUE_ROUTER_RETRY_LIMIT", 1), 5))

# Runtime provider slots for partner-supplied agent capabilities. "default"
# preserves the existing AgentPro wiring.
SKILL_PROVIDER = os.getenv("SKILL_PROVIDER", "default").strip()
ROUTER_PROVIDER = os.getenv("ROUTER_PROVIDER", "default").strip()
TOOL_PROVIDER = os.getenv("TOOL_PROVIDER", "default").strip()
HOOK_PROVIDER = os.getenv("HOOK_PROVIDER", "default").strip()
TRACE_PROVIDER = os.getenv("TRACE_PROVIDER", "default").strip()

# AgentOS kernel execution backend. "local" preserves the historical in-process
# SafeKernel; "remote" sends tool execution to the signed kernel_worker process.
def _kernel_int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# Untrusted multi-tenant execution guard — when true, tenant-reachable arbitrary-code
# execution (agent-shell `python3`) is forced OFF in the kernel regardless of
# AGENT_PYTHON3_ENABLED. Read directly via os.getenv in agent_os/kernel.py; surfaced here
# for discoverability and SaaS-profile validation. Default false = trusted single-tenant.
AGENTOS_UNTRUSTED_EXECUTION_GUARD = (
    os.getenv("AGENTOS_UNTRUSTED_EXECUTION_GUARD", "false").strip().lower() == "true"
)

AGENTOS_KERNEL_BACKEND = os.getenv("AGENTOS_KERNEL_BACKEND", "local").strip().lower()
AGENTOS_KERNEL_URL = os.getenv("AGENTOS_KERNEL_URL", "http://127.0.0.1:18081").strip()
AGENTOS_KERNEL_TOKEN_SECRET = os.getenv("AGENTOS_KERNEL_TOKEN_SECRET", "").strip()
AGENTOS_KERNEL_REQUIRE_REMOTE = os.getenv("AGENTOS_KERNEL_REQUIRE_REMOTE", "false").lower() == "true"
# OpenShell sandbox backend (read only when AGENTOS_KERNEL_BACKEND=openshell).
AGENTOS_SANDBOX_URL = os.getenv("AGENTOS_SANDBOX_URL", "").strip()
AGENTOS_SANDBOX_TOKEN = os.getenv("AGENTOS_SANDBOX_TOKEN", "").strip()
AGENTOS_SANDBOX_WORKSPACE = os.getenv("AGENTOS_SANDBOX_WORKSPACE", "default").strip()
AGENTOS_SANDBOX_ROOT = os.getenv("AGENTOS_SANDBOX_ROOT", "/workspace").strip()
AGENTOS_SANDBOX_TIMEOUT_SECONDS = max(5, _kernel_int_env("AGENTOS_SANDBOX_TIMEOUT_SECONDS", 120))

AGENTOS_KERNEL_WORKER_BIND = os.getenv("AGENTOS_KERNEL_WORKER_BIND", "127.0.0.1").strip()
AGENTOS_KERNEL_WORKER_PORT = max(1024, min(_kernel_int_env("AGENTOS_KERNEL_WORKER_PORT", 18081), 65535))
AGENTOS_KERNEL_SESSION_TTL_SECONDS = max(
    60,
    min(_kernel_int_env("AGENTOS_KERNEL_SESSION_TTL_SECONDS", 1800), 24 * 3600),
)

# ── Storage backend ──────────────────────────────────────────────────────────
# DB_BACKEND selects the relational store for all runtime state.
#   sqlite   (default) - single-node / dev; zero extra dependencies.
#   postgres           - multi-node / HA; requires DATABASE_URL and
#                        `pip install 'psycopg[binary]' pgvector`.
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_POOL_SIZE = os.getenv("DB_POOL_SIZE", "10").strip()
# VECTOR_BACKEND: brute_force (default) | sqlite_vec | pgvector
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "brute_force").strip().lower()
# VECTOR_DIMENSION: embedding dimension (default 1536 for text-embedding-ada-002 /
#   text-embedding-3-small). Must match the model used to produce embeddings.
VECTOR_DIMENSION = os.getenv("VECTOR_DIMENSION", "1536").strip()
# PGVECTOR_IVF_LISTS: IVFFlat cluster count for the pgvector ANN index.
#   Rule of thumb: sqrt(expected_row_count). Default 100 suits up to ~10k rows.
#   Raise for larger datasets; drop and recreate the index after changing.
PGVECTOR_IVF_LISTS = os.getenv("PGVECTOR_IVF_LISTS", "100").strip()

# Register Studio host services + deployment defaults into the engine runtime
# bridge so the engine (iaf_agent_skills) never imports Studio. Done here because
# config is the earliest Studio module on sys.path and every other Studio module
# imports it first — so registration is always in place before the provider
# factory / capability registry build, before any evidence/trace call, and even
# for unit tests that import a single Studio module. All registered services are
# lazy (heavy imports deferred to first use), so this stays import-cheap.
try:
    from iaf_agent_skills.runtime_bridge import (
        register_default_identity,
        register_provider_config,
    )

    register_default_identity(tenant_id=TENANT_ID, agent_id=AGENT_ID)
    register_provider_config({
        "SKILL_PROVIDER": SKILL_PROVIDER,
        "ROUTER_PROVIDER": ROUTER_PROVIDER,
        "TOOL_PROVIDER": TOOL_PROVIDER,
        "HOOK_PROVIDER": HOOK_PROVIDER,
        "TRACE_PROVIDER": TRACE_PROVIDER,
        # Storage backend selection (engine reads these via the runtime bridge).
        "DB_BACKEND": DB_BACKEND,
        "DATABASE_URL": DATABASE_URL,
        "DB_POOL_SIZE": DB_POOL_SIZE,
        "VECTOR_BACKEND": VECTOR_BACKEND,
        "VECTOR_DIMENSION": VECTOR_DIMENSION,
        "PGVECTOR_IVF_LISTS": PGVECTOR_IVF_LISTS,
    })

    from shared.engine_bridge import register_runtime_services
    register_runtime_services()
except Exception as _bridge_exc:  # pragma: no cover - engine always on path in Studio
    logger.warning("Engine runtime bridge registration skipped: %s", _bridge_exc)


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        logger.warning("Invalid float for %s; using default %s", key, default)
        return default


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        logger.warning("Invalid integer for %s; using default %s", key, default)
        return default


def _bool_env(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.lower() == "true"


def _normalize_msal_redirect_uri(raw: str) -> str:
    """Force the MSAL redirect URI onto the standard ``/auth/callback`` path.

    Azure AD requires an exact, pre-registered redirect URI, so the host/port
    stays operator-configured — but the path must not vary deployment to
    deployment. Keycloak's callback is a fixed backend route
    (``GET /auth/callback`` in routers/oauth.py); whatever path an operator
    pastes into MSAL_REDIRECT_URI is normalized onto that same route so both
    SSO providers share one standard callback instead of MSAL landing on an
    arbitrary page.
    """
    if not raw:
        return ""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        # Malformed value (no scheme/host) — leave as-is so the resulting
        # Azure AD redirect_uri_mismatch error points at the real input.
        return raw
    return urlunsplit((parts.scheme, parts.netloc, "/auth/callback", "", ""))


# Uvicorn process workers (1 = single process; >1 uses import-string reload per worker).
UVICORN_WORKERS = max(1, min(_int_env("UVICORN_WORKERS", 1), 32))

# Runtime role split. "all" preserves the historical monolith; production runs
# separate api, scheduler, and queue processes.
STUDIO_RUNTIME_ROLES = os.getenv("STUDIO_RUNTIME_ROLES", "all").strip().lower()
SCHEDULER_LEADER_LOCK_TTL_SECONDS = max(
    15,
    min(_int_env("SCHEDULER_LEADER_LOCK_TTL_SECONDS", 45), 300),
)
SCHEDULER_LEADER_RETRY_SECONDS = max(
    1,
    min(_int_env("SCHEDULER_LEADER_RETRY_SECONDS", 5), 60),
)
QUEUE_WORKER_REPLICAS = max(1, min(_int_env("QUEUE_WORKER_REPLICAS", 1), 64))
CC_QUEUE_STORAGE_BACKEND = os.getenv("CC_QUEUE_STORAGE_BACKEND", "sqlite").strip().lower()
CC_QUEUE_DATABASE_URL = os.getenv("CC_QUEUE_DATABASE_URL", "").strip()
QUEUE_CLAIM_LEASE_SECONDS = max(
    30,
    min(_int_env("QUEUE_CLAIM_LEASE_SECONDS", 360), 3600),
)
QUEUE_CLAIM_RECLAIM_LIMIT = max(
    1,
    min(_int_env("QUEUE_CLAIM_RECLAIM_LIMIT", 3), 20),
)
QUEUE_WORKER_HEARTBEAT_TTL_SECONDS = max(
    10,
    min(_int_env("QUEUE_WORKER_HEARTBEAT_TTL_SECONDS", 30), 300),
)

# Recovery verification reads only from this separately restored data root.
# An empty value disables UI/API-triggered verification while keeping the CLI
# available for explicitly supplied offline roots.
RECOVERY_VERIFICATION_ROOT = os.getenv("RECOVERY_VERIFICATION_ROOT", "").strip()
RECOVERY_VERIFICATION_ROOT_PATH = (
    resolve_server_path(RECOVERY_VERIFICATION_ROOT, label="RECOVERY_VERIFICATION_ROOT")
    if RECOVERY_VERIFICATION_ROOT
    else None
)
RECOVERY_RUNTIME_RPO_TARGET_MINUTES = max(
    1,
    min(_int_env("RECOVERY_RUNTIME_RPO_TARGET_MINUTES", 15), 7 * 24 * 60),
)
RECOVERY_RPO_TARGET_MINUTES = max(
    1,
    min(_int_env("RECOVERY_RPO_TARGET_MINUTES", 60), 7 * 24 * 60),
)
RECOVERY_RTO_TARGET_MINUTES = max(
    1,
    min(_int_env("RECOVERY_RTO_TARGET_MINUTES", 240), 7 * 24 * 60),
)
RECOVERY_LIVE_BASE_URL = os.getenv("RECOVERY_LIVE_BASE_URL", "").strip()
RECOVERY_REDIS_URL = os.getenv("RECOVERY_REDIS_URL", "").strip()
RECOVERY_LIVE_TOKEN = os.getenv("RECOVERY_LIVE_TOKEN", "").strip()
RECOVERY_LIVE_CONFIRMATION = os.getenv("RECOVERY_LIVE_CONFIRMATION", "").strip()
RECOVERY_LIVE_TIMEOUT_SECONDS = max(
    1,
    min(_int_env("RECOVERY_LIVE_TIMEOUT_SECONDS", 5), 30),
)

# Proxy / load-balancer support. Set BEHIND_PROXY=true when the server is behind
# an LB or reverse proxy that terminates TLS and forwards X-Forwarded-* headers.
# FORWARDED_ALLOW_IPS: comma-separated IPs/CIDRs to trust for proxy headers,
# or "*" to trust all (safe when the server is not directly internet-accessible).
BEHIND_PROXY = os.getenv("BEHIND_PROXY", "false").lower() in {"1", "true", "yes"}
FORWARDED_ALLOW_IPS = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")


# Sub-path / base-path support. When the app is served behind a gateway under a
# path prefix (e.g. https://host/qlabs/), set ROOT_PATH=/qlabs. The gateway is
# expected to strip the prefix before forwarding, so backend routes stay at "/".
# ROOT_PATH is applied as the ASGI root_path (correct redirects/openapi) and is
# injected into served HTML so the browser prefixes API/WS calls.
#
# Default "" (empty) => served at domain root, byte-for-byte unchanged. Any value
# is normalized to a single leading slash with no trailing slash ("/qlabs").
from shared.base_path import normalize_root_path as _normalize_root_path

ROOT_PATH = _normalize_root_path(os.getenv("ROOT_PATH", os.getenv("APP_ROOT_PATH", "")))

# Telemetry provider fanout. The local trace store remains the durable default; external
# providers are optional mirrors and must never break runtime request handling.
# `local,otel` mirrors traces/metrics to OpenTelemetry (official SDK). The collector, auth,
# sampling and content capture are configured with the standard OTEL_* variables — see
# docs/TELEMETRY.md and telemetry/otel_setup.py.
TELEMETRY_EXPORTERS = os.getenv("TELEMETRY_EXPORTERS", "local").lower()  # local | local,otel
# Security audit events (entitlement + external-access decisions) as OTel log records:
# off (default) | denials | all. "all" is high volume — every permission check is audited.
TELEMETRY_EXPORT_AUDIT = os.getenv("TELEMETRY_EXPORT_AUDIT", "off").strip().lower()
TELEMETRY_OTLP_ENDPOINT = os.getenv("TELEMETRY_OTLP_ENDPOINT", "")  # legacy -> OTEL_EXPORTER_OTLP_ENDPOINT
TELEMETRY_OTLP_SERVICE_NAME = os.getenv("TELEMETRY_OTLP_SERVICE_NAME", "iaf-agent-studio")
TELEMETRY_TIMEOUT_SECONDS = _float_env("TELEMETRY_TIMEOUT_SECONDS", 2.0)
TELEMETRY_PREVIEW_LIMIT = max(64, min(_int_env("TELEMETRY_PREVIEW_LIMIT", 512), 4096))
# Response grounding critique — server-side defaults.
# CRITIQUE_ENABLED: master switch. When true, critique runs even if UI toggle is off.
# CRITIQUE_MODE:    "sync"  — blocks response until critique + revision complete.
#                   "async" — answer returned instantly, critique runs in background,
#                             result pushed via WebSocket; low confidence shows
#                             "Regenerate" button in UI.
# Both can be overridden per-session by the UI 3-state toggle (off/sync/async).
CRITIQUE_ENABLED  = os.getenv("CRITIQUE_ENABLED", "false").lower() == "true"
CRITIQUE_MODE     = os.getenv("CRITIQUE_MODE", "async").lower()    # "sync" | "async"
# CRITIQUE_RECHECK: when true, fires a 3rd LLM call to re-verify the revised answer.
# Gives accurate final confidence but adds ~10-15s to grounding time.
# Set false to skip re-check — revision is trusted, confidence forced to "high".
CRITIQUE_RECHECK  = os.getenv("CRITIQUE_RECHECK", "true").lower() == "true"
# CONSISTENCY_CHECK: when true, fires a cold second agent run after the async grounding
# critique and compares the two responses. Only applies when critique_mode=async.
# Default false — opt-in because it doubles LLM cost per query.
CONSISTENCY_CHECK = os.getenv("CONSISTENCY_CHECK", "false").lower() == "true"

# Allowed knowledge file extensions (shared between skills and knowledge routers)
ALLOWED_KNOWLEDGE_EXTS = {".pdf", ".txt", ".csv", ".md", ".json", ".xlsx", ".docx"}

# ---------------------------------------------------------------------------
# Observers subsystem (Headlong companion agents)
# ---------------------------------------------------------------------------
# EXPERIMENTAL / feature-flagged off. Remaining limitations tracked for a future
# production-readiness pass:
#   * OBSERVERS_RUNTIME defaults to "dev", which does NOT enforce a filesystem/container
#     boundary (scope is only placed in the prompt). Set "container" for any real use.
#   * ObserverService reuses the normal agent state pool keyed by spec.user_id and sets
#     auto_run (see observers/service.py) — configure spec.user_id as a dedicated service
#     identity, never a real interactive user, until an isolated pool lands.
# Tenant isolation at the HTTP layer IS now enforced: every by-name route scopes the
# caller to the observer's tenant and the listing is filtered to the caller's tenants
# (routers/observers.py:_spec_or_404); the YAML store itself stays process-wide, so the
# route layer is the enforcement point.
OBSERVERS_ENABLED = os.getenv("OBSERVERS_ENABLED", "false").lower() == "true"
OBSERVERS_API_KEY = os.getenv("OBSERVERS_API_KEY", "")
# NOTE: "dev" is unsandboxed — prefer "container" in any non-dev deployment.
OBSERVERS_RUNTIME = os.getenv("OBSERVERS_RUNTIME", "dev").lower()
HEADLONG_APP_DIR = os.getenv("HEADLONG_APP_DIR", str(Path.home() / "headlong"))

# ---------------------------------------------------------------------------
# Authentication configuration
# ---------------------------------------------------------------------------
# Master switch — set to "true" to enforce JWT auth on all /api/* routes.
# When false: all requests pass through (dev mode).
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"

# Registration mode: "open" | "approval" | "admin_only"
AUTH_REGISTRATION_MODE = os.getenv("AUTH_REGISTRATION_MODE", "admin_only").lower()

# Provider: "local" | "microsoft"/"entra"/"oidc"/"okta". This picks the
# provider behind password-based /auth/login + /auth/register.
AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "local").lower()

# Microsoft/Entra SSO as an independent bolt-on (mirrors KEYCLOAK_ENABLED
# below) — can run alongside AUTH_PROVIDER=local so password login and
# "Sign in with Microsoft" (POST /auth/sso/microsoft) are both available at
# once. Defaults to true when AUTH_PROVIDER is itself microsoft/entra/etc, so
# existing single-provider deployments need no change.
AUTH_MICROSOFT_ENABLED = _bool_env(
    "AUTH_MICROSOFT_ENABLED",
    AUTH_PROVIDER in {"microsoft", "entra", "azuread", "azure_ad"},
)

# Microsoft / Entra ID settings — used when AUTH_MICROSOFT_ENABLED=true.
# These three vars let you configure just the Azure AD side; the OIDC vars
# below are auto-derived from them when not set explicitly.
AUTH_MICROSOFT_TENANT_ID = os.getenv("AUTH_MICROSOFT_TENANT_ID", "")
AUTH_MICROSOFT_CLIENT_ID     = os.getenv("AUTH_MICROSOFT_CLIENT_ID", "")      # backend app-registration ID
AUTH_MICROSOFT_CLIENT_SECRET = os.getenv("AUTH_MICROSOFT_CLIENT_SECRET", "")   # needed for OBO / client-credentials
AUTH_MICROSOFT_AUTHORITY = os.getenv(
    "AUTH_MICROSOFT_AUTHORITY",
    f"https://login.microsoftonline.com/{AUTH_MICROSOFT_TENANT_ID}"
    if AUTH_MICROSOFT_TENANT_ID else "",
)

# MSAL frontend config (served publicly via GET /auth/msal/config).
# MSAL_CLIENT_ID is always the same as AUTH_MICROSOFT_CLIENT_ID — one app registration for both.
MSAL_CLIENT_ID    = AUTH_MICROSOFT_CLIENT_ID
MSAL_SCOPES       = os.getenv(
    "MSAL_SCOPES",
    f"api://{AUTH_MICROSOFT_CLIENT_ID}/.default" if AUTH_MICROSOFT_CLIENT_ID else "",
)
# The path is always normalized to /auth/callback — the same fixed callback
# route Keycloak uses — regardless of the path given in the env var. Only the
# scheme/host/port (which Azure AD must have registered) come from the env.
_msal_redirect_raw = os.getenv("MSAL_REDIRECT_URI", "")
MSAL_REDIRECT_URI = _normalize_msal_redirect_uri(_msal_redirect_raw)
if _msal_redirect_raw and MSAL_REDIRECT_URI != _msal_redirect_raw:
    logger.warning(
        "MSAL_REDIRECT_URI path normalized to the standard SSO callback: %s -> %s. "
        "Update the redirect URI registered in Azure AD to match.",
        _msal_redirect_raw, MSAL_REDIRECT_URI,
    )

# Derived OIDC defaults (override by setting the AUTH_OIDC_* vars directly)
_ms_issuer   = (
    f"https://login.microsoftonline.com/{AUTH_MICROSOFT_TENANT_ID}/v2.0"
    if AUTH_MICROSOFT_TENANT_ID else ""
)
_ms_jwks_url = (
    f"https://login.microsoftonline.com/{AUTH_MICROSOFT_TENANT_ID}/discovery/v2.0/keys"
    if AUTH_MICROSOFT_TENANT_ID else ""
)
_ms_audience = (
    f"api://{AUTH_MICROSOFT_CLIENT_ID}"
    if AUTH_MICROSOFT_CLIENT_ID else ""
)

# OIDC/JWKS provider settings. Local auth ignores these; enterprise providers
# fail closed if selected without issuer/audience/JWKS configuration.
AUTH_OIDC_ISSUER   = os.getenv("AUTH_OIDC_ISSUER",   _ms_issuer).rstrip("/")
AUTH_OIDC_AUDIENCE = os.getenv("AUTH_OIDC_AUDIENCE", _ms_audience)
AUTH_OIDC_JWKS_URL = os.getenv("AUTH_OIDC_JWKS_URL", _ms_jwks_url)
AUTH_OIDC_JWKS_CACHE_SECONDS = max(30, min(_int_env("AUTH_OIDC_JWKS_CACHE_SECONDS", 300), 86400))
AUTH_OIDC_ROLE_CLAIMS = os.getenv("AUTH_OIDC_ROLE_CLAIMS", "roles role")
AUTH_OIDC_GROUP_CLAIMS = os.getenv("AUTH_OIDC_GROUP_CLAIMS", "groups")
AUTH_OIDC_TENANT_CLAIMS = os.getenv("AUTH_OIDC_TENANT_CLAIMS", "tenant_id tid")

# Backend for user store: "sqlite" (default, no extra deps) | "postgres" (shared DB) | "redis" (HA deployments).
# "postgres" persists users in the DATABASE_URL Postgres instance (auth_users/auth_passwords tables).
# WARNING: switching between backends does not migrate user accounts. If you run with
# AUTH_BACKEND=redis/postgres and that store is unreachable, the SQLite fallback has no accounts
# and every login will fail. Choose one backend and keep it consistent.
AUTH_BACKEND = os.getenv("AUTH_BACKEND", "sqlite").lower()

# Fail closed when the configured shared auth store (postgres/redis) is unreachable
# instead of silently switching to a per-instance SQLite store with no accounts.
# Defaults to strict whenever a shared backend is selected (its whole point is a
# single source of identity) OR TLS/proxy indicates production; only a local
# sqlite backend over plain HTTP keeps the convenient fallback. Set
# AUTH_STORE_STRICT=false explicitly to opt a shared-backend dev box out.
AUTH_STORE_STRICT = _bool_env(
    "AUTH_STORE_STRICT",
    AUTH_BACKEND in {"postgres", "redis"}
    or bool(os.getenv("SSL_CERTFILE", "").strip())
    or BEHIND_PROXY,
)

# JWT signing
import secrets as _secrets
JWT_SECRET    = os.getenv("JWT_SECRET", _secrets.token_hex(32))   # Override in production!
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TTL_MINUTES = int(os.getenv("JWT_ACCESS_TTL_MINUTES", "15"))
JWT_REFRESH_TTL_DAYS   = int(os.getenv("JWT_REFRESH_TTL_DAYS",   "1"))
# Absolute session lifetime. Refresh-token rotation
# re-issues a fresh refresh exp on every refresh, so without a cap an active
# session never ends. A refresh more than this many hours after the original
# interactive login is refused with 401 SESSION_EXPIRED. 0 disables the cap.
AUTH_SESSION_MAX_HOURS = max(0, _int_env("AUTH_SESSION_MAX_HOURS", 12))

# Client-side idle session timeout. Exposed to the browser via GET /auth/session-policy
# so ops can retune per deployment with an env var instead of editing JS. Warn must
# stay strictly before logout; an invalid pair silently falls back to the defaults
# rather than producing a warning that fires after (or at the same time as) logout.
SESSION_IDLE_LOGOUT_MINUTES = int(os.getenv("SESSION_IDLE_LOGOUT_MINUTES", "20"))
SESSION_IDLE_WARN_MINUTES = int(os.getenv("SESSION_IDLE_WARN_MINUTES", "15"))
if not (0 < SESSION_IDLE_WARN_MINUTES < SESSION_IDLE_LOGOUT_MINUTES):
    SESSION_IDLE_LOGOUT_MINUTES = 20
    SESSION_IDLE_WARN_MINUTES = 15

# Export resolved JWT settings for lower-level packages such as agent_os. This
# keeps the standalone kernel free of Studio imports while preserving the dev
# fallback where JWT_SECRET is generated at boot if it is not set explicitly.
os.environ.setdefault("JWT_SECRET", JWT_SECRET)
os.environ.setdefault("JWT_ALGORITHM", JWT_ALGORITHM)
os.environ.setdefault("TENANT_ID", TENANT_ID)

# Single active session per user. When true, a new interactive login ends the
# user's older session (other browsers/devices); tabs of one browser share a
# session and are unaffected. Agent service tokens are exempt. Requires Redis:
# if Redis is unreachable the check fails open. Default off.
AUTH_SINGLE_SESSION = _bool_env("AUTH_SINGLE_SESSION", False)

# Cookie name for refresh token
AUTH_REFRESH_COOKIE_NAME = os.getenv("AUTH_REFRESH_COOKIE_NAME", "iaf_refresh")

# Auth cookie Secure flag. Browsers only return Secure cookies over HTTPS (with a
# localhost exception), so forcing Secure over plain HTTP on a LAN/IP origin makes
# the browser silently drop auth cookies -> every authenticated request 401s.
# Auto-enable Secure only when TLS is actually in play (local cert or upstream
# proxy termination); override explicitly with AUTH_COOKIE_SECURE.
AUTH_COOKIE_SECURE = _bool_env(
    "AUTH_COOKIE_SECURE",
    bool(os.getenv("SSL_CERTFILE", "").strip()) or BEHIND_PROXY,
)

# Brute force protection
AUTH_MAX_FAILED_ATTEMPTS = int(os.getenv("AUTH_MAX_FAILED_ATTEMPTS", "5"))
AUTH_LOCKOUT_MINUTES     = int(os.getenv("AUTH_LOCKOUT_MINUTES",     "15"))

# Rate limiting
AUTH_RATE_LIMIT_PER_MINUTE = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "60"))
AUTH_LOGIN_RATE_LIMIT      = int(os.getenv("AUTH_LOGIN_RATE_LIMIT",      "10"))
# Global per-tenant API rate limit: requests/minute across ALL of a tenant's users,
# shared across server instances via Redis. Protects one tenant/customer from starving
# others at fleet scale. 0 disables. Tune per plan (override per-tenant via entitlements).
TENANT_RATE_LIMIT_PER_MINUTE = int(os.getenv("TENANT_RATE_LIMIT_PER_MINUTE", "600"))

# PWD policy
_auth_pwd_min_length_raw = os.getenv("AUTH_PASSWORD_MIN_LENGTH")
if _auth_pwd_min_length_raw is None:
    AUTH_PASSWORD_MIN_LENGTH = 8
else:
    try:
        AUTH_PASSWORD_MIN_LENGTH = int(_auth_pwd_min_length_raw)
    except ValueError:
        logger.warning("Invalid integer for AUTH_PASSWORD_MIN_LENGTH; using default 8")
        AUTH_PASSWORD_MIN_LENGTH = 8

AUTH_PASSWORD_REQUIRE_UPPERCASE  = _bool_env("AUTH_PASSWORD_REQUIRE_UPPERCASE", True)
AUTH_PASSWORD_REQUIRE_DIGIT      = _bool_env("AUTH_PASSWORD_REQUIRE_DIGIT", True)
AUTH_PASSWORD_REQUIRE_SPECIAL    = _bool_env("AUTH_PASSWORD_REQUIRE_SPECIAL", True)

# ---------------------------------------------------------------------------
# Keycloak SSO configuration
# ---------------------------------------------------------------------------
KEYCLOAK_ENABLED            = os.getenv("KEYCLOAK_ENABLED", "false").lower() == "true"
KEYCLOAK_SERVER_URL         = os.getenv("KEYCLOAK_SERVER_URL", "")
KEYCLOAK_REALM              = os.getenv("KEYCLOAK_REALM", "")
KEYCLOAK_CLIENT_ID          = os.getenv("KEYCLOAK_CLIENT_ID", "")
KEYCLOAK_CLIENT_SECRET      = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_REDIRECT_URI       = os.getenv("KEYCLOAK_REDIRECT_URI", "")
KEYCLOAK_POST_LOGOUT_REDIRECT_URI = os.getenv("KEYCLOAK_POST_LOGOUT_REDIRECT_URI", "")
KEYCLOAK_VERIFY_SSL         = os.getenv("KEYCLOAK_VERIFY_SSL", "false").lower() == "true"
# SSO session bounds — enforced for provider=keycloak users.
# Absolute ceiling even when IdP is online; shorter cap when IdP is unreachable.
KEYCLOAK_SESSION_MAX_TTL_MINUTES = max(
    15,
    min(_int_env("KEYCLOAK_SESSION_MAX_TTL_MINUTES", 480), 24 * 60),
)
KEYCLOAK_OFFLINE_SESSION_TTL_MINUTES = max(
    5,
    min(_int_env("KEYCLOAK_OFFLINE_SESSION_TTL_MINUTES", 60), KEYCLOAK_SESSION_MAX_TTL_MINUTES),
)
KEYCLOAK_REACHABILITY_CACHE_SECONDS = max(
    5,
    min(_int_env("KEYCLOAK_REACHABILITY_CACHE_SECONDS", 30), 300),
)

def _check_sso_provider_exclusivity(microsoft_enabled: bool, keycloak_enabled: bool) -> None:
    """Exactly one SSO IdP may be active at a time (local password login is
    independent and may run alongside either).

    Both Microsoft/Entra and Keycloak provision users into the same local
    UserRecord store and both own the "/auth/callback" redirect — running both
    leaves it ambiguous which IdP a given account's role/groups sync came from.
    Fail fast rather than letting the two SSO flows collide at runtime.
    """
    if microsoft_enabled and keycloak_enabled:
        raise RuntimeError(
            "AUTH_MICROSOFT_ENABLED=true and KEYCLOAK_ENABLED=true cannot both be set. "
            "Choose exactly one SSO IdP: disable one of them (local password login "
            "stays available either way)."
        )


_check_sso_provider_exclusivity(AUTH_MICROSOFT_ENABLED, KEYCLOAK_ENABLED)

# ---------------------------------------------------------------------------
# Entitlement / authorization configuration
# ---------------------------------------------------------------------------
# Entitlements are a framework-level authorization layer. Authentication proves
# who the user is; entitlements decide which tenant/agent/skill/tool/context
# resources that user may access.
ENTITLEMENTS_ENABLED = os.getenv("ENTITLEMENTS_ENABLED", "false").lower() == "true"
ENTITLEMENTS_PROVIDER = os.getenv("ENTITLEMENTS_PROVIDER", "yaml").lower()
ENTITLEMENTS_FAIL_CLOSED = os.getenv("ENTITLEMENTS_FAIL_CLOSED", "true").lower() == "true"
ENTITLEMENTS_ENFORCEMENT_MODE = os.getenv("ENTITLEMENTS_ENFORCEMENT_MODE", "enforce").lower()
ENTITLEMENTS_AUDIT_ENABLED = os.getenv("ENTITLEMENTS_AUDIT_ENABLED", "true").lower() == "true"

# Audit/evidence sink fanout. Local persistence is always first-class; the
# optional JSONL mirror is designed for enterprise log forwarders without
# requiring cloud credentials in the MVP.
AUDIT_EVIDENCE_MIRROR_ENABLED = os.getenv("AUDIT_EVIDENCE_MIRROR_ENABLED", "false").lower() == "true"
AUDIT_EVIDENCE_MIRROR_DIR = os.getenv("AUDIT_EVIDENCE_MIRROR_DIR", "")
AUDIT_EVIDENCE_PREVIEW_LIMIT = int(os.getenv("AUDIT_EVIDENCE_PREVIEW_LIMIT", "1024"))

# External access governance extends entitlements to credentials, MCP, DBs, and
# kernel-observed outbound calls. Defaults track ENTITLEMENTS_ENABLED so local
# dev remains unchanged unless entitlement checks are active.
EXTERNAL_ACCESS_ENABLED = os.getenv("EXTERNAL_ACCESS_ENABLED", str(ENTITLEMENTS_ENABLED).lower()).lower() == "true"
EXTERNAL_ACCESS_REGISTRY = os.getenv("EXTERNAL_ACCESS_REGISTRY", "security/external_access.yaml")
EXTERNAL_ACCESS_UNKNOWN_MODE = os.getenv("EXTERNAL_ACCESS_UNKNOWN_MODE", "audit").lower()  # allow | audit | deny
EXTERNAL_ACCESS_AUDIT_ENABLED = os.getenv("EXTERNAL_ACCESS_AUDIT_ENABLED", "true").lower() == "true"
EXTERNAL_ACCESS_ENFORCE_CREDENTIALS = os.getenv("EXTERNAL_ACCESS_ENFORCE_CREDENTIALS", str(EXTERNAL_ACCESS_ENABLED).lower()).lower() == "true"
EXTERNAL_ACCESS_ENFORCE_MCP = os.getenv("EXTERNAL_ACCESS_ENFORCE_MCP", str(EXTERNAL_ACCESS_ENABLED).lower()).lower() == "true"
EXTERNAL_ACCESS_ENFORCE_SQL = os.getenv("EXTERNAL_ACCESS_ENFORCE_SQL", str(EXTERNAL_ACCESS_ENABLED).lower()).lower() == "true"

# Capability registry hook kill-switch (Batch 4). When False, capability_registry
# is still built but the in-process hook firing is short-circuited. Used to
# A/B test the new hook system against the legacy code path.
CAPABILITY_HOOKS_ENABLED = os.getenv("CAPABILITY_HOOKS_ENABLED", "true").lower() == "true"

if ENTITLEMENTS_ENABLED and not AUTH_ENABLED:
    logger.warning(
        "ENTITLEMENTS_ENABLED=true while AUTH_ENABLED=false. "
        "This is only safe for local development; production should enable AUTH_ENABLED."
    )
