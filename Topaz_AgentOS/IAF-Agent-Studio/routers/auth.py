"""
routers/auth.py - All /auth/* and /login endpoints

Endpoints:
  POST /auth/register          Register a new account (behaviour depends on AUTH_REGISTRATION_MODE)
  POST /auth/login             Authenticate, get access + refresh tokens
  POST /auth/logout            Blacklist current access token
  POST /auth/refresh           Exchange refresh cookie for new access token
  GET  /auth/me                Current user profile
  PUT  /auth/me/PWD       Change own PWD
  GET  /auth/policy            PWD policy rules (for frontend validation)
  GET  /auth/session-policy    SEC-7 idle-timeout minutes (for client-side idle timer)
  GET  /auth/registration-mode Public endpoint: returns current registration mode
  GET  /auth/sessions          The caller's active sessions (current flagged)
  DELETE /auth/sessions/{id}   Sign out one of the caller's other sessions
  POST /auth/logout-all        Sign out of all devices (?keep_current=true keeps this one)

Admin (role=admin only):
  POST /auth/users             Admin creates a user directly
  GET  /auth/users             List all users
  PUT  /auth/users/{id}/status Update user status (active/disabled/locked)
  PUT  /auth/users/{id}/role   Promote or demote user (user | admin) - persists across SSO logins
  PUT  /auth/users/{id}/groups Assign entitlement groups - persists across SSO logins
  GET  /auth/rbac/groups       Known groups from tenant policies (for admin UI)
  POST /auth/users/{id}/reset-PWD  Admin PWD reset
  DELETE /auth/users/{id}      Delete a user
  GET  /auth/users/{id}/sessions         A user's active sessions
  POST /auth/users/{id}/revoke-sessions  Sign a user out everywhere
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, validator

from auth import audit, session_registry
from auth.middleware import require_admin, require_auth
from auth.rate_limiter import is_ip_allowed, is_login_allowed
from security.roles import (
    catalog as permission_catalog,
    delete_role,
    effective_permissions,
    known_roles,
    load_role_registry,
    upsert_role,
)
from auth.tokens import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    is_blacklisted,
)

logger = logging.getLogger("iaf_server.routers.auth")

router = APIRouter(tags=["auth"])


def _tenant_of(request: Request) -> str:
    return getattr(getattr(request, "state", None), "tenant_id", None) or "company"


def _refresh_cookie_name() -> str:
    try:
        from shared.config import AUTH_REFRESH_COOKIE_NAME
        return AUTH_REFRESH_COOKIE_NAME
    except ImportError:
        return "iaf_refresh"


def _refresh_ttl_days() -> int:
    try:
        from shared.config import JWT_REFRESH_TTL_DAYS
        return JWT_REFRESH_TTL_DAYS
    except ImportError:
        return 7


def _refresh_cookie_path() -> str:
    """Refresh-cookie Path, made ROOT_PATH-aware so the browser delivers it under
    a sub-path gateway (e.g. ROOT_PATH=/agentos -> /agentos/auth/refresh).
    No-op ("/auth/refresh") for root deployments."""
    try:
        from shared.config import ROOT_PATH
        rp = (ROOT_PATH or "").rstrip("/")
    except Exception:
        rp = ""
    return f"{rp}/auth/refresh"


def _cookie_secure() -> bool:
    try:
        from shared.config import AUTH_COOKIE_SECURE
        return AUTH_COOKIE_SECURE
    except ImportError:
        return False


class RegisterRequest(BaseModel):
    email: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class AdminSetStatusRequest(BaseModel):
    status: str   # "active" | "disabled" | "locked"


class AdminSetRoleRequest(BaseModel):
    role: str  # "user" | "admin"


class AdminSetGroupsRequest(BaseModel):
    groups: list[str] = []


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class AdminCreateUserRequest(BaseModel):
    email: str
    display_name: str
    password: str
    role: str = "user"  # any role defined in the tenant's roles.yaml


class RoleUpsertRequest(BaseModel):
    id: str
    permissions: list[str] = []
    name: str = ""
    description: str = ""


async def _token_response(
    user,
    response: Response,
    sid: str = "",
    *,
    auth_time: int | None = None,
    request: Request | None = None,
) -> dict:
    """Issue an access + refresh token pair and set the auth cookies.

    ``sid`` empty means a new interactive login: a fresh session id is minted and
    registered as the user's active session (AUTH_SINGLE_SESSION). A refresh
    passes the refresh token's ``sid`` so the session keeps one id for its life.
    ``auth_time`` is the original login time (epoch seconds), carried across
    refreshes for the absolute session lifetime. ``request`` supplies session
    metadata (IP, user agent) for the session list.
    """
    import json as _json
    import urllib.parse as _urlp

    # Session index metadata (never a token). A refresh without ``request`` only
    # updates last_seen_at.
    session_meta = _session_metadata(request, user)
    if sid:
        await session_registry.touch(user.user_id, sid, auth_time=auth_time, **session_meta)
    else:
        sid = session_registry.new_session_id()
        await session_registry.register(user.user_id, sid, **session_meta)

    user_groups = getattr(user, "groups", None) or []
    must_change_password = bool(getattr(user, "must_change_password", False))
    access_token = create_access_token(user.user_id, sid)
    if auth_time is None:
        # New interactive login: the absolute session lifetime starts now.
        import time as _time
        auth_time = int(_time.time())
    refresh_token, jti = create_refresh_token(user.user_id, sid, auth_time=auth_time)

    _secure = _cookie_secure()
    response.set_cookie(
        key=_refresh_cookie_name(),
        value=refresh_token,
        httponly=True,
        secure=_secure,
        samesite="lax",
        # No max_age: a session cookie, dropped when the browser closes. The token's
        # own exp (JWT_REFRESH_TTL_DAYS) still bounds it server-side.
        path=_refresh_cookie_path(),
    )

    # httponly cookie: JS cannot read the access token.
    response.set_cookie(
        key="iaf_access_token",
        value=access_token,
        httponly=True,
        secure=_secure,
        samesite="lax",
        path="/",
    )
    # Readable (non-httponly) cookie: display info only, not a secret.
    _user_payload = {
        "user_id":      user.user_id,
        "email":        user.email,
        "display_name": getattr(user, "display_name", ""),
        "role":         user.role,
        "groups":       user_groups,
        # Lets the page re-apply the change-password gate on reload without
        # waiting for an API call to be refused.
        "must_change_password": must_change_password,
        "permissions":  effective_permissions(user.role, user_groups),
    }
    response.set_cookie(
        key="iaf_user",
        value=_urlp.quote(_json.dumps(_user_payload), safe=""),
        httponly=False,
        secure=_secure,
        samesite="lax",
        path="/",
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "must_change_password": must_change_password,
        "user": {
            "user_id":      user.user_id,
            "email":        user.email,
            "display_name": user.display_name,
            "role":         user.role,
            "groups":       user_groups,
            "permissions":  effective_permissions(user.role, user_groups),
            "last_login":   user.last_login,
            "must_change_password": must_change_password,
        },
    }


def _session_superseded_response() -> JSONResponse:
    """401 SESSION_SUPERSEDED that also signs the browser out.

    Returned (not raised) because an HTTPException drops cookies set on the
    injected Response. Clears the auth cookies like /auth/logout and leaves a
    short-lived readable reason cookie so the login page can explain why.
    """
    from auth.middleware import session_superseded_response
    _secure = _cookie_secure()
    resp = session_superseded_response()
    resp.delete_cookie(key=_refresh_cookie_name(), path=_refresh_cookie_path(), secure=_secure)
    resp.delete_cookie(key="iaf_access_token", path="/", secure=_secure)
    resp.delete_cookie(key="iaf_user", path="/", secure=_secure)
    return resp


SESSION_EXPIRED_DETAIL = "SESSION_EXPIRED"
LOGOUT_REASON_SESSION_EXPIRED = "session_expired"


def _session_max_hours() -> int:
    try:
        from shared.config import AUTH_SESSION_MAX_HOURS
        return int(AUTH_SESSION_MAX_HOURS)
    except ImportError:
        return 12


def _session_lifetime_exceeded(refresh_payload: dict) -> bool:
    """True when the session behind this refresh token is older than
    AUTH_SESSION_MAX_HOURS (0 disables). ``auth_time`` is the original login;
    a legacy token without it falls back to its ``iat``."""
    import time as _time
    max_hours = _session_max_hours()
    if max_hours <= 0:
        return False
    started = refresh_payload.get("auth_time") or refresh_payload.get("iat")
    try:
        started = int(started)
    except (TypeError, ValueError):
        return False
    return int(_time.time()) - started > max_hours * 3600


def _session_expired_response() -> JSONResponse:
    """401 SESSION_EXPIRED that signs the browser out (same cookie handling as
    ``_session_superseded_response``) with a readable reason cookie for the
    login page."""
    _secure = _cookie_secure()
    resp = JSONResponse(status_code=401, content={"detail": SESSION_EXPIRED_DETAIL})
    resp.set_cookie(
        key=session_registry.LOGOUT_REASON_COOKIE,
        value=LOGOUT_REASON_SESSION_EXPIRED,
        max_age=120,
        path="/",
        secure=bool(_secure),
        httponly=False,
        samesite="lax",
    )
    resp.delete_cookie(key=_refresh_cookie_name(), path=_refresh_cookie_path(), secure=_secure)
    resp.delete_cookie(key="iaf_access_token", path="/", secure=_secure)
    resp.delete_cookie(key="iaf_user", path="/", secure=_secure)
    return resp


def _access_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer = auth_header[7:].strip()
        if bearer:
            return bearer
    cookie_token = request.cookies.get("iaf_access_token")
    return cookie_token or None


async def _blacklist_access_token(token: str | None) -> None:
    if not token:
        return
    try:
        from auth.tokens import decode_access_token
        from shared.config import JWT_ACCESS_TTL_MINUTES
        payload = decode_access_token(token)
        jti = payload.get("jti", "")
        if jti:
            await blacklist_token(jti, JWT_ACCESS_TTL_MINUTES * 60 + 60)
    except Exception:
        pass


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _session_metadata(request: Request | None, user) -> dict:
    """IP, user agent and provider recorded in the session index on login."""
    meta = {"provider": getattr(user, "provider", "") or "local"}
    if request is not None:
        meta["ip"] = _get_client_ip(request)
        meta["user_agent"] = request.headers.get("user-agent", "")
    return meta


def _current_sid(request: Request) -> str:
    identity = getattr(request.state, "identity", None)
    return getattr(identity, "session_id", "") or ""


def _session_revoked_response() -> JSONResponse:
    """401 SESSION_REVOKED that also signs the browser out (see
    ``_session_superseded_response``)."""
    from auth.middleware import session_revoked_response
    _secure = _cookie_secure()
    resp = session_revoked_response()
    resp.delete_cookie(key=_refresh_cookie_name(), path=_refresh_cookie_path(), secure=_secure)
    resp.delete_cookie(key="iaf_access_token", path="/", secure=_secure)
    resp.delete_cookie(key="iaf_user", path="/", secure=_secure)
    return resp


async def _reject_revoked_refresh(user_id: str, jti: str, ip: str) -> JSONResponse:
    """Refresh of a revoked session: burn the refresh token and sign out."""
    if jti:
        await blacklist_token(jti, _refresh_ttl_days() * 86400 + 60)
    await audit.log_event(
        audit.TOKEN_REFRESH, user_id=user_id, ip=ip, success=False,
        details={"reason": session_registry.LOGOUT_REASON_REVOKED},
    )
    return _session_revoked_response()


def _refresh_identity_cookie(
    request: Request, response: Response, *, must_change_password: bool
) -> None:
    """Rewrite the readable `iaf_user` cookie in place.

    That cookie is written once, when a token is issued, so any state it carries
    goes stale the moment it changes by another route. This updates the rotation
    flag without reissuing tokens, preserving every other field already there.
    """
    import json as _json
    import urllib.parse as _urlp

    raw = request.cookies.get("iaf_user")
    payload: dict = {}
    if raw:
        try:
            payload = _json.loads(_urlp.unquote(raw))
        except Exception:
            payload = {}
    if not payload:
        payload = {
            "user_id": getattr(request.state, "user_id", "") or "",
            "email": getattr(request.state, "email", "") or "",
            "display_name": "",
            "role": getattr(request.state, "role", "") or "user",
            "groups": list(getattr(request.state, "groups", []) or []),
        }
    payload["must_change_password"] = must_change_password

    response.set_cookie(
        key="iaf_user",
        value=_urlp.quote(_json.dumps(payload), safe=""),
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.get("/auth/msal/config")
async def get_msal_config():
    """Public: returns MSAL frontend config (client IDs are not secrets)."""
    from shared.config import (
        AUTH_MICROSOFT_ENABLED,
        AUTH_MICROSOFT_AUTHORITY,
        MSAL_CLIENT_ID,
        MSAL_SCOPES,
        MSAL_REDIRECT_URI,
    )
    enabled = AUTH_MICROSOFT_ENABLED
    return {
        "enabled": enabled,
        "client_id":    MSAL_CLIENT_ID    if enabled else "",
        "authority":    AUTH_MICROSOFT_AUTHORITY if enabled else "",
        "scopes":       MSAL_SCOPES       if enabled else "",
        "redirect_uri": MSAL_REDIRECT_URI if enabled else "",
    }


@router.get("/auth/registration-mode")
async def get_registration_mode():
    from shared.config import AUTH_REGISTRATION_MODE
    return {"mode": AUTH_REGISTRATION_MODE}


@router.get("/auth/version")
async def get_app_version():
    """Public: app version sourced from the repo-root ``Version`` file.

    Resolve at request time so a changed ``Version`` file is picked up without a
    server restart (vs. the import-time ``APP_VERSION`` constant).
    """
    from shared.config import resolve_app_version
    return {"version": resolve_app_version()}


@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request, response: Response):
    from shared.config import AUTH_REGISTRATION_MODE

    ip = _get_client_ip(request)
    allowed, _ = await is_ip_allowed(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    if AUTH_REGISTRATION_MODE == "admin_only":
        raise HTTPException(
            status_code=403,
            detail="Self-registration is disabled. Contact your administrator to create an account.",
        )

    from auth.factory import get_provider
    provider = await get_provider()

    try:
        user = await provider.register(
            email=body.email,
            display_name=body.display_name,
            password=body.password,
        )
    except ValueError as exc:
        await audit.log_event(
            audit.REGISTER, email=body.email, ip=ip, success=False,
            details={"reason": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc))

    if AUTH_REGISTRATION_MODE == "approval":
        user.status = "pending"
        from auth.factory import get_store
        store = await get_store()
        await store.update(user)
        await audit.log_event(
            audit.REGISTER, user_id=user.user_id, email=user.email, ip=ip,
            details={"status": "pending_approval"},
        )
        return {
            "message": "Registration submitted. Your account is pending admin approval. "
                       "You will be notified once approved.",
            "status": "pending",
        }

    await audit.log_event(audit.REGISTER, user_id=user.user_id, email=user.email, ip=ip)
    return await _token_response(user, response, request=request)


@router.post("/auth/login")
async def login(body: LoginRequest, request: Request, response: Response):
    ip = _get_client_ip(request)
    allowed, _ = await is_login_allowed(ip)
    if not allowed:
        await audit.log_event(
            audit.LOGIN_FAILED, email=body.email, ip=ip, success=False,
            details={"reason": "rate_limited"},
        )
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")

    from auth.factory import get_provider
    provider = await get_provider()

    # All failures return the same 401 to prevent account enumeration via status codes
    # or distinct error messages (lockout oracle / user enumeration finding).
    try:
        user = await provider.login(email=body.email, password=body.password)
    except (PermissionError, ValueError) as exc:
        await audit.log_event(
            audit.LOGIN_FAILED, email=body.email, ip=ip, success=False,
            details={"reason": str(exc)},
        )
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await audit.log_event(audit.LOGIN, user_id=user.user_id, email=user.email, ip=ip)

    return await _token_response(user, response, request=request)


@router.post("/auth/sso/microsoft")
async def sso_microsoft(request: Request, response: Response):
    """Exchange a valid MSAL access token for an IAF JWT session.

    The frontend calls this endpoint after a successful MSAL login, passing
    the access token as ``Authorization: Bearer <msal_token>``.  The backend
    validates it via Azure AD JWKS, provisions the user on first login, and
    returns IAF session cookies + a JSON body::

        { "status": "USER_EXISTS"|"PENDING_APPROVAL",
          "email": "...", "username": "...",
          "access_token": "...",   # present when status == USER_EXISTS
          "user": { ... } }
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header. "
                   "Expected: Authorization: Bearer <msal_access_token>",
        )
    msal_token = auth_header[7:].strip()
    if not msal_token:
        raise HTTPException(status_code=401, detail="Empty MSAL access token.")

    ip = _get_client_ip(request)

    from auth.factory import get_microsoft_provider

    # Independent of AUTH_PROVIDER — works whether the primary provider is
    # "local" (password login stays available) or "microsoft".
    provider = await get_microsoft_provider()
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Microsoft SSO is not enabled on this server. "
                "Set AUTH_MICROSOFT_ENABLED=true in the server config."
            ),
        )

    try:
        from shared.config import AUTH_REGISTRATION_MODE
    except ImportError:
        AUTH_REGISTRATION_MODE = "admin_only"

    try:
        user, prov_status = await provider.login_with_msal_token(
            msal_token,
            registration_mode=AUTH_REGISTRATION_MODE,
        )
    except ValueError as exc:
        logger.warning("MSAL token validation failed from %s: %s", ip, exc)
        raise HTTPException(status_code=401, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    await audit.log_event(
        audit.LOGIN,
        user_id=user.user_id,
        email=user.email,
        ip=ip,
        details={"provider": "microsoft", "provisioning_status": prov_status},
    )

    if prov_status == "PENDING_APPROVAL":
        return {
            "status": prov_status,
            "email": user.email,
            "username": user.display_name,
            "message": (
                "Your account is pending administrator approval. "
                "You will be notified once approved."
            ),
        }

    result = await _token_response(user, response, request=request)
    result["status"] = prov_status
    result["email"] = user.email
    result["username"] = user.display_name
    return result


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    ip = _get_client_ip(request)

    user_id = getattr(request.state, "user_id", None)
    sid = ""
    token = _access_token_from_request(request)
    if token:
        try:
            from auth.tokens import decode_access_token
            access_payload = decode_access_token(token)
            user_id = user_id or access_payload.get("sub")
            sid = access_payload.get("sid", "") or ""
        except Exception:
            pass

    # Blacklist the access token (Bearer header or httponly cookie)
    await _blacklist_access_token(token)

    # Blacklist the refresh token if present
    cookie_name = _refresh_cookie_name()
    refresh_token = request.cookies.get(cookie_name)
    if refresh_token:
        try:
            payload = decode_refresh_token(refresh_token)
            user_id = user_id or payload.get("sub")
            sid = sid or payload.get("sid", "") or ""
            jti = payload.get("jti", "")
            if jti:
                await blacklist_token(jti, _refresh_ttl_days() * 86400 + 60)
        except Exception:
            pass

    # Revoke by sid: the refresh cookie never reaches this endpoint; end the active record only if it is still this sid.
    if user_id and sid:
        await session_registry.clear(user_id, sid)

    if user_id:
        try:
            from auth.sso_session import clear_session
            await clear_session(user_id)
        except Exception:
            pass

    _secure = _cookie_secure()
    response.delete_cookie(key=cookie_name, path=_refresh_cookie_path(), secure=_secure)
    response.delete_cookie(key="iaf_access_token", path="/", secure=_secure)
    response.delete_cookie(key="iaf_user", path="/", secure=_secure)

    await audit.log_event(audit.LOGOUT, user_id=user_id, ip=ip)

    # If user was an SSO user, return the Keycloak end-session URL
    keycloak_logout_url = None
    try:
        from shared.config import KEYCLOAK_ENABLED
        if KEYCLOAK_ENABLED and user_id:
            from auth.factory import get_store
            store = await get_store()
            user = await store.get_by_id(user_id)
            if user and getattr(user, "provider", "local") == "keycloak":
                from auth.keycloak_service import get_keycloak_service
                kc = get_keycloak_service()
                keycloak_logout_url = await kc.get_logout_url()
    except Exception:
        pass

    return {"message": "Logged out successfully.", "keycloak_logout_url": keycloak_logout_url}


@router.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    ip = _get_client_ip(request)
    cookie_name = _refresh_cookie_name()
    token = request.cookies.get(cookie_name)

    if not token:
        raise HTTPException(status_code=401, detail="No refresh token.")

    try:
        payload = decode_refresh_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    jti = payload.get("jti", "")
    if jti and await is_blacklisted(jti):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked.")

    user_id = payload.get("sub")
    # Refresh keeps the sid (tabs refresh concurrently); a legacy token without one is a new session.
    sid = payload.get("sid", "") or ""

    if sid and not await session_registry.is_current(user_id, sid):
        # Another browser/device has signed in since. Revoke this refresh token
        # so it cannot revive the session if the newer one later logs out.
        if jti:
            await blacklist_token(jti, _refresh_ttl_days() * 86400 + 60)
        await audit.log_event(
            audit.TOKEN_REFRESH, user_id=user_id, ip=ip, success=False,
            details={"reason": session_registry.LOGOUT_REASON_SUPERSEDED},
        )
        return _session_superseded_response()
    if sid and await session_registry.is_revoked(sid):
        return await _reject_revoked_refresh(user_id, jti, ip)

    if _session_lifetime_exceeded(payload):
        # Absolute session lifetime (AUTH_SESSION_MAX_HOURS): rotation must not
        # keep an active session alive forever. Revoke and sign the browser out.
        if jti:
            await blacklist_token(jti, _refresh_ttl_days() * 86400 + 60)
        await session_registry.clear(user_id, sid)  # drop from the session list
        await audit.log_event(
            audit.TOKEN_REFRESH, user_id=user_id, ip=ip, success=False,
            details={"reason": "session_max_lifetime"},
        )
        return _session_expired_response()
    # Original login time, carried into the rotated refresh token. A legacy
    # token without auth_time falls back to its iat.
    auth_time = payload.get("auth_time") or payload.get("iat")

    from auth.factory import get_provider
    provider = await get_provider()
    user = await provider.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Account not found or inactive.")
    if user.status == "disabled":
        raise HTTPException(
            status_code=401,
            detail="Account is disabled. Contact your administrator.",
        )
    if user.status != "active":
        raise HTTPException(status_code=401, detail="Account not found or inactive.")

    try:
        from auth.sso_session import SESSION_EXPIRED, enforce_sso_session
        sso_reason = await enforce_sso_session(
            user.user_id,
            provider=getattr(user, "provider", "local"),
        )
        if sso_reason:
            raise HTTPException(status_code=401, detail=sso_reason)
    except HTTPException:
        raise
    except Exception:
        pass

    # Rotate: blacklist old refresh token, issue new pair
    if jti:
        await blacklist_token(jti, _refresh_ttl_days() * 86400 + 60)

    await audit.log_event(audit.TOKEN_REFRESH, user_id=user.user_id, ip=ip)
    # Same sid -> _token_response only extends its TTL; it never rewrites it.
    return await _token_response(
        user, response, sid=sid,
        auth_time=int(auth_time) if auth_time is not None else None,
    )


@router.get("/auth/me")
async def get_me(request: Request, _: dict = Depends(require_auth)):
    from auth.factory import get_provider
    provider = await get_provider()
    user = await provider.get_user(request.state.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    _groups = getattr(user, "groups", []) or []
    # Union permissions across all roles on request.state.roles; fall back to the stored role.
    _roles = getattr(request.state, "roles", None) or [user.role]
    _tenant = _tenant_of(request)
    _perms = sorted({
        p for r in _roles for p in effective_permissions(r, _groups, _tenant)
    })
    return {
        "user_id":      user.user_id,
        "email":        user.email,
        "display_name": user.display_name,
        "role":         user.role,
        "groups":       _groups,
        "permissions":  _perms,
        "provider":     getattr(user, "provider", "local"),
        "status":       user.status,
        "last_login":   user.last_login,
        "mfa_enabled":  user.mfa_enabled,
        "created_at":   user.created_at,
        # Live answer: the iaf_user cookie is only a snapshot from token issuance.
        "must_change_password": bool(getattr(user, "must_change_password", False)),
    }


@router.put("/auth/me/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    _: dict = Depends(require_auth),
):
    from auth.factory import get_provider
    provider = await get_provider()
    try:
        await provider.change_password(
            request.state.user_id,
            body.old_password,
            body.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Refresh iaf_user: it still holds the pre-rotation must_change_password value.
    _refresh_identity_cookie(request, response, must_change_password=False)

    await audit.log_event(
        audit.PASSWORD_CHANGED,
        user_id=request.state.user_id,
        ip=_get_client_ip(request),
    )
    return {"message": "Password changed successfully."}


@router.get("/auth/policy")
async def get_password_policy():
    from auth.password_policy import get_policy
    return get_policy().to_frontend_rules()


@router.get("/auth/session-policy")
async def get_session_policy():
    """Public, unauthenticated: SEC-7 idle-timeout minutes for the client-side
    timer (session-controls.js / index.html). Not secret, so no auth check —
    mirrors /auth/policy and /auth/registration-mode. Lets ops retune the idle
    timeout per deployment via SESSION_IDLE_LOGOUT_MINUTES / SESSION_IDLE_WARN_MINUTES
    instead of editing JS."""
    from shared.config import SESSION_IDLE_LOGOUT_MINUTES, SESSION_IDLE_WARN_MINUTES
    return {
        "idle_logout_minutes": SESSION_IDLE_LOGOUT_MINUTES,
        "idle_warn_minutes": SESSION_IDLE_WARN_MINUTES,
    }


@router.post("/auth/users")
async def admin_create_user(
    body: AdminCreateUserRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    role = (body.role or "user").strip().lower()
    _roles = known_roles(_tenant_of(request))
    if role not in _roles:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role '{role}'. Known roles: {', '.join(_roles)}",
        )
    body.role = role

    from auth.factory import get_provider
    provider = await get_provider()

    try:
        user = await provider.register(
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            role=body.role,
            # Admin-chosen password is temporary; applied during create so a failure leaves no permanent credential.
            must_change_password=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user.iaf_rbac_managed = True
    from auth.factory import get_store
    store = await get_store()
    await store.update(user)

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={"action": "create_user", "new_user": user.email, "role": user.role},
    )
    return {
        "message": f"User '{user.email}' created successfully.",
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "must_change_password": True,
    }


@router.get("/auth/users")
async def list_users(
    limit: int = 50,
    offset: int = 0,
    search: str = "",
    role: str = "",
    status: str = "",
    _: dict = Depends(require_admin),
):
    from auth.factory import get_store
    store = await get_store()

    q = (search or "").strip().lower()
    role_f = (role or "").strip()
    status_f = (status or "").strip()

    available_roles = await store.list_roles()
    total = await store.count(search=q, role=role_f, status=status_f)
    users = await store.list_users(
        limit=limit,
        offset=offset,
        search=q,
        role=role_f,
        status=status_f,
    )

    return {
        "total": total,
        "roles": available_roles,
        "users": [
            {
                "user_id":      u.user_id,
                "email":        u.email,
                "display_name": u.display_name,
                "role":         u.role,
                "groups":       getattr(u, "groups", []) or [],
                "provider":     getattr(u, "provider", "local"),
                "iaf_rbac_managed": getattr(u, "iaf_rbac_managed", False),
                "status":       u.status,
                "created_at":   u.created_at,
                "last_login":   u.last_login,
                "failed_attempts": u.failed_attempts,
            }
            for u in users
        ],
    }


@router.get("/auth/rbac/groups")
async def list_rbac_groups(_: dict = Depends(require_admin)):
    from pathlib import Path
    import yaml
    try:
        from shared.config import SERVER_DIR, DATA_ROOT, TENANT_ID
        policy_file = (
            Path(SERVER_DIR) / DATA_ROOT / "tenants" / TENANT_ID / "security" / "policies.yaml"
        )
    except ImportError:
        policy_file = Path("enterprise_root/tenants/company/security/policies.yaml")

    groups: set[str] = set()
    if policy_file.exists():
        doc = yaml.safe_load(policy_file.read_text(encoding="utf-8")) or {}
        for policy in doc.get("policies", []) or []:
            for g in policy.get("groups") or []:
                if g:
                    groups.add(str(g))

    # Well-known defaults if policies file is sparse
    defaults = {
        "finance", "finance-ap", "finance-ar", "finance-gl",
        "it-ops", "sre", "platform-ops", "marketing", "ai-programs",
    }
    groups |= defaults
    return {"groups": sorted(groups)}


@router.get("/auth/rbac/roles")
async def list_rbac_roles(request: Request, _: dict = Depends(require_admin)):
    """List defined roles (with their permission keys) and the permission catalog."""
    registry = load_role_registry(_tenant_of(request))
    roles = [
        {
            "id": rid,
            "name": meta.get("name") or rid.title(),
            "description": meta.get("description") or "",
            "permissions": effective_permissions(rid, tenant_id=_tenant_of(request)),
            "builtin": rid in ("user", "admin"),
        }
        for rid, meta in registry.items()
    ]
    return {"roles": roles, "catalog": permission_catalog()}


@router.post("/auth/rbac/roles")
async def create_or_update_rbac_role(
    body: RoleUpsertRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Create or update a role definition in the tenant's roles.yaml."""
    try:
        saved = upsert_role(
            role_id=body.id,
            permissions=body.permissions,
            name=body.name,
            description=body.description,
            tenant_id=_tenant_of(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={"action": "upsert_role", "role": saved["id"], "permissions": saved["permissions"]},
    )
    return {"message": f"Role '{saved['id']}' saved.", "role": saved}


@router.delete("/auth/rbac/roles/{role_id}")
async def delete_rbac_role(
    role_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Delete a role definition (built-in 'user'/'admin' cannot be deleted)."""
    try:
        delete_role(role_id, tenant_id=_tenant_of(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={"action": "delete_role", "role": role_id.strip().lower()},
    )
    return {"message": f"Role '{role_id.strip().lower()}' deleted."}


@router.put("/auth/users/{user_id}/role")
async def set_user_role(
    user_id: str,
    body: AdminSetRoleRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    role = body.role.strip().lower()
    _roles = known_roles(_tenant_of(request))
    if role not in _roles:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role '{role}'. Known roles: {', '.join(_roles)}",
        )
    if user_id == admin.get("user_id"):
        raise HTTPException(status_code=400, detail="Cannot change your own role.")

    from auth.factory import get_store
    store = await get_store()
    user = await store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    previous_role = user.role
    user.role = role
    user.iaf_rbac_managed = True
    await store.update(user)

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={
            "action": "set_role",
            "target_user": user_id,
            "email": user.email,
            "previous_role": previous_role,
            "new_role": role,
            "provider": getattr(user, "provider", "local"),
        },
    )
    return {
        "message": f"Role updated to '{role}'. Applies on next login.",
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "iaf_rbac_managed": True,
    }


@router.put("/auth/users/{user_id}/groups")
async def set_user_groups(
    user_id: str,
    body: AdminSetGroupsRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    from auth.factory import get_store
    store = await get_store()
    user = await store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    cleaned = sorted({g.strip() for g in body.groups if g and g.strip()})
    previous = list(getattr(user, "groups", []) or [])
    user.groups = cleaned
    user.iaf_rbac_managed = True
    await store.update(user)

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={
            "action": "set_groups",
            "target_user": user_id,
            "email": user.email,
            "previous_groups": previous,
            "new_groups": cleaned,
            "provider": getattr(user, "provider", "local"),
        },
    )
    return {
        "message": "Groups updated. Applies on next login.",
        "user_id": user.user_id,
        "email": user.email,
        "groups": user.groups,
        "iaf_rbac_managed": True,
    }


@router.put("/auth/users/{user_id}/status")
async def set_user_status(
    user_id: str,
    body: AdminSetStatusRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    if body.status not in ("active", "disabled", "locked"):
        raise HTTPException(status_code=400, detail="status must be active|disabled|locked")

    from auth.factory import get_store
    store = await get_store()
    user = await store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.status = body.status
    if body.status == "active":
        user.failed_attempts = 0
        user.locked_until = None
    await store.update(user)

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={"action": "set_status", "target_user": user_id, "new_status": body.status},
    )
    if body.status != "active":
        await _end_user_sessions(request, admin, user_id, f"admin_set_status_{body.status}")
    return {"message": f"User status set to '{body.status}'."}


@router.post("/auth/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    body: AdminResetPasswordRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    from auth.factory import get_provider
    provider = await get_provider()
    try:
        await provider.reset_password(user_id, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit.log_event(
        audit.PASSWORD_RESET,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={"target_user": user_id},
    )
    await _end_user_sessions(request, admin, user_id, "admin_reset_password")
    return {"message": "Password reset successfully."}


@router.delete("/auth/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    if user_id == admin.get("user_id"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")

    from auth.factory import get_store
    store = await get_store()
    user = await store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    await store.delete(user_id)

    await audit.log_event(
        audit.ADMIN_ACTION,
        user_id=admin.get("user_id"),
        ip=_get_client_ip(request),
        details={"action": "delete_user", "target_user": user_id, "email": user.email},
    )
    await _end_user_sessions(request, admin, user_id, "admin_delete_user")
    return {"message": "User deleted."}


_SESSION_STORE_UNAVAILABLE = "Session store unavailable. Please retry."


async def _audit_revocation(request: Request, actor_id: str | None, target_user: str,
                            action: str, revoked: int) -> None:
    await audit.log_event(
        audit.SESSION_REVOKED,
        user_id=actor_id,
        ip=_get_client_ip(request),
        details={"action": action, "target_user": target_user, "revoked": revoked},
    )


async def _end_user_sessions(request: Request, admin: dict, user_id: str, action: str) -> int:
    """Revoke every session of ``user_id`` after an admin action on the account.

    Best effort: the admin action already succeeded, and the disabled /
    temporary-password gates still apply, so a Redis outage is logged, not raised.
    An admin acting on their own account keeps the session they are using.
    """
    keep = _current_sid(request) if user_id == admin.get("user_id") else ""
    try:
        revoked = await session_registry.revoke_all(user_id, except_sid=keep)
    except session_registry.SessionStoreError as exc:
        logger.warning("Could not revoke sessions of %s after %s: %s", user_id, action, exc)
        return 0
    await _audit_revocation(request, admin.get("user_id"), user_id, action, revoked)
    return revoked


@router.get("/auth/sessions")
async def list_my_sessions(request: Request, user: dict = Depends(require_auth)):
    """The caller's active sessions. ``current`` marks the one making this call."""
    try:
        records = await session_registry.list_sessions(user["user_id"])
    except session_registry.SessionStoreError:
        raise HTTPException(status_code=503, detail=_SESSION_STORE_UNAVAILABLE)
    current = _current_sid(request)
    return {"sessions": [session_registry.public_view(r, current) for r in records]}


@router.delete("/auth/sessions/{session_id}")
async def revoke_my_session(session_id: str, request: Request, user: dict = Depends(require_auth)):
    """Sign out one of the caller's other sessions (by its public ``id``)."""
    user_id = user["user_id"]
    try:
        outcome = await session_registry.revoke(
            user_id, session_id, current_sid=_current_sid(request),
        )
    except session_registry.SessionStoreError:
        raise HTTPException(status_code=503, detail=_SESSION_STORE_UNAVAILABLE)
    if outcome == session_registry.IS_CURRENT:
        raise HTTPException(
            status_code=400,
            detail="This is your current session. Use Sign Out to end it.",
        )
    if outcome != session_registry.REVOKED:
        raise HTTPException(status_code=404, detail="Session not found.")
    await _audit_revocation(request, user_id, user_id, "user_revoke_session", 1)
    return {"message": "Session signed out.", "revoked": 1}


@router.post("/auth/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    keep_current: bool = False,
    user: dict = Depends(require_auth),
):
    """Sign out of all devices. With ``keep_current=true`` the calling session
    stays signed in; otherwise it is logged out too and its cookies cleared."""
    user_id = user["user_id"]
    current = _current_sid(request)
    try:
        revoked = await session_registry.revoke_all(
            user_id,
            except_sid=current if keep_current else "",
            include_sid="" if keep_current else current,
        )
    except session_registry.SessionStoreError:
        raise HTTPException(status_code=503, detail=_SESSION_STORE_UNAVAILABLE)
    await _audit_revocation(
        request, user_id, user_id,
        "logout_all_keep_current" if keep_current else "logout_all", revoked,
    )
    if keep_current:
        return {"message": "Signed out of all other sessions.", "revoked": revoked}
    result = await logout(request, response)
    result["message"] = "Signed out of all sessions."
    result["revoked"] = revoked
    return result


async def _require_existing_user(user_id: str) -> None:
    from auth.factory import get_store
    store = await get_store()
    if not await store.get_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found.")


@router.get("/auth/users/{user_id}/sessions")
async def admin_list_user_sessions(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    await _require_existing_user(user_id)
    try:
        records = await session_registry.list_sessions(user_id)
    except session_registry.SessionStoreError:
        raise HTTPException(status_code=503, detail=_SESSION_STORE_UNAVAILABLE)
    current = _current_sid(request) if user_id == admin.get("user_id") else ""
    return {
        "user_id": user_id,
        "sessions": [session_registry.public_view(r, current) for r in records],
    }


@router.post("/auth/users/{user_id}/revoke-sessions")
async def admin_revoke_user_sessions(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Sign the user out everywhere (an admin targeting themselves keeps the
    session they are using)."""
    await _require_existing_user(user_id)
    keep = _current_sid(request) if user_id == admin.get("user_id") else ""
    try:
        revoked = await session_registry.revoke_all(user_id, except_sid=keep)
    except session_registry.SessionStoreError:
        raise HTTPException(status_code=503, detail=_SESSION_STORE_UNAVAILABLE)
    await _audit_revocation(request, admin.get("user_id"), user_id, "admin_revoke_sessions", revoked)
    return {"message": f"Signed out {revoked} session(s).", "user_id": user_id, "revoked": revoked}
