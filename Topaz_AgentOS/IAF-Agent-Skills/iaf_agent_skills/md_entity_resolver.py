"""
MdEntityResolver — File-mode context delivery helper.

In file mode, entity identification and skill routing are both owned by
the router LLM (one call, returns skill + entity_name + entity_type).
This module's only job is to build the system-prompt instruction block
that tells the ReAct agent WHERE to find context.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from agent_os.safe_path import SecurityError, confine_to_root, validated_path

try:
    import yaml as _yaml
except ImportError:
    _yaml = None

logger = logging.getLogger(__name__)


def _load_entity_memory_config(shared_dir: Path) -> dict:
    """Read entity_memory section from shared/entity_validation.yaml."""
    if _yaml is None:
        return {}
    cfg_path = shared_dir / "entity_validation.yaml"
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        return data.get("entity_memory") or {}
    except Exception as exc:
        logger.warning("MdEntityResolver: could not load entity config: %s", exc)
        return {}


class MdEntityResolver:
    """
    Builds the file-context instruction block injected into the system prompt
    when context_loading_mode == "file".

    The router LLM extracts entity_name / entity_type from the query.
    This class handles only the prompt-side: telling the agent to read
    the Enterprise Context .md file and any linked files it finds there.
    """

    @staticmethod
    def make_file_context_block(file_path: str,
                                execution_hints: list = None,
                                entity_name: str = None,
                                entities_dir: str = None) -> str:
        """
        Return the instruction string injected into the system prompt (Step 10f).

        Instructs the ReAct agent to:
          1. Read Enterprise_Context.md using shell (cat).
          2. Follow any additional file paths found there (policies, playbooks).
          3. If an entity-specific notes file exists for the queried entity, read it too.
          4. Answer from those files, not from training memory.

        Args:
            file_path: Virtual path to the master context file.
            execution_hints: Optional list of {"tool", "input"} dicts captured
                from a previous successful run of a similar query (from plan_cache).
            entity_name: Name of the entity identified by the router (e.g. "Acme Supplies").
                Used to locate an entity-specific notes file if one exists.
            entities_dir: Absolute path to the entities storage directory.
                Derived from context_file_path + entity_validation.yaml config.
        """
        logger.info("MdEntityResolver: building file context block for %s", file_path)
        block = (
            "## Enterprise Context\n"
            f"Context information is stored in: `{file_path}`\n\n"
            "**MANDATORY — Step 1**: Use your `shell` tool to read this file FIRST:\n"
            f"`cat \"{file_path}\"`\n\n"
            "**MANDATORY — Step 2**: If the file lists additional file paths "
            "(policies, playbooks, databases) relevant to the user's request, "
            "read those files too using shell before composing your answer.\n"
        )
        if execution_hints:
            hint_lines = "\n".join(
                f"  {i+1}. {h.get('tool','shell')} → {h.get('input','')}"
                for i, h in enumerate(execution_hints)
            )
            block += (
                "\n## Execution Hints (from a previous successful run of a similar query)\n"
                "After reading the master index above, these resources were most relevant "
                "— prioritise them in this order:\n"
                f"{hint_lines}\n"
                "These are hints only. Always read the master index first to confirm.\n"
            )
            logger.info("MdEntityResolver: injected %d execution hints", len(execution_hints))

        # Entity-specific notes file — only appended when one actually exists on disk.
        # The storage path and ID patterns come from entity_validation.yaml, not from code.
        if entity_name and entities_dir:
            entity_file = MdEntityResolver._find_entity_file(entity_name, Path(entities_dir))
            if entity_file:
                block += (
                    f"\n\n## Entity Notes\n"
                    f"Confirmed notes for this entity are stored at: `{entity_file}`\n"
                    f"**Also read this file**: `cat \"{entity_file}\"`\n"
                    "The `## Confirmed Knowledge` section there contains verified facts "
                    "specific to this entity — treat them as highest priority."
                )
                logger.info("MdEntityResolver: injected entity notes hint for %s", entity_file)

        block += (
            "\nDo NOT answer from memory. All context must come from these files."
            "\nIf any context file contains a `## Confirmed Knowledge` section, "
            "treat those entries as verified facts that take precedence over general content."
        )
        return block

    @staticmethod
    def _find_entity_file(entity_name: str, entities_dir: Path) -> Optional[str]:
        """
        Scan the entities directory for a .md file that matches the entity_name.

        Matching is done by scoring how many significant words (3+ chars) from
        entity_name appear in the first 200 bytes of each candidate file.
        Returns the absolute path of the best match, or None if nothing is found.

        This method has zero domain knowledge — it works for any entity type
        (vendors, customers, employees, projects, etc.).
        """
        if not entities_dir.is_dir():
            return None

        name_words = set(re.findall(r"[a-z]{3,}", entity_name.lower()))
        if not name_words:
            return None

        best_path: Optional[Path] = None
        best_score = 0

        for candidate in entities_dir.glob("*.md"):
            try:
                header = candidate.read_text(encoding="utf-8", errors="ignore")[:300].lower()
            except Exception:
                continue
            score = sum(1 for w in name_words if w in header)
            if score > best_score:
                best_score = score
                best_path = candidate

        if best_path and best_score >= 1:
            return str(best_path)
        return None

    @staticmethod
    def get_entities_dir(context_file_path: str) -> Optional[str]:
        """
        Derive the entities storage directory from the context file path and
        entity_validation.yaml config.  Returns None when entity memory is
        disabled or config is unavailable.

        Used by agent.py to pass entities_dir to make_file_context_block without
        duplicating the config-loading logic.
        """
        if not context_file_path:
            return None
        try:
            shared_dir = validated_path(context_file_path, label="context_file_path").parent.parent
        except SecurityError as exc:
            logger.warning("MdEntityResolver: rejected context_file_path: %s", exc)
            return None
        cfg = _load_entity_memory_config(shared_dir)
        if not cfg.get("enabled", True):
            return None
        storage = cfg.get("storage_dir", "entities")
        try:
            # storage_dir comes from tenant YAML; keep it under the shared dir.
            return str(confine_to_root(shared_dir / str(storage), shared_dir, label="entity storage_dir"))
        except SecurityError as exc:
            logger.warning("MdEntityResolver: rejected entity storage_dir: %s", exc)
            return None
