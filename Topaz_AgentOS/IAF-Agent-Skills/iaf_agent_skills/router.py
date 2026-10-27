"""
SkillRouter: Match user queries to skills using LLM-based intent classification.

The router loads a lightweight index file containing skill names and descriptions,
then uses an LLM to classify which skill best matches the user's query.
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
import yaml
from langchain_openai import AzureChatOpenAI

logger = logging.getLogger(__name__)


class SkillRouter:
    """
    Match user queries to skills using LLM-based intent classification.
    
    The index file contains skill definitions with descriptions.
    The LLM classifies which skill best matches the user's query.
    
    Example _index.yaml:
        version: "1.0"
        default_skill: general
        skills:
          dilo:
            description: "Log daily work activities, time tracking, DILO entries"
          weather:
            description: "Weather forecasts, temperature, rain predictions"
          general:
            description: "General assistant for other questions"
    """
    
    def __init__(self, skills_path: str):
        """
        Initialize the router with LLM.

        Args:
            skills_path: Path to skills folder containing _index.yaml
        """
        self.skills_path = Path(skills_path)
        self.index_path = self.skills_path / "_index.yaml"
        self.index = self._load_index()
        self.default_skill = self.index.get("default_skill", "general")
        self.llm = self._create_llm()

        # Skill filtering (set by agent config)
        self._allowed_skills = None  # None = all allowed
        self._denied_skills = None   # None = none denied

        # Personal skills path (set via set_personal_path)
        self._personal_path: Optional[Path] = None
    
    def _create_llm(self) -> AzureChatOpenAI:
        """Create the router LLM through the model-provider adapter."""
        from .model_provider import default_model_provider
        return default_model_provider.get("router")
    
    def _load_index(self) -> Dict[str, Any]:
        """Load _index.yaml file."""
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"Skills index not found at {self.index_path}. "
                f"Create _index.yaml in your skills folder."
            )
        
        with open(self.index_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def reload(self) -> None:
        """Reload the index file (for hot-reloading)."""
        self.index = self._load_index()
        self.default_skill = self.index.get("default_skill", "general")
    
    def set_personal_path(self, personal_path) -> None:
        """
        Set the user's personal skills folder path.
        When set, personal skills are merged on top of global skills on every
        routing call — personal skills take priority if names collide (lets a
        user test a local override before submitting to central).

        Args:
            personal_path: Path to enterprise_root/.../users/{user_id}/skills/
        """
        self._personal_path = Path(personal_path) if personal_path else None

    def _merge_personal_index(self, global_skills: dict) -> dict:
        """
        Merge the user's personal _index.yaml on top of the global skill map.
        Personal skills are only included if their SKILL.md file actually exists
        (guards against stale index entries after manual deletions).
        """
        if not self._personal_path:
            return global_skills

        personal_index_path = self._personal_path / "_index.yaml"
        if not personal_index_path.exists():
            return global_skills

        try:
            personal_index = yaml.safe_load(personal_index_path.read_text(encoding='utf-8')) or {}
        except Exception:
            return global_skills

        merged = dict(global_skills)  # copy — don't mutate global
        for name, meta in personal_index.get("skills", {}).items():
            skill_file = self._personal_path / name / "SKILL.md"
            if not skill_file.exists():
                continue  # skip stale entries
            # Mark as personal so the loader knows where to find it
            entry = dict(meta)
            entry["_personal"] = True
            merged[name] = entry

        return merged

    def set_skill_filter(self, allowed: list = None, denied: list = None):
        """
        Set skill filtering for this router.
        
        Args:
            allowed: List of skill names to allow (allowlist mode)
            denied: List of skill names to deny (denylist mode)
            
        If both are None, all skills are available.
        If allowed is set, only those skills are available.
        If denied is set, all except those skills are available.
        """
        self._allowed_skills = allowed
        self._denied_skills = denied
    
    def _get_filtered_skills(self) -> dict:
        """
        Get skills filtered by allowlist/denylist.
        Personal skills (if personal_path is set) are merged on top of global.

        Returns:
            Dict of skill_name -> skill_info for allowed skills only
        """
        global_skills = self.index.get("skills", {})
        all_skills = self._merge_personal_index(global_skills)

        # No filter = all skills
        if self._allowed_skills is None and self._denied_skills is None:
            return all_skills

        # Allowlist mode
        if self._allowed_skills is not None:
            return {k: v for k, v in all_skills.items() if k in self._allowed_skills}

        # Denylist mode
        if self._denied_skills is not None:
            return {k: v for k, v in all_skills.items() if k not in self._denied_skills}

        return all_skills
    
    def _shortlist_by_taxonomy(self, skills: dict, taxonomy_hints: list | None) -> tuple[dict, str]:
        """Narrow the catalogue to the domain(s) the taxonomy signal points at.

        Showing the LLM every skill is the main driver of look-alike mis-routes: with
        ~180 one-line descriptions, several finance entries read almost identically and
        there is no way for the model to say "none of these". When the L5 signal is
        confident about a domain we keep that domain *whole* — every skill in the hinted
        skills' categories, plus the hinted skills and the default skill — and drop the
        unrelated domains.

        Deliberately category-wide rather than "just the hinted skills": the hints name
        domain anchors (e.g. fa_ap), not the executable skill, so narrowing to the hits
        themselves would discard the very skill that should win. This trades a modest
        precision gain for no loss of recall inside the chosen domain.

        Returns (skills, reason) and falls back to the full catalogue whenever the
        shortlist would be too small, too large to matter, or the signal is weak.
        """
        if not taxonomy_hints or os.getenv("ROUTER_SHORTLIST_ENABLED", "true").lower() != "true":
            return skills, ""
        try:
            min_score = float(os.getenv("ROUTER_SHORTLIST_MIN_SCORE", "0.90"))
            min_skills = int(os.getenv("ROUTER_SHORTLIST_MIN_SKILLS", "8"))
        except ValueError:
            return skills, ""

        strong = [h for h in taxonomy_hints if float(h.get("score", 0) or 0) >= min_score]
        if not strong:
            return skills, ""

        cats = {
            skills[n].get("category")
            for n in (h.get("skill") for h in strong)
            if n in skills and isinstance(skills[n], dict) and skills[n].get("category")
        }
        if not cats:
            return skills, ""

        keep = {
            name for name, info in skills.items()
            if isinstance(info, dict) and info.get("category") in cats
        }
        keep.update(h.get("skill") for h in strong if h.get("skill") in skills)
        if self.default_skill in skills:
            keep.add(self.default_skill)

        # Too small => likely a bad signal; ~no reduction => not worth the risk.
        if len(keep) < min_skills or len(keep) > 0.7 * len(skills):
            logger.info(
                "Router shortlist skipped (%d of %d skills, categories=%s)",
                len(keep), len(skills), sorted(cats),
            )
            return skills, ""

        reason = (
            f"(catalogue narrowed to {', '.join(sorted(cats))} — "
            f"{len(keep)} of {len(skills)} skills — by the semantic taxonomy signal)"
        )
        logger.info(
            "Router shortlist ACTIVE: %d of %d skills, categories=%s, anchors=%s",
            len(keep), len(skills), sorted(cats),
            [f"{h.get('skill')}={float(h.get('score', 0) or 0):.3f}" for h in strong],
        )
        return {k: v for k, v in skills.items() if k in keep}, reason

    def _format_skills_for_prompt(self, taxonomy_hints: list | None = None) -> str:
        """Format skills grouped by category for the LLM prompt.
        Category labels and order are read from _index.yaml — no hardcoding here.
        Grouping prevents the LLM from confusing skills that share surface-level
        keywords but serve different audiences (e.g. 'ar_ops' for daily BAU work
        vs 'i2c_consultant' for Oracle Cloud Fusion implementation projects).
        Skills without a 'category' field appear under an unlabelled 'other' group.

        When `taxonomy_hints` carry a confident domain signal the catalogue is first
        narrowed to that domain (see _shortlist_by_taxonomy).
        """
        skills  = self._get_filtered_skills()
        skills, _shortlist_note = self._shortlist_by_taxonomy(skills, taxonomy_hints)
        labels  = self.index.get("category_labels", {})
        order   = self.index.get("category_order", [])    # preferred section order

        # Bucket skills by their category field
        groups: dict = {}
        for name, info in skills.items():
            cat = (info.get("category", "other") if isinstance(info, dict) else "other")
            groups.setdefault(cat, []).append((name, info))

        # Ordered categories first, then any not listed in category_order
        cats = order + [c for c in groups if c not in order]

        lines = []
        for cat in cats:
            if cat not in groups:
                continue
            header = labels.get(cat, cat.upper())   # label from yaml, fallback to category name
            lines.append(f"\n## {header}")
            for name, info in groups[cat]:
                desc = (info.get("description", "No description") if isinstance(info, dict) else "No description")
                lines.append(f"- {name}: {desc}")

        if _shortlist_note:
            lines.append(f"\n{_shortlist_note}")
        return "\n".join(lines)
    
    def match(self, query: str, current_skill: str = None, last_response: str = None,
               return_details: bool = False, pending_action: dict = None,
               entity_hint: str = None, entity_confidence: float = 0.0,
               process_hint: str = None, process_matches: list = None,
               signals_agree: bool = None,
               taxonomy_hints: list = None) -> str:
        """
        Match a user query to the best skill using LLM-first semantic classification.
        
        Uses dual-signal routing:
          Signal 1 (entity_hint): WHO the query is about  (entity → tree walk)
          Signal 2 (process_hint): WHAT process it refers to  (taxonomy keyword match)
        
        Priority order:
        1. LLM semantic routing (includes entity + process signals, confirmation detection)
        2. Keyword fallback (only when LLM is uncertain or fails)
        
        Args:
            query: User's input query
            current_skill: The skill currently active (for continuation detection)
            last_response: The last assistant response (for context-aware routing)
            return_details: If True, returns dict with skill, method, confidence, alternatives
            pending_action: Optional dict with {skill, original_query, action_summary, timestamp}
            entity_hint: Signal 1 — skill name from entity ontology resolution.
            entity_confidence: Cosine similarity score of the entity match (0.0-1.0).
            process_hint: Signal 2 — skill name from taxonomy keyword matching.
            process_matches: List of taxonomy nodes matched by query keywords.
            signals_agree: True if both signals point to same skill, False if conflict, None if partial.
            
        Returns:
            Name of the matched skill, or dict with routing details if return_details=True
        """
        import json as _json
        
        skills = self._get_filtered_skills()
        skill_names = list(skills.keys())
        
        _detected = set()
        if entity_hint:
            _detected.add(entity_hint)
        if process_hint:
            _detected.add(process_hint)
        if process_matches:
            for _m in process_matches:
                _sk = _m.get("skill_name")
                if _sk:
                    _detected.add(_sk)

        routing_result = {
            "skill": self.default_skill,
            "method": "default",
            "confidence": 1.0,
            "is_continuation": False,
            "is_confirmation": False,
            "entity_hint": entity_hint,
            "entity_confidence": entity_confidence,
            "process_hint": process_hint,
            "signals_agree": signals_agree,
            "alternatives": [],
            "detected_domains": list(_detected),
            "execution_mode": "planned" if len(_detected) > 1 else "react",
            "complexity_class": "multi_domain" if len(_detected) > 1 else "simple",
            "mode_hint": "planned" if len(_detected) > 1 else "react",
            "search_variants": [],
        }
        
        if not skill_names:
            return routing_result if return_details else self.default_skill
        
        query_lower = query.lower().strip()
        logger.debug("Router checking query: '%s'", query_lower)
        logger.debug("Available skills: %s, current: %s", skill_names, current_skill)
        if pending_action:
            logger.debug("Pending action from skill '%s': %s", pending_action.get('skill'), pending_action.get('action_summary', '')[:50])
        
        truncated_response = last_response[-500:] if last_response and len(last_response) > 500 else (last_response or "")
        
        ontology_context = ""
        _entity_part = ""
        _process_part = ""
        _conflict_part = ""

        if entity_hint and entity_confidence >= 0.75:
            _entity_part = f'- Entity signal: query references entities linked to "{entity_hint}" (confidence: {entity_confidence:.2f})'

        if process_hint and process_matches:
            matched_desc = ", ".join(
                f'"{m.get("matched_alias", "")}" -> {m.get("display_name", "")} ({m.get("node_type", "")})'
                for m in (process_matches or [])[:3]
            )
            _process_part = f'- Process signal: query keywords match taxonomy [{matched_desc}] -> skill "{process_hint}"'

        if _entity_part or _process_part:
            if signals_agree is True:
                _conflict_part = f'Both signals AGREE on "{entity_hint or process_hint}". Route with high confidence.'
            elif signals_agree is False:
                _conflict_part = (
                    f'Signals CONFLICT: entity says "{entity_hint}", process keywords say "{process_hint}". '
                    f'Prefer the PROCESS intent (what the user wants to do) over entity identity (who they mention) '
                    f'unless the query clearly asks about the entity itself.'
                )
            ontology_context = f"""
ONTOLOGY CONTEXT:
{_entity_part}
{_process_part}
{_conflict_part}
"""
        entity_hint_context = ontology_context

        if taxonomy_hints:
            _tax_lines = ["SEMANTIC TAXONOMY SIGNAL (L5 activity vector matches — informational):"]
            for _th in (taxonomy_hints or [])[:5]:
                _tax_lines.append(
                    f"  - {_th.get('skill', '?')} score={_th.get('score', 0):.3f}: "
                    f"{(_th.get('embed_text') or '')[:90]}"
                )
            entity_hint_context += "\n" + "\n".join(_tax_lines) + "\n"

        # When 2+ distinct skill domains detected, explicitly tell the LLM router
        # so it routes to 'general' (the orchestrator) instead of a domain skill.
        if len(_detected) > 1:
            _domain_list = ", ".join(sorted(_detected))
            entity_hint_context += (
                f"\nMULTI-DOMAIN DETECTION: This query spans multiple skill domains: [{_domain_list}]. "
                f"No single domain skill can answer it — route to 'general' so it can orchestrate "
                f"across all detected domains using invoke_skill/invoke_plan.\n"
            )

        pending_context = ""
        if pending_action:
            pending_context = f"""
IMPORTANT - Pending Action Awaiting Confirmation:
The assistant previously proposed an action and is waiting for user confirmation.
- Skill: {pending_action.get('skill', 'unknown')}
- Action: {pending_action.get('action_summary', 'unknown action')}
- Original request: {pending_action.get('original_query', '')[:100]}

If the user's message confirms this action (e.g., "yes", "ok", "proceed", "do it", "go ahead", "confirmed"),
set is_confirmation to true and route to the pending skill.
"""

        # Load entity types from _index.yaml (domain-configurable, no hardcoding)
        _entity_types = self.index.get("entity_types") or ["vendor", "customer"]
        _et_list = ", ".join(f'"{t}"' for t in _entity_types)
        _et_example = _entity_types[0] if _entity_types else "vendor"

        # Load entity guide .md if configured — gives LLM rich context on what
        # counts as an entity, ID patterns, aliases, and named examples.
        _entity_guide_text = ""
        _guide_path = self.index.get("entity_guide_path")
        if _guide_path:
            try:
                _gp = Path(_guide_path)
                if not _gp.is_absolute():
                    _gp = (self.skills_path / _guide_path).resolve()
                if _gp.exists():
                    _entity_guide_text = "\n\n" + _gp.read_text(encoding="utf-8").strip()
            except Exception:
                pass  # guide is optional — never break routing

        entity_extract_instruction = (
            f"\nAlso extract any specific entity mentioned in the query:\n"
            f"- entity_name: canonical name of the entity (e.g. \"ACME Corp\"), "
            f"or null if none mentioned. Normalise aliases to their canonical form.\n"
            f"- entity_type: one of {_et_list}, or null.\n"
            f"{_entity_guide_text}"
        )

        if current_skill:
            prompt = f"""You are an intelligent skill router. Analyze the user's message and determine:
1. Is this a CONFIRMATION of a pending action?
2. Is this a CONTINUATION of the current conversation?
3. Or is this a NEW topic requiring a different skill?

Current skill: {current_skill}
{entity_hint_context}{pending_context}
Previous assistant response (excerpt):
\"\"\"{truncated_response[:300] if truncated_response else 'N/A'}\"\"\"

User's new message: "{query}"

Available skills:
{self._format_skills_for_prompt(taxonomy_hints)}
{entity_extract_instruction}
Respond with ONLY valid JSON (no markdown, no explanation):
{{"skill": "<skill_name>", "is_confirmation": true/false, "is_continuation": true/false, "entity_name": "<name or null>", "entity_type": "<{_et_example}|null>", "search_variants": ["<alt_keyword_1>", "<alt_keyword_2>", "<alt_keyword_3>"], "complexity_class": "<simple|multi_step|multi_domain>", "mode_hint": "<react|orchestrator|planned>"}}

Rules:
- is_confirmation: true ONLY if user is confirming a pending action (yes/ok/proceed/do it/go ahead/confirmed/sure/y)
- is_continuation: true if staying with same topic/skill
- If confirming, use the pending action's skill: "{pending_action.get('skill', current_skill) if pending_action else current_skill}"
- If new topic, pick the appropriate skill from the list
- If MULTI-DOMAIN DETECTION is present in context, ALWAYS route to "general"
- Default skill if unsure: "{self.default_skill}"
- search_variants: 3-5 short grep keywords (1-3 words each, NOT long phrases) a domain expert would use to find documents related to this query. Examples: "invoice imaging", "IDR", "AP automation", "3D systems". Short and specific — each term must be independently searchable. Use [] if query needs no file search.
- complexity_class: "simple" = one skill answers it in one pass; "multi_step" = needs sequential calls across 2+ skills to build up an answer; "multi_domain" = explicitly spans 2+ unrelated business domains
- mode_hint: "react" for simple, "orchestrator" for multi_step, "planned" for multi_domain

JSON:"""
        else:
            prompt = f"""You are an intelligent skill router. Determine which skill best handles this query.
{entity_hint_context}{pending_context}
User query: "{query}"

Available skills:
{self._format_skills_for_prompt(taxonomy_hints)}
{entity_extract_instruction}
Respond with ONLY valid JSON (no markdown, no explanation):
{{"skill": "<skill_name>", "is_confirmation": true/false, "is_continuation": false, "entity_name": "<name or null>", "entity_type": "<{_et_example}|null>", "search_variants": ["<alt_keyword_1>", "<alt_keyword_2>", "<alt_keyword_3>"], "complexity_class": "<simple|multi_step|multi_domain>", "mode_hint": "<react|orchestrator|planned>"}}

Rules:
- is_confirmation: true ONLY if user is confirming a pending action (yes/ok/proceed/do it/confirmed)
- is_continuation: always false (no prior conversation)
- If MULTI-DOMAIN DETECTION is present in context, ALWAYS route to "general"
- Default skill if unsure: "{self.default_skill}"
- search_variants: 3-5 short grep keywords (1-3 words each, NOT long phrases) a domain expert would use to find documents related to this query. Examples: "invoice imaging", "IDR", "AP automation", "3D systems". Short and specific — each term must be independently searchable. Use [] if query needs no file search.
- complexity_class: "simple" = one skill answers it in one pass; "multi_step" = needs sequential calls across 2+ skills to build up an answer; "multi_domain" = explicitly spans 2+ unrelated business domains
- mode_hint: "react" for simple, "orchestrator" for multi_step, "planned" for multi_domain

JSON:"""
        
        try:
            import time as _t
            _start = _t.time()
            _t0 = _start * 1000
            from .model_registry import llm_model_name as _llm_model_name, llm_base_url as _llm_base_url
            _router_model = _llm_model_name(self.llm)
            _router_base_url = _llm_base_url(self.llm)
            logger.info("🔀 ROUTING LLM call  ▸ model=%s  base_url=%s", _router_model, _router_base_url)
            response = self.llm.invoke(prompt)
            _router_duration_ms = _t.time() * 1000 - _t0
            try:
                try:
                    from . import llm_tracker as _lt
                except Exception:
                    import llm_tracker as _lt
                _router_recorded = _lt.get_budget() is not None
                _lt.record("router", response, _router_duration_ms, _router_model)
                _router_prompt_tokens, _router_completion_tokens = _lt.extract_usage(response)
                routing_result["_router_llm"] = {
                    "model": _router_model,
                    "prompt_tokens": _router_prompt_tokens,
                    "completion_tokens": _router_completion_tokens,
                    "duration_ms": round(_router_duration_ms, 1),
                    "cost_usd": _lt.estimate_cost(_router_model, _router_prompt_tokens, _router_completion_tokens),
                    "recorded_in_budget": _router_recorded,
                }
            except Exception:
                pass
            logger.debug("Router LLM call took %dms", (_t.time()-_start)*1000)
            raw_response = response.content.strip()
            logger.debug("LLM returned: '%s'", raw_response)
            
            try:
                # Clean up response - remove markdown code blocks if present
                json_str = raw_response
                if json_str.startswith("```"):
                    json_str = json_str.split("```")[1]
                    if json_str.startswith("json"):
                        json_str = json_str[4:]
                json_str = json_str.strip()
                
                parsed = _json.loads(json_str)
                matched_skill = parsed.get("skill", "").lower().strip()
                is_confirmation = parsed.get("is_confirmation", False)
                is_continuation = parsed.get("is_continuation", False)
                # Entity extraction — new fields, backward-compat (default null)
                extracted_entity_name = parsed.get("entity_name") or None
                extracted_entity_type = parsed.get("entity_type") or None
                if extracted_entity_name:
                    logger.debug("Router entity: '%s' (%s)", extracted_entity_name, extracted_entity_type)
                # Search variants — pre-expanded keywords for file search, backward-compat
                extracted_variants = [v for v in (parsed.get("search_variants") or []) if isinstance(v, str) and v.strip()]
                if extracted_variants:
                    logger.debug("Router variants: %s", extracted_variants)
                # Complexity classification — used by agent for auto-mode selection
                _valid_complexity = {"simple", "multi_step", "multi_domain"}
                _valid_mode_hints = {"react", "orchestrator", "planned"}
                extracted_complexity = parsed.get("complexity_class") or "simple"
                extracted_mode_hint = parsed.get("mode_hint") or "react"
                if extracted_complexity not in _valid_complexity:
                    extracted_complexity = "simple"
                if extracted_mode_hint not in _valid_mode_hints:
                    extracted_mode_hint = "react"
                # Hard entity-signal override: when entity_registry detected 2+ distinct
                # skill domains (table mode), that signal is reliable — keep multi_domain.
                if len(_detected) > 1:
                    extracted_complexity = "multi_domain"
                    extracted_mode_hint = "planned"

                # Sync execution_mode with the LLM's mode_hint decision so agent.py
                # uses it directly without needing a back-fill override.
                routing_result["execution_mode"] = extracted_mode_hint

                if extracted_complexity == "multi_domain" and len(_detected) <= 1 and taxonomy_hints:
                    for _th in taxonomy_hints:
                        _sk = (_th.get("skill") or _th.get("skill_name") or "").strip()
                        if _sk and _th.get("score", 0) >= 0.55:
                            _detected.add(_sk)
                    routing_result["detected_domains"] = list(_detected)

                logger.info("Router complexity: %s → mode_hint: %s (skill=%s)", extracted_complexity, extracted_mode_hint, matched_skill)
                
                if matched_skill not in skill_names:
                    _lower_to_canonical = {sn.lower(): sn for sn in skill_names}
                    if matched_skill in _lower_to_canonical:
                        matched_skill = _lower_to_canonical[matched_skill]
                    else:
                        # Try to find partial match (case-insensitive)
                        _ml = matched_skill.lower()
                        for sn in skill_names:
                            if sn.lower() in _ml:
                                matched_skill = sn
                                break
                        else:
                            matched_skill = self.default_skill
                
                if is_confirmation and pending_action:
                    logger.info("User confirmed pending action, routing to: %s", pending_action.get('skill'))
                    routing_result.update({
                        "skill": pending_action.get("skill", current_skill or self.default_skill),
                        "method": "llm_confirmation",
                        "confidence": 0.95,
                        "is_confirmation": True,
                        "is_continuation": True,
                        "entity_name": extracted_entity_name,
                        "entity_type": extracted_entity_type,
                        "search_variants": extracted_variants,
                        "complexity_class": extracted_complexity,
                        "mode_hint": extracted_mode_hint,
                    })
                    return routing_result if return_details else routing_result["skill"]

                # Normal routing
                alternatives = [{"skill": s, "score": 0.2} for s in skill_names if s != matched_skill][:3]
                routing_result.update({
                    "skill": matched_skill,
                    "method": "llm",
                    "confidence": 0.85,
                    "is_continuation": is_continuation,
                    "is_confirmation": False,
                    "alternatives": alternatives,
                    "entity_name": extracted_entity_name,
                    "entity_type": extracted_entity_type,
                    "search_variants": extracted_variants,
                    "complexity_class": extracted_complexity,
                    "mode_hint": extracted_mode_hint,
                })
                return routing_result if return_details else matched_skill
                
            except _json.JSONDecodeError:
                # LLM didn't return valid JSON - try to extract skill name
                logger.warning("LLM returned invalid JSON, falling back to text parsing")
                matched = raw_response.lower()
                for skill_name in skill_names:
                    # Case-insensitive: `matched` is lowercased but skill_names can be
                    # mixed case (DCM_*), so compare lowercased and return the canonical.
                    if skill_name.lower() in matched:
                        routing_result.update({"skill": skill_name, "method": "llm_text", "confidence": 0.60})
                        return routing_result if return_details else skill_name
                
                # Fall through to keyword fallback
                
        except Exception as e:
            logger.warning("Router LLM error: %s, falling back to keywords", e)
        
        logger.debug("Using keyword fallback")
        
        # Build keyword map dynamically from _index.yaml — no domain hardcoding in code.
        # Each skill defines its own keywords; new domains just update _index.yaml.
        skill_keywords = {
            name: meta.get("keywords", [])
            for name, meta in self.index.get("skills", {}).items()
            if meta.get("keywords")
        }
        
        matched_skill = None
        for skill, keywords in skill_keywords.items():
            if skill in skill_names:
                for kw in keywords:
                    pattern = r'\b' + re.escape(kw) + r'\b'
                    if re.search(pattern, query_lower):
                        matched_skill = skill
                        logger.info("Keyword fallback match: %s (keyword: '%s')", skill, kw)
                        break
            if matched_skill:
                break
        
        if matched_skill:
            routing_result.update({"skill": matched_skill, "method": "keyword_fallback", "confidence": 0.70})
            return routing_result if return_details else matched_skill
        
        if current_skill:
            word_count = len(query_lower.split())
            if word_count <= 5:
                logger.info("Sticky fallback: short reply (%d words), staying with: %s", word_count, current_skill)
                routing_result.update({
                    "skill": current_skill,
                    "method": "sticky_fallback",
                    "confidence": 0.60,
                    "is_continuation": True
                })
                return routing_result if return_details else current_skill
        
        # Default fallback
        routing_result.update({"skill": self.default_skill, "method": "default_fallback", "confidence": 0.30})
        return routing_result if return_details else self.default_skill
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """
        List all available skills with their descriptions.
        Respects skill filtering (allowlist/denylist) if set.
        
        Returns:
            List of skill info dicts with name and description
        """
        skills = self._get_filtered_skills()
        return [
            {
                "name": name,
                "description": info.get("description", ""),
            }
            for name, info in skills.items()
        ]
    
    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        Get info about a specific skill from the index.
        
        Args:
            skill_name: Name of the skill
            
        Returns:
            Skill info dict or None if not found
        """
        skills = self.index.get("skills", {})
        if skill_name in skills:
            return {
                "name": skill_name,
                **skills[skill_name]
            }
        return None
    
    def skill_exists(self, skill_name: str) -> bool:
        """Check if a skill exists in the index."""
        return skill_name in self.index.get("skills", {})
