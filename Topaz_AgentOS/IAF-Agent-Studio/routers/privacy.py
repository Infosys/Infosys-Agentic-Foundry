"""
routers/privacy.py — Login privacy notice + mandatory acknowledgement gate.

PIA Data Privacy controls 1 (Transparency) & 3 (Declaration & Acknowledgement).

Endpoints:
  GET  /auth/privacy/notice   Public: active notice (title, version, markdown, required)
  GET  /auth/privacy/status   Authed: has the current user accepted the current version?
  POST /auth/privacy/accept   Authed: record acceptance to the auth audit sink

All endpoints are inert unless PRIVACY_ACK_REQUIRED is enabled: `notice`/`status`
report `required: false` and the middleware gate never blocks, so the existing
login + SSO flow is unchanged.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth.middleware import require_auth
from privacy import service as privacy_service

logger = logging.getLogger("iaf_server.routers.privacy")

router = APIRouter(tags=["privacy"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/auth/privacy/notice")
async def privacy_notice():
    """Public: the active privacy notice + declaration text and its version."""
    return privacy_service.get_notice(include_body=True).to_public_dict()


@router.get("/auth/privacy/status")
async def privacy_status(request: Request, user: dict = Depends(require_auth)):
    """Authed: whether the current user has acknowledged the current notice version."""
    status = privacy_service.notice_status(user.get("user_id"), user.get("tenant_id"))
    status["user_id"] = user.get("user_id")
    return status


@router.post("/auth/privacy/accept")
async def privacy_accept(request: Request, user: dict = Depends(require_auth)):
    """Authed: record the current user's acceptance of the current notice version.

    Returns 503 if the durable audit sink refused the write; the gate stays
    closed and the client should retry rather than treat the user as accepted.
    """
    try:
        recorded = await privacy_service.record_acceptance(
            user_id=user.get("user_id"),
            tenant_id=user.get("tenant_id"),
            email=user.get("email"),
            ip=_client_ip(request),
        )
    except privacy_service.PrivacyAcceptanceNotPersisted as exc:
        logger.warning("privacy acceptance rejected — audit sink not durable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Privacy acknowledgement could not be recorded durably. Please retry.",
        )
    return {"ok": True, **recorded}
