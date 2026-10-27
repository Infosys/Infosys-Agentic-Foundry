"""Vision decision client — edge-appliance transport (mirrors jev_client.py).

Why an edge call and not local inference: the AgentOS runtime venv does not carry
the vision model stack (mlx-vlm / torch), and — exactly like Jev — the inference
lives behind a thin HTTP boundary. The edge appliance (jev_vision_demo/server.py,
the `/decide` endpoint) runs the selected-logit readout on the local VLM and
returns a *typed, calibrated* decision. This module is the curl transport to it,
so AgentOS core stays thin and the model is swappable per site.

Two primitives, shaped identically to jev_client so the tools/verifiers are the
same pattern:
  - vision_choice(image_ref, criteria, instructions) -> pick 1 of N over a frame
  - vision_noul(image_ref, instructions)             -> calibrated yes/no over a frame

Both fail soft: on any error they return {"ok": False, "error": ...} so a tool or
verifier can escalate to a human and never break the primary path.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from pathlib import Path

from agent_os.safe_path import SecurityError, confine_to_root, validated_path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EDGE_URL = "http://127.0.0.1:8799/decide"
DEFAULT_TIMEOUT = 30


def load_edge_url() -> str:
    """Edge /decide URL from env, falling back to agent_os/config.env, else default."""
    url = os.environ.get("VISION_EDGE_URL", "").strip()
    if url:
        return url
    for base in (Path.cwd(), *Path(__file__).resolve().parents):
        cfg = base / "agent_os" / "config.env"
        if cfg.exists():
            for line in cfg.read_text().splitlines():
                line = line.strip()
                if line.startswith("VISION_EDGE_URL=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return DEFAULT_EDGE_URL


def load_frame_root() -> Path | None:
    """Approved frame-store root from env / agent_os/config.env, else None.

    Only files under this root may be read+inlined. Without it, nothing local is
    inlined (fail safe) — the ref is passed through for the edge to resolve.
    """
    root = os.environ.get("VISION_FRAME_ROOT", "").strip()
    if not root:
        for base in (Path.cwd(), *Path(__file__).resolve().parents):
            cfg = base / "agent_os" / "config.env"
            if cfg.exists():
                for line in cfg.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("VISION_FRAME_ROOT=") and not line.startswith("#"):
                        root = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            if root:
                break
    if not root:
        return None
    try:
        return validated_path(root, label="VISION_FRAME_ROOT")
    except SecurityError:
        return None


def _encode_image(image_ref: str) -> dict[str, Any]:
    """Inline a frame as a base64 data URL ONLY when it resolves inside the approved
    frame-store root; otherwise pass image_ref through for the edge to resolve.

    event/item input is untrusted: inlining any readable local file would let a crafted
    vision event upload arbitrary host files (e.g. /etc/passwd, tenant secrets). So the
    path is jailed to VISION_FRAME_ROOT (symlinks resolved) before any read.
    """
    root = load_frame_root()
    if root is None:
        return {"image_ref": image_ref}
    try:
        p = Path(image_ref).expanduser()
        resolved = confine_to_root(p if p.is_absolute() else root / p, root, label="image_ref")
        if resolved.is_file():
            raw = resolved.read_bytes()
            return {"image": "data:image/jpeg;base64," + base64.b64encode(raw).decode()}
    except (SecurityError, OSError, ValueError):
        pass
    return {"image_ref": image_ref}


def _post(image_ref: str, question: str, options: list[str],
          *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """POST a frame + typed question to the edge /decide. Returns parsed JSON or raises."""
    body: dict[str, Any] = {"question": question, "options": options, "capture": 384}
    body.update(_encode_image(image_ref))
    payload = json.dumps(body).encode("utf-8")
    cmd = [
        "curl", "-sS", "--max-time", str(timeout), "-X", "POST", load_edge_url(),
        "-H", "Content-Type: application/json", "--data-binary", "@-",
    ]
    proc = subprocess.run(cmd, input=payload, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"vision curl failed rc={proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'ignore')[:300]}"
        )
    out = json.loads(proc.stdout.decode("utf-8"))
    if out.get("error"):
        raise RuntimeError(f"edge error: {str(out['error'])[:200]}")
    if out.get("choice") == "unstable":
        raise RuntimeError("edge returned unstable frame (model nan)")
    return out


def vision_choice(image_ref: str, criteria: dict[str, str], instructions: str,
                  *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Type-safe pick of 1 of N over a frame. `criteria` = {label: description}; the
    labels are the allowed options. `instructions` becomes the question.

    Returns {ok, choice, confidence, probabilities} on success; {ok: False, error}
    on any failure (caller decides the fallback).
    """
    if not criteria or len(criteria) < 2:
        return {"ok": False, "error": "vision_choice needs >= 2 criteria"}
    options = list(criteria.keys())
    try:
        out = _post(image_ref, instructions, options, timeout=timeout)
        return {"ok": True, "choice": out.get("choice"),
                "confidence": float(out.get("confidence", 0.0) or 0.0),
                "probabilities": out.get("probs", {}) or {}}
    except Exception as e:  # fail soft
        logger.warning("vision_choice failed (%s) — caller should escalate.", e)
        return {"ok": False, "error": str(e)[:300]}


def vision_noul(image_ref: str, instructions: str,
                *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Calibrated yes/no over a frame. Returns {ok, noul (bool), confidence} or
    {ok: False, error}. Implemented as a 2-way choice over yes/no, mirroring
    jev_noul so verifiers share one pattern."""
    try:
        out = _post(image_ref, instructions, ["yes", "no"], timeout=timeout)
        return {"ok": True, "noul": (out.get("choice") == "yes"),
                "confidence": float(out.get("confidence", 0.0) or 0.0),
                "probabilities": out.get("probs", {}) or {}}
    except Exception as e:  # fail soft
        logger.warning("vision_noul failed (%s) — caller should escalate.", e)
        return {"ok": False, "error": str(e)[:300]}
