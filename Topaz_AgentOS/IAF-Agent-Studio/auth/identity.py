"""Provider-neutral identity context and access-token resolvers.

Authentication providers prove who the caller is; downstream AgentOS code should
consume this normalized shape rather than provider-specific JWT/OIDC claims.
"""

from __future__ import annotations

import json
import logging
import time
import base64
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

from jose import JWTError, jwt


logger = logging.getLogger("iaf_server.auth.identity")


class IdentityResolutionError(ValueError):
    """Raised when a token cannot be validated or mapped to identity."""


class IdentityAuthorizationError(PermissionError):
    """Raised when a valid identity is not authorized for the requested tenant."""


class IdentityConfigurationError(RuntimeError):
    """Raised when the selected identity provider is not configured safely."""


class AccessTokenIdentityResolver(Protocol):
    """Resolver interface for provider-specific access-token validation."""

    def resolve(self, token: str) -> "IdentityContext":
        ...


@dataclass(frozen=True)
class IdentityContext:
    """Canonical identity object consumed by request, policy, and service paths."""

    user_id: str
    email: str = ""
    tenant_id: str = "company"
    roles: tuple[str, ...] = ("user",)
    groups: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    allowed_tenants: tuple[str, ...] = ("company",)
    auth_provider: str = "local"
    auth_method: str = "jwt"
    token_type: str = "access"
    issuer: str = ""
    audience: str = ""
    expires_at: int | None = None
    issued_at: int | None = None
    jti: str = ""
    request_id: str = ""
    is_service_principal: bool = False
    service_name: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    # Login session id (``sid`` claim) for the single-session control.
    session_id: str = ""
    # True for a minimal Studio token: email/roles/groups/tenant are placeholders
    # until enrich_identity_from_store() fills them from the user record.
    user_lookup_required: bool = False

    def __post_init__(self) -> None:
        if not self.user_id:
            raise IdentityResolutionError("Identity is missing required user_id")
        object.__setattr__(self, "roles", _tuple(self.roles) or ("user",))
        object.__setattr__(self, "groups", _tuple(self.groups))
        object.__setattr__(self, "scopes", _tuple(self.scopes))
        allowed = _tuple(self.allowed_tenants) or (self.tenant_id,)
        object.__setattr__(self, "allowed_tenants", allowed)

    def to_principal(self):
        from security.models import Principal

        attributes = {
            **(self.attributes or {}),
            "auth_provider": self.auth_provider,
            "auth_method": self.auth_method,
            "scopes": self.scopes,
            "is_service_principal": self.is_service_principal,
        }
        if self.service_name:
            attributes["service_name"] = self.service_name
        if self.request_id:
            attributes["request_id"] = self.request_id
        if self.jti:
            attributes["jti"] = self.jti
        return Principal(
            user_id=self.user_id,
            email=self.email,
            tenant_id=self.tenant_id,
            roles=self.roles,
            groups=self.groups,
            allowed_tenants=self.allowed_tenants,
            attributes=attributes,
        )

    def to_auth_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "role": self.roles[0] if self.roles else "user",
            "roles": list(self.roles),
            "tenant_id": self.tenant_id,
            "groups": list(self.groups),
            "scopes": list(self.scopes),
            "allowed_tenants": list(self.allowed_tenants),
            "auth_provider": self.auth_provider,
            "auth_method": self.auth_method,
            "is_service_principal": self.is_service_principal,
        }

    def safe_dict(self, attribute_limit: int = 256) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "tenant_id": self.tenant_id,
            "roles": list(self.roles),
            "groups": list(self.groups),
            "scopes": list(self.scopes),
            "allowed_tenants": list(self.allowed_tenants),
            "auth_provider": self.auth_provider,
            "auth_method": self.auth_method,
            "token_type": self.token_type,
            "issuer": self.issuer,
            "audience": self.audience,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "request_id": self.request_id,
            "is_service_principal": self.is_service_principal,
            "service_name": self.service_name,
            "attributes": _bound_value(self.attributes, attribute_limit),
        }


def _default_tenant() -> str:
    try:
        from shared.config import TENANT_ID
        return TENANT_ID
    except Exception:
        return "company"


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if not value:
            return ()
        return tuple(part for part in value.replace(",", " ").split() if part)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),) if str(value) else ()


def _bound_value(value: Any, limit: int) -> Any:
    if isinstance(value, dict):
        bounded: dict[str, Any] = {}
        budget = max(16, limit)
        for key in sorted(value):
            if len(json.dumps(bounded, default=str)) >= budget:
                bounded["_truncated"] = True
                break
            bounded[str(key)[:64]] = _bound_value(value[key], max(16, limit // 2))
        return bounded
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:10]
        if len(value) > 10:
            items.append("...")
        return [_bound_value(item, max(16, limit // 2)) for item in items]
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def identity_from_access_claims(
    claims: dict[str, Any],
    *,
    provider_name: str = "local",
    auth_method: str = "jwt",
    role_claims: tuple[str, ...] = ("roles", "role"),
    group_claims: tuple[str, ...] = ("groups",),
    tenant_claims: tuple[str, ...] = ("tenant_id", "tid"),
    email_claims: tuple[str, ...] = ("email", "preferred_username", "upn"),
) -> IdentityContext:
    token_type = str(claims.get("type") or "access")
    if token_type != "access":
        raise IdentityResolutionError("Not an access token")

    user_id = str(claims.get("sub") or claims.get("oid") or "")
    if not user_id:
        raise IdentityResolutionError("Access token is missing subject")
    tenant_id = _first_claim(claims, tenant_claims) or _default_tenant()
    roles = _first_claim(claims, role_claims)
    groups = _first_claim(claims, group_claims)
    scopes = claims.get("scp") or claims.get("scope") or claims.get("scopes") or ()
    allowed_tenants = claims.get("allowed_tenants") or [tenant_id]
    email = _first_claim(claims, email_claims) or ""

    return IdentityContext(
        user_id=user_id,
        email=str(email),
        tenant_id=str(tenant_id),
        roles=_tuple(roles) or ("user",),
        groups=_tuple(groups),
        scopes=_tuple(scopes),
        allowed_tenants=_tuple(allowed_tenants) or (str(tenant_id),),
        auth_provider=provider_name,
        auth_method=auth_method,
        token_type=token_type,
        issuer=str(claims.get("iss") or ""),
        audience=str(claims.get("aud") or ""),
        expires_at=_int_or_none(claims.get("exp")),
        issued_at=_int_or_none(claims.get("iat")),
        jti=str(claims.get("jti") or ""),
        attributes=_claim_attributes(claims),
    )


def _first_claim(claims: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in claims and claims[name] not in (None, ""):
            return claims[name]
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _claim_attributes(claims: dict[str, Any]) -> dict[str, Any]:
    blocked = {
        "sub", "email", "preferred_username", "upn", "role", "roles", "groups",
        "scp", "scope", "scopes", "tenant_id", "tid", "allowed_tenants", "type",
        "iss", "aud", "exp", "iat", "jti", "nbf", "sid",
    }
    return {key: value for key, value in claims.items() if key not in blocked}


class LocalJwtIdentityResolver:
    """Resolver for locally signed Agent Studio access tokens.

    Two kinds of token carry this signature:

    * Agent self-auth tokens (``principal_kind == "service"``, minted by
      ``agent_os.self_auth``). They never reach the browser and their subject may
      be a ``system:*`` id with no user record, so their claims are trusted as is.
    * Browser tokens (``auth.tokens.create_access_token``). Their payload is only
      ``sub``/``sid``/``jti``/``type``/``iat``/``exp``; the returned identity is
      marked ``user_lookup_required`` and must go through
      ``enrich_identity_from_store`` before it is used for authorization. Tokens
      minted before the payload was reduced are treated the same way, so their
      embedded claims are ignored.
    """

    def resolve(self, token: str) -> IdentityContext:
        try:
            from auth.tokens import decode_access_token
            claims = decode_access_token(token)
            if claims.get("principal_kind") == "service":
                return identity_from_access_claims(claims, provider_name="local", auth_method="jwt")
            return _minimal_identity_from_claims(claims)
        except Exception as exc:
            raise IdentityResolutionError(str(exc)) from exc


def _minimal_identity_from_claims(claims: dict[str, Any]) -> IdentityContext:
    if str(claims.get("type") or "access") != "access":
        raise IdentityResolutionError("Not an access token")
    user_id = str(claims.get("sub") or "")
    if not user_id:
        raise IdentityResolutionError("Access token is missing subject")
    tenant_id = _default_tenant()
    return IdentityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        allowed_tenants=(tenant_id,),
        auth_provider="local",
        auth_method="jwt",
        token_type="access",
        expires_at=_int_or_none(claims.get("exp")),
        issued_at=_int_or_none(claims.get("iat")),
        jti=str(claims.get("jti") or ""),
        session_id=str(claims.get("sid") or ""),
        user_lookup_required=True,
    )


async def enrich_identity_from_store(identity: IdentityContext, user: Any = None) -> tuple[IdentityContext, Any]:
    """Fill a minimal Studio identity from the user store.

    Returns ``(identity, user_record)``. Identities that do not need a lookup
    (OIDC, agent service tokens) are returned unchanged with ``None``. Pass an
    already-loaded ``user`` to avoid a second store read. Raises
    ``IdentityResolutionError`` when the subject no longer exists.
    """
    if not identity.user_lookup_required:
        return identity, None
    if user is None:
        from auth.factory import get_store
        store = await get_store()
        user = await store.get_by_id(identity.user_id)
    if user is None:
        raise IdentityResolutionError("Account not found")
    tenant_id = _default_tenant()
    enriched = replace(
        identity,
        email=str(getattr(user, "email", "") or ""),
        roles=_tuple(getattr(user, "role", None)) or ("user",),
        groups=_tuple(getattr(user, "groups", None)),
        tenant_id=tenant_id,
        allowed_tenants=(tenant_id,),
        user_lookup_required=False,
    )
    return enriched, user


class OidcJwksIdentityResolver:
    """OIDC/JWKS access-token resolver for Entra/Okta-compatible providers."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        provider_name: str = "oidc",
        jwks_fetcher: Callable[[], dict[str, Any]] | None = None,
        cache_seconds: int = 300,
        role_claims: tuple[str, ...] = ("roles", "role"),
        group_claims: tuple[str, ...] = ("groups",),
        tenant_claims: tuple[str, ...] = ("tenant_id", "tid"),
        email_claims: tuple[str, ...] = ("email", "preferred_username", "upn"),
    ) -> None:
        if not issuer or not audience or not jwks_url:
            raise IdentityConfigurationError("OIDC issuer, audience, and JWKS URL are required")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_url = jwks_url
        self.provider_name = provider_name
        self.cache_seconds = max(1, int(cache_seconds))
        self.role_claims = role_claims
        self.group_claims = group_claims
        self.tenant_claims = tenant_claims
        self.email_claims = email_claims
        self._jwks_fetcher = jwks_fetcher or self._fetch_jwks
        self._jwks: dict[str, Any] | None = None
        self._jwks_expires_at = 0.0

    @classmethod
    def from_config(cls, provider_name: str = "entra") -> "OidcJwksIdentityResolver":
        try:
            from shared.config import (
                AUTH_OIDC_AUDIENCE,
                AUTH_OIDC_GROUP_CLAIMS,
                AUTH_OIDC_ISSUER,
                AUTH_OIDC_JWKS_CACHE_SECONDS,
                AUTH_OIDC_JWKS_URL,
                AUTH_OIDC_ROLE_CLAIMS,
                AUTH_OIDC_TENANT_CLAIMS,
            )
        except ImportError as exc:
            raise IdentityConfigurationError("OIDC configuration is unavailable") from exc
        return cls(
            issuer=AUTH_OIDC_ISSUER,
            audience=AUTH_OIDC_AUDIENCE,
            jwks_url=AUTH_OIDC_JWKS_URL,
            provider_name=provider_name,
            cache_seconds=AUTH_OIDC_JWKS_CACHE_SECONDS,
            role_claims=_tuple(AUTH_OIDC_ROLE_CLAIMS) or ("roles", "role"),
            group_claims=_tuple(AUTH_OIDC_GROUP_CLAIMS) or ("groups",),
            tenant_claims=_tuple(AUTH_OIDC_TENANT_CLAIMS) or ("tenant_id", "tid"),
        )

    def resolve(self, token: str) -> IdentityContext:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if not kid:
                raise IdentityResolutionError("OIDC token is missing kid")
            key = self._find_key(kid)
            pem = _jwk_rsa_to_pem(key)
            claims = jwt.decode(
                token,
                pem,
                algorithms=["RS256", "RS384", "RS512"],
                options={"verify_aud": False, "verify_iss": False},
            )
            return identity_from_access_claims(
                claims,
                provider_name=self.provider_name,
                auth_method="oidc",
                role_claims=self.role_claims,
                group_claims=self.group_claims,
                tenant_claims=self.tenant_claims,
                email_claims=self.email_claims,
            )
        except IdentityResolutionError:
            raise
        except (JWTError, ValueError, TypeError, KeyError) as exc:
            # Surface token claims so mismatches are immediately obvious in logs
            try:
                unverified = jwt.get_unverified_claims(token)
                t_aud = unverified.get("aud", "?")
                t_iss = unverified.get("iss", "?")
                raise IdentityResolutionError(
                    f"Token validation failed: {exc}. "
                    f"Token aud={t_aud!r} iss={t_iss!r}. "
                    f"Expected aud={self.audience!r} iss={self.issuer!r}. "
                    "If aud is a Graph GUID/URL, set MSAL_SCOPES=api://<backend-client-id>/.default"
                ) from exc
            except IdentityResolutionError:
                raise
            except Exception:
                raise IdentityResolutionError(str(exc)) from exc

    def _find_key(self, kid: str) -> dict[str, Any]:
        jwks = self._get_jwks()
        key = _key_for_kid(jwks, kid)
        if key:
            return key
        self._jwks = None
        key = _key_for_kid(self._get_jwks(), kid)
        if not key:
            raise IdentityResolutionError(f"No JWKS key found for kid '{kid}'")
        return key

    def _get_jwks(self) -> dict[str, Any]:
        now = time.time()
        if self._jwks and now < self._jwks_expires_at:
            return self._jwks
        jwks = self._jwks_fetcher()
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise IdentityResolutionError("JWKS endpoint returned invalid payload")
        self._jwks = jwks
        self._jwks_expires_at = now + self.cache_seconds
        return jwks

    def _fetch_jwks(self) -> dict[str, Any]:
        import httpx
        with httpx.Client(timeout=10) as client:
            resp = client.get(self.jwks_url)
            resp.raise_for_status()
            return resp.json()


def _jwk_rsa_to_pem(jwk: dict[str, Any]) -> str:
    """Convert an RSA JWK (n/e) to PEM — bypasses python-jose's JWK parsing quirks."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    def _b64url_to_int(b64: str) -> int:
        pad = (-len(b64)) % 4
        return int.from_bytes(base64.urlsafe_b64decode(b64 + "=" * pad), "big")

    pub = RSAPublicNumbers(_b64url_to_int(jwk["e"]), _b64url_to_int(jwk["n"])).public_key(default_backend())
    return pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


def _key_for_kid(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def get_access_token_resolver(provider: str | None = None) -> AccessTokenIdentityResolver:
    provider_name = (provider or _configured_provider()).lower()
    if provider_name == "local":
        return LocalJwtIdentityResolver()
    if provider_name in {"microsoft", "entra", "azuread", "azure_ad", "oidc", "okta"}:
        return OidcJwksIdentityResolver.from_config(provider_name=provider_name)
    raise IdentityConfigurationError(f"Unsupported auth provider '{provider_name}'")


def _configured_provider() -> str:
    try:
        from shared.config import AUTH_PROVIDER
        return AUTH_PROVIDER
    except Exception:
        return "local"


def resolve_access_token_identity(token: str, provider: str | None = None) -> IdentityContext:
    """Validate a token. A Studio browser token comes back minimal
    (``user_lookup_required``); use ``resolve_access_token_identity_async`` in
    request paths so the identity is complete."""
    return get_access_token_resolver(provider).resolve(token)


async def resolve_access_token_identity_async(
    token: str, provider: str | None = None
) -> tuple[IdentityContext, Any]:
    """Validate a token and complete it from the user store.

    Returns ``(identity, user_record)``; ``user_record`` is ``None`` when no
    lookup was needed.
    """
    identity = resolve_access_token_identity(token, provider)
    return await enrich_identity_from_store(identity)


def bind_identity_to_tenant(identity: IdentityContext, requested_tenant: str | None) -> IdentityContext:
    tenant_id = requested_tenant or identity.tenant_id
    if tenant_id not in identity.allowed_tenants:
        raise IdentityAuthorizationError("Tenant access denied")
    if tenant_id == identity.tenant_id:
        return identity
    return replace(identity, tenant_id=tenant_id)


def apply_identity_to_state(state: Any, identity: IdentityContext) -> None:
    state.identity = identity
    state.user_id = identity.user_id
    state.email = identity.email
    state.role = identity.roles[0] if identity.roles else "user"
    state.roles = list(identity.roles)
    state.tenant_id = identity.tenant_id
    state.groups = list(identity.groups)
    state.scopes = list(identity.scopes)
    state.allowed_tenants = list(identity.allowed_tenants)
    state.auth_provider = identity.auth_provider
    state.auth_method = identity.auth_method
    state.is_service_principal = identity.is_service_principal
    state.auth_ok = True


def identity_from_state(state: Any, fallback_tenant: str | None = None) -> IdentityContext | None:
    identity = getattr(state, "identity", None)
    if identity:
        return identity
    user_id = getattr(state, "user_id", None)
    if not user_id:
        return None
    tenant_id = getattr(state, "tenant_id", None) or fallback_tenant or _default_tenant()
    return IdentityContext(
        user_id=user_id,
        email=getattr(state, "email", None) or "",
        tenant_id=tenant_id,
        roles=_tuple(getattr(state, "roles", None) or getattr(state, "role", None)) or ("user",),
        groups=_tuple(getattr(state, "groups", None)),
        scopes=_tuple(getattr(state, "scopes", None)),
        allowed_tenants=_tuple(getattr(state, "allowed_tenants", None)) or (tenant_id,),
        auth_provider=getattr(state, "auth_provider", None) or "local",
        auth_method=getattr(state, "auth_method", None) or "jwt",
        is_service_principal=bool(getattr(state, "is_service_principal", False)),
    )


def create_service_identity(
    tenant_id: str,
    service_name: str,
    user_id: str | None = None,
) -> IdentityContext:
    return IdentityContext(
        user_id=user_id or f"system:{service_name}",
        email=f"{service_name}@system.local",
        tenant_id=tenant_id,
        roles=("service",),
        groups=(f"service:{service_name}",),
        allowed_tenants=(tenant_id,),
        auth_provider="service",
        auth_method="service_principal",
        is_service_principal=True,
        service_name=service_name,
    )


def create_dev_identity(tenant_id: str | None = None, user_id: str = "dev") -> IdentityContext:
    resolved_tenant = tenant_id or _default_tenant()
    return IdentityContext(
        user_id=user_id,
        email="dev@local",
        tenant_id=resolved_tenant,
        roles=("admin",),
        allowed_tenants=(resolved_tenant,),
        auth_provider="dev",
        auth_method="disabled",
    )