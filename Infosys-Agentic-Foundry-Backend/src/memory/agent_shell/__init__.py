# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
AgentShell - Unix-like shell interface for AI agents.

This module provides a secure, sandboxed shell environment for agents
with built-in semantic search and memory management.

Usage:
    from src.memory.agent_shell import AgentShell, get_shell_tool
    
    # Create shell for an agent session
    shell = AgentShell(agent_id="my_agent", session_id="session_123")
    
    # Run commands
    result = shell.run("ls /memory")
    result = shell.run("cat /memory/facts/user_prefs.md")
    result = shell.run("semgrep 'pricing issues'")
    
    # Get LangChain tool
    tool = get_shell_tool(agent_id="my_agent", session_id="session_123")
"""

from .shell import AgentShell
from .vector_store import VectorStore
from .tools import get_shell_tool, get_shell_tools_for_session

__all__ = [
    "AgentShell",
    "VectorStore", 
    "get_shell_tool",
    "get_shell_tools_for_session"
]
