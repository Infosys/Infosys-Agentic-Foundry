#!/usr/bin/env python3
"""Seed Trace Value sample trajectories with realistic labels and varied queue sizes."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "IAF-Agent-Studio", ROOT / "IAF-Agent-Skills", ROOT / "agent_os"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rl_capture.core.schema import (  # noqa: E402
    CaptureMeta,
    CaptureFidelity,
    Message,
    ModelCall,
    PolicyRef,
    Role,
    TraceValueAssessment,
    Trajectory,
)
from shared.trace_value_service import store_for_tenant  # noqa: E402

FIXTURE_BATCH = "trace_value_fixture_v3"
FIXTURE_NS = uuid.UUID("8c4f2a91-6d3e-4b17-9f62-1a5e7c3d9048")

DEFAULT_COUNTS: dict[str, int] = {
    "skill": 43,
    "context": 47,
    "memory": 41,
    "golden_eval": 49,
    "model_training": 44,
    "debug_only": 46,
}

CATEGORIES = {
    "skill": "Skill operating rule",
    "context": "Enterprise context signal",
    "memory": "Tenant preference",
    "golden_eval": "Golden regression case",
    "model_training": "Training exemplar",
    "debug_only": "Diagnostic failure trace",
}

LEARNING = {
    "skill": "Keep a consistent validation checklist before executing finance skills on invoice exceptions.",
    "context": "Route AP ownership and policy questions through the enterprise finance context layer.",
    "memory": "Finance reviewers prefer concise exception summaries grouped by business unit.",
    "golden_eval": "Preserve verified invoice reconciliation answers as repeatable regression benchmarks.",
    "model_training": "Retain complete tool-grounded finance responses that cite evidence and next actions.",
    "debug_only": "Archive timeout and connector-fallback traces for engineering diagnosis only.",
}

ROUTE_STATUS = {
    "skill": "pending_review",
    "context": "pending_review",
    "memory": "pending_review",
    "golden_eval": "promoted",
    "model_training": "approved",
    "debug_only": "archived",
}

SKILLS = ("fa_ap", "vendor_mgmt", "invoice_recon", "payment_ops")
AGENTS = ("enterprise_agent", "finance_copilot", "ap_assistant")
REVIEWERS = ("morgan.lee", "priya.shah", "alex.chen", "jordan.kim")

TASK_TEMPLATES: dict[str, list[str]] = {
    "skill": [
        "Review three-way match exception for PO {po} and recommend the next AP action.",
        "Validate vendor onboarding checklist before enabling payment terms for supplier {vendor}.",
        "Check whether invoice {invoice} satisfies the finance skill approval gates.",
        "Apply the AP exception playbook for duplicate receipt lines on PO {po}.",
        "Confirm required evidence is attached before closing exception case {case}.",
    ],
    "context": [
        "Who owns escalation for North America invoice disputes above ${amount}?",
        "Which policy applies to intercompany billing exceptions for entity {entity}?",
        "Map invoice {invoice} to the correct cost center ownership and approver chain.",
        "Explain how corporate AP policy handles partial receipts for supplier {vendor}.",
        "Identify the business unit context for recurring mismatch pattern {pattern}.",
    ],
    "memory": [
        "Summarize month-end close blockers for controller review in business unit {entity}.",
        "Recall the preferred exception summary format for reviewer {reviewer}.",
        "List recurring vendor mismatch patterns observed for supplier {vendor}.",
        "Capture reviewer feedback on how to group open exceptions for {entity}.",
        "Track standing preference for concise variance commentary on invoice {invoice}.",
    ],
    "golden_eval": [
        "Calculate late-payment fee for invoice {invoice} under standard payment terms.",
        "Explain why duplicate payment prevention blocked batch {batch}.",
        "Verify tax handling on credit memo {invoice} against the approved baseline answer.",
        "Confirm accrual treatment for goods-not-invoiced lines on PO {po}.",
        "Produce the canonical response for short-shipment claim {case}.",
    ],
    "model_training": [
        "Reconcile open PO lines against goods receipt for supplier {vendor}.",
        "Draft approval request for credit memo on short-shipment claim {case}.",
        "Summarize overdue invoices for customer {entity} with evidence-backed next steps.",
        "Explain variance between invoice {invoice} and receiving document {po}.",
        "Prepare payment hold recommendation for supplier {vendor} with supporting rationale.",
    ],
    "debug_only": [
        "Investigate agent timeout while querying vendor master for supplier {vendor}.",
        "Trace fallback behavior after ERP connector retry exhaustion on batch {batch}.",
        "Diagnose malformed tool payload while fetching invoice {invoice} details.",
        "Capture partial response after model latency spike during PO {po} lookup.",
        "Record empty retrieval result for exception case {case} despite indexed source data.",
    ],
}

RESPONSE_TEMPLATES: dict[str, list[str]] = {
    "skill": [
        "Checked PO {po}, receipt, and invoice linkage. Missing GR line is the blocker; request receiving correction before approval.",
        "Validated onboarding evidence for {vendor}. Tax form and bank confirmation are complete; payment terms may be activated.",
        "Exception {case} fails the dual-approval gate because supporting approval is absent; route to AP supervisor.",
    ],
    "context": [
        "North America disputes above ${amount} escalate to Regional AP Lead, then Shared Services Controller.",
        "Intercompany exceptions for {entity} follow IC-AP policy section 4.2 with mandatory treasury review.",
        "Invoice {invoice} maps to cost center 4100 owned by Operations Finance with secondary approval from {reviewer}.",
    ],
    "memory": [
        "Grouped open exceptions for {entity} by root cause and aging bucket per the standing reviewer format.",
        "Applied {reviewer}'s preferred concise summary style with business-unit level rollups.",
        "Captured recurring mismatch trend for {vendor}: quantity variance on partial receipts.",
    ],
    "golden_eval": [
        "Late fee on {invoice} is $184.20 based on 2.0% monthly rate and 9 days past terms.",
        "Batch {batch} was blocked because invoice {invoice} matched a previously paid reference.",
        "Credit memo {invoice} applies tax reversal exactly as in the approved golden baseline.",
    ],
    "model_training": [
        "Reconciled PO {po} to receipt and invoice; one line remains open due to partial shipment from {vendor}.",
        "Drafted credit memo approval request for case {case} with cited receipt gap and recommended amount.",
        "Identified 3 overdue invoices for {entity}; oldest is 26 days past due with recommended collections follow-up.",
    ],
    "debug_only": [
        "Vendor master lookup for {vendor} timed out after 30s; agent returned partial context only.",
        "ERP connector exhausted retries on batch {batch}; fallback summary omitted line-level tax detail.",
        "Tool payload for invoice {invoice} was rejected by schema validation on missing currency code.",
    ],
}

VENDORS = ("Acme Industrial", "Northwind Components", "Summit Logistics", "Harbor Materials", "BlueRiver Supply")
ENTITIES = ("NA-Operations", "EMEA-Shared-Services", "APAC-Procurement", "Global-Treasury")
PATTERNS = ("qty-mismatch", "price-variance", "tax-code-drift", "receipt-lag")


def _parse_counts(raw: str | None) -> dict[str, int]:
    if not raw:
        return dict(DEFAULT_COUNTS)
    out = dict(DEFAULT_COUNTS)
    for part in raw.split(","):
        key, _, value = part.partition("=")
        key = key.strip()
        if key in out and value.strip().isdigit():
            out[key] = max(1, int(value.strip()))
    return out


def _fixture_id(kind: str, destination: str, index: int) -> str:
    return uuid.uuid5(FIXTURE_NS, f"{FIXTURE_BATCH}:{kind}:{destination}:{index}").hex


def _existing_fixture_count(store, destination: str) -> int:
    include_debug = destination == "debug_only"
    rows = store.list_trace_value_assessments(
        destination=destination,
        include_debug=include_debug,
        limit=10_000,
    )
    return sum(1 for row in rows if (row.get("metadata") or {}).get("fixture_batch") == FIXTURE_BATCH)


def _destinations(primary: str, index: int) -> dict[str, float]:
    scores = {key: round(0.08 + (index % 7) * 0.01, 2) for key in CATEGORIES}
    scores[primary] = round(0.88 - (index % 12) * 0.015, 2)
    if primary != "debug_only":
        scores["debug_only"] = 0.02
    else:
        scores["debug_only"] = scores[primary]
        scores["skill"] = 0.05
    return scores


def _format_tokens(destination: str, index: int) -> dict[str, str]:
    return {
        "po": f"{440000 + index * 17}",
        "invoice": f"INV-{220000 + index * 13}",
        "vendor": VENDORS[index % len(VENDORS)],
        "entity": ENTITIES[index % len(ENTITIES)],
        "case": f"EXC-{3100 + index}",
        "batch": f"88{index % 10}{index % 7}A",
        "amount": f"{25000 + (index % 9) * 5000}",
        "reviewer": REVIEWERS[index % len(REVIEWERS)],
        "pattern": PATTERNS[index % len(PATTERNS)],
    }


def _pick_text(destination: str, index: int, templates: dict[str, list[str]]) -> str:
    tokens = _format_tokens(destination, index)
    template = templates[destination][index % len(templates[destination])]
    return template.format(**tokens)


def _purge_fixture_rows(store) -> dict[str, int]:
    """Purge demo/fixture rows using the store's active backend.

    Works for both the SQLite ``RLStore`` and the Postgres ``PGRLStore``.
    The Postgres store exposes an ``engine`` with a ``connect()`` context
    manager and a ``placeholder(index)`` helper; the SQLite store is a plain
    file path we can open directly.
    """
    removed = {"trajectories": 0, "assessments": 0, "route_decisions": 0}

    engine = getattr(store, "engine", None)
    if engine is not None:
        # Postgres-backed store: use the shared engine, %s-style placeholders,
        # and let the connection context manager own the transaction.
        with engine.connect() as conn:
            _purge_with_connection(conn, engine.placeholder, removed, commit=False)
        return removed

    # SQLite-backed store.
    conn = sqlite3.connect(str(store.db_path))
    try:
        _purge_with_connection(conn, lambda _index: "?", removed, commit=True)
    finally:
        conn.close()
    return removed


def _purge_with_connection(conn, placeholder, removed: dict[str, int], *, commit: bool) -> dict[str, int]:
    def _rows(sql: str):
        cur = conn.execute(sql, ())
        return cur.fetchall()

    traj_ids: set[str] = set()
    for tid, metadata_raw in _rows("SELECT id, metadata_json FROM trajectories"):
        metadata = json.loads(metadata_raw or "{}")
        if (metadata or {}).get("fixture_batch") == FIXTURE_BATCH:
            traj_ids.add(tid)
            continue
        if "demo" in tid.lower():
            traj_ids.add(tid)
    for aid, trajectory_id, _assessment_raw in _rows(
        "SELECT id, trajectory_id, assessment_json FROM trace_value_assessments"
    ):
        if trajectory_id in traj_ids or "demo" in aid.lower():
            traj_ids.add(trajectory_id)
    for rid, trajectory_id, _decision_raw in _rows(
        "SELECT id, trajectory_id, decision_json FROM trace_route_decisions"
    ):
        if trajectory_id in traj_ids or "demo" in rid.lower():
            traj_ids.add(trajectory_id)

    if not traj_ids:
        return removed

    ids = list(traj_ids)
    placeholders = ",".join(placeholder(i) for i in range(len(ids)))
    params = tuple(ids)
    for table, column in (
        ("trajectory_steps", "trajectory_id"),
        ("model_calls", "trajectory_id"),
        ("tool_calls", "trajectory_id"),
        ("observations", "trajectory_id"),
        ("reward_events", "trajectory_id"),
        ("preference_signals", "trajectory_id"),
        ("candidate_outputs", "trajectory_id"),
        ("evaluator_results", "trajectory_id"),
        ("trace_route_decisions", "trajectory_id"),
        ("trace_value_assessments", "trajectory_id"),
    ):
        conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", params)
    cur = conn.execute(f"DELETE FROM trajectories WHERE id IN ({placeholders})", params)
    rowcount = getattr(cur, "rowcount", None)
    removed["trajectories"] = rowcount if isinstance(rowcount, int) and rowcount >= 0 else len(ids)
    if commit:
        conn.commit()
    return removed


def seed(
    *,
    tenant_id: str,
    counts: dict[str, int],
    promote_every: int,
    reset: bool,
) -> dict[str, int]:
    store = store_for_tenant(tenant_id)
    if reset:
        purged = _purge_fixture_rows(store)
        print("purged", purged)

    now = datetime.now(timezone.utc)
    created: dict[str, int] = {key: 0 for key in CATEGORIES}

    for destination in CATEGORIES:
        target = counts[destination]
        existing = _existing_fixture_count(store, destination)
        needed = max(0, target - existing)
        for offset in range(needed):
            index = existing + offset + 1
            tid = _fixture_id("trajectory", destination, index)
            assessment_id = _fixture_id("assessment", destination, index)
            created_at = (now - timedelta(hours=index + len(CATEGORIES) * 11)).isoformat()
            session_id = f"fin-ap-2026-07-{destination[:3]}-{index:03d}"
            skill = SKILLS[index % len(SKILLS)]
            agent_id = AGENTS[index % len(AGENTS)]
            task = _pick_text(destination, index, TASK_TEMPLATES)
            response = _pick_text(destination, index, RESPONSE_TEMPLATES)
            capture = CaptureMeta(
                adapter_version="agentpro:rl-capture-v1",
                tenant_id=tenant_id,
                agent_id=agent_id,
                source_event_id=tid,
                source_trace_id=tid,
                capture_time=created_at,
            )
            trajectory = Trajectory(
                id=tid,
                session_id=session_id,
                task=task,
                fidelity=CaptureFidelity.TEXT_ONLY,
                terminal_status="success" if destination != "debug_only" else "partial",
                started_at=created_at,
                ended_at=created_at,
                capture=capture,
                metadata={
                    "skill": skill,
                    "source": "studio_capture",
                    "fixture_batch": FIXTURE_BATCH,
                    "trace_value_category": destination,
                },
                model_calls=[
                    ModelCall(
                        id=f"{tid}:model:final",
                        policy=PolicyRef(provider="azure", model="gpt-5.2-chat"),
                        input_messages=[Message(role=Role.USER, content=task)],
                        output_messages=[Message(role=Role.ASSISTANT, content=response)],
                        prompt_tokens=120 + (index % 40),
                        completion_tokens=80 + (index % 25),
                        latency_ms=420 + (index % 90) * 10,
                    )
                ],
            )
            store.record_trajectory(trajectory)
            destinations = _destinations(destination, index)
            verdict = "partial" if destination == "debug_only" else "pass"
            assessment = TraceValueAssessment(
                id=assessment_id,
                trajectory_id=tid,
                input_hash=_fixture_id("hash", destination, index),
                rubric="trace_value_router_v1",
                quality={
                    "score": round(0.88 - (index % 12) * 0.015, 2),
                    "verdict": verdict,
                    "confidence": round(0.91 - (index % 10) * 0.02, 2),
                },
                destinations=destinations,
                learning=LEARNING[destination],
                rationale={
                    key: (
                        f"Strong fit for {CATEGORIES[destination].lower()} based on evidence quality and reuse potential."
                        if key == destination
                        else "Lower routing confidence for this destination."
                    )
                    for key in CATEGORIES
                },
                risks=[
                    "Requires human review before promotion.",
                    "Sensitive finance identifiers were redacted in capture metadata.",
                ],
                created_at=created_at,
                capture=capture,
                metadata={
                    "scope": "tenant",
                    "stability": "stable",
                    "generalizability": "high",
                    "skill": skill,
                    "fixture_batch": FIXTURE_BATCH,
                },
            )
            store.record_trace_value_assessment(assessment)
            if promote_every > 0 and index % promote_every == 0:
                store.record_trace_route_decision({
                    "id": _fixture_id("route", destination, index),
                    "trajectory_id": tid,
                    "assessment_id": assessment_id,
                    "destination": destination,
                    "action": "approve" if destination != "debug_only" else "archive",
                    "status": ROUTE_STATUS[destination],
                    "reviewer": REVIEWERS[index % len(REVIEWERS)],
                    "target_ref": (
                        "golden_finance_ap"
                        if destination == "golden_eval"
                        else ("default" if destination == "model_training" else destination)
                    ),
                    "reason": "Reviewed against finance governance checks and accepted for routing.",
                    "created_at": created_at,
                    "capture": capture,
                    "metadata": {"source": "studio_capture", "fixture_batch": FIXTURE_BATCH},
                })
            created[destination] += 1

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default="company")
    parser.add_argument(
        "--counts",
        default="",
        help="Comma-separated per-category totals, e.g. skill=43,context=47",
    )
    parser.add_argument(
        "--promote-every",
        type=int,
        default=5,
        help="Record a route decision on every Nth seeded row (0 disables).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove prior fixture/demo rows before seeding.",
    )
    args = parser.parse_args()
    counts = _parse_counts(args.counts)
    created = seed(
        tenant_id=args.tenant_id,
        counts=counts,
        promote_every=max(0, args.promote_every),
        reset=args.reset,
    )
    store = store_for_tenant(args.tenant_id)
    summary = store.trace_value_summary()
    print("targets", counts)
    print("seeded", created)
    print("totals", summary["totals"])
    print("by_destination", summary["by_destination"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
