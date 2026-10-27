"""
services/research_synthesis.py — synthesise a research workstream's per-item
results into one consolidated report.

Fired when a `research_orchestrator`-created workstream reaches terminal state
(``status=completed``). Reads each item's resolution + (optionally) its
evidence bundle's top documents, calls the light LLM with a synthesis prompt,
and produces a markdown report with:

  - consensus claims (claims supported by ≥ half the investigators)
  - [CONTESTED] tags where investigators disagree
  - [UNCONFIRMED] tags for one-source claims
  - confidence rating (HIGH / MEDIUM / LOW)
  - inline source attribution per claim

Design notes:
  - Pure module — no router or state.py imports at module load. Lazy-imports
    everything Studio-side so this can be tested standalone.
  - Persists the synthesis to ``workstream.meta.synthesis`` (truncated for the
    YAML) and writes the full markdown to ``workstreams/<name>.synthesis.md``
    for the detail-page viewer.
  - Idempotent — calling twice for the same workstream re-runs synthesis and
    overwrites. Useful for "re-synthesise" UI buttons.
  - Never raises — returns a dict with ``ok: False`` and a reason on failure
    so the caller (hook handler) can log + continue without crashing the
    completion flow.
"""

from __future__ import annotations

import logging
import time
from datetime import timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Hard caps on prompt input to protect the token budget.
_PER_ITEM_RESOLUTION_CHARS = 500
_PER_ITEM_DESC_CHARS = 200
_MAX_ITEMS_IN_PROMPT = 50
_SYNTHESIS_MAX_TOKENS = 2000


def _normalise_status(s: Optional[str]) -> str:
    return (s or "pending").lower()


def _build_synthesis_prompt(ws: dict) -> str:
    """Construct the markdown prompt that goes to the LLM. Items are listed
    in their YAML order — the LLM can cross-reference by id (q1, q2, …)."""
    question = (ws.get("description") or ws.get("display_name") or ws.get("name") or "").strip()
    items = ws.get("items") or []
    if len(items) > _MAX_ITEMS_IN_PROMPT:
        items = items[:_MAX_ITEMS_IN_PROMPT]

    decomposer_confidence = (ws.get("meta") or {}).get("decomposer_confidence", "")

    sections = []
    for idx, it in enumerate(items, 1):
        iid = it.get("id") or f"item-{idx}"
        desc = (it.get("description") or "")[:_PER_ITEM_DESC_CHARS]
        worker = it.get("worker_skill") or ws.get("skill") or "general"
        status = _normalise_status(it.get("status"))
        resolution = (it.get("resolution") or "")[:_PER_ITEM_RESOLUTION_CHARS]
        sections.append(
            f"### Investigator {idx} — `{iid}` (skill: `{worker}`, status: `{status}`)\n"
            f"**Angle:** {desc}\n\n"
            f"**Outcome:** {resolution or '(no resolution captured)'}"
        )

    investigations_block = "\n\n".join(sections) if sections else "(no investigations)"

    prompt = f"""You are synthesising a multi-perspective research run. Read the
question and the per-investigator outcomes below, then produce ONE consolidated
markdown report.

QUESTION
{question}

DECOMPOSER CONFIDENCE: {decomposer_confidence or 'unknown'}

INVESTIGATIONS ({len(items)} total)

{investigations_block}

PRODUCE OUTPUT IN EXACTLY THIS MARKDOWN SHAPE — nothing else, no preamble:

```markdown
# Research Report: {question[:100]}

## Summary
<1–2 paragraph consolidated answer that integrates the strongest signal from
each investigation. If investigations failed or were rejected, say so plainly.>

## Consensus claims
- <claim> (per inv. N, M, …)
- <claim> (per inv. N)

## [CONTESTED]
- <claim A says X (inv. N), claim B says Y (inv. M)>

## [UNCONFIRMED]
- <claim from only one investigator> (per inv. N)

## Confidence: HIGH | MEDIUM | LOW
**Reasoning:** <one sentence on why this confidence level>
```

Rules:
- Never invent claims an investigator didn't make.
- If an investigator's outcome is empty / failed / rejected: count it as
  "no signal" (don't mark it contested).
- If ALL investigations failed: produce a "Research could not converge"
  report with Confidence: LOW and a brief explanation of what went wrong.
- Confidence:
    HIGH   = ≥ 80 percent of investigations agree on the core claims
    MEDIUM = mixed; some consensus + some contested
    LOW    = mostly contested or failed
"""
    return prompt


def _light_llm():
    """Resolve the light (cheap) LLM through the capability-registry's
    model_provider. Lazy import so this module is importable without Studio
    on the path."""
    from iaf_agent_skills.model_provider import default_model_provider
    return default_model_provider.get("light")


def _load_workstream(workstream_name: str, tenant_id: str) -> dict:
    from iaf_agent_skills.workstream_store import WorkstreamStore
    from shared.config import SERVER_DIR, DATA_ROOT
    tenant_root = Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id
    return WorkstreamStore(tenant_root).load(workstream_name)


def _persist_synthesis(workstream_name: str, tenant_id: str, markdown: str,
                        confidence: str, stats: dict) -> Optional[Path]:
    """Write the full markdown next to the workstream YAML, and stash a
    short summary into ws.meta.synthesis."""
    from iaf_agent_skills.workstream_store import WorkstreamStore
    from shared.config import SERVER_DIR, DATA_ROOT
    tenant_root = Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id
    store = WorkstreamStore(tenant_root)
    ws_dir = tenant_root / "workstreams"
    md_path = ws_dir / f"{workstream_name}.synthesis.md"
    try:
        md_path.write_text(markdown, encoding="utf-8")
    except Exception as exc:
        logger.warning("synthesis: failed to write %s: %s", md_path, exc)
        md_path = None

    # Patch meta.synthesis with a digest; the full text lives in the .md alongside.
    try:
        ws = store.load(workstream_name)
        meta = dict(ws.get("meta") or {})
        meta["synthesis"] = {
            "confidence": confidence,
            "stats": stats,
            "preview": markdown[:600],   # short for inline display
            "full_path_rel": str(md_path.relative_to(SERVER_DIR)) if md_path else None,
            "generated_at": __import__("datetime").datetime.now(timezone.utc).isoformat() + "Z",
        }
        store.update_workstream(workstream_name, meta=meta)
    except Exception as exc:
        logger.warning("synthesis: failed to patch meta.synthesis: %s", exc)
    return md_path


def _extract_confidence(markdown: str) -> str:
    """Best-effort confidence extraction from the LLM's output. Default LOW."""
    import re
    m = re.search(r"^##\s+Confidence:\s*(HIGH|MEDIUM|LOW)", markdown, re.MULTILINE | re.IGNORECASE)
    return m.group(1).upper() if m else "LOW"


def _count_marker(markdown: str, marker: str) -> int:
    """Count lines starting with the marker (e.g. '[CONTESTED]' bullets)."""
    return sum(1 for line in markdown.splitlines() if marker in line)


def synthesize_workstream(workstream_name: str, tenant_id: str = "company") -> dict:
    """Generate and persist a synthesis report for a research workstream.

    Args:
        workstream_name: Name of the workstream (no .yaml suffix).
        tenant_id:       Tenant. Defaults to 'company'.

    Returns:
        Dict envelope. On success:
            {ok: True, markdown: str, confidence: str, stats: {...},
             persisted_path: str | None, model: str, duration_ms: int}
        On failure (no exception raised):
            {ok: False, reason: str, workstream_name: str}
    """
    started = time.time()
    try:
        ws = _load_workstream(workstream_name, tenant_id)
    except FileNotFoundError as exc:
        return {"ok": False, "reason": f"workstream not found: {exc}", "workstream_name": workstream_name}
    except Exception as exc:
        logger.exception("synthesize: load failed for %s", workstream_name)
        return {"ok": False, "reason": "load failed", "workstream_name": workstream_name}

    meta = ws.get("meta") or {}
    if meta.get("source") != "research_orchestrator":
        return {"ok": False, "reason": "not a research_orchestrator workstream", "workstream_name": workstream_name}

    prompt = _build_synthesis_prompt(ws)

    try:
        llm = _light_llm()
    except Exception as exc:
        logger.exception("synthesize: light LLM resolution failed")
        return {"ok": False, "reason": "LLM unavailable", "workstream_name": workstream_name}

    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=prompt)])
        markdown = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.exception("synthesize: LLM call failed for %s", workstream_name)
        return {
            "ok": False,
            "reason": "LLM call failed",
            "workstream_name": workstream_name,
        }

    markdown = (markdown or "").strip()
    if not markdown:
        return {"ok": False, "reason": "LLM returned empty synthesis", "workstream_name": workstream_name}

    # Strip an outer ```markdown fence the LLM sometimes wraps around its output.
    if markdown.startswith("```"):
        lines = markdown.splitlines()
        # Drop opening fence (with optional language)
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Drop closing fence
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        markdown = "\n".join(lines).strip()

    confidence = _extract_confidence(markdown)
    stats = {
        "items_total": len(ws.get("items") or []),
        "items_done": sum(1 for it in ws.get("items") or [] if _normalise_status(it.get("status")) == "done"),
        "items_failed": sum(1 for it in ws.get("items") or [] if _normalise_status(it.get("status")) == "failed"),
        "consensus_count": _count_marker(markdown, "(per inv."),
        "contested_count": _count_marker(markdown, "[CONTESTED]"),
        "unconfirmed_count": _count_marker(markdown, "[UNCONFIRMED]"),
    }

    persisted = _persist_synthesis(workstream_name, tenant_id, markdown, confidence, stats)
    duration_ms = int((time.time() - started) * 1000)

    logger.info(
        "synthesize: %s confidence=%s items=%d/%d in %dms",
        workstream_name, confidence, stats["items_done"], stats["items_total"], duration_ms,
    )

    return {
        "ok": True,
        "workstream_name": workstream_name,
        "markdown": markdown,
        "confidence": confidence,
        "stats": stats,
        "persisted_path": str(persisted) if persisted else None,
        "duration_ms": duration_ms,
    }
