"""Skill *suggestions* for imported taxonomy sections.

A graph says nothing about which AgentOS skill should handle a node, so the import
leaves every ``skill`` blank and only offers ranked hints for a human to accept.
Scoring is a small deterministic TF-IDF cosine between the section text
(domain + section + activities) and each skill's name/description/keywords from
``_index.yaml``. No model call, no network, same answer every time.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List

_STOP = frozenset(
    "a an and are as at be by for from in into is it of on or the to with via per".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")
MIN_SCORE = 0.08


def _tokens(text: str) -> List[str]:
    out = []
    for t in _TOKEN.findall((text or "").lower()):
        if t in _STOP or len(t) < 2:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def _skill_text(name: str, meta: Dict[str, Any]) -> str:
    kws = meta.get("keywords") or []
    return " ".join([name.replace("_", " "), str(meta.get("description") or ""), *map(str, kws)])


def suggest_skills(
    draft_domains: List[Dict[str, Any]],
    skills_index: Dict[str, Dict[str, Any]],
    top_k: int = 3,
) -> None:
    """Annotate every section in ``draft_domains`` with ``suggestions``:
    ``[{"skill": name, "score": 0.0-1.0}]`` (never sets ``skill``)."""
    docs = {n: Counter(_tokens(_skill_text(n, m or {}))) for n, m in skills_index.items()}
    n_docs = max(len(docs), 1)
    df: Counter = Counter()
    for c in docs.values():
        df.update(c.keys())
    idf = {t: math.log((1 + n_docs) / (1 + d)) + 1.0 for t, d in df.items()}

    def vec(counter: Counter) -> Dict[str, float]:
        return {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in counter.items()}

    def norm(v: Dict[str, float]) -> float:
        return math.sqrt(sum(x * x for x in v.values())) or 1.0

    skill_vecs = {n: vec(c) for n, c in docs.items()}
    skill_norms = {n: norm(v) for n, v in skill_vecs.items()}

    for d in draft_domains:
        for s in d.get("sections", []):
            text = " ".join([d.get("name", ""), s.get("name", ""), *s.get("activities", [])])
            q = vec(Counter(_tokens(text)))
            qn = norm(q)
            scored = []
            for n, v in skill_vecs.items():
                dot = sum(w * v.get(t, 0.0) for t, w in q.items())
                if dot:
                    scored.append((dot / (qn * skill_norms[n]), n))
            scored.sort(key=lambda x: (-x[0], x[1]))
            s["suggestions"] = [
                {"skill": n, "score": round(sc, 3)} for sc, n in scored[:top_k] if sc >= MIN_SCORE
            ]
