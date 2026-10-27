"""
auth/users_postgres.py — PostgreSQL-backed UserStore

Schema (mirrors the SQLite store so records round-trip identically):
  Table: auth_users     — one row per user
  Table: auth_passwords — separate table for PWD hashes

Selected when AUTH_BACKEND=postgres. Uses the shared PostgresEngine
(psycopg3) so it participates in the same connection-pooling behaviour as
the rest of the runtime. Timestamps are stored as ISO strings to keep
UserRecord serialization identical across backends.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Optional

from auth.base import UserRecord, UserStore

logger = logging.getLogger("iaf_server.auth.users_postgres")


class PostgresUserStore(UserStore):
    """Stores user accounts in PostgreSQL."""

    def __init__(self, dsn: str | None = None):
        from iaf_agent_skills.storage.engine import PostgresEngine
        self._engine = PostgresEngine(dsn=dsn or None)
        self._init_schema()


    def _init_schema(self):
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id             TEXT PRIMARY KEY,
                    email               TEXT UNIQUE NOT NULL,
                    display_name        TEXT NOT NULL,
                    role                TEXT NOT NULL DEFAULT 'user',
                    status              TEXT NOT NULL DEFAULT 'active',
                    created_at          TEXT NOT NULL,
                    last_login          TEXT,
                    failed_attempts     INTEGER NOT NULL DEFAULT 0,
                    locked_until        TEXT,
                    password_changed_at TEXT,
                    mfa_enabled         BOOLEAN NOT NULL DEFAULT FALSE,
                    provider            TEXT NOT NULL DEFAULT 'local',
                    groups              TEXT NOT NULL DEFAULT '[]',
                    iaf_rbac_managed    BOOLEAN NOT NULL DEFAULT FALSE,
                    must_change_password BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_passwords (
                    user_id       TEXT PRIMARY KEY REFERENCES auth_users(user_id) ON DELETE CASCADE,
                    password_hash TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(email)"
            )
            # Migrate pre-existing tables that lack the newer columns.
            cur.execute(
                "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS groups TEXT NOT NULL DEFAULT '[]'"
            )
            cur.execute(
                "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS iaf_rbac_managed BOOLEAN NOT NULL DEFAULT FALSE"
            )
            cur.execute(
                "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE"
            )

    @contextmanager
    def _conn(self):
        with self._engine.connect() as conn:
            yield conn

    def _cursor(self, conn):
        from psycopg.rows import dict_row
        return conn.cursor(row_factory=dict_row)


    def _row_to_user(self, row) -> UserRecord:
        d = dict(row)
        d["mfa_enabled"] = bool(d.get("mfa_enabled", False))
        d["failed_attempts"] = int(d.get("failed_attempts", 0))
        d["iaf_rbac_managed"] = bool(d.get("iaf_rbac_managed", False))
        d["must_change_password"] = bool(d.get("must_change_password", False))
        return UserRecord.from_dict(d)


    async def get_by_email(self, email: str) -> Optional[UserRecord]:
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute("SELECT * FROM auth_users WHERE email = %s", (email.lower().strip(),))
            row = cur.fetchone()
        return self._row_to_user(row) if row else None

    async def get_by_id(self, user_id: str) -> Optional[UserRecord]:
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute("SELECT * FROM auth_users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        return self._row_to_user(row) if row else None

    async def email_exists(self, email: str) -> bool:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM auth_users WHERE email = %s", (email.lower().strip(),))
            row = cur.fetchone()
        return row is not None


    async def create(self, user: UserRecord, password_hash: str) -> UserRecord:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO auth_users
                   (user_id, email, display_name, role, status, created_at,
                    last_login, failed_attempts, locked_until, password_changed_at,
                    mfa_enabled, provider, groups, iaf_rbac_managed, must_change_password)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    user.user_id, user.email, user.display_name, user.role,
                    user.status, user.created_at, user.last_login,
                    user.failed_attempts, user.locked_until,
                    user.password_changed_at,
                    bool(user.mfa_enabled),
                    user.provider,
                    json.dumps(user.groups or []),
                    bool(user.iaf_rbac_managed),
                    bool(getattr(user, "must_change_password", False)),
                ),
            )
            cur.execute(
                "INSERT INTO auth_passwords (user_id, password_hash) VALUES (%s, %s)",
                (user.user_id, password_hash),
            )
        logger.info("User created: %s (%s)", user.email, user.user_id)
        return user

    async def update(self, user: UserRecord) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE auth_users SET
                   display_name=%s, role=%s, status=%s, last_login=%s,
                   failed_attempts=%s, locked_until=%s, password_changed_at=%s,
                   mfa_enabled=%s, provider=%s, groups=%s, iaf_rbac_managed=%s,
                   must_change_password=%s
                   WHERE user_id=%s""",
                (
                    user.display_name, user.role, user.status, user.last_login,
                    user.failed_attempts, user.locked_until, user.password_changed_at,
                    bool(user.mfa_enabled), user.provider,
                    json.dumps(user.groups or []),
                    bool(user.iaf_rbac_managed),
                    bool(getattr(user, "must_change_password", False)),
                    user.user_id,
                ),
            )

    async def delete(self, user_id: str) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth_users WHERE user_id = %s", (user_id,))


    async def get_password_hash(self, user_id: str) -> Optional[str]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT password_hash FROM auth_passwords WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        return row[0] if row else None

    async def set_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO auth_passwords (user_id, password_hash) VALUES (%s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET password_hash = EXCLUDED.password_hash""",
                (user_id, password_hash),
            )


    async def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        search: str = "",
        role: str = "",
        status: str = "",
    ) -> list[UserRecord]:
        where, params = self._user_filter_sql(search, role, status)
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT * FROM auth_users{where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = cur.fetchall()
        return [self._row_to_user(r) for r in rows]

    async def count(
        self,
        *,
        search: str = "",
        role: str = "",
        status: str = "",
    ) -> int:
        where, params = self._user_filter_sql(search, role, status)
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM auth_users{where}", params)
            row = cur.fetchone()
        return int(row[0]) if row else 0

    async def list_roles(self) -> list[str]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT role FROM auth_users WHERE role IS NOT NULL AND role != '' ORDER BY role"
            )
            rows = cur.fetchall()
        return [row[0] for row in rows if row and row[0]]

    def _user_filter_sql(self, search: str, role: str, status: str) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        role_f = (role or "").strip()
        status_f = (status or "").strip()
        q = (search or "").strip().lower()
        if role_f:
            clauses.append("role = %s")
            params.append(role_f)
        if status_f:
            clauses.append("status = %s")
            params.append(status_f)
        if q:
            clauses.append(
                "(LOWER(email) LIKE %s OR LOWER(user_id) LIKE %s OR LOWER(display_name) LIKE %s)"
            )
            like = f"%{q}%"
            params.extend([like, like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params
