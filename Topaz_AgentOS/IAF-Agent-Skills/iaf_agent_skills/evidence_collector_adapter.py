"""Evidence Collector capability — Phase 5 facade over the existing evidence path.

Replaces the Batch 1 ``_PassivePlaceholder("evidence_collector")`` entry with
a real adapter so the capability registry can swap evidence backends per
tenant without modifying ``agent.py`` or any router.

Wraps two pieces:
  * ``iaf_agent_skills.document_evidence.EvidenceCollector`` — per-run bundle
    builder used by SkillAgent to record tool calls + document reads.
  * A host-injected ``EvidenceSink`` (see ``agentos_contracts.EvidenceSink``),
    registered via ``iaf_agent_skills.runtime_bridge``. The default Studio sink
    persists/reads bundles from the per-tenant ``evidence.db``. The engine never
    imports Studio directly.

The adapter does NOT change the wire format of the bundle dict; downstream
consumers (Studio routers, dashboards) keep working unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class EvidenceCollectorAdapter:
    """Capability-shaped facade. Composes EvidenceCollector + EvidenceStore."""

    def __init__(self) -> None:
        # Lazily import the collector class so this module is importable in
        # standalone tests without the full document_evidence dependency tree.
        self._collector_cls = None

    def _ensure_collector_cls(self):
        if self._collector_cls is None:
            from iaf_agent_skills.document_evidence import EvidenceCollector  # local import
            self._collector_cls = EvidenceCollector
        return self._collector_cls

    def new_collector(self):
        """Return a fresh EvidenceCollector for a single agent run."""
        cls = self._ensure_collector_cls()
        return cls()

    @staticmethod
    def _sink():
        """Return the host-injected evidence sink, or None. No host import."""
        try:
            from iaf_agent_skills.runtime_bridge import get_evidence_sink

            return get_evidence_sink()
        except Exception:  # pragma: no cover
            return None

    def persist(self, bundle: dict) -> dict:
        """Persist a finished bundle. Returns the same dict augmented with counts."""
        if not bundle:
            return {}
        sink = self._sink()
        if sink is None:  # pragma: no cover - host not always present
            logger.debug("EvidenceCollectorAdapter.persist: no evidence sink registered")
            return bundle
        try:
            tenant_id = str(bundle.get("tenant_id") or "")
            return sink.store_bundle(bundle, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("EvidenceCollectorAdapter.persist failed: %s", exc)
            return bundle

    def fetch_bundle(self, trace_id: str, tenant_id: str = "") -> Optional[dict]:
        """Return the persisted bundle for a trace id, or None."""
        if not trace_id:
            return None
        sink = self._sink()
        if sink is None:  # pragma: no cover
            return None
        try:
            return sink.fetch_bundle(trace_id, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover
            logger.debug("EvidenceCollectorAdapter.fetch_bundle error: %s", exc)
            return None

    def fetch_item(
        self,
        trace_id: str,
        evidence_id: str,
        tenant_id: str = "",
    ) -> Optional[dict]:
        """Return a single evidence item from a bundle, or None."""
        if not trace_id or not evidence_id:
            return None
        sink = self._sink()
        if sink is None:  # pragma: no cover
            return None
        try:
            return sink.fetch_item(trace_id, evidence_id, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover
            logger.debug("EvidenceCollectorAdapter.fetch_item error: %s", exc)
            return None

    def health(self) -> dict[str, Any]:
        """Return sanitized evidence sink diagnostics for capability snapshots."""
        sink = self._sink()
        if sink is None:  # pragma: no cover
            return {"available": False, "error_type": "NoEvidenceSink"}
        try:
            return sink.health()
        except Exception as exc:  # pragma: no cover
            return {"available": False, "error_type": type(exc).__name__}
