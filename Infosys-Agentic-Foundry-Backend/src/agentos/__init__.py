# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
AgentOS - Skill-based Agent Framework for IAF.

This module brings AgentOS-style features to the Infosys Agentic Foundry:
- Phase 1: Skills-as-Markdown (SKILL.md) with folder-based agent definitions
- Phase 2: Enterprise Context Layer
- Phase 3: Human-in-the-Loop (HITL) via LangGraph interrupt + hook-based gating
- Phase 4: Hardened Agent Shell with RBAC, Audit, Rate Limiting
- Phase 5: Smart Code Executor (goal-driven code generation & execution)

Usage:
    from src.agentos import SkillLoader, SkillRouter
    from src.agentos import EnterpriseContext
    from src.agentos import HardenedShell
    from src.agentos import SmartCodeExecutor, CodeExecutorConfig
"""

from src.agentos.skill_loader import SkillLoader, Skill
from src.agentos.skill_router import SkillRouter
from src.agentos.enterprise_context import EnterpriseContextManager
from src.agentos.hardened_shell import HardenedShell
from src.agentos.code_executor import SmartCodeExecutor, CodeExecutorConfig

__all__ = [
    "SkillLoader",
    "Skill",
    "SkillRouter",
    "EnterpriseContextManager",
    "HardenedShell",
    "SmartCodeExecutor",
    "CodeExecutorConfig",
]
