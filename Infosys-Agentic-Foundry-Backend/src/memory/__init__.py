# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
IAF Agent Memory - Shell-based memory for AI agents.

This module provides:
- AgentShell: Unix-like shell interface for agent memory operations (via run_shell_command tool)
"""

from src.memory.agent_shell.shell import AgentShell
from src.memory.agent_shell.tools import get_shell_tools_for_session

__all__ = [
    "AgentShell",
    "get_shell_tools_for_session"
]
