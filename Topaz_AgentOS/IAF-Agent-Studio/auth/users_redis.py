"""
auth/users_redis.py — Redis-backed UserStore

Layout in Redis:
  auth:user:email:<email>        → user_id  (string)
  auth:user:<user_id>            → UserRecord fields (hash)
  auth:user:<user_id>:pwd        → bcrypt hash (string)

User lookup by email is O(1) via the email→id index key.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from auth.base import UserRecord, UserStore, user_matches_filters

logger = logging.getLogger("iaf_server.auth.users_redis")

_EMAIL_IDX = "auth:user:email:"
_USER_KEY  = "auth:user:"
_PWD_SUFFIX = ":pwd"


class RedisUserStore(UserStore):
    """Stores user accounts in Redis hashes."""

    def __init__(self, redis):
        self._r = redis


    async def get_by_email(self, email: str) -> Optional[UserRecord]:
        email = email.lower().strip()
        user_id = await self._r.get(f"{_EMAIL_IDX}{email}")
        if not user_id:
            return None
        if isinstance(user_id, bytes):
            user_id = user_id.decode()
        return await self.get_by_id(user_id)

    async def get_by_id(self, user_id: str) -> Optional[UserRecord]:
        raw = await self._r.hgetall(f"{_USER_KEY}{user_id}")
        if not raw:
            return None
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        return UserRecord.from_dict(decoded)

    async def email_exists(self, email: str) -> bool:
        return bool(await self._r.exists(f"{_EMAIL_IDX}{email.lower().strip()}"))


    async def create(self, user: UserRecord, password_hash: str) -> UserRecord:
        pipe = self._r.pipeline()
        pipe.set(f"{_EMAIL_IDX}{user.email}", user.user_id)
        pipe.hset(f"{_USER_KEY}{user.user_id}", mapping=user.to_dict())
        pipe.set(f"{_USER_KEY}{user.user_id}{_PWD_SUFFIX}", password_hash)
        await pipe.execute()
        logger.info("User created: %s (%s)", user.email, user.user_id)
        return user

    async def update(self, user: UserRecord) -> None:
        await self._r.hset(f"{_USER_KEY}{user.user_id}", mapping=user.to_dict())

    async def delete(self, user_id: str) -> None:
        user = await self.get_by_id(user_id)
        if user:
            pipe = self._r.pipeline()
            pipe.delete(f"{_EMAIL_IDX}{user.email}")
            pipe.delete(f"{_USER_KEY}{user_id}")
            pipe.delete(f"{_USER_KEY}{user_id}{_PWD_SUFFIX}")
            await pipe.execute()


    async def get_password_hash(self, user_id: str) -> Optional[str]:
        val = await self._r.get(f"{_USER_KEY}{user_id}{_PWD_SUFFIX}")
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else val

    async def set_password_hash(self, user_id: str, password_hash: str) -> None:
        await self._r.set(f"{_USER_KEY}{user_id}{_PWD_SUFFIX}", password_hash)


    async def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        search: str = "",
        role: str = "",
        status: str = "",
    ) -> list[UserRecord]:
        matched: list[UserRecord] = []
        cursor = 0
        pattern = f"{_USER_KEY}*"
        while True:
            cursor, batch = await self._r.scan(cursor, match=pattern, count=200)
            for k in batch:
                k_str = k.decode() if isinstance(k, bytes) else k
                if k_str.startswith(_EMAIL_IDX) or k_str.endswith(_PWD_SUFFIX):
                    continue
                raw = await self._r.hgetall(k_str)
                if not raw:
                    continue
                decoded = {
                    (k2.decode() if isinstance(k2, bytes) else k2): (v2.decode() if isinstance(v2, bytes) else v2)
                    for k2, v2 in raw.items()
                }
                if not decoded.get("user_id"):
                    continue
                user = UserRecord.from_dict(decoded)
                if user_matches_filters(user, search=search, role=role, status=status):
                    matched.append(user)
            if cursor == 0:
                break
        matched.sort(key=lambda u: u.created_at or "", reverse=True)
        return matched[offset: offset + limit]

    async def count(
        self,
        *,
        search: str = "",
        role: str = "",
        status: str = "",
    ) -> int:
        total = 0
        cursor = 0
        while True:
            cursor, batch = await self._r.scan(cursor, match=f"{_USER_KEY}*", count=200)
            for k in batch:
                k_str = k.decode() if isinstance(k, bytes) else k
                if k_str.startswith(_EMAIL_IDX) or k_str.endswith(_PWD_SUFFIX):
                    continue
                raw = await self._r.hgetall(k_str)
                if not raw:
                    continue
                decoded = {
                    (k2.decode() if isinstance(k2, bytes) else k2): (v2.decode() if isinstance(v2, bytes) else v2)
                    for k2, v2 in raw.items()
                }
                if not decoded.get("user_id"):
                    continue
                user = UserRecord.from_dict(decoded)
                if user_matches_filters(user, search=search, role=role, status=status):
                    total += 1
            if cursor == 0:
                break
        return total

    async def list_roles(self) -> list[str]:
        roles: set[str] = set()
        cursor = 0
        while True:
            cursor, batch = await self._r.scan(cursor, match=f"{_USER_KEY}*", count=200)
            for k in batch:
                k_str = k.decode() if isinstance(k, bytes) else k
                if k_str.startswith(_EMAIL_IDX) or k_str.endswith(_PWD_SUFFIX):
                    continue
                raw = await self._r.hgetall(k_str)
                if not raw:
                    continue
                decoded = {
                    (k2.decode() if isinstance(k2, bytes) else k2): (v2.decode() if isinstance(v2, bytes) else v2)
                    for k2, v2 in raw.items()
                }
                role = decoded.get("role")
                if role:
                    roles.add(str(role))
            if cursor == 0:
                break
        return sorted(roles)
