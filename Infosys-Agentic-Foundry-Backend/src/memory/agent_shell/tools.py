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
        description="Shell command to execute (e.g., 'ls -la', 'cat -n /file', 'readfile /file.pdf', 'grep -C 3 \"error\" /', 'sed -n \"10,20p\" /file', 'stat /file', 'diff /a /b', 'grep \"x\" f | head -5', 'find / -iname \"*.md\"', 'semgrep \"pricing\"', 'get_secret my_api_key', 'get_secret --public shared_key')"
    )


# ============ SYSTEM PROMPT ============

SHELL_AGENT_SYSTEM_PROMPT = """You have access to a secure shell environment via the `run_shell_command` tool.

## Your Environment (Hierarchical)

### Skill Files (READ-ONLY)
- `/skills/` - Skill knowledge files for this agent
- `/skills/{skill_name}/SKILL.md` - Core knowledge, workflow, and instructions
- `/skills/{skill_name}/INSTRUCTIONS.md` - Step-by-step procedures
- `/skills/{skill_name}/EXAMPLES.md` - Example queries and responses
**Usage:** Always read SKILL.md BEFORE answering skill-related queries!

### Enterprise Context (READ-ONLY)
- `/enterprise_context/` - Enterprise-wide context and policies

### Database Files (SHARED across ALL agents - READ-ONLY)
- `/databases/` - Database schema and sample data files
- `/databases/{connection_name}/schema.md` - Database schema (tables, columns, relationships)
- `/databases/{connection_name}/samples.md` - Sample data from each table
**Usage:** Always read schema.md BEFORE writing SQL queries!

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

## Key Commands (18 commands + pipe support)

### Navigation
- `ls [path]` - List directory contents
- `cd [path]` - Change directory
- `pwd` - Print working directory
- `tree [-L N] [--size] /path` - Show directory tree (`--size` shows file sizes)

### Reading Files
- `cat [-n] /file` - Print **text** file contents (`-n` adds line numbers)
- `readfile /file` - Read **any** file (PDF, Excel, DOCX, PPTX, CSV, images, Parquet, etc.)
- `readfile report.pdf` - Auto-discovers the file across all mounts by name
- `head -n 20 /file` - First 20 lines
- `tail -n 20 /file` - Last 20 lines
- `sed -n '10,20p' /file` - Print specific line range (like a targeted read)
- `wc [-lwc] /file` - Count lines/words/chars (supports glob: `wc *.md`)
- `stat /file` - File metadata: size, line count, last modified
- `diff /file1 /file2` - Compare two files (unified diff)

### Database Schema Access
- `ls /databases/` - List all database connections
- `cat /databases/my_db/schema.md` - Read database schema
- `cat /databases/my_db/samples.md` - Read sample data

### Searching
- `grep -r "pattern" /path` - Search for exact text
- `grep -C 3 "pattern" /path` - Search with 3 lines of context before & after match
- `grep -A 5 -B 2 "pattern" /path` - Custom context: 2 lines before, 5 after
- `grep -rni -e "pat1" -e "pat2" /path` - Multi-pattern, case-insensitive, with line numbers
- `grep -v "pattern" /file` - Invert match (show non-matching lines)
- `semgrep "concept" /path` - Search by meaning (use when grep fails!)
- `find /path -name "*.md"` - Find files by name
- `find /path -iname "*.MD"` - Find files by name (case-insensitive)

### Writing
- `echo "content" > /user/facts/api_keys.md` - Write to file
- `echo "more" >> /file` - Append to file
- `mkdir -p /path` - Create directory
- `touch /file` - Create empty file

### Vault Secrets (retrieve stored credentials)
- `get_secret <key_name>` - Get private (user) secret from vault
- `get_secret --public <key_name>` - Get public secret from vault
- `get_secret --group <group_name> <key_name>` - Get group secret from vault
**Usage:** When a skill mentions credentials stored in vault, use `get_secret` to retrieve them at runtime.

### Pipes (chain up to 5 commands)
- `grep "pattern" file | head -5` - First 5 matches
- `cat file | grep "word"` - Search within file output
- `find / -name "*.md" | wc -l` - Count matching files
- `grep -rn "TODO" / | tail -3` - Last 3 TODO matches

## Storage Strategy

1. **Database schema/samples** → `/databases/{conn}/` (SHARED, read-only)
2. **API keys, credentials, user preferences** → `/user/facts/` (persists forever)
3. **Vault secrets** → Use `get_secret` to retrieve from platform vault (public, private, or group)
4. **Agent-specific knowledge** → `/agent/facts/` (persists across sessions)
5. **Temporary work** → `/session/workspace/` (current session only)

## Root-Level Search (IMPORTANT)

The virtual filesystem has 6 independent mount points. When you search from `/`, the search automatically fans out across ALL mounts:

- `grep -r "pattern" /` — Searches ALL 6 directories (skills, databases, enterprise_context, user, agent, session)
- `find / -name "*.md"` — Finds files across ALL 6 directories
- `semgrep "concept" /` — Semantic search across ALL 6 directories

This is the fastest way to locate information when you don't know which directory it's in.
You can also target a specific mount: `grep -r "pattern" /skills/` or `find /databases/ -name "*.md"`

## MANDATORY Shell Usage Rules (follow these ALWAYS)

1. **Before reading any file**, run `stat /file` first. If large (>50 lines), use `sed -n '1,50p'` to read in chunks instead of `cat`.
2. **When searching**, ALWAYS use `grep -C 3` (or `-A`/`-B` for asymmetric context) instead of plain `grep`.
3. **For multiple search terms**, use `grep -e "term1" -e "term2"` in one call instead of separate greps.
4. **To get first/last N results**, pipe: `grep "pattern" file | head -10` or `| tail -5`.
5. **When exploring directories**, prefer `tree --size /path` over `ls` to see full structure with file sizes.
6. **When you need line numbers**, use `cat -n` or `grep -n`.
7. **To compare files**, use `diff /file1 /file2` instead of reading both manually.
8. **To count files or lines**, use `wc` with globs: `wc /path/*.md`.
9. **To find files case-insensitively**, use `find -iname` instead of `-name`.

## Example Session

```
> ls /
skills/  databases/  enterprise_context/  user/  agent/  session/

> ls /skills/
hr_policy/  it_helpdesk/

> cat /skills/hr_policy/SKILL.md
# HR Policy Skill
...

> ls /databases/
sales_db/  customer_db/

> cat /databases/sales_db/schema.md
# Database Schema: sales_db
## Tables:
- orders (id, customer_id, total, created_at)
- products (id, name, price, category)

> grep -r "leave policy" /
/skills/hr_policy/SKILL.md: Annual leave policy: 20 days per year
/enterprise_context/policies.md: Leave policies are managed by HR

> ls /user
preferences.md  profile.md  facts/

> cat /user/facts/api_keys.md
API_KEY: abc123
DEFAULT_CITY: London

> cat /session/conversations/summary.md
# Conversation Summary
...recent messages...
```

## Rules

- Files in `/user/`, `/agent/`, `/session/` are automatically indexed for semantic search
- Files in `/skills/` are READ-ONLY (agent skill knowledge)
- Files in `/databases/` are READ-ONLY (shared across all agents)
- Files in `/enterprise_context/` are READ-ONLY (enterprise policies)
- Use descriptive filenames like `api_keys.md`, `weather_prefs.md`
- BLOCKED commands: rm, sudo, curl, wget, python (for security)
- ALWAYS read SKILL.md BEFORE answering skill-related queries
- ALWAYS read database schema BEFORE writing SQL queries
- Use `grep -r "pattern" /` to search across ALL mounts when unsure where info is

## Binary / Complex Files (PDF, Excel, DOCX, PPTX, images, etc.)

`cat`, `head`, and `tail` only work with **text** files (.md, .txt, .json, .yaml, .csv, etc.).
For **binary / complex files**, use `readfile`:

```
readfile /test_files/annual_report.pdf       # Extract text from PDF
readfile /test_files/financials.xlsx          # Read Excel as table
readfile /test_files/proposal.docx            # Extract text from Word doc
readfile /test_files/slides.pptx              # Extract text from PowerPoint
readfile /test_files/data.parquet             # Read Parquet as table
readfile /test_files/photo.png                # Base64-encode image
```

`readfile` supports: PDF, Excel (.xlsx/.xls), CSV, DOCX, PPTX, JSON, YAML, Parquet, images (PNG/JPG/GIF/BMP/TIFF/WebP/SVG), and any text file.
If you `cat` a binary file, the shell will tell you to use `readfile` instead.

**Auto-discovery:** If you only know the filename (not the full path), just use:
```
readfile report.pdf
```
The shell will search ALL mounts and read the file if found. If multiple files match, it lists the paths so you can pick the right one.
"""


# ============ TOOL FACTORY ============

def get_shell_tool(
    agent_id: str,
    session_id: str,
    user_email: str = None,
    workspace_root: str = "./agent_workspaces",
    department: str = None
) -> "StructuredTool":
    """
    Create a LangChain tool for shell command execution.
    
    Args:
        agent_id: Agent identifier.
        session_id: Session identifier.
        user_email: User email for user-level persistence.
        workspace_root: Root directory for workspaces.
        department: Department name for workspace segregation.
        
    Returns:
        LangChain StructuredTool.
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError("LangChain is required. Install with: pip install langchain-core")
    
    shell = AgentShell(
        agent_id=agent_id,
        session_id=session_id,
        user_email=user_email,
        workspace_root=workspace_root,
        department=department
    )
    
    def run_shell_command(command: str) -> str:
        """Execute a command in the agent's secure shell environment."""
        return shell.run(command)
    
    tool = StructuredTool.from_function(
        func=run_shell_command,
        name="run_shell_command",
        description="""Execute a command in the agent's secure shell environment (18 commands + pipe support).

Available commands:
- ls, cd, pwd: Navigate directories
- tree [--size] /path: Directory tree (--size shows file sizes)
- cat [-n] /file: Read TEXT file (-n for line numbers)
- readfile /file: Read ANY file (PDF, Excel, DOCX, PPTX, images, Parquet, etc.)
  Auto-discovers by filename: readfile report.pdf (searches all mounts)
- head -n N /file, tail -n N /file: First/last N lines
- sed -n '10,20p' /file: Read specific line range
- stat /file: File size, line count, modified time
- diff /file1 /file2: Compare two files (unified diff)
- wc [-lwc] /file|*.md: Count lines/words/chars (supports globs)
- grep [-rinlv] [-A N] [-B N] [-C N] [-e pat] "pattern" /path: Search text
  Flags: -A/-B/-C context lines, -e multi-pattern, -v invert match
- semgrep "concept" /path: Semantic search by meaning
- find /path -name|-iname "pat": Find files (-iname: case-insensitive)
- echo "text" > /file: Write (>> appends)
- mkdir -p /path, touch /file: Create dirs/files
- Pipes: cmd1 | cmd2 (up to 5 stages, e.g. grep "x" f | head -5)

Virtual filesystem (6 mount points):
- /skills/{skill_name}/ - Skill knowledge files (READ-ONLY)
- /enterprise_context/ - Enterprise context and policies (READ-ONLY)
- /databases/{connection}/ - Database schema & samples (SHARED, READ-ONLY)
- /user/facts/ - User-level facts (persists across ALL agents)
- /agent/facts/ - Agent-specific facts (persists across sessions)
- /session/workspace/ - Scratchpad for current task
- /session/conversations/ - [VIRTUAL] Past chat history (read-only)

Root-level search: grep/find/semgrep from "/" search ALL 6 mounts automatically.
Tips: Use readfile for binary/complex files, sed for targeted text reads, stat before reading large files.

Example: cat /skills/hr_policy/SKILL.md""",
        args_schema=ShellCommandInput
    )
    
    return tool


def get_shell_tools_for_session(
    agent_id: str,
    session_id: str,
    user_email: str = None,
    workspace_root: str = "./agent_workspaces",
    department: str = None,
    additional_paths: list = None,
    allowed_absolute_mount_roots: list = None,
    agentos_root_override: str = None,
    databases_root_override: str = None,
) -> Tuple[AgentShell, List["BaseTool"]]:
    """
    Create shell and tools for a session.
    
    This is the primary integration point for base_agent_inference.py.
    
    Args:
        agent_id: Agent application ID.
        session_id: Current session ID.
        user_email: User email for user-level persistence.
        workspace_root: Root directory for workspaces.
        department: Department name for workspace segregation.
        additional_paths: Optional list of dicts with keys 'path' and
            'permission' for custom folder mounts.
        allowed_absolute_mount_roots: Optional list of absolute directory
            paths this agent is allowed to mount (from agent_config.json).
        agentos_root_override: Override for the agentos_agents root path
            (used for cross-department shared skill agents).
        databases_root_override: Override for the databases root path
            (used for cross-department shared agents).
        
    Returns:
        Tuple of (AgentShell, List[BaseTool]).
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError("LangChain is required. Install with: pip install langchain-core")
    
    shell = AgentShell(
        agent_id=agent_id,
        session_id=session_id,
        user_email=user_email,
        workspace_root=workspace_root,
        department=department,
        additional_paths=additional_paths,
        allowed_absolute_mount_roots=allowed_absolute_mount_roots,
        agentos_root_override=agentos_root_override,
        databases_root_override=databases_root_override,
    )
    
    def run_shell_command(command: str) -> str:
        """Execute a command in the agent's secure shell environment."""
        return shell.run(command)
    
    # Build dynamic description: base + additional mounts
    additional_mounts_desc = ""
    if shell._additional_mounts:
        lines = []
        for vprefix, rpath, readonly in shell._additional_mounts:
            mode_label = "READ-ONLY" if readonly else "READ-WRITE"
            lines.append(f"- {vprefix}/ - Additional mount ({mode_label})")
        additional_mounts_desc = "\n" + "\n".join(lines)
    
    mount_count = 6 + len(shell._additional_mounts)
    
    tool_description = f"""Execute a command in the agent's secure shell environment (18 commands + pipe support).

Available commands:
- ls, cd, pwd: Navigate directories
- tree [--size] /path: Directory tree (--size shows file sizes)
- cat [-n] /file: Read TEXT file (-n for line numbers)
- readfile /file: Read ANY file (PDF, Excel, DOCX, PPTX, images, Parquet, etc.)
  Auto-discovers by filename: readfile report.pdf (searches all mounts)
- head -n N /file, tail -n N /file: First/last N lines
- sed -n '10,20p' /file: Read specific line range
- stat /file: File size, line count, modified time
- diff /file1 /file2: Compare two files (unified diff)
- wc [-lwc] /file|*.md: Count lines/words/chars (supports globs)
- grep [-rinlv] [-A N] [-B N] [-C N] [-e pat] "pattern" /path: Search text
  Flags: -A/-B/-C context lines, -e multi-pattern, -v invert match
- semgrep "concept" /path: Semantic search by meaning
- find /path -name|-iname "pat": Find files (-iname: case-insensitive)
- echo "text" > /file: Write (>> appends)
- mkdir -p /path, touch /file: Create dirs/files
- Pipes: cmd1 | cmd2 (up to 5 stages, e.g. grep "x" f | head -5)

Virtual filesystem ({mount_count} mount points):
- /skills/{{skill_name}}/ - Skill knowledge files (READ-ONLY)
- /enterprise_context/ - Enterprise context and policies (READ-ONLY)
- /databases/{{connection}}/ - Database schema & samples (SHARED, READ-ONLY)
- /user/facts/ - User-level facts (persists across ALL agents)
- /agent/facts/ - Agent-specific facts (persists across sessions)
- /session/workspace/ - Scratchpad for current task
- /session/conversations/ - [VIRTUAL] Past chat history (read-only){additional_mounts_desc}

Root-level search: grep/find/semgrep from "/" search ALL {mount_count} mounts automatically.
Tips: Use readfile for binary/complex files, sed for targeted text reads, stat before reading large files.

Example: cat /skills/hr_policy/SKILL.md"""
    
    tool = StructuredTool.from_function(
        func=run_shell_command,
        name="run_shell_command",
        description=tool_description,
        args_schema=ShellCommandInput
    )
    
    log.info(f"✅ AgentShell created: user={user_email}, agent={agent_id}, session={session_id[:12]}")
    if shell._additional_mounts:
        log.info(f"   📁 Additional mounts: {[m[0] for m in shell._additional_mounts]}")
    
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
            "description": """Execute a command in the agent's secure shell environment (18 commands + pipe support).

Available commands:
- ls, cd, pwd: Navigate | tree [--size]: Directory tree
- cat [-n]: Read file (-n for line numbers) | head/tail -n N: First/last lines
- sed -n '10,20p': Read line range | stat: File metadata | diff: Compare files
- wc [-lwc] file|*.md: Count lines/words (supports globs)
- grep [-rinlv] [-A/-B/-C N] [-e pat] "pattern" /path: Search (context, multi-pattern, invert)
- semgrep "concept" /path: Semantic search | find -name|-iname: Find files
- echo "text" > /file: Write (>> appends) | mkdir -p, touch: Create dirs/files
- Pipes: cmd1 | cmd2 (up to 5 stages, e.g. grep "x" f | head -5)

Virtual filesystem: /skills/ (READ-ONLY) | /enterprise_context/ (READ-ONLY) | /databases/ (SHARED, READ-ONLY)
/user/facts/ (persists all agents) | /agent/facts/ (persists sessions) | /session/ (current only)

Root-level search: grep/find/semgrep from "/" search ALL 6 mounts.
BLOCKED: rm, sudo, curl, wget, python (security)""",
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
