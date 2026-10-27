#!/usr/bin/env python3
"""
auth/seed_admin.py — Create the first admin user

Run once before starting the server (or any time to add/reset admin credentials):
    IAF_ADMIN_PASSWORD='<strong-value>' python3 auth/seed_admin.py

Reads AUTH_BACKEND from config to use the same store as the server.

The admin credential is taken ONLY from the IAF_ADMIN_PASSWORD (or legacy
ADMIN_PASSWORD) environment variable — it is never hard-coded in source and
never printed or logged, so no secret_data value leaves this process.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import AUTH_BACKEND, AUTH_STORE_STRICT, SERVER_DIR, DATA_ROOT, TENANT_ID, AGENT_ID

ADMIN_EMAIL = "admin@iaf.local"
ADMIN_NAME  = "IAF Admin"

logger = logging.getLogger(__name__)


def _resolve_admin_password() -> "str | None":
    """Return the admin credential from env vars, or None if unset.

    Looks up IAF_ADMIN_PWD env (falls back to ADMIN_PWD legacy name).
    The value is never hard-coded and never emitted to logs/stdout.
    """  # noqa: S105
    return os.getenv("IAF_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")


async def main(quiet: bool = False):
    """Ensure the admin user exists.

    Requires IAF_ADMIN_PWD env (or ADMIN_PWD). If neither is set the
    bootstrap is skipped with a warning (no credential is generated or printed).
    If quiet=True, skip reset and only create the admin if missing.
    """
    admin_password = _resolve_admin_password()
    if not admin_password:
        logger.warning(
            "Admin bootstrap skipped: set IAF_ADMIN_PASSWORD (or ADMIN_PASSWORD) "
            "to create/reset the %s account.", ADMIN_EMAIL,
        )
        return

    # Build the store directly (same logic as factory.py)
    # auth_users.db lives under tenant config/, not inside the agent folder
    base = Path(SERVER_DIR) / DATA_ROOT / "tenants" / TENANT_ID / "config"
    base.mkdir(parents=True, exist_ok=True)

    if AUTH_BACKEND == "postgres":
        try:
            from shared.config import DATABASE_URL
            from auth.users_postgres import PostgresUserStore
            store = PostgresUserStore(DATABASE_URL or None)
            if not quiet:
                logger.info("Using configured Postgres store")
        except Exception as e:
            if AUTH_STORE_STRICT:
                logger.error("Postgres store unavailable and AUTH_STORE_STRICT is set; not seeding SQLite: %s", e)
                raise
            if not quiet:
                logger.info("Postgres unavailable (%s), falling back to SQLite", e)
            from auth.users_sqlite import SQLiteUserStore
            store = SQLiteUserStore(base / "auth_users.db")
    elif AUTH_BACKEND == "redis":
        try:
            import redis.asyncio as aioredis
            from shared.config import REDIS_URL
            r = aioredis.from_url(REDIS_URL, decode_responses=False)
            await r.ping()
            from auth.users_redis import RedisUserStore
            store = RedisUserStore(r)
            if not quiet:
                logger.info("Using configured Redis store")
        except Exception as e:
            if AUTH_STORE_STRICT:
                logger.error("Redis store unavailable and AUTH_STORE_STRICT is set; not seeding SQLite: %s", e)
                raise
            if not quiet:
                logger.info("Redis unavailable (%s), falling back to SQLite", e)
            from auth.users_sqlite import SQLiteUserStore
            store = SQLiteUserStore(base / "auth_users.db")
    else:
        from auth.users_sqlite import SQLiteUserStore
        store = SQLiteUserStore(base / "auth_users.db")
        if not quiet:
            logger.info("Using SQLite store (%s)", base / "auth_users.db")

    from auth.local import LocalAuthProvider

    provider = LocalAuthProvider(store)

    # Check if admin already exists
    existing = await store.get_by_email(ADMIN_EMAIL)
    if existing:
        if quiet:
            return  # Already exists, nothing to do on auto-startup
        await provider.reset_password(existing.user_id, admin_password)
        existing.role = "admin"
        existing.status = "active"
        existing.failed_attempts = 0
        existing.locked_until = None
        await store.update(existing)
        action = "reset"
    else:
        user = await provider.register(
            ADMIN_EMAIL, ADMIN_NAME, admin_password, role="admin",
            must_change_password=True,
        )
        # Force role=admin (register defaults to 'user')
        user.role = "admin"
        await store.update(user)
        action = "created"

    # Confirmation only — the credential value is never logged.
    if not quiet:
        logger.info(
            "Admin %s: %s (role=admin). Log in at http://localhost:8080/login "
            "and change the credential after first login.",
            action, ADMIN_EMAIL,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
