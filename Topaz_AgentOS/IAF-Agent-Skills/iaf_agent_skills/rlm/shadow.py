"""Phase-0 shadow-mode comparison for RLM.

When enabled (env ``RLM_SHADOW=true``), after a normal turn we ALSO run the RLM analytical
path over the same context+query and log a comparison record — WITHOUT changing what was
served. This produces evidence (answer agreement, sizes, latency, context kept out of window)
before the RLM path is ever served to a user. Pure functions here; the agent calls them
best-effort inside a try/except.
"""
from __future__ import annotations

import json
import os
import re


def word_overlap(a: str, b: str) -> float:
    """Rough agreement signal: Jaccard overlap of lowercased word sets (0.0–1.0)."""
    wa = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    wb = set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _clip(s: str, n: int = 800) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n] + f"… (+{len(s) - n} chars)"


def build_record(*, query: str, normal_answer: str, rlm_answer: str, rlm_metrics: dict,
                 context_chars: int, ts: float, session_id: str = "",
                 rlm_elapsed_ms: int | None = None) -> dict:
    """Build one shadow comparison record (JSON-serializable)."""
    return {
        "ts": round(float(ts), 3),
        "session_id": session_id,
        "query": _clip(query, 400),
        "normal_answer": _clip(normal_answer),
        "rlm_answer": _clip(rlm_answer),
        "normal_len": len(str(normal_answer or "")),
        "rlm_len": len(str(rlm_answer or "")),
        "overlap": round(word_overlap(normal_answer, rlm_answer), 3),
        "context_chars": int(context_chars),
        "rlm_root_iters": (rlm_metrics or {}).get("root_iters"),
        "rlm_leaf_calls": (rlm_metrics or {}).get("leaf_calls"),
        "rlm_elapsed_ms": rlm_elapsed_ms,
    }


def append_jsonl(path: str, record: dict) -> None:
    """Append one record as a JSON line, creating parent dirs as needed.

    ``path`` comes from operator env (``RLM_SHADOW_LOG``) or the agent root; it is
    validated and rebuilt first (raises ``SecurityError`` — the caller is best-effort).
    """
    from agent_os.safe_path import validated_path

    safe_path = str(validated_path(path, label="RLM shadow log"))
    d = os.path.dirname(safe_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(safe_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
