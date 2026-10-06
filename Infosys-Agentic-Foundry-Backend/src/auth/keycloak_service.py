import os
import httpx
import asyncpg
import hashlib
import base64
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse
from src.auth.models import (
    User, UserRole, UserStatus, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, 
    RefreshTokenResponse, OAuthLoginInitResponse, OAuthCallbackResponse, OAuthLogoutResponse, OAuthStateData
)
from src.auth.repositories import AuditLogRepository
from telemetry_wrapper import logger as log
from src.config.settings import (
    KEYCLOAK_SERVER_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID, 
    KEYCLOAK_CLIENT_SECRET, KEYCLOAK_ADMIN_USERNAME, KEYCLOAK_ADMIN_PASSWORD,
    KEYCLOAK_REDIRECT_URI, KEYCLOAK_POST_LOGOUT_REDIRECT_URI,
    OAUTH_STATE_EXPIRY_SECONDS, KEYCLOAK_ALLOW_DIRECT_LOGIN
)
import jwt


# In-memory OAuth state store (use Redis in production for distributed systems)
# Maps state -> OAuthStateData for PKCE validation
_oauth_state_store: Dict[str, OAuthStateData] = {}


def _generate_code_verifier() -> str:
    """Generate a cryptographically random code verifier for PKCE (43-128 characters)"""
    return secrets.token_urlsafe(64)[:128]


def _generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from code verifier for PKCE"""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def _generate_state() -> str:
    """Generate a cryptographically random state parameter for CSRF protection"""
    return secrets.token_urlsafe(32)


def _generate_nonce() -> str:
    """Generate a cryptographically random nonce for replay protection"""
    return secrets.token_urlsafe(32)


class KeycloakService:
    """Service for Keycloak authentication operations with MFA support via Authorization Code Flow"""
    
    def __init__(self, audit_repo: AuditLogRepository):
        self.audit_repo = audit_repo
        self.server_url = KEYCLOAK_SERVER_URL.rstrip('/')
        self.realm = KEYCLOAK_REALM
        self.client_id = KEYCLOAK_CLIENT_ID
        self.client_secret = KEYCLOAK_CLIENT_SECRET
        self.admin_username = KEYCLOAK_ADMIN_USERNAME
        self.admin_password = KEYCLOAK_ADMIN_PASSWORD
        self.redirect_uri = KEYCLOAK_REDIRECT_URI
        self.post_logout_redirect_uri = KEYCLOAK_POST_LOGOUT_REDIRECT_URI
        
        # Keycloak endpoints
        self.token_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/token"
        self.userinfo_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/userinfo"
        self.logout_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/logout"
        self.auth_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/auth"
        self.end_session_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/logout"
        self.admin_token_url = f"{self.server_url}/realms/master/protocol/openid-connect/token"
        self.admin_users_url = f"{self.server_url}/admin/realms/{self.realm}/users"
        self.introspect_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/token/introspect"
        self.certs_url = f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/certs"
    
    # ------------------------------------------------------------------
    # JWKS key cache: { kid: public_key_pem, "_fetched_at": timestamp }
    # ------------------------------------------------------------------
    _jwks_cache: Dict[str, Any] = {}
    _JWKS_CACHE_TTL_SECONDS: int = 3600  # re-fetch keys every hour

    async def _get_jwks_public_key(self, kid: str) -> Optional[Any]:
        """
        Fetch and cache Keycloak's RS256 public key by key-id (kid).

        Keys are cached for _JWKS_CACHE_TTL_SECONDS to avoid a round-trip
        on every request. On unknown kid the cache is invalidated and
        re-fetched once (handles key rotation).
        """
        import time
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        import base64

        now = time.time()
        cached_at = self._jwks_cache.get("_fetched_at", 0)
        cache_stale = (now - cached_at) > self._JWKS_CACHE_TTL_SECONDS

        if kid not in self._jwks_cache or cache_stale:
            try:
                async with httpx.AsyncClient(trust_env=True) as client:
                    resp = await client.get(self.certs_url, timeout=10.0)
                    resp.raise_for_status()
                    jwks = resp.json()

                self._jwks_cache = {"_fetched_at": now}
                for jwk in jwks.get("keys", []):
                    k_kid = jwk.get("kid")
                    if not k_kid:
                        continue
                    # Build RSA public key from JWK n/e components
                    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
                    def _b64_to_int(val: str) -> int:
                        padded = val + "=" * (-len(val) % 4)
                        return int.from_bytes(base64.urlsafe_b64decode(padded), "big")
                    pub_numbers = RSAPublicNumbers(
                        e=_b64_to_int(jwk["e"]),
                        n=_b64_to_int(jwk["n"]),
                    )
                    self._jwks_cache[k_kid] = pub_numbers.public_key(default_backend())
            except Exception as e:
                log.error(f"Failed to fetch Keycloak JWKS: {e}")
                return None

        return self._jwks_cache.get(kid)

    async def validate_keycloak_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate an RS256 Keycloak access token using JWKS signature verification.

        Flow:
          1. Peek at the token header to get the key-id (kid)
          2. Fetch the matching RSA public key from Keycloak's JWKS endpoint (cached)
          3. Verify RS256 signature + exp + nbf + iss using PyJWT
          4. Return the decoded claims dict, or None if invalid

        No DB writes. No new token issued. Safe for token-passthrough from other apps.
        """
        try:
            # Step 1: read kid from header without verifying
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            if not kid:
                log.warning("Keycloak token missing kid in header")
                return None

            # Step 2: get matching public key (fetches JWKS if not cached)
            public_key = await self._get_jwks_public_key(kid)
            if not public_key:
                log.warning(f"No matching Keycloak public key for kid={kid}")
                return None

            # Step 3: verify signature + standard claims
            expected_issuer = f"{self.server_url}/realms/{self.realm}"
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={
                    "verify_aud": False,   # audience varies (client_id or resource)
                    "require": ["exp", "iat", "iss"],
                },
                issuer=expected_issuer,
            )
            return claims

        except jwt.ExpiredSignatureError:
            log.warning("Keycloak token has expired")
            return None
        except jwt.InvalidIssuerError:
            log.warning("Keycloak token issuer mismatch")
            return None
        except Exception as e:
            log.warning(f"Keycloak token validation failed: {e}")
            return None

    async def _get_admin_token(self) -> Optional[str]:
        """Get admin access token for user management operations"""
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                response = await client.post(
                    self.admin_token_url,
                    data={
                        "grant_type": "password",
                        "client_id": "admin-cli",
                        "username": self.admin_username,
                        "password": self.admin_password
                    }
                )
                if response.status_code == 200:
                    return response.json().get("access_token")
                log.error(f"Failed to get admin token: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            log.error(f"Error getting admin token: {e}")
            return None
    
    async def login(self, login_request: LoginRequest, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """
        Authenticate user via Keycloak using Resource Owner PWD Credentials (ROPC) Grant.
        
        WARNING: This method does NOT support MFA/OTP. If MFA is enabled in Keycloak,
        use init_oauth_login() and handle_oauth_callback() instead.
        
        This method is kept for backward compatibility but should be disabled when MFA is required.
        Set KEYCLOAK_ALLOW_DIRECT_LOGIN=false to enforce Authorization Code Flow.
        """
        # Check if direct login is allowed
        if not KEYCLOAK_ALLOW_DIRECT_LOGIN:
            log.warning("Direct password login attempted but KEYCLOAK_ALLOW_DIRECT_LOGIN is false")
            return LoginResponse(
                approval=False, 
                message="Direct login is disabled. Please use the OAuth login flow (/auth/oauth/login) which supports MFA."
            )
        
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Authenticate with Keycloak using Resource Owner PWD Credentials Grant
                data = {
                    "grant_type": "password",
                    "client_id": self.client_id,
                    "username": login_request.email_id,
                    "password": login_request.password,
                    "scope": "openid profile email"
                }
                
                # Add client secret_data if configured (for confidential clients)
                if self.client_secret:
                    data["client_secret"] = self.client_secret
                
                response = await client.post(self.token_url, data=data)
                
                if response.status_code != 200:
                    error_detail = response.json().get("error_description", "Authentication failed")
                    log.warning("Keycloak direct login rejected for %s: %s", login_request.email_id, error_detail)
                    await self.audit_repo.log_action(
                        user_id=None,
                        action="LOGIN_FAILED",
                        resource_type="user",
                        resource_id=login_request.email_id,
                        new_value=f"Keycloak error: {error_detail}",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return LoginResponse(approval=False, message="Authentication failed. Please try again or contact your administrator.")
                
                tokens = response.json()
                access_token = tokens.get("access_token")
                refresh_token = tokens.get("refresh_token")
                token_data = jwt.decode(access_token, options={"verify_signature": False, "verify_aud": False})
                
                # Get user info from Keycloak
                userinfo_response = await client.get(
                    self.userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if userinfo_response.status_code != 200:
                    return LoginResponse(approval=False, message="Failed to get user information")
                
                userinfo = userinfo_response.json()
                
                # Extract user details from Keycloak response
                email = userinfo.get("email", login_request.email_id)
                username = email.split("@")[0] if "@" in email else userinfo.get("preferred_username", userinfo.get("name", email))
                
                # Map Keycloak roles to application roles
                keycloak_roles = self._extract_roles(userinfo, token_data)
                app_role = self._map_keycloak_role_to_app_role(keycloak_roles, login_request.role)
                
                # Validate requested role against actual Keycloak roles
                if not self._validate_role_request(keycloak_roles, login_request.role):
                    await self.audit_repo.log_action(
                        user_id=email,
                        action="LOGIN_FAILED",
                        resource_type="user",
                        resource_id=email,
                        new_value=f"Requested role {login_request.role} not authorized",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return LoginResponse(approval=False, message=f"You are not authorized as {login_request.role}")
                
                # Log successful login
                await self.audit_repo.log_action(
                    user_id=email,
                    action="LOGIN_SUCCESS",
                    resource_type="user",
                    resource_id=email,
                    new_value=f"Role: {app_role} (Keycloak)",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                return LoginResponse(
                    approval=True,
                    token=access_token,
                    refresh_token=refresh_token,
                    role=app_role,
                    username=username,
                    email=email,
                    message="Login successful"
                )
                
        except httpx.RequestError as e:
            log.error(f"Keycloak connection error: {e}")
            return LoginResponse(approval=False, message="Unable to connect to authentication server")
        except Exception as e:
            log.error(f"Keycloak login error: {e}")
            return LoginResponse(approval=False, message="Login failed due to an error")
    
    # ==================== OAuth Authorization Code Flow (MFA Compatible) ====================
    
    def init_oauth_login(self, requested_role: str = None, custom_redirect_uri: str = None, frontend_origin: str = None) -> OAuthLoginInitResponse:
        """
        Initialize OAuth Authorization Code Flow with PKCE.
        
        This method generates the Keycloak authorization URL that the frontend should redirect to.
        Keycloak will handle the login UI including MFA/OTP if configured.
        
        Args:
            requested_role: Optional role the user is requesting (will be validated after login)
            custom_redirect_uri: Optional override for redirect URI
        
        Returns:
            OAuthLoginInitResponse with redirect URL and state token
        """
        # Generate PKCE parameters
        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)
        state = _generate_state()
        nonce = _generate_nonce()
        
        redirect_uri = custom_redirect_uri or self.redirect_uri
        
        # Store state data for validation during callback (TTL: 10 minutes)
        state_data = OAuthStateData(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            requested_role=requested_role,
            frontend_origin=frontend_origin,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=OAUTH_STATE_EXPIRY_SECONDS)
        )
        _oauth_state_store[state] = state_data
        
        # Clean up expired states
        self._cleanup_expired_states()
        
        # Build Keycloak authorization URL
        auth_params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        
        auth_url = f"{self.auth_url}?{urlencode(auth_params)}"
        
        log.info(f"OAuth login initiated with state: {state[:8]}...")
        
        return OAuthLoginInitResponse(
            redirect_url=auth_url,
            state=state,
            message="Redirect to Keycloak for authentication"
        )
    
    async def handle_oauth_callback(
        self, 
        code: str, 
        state: str, 
        ip_address: str = None, 
        user_agent: str = None
    ) -> OAuthCallbackResponse:
        """
        Handle OAuth callback from Keycloak after user completes authentication (including MFA).
        
        This exchanges the authorization code for tokens using PKCE verification.
        
        Args:
            code: Authorization code from Keycloak
            state: State parameter for CSRF validation
            ip_address: Client IP for audit logging
            user_agent: User agent for audit logging
        
        Returns:
            OAuthCallbackResponse with tokens and user information
        """
        # Validate state and retrieve stored data
        state_data = _oauth_state_store.get(state)
        
        if not state_data:
            log.warning(f"OAuth callback with invalid/expired state: {state[:8]}...")
            await self.audit_repo.log_action(
                user_id=None,
                action="OAUTH_LOGIN_FAILED",
                resource_type="user",
                resource_id=None,
                new_value="Invalid or expired state parameter",
                ip_address=ip_address,
                user_agent=user_agent
            )
            return OAuthCallbackResponse(
                approval=False,
                message="Invalid or expired login session. Please try logging in again."
            )
        
        # Check if state has expired
        if datetime.utcnow() > state_data.expires_at:
            del _oauth_state_store[state]
            log.warning(f"OAuth callback with expired state: {state[:8]}...")
            return OAuthCallbackResponse(
                approval=False,
                message="Login session expired. Please try logging in again.",
                frontend_origin=state_data.frontend_origin
            )
        
        # Remove state from store (one-time use)
        del _oauth_state_store[state]
        
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Exchange authorization code for tokens
                token_data = {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": state_data.redirect_uri,
                    "client_id": self.client_id,
                    "code_verifier": state_data.code_verifier  # PKCE verification
                }
                
                # Add client secret_data if configured (for confidential clients)
                if self.client_secret:
                    token_data["client_secret"] = self.client_secret
                
                # Log proxy env before token exchange (httpx trust_env uses these)
                log.info(
                    "OAuth token exchange: token_url=%s, HTTP_PROXY=%s, HTTPS_PROXY=%s, NO_PROXY=%s, no_proxy=%s",
                    self.token_url,
                    os.environ.get("HTTP_PROXY", "(unset)"),
                    os.environ.get("HTTPS_PROXY", "(unset)"),
                    os.environ.get("NO_PROXY", "(unset)"),
                    os.environ.get("no_proxy", "(unset)"),
                )
                try:
                    response = await client.post(
                        self.token_url,
                        data=token_data,
                        timeout=30.0
                    )
                except httpx.RequestError as e:
                    # ReadTimeout often means the request went through a proxy (HTTP_PROXY) that cannot
                    # reach internal Keycloak; fix by adding Keycloak host to NO_PROXY so requests go direct.
                    hint = ""
                    if isinstance(e, httpx.ReadTimeout):
                        keycloak_host = urlparse(self.token_url).hostname or ""
                        hint = f" Request goes via proxy; add Keycloak to NO_PROXY (e.g. NO_PROXY={keycloak_host}) so token request bypasses proxy. "
                    log.error(
                        "OAuth token exchange request failed (connection/timeout): token_url=%s, redirect_uri_sent=%s, error=%s (%s).%s"
                        "Ensure KEYCLOAK_SERVER_URL is reachable from the server.",
                        self.token_url,
                        state_data.redirect_uri,
                        type(e).__name__,
                        str(e),
                        hint,
                        exc_info=True
                    )
                    await self.audit_repo.log_action(
                        user_id=None,
                        action="OAUTH_LOGIN_FAILED",
                        resource_type="user",
                        resource_id=None,
                        new_value=f"Token exchange request failed: {type(e).__name__}: {e!s}",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return OAuthCallbackResponse(
                        approval=False,
                        message="Unable to connect to authentication server. Please try again.",
                        frontend_origin=state_data.frontend_origin
                    )
                
                if response.status_code != 200:
                    try:
                        error_response = response.json()
                    except Exception:
                        error_response = {}
                    error_desc = error_response.get("error_description", error_response.get("error", "Token exchange failed"))
                    # Log full details for debugging (redirect_uri mismatch is a common cause)
                    log.error(
                        "OAuth token exchange failed: status=%s, error=%s, redirect_uri_sent=%s, token_url=%s, response_body=%s",
                        response.status_code,
                        error_desc,
                        state_data.redirect_uri,
                        self.token_url,
                        response.text[:500] if response.text else "(empty)"
                    )
                    
                    await self.audit_repo.log_action(
                        user_id=None,
                        action="OAUTH_LOGIN_FAILED",
                        resource_type="user",
                        resource_id=None,
                        new_value=f"Token exchange error: {error_desc}",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    
                    return OAuthCallbackResponse(
                        approval=False,
                        message="Authentication failed. Please try again or contact your administrator.",
                        frontend_origin=state_data.frontend_origin
                    )
                
                tokens = response.json()
                access_token = tokens.get("access_token")
                refresh_token = tokens.get("refresh_token")
                id_token = tokens.get("id_token")
                expires_in = tokens.get("expires_in")
                
                # Decode token to get claims (without signature verification for now)
                decoded_token = jwt.decode(access_token, options={"verify_signature": False, "verify_aud": False})
                
                # Validate nonce in ID token if present
                if id_token:
                    id_token_claims = jwt.decode(id_token, options={"verify_signature": False, "verify_aud": False})
                    if id_token_claims.get("nonce") != state_data.nonce:
                        log.warning("Nonce mismatch in ID token - potential replay attack")
                        return OAuthCallbackResponse(
                            approval=False,
                            message="Security validation failed. Please try logging in again.",
                            frontend_origin=state_data.frontend_origin
                        )
                
                # Get user info from Keycloak
                userinfo_response = await client.get(
                    self.userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if userinfo_response.status_code != 200:
                    log.error(f"Failed to get userinfo: {userinfo_response.status_code}")
                    return OAuthCallbackResponse(
                        approval=False,
                        message="Failed to retrieve user information",
                        frontend_origin=state_data.frontend_origin
                    )
                
                userinfo = userinfo_response.json()
                
                # Extract user details
                email = userinfo.get("email", decoded_token.get("email", decoded_token.get("sub")))
                username = email.split("@")[0] if "@" in email else userinfo.get("preferred_username", userinfo.get("name", email))
                
                # Map roles
                keycloak_roles = self._extract_roles(userinfo, decoded_token)
                
                # Validate requested role if specified
                requested_role = state_data.requested_role
                if requested_role:
                    if not self._validate_role_request(keycloak_roles, requested_role):
                        await self.audit_repo.log_action(
                            user_id=email,
                            action="OAUTH_LOGIN_FAILED",
                            resource_type="user",
                            resource_id=email,
                            new_value=f"Requested role {requested_role} not authorized",
                            ip_address=ip_address,
                            user_agent=user_agent
                        )
                        return OAuthCallbackResponse(
                            approval=False,
                            message=f"You are not authorized as {requested_role}"
                        )
                    app_role = requested_role
                else:
                    app_role = self._get_highest_role(keycloak_roles)
                
                # Log successful OAuth login (user_id must exist in login_credential; OAuth users may not be there yet)
                try:
                    await self.audit_repo.log_action(
                        user_id=email,
                        action="OAUTH_LOGIN_SUCCESS",
                        resource_type="user",
                        resource_id=email,
                        new_value=f"Role: {app_role} (Keycloak OAuth + MFA)",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                except asyncpg.ForeignKeyViolationError:
                    # User not in login_credential yet (first-time OAuth); log with user_id=None, keep email in new_value
                    await self.audit_repo.log_action(
                        user_id=None,
                        action="OAUTH_LOGIN_SUCCESS",
                        resource_type="user",
                        resource_id=email,
                        new_value=f"OAuth login: {email}, Role: {app_role} (Keycloak OAuth + MFA)",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                
                log.info(f"OAuth login successful for user: {email}")
                
                return OAuthCallbackResponse(
                    approval=True,
                    token=access_token,
                    refresh_token=refresh_token,
                    id_token=id_token,
                    role=app_role,
                    username=username,
                    email=email,
                    message="Login successful",
                    expires_in=expires_in,
                    frontend_origin=state_data.frontend_origin
                )
                
        except httpx.RequestError as e:
            log.error(f"Keycloak connection error during OAuth callback: {e}")
            return OAuthCallbackResponse(
                approval=False,
                message="Unable to connect to authentication server"
            )
        except Exception as e:
            log.error("OAuth callback error: %s: %s", type(e).__name__, e, exc_info=True)
            return OAuthCallbackResponse(
                approval=False,
                message="Authentication failed due to an unexpected error"
            )
    
    def get_oauth_logout_url(self, id_token: str = None) -> OAuthLogoutResponse:
        """
        Generate Keycloak logout URL for OAuth end-session.
        
        The frontend should redirect to this URL to properly terminate the Keycloak session.
        
        Args:
            id_token: ID token hint for Keycloak (optional but recommended)
        
        Returns:
            OAuthLogoutResponse with logout URL
        """
        logout_params = {
            "client_id": self.client_id,
            "post_logout_redirect_uri": self.post_logout_redirect_uri
        }
        
        if id_token:
            logout_params["id_token_hint"] = id_token
        
        logout_url = f"{self.end_session_url}?{urlencode(logout_params)}"
        
        return OAuthLogoutResponse(
            success=True,
            logout_url=logout_url,
            message="Redirect to Keycloak to complete logout"
        )
    
    def validate_oauth_state(self, state: str) -> bool:
        """Check if an OAuth state token is valid and not expired"""
        state_data = _oauth_state_store.get(state)
        if not state_data:
            return False
        if datetime.utcnow() > state_data.expires_at:
            del _oauth_state_store[state]
            return False
        return True
    
    def _cleanup_expired_states(self):
        """Remove expired OAuth state entries from the store"""
        now = datetime.utcnow()
        expired_states = [
            state for state, data in _oauth_state_store.items()
            if now > data.expires_at
        ]
        for state in expired_states:
            del _oauth_state_store[state]
        if expired_states:
            log.debug(f"Cleaned up {len(expired_states)} expired OAuth states")
    
    # ==================== End OAuth Authorization Code Flow ====================

    async def guest_login(self, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """Guest login is not supported with Keycloak - users must authenticate"""
        await self.audit_repo.log_action(
            user_id=None,
            action="GUEST_LOGIN_ATTEMPT",
            resource_type="user",
            resource_id="guest",
            new_value="Guest login attempted but not supported with Keycloak",
            ip_address=ip_address,
            user_agent=user_agent
        )
        return LoginResponse(
            approval=False,
            message="Guest login is not available. Please log in with your credentials."
        )
    
    async def logout(self, token: str, refresh_token: str = None, ip_address: str = None, user_agent: str = None) -> bool:
        """Logout user by revoking tokens in Keycloak"""
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Revoke the refresh token in Keycloak (this invalidates the session)
                if refresh_token:
                    data = {
                        "client_id": self.client_id,
                        "refresh_token": refresh_token
                    }
                    if self.client_secret:
                        data["client_secret"] = self.client_secret
                    
                    await client.post(self.logout_url, data=data)
                
                await self.audit_repo.log_action(
                    user_id=None,
                    action="LOGOUT",
                    resource_type="user",
                    resource_id=None,
                    new_value="Keycloak session terminated",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return True
        except Exception as e:
            log.error(f"Keycloak logout error: {e}")
            return False
    
    async def refresh_access_token(self, refresh_token: str, ip_address: str = None, user_agent: str = None) -> RefreshTokenResponse:
        """Use refresh token to get new access token from Keycloak"""
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                data = {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": refresh_token
                }
                if self.client_secret:
                    data["client_secret"] = self.client_secret
                
                response = await client.post(self.token_url, data=data)
                
                if response.status_code != 200:
                    error_detail = response.json().get("error_description", "Token refresh failed")
                    return RefreshTokenResponse(approval=False, message=error_detail, token=None)
                
                tokens = response.json()
                new_access_token = tokens.get("access_token")
                new_refresh_token = tokens.get("refresh_token")
                
                await self.audit_repo.log_action(
                    user_id=None,
                    action="ACCESS_TOKEN_REFRESHED",
                    resource_type="user",
                    resource_id=None,
                    new_value="Token refreshed via Keycloak",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                return RefreshTokenResponse(
                    approval=True,
                    token=new_access_token,
                    refresh_token=new_refresh_token,
                    message="Access token refreshed"
                )
                
        except Exception as e:
            log.error(f"Keycloak token refresh error: {e}")
            return RefreshTokenResponse(approval=False, message="Failed to refresh token", token=None)
    
    async def register(self, register_request: RegisterRequest, ip_address: str = None, user_agent: str = None) -> RegisterResponse:
        """Register new user in Keycloak"""
        try:
            # Get admin token for user creation
            admin_token = await self._get_admin_token()
            if not admin_token:
                return RegisterResponse(approval=False, message="Unable to connect to user management service")
            
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Check if user already exists
                check_response = await client.get(
                    f"{self.admin_users_url}?email={register_request.email_id}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                
                if check_response.status_code == 200 and check_response.json():
                    return RegisterResponse(approval=False, message="User already exists")
                
                # Create user in Keycloak
                user_data = {
                    "username": register_request.email_id,
                    "email": register_request.email_id,
                    "firstName": register_request.user_name,
                    "enabled": True,
                    "emailVerified": True,
                    "credentials": [{
                        "type": "password",
                        "value": register_request.password,
                        "temporary": False
                    }],
                    "attributes": {
                        "app_role": [register_request.role]
                    }
                }
                
                create_response = await client.post(
                    self.admin_users_url,
                    json=user_data,
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                if create_response.status_code == 201:
                    # Assign role to user
                    user_id = create_response.headers.get("Location", "").split("/")[-1]
                    if user_id:
                        await self._assign_role_to_user(admin_token, user_id, register_request.role)
                    
                    await self.audit_repo.log_action(
                        user_id=register_request.email_id,
                        action="USER_REGISTERED",
                        resource_type="user",
                        resource_id=register_request.email_id,
                        new_value=f"Role: {register_request.role} (Keycloak)",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    
                    return RegisterResponse(approval=True, message=f"{register_request.user_name} registered successfully")
                elif create_response.status_code == 409:
                    return RegisterResponse(approval=False, message="User already exists")
                else:
                    error_msg = create_response.json().get("errorMessage", "Registration failed")
                    return RegisterResponse(approval=False, message=error_msg)
                    
        except Exception as e:
            log.error(f"Keycloak registration error: {e}")
            return RegisterResponse(approval=False, message="Registration failed due to an error")
    
    async def validate_jwt(self, token: str) -> Optional[User]:
        """Validate JWT token with Keycloak and return user info"""
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # First, introspect the token to validate it
                introspect_data = {
                    "client_id": self.client_id,
                    "token": token
                }
                if self.client_secret:
                    introspect_data["client_secret"] = self.client_secret
                
                introspect_response = await client.post(
                    self.introspect_url,
                    data=introspect_data
                )
                
                if introspect_response.status_code != 200:
                    log.warning("Token introspection failed")
                    return None
                
                introspect_result = introspect_response.json()
                
                if not introspect_result.get("active", False):
                    log.warning("Token is not active/valid")
                    return None
                
                # Get user info using the access token
                userinfo_response = await client.get(
                    self.userinfo_url,
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if userinfo_response.status_code != 200:
                    log.warning("Failed to get user info from Keycloak")
                    return None
                
                userinfo = userinfo_response.json()
                
                email = userinfo.get("email", userinfo.get("sub"))
                username = email.split("@")[0] if email and "@" in email else userinfo.get("preferred_username", userinfo.get("name", email))
                
                # Extract roles from token/userinfo
                keycloak_roles = self._extract_roles(userinfo, introspect_result)
                app_role = self._get_highest_role(keycloak_roles)
                
                return User(
                    id=email,
                    email=email,
                    username=username,
                    role=UserRole(app_role),
                    status=UserStatus.ACTIVE,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
        except Exception as e:
            log.error(f"Keycloak JWT validation error: {e}")
            return None
    
    async def update_password(self, email: str, new_password: str, current_user_id: str,
                            ip_address: str = None, user_agent: str = None) -> bool:
        """Update user PWD in Keycloak"""
        try:
            admin_token = await self._get_admin_token()
            if not admin_token:
                return False
            
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Find user by email
                search_response = await client.get(
                    f"{self.admin_users_url}?email={email}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                
                if search_response.status_code != 200 or not search_response.json():
                    return False
                
                user_id = search_response.json()[0]["id"]
                
                # Reset PWD
                reset_response = await client.put(
                    f"{self.admin_users_url}/{user_id}/reset-password",
                    json={
                        "type": "password",
                        "value": new_password,
                        "temporary": False
                    },
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                if reset_response.status_code == 204:
                    await self.audit_repo.log_action(
                        user_id=current_user_id,
                        action="PASSWORD_UPDATED",
                        resource_type="user",
                        resource_id=email,
                        new_value="Password changed (Keycloak)",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return True
                return False
                
        except Exception as e:
            log.error(f"Keycloak password update error: {e}")
            return False
    
    async def update_role(self, email: str, new_role: str, current_user_id: str,
                         ip_address: str = None, user_agent: str = None) -> bool:
        """Update user role in Keycloak"""
        try:
            admin_token = await self._get_admin_token()
            if not admin_token:
                return False
            
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Find user by email
                search_response = await client.get(
                    f"{self.admin_users_url}?email={email}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                
                if search_response.status_code != 200 or not search_response.json():
                    return False
                
                user_data = search_response.json()[0]
                user_id = user_data["id"]
                old_role = user_data.get("attributes", {}).get("app_role", ["User"])[0]
                
                # Update user attributes with new role
                user_data["attributes"] = user_data.get("attributes", {})
                user_data["attributes"]["app_role"] = [new_role]
                
                update_response = await client.put(
                    f"{self.admin_users_url}/{user_id}",
                    json=user_data,
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                if update_response.status_code == 204:
                    # Also update realm roles if applicable
                    await self._assign_role_to_user(admin_token, user_id, new_role)
                    
                    await self.audit_repo.log_action(
                        user_id=current_user_id,
                        action="ROLE_UPDATED",
                        resource_type="user",
                        resource_id=email,
                        old_value=old_role,
                        new_value=new_role,
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return True
                return False
                
        except Exception as e:
            log.error(f"Keycloak role update error: {e}")
            return False
    
    async def _assign_role_to_user(self, admin_token: str, user_id: str, role_name: str) -> bool:
        """Assign a realm role to a user in Keycloak"""
        try:
            async with httpx.AsyncClient(trust_env=True) as client:  # Respects NO_PROXY, HTTP_PROXY, HTTPS_PROXY from .env
                # Get available realm roles
                roles_url = f"{self.server_url}/admin/realms/{self.realm}/roles"
                roles_response = await client.get(
                    roles_url,
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                
                if roles_response.status_code != 200:
                    return False
                
                # Find the role that matches
                available_roles = roles_response.json()
                role_to_assign = None
                
                for role in available_roles:
                    if role["name"].lower() == role_name.lower():
                        role_to_assign = role
                        break
                
                if not role_to_assign:
                    log.warning(f"Role {role_name} not found in Keycloak realm")
                    return False
                
                # Assign role to user
                assign_url = f"{self.admin_users_url}/{user_id}/role-mappings/realm"
                assign_response = await client.post(
                    assign_url,
                    json=[role_to_assign],
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                return assign_response.status_code == 204
                
        except Exception as e:
            log.error(f"Error assigning role to user: {e}")
            return False
    
    def _extract_roles(self, userinfo: Dict[str, Any], token_data: Dict[str, Any]) -> list:
        """Extract roles from Keycloak userinfo and token data"""
        roles = []
        
        # Check for realm roles in token
        if "realm_access" in token_data:
            roles.extend(token_data["realm_access"].get("roles", []))
        
        # Check for client roles in token
        if "resource_access" in token_data:
            client_access = token_data["resource_access"].get(self.client_id, {})
            roles.extend(client_access.get("roles", []))
        
        # Check for groups in userinfo (if using groups for roles)
        if "groups" in userinfo:
            roles.extend(userinfo["groups"])
        
        # Check for custom app_role attribute
        if "app_role" in userinfo:
            role_value = userinfo["app_role"]
            if isinstance(role_value, list):
                roles.extend(role_value)
            else:
                roles.append(role_value)
        
        return roles
    
    def _map_keycloak_role_to_app_role(self, keycloak_roles: list, requested_role: str) -> str:
        """Map Keycloak roles to application roles"""
        role_mapping = {
            "SuperAdmin": "SuperAdmin",
            "Admin": "Admin",
            "Developer": "Developer",
            "User": "User"
        }
        normalized_roles = [r for r in keycloak_roles]
        
        # Check if user has the requested role or higher
        role_hierarchy = ["User", "Developer", "Admin", "SuperAdmin"]
        
        user_highest_role = "User"
        for role_key in reversed(role_hierarchy):
            if role_key in normalized_roles:
                user_highest_role = role_mapping.get(role_key, "User")
                break
        
        return user_highest_role
    
    def _validate_role_request(self, keycloak_roles: list, requested_role: str) -> bool:
        """Validate if user can request the specified role based on their Keycloak roles"""
        role_hierarchy = {
            "User": 0,
            "Developer": 1,
            "Admin": 2,
            "SuperAdmin": 3
        }
        
        # Normalize role names
        normalized_roles = [r for r in keycloak_roles]
        
        # Find user's highest role level
        user_level = 0
        role_mapping = {
            "SuperAdmin": 3,
            "Admin": 2,
            "Developer": 1,
            "User": 0
        }
        
        for role in normalized_roles:
            if role in role_mapping:
                user_level = max(user_level, role_mapping[role])
        
        requested_level = role_hierarchy.get(requested_role, 0)
        return user_level >= requested_level
    
    def _get_highest_role(self, keycloak_roles: list) -> str:
        """Get the highest role from Keycloak roles"""
        role_hierarchy = ["User", "Developer", "Admin", "SuperAdmin"]
        role_mapping = {
            "SuperAdmin": "SuperAdmin",
            "Admin": "Admin",
            "Developer": "Developer",
            "User": "User"
        }
        
        normalized_roles = [r for r in keycloak_roles]
        
        highest_role = "User"
        for role_key in reversed(role_hierarchy):
            if role_key in normalized_roles:
                highest_role = role_mapping.get(role_key, "User")
                break
        
        return highest_role
