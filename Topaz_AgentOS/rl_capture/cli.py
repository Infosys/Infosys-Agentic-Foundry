"""Command-line tools for RL/eval capture datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rl_capture.core.quality import assert_quality, validate_export_rows
from rl_capture.core.redaction import redact_rows, scan_pii
from rl_capture.core.resolver import TargetResolver
from rl_capture.core.schema import CaptureMeta, DatasetExport
from rl_capture.exporters.dpo import materialize_dpo_rows_from_targets
from rl_capture.exporters.eval_jsonl import materialize_eval_cases
from rl_capture.exporters.kto import materialize_kto_rows_from_targets
from rl_capture.exporters.rejection_sft import materialize_rejection_sft_rows_from_targets
from rl_capture.exporters.rft import materialize_rft_rows
from rl_capture.exporters.sft import materialize_sft_rows
from rl_capture.exporters.tool_sft import materialize_tool_sft_rows
from rl_capture.store.sqlite_store import RLStore, get_rl_store


EXPORT_KINDS = ("sft", "eval", "dpo", "kto", "rejection_sft", "rft", "tool_sft")
EXPORT_FORMATS = ("chat", "prompt_completion")


@dataclass
class ExportResult:
    id: str
    kind: str
    row_count: int
    file_path: str
    checksum: str
    created_at: str
    params: dict
    redaction: dict = None  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "row_count": self.row_count,
            "file_path": self.file_path,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "params": self.params,
            "redaction": self.redaction or {},
        }


class ResidualPIIError(ValueError):
    """Raised when the PII gate detects unredacted PII after scrubbing."""


def _assert_no_residual_pii(rows: list[dict]) -> None:
    """Hard gate: fail the export if any row still contains detectable PII.

    Redaction should have removed every detectable category; a hit here means a
    regex gap, so we block rather than leak.
    """
    for idx, row in enumerate(rows):
        found = scan_pii(json.dumps(row, ensure_ascii=False))
        if found:
            row_id = str(row.get("id") or (row.get("metadata") or {}).get("trajectory_id") or idx)
            raise ResidualPIIError(
                f"PII gate: row {row_id} still contains {sorted(found)} after redaction"
            )


def run_export(
    store: RLStore,
    *,
    kind: str,
    output_path: str | Path,
    tenant_id: str = "company",
    limit: int = 1000,
    format: str = "chat",
    eval_verdict: str = "",
    since: str = "",
    until: str = "",
    include_trajectory_ids: list[str] | None = None,
    golden_set: str = "",
    trace_destination: str = "",
    trace_route_status: str = "approved",
) -> ExportResult:
    """Materialize + validate + persist an RL/eval dataset.

    Reused by the CLI (`python -m rl_capture.cli export ...`) and the
    `/api/rl-capture/exports` HTTP endpoint so both entry points share one
    canonical export path.
    """
    if kind not in EXPORT_KINDS:
        raise ValueError(f"unknown export kind: {kind!r}")
    if format not in EXPORT_FORMATS:
        raise ValueError(f"unknown export format: {format!r}")

    out_path = Path(output_path)
    trajectory_total = int(store.dataset_health().get("trajectories", limit) or limit)
    trajectories = _filter_trajectories(
        store,
        store.list_trajectories(limit=max(limit, trajectory_total)),
        eval_verdict=eval_verdict,
        since=since,
        until=until,
        include_trajectory_ids=include_trajectory_ids,
        trace_destination=trace_destination,
        trace_route_status=trace_route_status,
    )[:limit]
    resolver = TargetResolver(store)

    require_text = True
    if kind == "sft":
        rows = materialize_sft_rows(trajectories, format=format)
    elif kind == "eval":
        rows = materialize_eval_cases(trajectories)
    elif kind == "dpo":
        rows = materialize_dpo_rows_from_targets(store.list_preference_signals(limit=limit), resolver)
    elif kind == "kto":
        rows = materialize_kto_rows_from_targets(store.list_reward_events(limit=limit), resolver)
    elif kind == "rejection_sft":
        rows = materialize_rejection_sft_rows_from_targets(store.list_reward_events(limit=limit), resolver)
    elif kind == "tool_sft":
        # Tool SFT needs model_calls.tool_calls; hydrate via trajectory_detail (list_trajectories omits incremental calls).
        rewards_by_trajectory = _rewards_by_trajectory(store, limit)
        rows = materialize_tool_sft_rows(
            _hydrate_trajectories(store, trajectories), rewards_by_trajectory
        )
        require_text = False
    else:  # rft
        rewards_by_trajectory = _rewards_by_trajectory(store, limit)
        rows = materialize_rft_rows(trajectories, rewards_by_trajectory)
        require_text = False

    # PII redaction gate: scrub every row, validate, hard-fail if PII survives.
    rows, redaction_summary = redact_rows(rows)
    assert_quality(validate_export_rows(rows, require_text=require_text))
    _assert_no_residual_pii(rows)

    count = _write_jsonl(rows, out_path)

    checksum = _sha256(out_path)
    created_at = datetime.now(timezone.utc).isoformat()
    export_id = f"export_{uuid.uuid4().hex}"
    params = {
        "limit": limit,
        "format": format if kind == "sft" else "",
        "redaction": redaction_summary,
        "eval_verdict": eval_verdict,
        "since": since,
        "until": until,
        "golden_set": golden_set,
        "trace_destination": trace_destination,
        "trace_route_status": trace_route_status if trace_destination else "",
    }
    export_record = DatasetExport(
        id=export_id,
        kind=kind,
        params=params,
        file_path=str(out_path),
        checksum=checksum,
        row_count=count,
        created_at=created_at,
        capture=CaptureMeta(tenant_id=tenant_id),
    )
    store.record_export(export_record)
    return ExportResult(
        id=export_id,
        kind=kind,
        row_count=count,
        file_path=str(out_path),
        checksum=checksum,
        created_at=created_at,
        params=params,
        redaction=redaction_summary,
    )


def _filter_trajectories(
    store: RLStore,
    trajectories: list[dict],
    *,
    eval_verdict: str = "",
    since: str = "",
    until: str = "",
    include_trajectory_ids: list[str] | None = None,
    trace_destination: str = "",
    trace_route_status: str = "approved",
) -> list[dict]:
    # None means "no membership filter"; an explicit empty list means the
    # selected golden set/filter matched zero trajectories.
    allowed_ids = (
        {str(item) for item in include_trajectory_ids if item}
        if include_trajectory_ids is not None
        else None
    )
    if eval_verdict:
        # Latest-verdict-wins: only the most recent evaluator verdict counts; all reward events stay for audit.
        latest: dict[str, tuple[str, str]] = {}  # trajectory_id -> (created_at, label)
        for reward in store.list_reward_events(limit=max(5000, len(trajectories) * 5)):
            if str(reward.get("channel") or "") not in {"evaluator", "shadow_eval"}:
                continue
            target = reward.get("target") or {}
            trajectory_id = str(target.get("trajectory_id") or "")
            if not trajectory_id:
                continue
            created_at = str(reward.get("created_at") or "")
            label = str(reward.get("raw_label") or "").lower()
            prev = latest.get(trajectory_id)
            if prev is None or created_at >= prev[0]:
                latest[trajectory_id] = (created_at, label)
        matching = {tid for tid, (_, label) in latest.items() if label == eval_verdict.lower()}
        allowed_ids = matching if allowed_ids is None else allowed_ids & matching

    if trace_destination:
        routed = set()
        for decision in store.list_trace_route_decisions(destination=trace_destination, limit=10000):
            if trace_route_status and str(decision.get("status") or "").lower() != trace_route_status.lower():
                continue
            trajectory_id = str(decision.get("trajectory_id") or "")
            if trajectory_id:
                routed.add(trajectory_id)
        allowed_ids = routed if allowed_ids is None else allowed_ids & routed

    def keep(row: dict) -> bool:
        trajectory_id = str(row.get("id") or "")
        if allowed_ids is not None and trajectory_id not in allowed_ids:
            return False
        ts = _trajectory_time(row)
        if since and ts and ts < since:
            return False
        if until and ts and ts > until:
            return False
        return True

    return [row for row in trajectories if keep(row)]


def _rewards_by_trajectory(store: RLStore, limit: int) -> dict[str, list[dict]]:
    rewards_by_trajectory: dict[str, list[dict]] = {}
    for reward in store.list_reward_events(limit=limit):
        target = reward.get("target") or {}
        rewards_by_trajectory.setdefault(str(target.get("trajectory_id") or ""), []).append(reward)
    return rewards_by_trajectory


def _hydrate_trajectories(store: RLStore, trajectories: list[dict]) -> list[dict]:
    """Reload each trajectory with its child-table model/tool calls (via detail).

    ``trajectory_detail`` returns a wrapper ``{"trajectory": {...}, "rewards": ...}``;
    we unwrap the nested trajectory dict (which carries model_calls with their
    ``output_messages[*].tool_calls``). Falls back to the raw trajectory when the
    store has no ``trajectory_detail`` (e.g. lightweight test doubles) or returns
    nothing for the id.
    """
    # TODO(perf): this is an N+1 — one full trajectory_detail drill-down per
    # trajectory, repeated in preview_export_counts. For large tool_sft exports
    # (limit up to 100k) add a bulk/lightweight model-call hydration path in the
    # store layer (sqlite_store/pg_store) and use it here instead of per-row detail.
    detail_fn = getattr(store, "trajectory_detail", None)
    if not callable(detail_fn):
        return list(trajectories)
    hydrated: list[dict] = []
    for trajectory in trajectories:
        trajectory_id = str(trajectory.get("id") or "")
        detail = detail_fn(trajectory_id) if trajectory_id else None
        inner = (detail or {}).get("trajectory") if isinstance(detail, dict) else None
        hydrated.append(inner or trajectory)
    return hydrated


def preview_export_counts(
    store: RLStore,
    *,
    limit: int = 1000,
    format: str = "prompt_completion",
    eval_verdict: str = "",
    since: str = "",
    until: str = "",
    include_trajectory_ids: list[str] | None = None,
    trace_destination: str = "",
    trace_route_status: str = "approved",
) -> dict:
    """Return current materialized row counts without writing export files."""
    trajectory_total = int(store.dataset_health().get("trajectories", limit) or limit)
    trajectories = _filter_trajectories(
        store,
        store.list_trajectories(limit=max(limit, trajectory_total)),
        eval_verdict=eval_verdict,
        since=since,
        until=until,
        include_trajectory_ids=include_trajectory_ids,
        trace_destination=trace_destination,
        trace_route_status=trace_route_status,
    )[:limit]
    resolver = TargetResolver(store)
    rewards = store.list_reward_events(limit=limit)
    rewards_by_trajectory: dict[str, list[dict]] = {}
    for reward in rewards:
        target = reward.get("target") or {}
        rewards_by_trajectory.setdefault(str(target.get("trajectory_id") or ""), []).append(reward)

    return {
        "candidate_trajectories": len(trajectories),
        "counts": {
            "sft": len(materialize_sft_rows(trajectories, format=format)),
            "eval": len(materialize_eval_cases(trajectories)),
            "dpo": len(materialize_dpo_rows_from_targets(store.list_preference_signals(limit=limit), resolver)),
            "kto": len(materialize_kto_rows_from_targets(rewards, resolver)),
            "rejection_sft": len(materialize_rejection_sft_rows_from_targets(rewards, resolver)),
            "rft": len(materialize_rft_rows(trajectories, rewards_by_trajectory)),
            "tool_sft": len(materialize_tool_sft_rows(
                _hydrate_trajectories(store, trajectories), rewards_by_trajectory
            )),
        },
    }


def _trajectory_time(row: dict) -> str:
    capture = row.get("capture") or {}
    return str(row.get("started_at") or capture.get("capture_time") or row.get("ended_at") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rl_capture.cli")
    parser.add_argument("--data-root", default="enterprise_root")
    parser.add_argument("--tenant", default="company")
    parser.add_argument("--db-path", default="")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--latest", action="store_true")

    export = sub.add_parser("export")
    export.add_argument("--kind", choices=list(EXPORT_KINDS), required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--format", choices=list(EXPORT_FORMATS), default="chat")
    export.add_argument("--limit", type=int, default=1000)

    args = parser.parse_args(argv)
    store = get_rl_store(data_root=args.data_root, tenant_id=args.tenant, db_path=args.db_path or None)
    if args.command == "inspect":
        return _inspect(store, latest=args.latest)
    if args.command == "export":
        result = run_export(
            store,
            kind=args.kind,
            output_path=args.out,
            tenant_id=args.tenant,
            limit=args.limit,
            format=args.format,
        )
        print(json.dumps(
            {
                "kind": result.kind,
                "rows": result.row_count,
                "path": result.file_path,
                "checksum": result.checksum,
                "redaction": result.redaction,
            },
            indent=2,
        ))
        return 0
    return 1


def _inspect(store, *, latest: bool) -> int:
    health = store.dataset_health()
    print(json.dumps({"health": health}, indent=2, sort_keys=True))
    if latest:
        trajectories = store.list_trajectories(limit=1)
        if trajectories:
            latest_row = trajectories[0]
            print(json.dumps({
                "latest": {
                    "id": latest_row.get("id"),
                    "task": latest_row.get("task"),
                    "fidelity": latest_row.get("fidelity"),
                    "terminal_status": latest_row.get("terminal_status"),
                    "metadata": latest_row.get("metadata"),
                }
            }, indent=2, sort_keys=True))
    return 0


def _write_jsonl(rows: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
