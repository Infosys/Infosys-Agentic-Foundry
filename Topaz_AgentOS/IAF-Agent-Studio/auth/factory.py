"""
auth/factory.py — Build the active AuthProvider from config

Called once at startup. Returns a (provider, store) pair.

AUTH_PROVIDER = local       → LocalAuthProvider + Redis/SQLite store
AUTH_PROVIDER = microsoft   → (Phase 2) MicrosoftProvider
AUTH_PROVIDER = google      → (Phase 2) GoogleProvider

Microsoft/Entra SSO is also available as an independent bolt-on via
get_microsoft_provider(), gated by AUTH_MICROSOFT_ENABLED rather than
AUTH_PROVIDER — this lets AUTH_PROVIDER=local (password login) and Microsoft
SSO (POST /auth/sso/microsoft) run side by side, sharing the same UserStore.
"""

from __future__ import annotations

import logging
from typing import Optional

from auth.base import AuthProvider, UserStore

logger = logging.getLogger("iaf_server.auth.factory")

_provider: Optional[AuthProvider] = None
_store:    Optional[UserStore]    = None
_microsoft_provider: Optional[AuthProvider] = None


async def get_provider() -> AuthProvider:
    global _provider
    if _provider is None:
        await _init()
    return _provider


async def get_store() -> UserStore:
    global _store
    if _store is None:
        await _init()
    return _store


async def get_microsoft_provider() -> Optional[AuthProvider]:
    """Microsoft/Entra SSO provider, independent of the primary AUTH_PROVIDER.

    Returns None when AUTH_MICROSOFT_ENABLED is false. Bound to the same
    UserStore as get_provider()/get_store(), so local password accounts and
    Microsoft SSO accounts are provisioned into one shared store — mirrors how
    Keycloak SSO in routers/oauth.py runs independently of AUTH_PROVIDER.
    """
    global _microsoft_provider

    try:
        from shared.config import AUTH_MICROSOFT_ENABLED
    except ImportError:
        AUTH_MICROSOFT_ENABLED = False

    if not AUTH_MICROSOFT_ENABLED:
        return None

    if _microsoft_provider is None:
        store = await get_store()
        from auth.microsoft import MicrosoftAuthProvider
        from auth.identity import OidcJwksIdentityResolver
        resolver = OidcJwksIdentityResolver.from_config(provider_name="microsoft")
        _microsoft_provider = MicrosoftAuthProvider(store, resolver)
        logger.info("Auth: MicrosoftAuthProvider initialised as SSO bolt-on (OIDC/JWKS via Entra ID)")
    return _microsoft_provider


async def _init() -> None:
    global _provider, _store

    try:
        from shared.config import AUTH_PROVIDER, AUTH_BACKEND, SERVER_DIR, DATA_ROOT, TENANT_ID, AGENT_ID
    except ImportError:
        AUTH_PROVIDER = "local"
        AUTH_BACKEND  = "sqlite"
        from pathlib import Path
        SERVER_DIR = Path(".")
        DATA_ROOT  = "../enterprise_root"
        TENANT_ID  = "company"
        AGENT_ID   = "enterprise_agent"

    if AUTH_PROVIDER == "local":
        _store = await _build_store(AUTH_BACKEND, SERVER_DIR, DATA_ROOT, TENANT_ID, AGENT_ID)
        from auth.local import LocalAuthProvider
        _provider = LocalAuthProvider(_store)
        logger.info("Auth: LocalAuthProvider initialised (backend=%s)", AUTH_BACKEND)

    elif AUTH_PROVIDER in {"microsoft", "entra", "azuread", "azure_ad"}:
        _store = await _build_store(AUTH_BACKEND, SERVER_DIR, DATA_ROOT, TENANT_ID, AGENT_ID)
        from auth.microsoft import MicrosoftAuthProvider
        from auth.identity import OidcJwksIdentityResolver
        resolver = OidcJwksIdentityResolver.from_config(provider_name="microsoft")
        _provider = MicrosoftAuthProvider(_store, resolver)
        logger.info("Auth: MicrosoftAuthProvider initialised (OIDC/JWKS via Entra ID)")

    else:
        raise NotImplementedError(
            f"AUTH_PROVIDER='{AUTH_PROVIDER}' is not supported. "
            "Supported values: local, microsoft (entra, azuread)."
        )


async def _build_store(backend: str, server_dir, data_root, tenant_id, agent_id) -> UserStore:
    from pathlib import Path

    if backend == "postgres":
        try:
            from shared.config import DATABASE_URL
            from auth.users_postgres import PostgresUserStore
            store = PostgresUserStore(DATABASE_URL or None)
            logger.info("Auth store: Postgres (DATABASE_URL)")
            return store
        except Exception as exc:
            if _store_strict():
                logger.error("Postgres auth store unavailable and AUTH_STORE_STRICT is set: %s", exc)
                raise
            logger.warning("Postgres store unavailable (%s), falling back to SQLite", exc)

    if backend == "redis":
        try:
            import redis.asyncio as aioredis
            from shared.config import REDIS_URL
            r = aioredis.from_url(REDIS_URL, decode_responses=False)
            await r.ping()
            from auth.users_redis import RedisUserStore
            store = RedisUserStore(r)
            logger.info("Auth store: Redis (configured endpoint)")
            return store
        except Exception as exc:
            if _store_strict():
                logger.error("Redis auth store unavailable and AUTH_STORE_STRICT is set: %s", exc)
                raise
            logger.warning("Redis store unavailable (%s), falling back to SQLite", exc)

    # SQLite fallback — auth_users.db lives under tenant config/, not inside the agent folder
    base = Path(server_dir) / data_root / "tenants" / tenant_id / "config"
    base.mkdir(parents=True, exist_ok=True)
    db_path = base / "auth_users.db"
    from auth.users_sqlite import SQLiteUserStore
    store = SQLiteUserStore(db_path)
    logger.info("Auth store: SQLite (%s)", db_path)
    return store


def reset():
    """Force re-init on next access (used in tests)."""
    global _provider, _store, _microsoft_provider
    _provider = None
    _store = None
    _microsoft_provider = None


def _store_strict() -> bool:
    """Whether a shared auth-store failure must fail closed instead of falling
    back to per-instance SQLite (see shared.config.AUTH_STORE_STRICT)."""
    try:
        from shared.config import AUTH_STORE_STRICT
        return bool(AUTH_STORE_STRICT)
    except Exception:
        return False
