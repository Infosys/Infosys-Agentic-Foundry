"""
ESAA Recommendation Engine — Tier 2 LLM Enrichment
====================================================

Reads ACTIVE memory layers only:
  - knowledge.jsonl  (fed by 3 user-confirmed flows: thumbs-down, /learn, LLM-suggested)
  - history/         (fed by episodic logging after every conversation)

Classifies process improvement opportunities into ESAA categories:

  - Eliminate: Stop doing this (waste, rework, rubber-stamp approvals)
  - Standardize: Do it the same way everywhere (inconsistency, variance)
  - Augment: Keep human but add AI assist (high wait, repetitive patterns)
  - Automate: Remove human entirely (high-success, low-value, read-only)

NOTE: entities.jsonl, decisions.jsonl, implicit_feedback.jsonl are NOT read
because the Context Graph Gardener was removed in the Feb 2026 memory refactor.
Knowledge is now user-confirmed only. If those writers are re-enabled in the
future, add their read paths back here.

Design principles
-----------------
* **Never block** — runs asynchronously, caches results.
* **Never crash** — all LLM calls wrapped in try/except.
* **Evidence-backed** — every recommendation links to source IDs.
* **Bounded** — max 50 entries per memory file, max 3 recs per category.

Usage (called from server.py):
    from esaa_enricher import ESAAEnricher

    enricher = ESAAEnricher(memory_root, llm=azure_mini)
    result = await enricher.analyze()   # returns dict with recommendations
"""

from __future__ import annotations

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter



MAX_ENTRIES_PER_FILE = 50  # Cap memory entries sent to LLM
MAX_RECS_PER_CATEGORY = 3
DETAIL_TRUNCATION = 500   # chars
CATEGORIES = ("eliminate", "standardize", "augment", "automate")



def _read_jsonl(path: Path, max_lines: int = MAX_ENTRIES_PER_FILE) -> List[dict]:
    """Read a JSONL file, return list of dicts. Never crashes."""
    entries = []
    if not path.is_file():
        return entries
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass
    return entries


def _read_history_sessions(history_root: Path, max_sessions: int = 30) -> List[dict]:
    """Read recent session JSONL files from history/. Returns flattened entries."""
    sessions = []
    if not history_root.is_dir():
        return sessions
    try:
        date_dirs = sorted(history_root.iterdir(), reverse=True)[:7]  # last 7 days
        count = 0
        for date_dir in date_dirs:
            if not date_dir.is_dir():
                continue
            for session_file in sorted(date_dir.glob("*.jsonl"), reverse=True):
                if count >= max_sessions:
                    break
                entries = _read_jsonl(session_file, max_lines=5)  # first 5 turns per session
                for e in entries:
                    e["_session_file"] = session_file.name
                sessions.extend(entries)
                count += 1
    except Exception:
        pass
    return sessions



def _extract_exception_patterns(knowledge: List[dict]) -> List[dict]:
    """Find recurring exception patterns from knowledge.jsonl."""
    exceptions = [k for k in knowledge if k.get("type") == "exception"]
    # Group by entity if available
    entity_exceptions: Dict[str, List[dict]] = {}
    for exc in exceptions:
        keys = exc.get("entity_keys", [])
        key = keys[0] if keys else exc.get("summary", "")[:50]
        entity_exceptions.setdefault(key, []).append(exc)
    # Return entities with 2+ exceptions
    patterns = []
    for entity_key, entries in entity_exceptions.items():
        if len(entries) >= 2:
            patterns.append({
                "entity": entity_key,
                "count": len(entries),
                "summaries": [e.get("summary", "")[:200] for e in entries[:5]],
                "ids": [e.get("id", "") for e in entries[:5]],
            })
    return sorted(patterns, key=lambda p: p["count"], reverse=True)[:10]


def _extract_rule_patterns(knowledge: List[dict]) -> List[dict]:
    """Find recurring/conflicting rules from knowledge.jsonl (user-confirmed knowledge)."""
    rules = [k for k in knowledge if k.get("type") in ("rule", "preference", "correction")]
    # Group by skill/scope
    skill_rules: Dict[str, List[dict]] = {}
    for r in rules:
        skill = r.get("scope", {}).get("skill", "") if isinstance(r.get("scope"), dict) else ""
        if not skill:
            # Fallback: extract from applies_to or entity_keys
            applies = r.get("applies_to", {})
            skill = applies.get("entity_type", "general") if isinstance(applies, dict) else "general"
        skill_rules.setdefault(skill, []).append(r)
    patterns = []
    for skill, items in skill_rules.items():
        if len(items) >= 2:
            patterns.append({
                "skill": skill,
                "rule_count": len(items),
                "summaries": [i.get("summary", "")[:200] for i in items[:5]],
                "ids": [i.get("id", "") for i in items[:5]],
                "sources": list(set(i.get("source", "unknown") for i in items)),
                "statuses": list(set(i.get("status", "unknown") for i in items)),
            })
    return sorted(patterns, key=lambda p: p["rule_count"], reverse=True)[:10]


def _extract_workaround_patterns(knowledge: List[dict]) -> List[dict]:
    """Find workarounds — these signal process gaps that need standardization or elimination."""
    workarounds = [k for k in knowledge if k.get("type") == "workaround"]
    # Group by entity if available
    entity_wa: Dict[str, List[dict]] = {}
    for wa in workarounds:
        keys = wa.get("entity_keys", [])
        key = keys[0] if keys else wa.get("summary", "")[:50]
        entity_wa.setdefault(key, []).append(wa)
    patterns = []
    for entity_key, entries in entity_wa.items():
        patterns.append({
            "entity": entity_key,
            "count": len(entries),
            "summaries": [e.get("summary", "")[:200] for e in entries[:5]],
            "ids": [e.get("id", "") for e in entries[:5]],
        })
    return sorted(patterns, key=lambda p: p["count"], reverse=True)[:10]


def _extract_history_patterns(sessions: List[dict]) -> Dict[str, Any]:
    """Extract patterns from conversation history — skill frequency, repeated queries, etc."""
    skill_counter: Counter = Counter()
    tool_counter: Counter = Counter()
    query_themes: List[str] = []

    for entry in sessions:
        skill = entry.get("skill", "")
        if skill:
            skill_counter[skill] += 1
        tools = entry.get("tools_used", [])
        for t in tools:
            tool_counter[t] += 1
        query = entry.get("query", "")
        if query:
            query_themes.append(query[:150])

    return {
        "session_count": len(sessions),
        "top_skills": skill_counter.most_common(5),
        "top_tools": tool_counter.most_common(5),
        "sample_queries": query_themes[:10],
    }



ESAA_SYSTEM_PROMPT = """You are a process optimization analyst for Finance & Accounting operations.

Given evidence from an operational system's memory (exceptions, rules, workarounds, conversation patterns),
classify each finding into exactly ONE ESAA category:

- ELIMINATE: Waste, rework, rubber-stamp approvals, duplicate steps that should be removed
- STANDARDIZE: Inconsistent processes across segments, varying thresholds, non-uniform workflows
- AUGMENT: High human effort that AI can assist with (not replace) — drafting, summarizing, analysis
- AUTOMATE: High-success, low-risk tasks suitable for full end-to-end automation

Return a JSON array of recommendations. Each recommendation:
{
  "category": "eliminate|standardize|augment|automate",
  "title": "Short actionable title (max 80 chars)",
  "detail": "1-2 sentence explanation with specific data",
  "impact": "high|medium|low",
  "evidence_ids": ["id1", "id2"],
  "estimated_savings_desc": "e.g., '$400/month rework cost' or '2 FTE-hours/week'"
}

Rules:
- Return 2-4 recommendations per category (max 12 total)
- Every recommendation MUST cite evidence_ids from the provided data
- If insufficient evidence for a category, return 0 for that category
- Be specific — use entity names, amounts, counts from the evidence
- Return ONLY the JSON array, no prose"""


def _build_enrichment_prompt(
    exception_patterns: List[dict],
    rule_patterns: List[dict],
    workaround_patterns: List[dict],
    history_patterns: Dict[str, Any],
) -> str:
    """Build the user prompt with evidence from active memory layers."""
    sections = []

    if exception_patterns:
        lines = []
        for p in exception_patterns[:6]:
            lines.append(f"  - {p['entity']}: {p['count']} exceptions. "
                         f"Samples: {'; '.join(p['summaries'][:2])}")
        sections.append("## Exception Patterns (from knowledge.jsonl)\n" + "\n".join(lines))

    if rule_patterns:
        lines = []
        for p in rule_patterns[:6]:
            lines.append(f"  - Skill [{p['skill']}]: {p['rule_count']} rules/preferences. "
                         f"Sources: {p['sources']}. "
                         f"Samples: {'; '.join(p['summaries'][:2])}")
        sections.append("## Rule & Preference Patterns (from knowledge.jsonl)\n" + "\n".join(lines))

    if workaround_patterns:
        lines = []
        for p in workaround_patterns[:6]:
            lines.append(f"  - {p['entity']}: {p['count']} workarounds. "
                         f"Samples: {'; '.join(p['summaries'][:2])}")
        sections.append("## Workaround Patterns (from knowledge.jsonl — signals process gaps)\n" + "\n".join(lines))

    if history_patterns and history_patterns.get("session_count", 0) > 0:
        lines = []
        for skill, count in history_patterns.get("top_skills", []):
            lines.append(f"  - Skill '{skill}': used {count} times")
        for tool, count in history_patterns.get("top_tools", []):
            lines.append(f"  - Tool '{tool}': called {count} times")
        if history_patterns.get("sample_queries"):
            lines.append(f"  - Sample queries: {'; '.join(history_patterns['sample_queries'][:3])}")
        if lines:
            sections.append("## Conversation Patterns (from history/)\n" + "\n".join(lines))

    if not sections:
        return "No evidence available from memory layers."

    return "Analyze the following evidence and produce ESAA recommendations:\n\n" + \
           "\n\n".join(sections)



class ESAAEnricher:
    """
    Reads ACTIVE agent memory layers, extracts patterns, and optionally uses
    LLM to produce ESAA recommendations.

    Active memory layers:
      - knowledge.jsonl (user-confirmed: thumbs-down, /learn, LLM-suggested)
      - history/ (episodic session logs)

    Removed (no writers since Feb 2026 memory refactor):
      - entities.jsonl, decisions.jsonl, implicit_feedback.jsonl

    Tier 1: Pure pattern extraction (no LLM, fast)
    Tier 2: LLM-enriched classification (async, cached)
    """

    def __init__(self, memory_root: str | Path, llm=None):
        """
        Args:
            memory_root: Path to agent memory directory
                (e.g., enterprise_root/tenants/company/agents/enterprise_agent/memory)
            llm: Optional LangChain-compatible LLM for Tier 2 enrichment.
                 If None, only Tier 1 (pattern extraction) is available.
        """
        self.memory_root = Path(memory_root)
        self.llm = llm

        # Active memory file paths
        self.knowledge_path = self.memory_root / "context_graph" / "knowledge.jsonl"
        self.history_root = self.memory_root / "history"



    def extract_patterns(self) -> Dict[str, Any]:
        """
        Read active memory layers and extract patterns.
        Returns structured evidence dict. No LLM calls.
        """
        knowledge = _read_jsonl(self.knowledge_path)
        sessions = _read_history_sessions(self.history_root)

        exception_patterns = _extract_exception_patterns(knowledge)
        rule_patterns = _extract_rule_patterns(knowledge)
        workaround_patterns = _extract_workaround_patterns(knowledge)
        history_patterns = _extract_history_patterns(sessions)

        return {
            "exception_patterns": exception_patterns,
            "rule_patterns": rule_patterns,
            "workaround_patterns": workaround_patterns,
            "history_patterns": history_patterns,
            "stats": {
                "knowledge_entries": len(knowledge),
                "knowledge_confirmed": sum(1 for k in knowledge if k.get("status") == "confirmed"),
                "knowledge_pending": sum(1 for k in knowledge if k.get("status") == "pending_review"),
                "session_entries": len(sessions),
            },
        }


    async def analyze(self) -> Dict[str, Any]:
        """
        Full ESAA analysis: extract patterns + LLM classification.
        Returns the complete optimization result ready for the API.
        """
        patterns = self.extract_patterns()

        # Build recommendations — start with Tier 1 (pattern-only)
        tier1_recs = self._patterns_to_recommendations(patterns)

        # If LLM available, run Tier 2 enrichment
        tier2_recs = []
        tier2_status = "skipped"
        if self.llm is not None:
            try:
                tier2_recs = await self._llm_classify(patterns)
                tier2_status = "completed"
            except Exception as e:
                tier2_status = f"error: {str(e)[:200]}"

        # Merge: LLM recs take priority, dedup by title similarity
        merged = self._merge_recommendations(tier1_recs, tier2_recs)

        # Compute summary
        summary = {"eliminate": 0, "standardize": 0, "augment": 0, "automate": 0,
                    "total_estimated_savings": 0}
        for rec in merged:
            cat = rec.get("category", "")
            if cat in summary:
                summary[cat] += 1

        return {
            "recommendations": merged,
            "summary": summary,
            "tier2_status": tier2_status,
            "patterns": patterns.get("stats", {}),
            "computed_at": datetime.now().isoformat(),
        }


    def _patterns_to_recommendations(self, patterns: Dict[str, Any]) -> List[dict]:
        """Convert extracted patterns into rule-based recommendations."""
        recs = []

        # ELIMINATE: Recurring exceptions on same entity
        for p in patterns.get("exception_patterns", [])[:MAX_RECS_PER_CATEGORY]:
            recs.append({
                "category": "eliminate",
                "rule_id": "E1",
                "title": f"Recurring exceptions on {p['entity'][:60]}",
                "detail": (f"{p['count']} exceptions logged for this entity. "
                           f"Sample: {p['summaries'][0][:200]}" if p.get("summaries") else
                           f"{p['count']} exceptions logged for this entity.")[:DETAIL_TRUNCATION],
                "impact": "high" if p["count"] >= 4 else "medium",
                "evidence_ids": p.get("ids", []),
                "evidence_type": "knowledge.jsonl",
                "estimated_savings_desc": f"{p['count']} rework cycles eliminated",
                "source": "tier1",
            })

        # ELIMINATE: Recurring workarounds (signal broken process)
        for p in patterns.get("workaround_patterns", [])[:2]:
            recs.append({
                "category": "eliminate",
                "rule_id": "E2",
                "title": f"Recurring workaround for {p['entity'][:50]}",
                "detail": (f"{p['count']} workarounds logged. "
                           f"Sample: {p['summaries'][0][:200]}" if p.get("summaries") else
                           f"{p['count']} workarounds logged.")[:DETAIL_TRUNCATION],
                "impact": "high" if p["count"] >= 3 else "medium",
                "evidence_ids": p.get("ids", []),
                "evidence_type": "knowledge.jsonl",
                "estimated_savings_desc": f"{p['count']} process gaps to fix",
                "source": "tier1",
            })

        # STANDARDIZE: Multiple rules/preferences for same skill (signals inconsistency)
        for p in patterns.get("rule_patterns", [])[:MAX_RECS_PER_CATEGORY]:
            if p["rule_count"] >= 2:
                recs.append({
                    "category": "standardize",
                    "rule_id": "S1",
                    "title": f"Multiple rules for '{p['skill']}' — potential inconsistency",
                    "detail": (f"{p['rule_count']} rules/preferences from sources {p['sources']}. "
                               f"Sample: {p['summaries'][0][:200]}" if p.get("summaries") else
                               f"{p['rule_count']} rules/preferences.")[:DETAIL_TRUNCATION],
                    "impact": "medium",
                    "evidence_ids": p.get("ids", []),
                    "evidence_type": "knowledge.jsonl",
                    "estimated_savings_desc": "Reduced policy conflicts",
                    "source": "tier1",
                })

        # AUGMENT: High-frequency skills from history (humans using AI assist a lot)
        history = patterns.get("history_patterns", {})
        for skill, count in history.get("top_skills", [])[:MAX_RECS_PER_CATEGORY]:
            if count >= 5:
                recs.append({
                    "category": "augment",
                    "rule_id": "A1",
                    "title": f"High-frequency AI-assist in '{skill}' ({count} sessions)",
                    "detail": f"Skill '{skill}' was used {count} times in recent sessions. "
                              f"Consider proactive templates or pre-filled workflows.",
                    "impact": "medium" if count < 10 else "high",
                    "evidence_ids": [],
                    "evidence_type": "history",
                    "estimated_savings_desc": f"~{count * 2} minutes saved with proactive suggestions",
                    "source": "tier1",
                })

        # AUTOMATE: User-confirmed rules that could be auto-applied
        for p in patterns.get("rule_patterns", []):
            confirmed_count = sum(1 for s in p.get("statuses", []) if s == "confirmed")
            if confirmed_count >= 1 and p["rule_count"] >= 2:
                recs.append({
                    "category": "automate",
                    "rule_id": "T1",
                    "title": f"Auto-apply confirmed rules for '{p['skill']}'",
                    "detail": (f"{p['rule_count']} rules ({confirmed_count} confirmed) for this area. "
                               f"Sample: {p['summaries'][0][:200]}" if p.get("summaries") else
                               f"{p['rule_count']} rules.")[:DETAIL_TRUNCATION],
                    "impact": "medium",
                    "evidence_ids": p.get("ids", []),
                    "evidence_type": "knowledge.jsonl",
                    "estimated_savings_desc": "Full automation of validated rules",
                    "source": "tier1",
                })
                if len([r for r in recs if r["category"] == "automate"]) >= MAX_RECS_PER_CATEGORY:
                    break

        return recs


    async def _llm_classify(self, patterns: Dict[str, Any]) -> List[dict]:
        """Call LLM to classify patterns into ESAA categories."""
        prompt = _build_enrichment_prompt(
            patterns.get("exception_patterns", []),
            patterns.get("rule_patterns", []),
            patterns.get("workaround_patterns", []),
            patterns.get("history_patterns", {}),
        )

        if prompt == "No evidence available from memory layers.":
            return []

        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            messages = [
                SystemMessage(content=ESAA_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = await asyncio.to_thread(
                self.llm.invoke, messages
            )
            text = response.content if hasattr(response, "content") else str(response)

            # Parse JSON from response
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            recs = json.loads(text)
            if not isinstance(recs, list):
                return []

            # Validate and normalize
            valid = []
            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                cat = rec.get("category", "").lower()
                if cat not in CATEGORIES:
                    continue
                valid.append({
                    "category": cat,
                    "rule_id": f"LLM_{cat[0].upper()}",
                    "title": str(rec.get("title", ""))[:80],
                    "detail": str(rec.get("detail", ""))[:DETAIL_TRUNCATION],
                    "impact": rec.get("impact", "medium") if rec.get("impact") in ("high", "medium", "low") else "medium",
                    "evidence_ids": rec.get("evidence_ids", [])[:5],
                    "evidence_type": "llm_analysis",
                    "estimated_savings_desc": str(rec.get("estimated_savings_desc", ""))[:200],
                    "source": "tier2",
                })
            return valid[:12]  # Max 12 total from LLM
        except Exception:
            return []


    def _merge_recommendations(
        self, tier1: List[dict], tier2: List[dict]
    ) -> List[dict]:
        """
        Merge Tier 1 (rule-based) and Tier 2 (LLM) recommendations.
        Tier 2 takes priority. Dedup by title similarity. Cap 3 per category.
        """
        # Start with Tier 2 (higher quality)
        merged: Dict[str, List[dict]] = {c: [] for c in CATEGORIES}
        seen_titles: set = set()

        for rec in tier2:
            cat = rec["category"]
            title_key = rec["title"].lower()[:30]
            if len(merged[cat]) < MAX_RECS_PER_CATEGORY and title_key not in seen_titles:
                merged[cat].append(rec)
                seen_titles.add(title_key)

        # Fill remaining slots with Tier 1
        for rec in tier1:
            cat = rec["category"]
            title_key = rec["title"].lower()[:30]
            if len(merged[cat]) < MAX_RECS_PER_CATEGORY and title_key not in seen_titles:
                merged[cat].append(rec)
                seen_titles.add(title_key)

        # Flatten and sort: high > medium > low within each category
        impact_order = {"high": 0, "medium": 1, "low": 2}
        result = []
        for cat in CATEGORIES:
            items = sorted(merged[cat], key=lambda r: impact_order.get(r.get("impact", "medium"), 1))
            result.extend(items)

        return result
