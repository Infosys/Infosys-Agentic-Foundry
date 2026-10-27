"""
auth/middleware.py — FastAPI authentication middleware

Responsibilities:
  1. Extract Bearer token from Authorization header
  2. Decode + validate JWT, check blacklist and revoked/superseded session (sid)
  3. Complete the identity from the user store (the browser token carries only
     sub/sid) and attach user context to request.state
  4. Apply security headers to every response
  5. Bypass list for public routes (login, register, refresh, static)

IMPORTANT: AUTH_ENABLED in config.py acts as a master switch.
           When false, middleware is a no-op — useful for local dev.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from shared.csp_nonce import generate_nonce

logger = logging.getLogger("iaf_server.auth.middleware")

# Routes that do NOT require a valid access token
_PUBLIC_EXACT = {
    "/",
    "/favicon.ico",
    "/login",
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/auth/policy",
    "/auth/session-policy",   # public: SEC-7 idle-timeout minutes (not secret)
    "/auth/registration-mode",
    "/auth/version",          # public: app version string for the login screen
    "/auth/msal/config",        # public: MSAL frontend config (client IDs, authority)
    "/auth/sso/microsoft",      # public: MSAL token → IAF session exchange
    "/auth/oauth/login",
    "/auth/oauth/status",
    "/auth/callback",           # public: standard SSO callback (Keycloak code exchange, or MSAL relay → /login)
    "/auth/oauth/logout",
    "/auth/oauth/refresh",
    "/auth/privacy/notice",   # public: privacy notice + declaration text (pre-auth display)
    "/health/live",
    "/health/ready",
    "/metrics",
    "/dashboard",
    "/dashboard/v2",
    "/twin",
    "/twin/optimization",
    "/skill-builder",
    "/skill-builder/v2",
    "/skill-creator",
    "/studio",
    "/customize",
    "/finops",
    "/observers",
    "/rl-capture",
    "/rl-capture/workbench",
    "/rl-eval",
}

_PUBLIC_PREFIXES = (
    "/static/",
    "/api/files/serve",   # image serving — browser <img> tags can't send auth headers
    "/api/queue/feed",    # queue feeder — called by cron skill via curl (no browser session)
    "/api/queue/ingest",  # external webhook — called by PagerDuty/ServiceNow (API-key auth only)
    "/api/observers/act", # observer gateway — sidecar/Headlong skill (X-API-Key auth only)
    "/observers/",        # observer detail page shells (data XHRs still carry the JWT)
)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    if path.startswith(("/api/mock/", "/mock/")):
        try:
            from shared.config import DEMO_PUBLIC_SURFACES
        except ImportError:
            DEMO_PUBLIC_SURFACES = False
        return DEMO_PUBLIC_SURFACES
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def _route_path(request: Request) -> str:
    """Return the request path with the configured ROOT_PATH prefix removed.

    Under a sub-path deployment (e.g. ROOT_PATH="/agentos") the ASGI path the
    middleware sees is the full "/agentos/...". The public-route allowlist and
    the security-header logic here are defined in un-prefixed terms ("/",
    "/login", "/static/"), so strip the prefix to keep them prefix-agnostic.
    No-op when ROOT_PATH is empty (root deployment)."""
    path = request.url.path
    try:
        from shared.config import ROOT_PATH
    except Exception:
        ROOT_PATH = ""
    if ROOT_PATH and (path == ROOT_PATH or path.startswith(ROOT_PATH + "/")):
        stripped = path[len(ROOT_PATH):]
        return stripped or "/"
    return path


# ---------------------------------------------------------------------------
# Security headers applied to every response
# ---------------------------------------------------------------------------

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def _build_csp(nonce: Optional[str] = None, *, allow_eval: bool = False) -> str:
    """Build the Content-Security-Policy header value (SEC-4)."""
    script_src = "script-src 'self' 'unsafe-eval'" if allow_eval else "script-src 'self'"
    style_src = "style-src 'self'"
    if nonce:
        script_src += f" 'nonce-{nonce}'"
        style_src += f" 'nonce-{nonce}'"
    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "connect-src 'self' wss: ws: https://login.microsoftonline.com; "
        f"{script_src}; "
        "script-src-attr 'unsafe-inline'; "
        f"{style_src}; "
        "style-src-attr 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'; "
        "form-action 'self';"
    )


def _strict_report_only_enabled() -> bool:
    return os.getenv("CSP_STRICT_REPORT_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_STRICT_CSP_PATHS = (
    "/world-model",
    "/graph-review",
    "/static/world_model_review.html",
    "/static/finance_workstreams_explainer.html",
)


_ALPINE_PAGES = frozenset(
    {
        "bp_policy_opportunity.html",
        "bp_workstream_detail.html",
        "bp_workstreams.html",
        "dashboard_v2.html",
        "finops.html",
        "index.html",
        "index_v2_chatgpt.html",
        "index_v3_refined.html",
        "login.html",
        "optimization.html",
        "rl_capture.html",
        "rl_workbench.html",
        "skill-builder-v2.html",
        "skill-creator.html",
        "studio.html",
        "twin.html",
        "workstream_detail.html",
        "workstream_new.html",
        "workstreams.html",
    }
)

_EVAL_CSP_ROUTES = frozenset(
    {
        "/",
        "/customize",
        "/dashboard",
        "/dashboard/v2",
        "/finops",
        "/login",
        "/rl-capture",
        "/rl-capture/workbench",
        "/rl-eval",
        "/skill-builder/v2",
        "/skill-creator",
        "/studio",
        "/twin",
        "/twin/optimization",
    }
)

_EVAL_CSP_PATHS = _EVAL_CSP_ROUTES | frozenset(f"/static/{p}" for p in _ALPINE_PAGES)


def _needs_eval(path: str) -> bool:
    """True only for paths that serve an Alpine.js page."""
    return path.rstrip("/") in _EVAL_CSP_PATHS or path in _EVAL_CSP_PATHS


def _is_strict_csp_path(path: str) -> bool:
    """True when *path* is served by a page proven to satisfy the strict CSP."""
    return path.rstrip("/") in _STRICT_CSP_PATHS or path in _STRICT_CSP_PATHS


def _build_strict_csp(nonce: Optional[str] = None) -> str:
    """Build the SEC-4b target policy — nonce-only, no ``'unsafe-eval'``, no ``-attr`` escape hatch, no wildcard ``font-src``."""
    script_src = "script-src 'self'"
    style_src = "style-src 'self'"
    if nonce:
        script_src += f" 'nonce-{nonce}'"
        style_src += f" 'nonce-{nonce}'"
    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "connect-src 'self' wss: ws: https://login.microsoftonline.com; "
        f"{script_src}; "
        f"{style_src}; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'; "
        "form-action 'self';"
    )


_CACHEABLE_STATIC_SUFFIXES = (".js", ".mjs", ".css")

_SAME_ORIGIN_FRAMEABLE = (
    "/api/files/serve",
    "/skill-creator",
    "/static/workstream_detail.html",
)


def _add_security_headers(response: Response, path: str = "", nonce: Optional[str] = None) -> None:
    for header, value in _SECURITY_HEADERS.items():
        response.headers[header] = value
    enforce_strict = nonce is None or _is_strict_csp_path(path)
    csp = (
        _build_strict_csp(nonce)
        if enforce_strict
        else _build_csp(nonce, allow_eval=_needs_eval(path))
    )
    strict = (
        _build_strict_csp(nonce)
        if (not enforce_strict and _strict_report_only_enabled())
        else None
    )
    if path.startswith(_SAME_ORIGIN_FRAMEABLE):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        csp = csp.replace("frame-ancestors 'none';", "frame-ancestors 'self';")
        if strict:
            strict = strict.replace(
                "frame-ancestors 'none';", "frame-ancestors 'self';"
            )
    response.headers["Content-Security-Policy"] = csp
    if strict:
        response.headers["Content-Security-Policy-Report-Only"] = strict
    is_cacheable_static_asset = path.startswith("/static/") and path.endswith(
        _CACHEABLE_STATIC_SUFFIXES
    )
    if not is_cacheable_static_asset:
        response.headers["Cache-Control"] = "no-store"


class TokenRevokedError(Exception):
    """The token's jti is on the blacklist (logout / refresh rotation)."""


class SessionSupersededError(Exception):
    """This token's session has ended: a newer login replaced it
    (AUTH_SINGLE_SESSION). ``str(exc)`` is the 401 detail code."""


class SessionRevokedError(SessionSupersededError):
    """This token's session was revoked (signed out from another device, "sign
    out of all devices", or by an administrator). Subclass of
    ``SessionSupersededError`` so every handler of an ended session covers it."""


class IdentityStoreUnavailableError(Exception):
    """The user store could not be read, so the identity cannot be completed."""


_SESSION_GATE_EXEMPT_EXACT = {
    "/auth/logout",
    "/auth/oauth/logout",
}


async def authenticate_access_token(token: str, *, enforce_session_gate: bool = True):
    """Validate an access token and return ``(identity, user_record | None)``."""
    from auth import session_registry
    from auth.identity import (
        IdentityResolutionError,
        enrich_identity_from_store,
        resolve_access_token_identity,
    )
    from auth.tokens import is_blacklisted

    identity = resolve_access_token_identity(token)
    if identity.jti and await is_blacklisted(identity.jti):
        raise TokenRevokedError("Token has been revoked.")
    if enforce_session_gate and identity.session_id:
        ended = await session_registry.check(identity.user_id, identity.session_id)
        if ended == session_registry.SESSION_REVOKED:
            raise SessionRevokedError(ended)
        if ended:
            raise SessionSupersededError(ended)
    try:
        return await enrich_identity_from_store(identity)
    except IdentityResolutionError:
        raise
    except Exception as exc:
        raise IdentityStoreUnavailableError(str(exc)) from exc


def session_superseded_response() -> JSONResponse:
    """401 for a superseded session plus a short-lived, readable reason cookie
    the login page uses to tell the user why they were signed out."""
    from auth.session_registry import LOGOUT_REASON_SUPERSEDED, SESSION_SUPERSEDED
    return _session_ended_response(SESSION_SUPERSEDED, LOGOUT_REASON_SUPERSEDED)


def session_revoked_response() -> JSONResponse:
    """401 SESSION_REVOKED plus the ``session_revoked`` reason cookie."""
    from auth.session_registry import LOGOUT_REASON_REVOKED, SESSION_REVOKED
    return _session_ended_response(SESSION_REVOKED, LOGOUT_REASON_REVOKED)


def _session_ended_response(detail: str, reason: str) -> JSONResponse:
    from auth.session_registry import LOGOUT_REASON_COOKIE
    try:
        from shared.config import AUTH_COOKIE_SECURE
    except ImportError:
        AUTH_COOKIE_SECURE = False
    resp = _unauthorized(detail)
    resp.set_cookie(
        key=LOGOUT_REASON_COOKIE,
        value=reason,
        max_age=120,
        path="/",
        secure=bool(AUTH_COOKIE_SECURE),
        httponly=False,
        samesite="lax",
    )
    return resp


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT auth middleware.

    Attaches to request.state:
            .identity  (IdentityContext | None)
      .user_id   (str | None)
      .email     (str | None)
      .role      (str | None)
      .tenant_id (str | None)
      .groups    (list[str])
      .auth_ok   (bool)
    """

    async def dispatch(self, request: Request, call_next):
        # Always stamp defaults
        request.state.identity = None
        request.state.user_id = None
        request.state.email   = None
        request.state.role    = None
        request.state.roles = []
        request.state.tenant_id = None
        request.state.groups = []
        request.state.scopes = []
        request.state.allowed_tenants = []
        request.state.auth_provider = None
        request.state.auth_method = None
        request.state.is_service_principal = False
        request.state.auth_ok = False

        nonce = generate_nonce()
        request.state.csp_nonce = nonce

        # Path with any ROOT_PATH sub-path prefix removed, so the public-route
        # allowlist and security-header logic stay prefix-agnostic.
        route_path = _route_path(request)

        # Check master switch
        try:
            from shared.config import AUTH_ENABLED
        except ImportError:
            AUTH_ENABLED = False

        if not AUTH_ENABLED:
            # Auth disabled — pass all requests through
            try:
                from shared.config import TENANT_ID
                tenant_id = TENANT_ID
            except Exception:
                tenant_id = "company"
            try:
                from auth.identity import apply_identity_to_state, create_dev_identity
                apply_identity_to_state(request.state, create_dev_identity(tenant_id))
            except Exception:
                request.state.auth_ok = True
                request.state.role = "admin"  # dev convenience
                request.state.roles = ["admin"]
                request.state.tenant_id = tenant_id
                request.state.allowed_tenants = [tenant_id]
            response = await call_next(request)
            _add_security_headers(response, route_path, nonce)
            return response

        # Public routes bypass token check
        if _is_public(route_path):
            response = await call_next(request)
            _add_security_headers(response, route_path, nonce)
            return response

        # Extract token
        token = _extract_token(request)
        if not token:
            return _unauthorized("Missing or invalid Authorization header.")

        # Validate token, reject revoked / superseded sessions, and complete the
        # identity from the user store (the browser token carries only sub/sid).
        try:
            from auth.identity import apply_identity_to_state
            identity, user = await authenticate_access_token(
                token,
                enforce_session_gate=route_path not in _SESSION_GATE_EXEMPT_EXACT,
            )
            apply_identity_to_state(request.state, identity)
            if user is not None:
                # Share the record with the password / SSO / disabled gates below
                # so the request still costs one store read.
                request.state._user_record = user
                request.state._user_record_loaded = True
        except TokenRevokedError:
            return _unauthorized("Token has been revoked.")
        except SessionRevokedError:
            logger.info("Session gate: revoked session rejected path=%s", route_path)
            return session_revoked_response()
        except SessionSupersededError:
            logger.info("Single-session gate: superseded session rejected path=%s", route_path)
            return session_superseded_response()
        except IdentityStoreUnavailableError as exc:
            logger.warning("Identity store unavailable during token validation: %s", exc)
            resp = JSONResponse(status_code=503, content={"detail": "Identity service unavailable. Please retry."})
            resp.headers["Retry-After"] = "5"
            _add_security_headers(resp, route_path)
            return resp
        except Exception as exc:
            logger.warning("Token validation failed: %s", exc)
            return _unauthorized("Invalid or expired token.")

        sso_gated = await _sso_session_gate(request, route_path)
        if sso_gated is not None:
            _add_security_headers(sso_gated, route_path)
            return sso_gated

        # Global per-tenant API rate limit (Redis-shared across instances; fail-open).
        limited = await _tenant_rate_limited(request)
        if limited is not None:
            return limited

        # Data Privacy acknowledgement gate (opt-in; fail-open). Blocks protected
        # API calls for authenticated users who have not accepted the current
        # privacy notice version. No-op unless PRIVACY_ACK_REQUIRED is enabled.
        gated = _privacy_ack_gate(request, route_path)
        if gated is not None:
            _add_security_headers(gated, route_path)
            return gated

        # Temporary-password gate. Blocks application traffic for a user whose
        # current password was issued by an administrator and not yet replaced.
        pw_gated = await _password_change_gate(request, route_path)
        if pw_gated is not None:
            _add_security_headers(pw_gated, route_path)
            return pw_gated

        disabled_gated = await _disabled_account_gate(request, route_path)
        if disabled_gated is not None:
            return disabled_gated

        response = await call_next(request)
        _add_security_headers(response, route_path, nonce)
        return response


# ---------------------------------------------------------------------------
# Temporary-password gate
# ---------------------------------------------------------------------------
# An administrator who creates a user, or resets someone's password, chooses
# that password on the owner's behalf. The UI calls it a "Temporary Password",
# and this gate is what makes that true: the account authenticates, but cannot
# be used for ordinary work until the owner replaces the credential.
#
# Only `/api/*` and `/auth/*` are gated, and the `/auth` routes a user needs in
# order to *resolve* the condition are allowlisted below. Everything else under
# `/auth` — notably the `/auth/users*` administration surface — is blocked, so an
# administrator holding a credential someone else chose for them cannot create
# accounts, change roles or reset other people's passwords until they rotate.

PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"

# Paths that must stay reachable while a rotation is outstanding: read the
# rules, identify yourself, rotate, refresh, and leave. Never lock the user out.
_PASSWORD_GATE_EXEMPT_EXACT = {
    "/auth/me",
    "/auth/me/password",
    "/auth/policy",
    "/auth/logout",
    "/auth/logout-all",
    "/auth/refresh",
    "/auth/version",
    "/auth/registration-mode",
    "/auth/oauth/logout",
    "/auth/oauth/refresh",
    "/auth/privacy/notice",
    "/auth/privacy/status",
    "/auth/privacy/accept",
}


def _password_gate_required(path: str) -> bool:
    """True when this route should be subject to the temporary-password gate."""
    if _is_public(path):
        return False
    if path in _PASSWORD_GATE_EXEMPT_EXACT:
        return False
    return path.startswith("/api/") or path.startswith("/auth/")


def _password_change_forbidden(path: str) -> JSONResponse:
    resp = JSONResponse(
        status_code=403,
        content={
            "detail": PASSWORD_CHANGE_REQUIRED,
            "message": "Your temporary password must be changed before continuing.",
        },
    )
    _add_security_headers(resp, path)
    return resp


# Sentinel: distinguishes "caller did not pass a preloaded user" from "user is
# None" (a genuine not-found / store-error result that must still fail-open).
_USER_UNSET = object()


async def password_rotation_outstanding(user_id: str, *, user: Any = _USER_UNSET) -> bool:
    """True when this user still owes a password rotation.

    Shared by the HTTP gate below and by the WebSocket handlers. WebSocket
    upgrades never traverse ``BaseHTTPMiddleware``, so a socket has to ask this
    question explicitly rather than relying on the gate having run.

    ``user`` lets the HTTP gate pass the request-scoped record it already loaded
    so this does NOT issue a second ``get_by_id`` — the password and disabled
    gates then share ONE user read per request (perf: PERF_NAVIGATION_INVESTIGATION
    Evidence 7). WebSocket callers omit it and the record is fetched on demand.

    Fail-open on lookup errors, matching the privacy gate: the credential itself
    was verified at login, so what is enforced here is rotation, not
    authentication, and failing closed would take the API down on a store
    hiccup.
    """
    if not user_id:
        return False
    if user is _USER_UNSET:
        try:
            from auth.factory import get_store
            store = await get_store()
            user = await store.get_by_id(user_id)
        except Exception as exc:
            logger.debug("password-rotation check skipped: %s", exc)
            return False
    return bool(user is not None and getattr(user, "must_change_password", False))


async def _load_request_user(request: Request, user_id: str):
    """Fetch the caller's user record ONCE per request and memoize on request.state.

    The password-rotation and disabled-account HTTP gates both need the same
    record. Previously each did its own uncached ``store.get_by_id`` — two Redis
    ``hgetall``s on every ``/api/*`` request, multiplied by the ~5 parallel fetches
    a single navigation fires and again by every open tab (see
    docs/PERF_NAVIGATION_INVESTIGATION.md, Evidence 7). The cache lives on
    ``request.state`` so it spans exactly one request: no cross-request staleness,
    so a just-disabled / just-rotated account is still cut off on its very next
    request.

    Only a *successful* (or genuine not-found) lookup is memoized. A store ERROR is
    NOT cached: it returns ``None`` (fail-open, matching the gates) but leaves the
    slot unloaded so the SECOND gate re-attempts the read. Otherwise a transient
    blip during the password gate's lookup would memoize ``None`` and let the
    disabled-account gate skip its own retry — slipping a disabled user through.
    """
    if getattr(request.state, "_user_record_loaded", False):
        return getattr(request.state, "_user_record", None)
    try:
        from auth.factory import get_store
        store = await get_store()
        user = await store.get_by_id(user_id)
    except Exception as exc:
        # Do NOT memoize a failure — let the next gate retry the store.
        logger.debug("request user load skipped (not memoized): %s", exc)
        return None
    request.state._user_record = user
    request.state._user_record_loaded = True
    return user


async def _password_change_gate(request: Request, route_path: str) -> Optional[JSONResponse]:
    """Return a 403 while the caller still owes a password change."""
    if not _password_gate_required(route_path):
        return None
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None
    # Machine identities have no interactive password to rotate.
    if getattr(request.state, "is_service_principal", False):
        return None
    user = await _load_request_user(request, user_id)
    if await password_rotation_outstanding(user_id, user=user):
        return _password_change_forbidden(route_path)
    return None


ACCOUNT_DISABLED = "ACCOUNT_DISABLED"

_DISABLED_GATE_EXEMPT_EXACT = {
    "/auth/me",
    "/auth/logout",
    "/auth/logout-all",
    "/auth/refresh",
    "/auth/version",
    "/auth/oauth/logout",
    "/auth/oauth/refresh",
}


def _disabled_gate_required(path: str) -> bool:
    if _is_public(path):
        return False
    if path in _DISABLED_GATE_EXEMPT_EXACT:
        return False
    return path.startswith("/api/") or path.startswith("/auth/")


def _disabled_account_forbidden(path: str) -> JSONResponse:
    resp = JSONResponse(
        status_code=401,
        content={
            "detail": ACCOUNT_DISABLED,
            "message": "Account is disabled. Contact your administrator.",
        },
    )
    _add_security_headers(resp, path)
    return resp


async def account_is_disabled(user_id: str, *, user: Any = _USER_UNSET) -> bool:
    """True when the account has been disabled by an administrator.

    ``user`` lets the HTTP gate pass the request-scoped record it already loaded
    (shared with the password gate) so this issues no extra ``get_by_id``.
    WebSocket callers omit it and the record is fetched on demand.
    """
    if not user_id:
        return False
    if user is _USER_UNSET:
        try:
            from auth.factory import get_store
            store = await get_store()
            user = await store.get_by_id(user_id)
        except Exception as exc:
            logger.debug("disabled-account check skipped: %s", exc)
            return False
    return bool(user is not None and getattr(user, "status", "") == "disabled")


_SSO_GATE_EXEMPT_EXACT = {
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/auth/logout",
    "/auth/logout-all",
    "/auth/me",
    "/auth/oauth/login",
    "/auth/oauth/status",
    "/auth/oauth/logout",
    "/auth/oauth/refresh",
    "/auth/callback",
    "/auth/version",
    "/auth/policy",
    "/auth/registration-mode",
}


def _sso_gate_required(path: str) -> bool:
    if _is_public(path):
        return False
    if path in _SSO_GATE_EXEMPT_EXACT:
        return False
    return path.startswith("/api/") or path.startswith("/auth/")


def _sso_session_forbidden(path: str, detail: str) -> JSONResponse:
    resp = JSONResponse(
        status_code=401,
        content={
            "detail": detail,
            "message": "Your SSO session has expired. Please sign in again.",
        },
    )
    _add_security_headers(resp, path)
    return resp


async def _sso_session_gate(request: Request, route_path: str) -> Optional[JSONResponse]:
    """Enforce Keycloak session bounds for SSO users (online re-validate / offline TTL)."""
    if not _sso_gate_required(route_path):
        return None
    user_id = getattr(request.state, "user_id", None)
    if not user_id or getattr(request.state, "is_service_principal", False):
        return None
    user = await _load_request_user(request, user_id)
    provider = getattr(user, "provider", "local") if user is not None else "local"
    try:
        from auth.sso_session import SESSION_EXPIRED, enforce_sso_session
        reason = await enforce_sso_session(user_id, provider=provider)
    except Exception as exc:
        logger.debug("SSO session gate skipped: %s", exc)
        return None
    if reason:
        logger.info("SSO session gate: blocking user=%s path=%s reason=%s", user_id, route_path, reason)
        return _sso_session_forbidden(route_path, reason)
    return None


async def _disabled_account_gate(request: Request, route_path: str) -> Optional[JSONResponse]:
    if not _disabled_gate_required(route_path):
        return None
    user_id = getattr(request.state, "user_id", None)
    if not user_id or getattr(request.state, "is_service_principal", False):
        return None
    user = await _load_request_user(request, user_id)
    if await account_is_disabled(user_id, user=user):
        return _disabled_account_forbidden(route_path)
    return None


# ---------------------------------------------------------------------------
# Data Privacy acknowledgement gate (PIA controls 1 & 3)
# ---------------------------------------------------------------------------
# Paths that must stay reachable while a user is un-acknowledged so they can
# read the notice, accept it, inspect themselves, and log out (never lock out).
_PRIVACY_GATE_EXEMPT_EXACT = {
    "/auth/privacy/notice",
    "/auth/privacy/status",
    "/auth/privacy/accept",
    "/auth/me",
    "/auth/logout",
    "/auth/refresh",
    "/auth/oauth/logout",
    "/auth/oauth/refresh",
}


def _privacy_gate_required(path: str) -> bool:
    """True when this route should be subject to the privacy-ack gate."""
    if _is_public(path):
        return False
    if path in _PRIVACY_GATE_EXEMPT_EXACT:
        return False
    # Only gate application/API traffic; leave auth + static handling alone.
    return path.startswith("/api/")


def _privacy_forbidden(path: str) -> JSONResponse:
    resp = JSONResponse(
        status_code=403,
        content={
            "detail": "PRIVACY_ACK_REQUIRED",
            "message": "You must accept the current data privacy notice before continuing.",
        },
    )
    _add_security_headers(resp, path)
    return resp


def _privacy_ack_gate(request: Request, route_path: str) -> Optional[JSONResponse]:
    """Return a 403 if the authenticated user has not accepted the current notice.

    Fully opt-in (PRIVACY_ACK_REQUIRED) and fail-open: any import/lookup error
    allows the request through so a privacy-store hiccup never takes down the API
    or locks admins out."""
    try:
        from shared.config import PRIVACY_ACK_REQUIRED
    except Exception:
        return None
    if not PRIVACY_ACK_REQUIRED:
        return None
    if not _privacy_gate_required(route_path):
        return None
    try:
        from privacy import service as privacy_service
        role = getattr(request.state, "role", None)
        if privacy_service.is_exempt_role(role):
            return None
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return None  # unauthenticated flows are handled by the token check above
        tenant_id = getattr(request.state, "tenant_id", None)
        if privacy_service.has_accepted(str(user_id), tenant_id):
            return None
        logger.info("privacy gate: blocking un-acknowledged user=%s path=%s", user_id, route_path)
        return _privacy_forbidden(route_path)
    except Exception as exc:  # never break the API on a gate/store error
        logger.debug("privacy gate check errored (allowing): %s", exc)
        return None


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer = auth_header[7:].strip()
        if bearer:  # only use non-empty bearer tokens; empty falls through to cookie
            return bearer
    # SEC-6: fallback to httponly cookie set by server on login/refresh
    cookie_token = request.cookies.get("iaf_access_token")
    if cookie_token:
        return cookie_token
    return None


def _unauthorized(detail: str) -> JSONResponse:
    resp = JSONResponse(status_code=401, content={"detail": detail})
    _add_security_headers(resp)
    return resp


def _too_many_requests(path: str = "") -> JSONResponse:
    resp = JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded for your organization. Please retry shortly."},
    )
    resp.headers["Retry-After"] = "60"
    _add_security_headers(resp, path)
    return resp


async def _tenant_rate_limited(request: Request) -> Optional[JSONResponse]:
    """Enforce the global per-tenant API rate limit. Returns a 429 response if the tenant is
    over its limit, else None. Fail-open: never blocks a request on a limiter/Redis error."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        return None  # no tenant on the request → nothing to key on
    try:
        from auth.rate_limiter import is_tenant_allowed
        allowed, _ = await is_tenant_allowed(str(tenant_id))
    except Exception as exc:  # never take the API down on a limiter hiccup
        logger.debug("tenant rate-limit check errored (allowing): %s", exc)
        return None
    if not allowed:
        logger.warning("Tenant rate limit exceeded: tenant=%s path=%s", tenant_id, request.url.path)
        return _too_many_requests(request.url.path)
    return None


# ---------------------------------------------------------------------------
# Dependency — use in individual route handlers for role enforcement
# ---------------------------------------------------------------------------

from fastapi import HTTPException


def require_auth(request: Request) -> dict:
    """FastAPI dependency: raises 401 if not authenticated."""
    try:
        from shared.config import AUTH_ENABLED
    except ImportError:
        AUTH_ENABLED = False

    if not AUTH_ENABLED:
        return {
            "user_id": "dev",
            "email": "dev@local",
            "role": "admin",
            "roles": ["admin"],
            "tenant_id": getattr(request.state, "tenant_id", None),
            "groups": getattr(request.state, "groups", []),
            "scopes": getattr(request.state, "scopes", []),
            "allowed_tenants": getattr(request.state, "allowed_tenants", []),
        }

    if not getattr(request.state, "auth_ok", False):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return {
        "user_id": request.state.user_id,
        "email":   request.state.email,
        "role":    request.state.role,
        "roles": getattr(request.state, "roles", []),
        "tenant_id": getattr(request.state, "tenant_id", None),
        "groups": getattr(request.state, "groups", []),
        "scopes": getattr(request.state, "scopes", []),
        "allowed_tenants": getattr(request.state, "allowed_tenants", []),
    }


def require_admin(request: Request) -> dict:
    """FastAPI dependency: raises 403 if not admin role."""
    user = require_auth(request)
    try:
        from shared.config import AUTH_ENABLED
    except ImportError:
        AUTH_ENABLED = False
    if AUTH_ENABLED and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return user


def require_permission(permission: str):
    """FastAPI dependency factory: raises 403 unless the user's role grants ``permission``.

    Permissions are projected from the tenant's roles.yaml (see security.roles).
    Admin holds the ``*`` wildcard, so admins pass every check. When auth is
    disabled every caller is treated as fully privileged (mirrors require_admin).
    """
    def _dependency(request: Request) -> dict:
        user = require_auth(request)
        try:
            from shared.config import AUTH_ENABLED
        except ImportError:
            AUTH_ENABLED = False
        if not AUTH_ENABLED:
            return user
        from security.roles import effective_permissions
        # Evaluate the permission against the tenant the request targets (a ?tenant_id
        # query wins), not just the token's home tenant — otherwise an identity granted
        # a permission only in the requested tenant is wrongly rejected. The route's own
        # bind_request_identity still enforces the allowed-tenants list afterwards.
        try:
            requested_tenant = request.query_params.get("tenant_id")
        except Exception:
            requested_tenant = None
        tenant_id = requested_tenant or getattr(request.state, "tenant_id", None) or "company"
        groups = user.get("groups") or []
        # Union permissions across every assigned role, not just the primary one:
        # an identity with roles=["user","developer"] must receive the developer grant.
        roles = user.get("roles") or [user.get("role")]
        perms = {
            granted
            for role in roles
            for granted in effective_permissions(role, groups, tenant_id)
        }
        if permission not in perms:
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' required.",
            )
        return user

    return _dependency

