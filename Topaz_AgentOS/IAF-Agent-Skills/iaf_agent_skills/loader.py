"""
SkillLoader: Load and parse SKILL.md files with YAML frontmatter.

Skills are defined as markdown files with YAML frontmatter containing
metadata about the skill (files, knowledge paths, MCP tools, etc.)
"""

import re
from pathlib import Path
from typing import List, Optional, Dict
import yaml

from .yaml_fast import safe_load as _fast_yaml_load

from agentos_contracts import Skill


class SkillLoader:
    """
    Load and parse SKILL.md files with YAML frontmatter.
    
    A SKILL.md file has this structure:
    
        ---
        name: dilo
        version: "1.0"
        description: "Day in Life Of activity logger"
        
        files:
          instructions: "INSTRUCTIONS.md"
          examples: "EXAMPLES.md"
        
        knowledge:
          - "/shared/learnings/"
        
        mcp_tools:
          - server: slack
            tools: [send_message]
        ---
        
        # DILO Agent
        
        You help employees log their daily activities...
    """
    
    def __init__(self, skills_path: str):
        """
        Initialize the loader.

        Args:
            skills_path: Path to global skills folder
        """
        self.skills_path = Path(skills_path)
        # Cache: {skill_name: (mtime, Skill)} — auto-invalidates when SKILL.md changes on disk
        self._cache: Dict[str, tuple] = {}

        # Personal skills folder (set via set_personal_path).
        # When set, loader checks this folder before the global one.
        self._personal_path: Optional[Path] = None

    def set_personal_path(self, personal_path) -> None:
        """
        Set the user's personal skills folder path.
        Loader checks this folder before the global skills folder on every load().

        Args:
            personal_path: Path to enterprise_root/.../users/{user_id}/skills/
        """
        self._personal_path = Path(personal_path) if personal_path else None

    def _resolve_skill_folder(self, skill_name: str) -> Path:
        """
        Resolve which folder to load a skill from.
        Personal folder takes priority over global if the skill exists in both
        (allows users to test local overrides before submitting to central).
        """
        if self._personal_path:
            personal_folder = self._personal_path / skill_name
            if (personal_folder / "SKILL.md").exists():
                return personal_folder
        return self.skills_path / skill_name

    def load(self, skill_name: str) -> Skill:
        """
        Load a skill by name.
        Checks user's personal folder first, then falls back to global.

        Args:
            skill_name: Name of the skill (folder name)

        Returns:
            Loaded Skill object

        Raises:
            FileNotFoundError: If skill folder or SKILL.md not found
        """
        skill_folder = self._resolve_skill_folder(skill_name)
        skill_file = skill_folder / "SKILL.md"

        if not skill_folder.exists():
            raise FileNotFoundError(f"Skill folder not found: {skill_folder}")

        if not skill_file.exists():
            raise FileNotFoundError(f"SKILL.md not found in: {skill_folder}")
        
        # Cache check: return cached Skill if file hasn't changed on disk
        current_mtime = skill_file.stat().st_mtime
        if skill_name in self._cache and self._cache[skill_name][0] == current_mtime:
            return self._cache[skill_name][1]
        
        content = skill_file.read_text(encoding='utf-8')
        frontmatter, body = self._parse_frontmatter(content)
        
        skill = Skill(
            name=frontmatter.get("name", skill_name),
            version=frontmatter.get("version", "1.0"),
            description=frontmatter.get("description", ""),
            files=frontmatter.get("files", {}),
            knowledge=frontmatter.get("knowledge", []),
            user_data=frontmatter.get("user_data", {}),
            mcp_tools=frontmatter.get("mcp_tools", []),
            mcp_connections=frontmatter.get("mcp_connections", []),  # Unified MCP connections
            connections=frontmatter.get("connections", []),  # Data connections (database/api/erp)
            tools=frontmatter.get("tools", []),  # Simple tool list like ['fs', 'run_sql_query']
            business_context=frontmatter.get("business_context", {}),
            approval_rules=frontmatter.get("approval_rules", {}),  # HITL rules
            evidence_highlights=frontmatter.get("evidence_highlights", {}) or {},  # Evidence highlight rules
            sql_mode=frontmatter.get("sql_mode", "read_only"),  # SQL write control
            execution_mode=frontmatter.get("execution_mode", "react"),  # Default to react
            react_runtime=frontmatter.get("react_runtime", ""),
            profile=frontmatter.get("profile", ""),  # Harness execution profile (empty → agent/tenant default)
            context_file=frontmatter.get("context_file", ""),  # Per-skill context doc (empty → none)
            steps=frontmatter.get("steps", []),  # For workflow/parallel modes
            worker_skills=self._normalize_worker_skills(frontmatter.get("worker_skills", [])),  # For supervisor/orchestrator mode
            max_steps=int(frontmatter.get("max_steps", 10)),  # Orchestrator step ceiling
            graph_ref=frontmatter.get("graph_ref", ""),  # For execution_mode 'graph': stored process-graph YAML
            body=body.strip(),
            path=skill_folder
        )
        
        # Store in cache keyed by mtime for automatic invalidation
        self._cache[skill_name] = (current_mtime, skill)
        return skill
    
    def _normalize_worker_skills(self, worker_skills: list) -> List[Dict[str, str]]:
        """
        Normalize worker_skills to list of dicts with 'name' and 'task' keys.
        
        Supports two formats in SKILL.md:
        
        1. Simple list (backward compatible):
            worker_skills:
              - ar_ops
              - invoice
        
        2. List with specific tasks:
            worker_skills:
              - name: ar_ops
                task: "Generate AR summary..."
        
        Returns:
            List of dicts: [{'name': 'ar_ops', 'task': '...'}, ...]
        """
        if not worker_skills:
            return []
        
        normalized = []
        for item in worker_skills:
            if isinstance(item, str):
                # Simple format: just skill name, no specific task
                normalized.append({'name': item, 'task': None})
            elif isinstance(item, dict):
                # Dict format: {name: ..., task: ..., description: ...}
                normalized.append({
                    'name':        item.get('name', ''),
                    'task':        item.get('task', None),
                    'description': item.get('description', ''),
                })
        
        return normalized
    
    def _parse_frontmatter(self, content: str) -> tuple:
        """
        Parse YAML frontmatter from markdown content.
        
        Supports two formats:
          1. Standard:  ---\\n<yaml>\\n---\\n<body>
          2. Fenced:    ````skill\\n---\\n<yaml>\\n---\\n<body>\\n````
        
        Args:
            content: Full markdown content with frontmatter
            
        Returns:
            Tuple of (frontmatter_dict, body_string)
        """
        # Strip optional ````skill ... ```` wrapper (some skills use fenced format)
        stripped = content
        fence_match = re.match(r'^[`]{3,4}\w*\s*\n(.*)', content, re.DOTALL)
        if fence_match:
            inner = fence_match.group(1)
            # Remove trailing fence if present
            inner = re.sub(r'\n[`]{3,4}\s*$', '', inner)
            stripped = inner

        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, stripped, re.DOTALL)
        
        if match:
            frontmatter_str = match.group(1)
            body = match.group(2)
            try:
                frontmatter = _fast_yaml_load(frontmatter_str) or {}
            except yaml.YAMLError:
                frontmatter = {}
            return frontmatter, body
        
        # No frontmatter found
        return {}, content
    
    def get_file_content(self, skill: Skill, file_key: str) -> Optional[str]:
        """
        Get content of a related file (instructions, examples, etc.)
        
        Args:
            skill: Loaded Skill object
            file_key: Key from skill.files (e.g., "instructions")
            
        Returns:
            File content or None if not found
        """
        if file_key not in skill.files:
            return None
        
        file_path = skill.path / skill.files[file_key]
        if file_path.exists():
            return file_path.read_text(encoding='utf-8')
        return None
    
    def get_prompt(self, skill: Skill, include_files: bool = True) -> str:
        """
        Build a complete system prompt from the skill.
        
        Args:
            skill: Loaded Skill object
            include_files: Whether to include INSTRUCTIONS.md content
            
        Returns:
            Complete system prompt string
        """
        parts = []
        
        # Add skill body (main content)
        parts.append(skill.body)
        
        # Optionally include instructions
        if include_files and "instructions" in skill.files:
            instructions = self.get_file_content(skill, "instructions")
            if instructions:
                parts.append("\n\n---\n\n## Detailed Instructions\n\n")
                parts.append(instructions)
        
        return "\n".join(parts)
    
    def list_skill_files(self, skill: Skill) -> List[Dict[str, str]]:
        """
        List all files in a skill folder.
        
        Args:
            skill: Loaded Skill object
            
        Returns:
            List of file info dicts with name and path
        """
        if not skill.path or not skill.path.exists():
            return []
        
        files = []
        for f in skill.path.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "path": str(f),
                    "relative": f.name
                })
        return files
