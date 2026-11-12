#!/usr/bin/env python3
"""
merge_orphaned_personal_skills.py — offline migration for orphaned personal
skill folders.

Historically a user's personal skills folder was keyed by a filesystem id
(email or user_id). When that key churned — e.g. legacy provisioning minting a
fresh ``uuid4`` on every login (now fixed by ``auth.microsoft._stable_user_id``)
— drafts could land in an alternate-key folder and go invisible in the UI. This
tool merges an orphaned alt-key folder into the canonical one the UI uses.

It only ever COPIES. Nothing is deleted; a folder that already exists in the
destination is kept authoritative and the conflicting source copy is backed up
under ``<dest>/_merged_backup/<ts>/``. Runs dry by default — pass ``--apply`` to
write.

Layout::

    <data-root>/tenants/<tenant>/agents/<agent>/users/<key>/skills/

Usage::

    # See what is there
    python merge_orphaned_personal_skills.py --data-root enterprise_root --scan

    # Dry-run a merge of one key into another
    python merge_orphaned_personal_skills.py --data-root enterprise_root \
        --from 780eab11-....  --to user@example.com

    # Actually write it
    python merge_orphaned_personal_skills.py --data-root enterprise_root \
        --from 780eab11-....  --to user@example.com --apply
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - yaml is a server dep; run in the Studio env
    # Fail BEFORE copying anything. Without PyYAML the _index.yaml merge below is skipped,
    # so folders would be copied but never registered — list_personal_skills() reads only
    # index entries, so the migration would report success while leaving the drafts
    # invisible. A loud exit is correct for an unusable partial migration. (#7)
    raise SystemExit(
        "PyYAML is required to merge personal skill indexes; run this tool in the Studio environment."
    ) from exc


def _users_root(data_root: Path, tenant: str, agent: str) -> Path:
    return Path(data_root).resolve() / "tenants" / tenant / "agents" / agent / "users"


def _skills_dir(data_root: Path, tenant: str, agent: str, key: str) -> Path:
    return _users_root(data_root, tenant, agent) / key / "skills"


def _merge_index_entries(dst_index: dict, src_index: dict) -> dict:
    dst_index.setdefault("skills", {})
    for sname, meta in (src_index.get("skills") or {}).items():
        if sname not in dst_index["skills"]:
            dst_index["skills"][sname] = meta
    return dst_index


def merge_personal_dirs(src_skills: Path, dst_skills: Path, *, apply: bool) -> int:
    """Copy skill folders from src into dst (copy-only). Returns folders merged."""
    if not src_skills.is_dir():
        print(f"  source has no skills/ folder: {src_skills}")
        return 0
    if src_skills.resolve() == dst_skills.resolve():
        print("  source and destination are the same folder — nothing to do")
        return 0

    merged = 0
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for child in sorted(src_skills.iterdir()):
        if not child.is_dir() or child.name in ("_merged_backup", "notifications"):
            continue
        target = dst_skills / child.name
        if not target.exists():
            print(f"  + copy   {child.name}")
            if apply:
                dst_skills.mkdir(parents=True, exist_ok=True)
                # Stage then atomically promote so a crash mid-copy can't leave a
                # half-populated authoritative target. (#5)
                staging = dst_skills / f".{child.name}.tmp-{ts}-{os.getpid()}"
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                try:
                    shutil.copytree(child, staging)
                    if target.exists():
                        shutil.rmtree(staging, ignore_errors=True)
                    else:
                        os.replace(staging, target)
                except Exception:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
            merged += 1
        else:
            print(f"  ~ conflict {child.name} (kept dest; backing up source)")
            if apply:
                backup = dst_skills / "_merged_backup" / ts / child.name
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(child, backup)

    # Merge _index.yaml without overwriting existing entries. PyYAML is guaranteed
    # importable here (the module raises SystemExit at import otherwise), so the merge
    # always runs — copied folders are never left unregistered. (#7)
    src_idx_path = src_skills / "_index.yaml"
    if src_idx_path.exists():
        dst_idx_path = dst_skills / "_index.yaml"
        src_idx = yaml.safe_load(src_idx_path.read_text(encoding="utf-8")) or {}
        dst_idx = {}
        if dst_idx_path.exists():
            dst_idx = yaml.safe_load(dst_idx_path.read_text(encoding="utf-8")) or {}
        merged_idx = _merge_index_entries(dst_idx, src_idx)
        print(f"  merge _index.yaml ({len(merged_idx.get('skills', {}))} entries)")
        if apply:
            dst_skills.mkdir(parents=True, exist_ok=True)
            dst_idx_path.write_text(
                yaml.safe_dump(merged_idx, sort_keys=False), encoding="utf-8"
            )
    return merged


def _count_skills(skills_dir: Path) -> int:
    if not skills_dir.is_dir():
        return 0
    return sum(
        1 for c in skills_dir.iterdir()
        if c.is_dir() and c.name not in ("_merged_backup", "notifications")
    )


def scan(data_root: Path, tenant: str, agent: str) -> None:
    root = _users_root(data_root, tenant, agent)
    if not root.is_dir():
        print(f"No users/ folder at {root}")
        return
    print(f"User folders under {root}:")
    for key_dir in sorted(root.iterdir()):
        if not key_dir.is_dir():
            continue
        n = _count_skills(key_dir / "skills")
        looks_uuid = len(key_dir.name) == 36 and key_dir.name.count("-") == 4
        flag = "  <- uuid-shaped (possible orphan)" if looks_uuid else ""
        print(f"  {key_dir.name:40s} skills={n}{flag}")
    print("\nTo merge an orphan into the canonical key, re-run with --from <key> --to <key>.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default="enterprise_root", help="enterprise_root path")
    ap.add_argument("--tenant", default="company")
    ap.add_argument("--agent", default="enterprise_agent")
    ap.add_argument("--scan", action="store_true", help="list user folders and likely orphans")
    ap.add_argument("--from", dest="src_key", help="alt-key folder to merge FROM")
    ap.add_argument("--to", dest="dst_key", help="canonical-key folder to merge INTO")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    args = ap.parse_args(argv)

    data_root = Path(args.data_root)
    if args.scan:
        scan(data_root, args.tenant, args.agent)
        return 0

    if not args.src_key or not args.dst_key:
        ap.error("provide --from and --to (or --scan)")

    src = _skills_dir(data_root, args.tenant, args.agent, args.src_key)
    dst = _skills_dir(data_root, args.tenant, args.agent, args.dst_key)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] merge '{args.src_key}' -> '{args.dst_key}'")
    print(f"  src: {src}")
    print(f"  dst: {dst}")
    merged = merge_personal_dirs(src, dst, apply=args.apply)
    print(f"Done. {merged} skill folder(s) {'merged' if args.apply else 'would be merged'}.")
    if not args.apply and merged:
        print("Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
