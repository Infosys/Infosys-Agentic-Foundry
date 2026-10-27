"""
routers/oauth.py - Keycloak SSO endpoints

Endpoints:
  GET  /auth/oauth/status   Is Keycloak SSO enabled?
  GET  /auth/oauth/login    Generate Keycloak auth URL (PKCE)
  GET  /auth/callback       Browser redirect from Keycloak -> exchange code -> redirect to /login with tokens
  POST /auth/oauth/refresh  Refresh Keycloak tokens
  POST /auth/oauth/logout   Revoke Keycloak refresh token, return end-session URL
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from auth import session_registry
from auth.keycloak_service import get_keycloak_service
from auth.tokens import create_access_token, create_refresh_token

logger = logging.getLogger("iaf_server.routers.oauth")

router = APIRouter(tags=["oauth"])


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


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _find_or_create_user(
    email: str,
    display_name: str,
    roles: list[str],
    groups: list[str] | None = None,
    ip: str | None = None,
):
    """Look up user by email in IAF UserStore; auto-create on first SSO login.

    Returning users keep role/groups assigned in IAF (admin UI). Keycloak is used
    only for identity verification - not to overwrite IAF-managed RBAC."""
    from auth.factory import get_store
    from auth import audit
    store = await get_store()
    kc_has_roles = bool(roles)          # did Keycloak actually return any roles?
    kc_role = "admin" if "admin" in roles else "user"
    kc_groups = groups or []

    user = await store.get_by_email(email)
    if user:
        if display_name and user.display_name != display_name:
            user.display_name = display_name
        if not getattr(user, "iaf_rbac_managed", False):
            # Seed the role from Keycloak only when it returned roles; with local RBAC an empty set must not downgrade the role.
            if kc_has_roles and user.role != kc_role:
                logger.info("SSO: initial role for %s: %s", email, kc_role)
                user.role = kc_role
            if kc_groups:
                user.groups = kc_groups
        from datetime import datetime, timezone
        user.last_login = datetime.now(timezone.utc).isoformat()
        await store.update(user)
        await audit.log_event(
            audit.LOGIN, user_id=user.user_id, email=email, ip=ip,
            details={
                "provider": "keycloak",
                "role": user.role,
                "groups": user.groups,
                "iaf_rbac_managed": getattr(user, "iaf_rbac_managed", False),
            },
        )
        return user

    from auth.base import UserRecord
    new_user = UserRecord.new(email=email, display_name=display_name, role=kc_role)
    new_user.provider = "keycloak"
    new_user.groups = kc_groups
    await store.create(new_user, password_hash="")
    logger.info("SSO: auto-created user %s (role=%s, groups=%s)", email, kc_role, kc_groups)
    await audit.log_event(
        "SSO_USER_CREATED", user_id=new_user.user_id, email=email, ip=ip,
        details={"provider": "keycloak", "role": kc_role, "groups": kc_groups},
    )
    return new_user


async def _issue_iaf_tokens(user, response: Response) -> dict:
    """Issue IAF HS256 access + refresh tokens and set refresh cookie.

    An SSO callback is a new interactive login, so it gets a fresh session id,
    registered as the user's active session (AUTH_SINGLE_SESSION). The tokens
    carry only sub/sid/jti; identity is looked up server-side.
    """
    sid = session_registry.new_session_id()
    await session_registry.register(user.user_id, sid)
    access_token = create_access_token(user.user_id, sid)
    # New login: the absolute session lifetime (AUTH_SESSION_MAX_HOURS) starts now.
    import time as _time
    refresh_token, _jti = create_refresh_token(user.user_id, sid, auth_time=int(_time.time()))

    response.set_cookie(
        key=_refresh_cookie_name(),
        value=refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=_refresh_cookie_path(),
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "user_id":      user.user_id,
            "email":        user.email,
            "display_name": user.display_name,
            "role":         user.role,
        },
    }


@router.get("/auth/oauth/status")
async def oauth_status():
    kc = get_keycloak_service()
    return {
        "keycloak_enabled": kc.is_enabled,
        "features": {
            "pkce": True,
            "refresh_tokens": True,
        },
    }


@router.get("/auth/oauth/login")
async def oauth_login():
    kc = get_keycloak_service()
    if not kc.is_enabled:
        raise HTTPException(status_code=503, detail="Keycloak SSO is not enabled.")

    try:
        auth_url, state = await kc.get_authorization_url()
        return {"authorization_url": auth_url, "state": state}
    except Exception as exc:
        logger.error("SSO login init failed: %s", exc)
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.get("/auth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """Standard SSO callback — the one fixed redirect URI both providers use.

    Keycloak's server-side PKCE exchange runs here directly (code+state against
    the stored verifier). Microsoft/Entra's PKCE exchange runs client-side in
    login.html, so when Keycloak is not the active provider this just relays
    the raw query string through to /login unchanged — the same relay the old
    standalone "/auth-callback" route performed, now under the shared path.
    AUTH_MICROSOFT_ENABLED and KEYCLOAK_ENABLED are mutually exclusive
    (enforced at config load), so only one of these branches is ever
    reachable per deployment.
    """
    kc = get_keycloak_service()
    if not kc.is_enabled:
        qs = request.url.query
        return RedirectResponse(url=f"/login?{qs}" if qs else "/login", status_code=302)

    if error:
        logger.warning("SSO callback error: %s - %s", error, error_description)
        params = urlencode({"sso_error": error_description or error})
        return RedirectResponse(url=f"/login?{params}", status_code=302)

    if not code or not state:
        return RedirectResponse(url="/login?sso_error=Missing+code+or+state", status_code=302)

    try:
        tokens = await kc.exchange_code(code, state)
        user_info = await kc.get_userinfo(tokens.access_token)

        display = (
            user_info.name
            or user_info.preferred_username
            or user_info.email.split("@")[0]
        )
        ip = _get_client_ip(request)
        user = await _find_or_create_user(
            email=user_info.email,
            display_name=display,
            roles=user_info.roles,
            groups=user_info.groups,
            ip=ip,
        )

        try:
            from auth.sso_session import establish_session
            await establish_session(
                user.user_id,
                provider="keycloak",
                keycloak_refresh_token=tokens.refresh_token,
                refresh_ttl_seconds=int(tokens.refresh_expires_in or tokens.expires_in or 3600),
            )
        except Exception as exc:
            logger.warning("SSO session record skipped: %s", exc)

        # Redirect to /login?sso=ok as a non-secret presence signal.
        # iaf_sso_token (the access token) is removed — the session is established
        # via the HttpOnly refresh cookie written by _issue_iaf_tokens.
        # iaf_sso_user carries only display info and is safe as a readable cookie.
        import json as _json
        response = RedirectResponse(url="/login?sso=ok", status_code=302)
        iaf_data = await _issue_iaf_tokens(user, response)
        _secure = _cookie_secure()
        response.set_cookie(
            key="iaf_sso_user",
            value=_json.dumps(iaf_data["user"]),
            httponly=False,
            secure=_secure,
            samesite="lax",
            max_age=120,
            path="/",
        )

        logger.info("SSO: callback successful for %s", user_info.email)
        return response

    except ValueError as exc:
        logger.warning("SSO callback failed: %s", exc)
        return RedirectResponse(
            url=f"/login?sso_error={urlencode({'e': str(exc)}).split('=',1)[1]}",
            status_code=302,
        )
    except Exception as exc:
        logger.error("SSO callback error: %s", exc, exc_info=True)
        return RedirectResponse(url="/login?sso_error=Internal+error", status_code=302)


@router.post("/auth/oauth/refresh")
async def oauth_refresh(request: Request):
    kc = get_keycloak_service()
    if not kc.is_enabled:
        raise HTTPException(status_code=503, detail="Keycloak SSO is not enabled.")

    try:
        body = await request.json()
        refresh_token = body.get("refresh_token")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="Missing refresh_token")

    try:
        tokens = await kc.refresh_tokens(refresh_token)
        return {
            "access_token": tokens.access_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "refresh_token": tokens.refresh_token,
        }
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/auth/oauth/logout")
async def oauth_logout(request: Request):
    kc = get_keycloak_service()
    refresh_token = None
    id_token = None
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token")
        id_token = body.get("id_token")
    except Exception:
        pass

    if kc.is_enabled and refresh_token:
        try:
            await kc.revoke_refresh_token(refresh_token)
        except Exception as exc:
            logger.warning("SSO: refresh revocation failed: %s", exc)

    logout_url = None
    if kc.is_enabled:
        logout_url = await kc.get_logout_url(id_token_hint=id_token)

    return {"logout_url": logout_url, "message": "logout_success"}
