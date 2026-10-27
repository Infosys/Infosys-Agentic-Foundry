"""
auth/audit.py — Auth event audit log

Writes to:
  1. Redis stream  auth:audit:events  (primary, with MAXLEN cap)
  2. SQLite config/auth_audit.db      (durable fallback)
  3. Python logger                    (always)

Event types:
  REGISTER, LOGIN, LOGIN_FAILED, LOGOUT,
  TOKEN_REFRESH, PASSWORD_CHANGED, PASSWORD_RESET,
  ACCOUNT_LOCKED, ACCOUNT_UNLOCKED, ADMIN_ACTION, SESSION_REVOKED
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("iaf_server.auth.audit")

_REDIS_STREAM = "auth:audit:events"
_REDIS_MAXLEN = 10_000   # Trim stream to last 10k events



def _get_audit_db_path() -> str:
    try:
        from shared.config import SERVER_DIR, DATA_ROOT, TENANT_ID
        p = (
            SERVER_DIR / DATA_ROOT
            / "tenants" / TENANT_ID
            / "config"
            / "auth_audit.db"
        )
        if not p.is_absolute():
            p = (SERVER_DIR / p).resolve()
        return str(p)
    except Exception:
        return "auth_audit.db"


@contextmanager
def _sqlite_conn():
    db_path = _get_audit_db_path()
    conn = _sqlite_connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                user_id     TEXT,
                email       TEXT,
                ip          TEXT,
                details     TEXT,
                success     INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_audit_ts ON auth_audit_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_audit_user ON auth_audit_log(user_id)")
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()



async def log_event(
    event_type: str,
    *,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    ip: Optional[str] = None,
    details: Optional[dict] = None,
    success: bool = True,
) -> bool:
    """
    Record an auth audit event.

    event_type: one of the constants at the top of this module.

    Returns True iff the event was durably persisted (SQLite insert succeeded).
    Redis writes are best-effort — the stream is capped and treated as a fast
    tail, not the authoritative sink — so a Redis-only success returns False.
    Existing callers that ignore the return value keep their behaviour; callers
    that require durable evidence (e.g. the privacy-acknowledgement gate) can
    now detect a silent sink failure instead of caching a phantom acceptance.
    """
    ts = datetime.now(timezone.utc).isoformat()
    details_str = json.dumps(details) if details else ""

    # 1. Logger
    log_fn = logger.info if success else logger.warning
    log_fn(
        "AUTH_AUDIT | %s | user=%s | ip=%s | ok=%s | %s",
        event_type, user_id or email or "?", ip or "-", success, details_str,
    )

    # 2. Redis stream (best-effort tail)
    try:
        from shared.state import redis_client
        if redis_client:
            event_data = {
                "ts": ts,
                "event_type": event_type,
                "user_id": user_id or "",
                "email": email or "",
                "ip": ip or "",
                "details": details_str,
                "success": "1" if success else "0",
            }
            await redis_client.xadd(
                _REDIS_STREAM,
                event_data,
                maxlen=_REDIS_MAXLEN,
                approximate=True,
            )
    except Exception as exc:
        logger.debug("Auth audit Redis write failed: %s", exc)

    # 3. SQLite (sync — runs fast, no async needed). This is the durable sink;
    #    the returned bool reflects whether this insert committed.
    sqlite_ok = False
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                """INSERT INTO auth_audit_log
                   (ts, event_type, user_id, email, ip, details, success)
                   VALUES (?,?,?,?,?,?,?)""",
                (ts, event_type, user_id, email, ip, details_str, 1 if success else 0),
            )
        sqlite_ok = True
    except Exception as exc:
        logger.warning("Auth audit SQLite write failed: %s", exc)
    return sqlite_ok



def get_latest_event(event_type: str, *, user_id: str) -> Optional[dict]:
    """Return the most recent successful audit row for (event_type, user_id).

    Read-only convenience over the same durable SQLite sink that log_event writes.
    Keeps all audit-store access inside this module (no parallel store). Returns a
    dict with ts/details (details parsed from JSON) or None. Never raises.
    """
    if not user_id:
        return None
    try:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                """SELECT ts, event_type, user_id, email, ip, details, success
                     FROM auth_audit_log
                    WHERE event_type = ? AND user_id = ? AND success = 1
                    ORDER BY ts DESC
                    LIMIT 1""",
                (event_type, user_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.debug("Auth audit SQLite read failed: %s", exc)
        return None
    if not row:
        return None
    try:
        details = json.loads(row[5]) if row[5] else {}
    except Exception:
        details = {}
    return {
        "ts": row[0],
        "event_type": row[1],
        "user_id": row[2],
        "email": row[3],
        "ip": row[4],
        "details": details,
        "success": bool(row[6]),
    }



REGISTER         = "REGISTER"
LOGIN            = "LOGIN"
LOGIN_FAILED     = "LOGIN_FAILED"
LOGOUT           = "LOGOUT"
TOKEN_REFRESH    = "TOKEN_REFRESH"
PASSWORD_CHANGED = "PASSWORD_CHANGED"
PASSWORD_RESET   = "PASSWORD_RESET"
ACCOUNT_LOCKED   = "ACCOUNT_LOCKED"
ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
ADMIN_ACTION     = "ADMIN_ACTION"
# Session management: one or more interactive sessions revoked (by the user from
# another device, "sign out of all devices", or an administrator).
SESSION_REVOKED  = "SESSION_REVOKED"
# Data Privacy — PIA transparency/declaration acknowledgement evidence.
PRIVACY_ACK_ACCEPTED = "PRIVACY_ACK_ACCEPTED"
