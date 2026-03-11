# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
LangChain Tools - Compatible tool wrappers for AgentShell.

Provides LangChain-compatible tools that integrate with IAF's tool system.
"""

from typing import List, Tuple, Any, Optional
from pydantic import BaseModel, Field

# Support both relative and absolute imports
try:
    from .shell import AgentShell
    from .vector_store import VectorStore
except ImportError:
    from shell import AgentShell
    from vector_store import VectorStore

try:
    from langchain_core.tools import BaseTool, StructuredTool
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============ TOOL INPUT SCHEMAS ============

class ShellCommandInput(BaseModel):
    """Input for the shell command tool."""
    command: str = Field(
        description="Shell command to execute (e.g., 'ls -la', 'grep error .', 'cat /memory/facts/user.md', 'semgrep \"pricing\"')"
    )


# ============ SYSTEM PROMPT ============

SHELL_AGENT_SYSTEM_PROMPT = """You have access to a secure shell environment via the `run_shell_command` tool.

## Your Environment (Hierarchical)

### User Level (persists across ALL agents and sessions)
- `/user/preferences.md` - User preferences (theme, language)
- `/user/profile.md` - User profile info
- `/user/facts/` - User-level facts (API keys, credentials)

### Agent Level (persists across sessions for THIS agent)
- `/agent/facts/` - Agent-specific facts
- `/agent/learnings/` - Patterns and insights
- `/agent/entities/` - Known entities

### Session Level (current session only)
- `/session/workspace/` - Scratchpad for current task
- `/session/history/` - Session history
- `/session/conversations/` - [VIRTUAL] Past chat history (read-only)
  - `summary.md` - AI-generated conversation summary
  - `full.md` - Full conversation history

## Key Commands

### Navigation
- `ls`, `cd`, `pwd` - Navigate directories
- `tree /path` - Show directory structure

### Reading Files
- `cat /file` - Print file contents
- `head -n 20 /file` - First 20 lines
- `tail -n 20 /file` - Last 20 lines

### Searching
- `grep -r "pattern" /path` - Search for exact text
- `semgrep "concept" /path` - Search by meaning (use when grep fails!)
- `find /path -name "*.md"` - Find files by name

### Writing
- `echo "content" > /user/facts/api_keys.md` - Write to file
- `echo "more" >> /file` - Append to file
- `mkdir -p /path` - Create directory

## Storage Strategy

1. **API keys, credentials, user preferences** → `/user/facts/` (persists forever)
2. **Agent-specific knowledge** → `/agent/facts/` (persists across sessions)
3. **Temporary work** → `/session/workspace/` (current session only)

## Example Session

```
> ls /
user/  agent/  session/

> ls /user
preferences.md  profile.md  facts/

> cat /user/facts/api_keys.md
API_KEY: abc123
DEFAULT_CITY: London

> echo "Favorite color: blue" >> /user/preferences.md
Wrote to /user/preferences.md

> cat /session/conversations/summary.md
# Conversation Summary
...recent messages...
```

## Rules

- Files in `/user/`, `/agent/`, `/session/` are automatically indexed for semantic search
- Use descriptive filenames like `api_keys.md`, `weather_prefs.md`
- BLOCKED commands: rm, sudo, curl, wget, python (for security)
"""


# ============ TOOL FACTORY ============

def get_shell_tool(
    agent_id: str,
    session_id: str,
    user_email: str = None,
    workspace_root: str = "./agent_workspaces"
) -> "StructuredTool":
    """
    Create a LangChain tool for shell command execution.
    
    Args:
        agent_id: Agent identifier.
        session_id: Session identifier.
        user_email: User email for user-level persistence.
        workspace_root: Root directory for workspaces.
        
    Returns:
        LangChain StructuredTool.
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError("LangChain is required. Install with: pip install langchain-core")
    
    shell = AgentShell(
        agent_id=agent_id,
        session_id=session_id,
        user_email=user_email,
        workspace_root=workspace_root
    )
    
    def run_shell_command(command: str) -> str:
        """Execute a command in the agent's secure shell environment."""
        return shell.run(command)
    
    tool = StructuredTool.from_function(
        func=run_shell_command,
        name="run_shell_command",
        description="""Execute a command in the agent's secure shell environment.

Available commands:
- ls, cd, pwd, tree: Navigate directories
- cat, head, tail: Read files
- grep "pattern" /path: Search for exact text
- semgrep "concept" /path: Search by meaning (semantic search)
- echo "text" > /file: Write to file
- find /path -name "*.md": Find files

Key directories (Hierarchical):
- /user/facts/ - User-level facts (API keys, preferences) - persists across ALL agents
- /agent/facts/ - Agent-specific facts - persists across sessions
- /agent/learnings/ - Agent insights and patterns
- /session/workspace/ - Scratchpad for current task
- /session/conversations/ - [VIRTUAL] Past chat history (read-only)

Example: echo "API_KEY: abc123" > /user/facts/api_keys.md""",
        args_schema=ShellCommandInput
    )
    
    return tool


def get_shell_tools_for_session(
    agent_id: str,
    session_id: str,
    user_email: str = None,
    workspace_root: str = "./agent_workspaces"
) -> Tuple[AgentShell, List["BaseTool"]]:
    """
    Create shell and tools for a session.
    
    This is the primary integration point for base_agent_inference.py.
    
    Args:
        agent_id: Agent application ID.
        session_id: Current session ID.
        user_email: User email for user-level persistence.
        workspace_root: Root directory for workspaces.
        
    Returns:
        Tuple of (AgentShell, List[BaseTool]).
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError("LangChain is required. Install with: pip install langchain-core")
    
    shell = AgentShell(
        agent_id=agent_id,
        session_id=session_id,
        user_email=user_email,
        workspace_root=workspace_root
    )
    
    def run_shell_command(command: str) -> str:
        """Execute a command in the agent's secure shell environment."""
        return shell.run(command)
    
    tool = StructuredTool.from_function(
        func=run_shell_command,
        name="run_shell_command",
        description="""Execute a command in the agent's secure shell environment.

Available commands:
- ls, cd, pwd, tree: Navigate directories
- cat, head, tail: Read files  
- grep "pattern" /path: Search for exact text
- semgrep "concept" /path: Search by meaning (semantic search)
- echo "text" > /file: Write to file
- find /path -name "*.md": Find files

Key directories (Hierarchical):
- /user/facts/ - User-level facts (API keys, preferences) - persists across ALL agents
- /agent/facts/ - Agent-specific facts - persists across sessions
- /agent/learnings/ - Agent insights and patterns
- /session/workspace/ - Scratchpad for current task
- /session/conversations/ - [VIRTUAL] Past chat history (read-only)

Example: echo "API_KEY: abc123" > /user/facts/api_keys.md""",
        args_schema=ShellCommandInput
    )
    
    log.info(f"✅ AgentShell created: user={user_email}, agent={agent_id}, session={session_id[:12]}")
    
    return shell, [tool]


# ============ OPENAI FUNCTION SCHEMA ============

def get_openai_tool_schema() -> dict:
    """
    Get OpenAI-compatible function schema for the shell tool.
    
    Returns:
        OpenAI tool definition dict.
    """
    return {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": """Execute a command in the agent's secure shell environment.

Use standard Unix commands to explore and manage files:
- ls, cd, pwd: Navigate directories
- cat, head, tail: Read files
- grep "pattern" /path: Search for exact text
- semgrep "concept" /path: Semantic search (by meaning)
- echo "text" > /file: Write to file
- find, mkdir, touch: File operations

Key directories:
- /workspace/ - Scratchpad for current task
- /memory/facts/ - Persistent facts (auto-indexed for semgrep)
- /memory/learnings/ - Insights and patterns

BLOCKED: rm, sudo, curl, wget, python (for security)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }
