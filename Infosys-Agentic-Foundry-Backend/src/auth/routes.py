from fastapi import APIRouter, Body, Depends, Request, HTTPException, status, Query, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from src.auth.models import (
    User, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, SuperAdminRegisterRequest,
    UpdatePasswordRequest, GrantApprovalPermissionRequest, ApprovalPermissionResponse,
    RevokeApprovalPermissionRequest, UserRole, Permission, RefreshTokenRequest, RefreshTokenResponse,
    OAuthLoginInitResponse, OAuthCallbackRequest, OAuthCallbackResponse, OAuthLogoutResponse,
    RoleListResponse, AssignRoleDepartmentRequest, AssignRoleDepartmentResponse, UpdateUserRoleRequest,
    RemoveRoleDepartmentRequest, RemoveRoleDepartmentResponse,
    SetUserActiveStatusRequest, UserActiveStatusResponse,
    AdminResetPasswordRequest, AdminResetPasswordResponse, ChangePasswordRequest, ChangePasswordResponse,
    RegistrationApproveRequest, RegistrationRejectRequest, RegistrationRequestResponse,
    DepartmentAccessRequest, GetUserDepartmentsResponse, SwitchDepartmentRequest, SwitchDepartmentResponse,
    SwitchRoleRequest, SwitchRoleResponse,
    UserDepartmentInfo, ExchangeCodeRequest, ExchangeCodeResponse,
    SSORegisterRequest, SSORegisterResponse
)
from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.auth.dependencies import (
    get_auth_service, get_authorization_service, get_current_user,
    require_role, require_permission, get_client_ip, get_user_agent
)
from src.api.dependencies import ServiceProvider
from src.database.services import RoleAccessService
from src.config.settings import (
    FRONTEND_REDIRECT_URI, ALLOWED_FRONTEND_URLS, SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, KEYCLOAK_ALLOW_DIRECT_LOGIN,
    OAUTH_TOKEN_DELIVERY_METHOD, ACCESS_TOKEN_EXPIRE_SECONDS, KEYCLOAK_ENABLED,
    AZURE_AD_ENABLED
)
from telemetry_wrapper import logger as log
from typing import Optional, List, Dict
from collections import defaultdict
from urllib.parse import urlencode




router = APIRouter(tags=["Authentication"], prefix="/auth")


# ==================== Secure Token Delivery Helpers ====================

def _generate_post_form_response(callback_response: OAuthCallbackResponse, redirect_url: str) -> HTMLResponse:
    """
    Generate HTML with auto-submitting POST form to securely deliver tokens.

    This is the MOST SECURE method for SPAs because:
    - Tokens sent in POST body (not visible in URL)
    - No browser history/logs
    - No referer leakage
    - Works cross-domain
    """
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Redirecting...</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f5f5f5;
            }}
            .loader {{
                text-align: center;
            }}
            .spinner {{
                border: 4px solid #f3f3f3;
                border-top: 4px solid #3498db;
                border-radius: 50%;
                width: 40px;
                height: 40px;
                animation: spin 1s linear infinite;
                margin: 0 auto 20px;
            }}
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
        </style>
    </head>
    <body>
        <div class="loader">
            <div class="spinner"></div>
            <p>Authentication successful. Redirecting...</p>
        </div>
        <form id="tokenForm" method="POST" action="{redirect_url}">
            <input type="hidden" name="token" value="{callback_response.token or ''}" />
            <input type="hidden" name="refresh_token" value="{callback_response.refresh_token or ''}" />
            <input type="hidden" name="id_token" value="{callback_response.id_token or ''}" />
            <input type="hidden" name="email" value="{callback_response.email or ''}" />
            <input type="hidden" name="username" value="{callback_response.username or ''}" />
            <input type="hidden" name="role" value="{callback_response.role or ''}" />
            <input type="hidden" name="department_name" value="{callback_response.department_name or ''}" />
            <input type="hidden" name="expires_in" value="{callback_response.expires_in or ACCESS_TOKEN_EXPIRE_SECONDS}" />
        </form>
        <script>
            // Auto-submit form immediately
            document.getElementById('tokenForm').submit();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


def _set_token_cookies(response: Response, callback_response: OAuthCallbackResponse):
    """
    Set tokens in HTTP-Only cookies (MOST SECURE for same-domain deployments).

    Security features:
    - HTTP-Only: JavaScript cannot access (XSS protection)
    - Secure: Only sent over HTTPS (production)
    - SameSite: CSRF protection
    """
    cookie_max_age = callback_response.expires_in or ACCESS_TOKEN_EXPIRE_SECONDS

    # Set access token cookie
    if callback_response.token:
        response.set_cookie(
            key="access_token",
            value=callback_response.token,
            max_age=cookie_max_age,
            httponly=SESSION_COOKIE_HTTPONLY,  # Prevent JavaScript access
            secure=SESSION_COOKIE_SECURE,      # HTTPS only in production
            samesite=SESSION_COOKIE_SAMESITE   # CSRF protection
        )

    # Set refresh token cookie (longer expiry)
    if callback_response.refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=callback_response.refresh_token,
            max_age=86400 * 14,  # 14 days
            httponly=True,       # Always HTTP-Only for refresh tokens
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE
        )

    # Set ID token cookie
    if callback_response.id_token:
        response.set_cookie(
            key="id_token",
            value=callback_response.id_token,
            max_age=cookie_max_age,
            httponly=SESSION_COOKIE_HTTPONLY,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE
        )

    # Set user info in non-HTTP-Only cookies (safe to expose)
    if callback_response.email:
        response.set_cookie(
            key="user_email",
            value=callback_response.email,
            max_age=cookie_max_age,
            httponly=False,  # Frontend needs to read this
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE
        )

    if callback_response.role:
        response.set_cookie(
            key="user_role",
            value=callback_response.role,
            max_age=cookie_max_age,
            httponly=False,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Direct login endpoint (username/pwd).
    
    ⚠️ WARNING: This endpoint does NOT support MFA/OTP.
    If MFA is enabled in Keycloak, use the OAuth flow endpoints instead:
    - GET /auth/oauth/login - Start OAuth login
    - GET /auth/callback - OAuth callback handler
    
    This endpoint can be disabled by setting KEYCLOAK_ALLOW_DIRECT_LOGIN=false
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    login_response = await auth_service.login(login_data, ip_address, user_agent)
    # Return response directly; caller handles refresh token storage (no cookies set server-side)
    return login_response


# ==================== OAuth Authorization Code Flow Routes (MFA Compatible) ====================

@router.get("/oauth/login", response_model=OAuthLoginInitResponse)
async def oauth_login_init(
    request: Request,
    role: str = Query(None, description="Requested role (will be validated after login)"),
    redirect_uri: str = Query(None, description="Custom redirect URI (optional)"),
    frontend_origin: str = Query(None, description="The origin URL of the UI initiating login (for multi-UI support, e.g. http://localhost:4000)"),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Initialize OAuth Authorization Code Flow with PKCE.
    
    This is the MFA-compatible login endpoint. It returns a URL that the client
    should redirect to for Keycloak authentication. Keycloak will handle:
    - Username/pwd entry
    - MFA/OTP enrollment (first time if required)
    - MFA/OTP prompt on subsequent logins
    
    Flow:
    1. Client calls this endpoint (pass `frontend_origin` to support multiple UIs)
    2. Client redirects user to the returned redirect_url
    3. User authenticates on Keycloak (including MFA)
    4. Keycloak redirects to /auth/callback with authorization code
    5. Backend exchanges code for tokens and redirects browser back to the originating UI
    
    Returns:
        OAuthLoginInitResponse with:
        - redirect_url: URL to redirect the user to for Keycloak login
        - state: CSRF protection token (frontend should verify this in callback)
    """
    # Guard: SSO is only available when Keycloak is enabled
    if not KEYCLOAK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO / OAuth login is disabled. Set KEYCLOAK_ENABLED=true in your .env to enable it."
        )
    # Validate frontend_origin against allowlist to prevent open-redirect attacks
    if frontend_origin is not None:
        if frontend_origin not in ALLOWED_FRONTEND_URLS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"frontend_origin '{frontend_origin}' is not in the list of allowed frontend URLs. "
                       f"Add it to ALLOWED_FRONTEND_URLS in your .env file."
            )
    log.info(f"OAuth login init requested with role: {role}, frontend_origin: {frontend_origin}")
    return auth_service.init_oauth_login(requested_role=role, custom_redirect_uri=redirect_uri, frontend_origin=frontend_origin)


@router.get("/callback")
async def oauth_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Authorization code from Keycloak"),
    state: str = Query(..., description="State parameter for CSRF validation"),
    session_state: str = Query(None, description="Keycloak session state"),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Handle OAuth callback from Keycloak after user completes authentication.

    This endpoint is called by Keycloak after the user successfully authenticates
    (including completing MFA if enabled). It exchanges the authorization code
    for access/refresh tokens and securely delivers them to the frontend.

    Security: Token delivery method configured via OAUTH_TOKEN_DELIVERY_METHOD:
    - "post" (recommended): Auto-submit POST form - tokens in body, not URL
    - "cookie": HTTP-Only cookies - most secure for same-domain
    - "fragment": URL fragment - legacy method, not recommended

    Query Parameters:
        code: Authorization code from Keycloak
        state: State parameter (must match the one from /oauth/login)
        session_state: Optional Keycloak session identifier

    Returns:
        - Browser (text/html): Secure token delivery based on config
        - API clients: JSON response with tokens
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    try:
        callback_response = await auth_service.handle_oauth_callback(
            code=code,
            state=state,
            ip_address=ip_address,
            user_agent=user_agent
        )
    except Exception as e:
        log.exception(f"Unexpected error in handle_oauth_callback: {e}")
        return RedirectResponse(url=f"{FRONTEND_REDIRECT_URI or ''}/auth/callback?success=false&error=Authentication+error")

    # Check if this is a browser request that expects a redirect
    accept_header = request.headers.get("Accept", "")
    is_browser = "text/html" in accept_header

    # Resolve which frontend to redirect to: use the UI that initiated the login,
    # or fall back to the default FRONTEND_REDIRECT_URI for backwards compatibility.
    _origin = callback_response.frontend_origin
    if _origin and _origin in ALLOWED_FRONTEND_URLS:
        _frontend_base = _origin
    else:
        _frontend_base = FRONTEND_REDIRECT_URI or ""

    # Handle error cases
    if is_browser and not callback_response.approval:
        error_msg = urlencode({"error": callback_response.message or "Authentication failed"})
        redirect_url = f"{_frontend_base}/auth/callback?success=false&{error_msg}"
        return RedirectResponse(url=redirect_url)

    # JIT Provisioning: Check if this is a new SSO user that needs admin approval
    if callback_response.approval and callback_response.email:
        try:
            jit_result = await auth_service.handle_sso_user_jit_provisioning(
                email=callback_response.email,
                username=callback_response.username or callback_response.email,
                ip_address=ip_address,
                user_agent=user_agent
            )
        except Exception as e:
            log.exception(f"Unexpected error in JIT provisioning for {callback_response.email}: {e}")
            if is_browser:
                return RedirectResponse(url=f"{_frontend_base}/auth/callback?success=false&error=Provisioning+error")
            callback_response.approval = False
            callback_response.message = "An error occurred during user provisioning"
            return callback_response

        if jit_result.get("status") == "NEEDS_DEPARTMENT_SELECTION":
            # Brand-new SSO user - redirect to department selection page
            log.info(f"New SSO user {callback_response.email} redirected to department selection")
            if is_browser:
                try:
                    _email_val = str(callback_response.email or "")
                    _user_val = str(jit_result.get("username") or callback_response.email or "")
                    _encoded = urlencode({"email": _email_val, "username": _user_val})
                    redirect_url = f"{_frontend_base}/select-department?{_encoded}"
                    return RedirectResponse(url=redirect_url)
                except BaseException as _redir_exc:
                    _is_base = not isinstance(_redir_exc, Exception)
                    log.exception(
                        f"{'BASE' if _is_base else ''}EXCEPTION in dept-selection redirect "
                        f"(type={type(_redir_exc).__name__}, is_base_only={_is_base}, "
                        f"frontend_base={_frontend_base!r}, "
                        f"email={callback_response.email!r}, "
                        f"username_from_jit={jit_result.get('username')!r}): {_redir_exc}"
                    )
                    if _is_base:
                        raise  # let CancelledError / BaseExceptionGroup propagate
                    return RedirectResponse(
                        url=f"{_frontend_base or FRONTEND_REDIRECT_URI or ''}"
                            f"/auth/callback?success=false&error=Internal+error"
                    )
            else:
                callback_response.approval = False
                callback_response.status = "NEEDS_DEPARTMENT_SELECTION"
                callback_response.message = jit_result.get("message", "Please select your department")
                callback_response.token = None
                callback_response.refresh_token = None
                callback_response.id_token = None
                return callback_response

        if jit_result.get("status") == "PENDING_APPROVAL":
            # Already submitted department selection, waiting for admin approval
            log.info(f"SSO user {callback_response.email} already pending approval")

            if is_browser:
                redirect_url = (
                    f"{_frontend_base}/pending-approval?"
                    + urlencode({
                        "email": callback_response.email or "",
                        "username": callback_response.username or callback_response.email or "",
                    })
                )
                return RedirectResponse(url=redirect_url)
            else:
                callback_response.approval = False
                callback_response.status = "PENDING_APPROVAL"
                callback_response.message = jit_result.get("message", "Your account is awaiting administrator approval")
                callback_response.token = None
                callback_response.refresh_token = None
                callback_response.id_token = None
                return callback_response

        elif jit_result.get("status") == "ACCOUNT_DEACTIVATED":
            # Account or all department access has been deactivated by admin
            log.warning(f"Blocked SSO login for deactivated account: {callback_response.email}")
            if is_browser:
                redirect_url = (
                    f"{_frontend_base}/auth/callback?success=false&"
                    + urlencode({"error": jit_result.get("message", "Your account has been deactivated")})
                )
                return RedirectResponse(url=redirect_url)
            else:
                callback_response.approval = False
                callback_response.message = jit_result.get("message", "Your account has been deactivated")
                callback_response.token = None
                callback_response.refresh_token = None
                callback_response.id_token = None
                return callback_response

        elif jit_result.get("status") == "ERROR":
            # Error during JIT provisioning
            log.error(f"JIT provisioning error for {callback_response.email}: {jit_result.get('message')}")
            if is_browser:
                return RedirectResponse(url=f"{_frontend_base}/auth/callback?success=false&error=Provisioning+error")
            else:
                callback_response.approval = False
                callback_response.message = "An error occurred during user provisioning"
                return callback_response

        # If status is "USER_EXISTS", continue with normal flow

    # Handle successful authentication for browser
    if is_browser and callback_response.approval:
        redirect_url = f"{_frontend_base}/auth/callback"

        # Choose token delivery method based on configuration
        if OAUTH_TOKEN_DELIVERY_METHOD == "code":
            # MOST SECURE: One-time authorization code exchange
            # Generate and store one-time code in database
            auth_code = await auth_service.generate_and_store_authorization_code(
                access_token=callback_response.token,
                refresh_token=callback_response.refresh_token,
                id_token=callback_response.id_token,
                email=callback_response.email,
                username=callback_response.username,
                role=callback_response.role,
                department_name=callback_response.department_name,
                expires_in=callback_response.expires_in or ACCESS_TOKEN_EXPIRE_SECONDS,
                ip_address=ip_address,
                user_agent=user_agent
            )

            if auth_code:
                # Redirect with one-time code (NOT tokens!)
                return RedirectResponse(url=f"{redirect_url}?code={auth_code}")
            else:
                log.error("Failed to generate authorization code")
                return RedirectResponse(url=f"{redirect_url}?success=false&error=Failed to generate authorization code")

        elif OAUTH_TOKEN_DELIVERY_METHOD == "post":
            # SECURE (cross-domain): POST with auto-submit form
            return _generate_post_form_response(callback_response, redirect_url)

        elif OAUTH_TOKEN_DELIVERY_METHOD == "cookie":
            # SECURE (same-domain): HTTP-Only cookies
            _set_token_cookies(response, callback_response)
            return RedirectResponse(url=f"{redirect_url}?success=true")

        elif OAUTH_TOKEN_DELIVERY_METHOD == "fragment":
            # LEGACY METHOD (NOT RECOMMENDED): URL fragment
            log.warning("Using URL fragment for token delivery - NOT RECOMMENDED for production. "
                       "Set OAUTH_TOKEN_DELIVERY_METHOD=code for best security")
            redirect_params = {
                "success": "true",
                "token": callback_response.token or "",
                "refresh_token": callback_response.refresh_token or "",
                "id_token": callback_response.id_token or "",
                "email": callback_response.email or "",
                "role": callback_response.role or "",
                "username": callback_response.username or "",
                "department_name": callback_response.department_name or "",
                "expires_in": str(callback_response.expires_in or ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            return RedirectResponse(url=f"{redirect_url}#{urlencode(redirect_params)}")

    # API flow: return JSON response (same as /auth/login)
    return callback_response


@router.post("/callback", response_model=OAuthCallbackResponse)
async def oauth_callback_post(
    request: Request,
    callback_data: OAuthCallbackRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Handle OAuth callback via POST (for SPA flows).
    
    This is an alternative to the GET callback for SPAs that intercept the
    redirect and extract the code/state themselves.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    return await auth_service.handle_oauth_callback(
        code=callback_data.code,
        state=callback_data.state,
        ip_address=ip_address,
        user_agent=user_agent
    )


@router.post("/exchange-code", response_model=ExchangeCodeResponse)
async def exchange_authorization_code(
    request: Request,
    exchange_request: ExchangeCodeRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Exchange one-time authorization code for tokens.

    This is the MOST SECURE token delivery method for OAuth/SSO:

    Flow:
    1. User authenticates via SSO
    2. Backend generates one-time authorization code
    3. Backend redirects to: http://frontend/auth/callback?code=abc123xyz
    4. Frontend calls this endpoint to exchange code for tokens
    5. Backend returns tokens in JSON response body
    6. Code is marked as used (can only be used once)

    Security features:
    - Code expires after 60 seconds
    - Code can only be used once
    - Tokens never appear in URL
    - All exchanges logged in audit trail
    - Works in distributed/pods architecture (stored in PostgreSQL)

    Query Parameters:
        code: One-time authorization code from URL parameter

    Returns:
        ExchangeCodeResponse with JWT tokens and user info
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    result = await auth_service.exchange_authorization_code(
        code=exchange_request.code,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["approval"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return ExchangeCodeResponse(
        approval=True,
        token=result.get("token"),
        refresh_token=result.get("refresh_token"),
        id_token=result.get("id_token"),
        email=result.get("email"),
        username=result.get("username"),
        role=result.get("role"),
        department_name=result.get("department_name"),
        expires_in=result.get("expires_in"),
        message=result["message"]
    )


# ==================== SSO Self-Registration ====================

@router.post("/sso/register", response_model=SSORegisterResponse)
async def sso_register_with_departments(
    request: Request,
    register_request: SSORegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    New SSO user self-registration with department selection.

    Called after a brand-new SSO user is redirected to /select-department.
    The user picks their department(s) and submits this form. A pending
    registration request is created for each department; an admin must
    approve them before they can log in.

    This endpoint is intentionally public (no auth required) because the
    SSO user has no token yet.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    result = await auth_service.register_sso_user_with_departments(
        email=register_request.email,
        username=register_request.username,
        department_names=register_request.department_names,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return SSORegisterResponse(success=True, message=result["message"])


@router.get("/oauth/logout", response_model=OAuthLogoutResponse)
async def oauth_logout_url(
    request: Request,
    id_token: str = Query(None, description="ID token hint for Keycloak"),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get Keycloak logout URL for OAuth end-session.
    
    This returns the URL that the client should redirect to for a complete
    logout from Keycloak. This will:
    - End the Keycloak session (including SSO sessions)
    - Redirect back to the configured post-logout URI
    
    The client should:
    1. Call this endpoint to get the logout URL
    2. Clear local tokens/session
    3. Redirect user to the logout URL
    """
    # Also try to get id_token from cookie if not provided
    if not id_token:
        id_token = request.cookies.get("id_token")
    
    return auth_service.get_oauth_logout_url(id_token=id_token)


@router.post("/oauth/logout")
async def oauth_logout_action(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Perform logout and return Keycloak logout URL.
    
    This combines local session cleanup with Keycloak logout.
    Tokens should be passed in the Authorization header or request body.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    # Get tokens from Authorization header first, then fall back to cookies (for backward compatibility)
    auth_header = request.headers.get("Authorization", "")
    access_token = None
    if auth_header.startswith("Bearer "):
        access_token = auth_header[7:]
    
    # Try to get refresh_token and id_token from request body if it's JSON
    refresh_token = None
    id_token = None
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token")
        id_token = body.get("id_token")
    except:
        pass
    
    # Revoke tokens in Keycloak if we have them
    if access_token or refresh_token:
        await auth_service.logout(
            token=access_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    # requires_keycloak_redirect is True whenever Keycloak is enabled, because the
    # Keycloak browser session (SSO cookie) must be terminated via the end-session
    # redirect — regardless of whether an id_token was provided.
    # Without this redirect, clicking SSO login again after logout silently
    # re-authenticates the user using the still-active Keycloak session.
    requires_keycloak_redirect = KEYCLOAK_ENABLED

    if KEYCLOAK_ENABLED:
        logout_response = auth_service.get_oauth_logout_url(id_token=id_token)
        logout_url = logout_response.logout_url
    else:
        logout_url = None

    return {
        "success": True,
        "logout_url": logout_url,
        "requires_keycloak_redirect": requires_keycloak_redirect,
        "message": "Tokens revoked. Redirect to logout_url to complete Keycloak logout." if requires_keycloak_redirect else "Tokens revoked. Local session ended."
    }


@router.get("/oauth/status")
async def oauth_status():
    """
    Check OAuth/MFA configuration status.
    
    Returns information about the current authentication configuration.
    """
    return {
        "direct_login_enabled": KEYCLOAK_ALLOW_DIRECT_LOGIN,
        "oauth_flow_enabled": True,
        "mfa_supported": True,
        "message": "Use /auth/oauth/login for MFA-compatible authentication" if not KEYCLOAK_ALLOW_DIRECT_LOGIN 
                   else "Both direct login and OAuth flow are available. OAuth flow supports MFA."
    }


# ==================== End OAuth Routes ====================


# ==================== Azure AD / MSAL Pass-Through Status Check ====================

@router.get("/me")
async def get_azure_ad_user_status(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Status check for MSAL / Azure AD users (token pass-through — no exchange).

    The UI calls this endpoint immediately after acquiring an MSAL access token.
    The Azure AD token is validated via JWKS signature verification but is never
    stored or exchanged — the UI continues to use the same token for all apps.

    The backend checks the user's provisioning state in the database and returns
    a `status` field the UI uses for navigation:

    | status                      | UI action                              |
    |-----------------------------|----------------------------------------|
    | USER_EXISTS                 | Proceed to the app dashboard           |
    | NEEDS_DEPARTMENT_SELECTION  | Navigate to /select-department         |
    | PENDING_APPROVAL            | Navigate to /pending-approval          |
    | ACCOUNT_DEACTIVATED         | Show deactivated error, stay on login  |

    All state is persisted in the database — no pod-local memory is used.

    Authorization: Bearer <azure_ad_access_token>
    """
    if not AZURE_AD_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure AD is not enabled. Set AZURE_AD_ENABLED=true in your .env to enable it."
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or not a Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode Azure AD token payload — no signature validation performed
    claims = await auth_service.azure_ad_service.decode_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not decode Azure AD token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract identity claims — Azure AD uses upn/unique_name for corporate accounts
    email: Optional[str] = (
        claims.get("upn")
        or claims.get("unique_name")
        or claims.get("email")
        or claims.get("preferred_username")
    )
    if not email:
        log.warning("Azure AD token validated but missing upn/email claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure AD token is missing a required identity claim (upn/email)",
        )

    username: str = claims.get("name") or email
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    log.info(f"[/auth/me] Azure AD token accepted for {email}, running JIT provisioning check")

    # All state lives in DB — safe across multiple pods
    try:
        jit_result = await auth_service.handle_sso_user_jit_provisioning(
            email=email,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as exc:
        log.exception(f"[/auth/me] JIT provisioning error for {email}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while checking account status. Please try again.",
        )

    provisioning_status = jit_result.get("status")

    return {
        "email": email,
        "username": username,
        "status": provisioning_status,
        "message": jit_result.get("message", ""),
        # role and department_name are only populated when status == "USER_EXISTS";
        # they come from the DB — never hardcoded defaults.
        "role": jit_result.get("role"),
        "department_name": jit_result.get("department_name"),
    }


# ==================== End Azure AD / MSAL Pass-Through Status Check ====================


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Logout endpoint"""
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(" ", 1)[1]
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    refresh_token = request.cookies.get("refresh_token")

    # Try to read id_token from request body or cookie for SSO session termination
    id_token = None
    try:
        body = await request.json()
        id_token = body.get("id_token")
    except Exception:
        pass
    if not id_token:
        id_token = request.cookies.get("id_token")

    await auth_service.logout(token, refresh_token, ip_address, user_agent)

    # For SSO users the Keycloak browser session must also be terminated.
    # Return logout_url so the frontend can redirect to end the SSO session;
    # without this step, clicking SSO login again silently re-authenticates.
    if KEYCLOAK_ENABLED:
        logout_response = auth_service.get_oauth_logout_url(id_token=id_token)
        return {
            "message": "Logged out successfully",
            "logout_url": logout_response.logout_url,
            "requires_keycloak_redirect": True
        }

    return {"message": "Logged out successfully"}

@router.post("/register", response_model=RegisterResponse)
async def register(
    request: Request,
    register_data: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Register endpoint"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    # Try to get current user if request is authenticated
    current_user = None
    if hasattr(request.state, 'user'):
        current_user = request.state.user
    
    return await auth_service.register(register_data, ip_address, user_agent, current_user)


@router.post("/register-superadmin", response_model=RegisterResponse)
async def register_superadmin(
    request: Request,
    register_data: SuperAdminRegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Register a SuperAdmin user.
    This endpoint is only available when no SuperAdmin exists in the system.
    Use this to bootstrap the system or recover from a state with no SuperAdmin.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    return await auth_service.register_superadmin(register_data, ip_address, user_agent)


@router.post("/assign-role-department", response_model=AssignRoleDepartmentResponse)
async def assign_role_department(
    request: Request,
    assign_data: AssignRoleDepartmentRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Assign role and department to a registered user.
    Only SuperAdmin or department Admin can use this endpoint.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    # Only SuperAdmin and Admin can assign roles
    if current_user.role not in ["SuperAdmin", "Admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only SuperAdmin or Admin can assign roles and departments"
        )
    
    result = await auth_service.assign_role_department(
        email_id=assign_data.email_id,
        department_name=assign_data.department_name,
        role=assign_data.role,
        current_user=current_user,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return AssignRoleDepartmentResponse(
        success=result["success"],
        message=result["message"]
    )


@router.post("/remove-role-department", response_model=RemoveRoleDepartmentResponse)
async def remove_role_department(
    request: Request,
    remove_data: RemoveRoleDepartmentRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Remove a specific role from a user in a department.
    Only SuperAdmin or department Admin can use this endpoint.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    if current_user.role not in ["SuperAdmin", "Admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only SuperAdmin or Admin can remove roles from users"
        )

    result = await auth_service.remove_role_from_user_in_department(
        email_id=remove_data.email_id,
        department_name=remove_data.department_name,
        role=remove_data.role,
        current_user=current_user,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return RemoveRoleDepartmentResponse(
        success=result["success"],
        message=result["message"]
    )


@router.post("/promote-superadmin")
async def promote_to_superadmin(
    request: Request,
    target_email: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Promote an existing user to SuperAdmin. SuperAdmin only.
    The target user must already exist (have logged in at least once).
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    return await auth_service.promote_to_superadmin(
        target_email=target_email,
        current_user=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post("/depromote-superadmin")
async def depromote_from_superadmin(
    request: Request,
    target_email: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    depromote a SuperAdmin back to a regular user. SuperAdmin only.
    Users listed in the INITIAL_SUPERADMIN_EMAILS env variable cannot be depromoted.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    result = await auth_service.depromote_from_superadmin(
        target_email=target_email,
        current_user=current_user,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRATION REQUEST APPROVAL ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/request-department-access", response_model=RegisterResponse)
async def request_department_access(
    request: Request,
    access_data: DepartmentAccessRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Request access to additional departments. User must be logged in."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    return await auth_service.request_department_access(
        email_id=current_user.email,
        department_names=access_data.department_names,
        ip_address=ip_address,
        user_agent=user_agent
    )


@router.get("/my-requests", response_model=dict)
async def get_my_requests(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Get all department access requests for the logged-in user (pending, approved, rejected)."""
    result = await auth_service.get_my_requests(current_user.email)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to fetch requests"))
    return result


@router.get("/my-requests/search-paginated", response_model=dict)
async def search_paginated_my_requests(
    request: Request,
    search_value: Optional[str] = Query(None, description="Department name to search for (partial, case-insensitive match)"),
    page_number: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    status: Optional[str] = Query(None, description="Filter by request status: pending, approved, or rejected"),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get the logged-in user's department access requests with pagination and search.

    Args:
        search_value: Optional department name to search for (partial, case-insensitive match)
        page_number: Page number for pagination (starts from 1)
        page_size: Number of results per page
        status: Optional filter by request status (pending, approved, rejected)

    Returns:
        Paginated request results with pagination metadata
    """
    result = await auth_service.get_my_requests_paginated(
        email_id=current_user.email,
        search_value=search_value or '',
        page=page_number,
        limit=page_size,
        status=status
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to fetch requests"))
    return result


@router.get("/registration-requests", response_model=dict)
async def get_registration_requests(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get pending registration requests.
    Admin sees requests for their departments, SuperAdmin sees all.
    """
    if current_user.role not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Only SuperAdmin or Admin can view registration requests")

    result = await auth_service.get_pending_registrations(current_user)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to fetch requests"))
    return result


@router.api_route("/registration-requests/approve", methods=["PATCH", "POST"])
async def approve_registration_request(
    request: Request,
    approve_data: RegistrationApproveRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Approve one or more pending registration requests with a single role assignment.
    Admin can approve for their departments, SuperAdmin for any department.
    Accepts a list of request_ids and assigns the same role to all.
    """
    if current_user.role not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Only SuperAdmin or Admin can approve registrations")

    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    result = await auth_service.bulk_approve_registration(
        request_ids=approve_data.request_ids,
        role=approve_data.role,
        department_name_override=approve_data.department_name,
        current_user=current_user,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.api_route("/registration-requests/reject", methods=["PATCH", "POST"])
async def reject_registration_request(
    request: Request,
    reject_data: RegistrationRejectRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Reject one or more pending registration requests with an optional reason.
    Admin can reject for their departments, SuperAdmin for any department.
    Accepts a list of request_ids and applies the same rejection reason to all.
    """
    if current_user.role not in ["SuperAdmin", "Admin"]:
        raise HTTPException(status_code=403, detail="Only SuperAdmin or Admin can reject registrations")

    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    result = await auth_service.bulk_reject_registration(
        request_ids=reject_data.request_ids,
        current_user=current_user,
        rejection_reason=reject_data.rejection_reason,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/guest-login", response_model=LoginResponse)
async def guest_login(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Guest login endpoint that returns JWT."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    login_response = await auth_service.guest_login(ip_address, user_agent)
    return login_response


@router.post("/refresh-token", response_model=RefreshTokenResponse)
async def refresh_access_token(
    request: Request,
    payload: RefreshTokenRequest | None = None,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Use refresh token (from cookie or body) to obtain a new access token."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    provided = (payload.refresh_token if payload else None) or request.cookies.get("refresh_token")
    if not provided:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    return await auth_service.refresh_access_token(provided, ip_address, user_agent)


# ─────────────────────────────────────────────────────────────────────────────
# PWD MANAGEMENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/reset-password", response_model=AdminResetPasswordResponse)
async def admin_reset_password(
    request: Request,
    reset_data: AdminResetPasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Reset a user's PWD with a temporary PWD (SuperAdmin only).
    
    The user will be required to change their PWD on next login.
    
    **SuperAdmin Only** - Only SuperAdmin users can reset PWDs for other users.
    
    Flow:
    1. User forgets PWD and contacts SuperAdmin
    2. SuperAdmin uses this endpoint to set a temporary PWD
    3. SuperAdmin communicates temporary PWD to user
    4. User logs in with temporary PWD
    5. User is prompted to change PWD (must_change_password=True in login response)
    6. User changes PWD via /auth/change-pwd endpoint
    """
    # Only SuperAdmin can reset PWDs
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SuperAdmin can reset user passwords"
        )
    
    # Verify target user exists
    target_user = await auth_service.user_repo.get_user_basic_by_email(reset_data.email_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{reset_data.email_id}' not found"
        )
    
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    success = await auth_service.set_temporary_password(
        email=reset_data.email_id,
        temporary_password=reset_data.temporary_password,
        current_user_id=current_user.email,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if success:
        return AdminResetPasswordResponse(
            success=True,
            message=f"Temporary password set for user '{reset_data.email_id}'. User will be required to change password on next login.",
            email=reset_data.email_id,
            must_change_password=True
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set temporary password"
        )


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    request: Request,
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Change the current user's PWD after admin has reset it.
    
    This endpoint is ONLY available when must_change_password=True,
    which is set by SuperAdmin via /auth/reset-pwd endpoint.
    
    Requires:
    - Current PWD (temporary PWD set by admin) for verification
    - New PWD to set
    
    The must_change_password flag is cleared after successful PWD change.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    result = await auth_service.change_password(
        email=current_user.email,
        current_password=password_data.current_password,
        new_password=password_data.new_password,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if result["success"]:
        return ChangePasswordResponse(
            success=True,
            message=result["message"]
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )


# ==================== Department Switching Endpoints ====================

@router.get("/my-departments", response_model=GetUserDepartmentsResponse)
async def get_my_departments(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get all departments the current user has access to.

    The response includes:
    - department_name: Name of the department
    - role: User's role in that department
    - is_active: Whether user is active in that department
    - is_default: True for the most recently used department (default on next login)
    - last_used_at: Timestamp when department was last used

    The departments are ordered by most recently used first.
    """
    result = await auth_service.get_user_departments_with_default(current_user.email)

    if not result["approval"]:
        return GetUserDepartmentsResponse(
            approval=False,
            departments=[],
            message=result["message"]
        )

    # Convert dict departments to UserDepartmentInfo models
    departments = [
        UserDepartmentInfo(
            department_name=dept["department_name"],
            role=dept["role"],
            roles=dept.get("roles", [dept["role"]]),
            is_active=dept["is_active"],
            is_default=dept.get("is_default", False),
            created_at=dept.get("created_at"),
            last_used_at=dept.get("last_used_at")
        )
        for dept in result["departments"]
    ]

    return GetUserDepartmentsResponse(
        approval=True,
        departments=departments,
        message=result["message"]
    )


@router.post("/switch-department", response_model=SwitchDepartmentResponse)
async def switch_department(
    request: Request,
    switch_request: SwitchDepartmentRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Switch to a different department.

    This endpoint:
    1. Verifies user has access to the requested department
    2. Updates last_used_at timestamp (makes it the new default)
    3. Generates a new JWT with the new department context
    4. Returns new JWT token with the appropriate role for that department

    After switching, the new department will be used as the default on next login.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    result = await auth_service.switch_department(
        email=current_user.email,
        department_name=switch_request.department_name,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["approval"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return SwitchDepartmentResponse(
        approval=True,
        token=result.get("token"),
        refresh_token=result.get("refresh_token"),
        role=result.get("role"),
        department_name=result.get("department_name"),
        available_roles=result.get("available_roles"),
        message=result["message"]
    )


@router.post("/switch-role", response_model=SwitchRoleResponse)
async def switch_role(
    request: Request,
    switch_request: SwitchRoleRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Switch to a different role within a department.

    This endpoint:
    1. Verifies user has the requested role in the department
    2. Updates is_current flag in the database
    3. Generates a new JWT with the new role context
    4. Returns new JWT token with the new role

    If department_name is not provided, uses the current department from the JWT.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Use department from request or fall back to current JWT department
    department_name = switch_request.department_name or current_user.department_name

    result = await auth_service.switch_role(
        email=current_user.email,
        role=switch_request.role,
        department_name=department_name,
        ip_address=ip_address,
        user_agent=user_agent
    )

    if not result["approval"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )

    return SwitchRoleResponse(
        approval=True,
        token=result.get("token"),
        refresh_token=result.get("refresh_token"),
        role=result.get("role"),
        department_name=result.get("department_name"),
        available_roles=result.get("available_roles"),
        message=result["message"]
    )


@router.get("/users")
async def list_users(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Lists users scoped by the logged-in user's role and department:
      - SuperAdmin: all users (mapped + unassigned), department-wise counts, unassigned users list.
      - Admin: users in current_user.department_name only, role-wise counts.
      - Others: 403.
    """
    # Gate: only Admin and SuperAdmin
    if current_user.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin or SuperAdmin can list users"
        )

    try:
        # ---- SuperAdmin: show everything ----
        if current_user.role == "SuperAdmin":
            # Base users from login_credential
            all_users = await auth_service.user_repo.get_all_users()
            all_emails = {u["mail_id"] for u in all_users}

            # Enrich with dept-role mappings
            mappings = await auth_service.user_dept_mapping_repo.get_all_mappings()
            # mappings rows: {mail_id, department_name, role, created_at, created_by, user_name}

            # Build {email -> user summary} for ALL users (mapped + unassigned)
            by_email = {
                u["mail_id"]: {
                    "email": u["mail_id"],
                    "username": u["user_name"],
                    "departments": []  # will be filled for mapped users; stays [] for unassigned
                }
                for u in all_users
            }

            # Aggregate dept-wise unique users (ignore NULL department_name used in special cases)
            dept_user_set: dict[str, set[str]] = defaultdict(set)
            assigned_emails: set[str] = set()

            for m in mappings:
                email = m.get("mail_id")
                dept = m.get("department_name")
    
                # Fill department-role mapping into the user's summary
                if email in by_email:
                    by_email[email]["departments"].append({
                        "department_name": dept,
                        "role": m.get("role"),
                        "is_active": m.get("is_active", True) if m.get("is_active") is not None else True,
                        "added_at": m.get("created_at"),
                        "added_by": m.get("created_by"),
                    })
                # Count only real departments (non-NULL)
                if dept is not None:
                    dept_user_set[dept].add(email)
                    assigned_emails.add(email)

            # Compute counts
            superadmin_emails = {m["mail_id"] for m in mappings if m["role"] == "SuperAdmin"}
            
            # Remove SuperAdmin users from the output — they should not be visible in user lists
            for sa_email in superadmin_emails:
                by_email.pop(sa_email, None)
            
            department_counts = {dept: len(users - superadmin_emails) for dept, users in dept_user_set.items()}
            unassigned_emails = sorted(all_emails - assigned_emails - superadmin_emails)
            unassigned_count = len(unassigned_emails)

            # Build a simple list for unassigned users (email + username)
            unassigned_users = [
                {
                    "email": e,
                    "username": by_email[e]["username"],
                    "departments": []  # explicitly empty to indicate "no department / no role yet"
                }
                for e in unassigned_emails
            ]

            return {
                "success": True,
                "scope": "all",
                "total_users": len(all_emails),
                "department_counts": department_counts,   # {"AI": 12, "ML": 8, ...}
                "unassigned_count": unassigned_count,     # users with no dept mapping
                "unassigned_users": unassigned_users,     # simple array for UI convenience
                "count": len(by_email),
                "users": list(by_email.values()),         # includes both mapped and unassigned (departments=[])
            }

        # ---- Admin: restrict to current_user.department_name ----
        admin_dept = current_user.department_name
        if not admin_dept:
            # Defensive: if token/user context lacks department, return empty
            log.warning(f"Admin {current_user.email} has no department_name in context")
            return {
                "success": True,
                "scope": "none",
                "total_users": 0,
                "role_counts": {},
                "count": 0,
                "users": []
            }

        dept_users = await auth_service.user_dept_mapping_repo.get_department_users(admin_dept)
        # dept_users rows: {mail_id, role, is_active, created_at, created_by, user_name}

        # Shape output and aggregate role-wise counts
        users_out: dict[str, dict] = {}
        role_counts: dict[str, int] = defaultdict(int)

        for du in dept_users:
            email = du.get("mail_id")
            role = du.get("role")
            # Skip SuperAdmin users — they should not appear in user lists
            if role == "SuperAdmin":
                continue
            role_counts[role] += 1

            if email not in users_out:
                users_out[email] = {
                    "email": email,
                    "username": du.get("user_name"),
                    "departments": []
                }
            users_out[email]["departments"].append({
                "department_name": admin_dept,
                "role": role,
                "is_active": du.get("is_active", True) if du.get("is_active") is not None else True,
                "added_at": du.get("created_at"),
                "added_by": du.get("created_by"),
            })

        total_unique = len(users_out)

        return {
            "success": True,
            "scope": "department",
            "department_name": admin_dept,
            "total_users": total_unique,
            "role_counts": dict(role_counts),  # {"User": 94, "Developer": 20, "Admin": 5}
            "count": len(users_out),
            "users": list(users_out.values()),
        }

    except Exception as e:
        log.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users")



@router.api_route("/users/update-role", methods=["PATCH", "POST"])
async def update_user_role_in_department(
    request: Request,
    payload: UpdateUserRoleRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Update a user's roles and/or PWD within a department.
    - Assign one or more roles (add_roles) and/or remove one or more roles (remove_roles).
    - Optionally set a temporary password (temporary_password).
    - SuperAdmin: Can update any user in any department (must provide department_name in payload).
    - Admin: Can update users only within their own department.
    - At least one of add_roles / remove_roles / temporary_password must be provided.
    """

    # 1) Role gate: Admin and SuperAdmin only
    if current_user.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin or SuperAdmin can update user details"
        )

    add_roles = payload.add_roles or []
    remove_roles = payload.remove_roles or []
    temporary_password = payload.temporary_password if payload.temporary_password else None

    # At least one update field must be provided
    if not add_roles and not remove_roles and not temporary_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of 'add_roles', 'remove_roles' or 'temporary_password' must be provided"
        )

    # A role cannot be both added and removed in the same request
    conflicting = set(add_roles) & set(remove_roles)
    if conflicting:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role(s) {sorted(conflicting)} cannot be both added and removed in the same request"
        )

    target_email = payload.email_id.strip()

    # Prevent Admin from updating their own roles
    if current_user.role == "Admin" and target_email == current_user.email and (add_roles or remove_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin cannot update their own roles"
        )

    # 2) Determine target department based on role
    if current_user.role == "SuperAdmin":
        # SuperAdmin must provide department in payload
        if not payload.department_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SuperAdmin must specify department_name in payload"
            )
        target_dept = payload.department_name.strip()
    else:
        # Admin: use their own department context
        admin_dept = current_user.department_name
        if not admin_dept:
            log.warning(f"Admin {current_user.email} has no department_name in current_user context")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin has no department context; contact SuperAdmin to assign a department"
            )
        # If Admin provides department_name, it must match their own department
        if payload.department_name and payload.department_name.strip() != admin_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Admin can only update users in their own department '{admin_dept}'"
            )
        target_dept = admin_dept

    try:
        # 3) Verify target user is mapped to the target department
        in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
            mail_id=target_email,
            department_name=target_dept
        )
        if not in_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Target user is not in department '{target_dept}'"
            )

        # 3b) Block updates on SuperAdmin users
        target_global_role = await auth_service.user_dept_mapping_repo.get_user_role_for_department(
            mail_id=target_email,
            department_name=None
        )
        if target_global_role == "SuperAdmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update role for a SuperAdmin. SuperAdmin has system-wide access and is not tied to any department."
            )

        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")

        updates_made = []
        roles_added = []
        roles_removed = []
        errors = []

        # 4) Assign roles (delegates to assign_role_department for validation/auth/audit)
        for role in add_roles:
            result = await auth_service.assign_role_department(
                email_id=target_email,
                department_name=target_dept,
                role=role,
                current_user=current_user,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if result["success"]:
                roles_added.append(role)
            else:
                errors.append(result["message"])

        # 5) Remove roles (delegates to remove_role_from_user_in_department)
        for role in remove_roles:
            result = await auth_service.remove_role_from_user_in_department(
                email_id=target_email,
                department_name=target_dept,
                role=role,
                current_user=current_user,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if result["success"]:
                roles_removed.append(role)
            else:
                errors.append(result["message"])

        if roles_added:
            updates_made.append("roles_added")
        if roles_removed:
            updates_made.append("roles_removed")

        # 6) Set temporary PWD if provided (user must change on next login)
        if temporary_password:
            password_updated = await auth_service.set_temporary_password(
                email=target_email,
                temporary_password=temporary_password,
                current_user_id=current_user.email,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if not password_updated:
                errors.append("Failed to set temporary password")
            else:
                updates_made.append("password")

        # If nothing succeeded, surface the errors as a failure
        if not updates_made:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(errors) if errors else "No updates were applied"
            )

        # Build response message
        message_parts = []
        if roles_added:
            message_parts.append(f"added role(s) {roles_added}")
        if roles_removed:
            message_parts.append(f"removed role(s) {roles_removed}")
        if "password" in updates_made:
            message_parts.append("temporary password (user must change on next login)")

        return {
            "success": True,
            "message": f"Updated {', '.join(message_parts)} for {target_email} in department '{target_dept}'",
            "data": {
                "email": target_email,
                "department_name": target_dept,
                "roles_added": roles_added,
                "roles_removed": roles_removed,
                "password_updated": "password" in updates_made,
                "must_change_password": "password" in updates_made,
                "updates": updates_made,
                "errors": errors
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating role (actor={current_user.email}, target={target_email}, dept={target_dept}): {e}")
        raise HTTPException(status_code=500, detail="Internal server error while updating role")


@router.get("/get/search-paginated/users")
async def search_paginated_users_endpoint(
    request: Request,
    search_value: Optional[str] = Query(None, description="Substring match on email/username"),
    page_number: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    role: Optional[str] = Query(None, description="Filter by role"),
    department: Optional[str] = Query(None, description="SuperAdmin only: filter by department"),
    auth_service: AuthService = Depends(get_auth_service),
    user_data: User = Depends(get_current_user),
):
    """
    Role-aware search + pagination (NO status):
      - SuperAdmin: global view; can filter by department, role, and search.
      - Admin: restricted to current_user.department_name; can filter by role and search.
      - Others: 403.
    """
    if user_data.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Admin or SuperAdmin can list users")

    limit = page_size
    offset = (page_number - 1) * page_size

    try:
        if user_data.role == "SuperAdmin":
            result = await auth_service.user_dept_mapping_repo.search_users_all(
                search=search_value,
                department_name=department,
                role=role,
                limit=limit,
                offset=offset
            )
            return {
                "success": True,
                "scope": "all",
                "filters": {
                    "search_value": search_value,
                    "department": department,
                    "role": role,
                },
                "page_number": page_number,
                "page_size": page_size,
                "total": result["total"],
                "count": len(result["rows"]),
                "users": result["rows"],
            }

        # ----- Admin path -----
        admin_dept = user_data.department_name
        if not admin_dept:
            log.warning(f"Admin {user_data.email} has no department_name in auth context")
            return {
                "success": True,
                "scope": "none",
                "page_number": page_number,
                "page_size": page_size,
                "total": 0,
                "count": 0,
                "users": [],
                "message": "No department found for current admin",
            }

        if department and department != admin_dept:
            raise HTTPException(status_code=403, detail=f"Admins can only query their department ({admin_dept}).")

        result = await auth_service.user_dept_mapping_repo.search_department_users_for_admin(
            admin_department=admin_dept,
            search=search_value,
            role=role,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "scope": "department",
            "department_name": admin_dept,
            "filters": {"search_value": search_value, "role": role},
            "page_number": page_number,
            "page_size": page_size,
            "total": result["total"],
            "count": len(result["rows"]),
            "users": result["rows"],
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[GET /auth/get/search-paginated/users] error: {e}")
        raise HTTPException(status_code=500, detail="Failed to search/list users")



@router.get("/admin-contacts")
async def get_admin_contacts(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Returns a contact list of SuperAdmins (global) and Admins per department.
    Intended for newly registered members to know whom to contact for assignment.
    """
    try:
        # Pull all mappings once, then shape in-memory
        mappings = await auth_service.user_dept_mapping_repo.get_all_mappings()

        superadmins = sorted([
            {"email": m.get("mail_id"), "username": m.get("user_name")}
            for m in mappings
            if m.get("role") == "SuperAdmin" and m.get("department_name") is None
        ], key=lambda x: (x["username"] or "").lower())

        # Collect admins per department
        by_dept: Dict[str, List[Dict[str, str]]] = {}
        for m in mappings:
            if m.get("role") == "Admin" and m.get("department_name") is not None:
                dept = m.get("department_name")
                by_dept.setdefault(dept, [])
                by_dept[dept].append({"email": m.get("mail_id"), "username": m.get("user_name")})

        # Sort admins within each department and shape output list
        departments = []
        for dept, admins in by_dept.items():
            admins_sorted = sorted(admins, key=lambda x: (x["username"] or "").lower())
            departments.append({"department_name": dept, "admins": admins_sorted})
        departments.sort(key=lambda x: x["department_name"].lower())

        # Friendly message for the UI
        return {
            "success": True,
            "superadmins": superadmins,
            "departments": departments,
            "message": (
                "Contact a SuperAdmin for system-wide help, or a Department Admin "
                "to be assigned your role in that department."
            ),
        }
    except Exception as e:
        log.error(f"[GET /auth/admin-contacts] error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch admin contacts")


@router.get("/me/departments-with-roles")
async def get_current_user_department_roles(request: Request, auth_service: AuthService = Depends(get_auth_service)):
    """Get current user's departments with their specific roles in each department"""
    current_user = await get_current_user(request)
    
    # Get user's detailed department mappings
    department_roles = []
    if auth_service.user_dept_mapping_repo:
        # Get all mappings for this user with creation details
        async with auth_service.user_dept_mapping_repo.pool.acquire() as conn:
            query = """
            SELECT udm.department_name, udm.created_at, udm.created_by,
                   lc.role as user_global_role
            FROM userdepartmentmapping udm
            JOIN login_credential lc ON udm.mail_id = lc.mail_id
            WHERE udm.mail_id = $1
            ORDER BY udm.department_name
            """
            rows = await conn.fetch(query, current_user.email)
            
            for row in rows:
                department_roles.append({
                    "department_name": row["department_name"],
                    "role": row["user_global_role"],  # Currently same role for all departments
                    "added_to_department_at": row["created_at"],
                    "added_by": row["created_by"]
                })
    
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "global_role": current_user.role,  # The single role from login_credential table
        "department_roles": department_roles,  # Detailed department information
        "note": "Currently all departments show the same role. To have different roles per department, the UserDepartmentMapping table would need a role column."
    }


@router.get("/superadmin/exists")
async def check_superadmin_exists(
    auth_service: AuthService = Depends(get_auth_service)
):
    """Check if a SuperAdmin user exists in the system"""
    try:
        superadmin_exists = await auth_service.user_dept_mapping_repo.has_superadmin_assignment()
        return {
            "success": True,
            "superadmin_exists": superadmin_exists,
            "message": "SuperAdmin exists" if superadmin_exists else "No SuperAdmin found"
        }
    except Exception as e:
        log.error(f"Error checking SuperAdmin existence: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Internal server error while checking SuperAdmin existence"
        )


# ─────────────────────────────────────────────────────────────────────────────
# USER ENABLE/DISABLE ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.api_route("/users/set-active-status", methods=["PATCH", "POST"], response_model=UserActiveStatusResponse)
async def set_user_active_status(
    request: Request,
    payload: SetUserActiveStatusRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Enable or disable a user's login access in a specific department.
    
    **Department-specific disable**: Disables user in specified department only
    - SuperAdmin: Can disable in any department
    - Admin: Can only disable users in their own department
    
    When a user is disabled in a specific department:
    - They cannot log in to THAT department
    - They can still log in to other departments they have access to
    """
    # Only Admin and SuperAdmin can manage user active status
    if current_user.role not in ["Admin", "SuperAdmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin and SuperAdmin can enable/disable users"
        )
    
    target_email = payload.email_id.strip()
    new_status = payload.is_active
    target_department = payload.department_name
    
    # Prevent users from disabling themselves
    if target_email == current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own active status"
        )
    
    try:
        # Check if target user exists
        target_user = await auth_service.user_repo.get_user_basic_by_email(target_email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{target_email}' not found"
            )
        
        # Admin cannot disable SuperAdmin users
        target_primary_role = await auth_service.user_dept_mapping_repo.get_user_primary_role(target_email)
        if current_user.role == "Admin" and target_primary_role == "SuperAdmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin cannot change active status of SuperAdmin users"
            )
        
        # DEPARTMENT-SPECIFIC DISABLE
        # Verify department exists
        if auth_service.department_repo:
            dept_exists = await auth_service.department_repo.department_exists(target_department)
            if not dept_exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Department '{target_department}' does not exist"
                )
        
        # For Admin users, verify they can only manage their own department
        if current_user.role == "Admin":
            admin_dept = current_user.department_name
            if not admin_dept:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Admin has no department context"
                )
            if admin_dept != target_department:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"You can only manage users in your department '{admin_dept}'"
                )
        
        # Check if target user is in the specified department
        target_in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
            mail_id=target_email,
            department_name=target_department
        )
        if not target_in_dept:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{target_email}' is not a member of department '{target_department}'"
            )
        
        # Get current department-specific status for audit
        current_status = await auth_service.user_dept_mapping_repo.is_user_active_in_department(
            target_email, target_department
        )
        
        # Update department-specific status
        success = await auth_service.user_dept_mapping_repo.set_user_active_in_department(
            target_email, target_department, new_status
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user status"
            )
        
        # Log the action
        status_text = "enabled" if new_status else "disabled"
        old_status_text = "enabled" if current_status else "disabled"
        
        try:
            await auth_service.audit_repo.log_action(
                user_id=current_user.email,
                action="USER_STATUS_CHANGED_IN_DEPARTMENT",
                resource_type="user",
                resource_id=target_email,
                old_value=f"{old_status_text} (dept: {target_department})",
                new_value=f"{status_text} (dept: {target_department})",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("User-Agent")
            )
        except Exception as audit_err:
            log.warning(f"Audit log failed for user status change: {audit_err}")
        
        message = f"User '{target_email}' has been {status_text} in department '{target_department}'"
        
        return UserActiveStatusResponse(
            success=True,
            message=message,
            email=target_email,
            is_active=new_status,
            department_name=target_department
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error changing user active status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user active status"
        )


@router.get("/users/{email}/active-status")
async def get_user_active_status(
    email: str,
    department_name: Optional[str] = Query(None, description="Department to check status for. If None, returns all department statuses."),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get a user's active status per department.
    
    - If department_name is provided: Returns department-specific status
    - If department_name is None: Returns all department statuses
    
    Access Control:
    - SuperAdmin: Can check any user's status in any department
    - Admin: Can check users within their department only
    """
    # Only Admin and SuperAdmin can check user status
    if current_user.role not in ["Admin", "SuperAdmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin and SuperAdmin can check user active status"
        )
    
    try:
        # Check if target user exists
        target_user = await auth_service.user_repo.get_user_basic_by_email(email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{email}' not found"
            )
        
        if department_name:
            # Department-specific query
            # For Admin users, verify they can only check their own department
            if current_user.role == "Admin":
                admin_dept = current_user.department_name
                if admin_dept != department_name:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"You can only check users in your department '{admin_dept}'"
                    )
            
            # Check if user is in the department
            target_in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
                mail_id=email,
                department_name=department_name
            )
            if not target_in_dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{email}' is not a member of department '{department_name}'"
                )
            
            dept_is_active = await auth_service.user_dept_mapping_repo.is_user_active_in_department(
                email, department_name
            )
            dept_is_active = dept_is_active if dept_is_active is not None else True
            
            return {
                "success": True,
                "email": email,
                "username": target_user.get("user_name"),
                "department_name": department_name,
                "is_active": dept_is_active,
                "message": "User can login" if dept_is_active else f"User is disabled in department '{department_name}'"
            }
        else:
            # Return all department statuses
            # For Admin, only return their department
            if current_user.role == "Admin":
                admin_dept = current_user.department_name
                if not admin_dept:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Admin has no department context"
                    )
                
                # Check if user is in admin's department
                target_in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
                    mail_id=email,
                    department_name=admin_dept
                )
                if not target_in_dept:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"User is not in your department '{admin_dept}'"
                    )
                
                dept_status = await auth_service.user_dept_mapping_repo.get_user_department_status(
                    email, admin_dept
                )
                departments = [{
                    "department_name": admin_dept,
                    "is_active": dept_status.get("is_active", True) if dept_status else True,
                    "role": dept_status.get("role") if dept_status else None
                }]
            else:
                # SuperAdmin gets all departments
                user_depts = await auth_service.user_dept_mapping_repo.get_user_departments(email)
                departments = [
                    {
                        "department_name": d.get("department_name"),
                        "is_active": d.get("is_active", True),
                        "role": d.get("role")
                    }
                    for d in user_depts
                ]
            
            return {
                "success": True,
                "email": email,
                "username": target_user.get("user_name"),
                "departments": departments
            }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error getting user active status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user active status"
        )


@router.get("/users/{email}/roles")
async def get_user_roles_in_department(
    email: str,
    department_name: str = Query(..., description="Department to get roles for"),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get all roles a user has in a specific department.

    Access Control:
    - SuperAdmin: Can check any user in any department
    - Admin: Can check users within their own department only
    """
    if current_user.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin and SuperAdmin can view user roles"
        )

    try:
        # Admin can only query their own department
        if current_user.role == "Admin":
            admin_dept = current_user.department_name
            if admin_dept != department_name:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"You can only view users in your department '{admin_dept}'"
                )

        # Check if target user exists
        target_user = await auth_service.user_repo.get_user_basic_by_email(email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{email}' not found"
            )

        # Get all departments (includes grouped roles per department)
        user_depts = await auth_service.user_dept_mapping_repo.get_user_departments(email)

        # Find the requested department
        dept_data = next(
            (d for d in user_depts if d.get("department_name") == department_name),
            None
        )
        if not dept_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{email}' is not a member of department '{department_name}'"
            )

        return {
            "success": True,
            "email": email,
            "username": target_user.get("user_name"),
            "department_name": department_name,
            "current_role": dept_data.get("role"),
            "roles": dept_data.get("roles", []),
            "is_active": dept_data.get("is_active", True)
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error getting user roles in department: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user roles"
        )


@router.get("/departments")
async def get_available_departments(
    auth_service: AuthService = Depends(get_auth_service)
):
    """Get available departments for registration (public endpoint)"""
    try:
        # Get departments from the user repository using proper async context manager
        async with auth_service.user_repo.pool.acquire() as conn:
            results = await conn.fetch("SELECT department_name FROM departments ORDER BY department_name")
            department_list = [row["department_name"] for row in results]
            
        return {
            "success": True,
            "departments": department_list,
            "message": "Departments retrieved successfully"
        }
    except Exception as e:
        log.error(f"Error fetching departments for registration: {e}")
        return {
            "success": False,
            "departments": [],
            "message": "Failed to fetch departments"
        }



def get_role_access_service() -> RoleAccessService:
    """Dependency to get RoleAccessService instance"""
    return ServiceProvider.get_role_access_service()

