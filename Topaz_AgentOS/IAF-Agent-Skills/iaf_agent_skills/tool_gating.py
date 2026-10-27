"""Per-skill runtime tool gating policy.

Central, dependency-free policy for deciding whether a powerful runtime tool
(``shell``, ``write_file``, ``query_memory``, ...) may be granted to a specific
skill invocation.

Background
----------
Historically, the runtime gated ``shell``, ``write_file`` and ``query_memory``
purely by the *agent-level* allowlist (``config.yaml`` -> ``tools.allowed``),
while ``run_sql_query`` was additionally gated by the *skill-level* tool list
(``SKILL.md`` frontmatter ``tools:``). The consequence was a security
enforcement gap: a skill whose frontmatter deliberately omitted ``shell`` still
received the shell tool, because the agent allowed it. The per-skill checkbox in
the UI (which writes ``SKILL.md`` ``tools:``) was therefore not honoured for the
most powerful tools.

Policy
------
``tool_allowed_for_skill`` applies two gates, in order:

1. **Agent gate (always enforced).** The tool must be present in the agent-level
   allowlist. The skill can never widen what the agent forbids.
2. **Skill gate (opt-in strict).** When a skill declares a *non-empty* ``tools``
   list it opts into strict per-skill gating: only the tools it names are
   granted, including powerful ones. A skill that declares *no* tools (empty or
   absent list) inherits the agent-level allowlist -- preserving legacy
   behaviour for skills that never declared a tool list.

This mirrors, and generalises, the existing ``run_sql_query`` intersection so
that ``shell``/``write_file``/``query_memory`` are enforced the same way.
"""

from __future__ import annotations

from typing import Iterable

__all__ = ["skill_declares_tools", "tool_allowed_for_skill"]


def skill_declares_tools(skill_tools: Iterable[str] | None) -> bool:
    """Return ``True`` when the skill declares a non-empty explicit tool list.

    A skill that declares a non-empty ``tools:`` list opts into strict
    per-skill gating. Empty / ``None`` means "inherit agent-level allowlist".
    """
    return bool(list(skill_tools or []))


def tool_allowed_for_skill(
    tool_name: str,
    agent_allowed_tools: Iterable[str] | None,
    skill_tools: Iterable[str] | None,
    skill_load_failed: bool = False,
) -> bool:
    """Decide whether ``tool_name`` may be granted for this skill invocation.

    Args:
        tool_name: Canonical tool id, e.g. ``"shell"``, ``"write_file"``,
            ``"query_memory"``.
        agent_allowed_tools: Tools permitted at the agent level
            (``config.yaml`` -> ``tools.allowed``, post entitlement filtering).
        skill_tools: Tools declared by the skill (``SKILL.md`` frontmatter
            ``tools:``). Empty / ``None`` means the skill declares nothing and
            inherits the agent-level allowlist.
        skill_load_failed: ``True`` when the skill could not be loaded, so its
            declared tool policy is unknown. In that case we **fail closed** and
            deny the (powerful) tool — an empty ``skill_tools`` on a load failure
            must NOT be mistaken for "declares nothing, inherit agent allowlist",
            which would silently grant shell/write/memory to a broken skill
            (Copilot #1).

    Returns:
        ``True`` if the tool is permitted for this skill, else ``False``.
    """
    # Gate 0: fail closed when the skill's policy could not be established.
    if skill_load_failed:
        return False
    allowed = set(agent_allowed_tools or [])
    # Gate 1: agent-level allowlist is the outer boundary and always wins.
    if tool_name not in allowed:
        return False
    # Gate 2: a skill with an explicit non-empty tool list is authoritative.
    declared = list(skill_tools or [])
    if declared:
        return tool_name in set(declared)
    # No skill-level declaration -> inherit the agent-level decision.
    return True
