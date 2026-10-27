"""
Observers — deterministic trigger sidecar.

An out-of-process tailer (one per observer) that reads the observer's Headlong
trajectory.jsonl, feeds each new event to the pure TriggerEngine, and POSTs any
resulting ActRequests to the gateway (/api/observers/act) with the X-API-Key.

Out-of-process by design: the fire-and-forget principle — trigger evaluation
never sits in the agent's request path and can never block it.

Run:
    python -m observers.sidecar <observer_name>
Env:
    OBSERVERS_GATEWAY_URL   default http://127.0.0.1:8081
    OBSERVERS_API_KEY       must match the server's key
    OBSERVERS_POLL_SECONDS  default 2.0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from observers.models import ObserverSpec
from observers.store import _SAFE_NAME_RE, get_observer_store
from observers.triggers import CooldownState, TriggerEngine

logger = logging.getLogger("observers.sidecar")

_GATEWAY = os.getenv("OBSERVERS_GATEWAY_URL", "http://127.0.0.1:8081")
_API_KEY = os.getenv("OBSERVERS_API_KEY", "")
_POLL = float(os.getenv("OBSERVERS_POLL_SECONDS", "2.0"))
_APP_DIR = os.getenv("HEADLONG_APP_DIR", str(Path.home() / "headlong"))
# Portable charset for the operator-set app dir (mirrors agent_os.safe_path;
# inlined because the sidecar runs without the repo's agent_os on sys.path).
_APP_DIR_RE = re.compile(r"^[\w .@+()~:/\\\-]{1,4096}$")


def _trajectory_dir(observer: str) -> Path:
    """Validated ``<app_dir>/.identities/<observer>/trajectories`` (CWE-22/73).

    The observer name must be one safe slug segment (same rule the observer
    store applies to spec names) and the result must stay under the app dir.
    """
    if not _SAFE_NAME_RE.fullmatch(observer or ""):
        raise ValueError("unsafe observer name")
    if not _APP_DIR_RE.fullmatch((_APP_DIR or "").strip()):
        raise ValueError("Invalid HEADLONG_APP_DIR")
    identities = Path(_APP_DIR.strip()).expanduser().resolve() / ".identities"
    tdir = (identities / observer / "trajectories").resolve()
    if not tdir.is_relative_to(identities):
        raise ValueError("observer trajectory dir escapes the app dir")
    return Path(str(tdir))


def _latest_trajectory(observer: str) -> Optional[Path]:
    tdir = _trajectory_dir(observer)
    if not tdir.exists():
        return None
    files = sorted(tdir.glob("*/trajectory.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _post_act(payload: dict) -> None:
    """POST one ActRequest to the gateway. Uses httpx if present, else urllib."""
    url = f"{_GATEWAY}/api/observers/act"
    headers = {"Content-Type": "application/json"}
    if _API_KEY:
        headers["X-API-Key"] = _API_KEY
    body = json.dumps(payload).encode()
    try:
        try:
            import httpx  # preferred (already a project dep)
            resp = httpx.post(url, content=body, headers=headers, timeout=30.0)
            logger.info("act -> %s %s", resp.status_code, resp.text[:200])
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                logger.info("act -> %s %s", r.status, r.read()[:200])
    except Exception as exc:
        logger.error("Gateway POST failed: %s", exc)


def _act_payload(act) -> dict:
    return act.model_dump(mode="json") if hasattr(act, "model_dump") else act.dict()


def run_sidecar(observer: str) -> int:
    try:
        _trajectory_dir(observer)  # fail fast on an unsafe name / app dir
    except ValueError as exc:
        logger.error("Refusing to start sidecar: %s", exc)
        return 2
    store = get_observer_store()
    spec: Optional[ObserverSpec] = store.get_spec(observer)
    if spec is None:
        logger.error("Unknown observer '%s' (no spec found)", observer)
        return 2

    engine = TriggerEngine()
    cooldown: CooldownState = {}
    logger.info("Sidecar watching observer '%s' -> gateway %s", observer, _GATEWAY)

    traj: Optional[Path] = None
    offset = 0
    while True:
        if traj is None or not traj.exists():
            traj = _latest_trajectory(observer)
            offset = 0
            if traj is None:
                time.sleep(_POLL)
                continue
            logger.info("Tailing trajectory: %s", traj)

        try:
            with traj.open("r") as fh:
                fh.seek(offset)
                new_lines = fh.readlines()
                offset = fh.tell()
        except FileNotFoundError:
            traj = None
            continue

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            fired, cooldown = engine.match(spec, event, cooldown, now=time.time())
            for act in fired:
                logger.info("TRIGGER fired: skill=%s task=%s", act.skill, act.task[:80])
                _post_act(_act_payload(act))

        time.sleep(_POLL)


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    parser = argparse.ArgumentParser(description="Observer trigger sidecar")
    parser.add_argument("observer", help="observer name (matches a spec)")
    args = parser.parse_args(argv)
    try:
        return run_sidecar(args.observer)
    except KeyboardInterrupt:
        logger.info("Sidecar stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
