#!/usr/bin/env python3
"""Find and optionally delete orphaned Redis cron/workstream jobs.

Background
----------
Workstream crons are declared inline in each workstream's YAML file
(``enterprise_root/tenants/<tenant>/workstreams/<name>.yaml``); standalone
(non-workstream) crons are declared in
``enterprise_root/tenants/<tenant>/scheduler/jobs/*.yaml``. Both kinds get
reconciled *into* Redis (the runtime scheduler store), but the reconciler is
intentionally one-directional: it only adds/updates Redis from YAML, it never
deletes a Redis job just because its source YAML disappeared (see
``shared.standalone_crons.reconcile_standalone_cron_jobs`` docstring) — this
protects manually-created jobs from being silently wiped.

The downside: if a workstream or standalone-cron YAML file is deleted (e.g.
during a demo-content cleanup) without also deleting its Redis job, the job
keeps firing forever, invisible to anyone reading the git-tracked YAML. This
script finds — and optionally removes — exactly that class of orphan: a job
in Redis whose underlying workstream (for workstream-style jobs) or skill no
longer exists on disk for its tenant.

Usage
-----
    # Dry run (default) - lists what WOULD be deleted, deletes nothing:
    python3 IAF-Agent-Studio/scripts/prune_orphaned_crons.py

    # Scope to one tenant:
    python3 IAF-Agent-Studio/scripts/prune_orphaned_crons.py --tenant-id company

    # Actually delete the orphans found:
    python3 IAF-Agent-Studio/scripts/prune_orphaned_crons.py --delete

    # Skip the "does the skill_name exist anywhere" check (workstream-only):
    python3 IAF-Agent-Studio/scripts/prune_orphaned_crons.py --workstream-only

Run this from the harness root or from ``IAF-Agent-Studio/`` with the same
environment (``DATA_ROOT``, ``TENANT_ID``, Redis connection vars) as the
Studio process whose scheduler state you want to prune — it talks to the
SAME Redis-backed scheduler the running server uses, not a copy.
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

from shared.config import DATA_ROOT_PATH, TENANT_ID  # noqa: E402
from shared.state import cron_scheduler  # noqa: E402


def _workstream_names(tenant_id: str) -> set[str]:
    """Workstream names that still exist on disk for this tenant."""
    ws_dir = DATA_ROOT_PATH / "tenants" / tenant_id / "workstreams"
    if not ws_dir.exists():
        return set()
    return {p.stem for p in ws_dir.glob("*.yaml") if not p.name.startswith("_")}


def _skill_names(tenant_id: str) -> set[str]:
    """Skill ids that still exist on disk for this tenant (directory names)."""
    skills_dir = DATA_ROOT_PATH / "tenants" / tenant_id / "skills"
    if not skills_dir.exists():
        return set()
    return {p.name for p in skills_dir.iterdir() if p.is_dir()}


def find_orphans(tenant_id: str, workstream_only: bool) -> list[dict]:
    """Return job dicts whose backing workstream/skill no longer exists on disk."""
    valid_workstreams = _workstream_names(tenant_id)
    valid_skills = _skill_names(tenant_id) if not workstream_only else None

    orphans: list[dict] = []
    for job in cron_scheduler.list_jobs(tenant_id, enabled_only=False):
        task = (getattr(job, "task", "") or "").strip()
        skill_name = (getattr(job, "skill_name", "") or "").strip()

        # Workstream-style job: skill_name is "mission_mode" and task carries the workstream name.
        if skill_name == "mission_mode":
            if task and task not in valid_workstreams:
                orphans.append({
                    "id": job.id, "name": job.name, "kind": "workstream",
                    "ref": task, "cron": job.cron, "enabled": job.enabled,
                })
            continue

        # Standalone (non-workstream) job: skill_name IS the skill id to run.
        if valid_skills is not None and skill_name and skill_name not in valid_skills:
            orphans.append({
                "id": job.id, "name": job.name, "kind": "standalone-skill",
                "ref": skill_name, "cron": job.cron, "enabled": job.enabled,
            })

    return orphans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", default=TENANT_ID, help="Tenant to scan (default from config)")
    parser.add_argument("--delete", action="store_true", help="Actually delete the orphans found (default: dry run)")
    parser.add_argument("--workstream-only", action="store_true", help="Only check workstream-style jobs, skip standalone skill jobs")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt when --delete is set")
    args = parser.parse_args()

    orphans = find_orphans(args.tenant_id, args.workstream_only)

    if not orphans:
        print(f"No orphaned cron jobs found for tenant={args.tenant_id!r}.")
        return 0

    print(f"Found {len(orphans)} orphaned job(s) for tenant={args.tenant_id!r} "
          f"(no matching workstream/skill on disk):\n")
    for o in orphans:
        state = "enabled" if o["enabled"] else "disabled"
        print(f"  [{o['kind']:16}] {o['name']:40} -> {o['ref']:35} "
              f"cron={o['cron']:15} ({state})  id={o['id']}")

    if not args.delete:
        print("\nDry run only - nothing deleted. Re-run with --delete to remove these.")
        return 0

    if not args.yes:
        reply = input(f"\nDelete these {len(orphans)} job(s) from Redis? [y/N] ").strip().lower()
        if reply != "y":
            print("Aborted - nothing deleted.")
            return 1

    deleted = 0
    for o in orphans:
        if cron_scheduler.delete_job(o["id"]):
            deleted += 1
            print(f"  deleted {o['name']} ({o['id']})")
        else:
            print(f"  FAILED to delete {o['name']} ({o['id']}) - already gone?")

    print(f"\nDeleted {deleted}/{len(orphans)} orphaned job(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
