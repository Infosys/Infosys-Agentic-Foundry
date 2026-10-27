"""
auth/keycloak_service.py — Keycloak OAuth 2.0 + PKCE integration

Handles the full OAuth Authorization Code Flow with PKCE:
  - Authorization URL generation with code_challenge (S256)
  - Token exchange (code -> access + refresh + id tokens)
  - Token refresh via Keycloak
  - User info retrieval
  - Logout (token revocation + end-session URL)

All HTTP to Keycloak uses httpx with proxy=None and trust_env=False
so corporate proxies (Zscaler, etc.) are bypassed for internal IdP traffic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

logger = logging.getLogger("iaf_server.auth.keycloak")


def _decode_jwt_claims(token: str) -> Dict[str, Any]:
    """Best-effort decode of a JWT payload (no signature verification) to read its
    claims. Keycloak access tokens carry role claims in `realm_access`/`resource_access`,
    which the OIDC /userinfo endpoint does NOT return by default. The token comes
    from a trusted back-channel code exchange over TLS, so reading its claims here
    is safe. Returns {} on any parse failure."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # restore base64url padding
        return json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    except Exception:
        return {}


def _extract_roles(cfg: dict, *sources: Dict[str, Any]) -> List[str]:
    """Collect realm + client roles from one or more claim dicts (access-token
    payload and/or /userinfo response), de-duplicated in order."""
    roles: List[str] = []
    client_id = cfg.get("client_id", "")
    for src in sources:
        if not isinstance(src, dict):
            continue
        realm = src.get("realm_access") or {}
        roles.extend(realm.get("roles", []) or [])
        res = src.get("resource_access") or {}
        client_roles = (res.get(client_id) or {}) if isinstance(res, dict) else {}
        roles.extend(client_roles.get("roles", []) or [])
    return list(dict.fromkeys(roles))



def _generate_code_verifier(length: int = 64) -> str:
    raw = secrets.token_bytes(length)
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")[:128]


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")



@dataclass
class OAuthStateData:
    state: str
    code_verifier: str
    nonce: str
    redirect_uri: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self, expiry_seconds: int = 300) -> bool:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() > expiry_seconds


@dataclass
class KeycloakTokens:
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 300
    refresh_token: Optional[str] = None
    refresh_expires_in: Optional[int] = None
    id_token: Optional[str] = None
    scope: Optional[str] = None


@dataclass
class KeycloakUserInfo:
    sub: str
    email: str
    email_verified: bool = False
    preferred_username: Optional[str] = None
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)



class OAuthStateStore:
    def __init__(self, expiry_seconds: int = 300):
        self._store: Dict[str, OAuthStateData] = {}
        self._expiry = expiry_seconds

    def save(self, state: str, data: OAuthStateData) -> None:
        self._cleanup()
        self._store[state] = data

    def get(self, state: str) -> Optional[OAuthStateData]:
        self._cleanup()
        data = self._store.get(state)
        if data and not data.is_expired(self._expiry):
            return data
        return None

    def delete(self, state: str) -> None:
        self._store.pop(state, None)

    def _cleanup(self) -> None:
        expired = [s for s, d in self._store.items() if d.is_expired(self._expiry)]
        for s in expired:
            del self._store[s]


_state_store = OAuthStateStore()



class KeycloakService:
    """
    Stateless-ish service wrapping Keycloak OIDC endpoints.
    Reads config from shared.config at call time so env reloads work.
    """

    def __init__(self) -> None:
        self._http: Any = None  # httpx.AsyncClient, created lazily


    @staticmethod
    def _cfg() -> Dict[str, Any]:
        from shared.config import (
            KEYCLOAK_ENABLED, KEYCLOAK_SERVER_URL, KEYCLOAK_REALM,
            KEYCLOAK_CLIENT_ID, KEYCLOAK_CLIENT_SECRET,
            KEYCLOAK_REDIRECT_URI, KEYCLOAK_POST_LOGOUT_REDIRECT_URI,
            KEYCLOAK_VERIFY_SSL,
        )
        return {
            "enabled": KEYCLOAK_ENABLED,
            "server_url": KEYCLOAK_SERVER_URL.rstrip("/"),
            "realm": KEYCLOAK_REALM,
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": KEYCLOAK_CLIENT_SECRET,
            "redirect_uri": KEYCLOAK_REDIRECT_URI,
            "post_logout_redirect_uri": KEYCLOAK_POST_LOGOUT_REDIRECT_URI,
            "verify_ssl": KEYCLOAK_VERIFY_SSL,
        }

    @property
    def is_enabled(self) -> bool:
        return self._cfg()["enabled"]

    def _base_url(self, cfg: dict) -> str:
        return f"{cfg['server_url']}/realms/{cfg['realm']}"

    def _oidc(self, cfg: dict, endpoint: str) -> str:
        return f"{self._base_url(cfg)}/protocol/openid-connect/{endpoint}"


    async def _client(self) -> Any:
        if self._http is None or self._http.is_closed:
            import httpx
            cfg = self._cfg()
            self._http = httpx.AsyncClient(
                timeout=30.0,
                verify=cfg["verify_ssl"],
                follow_redirects=True,
                proxy=None,
                trust_env=False,
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def is_reachable(self) -> bool:
        """Best-effort probe of the realm OIDC discovery document."""
        cfg = self._cfg()
        if not cfg["enabled"]:
            return False
        try:
            client = await self._client()
            resp = await client.get(f"{self._base_url(cfg)}/.well-known/openid-configuration")
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Keycloak reachability check failed: %s", exc)
            return False


    async def get_authorization_url(
        self,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, str]:
        cfg = self._cfg()
        if not cfg["enabled"]:
            raise RuntimeError("Keycloak SSO is not enabled")

        state = secrets.token_urlsafe(32)
        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)
        nonce = secrets.token_urlsafe(32)

        final_redirect = redirect_uri or cfg["redirect_uri"]

        _state_store.save(state, OAuthStateData(
            state=state,
            code_verifier=code_verifier,
            nonce=nonce,
            redirect_uri=final_redirect,
        ))

        params = {
            "client_id": cfg["client_id"],
            "response_type": "code",
            "redirect_uri": final_redirect,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{self._oidc(cfg, 'auth')}?{urlencode(params)}"
        logger.info("SSO: generated authorization URL (state=%s...)", state[:8])
        return auth_url, state


    async def exchange_code(
        self,
        code: str,
        state: str,
    ) -> KeycloakTokens:
        cfg = self._cfg()
        if not cfg["enabled"]:
            raise RuntimeError("Keycloak SSO is not enabled")

        state_data = _state_store.get(state)
        if not state_data:
            raise ValueError("Invalid or expired OAuth state")
        _state_store.delete(state)

        client = await self._client()
        data: Dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": cfg["client_id"],
            "code": code,
            "redirect_uri": state_data.redirect_uri or cfg["redirect_uri"],
            "code_verifier": state_data.code_verifier,
        }
        if cfg["client_secret"]:
            data["client_secret"] = cfg["client_secret"]

        resp = await client.post(
            self._oidc(cfg, "token"),
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            logger.error("SSO token exchange failed: %s %s", resp.status_code, resp.text)
            raise ValueError(f"Token exchange failed: {resp.text}")

        t = resp.json()
        logger.info("SSO: token exchange successful")
        return KeycloakTokens(
            access_token=t["access_token"],
            token_type=t.get("token_type", "Bearer"),
            expires_in=t.get("expires_in", 300),
            refresh_token=t.get("refresh_token"),
            refresh_expires_in=t.get("refresh_expires_in"),
            id_token=t.get("id_token"),
            scope=t.get("scope"),
        )


    async def refresh_tokens(self, refresh_token: str) -> KeycloakTokens:
        cfg = self._cfg()
        client = await self._client()
        data: Dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": cfg["client_id"],
            "refresh_token": refresh_token,
        }
        if cfg["client_secret"]:
            data["client_secret"] = cfg["client_secret"]

        resp = await client.post(
            self._oidc(cfg, "token"),
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise ValueError(f"Keycloak token refresh failed: {resp.text}")

        t = resp.json()
        return KeycloakTokens(
            access_token=t["access_token"],
            token_type=t.get("token_type", "Bearer"),
            expires_in=t.get("expires_in", 300),
            refresh_token=t.get("refresh_token"),
            refresh_expires_in=t.get("refresh_expires_in"),
            id_token=t.get("id_token"),
            scope=t.get("scope"),
        )


    async def get_userinfo(self, access_token: str) -> KeycloakUserInfo:
        cfg = self._cfg()
        client = await self._client()
        resp = await client.get(
            self._oidc(cfg, "userinfo"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            raise ValueError(f"Keycloak userinfo failed: {resp.text}")

        d = resp.json()
        # Roles live in the access token; /userinfo omits them unless a mapper adds them.
        token_claims = _decode_jwt_claims(access_token)
        roles = _extract_roles(cfg, token_claims, d)
        groups = d.get("groups") or token_claims.get("groups") or []
        logger.info(
            "Keycloak userinfo: email=%s roles=%s groups=%s",
            d.get("email", ""), roles, groups,
        )

        return KeycloakUserInfo(
            sub=d.get("sub", ""),
            email=d.get("email", ""),
            email_verified=d.get("email_verified", False),
            preferred_username=d.get("preferred_username"),
            name=d.get("name"),
            given_name=d.get("given_name"),
            family_name=d.get("family_name"),
            roles=roles,
            groups=groups,
        )


    async def get_logout_url(self, id_token_hint: Optional[str] = None) -> str:
        cfg = self._cfg()
        params: Dict[str, str] = {}
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        redirect = cfg.get("post_logout_redirect_uri")
        if redirect:
            params["post_logout_redirect_uri"] = redirect
            params["client_id"] = cfg["client_id"]
        base = self._oidc(cfg, "logout")
        return f"{base}?{urlencode(params)}" if params else base

    async def revoke_refresh_token(self, refresh_token: str) -> bool:
        cfg = self._cfg()
        client = await self._client()
        data: Dict[str, str] = {
            "client_id": cfg["client_id"],
            "refresh_token": refresh_token,
        }
        if cfg["client_secret"]:
            data["client_secret"] = cfg["client_secret"]
        resp = await client.post(
            self._oidc(cfg, "logout"),
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        ok = resp.status_code in (200, 204)
        if not ok:
            logger.warning("SSO: refresh token revocation failed: %s", resp.status_code)
        return ok



_service: Optional[KeycloakService] = None


def get_keycloak_service() -> KeycloakService:
    global _service
    if _service is None:
        _service = KeycloakService()
    return _service
