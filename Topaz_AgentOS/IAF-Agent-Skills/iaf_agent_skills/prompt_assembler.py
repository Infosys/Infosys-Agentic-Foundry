"""
Prompt Assembly Functions for SkillAgent.

Extracted from agent.py to improve modularity.
This module handles:
- User profile loading and merging (_load_user_profile)
- Message history building (_build_messages_with_history)

USAGE:
    from iaf_agent_skills.prompt_assembler import (
        load_user_profile,
        build_messages_with_history,
    )

DEPENDENCIES:
    - SafeKernel (for file access via /me/ path)
    - datetime (for history file paths)
    - logging

NOTE: These functions are called from SkillAgent which passes 'self' as
first argument via delegation methods.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Any

logger = logging.getLogger(__name__)



# Folders that are never useful to show the agent
_TREE_SKIP_DIRS = {
    '.git', '__pycache__', '_archive', '_recycle_bin',
    'node_modules', '.venv', 'venv', '.DS_Store', '.idea',
}

# File extensions that are binary/unreadable — skip from tree
_TREE_SKIP_EXTS = {
    '.db', '.db-wal', '.db-shm', '.pyc', '.pyo',
    '.zip', '.tar', '.gz', '.rdb', '.bin',
}


def build_local_tree_section(
    kernel: Any,
    max_depth: int = 2,
    max_lines: int = 200,
) -> str:
    """
    Build a compact directory tree of /local/ to inject into the system prompt.

    Gives the agent structural awareness of available documents at session start —
    eliminating the need to ls blindly before every search.

    Generic: works for any local mount (P2P docs, HR runbooks, IT policies, etc.).
    No-ops silently if no local mount is configured.

    Args:
        kernel:     SafeKernel instance — reads kernel.local_mount for the real path.
        max_depth:  How many folder levels to show (default 2: top + one level down).
        max_lines:  Cap on total tree lines to avoid bloating the prompt (default 200).

    Returns:
        Formatted string section for system prompt, or "" if no local mount.
    """
    local_mount = getattr(kernel, 'local_mount', None)
    if not local_mount:
        return ""

    from agent_os.safe_path import SecurityError, validated_path

    try:
        root = validated_path(local_mount, label="local mount")
    except SecurityError as exc:
        logger.warning("Local mount tree skipped — rejected local_mount: %s", exc)
        return ""
    if not root.exists() or not root.is_dir():
        return ""

    lines = ["/local/"]
    count = [0]  # mutable counter for nested closure

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth or count[0] >= max_lines:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        # Separate dirs and readable files; apply skip rules
        dirs = [
            e for e in entries
            if e.is_dir() and e.name not in _TREE_SKIP_DIRS and not e.name.startswith('.')
        ]
        files = [
            e for e in entries
            if e.is_file()
            and not e.name.startswith('.')
            and e.suffix.lower() not in _TREE_SKIP_EXTS
        ]

        visible = dirs + files
        for i, entry in enumerate(visible):
            if count[0] >= max_lines:
                lines.append(f"{prefix}    ... (truncated — use grep to search)")
                return
            is_last = (i == len(visible) - 1)
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            count[0] += 1
            if entry.is_dir() and depth < max_depth:
                child_prefix = prefix + ("    " if is_last else "│   ")
                _walk(entry, child_prefix, depth + 1)

    _walk(root, "", 1)

    if len(lines) <= 1:
        return ""

    tree_text = "\n".join(lines)
    return f"""## Local Document Library
The following structure is mounted at `/local/`. Use this as your navigation map.
**Do NOT `ls` to explore — use `grep -r -i -l` to find files by content.**

```
{tree_text}
```

"""



def load_user_profile(kernel: Any) -> str:
    """
    Load user profile from both global and agent-specific sources.
    
    Profile hierarchy:
    1. /me/global.md - Tenant-level (facts, comm style, pet peeves)
    2. /me/profile.md - Agent-specific (domain context, workflow, patterns)
    
    Both are loaded and merged (global first, agent extends/overrides).
    
    Args:
        kernel: SafeKernel instance with run_shell_command method
    
    Returns:
        Merged profile content as string, or empty string if both are empty
    """
    profiles = []
    
    # 1. Load global profile (tenant-level)
    try:
        global_result = kernel.run_shell_command("cat /me/global.md", confirmed=True)
        if global_result and not global_result.startswith("Error"):
            content = global_result.strip()
            # Skip if just empty template (multiple HTML comments only)
            if "<!--" not in content or content.count("<!--") < 3:
                profiles.append(("Global", content))
    except Exception as e:
        logger.warning("Could not load global profile: %s", e)
    
    # 2. Load agent-specific profile
    try:
        agent_result = kernel.run_shell_command("cat /me/profile.md", confirmed=True)
        if agent_result and not agent_result.startswith("Error"):
            content = agent_result.strip()
            # Skip if just empty template
            if "<!--" not in content or content.count("<!--") < 2:
                profiles.append(("Agent", content))
    except Exception as e:
        logger.warning("Could not load agent profile: %s", e)
    
    if not profiles:
        return ""
    
    # Single profile case
    if len(profiles) == 1:
        return profiles[0][1]
    
    # Both profiles exist - merge them (global first, then agent-specific)
    global_content = profiles[0][1] if profiles[0][0] == "Global" else profiles[1][1]
    agent_content = profiles[1][1] if profiles[0][0] == "Global" else profiles[0][1]
    
    return f"""{global_content}

---
## Agent-Specific Preferences
{agent_content}"""



def build_messages_with_history(
    *,
    query: str,
    conversation_history: List[dict],
    current_skill: str,
    session_summary: Optional[str],
    pending_action: Optional[dict],
    get_history_path_fn: Any,
    max_history: int = 10,
    is_confirmation: bool = False,
    other_domains: Optional[List[str]] = None,
    search_variants: Optional[List[str]] = None,
    summary_refs: Optional[List[dict]] = None,
    summary_pointer: str = "",
    max_history_chars: int = 60_000,
) -> List[Tuple[str, str]]:
    """
    Build message list with cross-skill conversation history.
    
    Includes session summary (if compacted), conversation history from
    all skills (with cross-skill tags), and the current query.
    
    Args:
        query: Current user query
        conversation_history: List of turn dicts with skill, user_input, response
        current_skill: Name of current active skill
        session_summary: Summary of compacted earlier conversation, or None
        pending_action: If confirmation mode, the pending action dict
        get_history_path_fn: Function that returns pathlib.Path to history file
        max_history: Maximum number of past turns to include
        is_confirmation: If True, inject confirmation context
    
    Returns:
        List of (role, content) tuples for LangGraph messages
    """
    messages = []
    
    # Include session summary if we've compacted older turns (OpenClaw-style)
    if session_summary:
        pointer = (summary_pointer or "").strip()
        lines = [f"[SESSION CONTEXT - Compacted from earlier conversation]", session_summary]
        if summary_refs:
            # Provenance for the turns that were summarized away, so "which skill/document
            # did that come from?" is answerable instead of hallucinated.
            seen, parts = set(), []
            for ref in summary_refs[-12:]:
                if not isinstance(ref, dict):
                    continue
                bit = ref.get("skill") or "general"
                if ref.get("tools"):
                    bit += f" ({', '.join(ref['tools'][:3])})"
                if ref.get("trace_id"):
                    bit += f" trace:{str(ref['trace_id'])[:8]}"
                if bit not in seen:
                    seen.add(bit)
                    parts.append(bit)
            if parts:
                lines.append("\nEarlier turns came from: " + "; ".join(parts))
        if pointer:
            lines.append(
                f"\n📄 Full session log: `{pointer}`\n"
                f"💡 To recall specific earlier details, call `query_memory(\"<keyword>\")`."
            )
        # Add as assistant message so it doesn't look like user said it
        messages.append(("assistant", "\n".join(lines)))

    # Include ALL session history (cross-skill) with skill tags for context
    if conversation_history:
        usable = []
        for turn in conversation_history:
            if not isinstance(turn, dict):
                continue
            if "role" in turn and "user_input" not in turn:
                logger.warning(
                    "Skipping legacy-format entry in conversation_history "
                    "(role=%s). Likely corrupted Redis state — flush Redis to clear.",
                    turn.get("role"),
                )
                continue
            usable.append(turn)

        # Walk newest-first and spend a character budget, so ten oversized turns can't
        # silently become a 500KB prompt. max_history remains the hard turn cap.
        selected, spent = [], 0
        for turn in reversed(usable[-max_history:]):
            cost = len(str(turn.get("user_input") or "")) + len(str(turn.get("response") or ""))
            if selected and spent + cost > max_history_chars:
                break          # always keep at least the most recent turn
            selected.append(turn)
            spent += cost
        selected.reverse()

        for turn in selected:
            turn_skill = turn.get("skill", "unknown")

            # Add context tag if message is from a different skill
            if turn_skill != current_skill:
                prefix = f"[From {turn_skill} skill] "
            else:
                prefix = ""

            # User message with optional skill context (defensive .get())
            user_text = turn.get("user_input", "")
            resp_text = turn.get("response", "")

            if user_text:
                messages.append(("user", prefix + user_text))
            if resp_text:
                messages.append(("assistant", resp_text))
    
    # Build current query with optional confirmation context
    if is_confirmation and pending_action:
        # Inject confirmation context to help LLM understand user is confirming
        action_summary = pending_action.get("action_summary", "the pending action")
        original_query = pending_action.get("original_query", "")
        confirmation_prefix = (
            f"[USER CONFIRMED] The user has confirmed the pending action. "
            f"Original request: '{original_query[:100]}'. "
            f"Action to execute: {action_summary}. "
            f"Execute the action NOW without re-asking for confirmation.\n\n"
            f"User's confirmation: "
        )
        messages.append(("user", confirmation_prefix + query))
        logger.info("Injected confirmation context for pending action: %s", action_summary[:50])
    else:
        # Build prefix blocks to prepend to the user message
        prefix = ""

        # Inject multi-domain routing hints when the query spans multiple skills.
        if other_domains:
            domain_list = ", ".join(other_domains)
            prefix += (
                f"[ROUTING CONTEXT: This query spans multiple domains: {domain_list}. "
                f"You MUST call the create_plan tool to generate a DAG execution plan "
                f"for user confirmation before attempting to answer directly. "
                f"Do not answer inline — call create_plan now.]\n\n"
            )

        # Inject pre-expanded search variants from router — start with these
        # in Step B parallel search and add more if needed.
        if search_variants:
            variant_list = ", ".join(f'"{v}"' for v in search_variants[:5])
            prefix += (
                f"[SEARCH VARIANTS: Start your Step B parallel search with these "
                f"pre-expanded keywords — add more if needed: {variant_list}]\n\n"
            )

        messages.append(("user", prefix + query))
    
    return messages
