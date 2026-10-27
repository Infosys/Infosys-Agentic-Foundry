"""Jev (TypeSafe System One) client — curl transport.

Why curl and not the SDK: `typesafe_sdk` is not installed in this deployment and
PyPI is blocked by the corporate proxy. The proxy also injects a CA that Python's
cert store rejects, but `curl` trusts the macOS keychain — so the raw-HTTP curl
path is the only transport that actually reaches Jev here. This mirrors the proven
call in `model_training/finance_candidate_router/eval_jev_direct.py`.

Jev only *decides* — it never generates text. Two primitives:
  - jev_choice(state, criteria, instructions) -> pick 1 of N (type-safe, calibrated)
  - jev_noul(state, instructions)             -> calibrated yes/no

Both fail soft: on any error they return {"ok": False, "error": ...} so callers
(a tool, a verifier skill) can degrade to an LLM/deterministic fallback and never
break the primary path.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 30


def load_api_key() -> str | None:
    """TypeSafe key from env, falling back to agent_os/config.env. None if absent."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    # Walk up to find agent_os/config.env (repo root or CWD).
    for base in (Path.cwd(), *Path(__file__).resolve().parents):
        cfg = base / "agent_os" / "config.env"
        if cfg.exists():
            for line in cfg.read_text().splitlines():
                line = line.strip()
                if line.startswith("TYPESAFE_API_KEY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _post(body: dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """POST to Jev via curl (system keychain trust). Returns parsed JSON or raises."""
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY not found in env or agent_os/config.env")
    payload = json.dumps(body).encode("utf-8")
    cmd = [
        "curl", "-sS", "--max-time", str(timeout), "-X", "POST", API_URL,
        "-H", f"Authorization: Bearer {key}",
        "-H", "Content-Type: application/json",
        "--data-binary", "@-",
    ]
    proc = subprocess.run(cmd, input=payload, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"jev curl failed rc={proc.returncode}: {proc.stderr.decode('utf-8', 'ignore')[:300]}")
    return json.loads(proc.stdout.decode("utf-8"))


def jev_choice(state: Any, criteria: dict[str, str], instructions: str,
               *, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Type-safe calibrated pick of 1 of N. `criteria` = {label: description}.

    Returns {ok, choice, confidence, probabilities} on success; {ok: False, error}
    on any failure (caller decides the fallback). `state` is treated as data.
    """
    if not criteria or len(criteria) < 2:
        return {"ok": False, "error": "jev_choice needs >= 2 criteria"}
    body = {
        "model": model,
        "state": state if isinstance(state, dict) else {"request": str(state)},
        "questions": {"q": {"type": "choice", "criteria": criteria,
                            "instructions": {"goal": instructions}}},
    }
    try:
        ans = _post(body, timeout=timeout)["answers"]["q"]
        return {"ok": True, "choice": ans.get("choice"),
                "confidence": float(ans.get("confidence", 0.0) or 0.0),
                "probabilities": ans.get("probabilities", {}) or {}}
    except Exception as e:  # fail soft
        logger.warning("jev_choice failed (%s) — caller should fall back.", e)
        return {"ok": False, "error": str(e)[:300]}


def jev_noul(state: Any, instructions: str,
             *, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Calibrated yes/no. Returns {ok, noul (bool), confidence} or {ok: False, error}.

    Implemented as a 2-way Choice over yes/no so it works on the same endpoint
    regardless of whether the deployment's model exposes a native `noul` type.
    """
    body = {
        "model": model,
        "state": state if isinstance(state, dict) else {"request": str(state)},
        "questions": {"q": {"type": "choice",
                            "criteria": {"yes": "The statement is TRUE / the condition holds.",
                                         "no": "The statement is FALSE / the condition does not hold."},
                            "instructions": {"goal": instructions}}},
    }
    try:
        ans = _post(body, timeout=timeout)["answers"]["q"]
        choice = ans.get("choice")
        return {"ok": True, "noul": (choice == "yes"),
                "confidence": float(ans.get("confidence", 0.0) or 0.0),
                "probabilities": ans.get("probabilities", {}) or {}}
    except Exception as e:  # fail soft
        logger.warning("jev_noul failed (%s) — caller should fall back.", e)
        return {"ok": False, "error": str(e)[:300]}
