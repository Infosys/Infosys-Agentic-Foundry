"""Contracts for host-provided runtime services.

These Protocols describe services that an embedding host application (for
example ``IAF-Agent-Studio``) may inject into the engine at startup. The engine
never imports the host; instead the host registers implementations of these
contracts through ``iaf_agent_skills.runtime_bridge``. When no implementation is
registered (standalone / CLI / tests) the engine degrades gracefully.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EvidenceSink(Protocol):
    """Contract for persisting and reading evidence bundles.

    Mirrors the wire shape of the Studio ``EvidenceSinkFanout`` so the engine's
    evidence adapter can delegate without importing Studio.
    """

    def store_bundle(self, bundle: dict, *, tenant_id: str) -> dict:
        """Persist a finished bundle and return it (optionally augmented)."""

    def fetch_bundle(self, trace_id: str, *, tenant_id: str = "") -> dict | None:
        """Return the persisted bundle for a trace id, or None."""

    def fetch_item(self, trace_id: str, evidence_id: str, *, tenant_id: str = "") -> dict | None:
        """Return a single evidence item from a bundle, or None."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""


@runtime_checkable
class MissionRuntimeBridge(Protocol):
    """Contract for host services Mission Mode needs while iterating.

    All methods are best-effort and must never raise into the engine; the host
    implementation owns event-loop scheduling and any FastAPI/WebSocket detail.
    """

    def publish_workstream_event(self, workstream_name: str, event: dict) -> None:
        """Push a live event to subscribers of a workstream (best-effort)."""

    def on_mission_complete(self, workstream_name: str, tenant_id: str) -> None:
        """Fire host-side follow-up work when a workstream completes."""

    def checkpoint_hitl(
        self,
        agent: Any,
        tenant_id: str,
        user_id: str,
        skill_name: str,
        source: str = "chat",
    ) -> dict | None:
        """Persist a pending HITL approval, returning the checkpoint payload."""

    def get_runtime_db(self) -> Any:
        """Return the host's durable workstream runtime DB, or None."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""
