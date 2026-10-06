# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
SkillLoader - Parses SKILL.md files with YAML frontmatter into Skill objects.

A Skill is defined by a single SKILL.md file containing:
- YAML frontmatter (between --- delimiters): metadata, tools, triggers, approval rules
- Markdown body: the system prompt / instructions for the LLM

Example SKILL.md:
    ---
    name: invoice_lookup
    version: "1.0"
    description: "Look up invoice status and payment history."
    execution_mode: react
    tools:
      - run_shell_command
      - database_query_tool
    triggers:
      - invoice
      - payment status
    sql_mode: read_only
    ---
    
    # Invoice Lookup Agent
    
    You are an AP data assistant. Look up invoice records...
"""

import os
import re
import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Skill Data Model
# ============================================================================

@dataclass
class Skill:
    """
    A parsed skill definition loaded from a SKILL.md file.
    
    Attributes:
        name: Unique identifier (snake_case, must match folder name).
        version: Semver string.
        description: Short description shown to the router (≤200 chars).
        execution_mode: react | workflow | parallel | supervisor | map_reduce | chain | iterative | consensus.
        tools: List of tool names this skill can use.
        triggers: Keywords for keyword-based routing fallback.
        body: The markdown body (system prompt for the LLM).
        hooks: Skill-level hook definitions (same format as agent config.yaml hooks).
        sql_mode: read_only | read_write.
        knowledge: Paths to context folders auto-injected into prompt.
        mcp_connections: External MCP tool servers.
        business_context: Domain metadata (domain, KPIs, databases).
        steps: Workflow steps (for execution_mode=workflow).
        worker_skills: Sub-skills (for execution_mode=supervisor/parallel).
        files: References to companion files (INSTRUCTIONS.md, EXAMPLES.md).
        scope: personal | submitted | approved.
        category: Skill category for grouping (operations, platform, etc.).
        folder_path: Filesystem path to the skill folder.
        loaded_at: When the skill was last loaded.
        file_hash: SHA256 hash of SKILL.md for change detection.
    """
    name: str
    version: str = "1.0"
    description: str = ""
    execution_mode: str = "react"
    tools: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    body: str = ""
    hooks: Dict[str, Any] = field(default_factory=dict)
    sql_mode: str = "read_only"
    databases: List[Dict[str, Any]] = field(default_factory=list)
    knowledge: List[str] = field(default_factory=list)
    mcp_connections: List[Dict[str, Any]] = field(default_factory=list)
    business_context: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    worker_skills: List[Any] = field(default_factory=list)
    max_steps: int = 10
    max_iterations: int = 3
    quality_threshold: int = 7
    evaluation_criteria: str = ""
    files: Dict[str, str] = field(default_factory=dict)
    scope: str = "personal"
    category: str = "general"
    folder_path: Optional[str] = None
    loaded_at: Optional[str] = None
    file_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (no internal paths exposed)."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "tools": self.tools,
            "triggers": self.triggers,
            "hooks": self.hooks,
            "sql_mode": self.sql_mode,
            "databases": self.databases,
            "knowledge": self.knowledge,
            "business_context": self.business_context,
            "steps": self.steps,
            "worker_skills": self.worker_skills,
            "max_steps": self.max_steps,
            "max_iterations": self.max_iterations,
            "quality_threshold": self.quality_threshold,
            "evaluation_criteria": self.evaluation_criteria,
            "files": self.files,
            "scope": self.scope,
            "category": self.category,
            "body": self.body,
        }


# ============================================================================
# SkillLoader
# ============================================================================

class SkillLoader:
    """
    Loads and caches Skill objects from SKILL.md files on disk.
    
    Supports:
    - Parsing YAML frontmatter + markdown body
    - Mtime-based cache invalidation (hot-reload on file change)
    - Loading companion files (INSTRUCTIONS.md, EXAMPLES.md)
    - Personal skills (per-user overrides)
    - Schema versioning: if a SKILL.md declares ``schema_version: N`` in its
      frontmatter and *N* exceeds ``_SCHEMA_VERSION``, the file is skipped with
      a warning so that an older loader never silently drops new fields.
    """

    # Bump when the set of recognised frontmatter keys changes materially.
    _SCHEMA_VERSION = 1

    FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
    # Also accept ```skill ... ``` fenced code blocks as frontmatter
    FENCED_REGEX = re.compile(r"^```\w*\s*\n(.*?)\n```\s*\n?(.*)", re.DOTALL)

    def __init__(self, skills_path: str):
        """
        Initialize SkillLoader.
        
        Args:
            skills_path: Root directory containing skill folders.
        """
        self.skills_path = Path(skills_path)
        self._cache: Dict[str, Skill] = {}
        self._mtime_cache: Dict[str, float] = {}
        self._lock = threading.Lock()
        log.info(f"SkillLoader initialized: skills_path={self.skills_path}")

    # ---- Public API ----

    def load(self, skill_name: str) -> Optional[Skill]:
        """
        Load a skill by name. Returns cached version if file hasn't changed.
        Thread-safe: uses a lock for cache reads/writes.
        
        Args:
            skill_name: The skill folder name (must match SKILL.md's name field).
            
        Returns:
            Skill object or None if not found.
        """
        skill_dir = self.skills_path / skill_name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            log.warning(f"Skill file not found: {skill_file}")
            return None

        # Check mtime for hot-reload
        current_mtime = skill_file.stat().st_mtime
        with self._lock:
            if skill_name in self._cache and self._mtime_cache.get(skill_name) == current_mtime:
                return self._cache[skill_name]

        # Parse outside lock (I/O bound)
        skill = self._parse_skill_file(skill_file, skill_dir)
        if skill:
            with self._lock:
                self._cache[skill_name] = skill
                self._mtime_cache[skill_name] = current_mtime
            log.info(f"Loaded skill: {skill_name} (v{skill.version})")
        return skill

    def load_all(self) -> List[Skill]:
        """Load all skills from the skills directory."""
        skills = []
        if not self.skills_path.exists():
            return skills

        for entry in sorted(self.skills_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith(("_", ".")):
                skill = self.load(entry.name)
                if skill:
                    skills.append(skill)
        return skills

    def get_companion_content(self, skill: Skill, file_key: str) -> Optional[str]:
        """
        Load a companion file referenced in the skill's `files` frontmatter.
        
        Args:
            skill: The skill object.
            file_key: Key from the `files` dict (e.g., 'instructions', 'examples').
            
        Returns:
            File content as string, or None.
        """
        if not skill.folder_path or file_key not in skill.files:
            return None
        
        companion_path = Path(skill.folder_path) / skill.files[file_key]
        if companion_path.exists():
            return companion_path.read_text(encoding="utf-8")
        return None

    def get_full_prompt(self, skill: Skill, include_companions: bool = True) -> str:
        """
        Build the complete system prompt for a skill.
        
        Concatenates: SKILL.md body + INSTRUCTIONS.md (auto-detected by convention)
        EXAMPLES.md is NOT included — it is loaded on-demand via run_shell_command.
        
        Args:
            skill: The skill object.
            include_companions: Whether to append companion files.
            
        Returns:
            Complete prompt string.
        """
        parts = [skill.body]

        if include_companions and skill.folder_path:
            skill_dir = Path(skill.folder_path)

            # Auto-detect INSTRUCTIONS.md by convention (file on disk)
            instructions_file = skill_dir / "INSTRUCTIONS.md"
            if instructions_file.exists():
                instructions = instructions_file.read_text(encoding="utf-8").strip()
                if instructions:
                    parts.append(f"\n\n## Detailed Instructions\n\n{instructions}")
            else:
                # Fallback: check files: frontmatter mapping
                instructions = self.get_companion_content(skill, "instructions")
                if instructions:
                    parts.append(f"\n\n## Detailed Instructions\n\n{instructions}")

            # EXAMPLES.md is intentionally NOT loaded here.
            # The agent reads it on-demand via run_shell_command as a fallback.

        return "\n".join(parts)

    def list_skill_names(self) -> List[str]:
        """List all available skill folder names."""
        if not self.skills_path.exists():
            return []
        return sorted([
            d.name for d in self.skills_path.iterdir()
            if d.is_dir() and not d.name.startswith(("_", "."))
               and (d / "SKILL.md").exists()
        ])

    def invalidate_cache(self, skill_name: Optional[str] = None):
        """Clear cache for a specific skill or all skills (thread-safe)."""
        with self._lock:
            if skill_name:
                self._cache.pop(skill_name, None)
                self._mtime_cache.pop(skill_name, None)
            else:
                self._cache.clear()
                self._mtime_cache.clear()

    # ---- Internal ----

    def _parse_skill_file(self, skill_file: Path, skill_dir: Path) -> Optional[Skill]:
        """Parse a SKILL.md file into a Skill object."""
        try:
            content = skill_file.read_text(encoding="utf-8")
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            
            frontmatter, body = self._split_frontmatter(content)
            if frontmatter is None:
                # No explicit delimiters — try to parse the whole file as YAML.
                # If it contains at least a 'name' or 'triggers' key we treat it
                # as a delimiter-less frontmatter file.  Everything after the YAML
                # block (first blank-line-separated paragraph that fails to parse)
                # becomes the body.
                frontmatter, body = self._try_yaml_only(content)

            if frontmatter is None:
                # Truly unparseable — treat entire content as body
                return Skill(
                    name=skill_dir.name,
                    body=content.strip(),
                    folder_path=str(skill_dir),
                    loaded_at=datetime.utcnow().isoformat(),
                    file_hash=file_hash,
                )

            # Parse YAML frontmatter
            if yaml is None:
                log.error("PyYAML is required to parse SKILL.md frontmatter. pip install pyyaml")
                return None

            meta = yaml.safe_load(frontmatter) or {}

            # Schema version guard — reject skills written for a newer loader
            file_schema_version = meta.get("schema_version", 1)
            if isinstance(file_schema_version, (int, float)) and file_schema_version > self._SCHEMA_VERSION:
                log.warning(
                    f"Skill {skill_dir.name}: schema_version {file_schema_version} "
                    f"exceeds loader's supported version {self._SCHEMA_VERSION} — skipping. "
                    f"Upgrade SkillLoader to parse this skill."
                )
                return None

            # Normalize tools list (can be strings or dicts with "type" key)
            raw_tools = meta.get("tools", [])
            tools = []
            for t in raw_tools:
                if isinstance(t, str):
                    tools.append(t)
                elif isinstance(t, dict) and "type" in t:
                    tools.append(t["type"])
                elif isinstance(t, dict) and "name" in t:
                    tools.append(t["name"])

            # Normalize worker_skills
            raw_workers = meta.get("worker_skills", [])
            worker_skills = []
            for w in raw_workers:
                if isinstance(w, str):
                    worker_skills.append({"name": w})
                elif isinstance(w, dict):
                    worker_skills.append(w)

            return Skill(
                name=meta.get("name", skill_dir.name),
                version=str(meta.get("version", "1.0")),
                description=meta.get("description", ""),
                execution_mode=meta.get("execution_mode", "react"),
                tools=tools,
                triggers=[str(x) for x in meta.get("triggers", meta.get("keywords", []))],
                body=body.strip(),
                hooks=meta.get("hooks", {}),
                sql_mode=meta.get("sql_mode", "read_only"),
                databases=meta.get("databases", []),
                knowledge=meta.get("knowledge", []),
                mcp_connections=meta.get("mcp_connections", []),
                business_context=meta.get("business_context", {}),
                steps=meta.get("steps", []),
                worker_skills=worker_skills,
                max_steps=int(meta.get("max_steps", 10)),
                max_iterations=int(meta.get("max_iterations", 3)),
                quality_threshold=int(meta.get("quality_threshold", 7)),
                evaluation_criteria=meta.get("evaluation_criteria", ""),
                files=meta.get("files", {}),
                scope=meta.get("scope", "personal"),
                category=meta.get("category", "general"),
                folder_path=str(skill_dir),
                loaded_at=datetime.utcnow().isoformat(),
                file_hash=file_hash,
            )

        except Exception as e:
            log.error(f"Error parsing skill file {skill_file}: {e}")
            return None

    def _split_frontmatter(self, content: str):
        """
        Split SKILL.md content into YAML frontmatter and markdown body.
        Supports both ``---`` delimiters and ``` fenced code blocks.

        Returns:
            Tuple of (frontmatter_str, body_str) or (None, None) if no frontmatter.
        """
        # Try standard --- delimiters first
        match = self.FRONTMATTER_REGEX.match(content)
        if match:
            return match.group(1), match.group(2)
        # Try ```skill / ``` fenced block
        match = self.FENCED_REGEX.match(content)
        if match:
            return match.group(1), match.group(2)
        return None, None

    # ---- YAML-only (no delimiters) ----

    @staticmethod
    def _try_yaml_only(content: str):
        """
        Handle SKILL.md files that contain raw YAML without ``---`` or
        ` ``` ` delimiters.

        Strategy: attempt ``yaml.safe_load`` on the whole content.  If it
        produces a dict with at least one expected skill key (``name``,
        ``triggers``, ``description``, ``execution_mode``) we split the
        text at the first blank line (or the end) to separate YAML from body.

        Returns:
            (frontmatter_str, body_str) or (None, None).
        """
        if yaml is None:
            return None, None

        # Quick sniff: first line should look like a YAML key
        first_line = content.split("\n", 1)[0].strip()
        if not first_line or ":" not in first_line:
            return None, None

        # Split at first blank line to separate YAML block from body
        _SKILL_KEYS = {"name", "triggers", "description", "execution_mode", "version", "tools", "category"}
        # Try parsing the whole content as YAML first
        try:
            parsed = yaml.safe_load(content)
            if isinstance(parsed, dict) and _SKILL_KEYS & set(parsed.keys()):
                # Everything is YAML – body is empty or embedded in the YAML stream
                return content, ""
        except yaml.YAMLError:
            pass

        # Try splitting at first blank line
        parts = re.split(r"\n\s*\n", content, maxsplit=1)
        if len(parts) == 2:
            yaml_part, body_part = parts
            try:
                parsed = yaml.safe_load(yaml_part)
                if isinstance(parsed, dict) and _SKILL_KEYS & set(parsed.keys()):
                    return yaml_part, body_part
            except yaml.YAMLError:
                pass

        return None, None
