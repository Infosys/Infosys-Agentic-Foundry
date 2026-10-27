"""
auth/users_sqlite.py — SQLite-backed UserStore (fallback when Redis is unavailable)

Schema:
  Table: auth_users   — one row per user
  Table: auth_passwords — separate table for PWD hashes
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from pathlib import Path
from typing import Optional

from auth.base import UserRecord, UserStore

logger = logging.getLogger("iaf_server.auth.users_sqlite")


class SQLiteUserStore(UserStore):
    """Stores user accounts in a local SQLite database."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._init_schema()


    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
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
                    mfa_enabled         INTEGER NOT NULL DEFAULT 0,
                    provider            TEXT NOT NULL DEFAULT 'local',
                    groups              TEXT NOT NULL DEFAULT '[]',
                    iaf_rbac_managed    INTEGER NOT NULL DEFAULT 0,
                    must_change_password INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS auth_passwords (
                    user_id             TEXT PRIMARY KEY,
                    password_hash       TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES auth_users(user_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(email);
            """)
            # Migrate existing databases that lack the new columns
            try:
                conn.execute("ALTER TABLE auth_users ADD COLUMN groups TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass  # column already exists
            try:
                conn.execute("ALTER TABLE auth_users ADD COLUMN iaf_rbac_managed INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already exists
            try:
                conn.execute("ALTER TABLE auth_users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already exists

    @contextmanager
    def _conn(self):
        conn = _sqlite_connect(self._db_path, row_factory=sqlite3.Row)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


    def _row_to_user(self, row) -> UserRecord:
        d = dict(row)
        d["mfa_enabled"] = bool(d.get("mfa_enabled", 0))
        d["failed_attempts"] = int(d.get("failed_attempts", 0))
        d["iaf_rbac_managed"] = bool(d.get("iaf_rbac_managed", 0))
        d["must_change_password"] = bool(d.get("must_change_password", 0))
        return UserRecord.from_dict(d)


    async def get_by_email(self, email: str) -> Optional[UserRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
        return self._row_to_user(row) if row else None

    async def get_by_id(self, user_id: str) -> Optional[UserRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    async def email_exists(self, email: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM auth_users WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
        return row is not None


    async def create(self, user: UserRecord, password_hash: str) -> UserRecord:
        import json
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO auth_users
                   (user_id, email, display_name, role, status, created_at,
                    last_login, failed_attempts, locked_until, password_changed_at,
                    mfa_enabled, provider, groups, iaf_rbac_managed,
                    must_change_password)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user.user_id, user.email, user.display_name, user.role,
                    user.status, user.created_at, user.last_login,
                    user.failed_attempts, user.locked_until,
                    user.password_changed_at,
                    1 if user.mfa_enabled else 0,
                    user.provider,
                    json.dumps(user.groups or []),
                    1 if user.iaf_rbac_managed else 0,
                    1 if user.must_change_password else 0,
                ),
            )
            conn.execute(
                "INSERT INTO auth_passwords (user_id, password_hash) VALUES (?, ?)",
                (user.user_id, password_hash),
            )
        logger.info("User created: %s (%s)", user.email, user.user_id)
        return user

    async def update(self, user: UserRecord) -> None:
        import json
        with self._conn() as conn:
            conn.execute(
                """UPDATE auth_users SET
                   display_name=?, role=?, status=?, last_login=?,
                   failed_attempts=?, locked_until=?, password_changed_at=?,
                   mfa_enabled=?, provider=?, groups=?, iaf_rbac_managed=?,
                   must_change_password=?
                   WHERE user_id=?""",
                (
                    user.display_name, user.role, user.status, user.last_login,
                    user.failed_attempts, user.locked_until, user.password_changed_at,
                    1 if user.mfa_enabled else 0, user.provider,
                    json.dumps(user.groups or []),
                    1 if user.iaf_rbac_managed else 0,
                    1 if user.must_change_password else 0,
                    user.user_id,
                ),
            )

    async def delete(self, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM auth_users WHERE user_id = ?", (user_id,))


    async def get_password_hash(self, user_id: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash FROM auth_passwords WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["password_hash"] if row else None

    async def set_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO auth_passwords (user_id, password_hash) VALUES (?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET password_hash=excluded.password_hash""",
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
            rows = conn.execute(
                f"SELECT * FROM auth_users{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
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
            row = conn.execute(
                f"SELECT COUNT(*) as n FROM auth_users{where}",
                params,
            ).fetchone()
        return row["n"] if row else 0

    async def list_roles(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT role FROM auth_users WHERE role IS NOT NULL AND role != '' ORDER BY role"
            ).fetchall()
        return [row["role"] for row in rows if row["role"]]

    def _user_filter_sql(self, search: str, role: str, status: str) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        role_f = (role or "").strip()
        status_f = (status or "").strip()
        q = (search or "").strip().lower()
        if role_f:
            clauses.append("role = ?")
            params.append(role_f)
        if status_f:
            clauses.append("status = ?")
            params.append(status_f)
        if q:
            clauses.append(
                "(LOWER(email) LIKE ? OR LOWER(user_id) LIKE ? OR LOWER(display_name) LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params
