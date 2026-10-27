"""
auth/local.py — LocalAuthProvider

Phase 1 auth provider:
  - bcrypt PWD hashing (passlib)
  - PWD policy enforcement
  - Account locking after N failed attempts
  - UserStore abstraction (Redis or SQLite)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from auth.base import AuthProvider, UserRecord, UserStore
from auth.password_policy import get_policy

logger = logging.getLogger("iaf_server.auth.local")

try:
    import bcrypt as _bcrypt_lib
    _BCRYPT_AVAILABLE = True
except ImportError:
    _BCRYPT_AVAILABLE = False
    logger.warning("bcrypt not installed — password hashing disabled. Run: pip install bcrypt")


def _hash(password: str) -> str:
    """Hash a PWD with bcrypt (rounds=12)."""
    if not _BCRYPT_AVAILABLE:
        raise RuntimeError("bcrypt not installed")
    # bcrypt max is 72 bytes; truncate to avoid silent truncation surprises
    pwd_bytes = password.encode("utf-8")[:72]
    salt = _bcrypt_lib.gensalt(rounds=12)
    return _bcrypt_lib.hashpw(pwd_bytes, salt).decode("utf-8")


# _hash/_verify are deliberately slow (bcrypt, ~0.2 s). Async callers run them via
# asyncio.to_thread so a burst of logins does not stall every other request.
def _verify(plain: str, hashed: str) -> bool:
    """Verify a plain PWD against a bcrypt hash."""
    if not _BCRYPT_AVAILABLE:
        return False
    try:
        pwd_bytes = plain.encode("utf-8")[:72]
        return _bcrypt_lib.checkpw(pwd_bytes, hashed.encode("utf-8"))
    except Exception:
        return False


class LocalAuthProvider(AuthProvider):
    """
    Username + PWD auth backed by any UserStore.

    Config keys consumed (from shared/config.py):
      AUTH_MAX_FAILED_ATTEMPTS  — lockout threshold (default 5)
      AUTH_LOCKOUT_MINUTES      — initial lockout duration (default 15)
    """

    def __init__(self, store: UserStore):
        self._store = store
        try:
            from shared.config import AUTH_MAX_FAILED_ATTEMPTS, AUTH_LOCKOUT_MINUTES
            self._max_attempts = AUTH_MAX_FAILED_ATTEMPTS
            self._lockout_minutes = AUTH_LOCKOUT_MINUTES
        except ImportError:
            self._max_attempts = 5
            self._lockout_minutes = 15


    async def register(
        self,
        email: str,
        display_name: str,
        password: str,
        role: str = "user",
        must_change_password: bool = False,
    ) -> UserRecord:
        email = email.lower().strip()

        if await self._store.email_exists(email):
            raise ValueError("An account with this email already exists.")

        policy = get_policy()
        error = policy.validate(password)
        if error:
            raise ValueError(error)

        password_hash = await asyncio.to_thread(_hash, password)
        user = UserRecord.new(email=email, display_name=display_name, role=role)
        user.password_changed_at = datetime.now(timezone.utc).isoformat()
        # Part of the atomic create: a later failure must not be able to leave
        # behind an account whose administrator-issued password is permanent.
        user.must_change_password = must_change_password

        return await self._store.create(user, password_hash)


    async def login(self, email: str, password: str) -> UserRecord:
        email = email.lower().strip()
        user = await self._store.get_by_email(email)

        if user is None:
            # Consistent timing to prevent user enumeration
            await asyncio.to_thread(_hash, "dummy_timing_constant_!")
            raise ValueError("Invalid email or password.")

        # Account status checks
        if user.status == "disabled":
            raise PermissionError("Account is disabled. Contact your administrator.")

        # Check lockout
        if user.locked_until:
            until = datetime.fromisoformat(user.locked_until.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < until:
                remaining = int((until - datetime.now(timezone.utc)).total_seconds() // 60) + 1
                raise PermissionError(
                    f"Account is temporarily locked. Try again in {remaining} minute(s)."
                )
            else:
                # Lockout expired — reset counter
                user.locked_until = None
                user.failed_attempts = 0
                await self._store.update(user)

        pwd_hash = await self._store.get_password_hash(user.user_id)
        if not pwd_hash or not await asyncio.to_thread(_verify, password, pwd_hash):
            # Increment failed attempts
            user.failed_attempts += 1
            if user.failed_attempts >= self._max_attempts:
                # Exponential-ish lockout: doubles after each lockout cycle
                multiplier = max(1, user.failed_attempts // self._max_attempts)
                lockout_dur = self._lockout_minutes * multiplier
                user.locked_until = (
                    datetime.now(timezone.utc) + timedelta(minutes=lockout_dur)
                ).isoformat()
                logger.warning(
                    "Account locked: %s (attempts=%d, lockout=%dmin)",
                    email, user.failed_attempts, lockout_dur,
                )
            await self._store.update(user)
            raise ValueError("Invalid email or password.")

        # Success — reset counters
        user.failed_attempts = 0
        user.locked_until = None
        user.last_login = datetime.now(timezone.utc).isoformat()
        await self._store.update(user)

        return user


    async def change_password(
        self, user_id: str, old_password: str, new_password: str
    ) -> None:
        user = await self._store.get_by_id(user_id)
        if not user:
            raise ValueError("User not found.")

        pwd_hash = await self._store.get_password_hash(user_id)
        if not pwd_hash or not await asyncio.to_thread(_verify, old_password, pwd_hash):
            raise ValueError("Current password is incorrect.")

        # Reject reusing the current password so rotation actually rotates.
        if await asyncio.to_thread(_verify, new_password, pwd_hash):
            raise ValueError("New password must be different from the current password.")

        policy = get_policy()
        error = policy.validate(new_password)
        if error:
            raise ValueError(error)

        new_hash = await asyncio.to_thread(_hash, new_password)
        await self._store.set_password_hash(user_id, new_hash)

        user.password_changed_at = datetime.now(timezone.utc).isoformat()
        # The user has now chosen their own password, so any temporary-password
        # requirement is satisfied and the gate must release.
        user.must_change_password = False
        await self._store.update(user)

    async def reset_password(self, user_id: str, new_password: str) -> None:
        """Admin-initiated reset — no old PWD required.

        The replacement is a temporary password by definition: an administrator
        chose it, not the account owner, so it must be replaced at next sign-in.
        """
        user = await self._store.get_by_id(user_id)
        if not user:
            raise ValueError("User not found.")

        policy = get_policy()
        error = policy.validate(new_password)
        if error:
            raise ValueError(error)

        # A temporary password must differ from the current one.
        current_hash = await self._store.get_password_hash(user_id)
        if current_hash and _verify(new_password, current_hash):
            raise ValueError("New password must be different from the current password.")

        new_hash = await asyncio.to_thread(_hash, new_password)

        # Set the flag before the hash so a failure leaves the account untouched.
        user.password_changed_at = datetime.now(timezone.utc).isoformat()
        user.failed_attempts = 0
        user.locked_until = None
        user.must_change_password = True
        await self._store.update(user)

        await self._store.set_password_hash(user_id, new_hash)


    async def get_user(self, user_id: str) -> Optional[UserRecord]:
        return await self._store.get_by_id(user_id)
