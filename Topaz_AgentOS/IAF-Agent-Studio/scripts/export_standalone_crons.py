#!/usr/bin/env python3
"""Export Redis-only standalone cron jobs to enterprise_root YAML.

Run from the harness root or Studio directory:

    python3 IAF-Agent-Studio/scripts/export_standalone_crons.py
    python3 IAF-Agent-Studio/scripts/export_standalone_crons.py --overwrite

Workstream crons are skipped because their source of truth is already each
workstream YAML file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parents[1]
HARNESS_DIR = STUDIO_DIR.parent
for path in [STUDIO_DIR, HARNESS_DIR / "IAF-Agent-Skills", HARNESS_DIR / "agent_os"]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from shared.config import TENANT_ID  # noqa: E402
from shared.standalone_crons import export_redis_standalone_cron_jobs, standalone_cron_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Redis standalone crons to enterprise_root YAML")
    parser.add_argument("--tenant-id", default=TENANT_ID, help="Tenant to export (default from config)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing YAML files")
    args = parser.parse_args()

    result = export_redis_standalone_cron_jobs(args.tenant_id, overwrite=args.overwrite)
    print(f"target={standalone_cron_dir(args.tenant_id)}")
    print(f"exported={result['total']}")
    for item in result["exported"]:
        print(f"  wrote {item['file']} ({item['job']})")
    if result["skipped"]:
        print(f"skipped={len(result['skipped'])}")
        for item in result["skipped"]:
            print(f"  skipped {item.get('job', '?')}: {item.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
