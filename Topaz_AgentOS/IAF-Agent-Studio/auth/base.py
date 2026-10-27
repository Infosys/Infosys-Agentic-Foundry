"""
auth/base.py — Abstract interfaces for Auth system

Swap providers by changing AUTH_PROVIDER in config/env.
Phase 1: local   (bcrypt + JWT — this file's primary consumer)
Phase 2: microsoft | google  (OIDC redirect flow)
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional



def _parse_groups(raw) -> list:
    """Deserialize groups from JSON string or pass through a list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


@dataclass
class UserRecord:
    """Canonical user object — provider-agnostic."""
    user_id: str
    email: str
    display_name: str
    role: str = "user"                    # "user" | "admin"
    status: str = "active"                # "active" | "pending" | "locked" | "disabled"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login: Optional[str] = None
    failed_attempts: int = 0
    locked_until: Optional[str] = None
    password_changed_at: Optional[str] = None
    mfa_enabled: bool = False
    provider: str = "local"               # "local" | "microsoft" | "google" | "keycloak"
    groups: List[str] = field(default_factory=list)
    iaf_rbac_managed: bool = False        # True when admin set role/groups in IAF UI (SSO won't overwrite)
    must_change_password: bool = False    # True while the current password is a temporary one

    @classmethod
    def new(cls, email: str, display_name: str, role: str = "user") -> "UserRecord":
        return cls(
            user_id=str(uuid.uuid4()),
            email=email.lower().strip(),
            display_name=display_name,
            role=role,
        )

    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            if k == "groups":
                d[k] = json.dumps(v) if v else "[]"
            elif v is not None:
                d[k] = str(v)
            else:
                d[k] = ""
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "UserRecord":
        return cls(
            user_id=d.get("user_id", ""),
            email=d.get("email", ""),
            display_name=d.get("display_name", ""),
            role=d.get("role", "user"),
            status=d.get("status", "active"),
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
            last_login=d.get("last_login") or None,
            failed_attempts=int(d.get("failed_attempts", 0)),
            locked_until=d.get("locked_until") or None,
            password_changed_at=d.get("password_changed_at") or None,
            mfa_enabled=str(d.get("mfa_enabled", "false")).lower() == "true",
            provider=d.get("provider", "local"),
            groups=_parse_groups(d.get("groups", "[]")),
            iaf_rbac_managed=str(d.get("iaf_rbac_managed", "false")).lower() == "true",
            must_change_password=str(d.get("must_change_password", "false")).lower() == "true",
        )


def user_matches_filters(
    user: UserRecord,
    *,
    search: str = "",
    role: str = "",
    status: str = "",
) -> bool:
    """Return True when a user record satisfies optional admin list filters."""
    role_f = (role or "").strip()
    status_f = (status or "").strip()
    q = (search or "").strip().lower()
    if role_f and user.role != role_f:
        return False
    if status_f and user.status != status_f:
        return False
    if q:
        if (
            q not in (user.email or "").lower()
            and q not in (user.user_id or "").lower()
            and q not in (user.display_name or "").lower()
        ):
            return False
    return True


class UserStore(ABC):
    """Persistent storage for user accounts and PWD hashes."""

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[UserRecord]:
        ...

    @abstractmethod
    async def get_by_id(self, user_id: str) -> Optional[UserRecord]:
        ...

    @abstractmethod
    async def create(self, user: UserRecord, password_hash: str) -> UserRecord:
        ...

    @abstractmethod
    async def update(self, user: UserRecord) -> None:
        ...

    @abstractmethod
    async def get_password_hash(self, user_id: str) -> Optional[str]:
        ...

    @abstractmethod
    async def set_password_hash(self, user_id: str, password_hash: str) -> None:
        ...

    @abstractmethod
    async def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        search: str = "",
        role: str = "",
        status: str = "",
    ) -> list[UserRecord]:
        ...

    @abstractmethod
    async def delete(self, user_id: str) -> None:
        ...

    @abstractmethod
    async def count(
        self,
        *,
        search: str = "",
        role: str = "",
        status: str = "",
    ) -> int:
        ...

    @abstractmethod
    async def list_roles(self) -> list[str]:
        ...

    @abstractmethod
    async def email_exists(self, email: str) -> bool:
        ...



class AuthProvider(ABC):
    """Business-logic layer for authenticating users."""

    @abstractmethod
    async def register(
        self,
        email: str,
        display_name: str,
        password: str,
        role: str = "user",
        must_change_password: bool = False,
    ) -> UserRecord:
        """Create a new user. Raises ValueError on policy violation.

        ``must_change_password`` must be applied as part of the initial create,
        not a follow-up write, so a failure can never leave an account holding a
        permanent administrator-issued password.
        """
        ...

    @abstractmethod
    async def login(self, email: str, password: str) -> UserRecord:
        """Verify credentials. Raises ValueError/PermissionError on failure."""
        ...

    @abstractmethod
    async def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        """Change PWD after verifying old PWD."""
        ...

    @abstractmethod
    async def reset_password(self, user_id: str, new_password: str) -> None:
        """Admin-initiated PWD reset (no old PWD needed)."""
        ...

    @abstractmethod
    async def get_user(self, user_id: str) -> Optional[UserRecord]:
        ...
