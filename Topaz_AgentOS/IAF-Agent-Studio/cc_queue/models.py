"""
Command Center — Pydantic models for API request/response.
"""

from typing import Optional, List
from pydantic import BaseModel


class QueueItemCreate(BaseModel):
    """Manual creation from dashboard or webhook."""
    title: str
    description: str = ""
    entity_id: str = ""
    priority: str = "P3"               # P1 / P2 / P3
    skill: Optional[str] = None        # Route directly to this skill (bypasses LLM router)
    domain: str = "itops"
    tenant_id: str = "company"
    external_id: Optional[str] = None  # Dedup key. If omitted, server computes a content+time fingerprint.
    bucket_seconds: Optional[int] = None  # Window for auto-computed external_id. Default 3600.
    source: str = "manual"             # manual / webhook / simulated


class IngestWebhook(BaseModel):
    """External system webhook payload (PagerDuty, ServiceNow, etc.)."""
    # An omitted external_id becomes a content+time fingerprint so periodic fires deduplicate.
    external_id: Optional[str] = None
    bucket_seconds: Optional[int] = None  # Window for auto-computed external_id. Default 3600.
    title: str
    description: str = ""
    entity_id: str = ""
    priority: str = "P3"
    domain: str = "itops"
    tenant_id: str = "company"


class HITLResponse(BaseModel):
    """Human response to a HITL approval gate."""
    response: str                      # "Approve" / "Reject" / "Escalate"
    notes: str = ""
