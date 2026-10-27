"""
Email router — send emails via Microsoft Graph (O365).

MOCK MODE: Currently logs the email payload and returns success.
To activate real sending, fill in O365 credentials in config.env and
replace the mock block below with the Graph API call.

O365 Graph endpoint:
    POST https://graph.microsoft.com/v1.0/me/sendMail
    Headers: Authorization: Bearer <access_token>
    Body: { "message": { "subject": ..., "body": ..., "toRecipients": [...] } }
"""

import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

from shared.config import DATA_ROOT, SERVER_DIR
from shared.state import ApprovalRequest, approval_store, dashboard

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["email"])
SAP_APPROVAL_THRESHOLD = 100_000.0


class EmailPayload(BaseModel):
    to: List[str]
    cc: Optional[List[str]] = []
    from_address: Optional[str] = ""
    subject: str
    body: str
    body_html: Optional[str] = None   # rich HTML body (preferred if present)


class SapPostPayload(BaseModel):
    company_code: str = ""
    document_type: str = ""
    posting_date: str = ""
    reference: str = ""
    header_text: str = ""
    currency: str = ""
    amount: str = ""
    po_number: str = ""
    gr_number: str = ""
    cost_center: str = ""
    gl_account: str = ""
    line_text: str = ""
    metadata: Optional[dict[str, Any]] = None


def _parse_amount(value: str) -> float:
    try:
        cleaned = str(value or "").replace(",", "").replace("$", "").strip()
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _workstream_store_for(tenant_id: str = "company"):
    from pathlib import Path
    from iaf_agent_skills.workstream_store import WorkstreamStore

    tenant_root = Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id
    return WorkstreamStore(tenant_root)


def _suggested_actions_for_approval() -> list[dict[str, Any]]:
    return [
        {"id": "continue_chat", "label": "Continue", "kind": "chat", "side_effect": False},
        {"id": "approve", "label": "Approve", "kind": "approval", "side_effect": True},
        {"id": "reject", "label": "Reject", "kind": "approval", "side_effect": True},
    ]


async def _create_sap_post_approval(payload: SapPostPayload, request: Request, amount_value: float) -> dict[str, Any]:
    metadata = payload.metadata or {}
    tenant_id = getattr(request.state, "tenant_id", None) or metadata.get("tenant_id") or "company"
    user_id = getattr(request.state, "user_id", None) or metadata.get("user_id") or "workstream_copilot"
    approval_id = str(uuid4())
    context = {
        "resume_kind": "connector_action",
        "action": "post_to_sap",
        "workstream_name": metadata.get("workstream_name") or metadata.get("workstream"),
        "mission_item_id": metadata.get("mission_item_id") or metadata.get("item_id"),
        "amount": amount_value,
        "currency": payload.currency,
        "company_code": payload.company_code,
        "document_type": payload.document_type,
        "reference": payload.reference,
        "po_number": payload.po_number,
        "gr_number": payload.gr_number,
        "payload": payload.model_dump(),
    }
    approval = ApprovalRequest(
        id=approval_id,
        tenant_id=tenant_id,
        user_id=user_id,
        skill="post_to_sap",
        reason=f"SAP posting {payload.reference or '(no reference)'} for {payload.currency or ''} {payload.amount or amount_value} requires approval",
        context=context,
        options=["Approve", "Reject"],
        urgency="high",
        rule_matched=f"SAP posting amount >= {SAP_APPROVAL_THRESHOLD:,.0f}",
        rule_type="threshold",
        sla_minutes=30,
        source="sap_connector",
    )
    await approval_store.create_approval(approval)
    try:
        await dashboard.broadcast({
            "type": "hitl_approval_new",
            "approval_id": approval_id,
            "user_id": user_id,
            "skill": "post_to_sap",
            "reason": approval.reason,
            "urgency": approval.urgency,
            "context": context,
            "sla_minutes": approval.sla_minutes,
            "source": approval.source,
        })
    except Exception:
        pass

    ws_name = context.get("workstream_name")
    item_id = context.get("mission_item_id")
    if ws_name and item_id:
        try:
            store = _workstream_store_for(tenant_id)
            store.update_item(
                ws_name,
                item_id,
                status="awaiting_human",
                escalated_approval_id=approval_id,
                last_approval_context=context,
                last_result_summary=approval.reason,
                last_result_at=datetime.now(timezone.utc).isoformat(),
                suggested_actions=_suggested_actions_for_approval(),
            )
        except Exception as exc:
            logger.warning("Could not link SAP approval to workstream item %s/%s: %s", ws_name, item_id, exc)

    return {
        "success": True,
        "approval_required": True,
        "message": f"SAP post requires approval in Command Center ({approval_id[:8]}).",
        "hitl_approval": {
            "approval_id": approval_id,
            "reason": approval.reason,
            "urgency": approval.urgency,
            "context": context,
            "sla_minutes": approval.sla_minutes,
        },
    }


@router.post("/send-email")
async def send_email(payload: EmailPayload, request: Request):
    """
    Send an email. Currently MOCK — logs and returns success.

    To switch to real O365 Graph sending:
    1. Add to config.env:
         O365_TENANT_ID=<your-tenant-id>
         O365_CLIENT_ID=<your-app-client-id>
         O365_CLIENT_SECRET=<your-client-sensitive>
         O365_SENDER_EMAIL=<mailbox-to-send-from>
    2. Replace the MOCK block below with:

        import httpx, os
        token_url = f"https://login.microsoftonline.com/{os.getenv('O365_TENANT_ID')}/oauth2/v2.0/token"
        token_resp = httpx.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("O365_CLIENT_ID"),
            "client_secret_data": os.getenv("O365_CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
        })
        access_token = token_resp.json()["access_token"]

        graph_payload = {
            "message": {
                "subject": payload.subject,
                "body": {
                    "contentType": "HTML" if payload.body_html else "Text",
                    "content": payload.body_html or payload.body,
                },
                "toRecipients": [{"emailAddress": {"address": a}} for a in payload.to],
                "ccRecipients": [{"emailAddress": {"address": a}} for a in (payload.cc or [])],
            },
            "saveToSentItems": True,
        }
        sender = os.getenv("O365_SENDER_EMAIL")
        send_url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
        resp = httpx.post(send_url, json=graph_payload,
                          headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code != 202:
            return {"success": False, "error": resp.text}
        return {"success": True, "message": f"Email sent to {', '.join(payload.to)}"}
    """

    # Mock: logs the request instead of sending.
    logger.info("📧 [MOCK] Email send request:")
    logger.info(f"   To      : {', '.join(payload.to)}")
    logger.info(f"   CC      : {', '.join(payload.cc or [])}")
    logger.info(f"   From    : {payload.from_address}")
    logger.info(f"   Subject : {payload.subject}")
    logger.info(f"   Body    : {payload.body[:120]}{'...' if len(payload.body) > 120 else ''}")

    return {
        "success": True,
        "mock": True,
        "message": f"[MOCK] Email queued to {', '.join(payload.to)}",
        "recipients": payload.to,
        "subject": payload.subject,
    }


@router.post("/post-to-sap")
async def post_to_sap(payload: SapPostPayload, request: Request):
    """
    Post to SAP. Currently MOCK — logs and returns a synthetic SAP document id.

    This preserves the UX and approval pattern while keeping the demo safe. Replace
    this block with a real SAP OData/BAPI connector when credentials and endpoint
    contracts are available.
    """
    amount_value = _parse_amount(payload.amount)
    if amount_value >= SAP_APPROVAL_THRESHOLD:
        return await _create_sap_post_approval(payload, request, amount_value)

    document_id = f"BP-SAP-MOCK-{uuid4().hex[:10].upper()}"
    logger.info("🧾 [MOCK] SAP post request:")
    logger.info("   Document : %s", document_id)
    logger.info("   Company  : %s", payload.company_code)
    logger.info("   Type     : %s", payload.document_type)
    logger.info("   Ref      : %s", payload.reference)
    logger.info("   Amount   : %s %s", payload.currency, payload.amount)
    logger.info("   PO / GR  : %s / %s", payload.po_number, payload.gr_number)
    return {
        "success": True,
        "mock": True,
        "message": f"[MOCK] SAP post accepted as {document_id}",
        "document_id": document_id,
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "reference": payload.reference,
    }
