"""
Tools - LangChain/OpenAI compatible tool wrappers for AgentOS.
"""

from typing import Dict, Any, List, Optional, Callable
from .kernel import SafeKernel


def get_tool_schema() -> Dict[str, Any]:
    """
    Get the OpenAI-compatible tool schema for run_shell_command.
    """
    return {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": """Execute a command in the agent's secure shell environment. 

Use standard Unix commands to explore and manage files:
- ls, cd, pwd: Navigate directories
- cat, head, tail: Read file contents
- grep: Search for exact text patterns
- find: Find files by name
- echo "content" > file: Write to files
- mkdir, touch: Create directories and files
- semgrep: Semantic search (find by meaning, not exact text)

The environment has:
- /shared/ : READ-ONLY company knowledge (policies, API docs)
- /workspace/ : Your scratchpad for current task
- /memory/ : Your persistent brain (facts, learnings) - auto-indexed for semgrep

BLOCKED: rm, sudo, curl, wget, chmod, python (for safety)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute. Examples: 'ls -la', 'grep -r \"error\" .', 'cat /memory/facts/user.md', 'semgrep \"pricing issues\"', 'echo \"User prefers email\" > /memory/facts/prefs.md'"
                    }
                },
                "required": ["command"]
            }
        }
    }


def get_agent_tools(kernel: SafeKernel) -> List[Dict[str, Any]]:
    """
    Get list of tool schemas for use with OpenAI/Anthropic.
    
    Args:
        kernel: The SafeKernel instance.
        
    Returns:
        List of tool definitions.
    """
    return [get_tool_schema()]


def create_shell_tool(kernel: SafeKernel) -> Callable[[str], str]:
    """
    Create a callable tool function.
    
    Args:
        kernel: The SafeKernel instance.
        
    Returns:
        A function that executes shell commands.
    """
    def run_shell_command(command: str) -> str:
        """Execute a shell command in the secure environment."""
        return kernel.run_shell_command(command)
    
    return run_shell_command


def get_langchain_tools(kernel: SafeKernel) -> List[Any]:
    """
    Get LangChain-compatible tools.
    
    Requires langchain-core to be installed.
    
    Args:
        kernel: The SafeKernel instance.
        
    Returns:
        List of LangChain Tool objects.
    """
    try:
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field
    except ImportError:
        raise ImportError(
            "LangChain tools require langchain-core. "
            "Install with: pip install langchain-core"
        )
    
    class ShellCommandInput(BaseModel):
        command: str = Field(
            description="The shell command to execute (e.g., 'ls -la', 'grep error .', 'cat file.md')"
        )
    
    tool = StructuredTool.from_function(
        func=kernel.run_shell_command,
        name="run_shell_command",
        description=get_tool_schema()["function"]["description"],
        args_schema=ShellCommandInput
    )
    
    return [tool]


# System prompt to include for agents using AgentOS
AGENT_SYSTEM_PROMPT = """You have access to a secure shell environment via the `run_shell_command` tool.

**Your Environment:**
- `/shared/`: READ-ONLY company knowledge (policies, API docs, FAQs).
- `/workspace/`: Your scratchpad for the current task.
- `/memory/`: Your persistent brain. Write important learnings here.

**Key Commands:**
- `ls`, `cd`, `pwd`: Navigate directories.
- `cat`, `head`, `tail`: Read file contents.
- `grep -r "pattern" .`: Search for exact text matches.
- `semgrep "concept" ./path`: Search for conceptually similar content (use when grep fails or for fuzzy search).
- `echo "content" > /memory/file.md`: Save information to memory.
- `find . -name "*.md"`: Find files by name pattern.

**Strategy:**
1. Use `ls` to explore available data.
2. Use `grep` first for specific IDs, codes, or keywords.
3. Use `semgrep` when looking for concepts or when grep returns nothing.
4. Write important findings to `/memory/` so you remember them next time.

**Example Session:**
```
> ls /shared/policies
refund_policy.md
approval_rules.md

> grep "30 day" /shared/policies/refund_policy.md
Line 5: Customers have 30 days to request a full refund.

> echo "Remember: 30-day refund policy applies" > /memory/facts/policy_notes.md
Wrote to /memory/facts/policy_notes.md (indexed to memory)

> semgrep "refund rules"
/memory/facts/policy_notes.md [85% match]: Remember: 30-day refund policy applies...
```
"""
