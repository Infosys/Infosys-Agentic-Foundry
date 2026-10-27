"""Request identity binding and route-level entitlement helpers."""

from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket
from starlette.requests import HTTPConnection

from agent_os.path_ids import validate_path_id
from agent_os.safe_path import SecurityError
from shared.config import AUTH_ENABLED, DATA_ROOT_PATH, TENANT_ID
from shared.filesystem_identity import coerce_filesystem_user_id, filesystem_user_id_from_principal

from .models import Principal, Resource
from .provider import get_entitlement_provider


def principal_from_request(request: Request, fallback_tenant: str | None = None) -> Principal:
    tenant_id = getattr(request.state, "tenant_id", None) or fallback_tenant or TENANT_ID
    if not AUTH_ENABLED:
        try:
            from auth.identity import bind_identity_to_tenant, identity_from_state
            identity = identity_from_state(request.state, tenant_id)
            if identity:
                return bind_identity_to_tenant(identity, tenant_id).to_principal()
        except Exception:
            pass
        return Principal(
            user_id=getattr(request.state, "user_id", None) or "dev",
            email=getattr(request.state, "email", None) or "dev@local",
            tenant_id=tenant_id,
            roles=("admin",),
            groups=(),
            allowed_tenants=(tenant_id,),
        )

    try:
        from auth.identity import bind_identity_to_tenant, identity_from_state
        identity = identity_from_state(request.state, tenant_id)
        if identity:
            return bind_identity_to_tenant(identity, tenant_id).to_principal()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc) or "Tenant access denied") from exc

    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    roles = tuple(filter(None, [getattr(request.state, "role", None) or "user"]))
    groups = tuple(getattr(request.state, "groups", []) or [])
    allowed_tenants = tuple(getattr(request.state, "allowed_tenants", []) or [tenant_id])
    return Principal(
        user_id=user_id,
        email=getattr(request.state, "email", None) or "",
        tenant_id=tenant_id,
        roles=roles,
        groups=groups,
        allowed_tenants=allowed_tenants,
    )


def bind_request_identity(
    request: Request,
    requested_tenant: str | None = None,
    requested_agent: str | None = None,
    requested_user: str | None = None,
) -> tuple[Principal, str, str, str]:
    for _value, _label in (
        (requested_tenant, "tenant_id"),
        (requested_agent, "agent_id"),
        (requested_user, "user_id"),
    ):
        if _value:
            try:
                validate_path_id(_value, _label)
            except SecurityError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid {_label}") from exc
    principal = principal_from_request(request, requested_tenant)
    tenant_id = requested_tenant or principal.tenant_id

    if AUTH_ENABLED and tenant_id not in principal.allowed_tenants:
        raise HTTPException(status_code=403, detail="Tenant access denied")

    agent_id = requested_agent or "enterprise_agent"
    # In production identity is the authenticated principal; the payload user_id is ignored.
    if not AUTH_ENABLED and requested_user:
        user_id = requested_user
    else:
        user_id = coerce_filesystem_user_id(
            user_id=principal.user_id,
            email=principal.email or None,
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    principal = Principal(
        user_id=principal.user_id,
        email=principal.email,
        tenant_id=tenant_id,
        roles=principal.roles,
        groups=principal.groups,
        allowed_tenants=principal.allowed_tenants,
        attributes=principal.attributes,
    )
    return principal, tenant_id, agent_id, user_id


async def requested_tenant(request: Request) -> str:
    """Best-effort read of the tenant a request is asking for.

    Checks the URL path, the query string, then a JSON body (several endpoints carry
    `tenant_id` inside a pydantic model). Multipart bodies are deliberately NOT parsed —
    that would consume the upload stream — so those handlers call `authorise_tenant()`.
    """
    from_path = (getattr(request, "path_params", None) or {}).get("tenant_id")
    if from_path:
        return str(from_path)
    from_query = request.query_params.get("tenant_id")
    if from_query:
        return from_query
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            # Starlette caches the body, so FastAPI can still parse it afterwards.
            payload = await request.json()
        except Exception:
            return ""
        if isinstance(payload, dict):
            candidate = payload.get("tenant_id")
            if isinstance(candidate, str) and candidate:
                return candidate
    return ""


async def require_request_tenant(request: HTTPConnection) -> None:
    """App-wide guard: a request may only name a tenant its caller is entitled to.

    Attached to every API router in server.py. Most handlers take `tenant_id` straight
    from the request; this rejects a foreign one with 403 before the handler runs, so
    those handlers need no edits. Skipped for WebSockets (they bind via
    bind_websocket_identity) and for unauthenticated requests on public routes, which
    the auth middleware already admitted and which carry their own checks (signed
    URLs, API keys).

    Typed `HTTPConnection`, NOT `Request`: router-level dependencies run on WebSocket
    routes too, and FastAPI cannot inject a `Request` into a WebSocket (it would raise
    "missing argument: request" and break the socket). HTTPConnection injects on both;
    on an HTTP route FastAPI still passes the concrete `Request` (so requested_tenant()
    can read a JSON body via .json()), and WebSocket connections return early below.
    """
    if request.scope.get("type") != "http":
        return
    if AUTH_ENABLED and not getattr(request.state, "auth_ok", False):
        return
    requested = await requested_tenant(request)
    if requested:
        bind_request_identity(request, requested_tenant=requested)


def authorise_tenant(request: Request, tenant_id: str) -> str:
    """Explicit guard for multipart/form handlers, which require_request_tenant skips.

    Returns the authorised tenant id; raises 403 if the caller is not entitled.
    """
    _principal, resolved, _agent, _user = bind_request_identity(
        request, requested_tenant=(tenant_id or None)
    )
    return resolved


def require_scoped_identity(
    request: Request,
    *,
    requested_tenant: str | None = None,
    requested_agent: str | None = None,
    requested_user: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    context: dict | None = None,
) -> tuple[Principal, str, str, str]:
    """Bind request identity and optionally enforce one route-level permission.

    This is the canonical adapter for tenant-scoped REST routes. Client-supplied
    tenant/user values remain supported in development mode, while authenticated
    deployments always use the JWT principal and allowed-tenant set.
    """
    bound = bind_request_identity(
        request,
        requested_tenant=requested_tenant,
        requested_agent=requested_agent,
        requested_user=requested_user,
    )
    principal, _tenant_id, _agent_id, _user_id = bound
    permission = (action, resource_type, resource_id)
    if any(permission) and not all(permission):
        raise ValueError("action, resource_type, and resource_id must be supplied together")
    if all(permission):
        enforce_entitlement(
            principal,
            str(action),
            str(resource_type),
            str(resource_id),
            context=context,
        )
    return bound


def authorise_approver(request: Request, approval) -> str:
    """Return the decided_by identity for a caller deciding `approval`, or raise 403.

    The approver is the authenticated principal (a client-sent decided_by is ignored), it
    must belong to the approval's tenant, and policies.yaml must grant it `approve` on
    `approval:<id>` — default deny, so only configured approver groups (and admin) pass.
    """
    _principal, _tenant_id, _agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=getattr(approval, "tenant_id", None) or None,
        action="approve",
        resource_type="approval",
        resource_id=str(getattr(approval, "id", "") or ""),
        context={
            "skill": getattr(approval, "skill", ""),
            "source": getattr(approval, "source", ""),
            "requested_by": getattr(approval, "user_id", ""),
        },
    )
    return user_id


async def bind_websocket_identity(
    websocket: WebSocket,
    *,
    requested_tenant: str | None = None,
    requested_user: str | None = None,
    token: str | None = None,
) -> tuple[Principal, str, str]:
    """Resolve and tenant-bind a WebSocket caller using the shared JWT model.

    WebSockets never pass through ``AuthMiddleware``, so this applies the same
    checks via ``auth.middleware.authenticate_access_token``: signature, revoked
    ``jti``, superseded session, and the user-store lookup that supplies
    email/roles/groups (the browser token carries none of them). Any failure is
    a 401 ``HTTPException``; a foreign tenant is a 403.
    """
    tenant_id = requested_tenant or TENANT_ID
    if not AUTH_ENABLED:
        try:
            from auth.identity import create_dev_identity

            identity = create_dev_identity(tenant_id, user_id=requested_user or "dev")
            principal = identity.to_principal()
            return principal, tenant_id, requested_user or principal.user_id
        except Exception:
            principal = Principal(
                user_id=requested_user or "dev",
                email="dev@local",
                tenant_id=tenant_id,
                roles=("admin",),
                allowed_tenants=(tenant_id,),
            )
            return principal, tenant_id, requested_user or principal.user_id

    access_token = token or websocket.query_params.get("token") or websocket.cookies.get("iaf_access_token") or ""
    if not access_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    from auth.identity import bind_identity_to_tenant
    from auth.middleware import SessionSupersededError, authenticate_access_token

    try:
        resolved, _user = await authenticate_access_token(access_token)
        identity = bind_identity_to_tenant(resolved, tenant_id)
    except SessionSupersededError as exc:
        # SESSION_SUPERSEDED or SESSION_REVOKED (SessionRevokedError subclass).
        raise HTTPException(status_code=401, detail=str(exc) or "SESSION_SUPERSEDED") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc) or "Tenant access denied") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    principal = identity.to_principal()
    return principal, tenant_id, principal.user_id


def enforce_entitlement(
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str,
    context: dict | None = None,
) -> None:
    provider = get_entitlement_provider()
    resource = Resource(resource_type, resource_id, tenant_id=principal.tenant_id)
    decision = provider.check(principal, action, resource, context)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason or "Access denied")


def make_service_principal(
    tenant_id: str,
    service_name: str,
    user_id: str | None = None,
) -> Principal:
    """Create a service principal for non-interactive entry points (cron, queue, HITL resume).

    Service principals enable entitlement enforcement on background execution paths
    that have no HTTP request context. Tenants can grant/restrict service groups
    independently via policies.yaml.

    Args:
        tenant_id: Tenant owning the job/task.
        service_name: One of 'cron', 'queue', 'hitl_resume'.
        user_id: Optional originating user (e.g., job creator). Defaults to 'system:<service_name>'.
    """
    try:
        from auth.identity import create_service_identity
        return create_service_identity(tenant_id, service_name, user_id=user_id).to_principal()
    except Exception:
        pass
    return Principal(
        user_id=user_id or f"system:{service_name}",
        email=f"{service_name}@system.local",
        tenant_id=tenant_id,
        roles=("service",),
        groups=(f"service:{service_name}",),
    )


def make_agent_entitlement_checker(principal: Principal):
    provider = get_entitlement_provider()

    def _checker(action: str, resource_type: str, resource_id: str, context: dict | None = None) -> bool:
        resource = Resource(resource_type, resource_id, tenant_id=principal.tenant_id)
        return provider.check(principal, action, resource, context).allowed

    return _checker
