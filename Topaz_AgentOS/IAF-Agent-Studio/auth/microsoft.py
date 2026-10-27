"""
auth/microsoft.py — Microsoft Entra ID (Azure AD) auth provider

Validates MSAL access tokens issued by Azure AD via OIDC/JWKS and provisions
users into the local user store on first login. Password-based operations are
not supported — the frontend handles all Azure AD interaction via MSAL.

Login flow:
  1. React frontend: MSAL login → acquires access token scoped to this API
  2. Frontend: POST /auth/sso/microsoft  (Authorization: Bearer <msal_token>)
  3. This provider: validate token via Azure AD JWKS (OidcJwksIdentityResolver)
  4. This provider: find or create the user in the local store
  5. Backend router: issue IAF JWT + refresh token, return to frontend
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from auth.base import AuthProvider, UserRecord, UserStore
from auth.identity import IdentityResolutionError, OidcJwksIdentityResolver

logger = logging.getLogger("iaf_server.auth.microsoft")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MicrosoftAuthProvider(AuthProvider):
    """
    Validates MSAL tokens via Azure AD JWKS and provisions users on first login.

    Token validation is delegated to OidcJwksIdentityResolver (the same JWKS
    mechanism already in identity.py).  No separate HTTP call is made here.

    Provisioning status values returned by login_with_msal_token():
      USER_EXISTS          — existing active user, proceed to app
      PENDING_APPROVAL     — new/pending user, show waiting screen
    """

    def __init__(self, store: UserStore, resolver: OidcJwksIdentityResolver) -> None:
        self._store = store
        self._resolver = resolver

    async def login_with_msal_token(
        self,
        access_token: str,
        *,
        registration_mode: str = "open",
        default_role: str = "user",
        default_groups: list[str] | None = None,
    ) -> tuple[UserRecord, str]:
        """
        Validate an MSAL access token and return (user_record, provisioning_status).

        Raises:
            ValueError    — token invalid / email missing
            PermissionError — account disabled or locked
        """
        try:
            identity = self._resolver.resolve(access_token)
        except IdentityResolutionError as exc:
            raise ValueError(f"MSAL token validation failed: {exc}") from exc

        email = identity.email
        if not email:
            raise ValueError(
                "MSAL token does not contain an email claim. "
                "Ensure the API scope grants access to the user's email."
            )

        existing = await self._store.get_by_email(email)

        if existing:
            if existing.status == "disabled":
                raise PermissionError(
                    "Access restricted: account is unregistered or deactivated."
                )
            if existing.status == "locked":
                raise PermissionError("Account is locked. Contact your administrator.")

            # Refresh last_login and sync display_name from Entra (unless RBAC-managed)
            existing.last_login = _utc_now()
            if not getattr(existing, "iaf_rbac_managed", False):
                entra_name = (
                    identity.attributes.get("name")
                    or identity.attributes.get("given_name")
                )
                if entra_name:
                    existing.display_name = entra_name
            await self._store.update(existing)

            status = (
                "PENDING_APPROVAL" if existing.status == "pending" else "USER_EXISTS"
            )
            return existing, status

        user_id = identity.user_id or str(uuid.uuid4())
        display_name = (
            identity.attributes.get("name")
            or identity.attributes.get("given_name")
            or email.split("@")[0]
        )
        new_status = "active" if registration_mode == "open" else "pending"

        new_user = UserRecord(
            user_id=user_id,
            email=email,
            display_name=display_name,
            role=default_role,
            status=new_status,
            created_at=_utc_now(),
            last_login=_utc_now(),
            provider="microsoft",
            groups=list(identity.groups) or (default_groups or []),
            iaf_rbac_managed=False,
            mfa_enabled=False,
            must_change_password=False,
        )
        await self._store.create(new_user, password_hash="")
        logger.info(
            "Microsoft SSO: provisioned new user %s (status=%s)", email, new_status
        )

        prov_status = "PENDING_APPROVAL" if new_status == "pending" else "USER_EXISTS"
        return new_user, prov_status


    async def register(
        self, *, email: str, display_name: str, password: str
    ) -> UserRecord:
        raise NotImplementedError(
            "Direct registration is not supported when AUTH_PROVIDER=microsoft. "
            "Users are provisioned automatically on first MSAL login."
        )

    async def login(self, *, email: str, password: str) -> UserRecord:
        raise NotImplementedError(
            "Password login is not supported when AUTH_PROVIDER=microsoft. "
            "Use the MSAL SSO flow (POST /auth/sso/microsoft)."
        )

    async def change_password(
        self, *, user_id: str, old_password: str, new_password: str
    ) -> None:
        raise NotImplementedError(
            "Password change is not supported for Microsoft SSO accounts."
        )

    async def reset_password(self, *, user_id: str, new_password: str) -> None:
        raise NotImplementedError(
            "Password reset is not supported for Microsoft SSO accounts."
        )

    async def get_user(self, user_id: str) -> Optional[UserRecord]:
        return await self._store.get_by_id(user_id)
