#!/usr/bin/env python3
"""Capture or verify an isolated AgentPro enterprise recovery root."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[2]
STUDIO_ROOT = HARNESS_ROOT / "IAF-Agent-Studio"
for path in (HARNESS_ROOT, STUDIO_ROOT, HARNESS_ROOT / "IAF-Agent-Skills"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_os.safe_path import SecurityError, validated_path  # noqa: E402
from shared.file_utils import atomic_write_json  # noqa: E402
from shared.recovery_live_probe import run_live_probes  # noqa: E402
from shared.recovery_verifier import (  # noqa: E402
    build_manifest,
    merge_live_probe_results,
    persist_report,
    verify_restore,
)


TENANT_ID = os.getenv("TENANT_ID", "company")


def _resolve_data_root(raw: str) -> Path:
    """Validate DATA_ROOT; relative values resolve from IAF-Agent-Studio/."""
    candidate = raw if Path(raw).expanduser().is_absolute() else STUDIO_ROOT / raw
    try:
        return validated_path(candidate, label="DATA_ROOT")
    except SecurityError as exc:
        raise SystemExit(str(exc)) from None


DATA_ROOT_PATH = _resolve_data_root(os.getenv("DATA_ROOT", "../enterprise_root"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="Create a checksum manifest")
    capture.add_argument("--root", type=Path, required=True)
    capture.add_argument("--tenant-id", default=TENANT_ID)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument(
        "--redis-snapshot",
        type=Path,
        help="Optional Redis RDB/AOF snapshot inside the backup root",
    )

    verify = commands.add_parser("verify", help="Verify an isolated restore root")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--tenant-id", default=TENANT_ID)
    verify.add_argument("--active-data-root", type=Path, default=DATA_ROOT_PATH)
    verify.add_argument("--report-dir", type=Path)
    verify.add_argument("--runtime-rpo-target-minutes", type=int, default=15)
    verify.add_argument("--rpo-target-minutes", type=int, default=60)
    verify.add_argument("--rto-target-minutes", type=int, default=240)
    verify.add_argument(
        "--run-live",
        action="store_true",
        help="Run configured read-only HTTP probes against an isolated recovery cell",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "capture":
        manifest = build_manifest(
            args.root.resolve(),
            args.tenant_id,
            redis_snapshot=args.redis_snapshot,
        )
        atomic_write_json(args.output.resolve(), manifest)
        print(json.dumps({
            "status": "captured",
            "output": str(args.output.resolve()),
            "file_count": manifest["file_count"],
            "manifest_hash": manifest["manifest_hash"],
        }, indent=2))
        return 0

    report = verify_restore(
        restore_root=args.root,
        active_data_root=args.active_data_root,
        tenant_id=args.tenant_id,
        reports_dir=None,
        runtime_rpo_target_minutes=max(1, args.runtime_rpo_target_minutes),
        rpo_target_minutes=max(1, args.rpo_target_minutes),
        rto_target_minutes=max(1, args.rto_target_minutes),
    )
    if args.run_live:
        live_checks = run_live_probes(
            base_url=os.getenv("RECOVERY_LIVE_BASE_URL", ""),
            recovery_redis_url=os.getenv("RECOVERY_REDIS_URL", ""),
            production_redis_url=os.getenv("REDIS_URL", ""),
            confirmation=os.getenv("RECOVERY_LIVE_CONFIRMATION", ""),
            tenant_id=args.tenant_id,
            token=os.getenv("RECOVERY_LIVE_TOKEN", ""),
            timeout_seconds=float(os.getenv("RECOVERY_LIVE_TIMEOUT_SECONDS", "5")),
        )
        merge_live_probe_results(report, live_checks)
    if args.report_dir:
        persist_report(args.report_dir, report)
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
