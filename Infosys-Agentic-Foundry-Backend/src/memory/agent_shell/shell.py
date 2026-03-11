# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
AgentShell - Secure Unix-like shell for AI agents.

Provides a sandboxed shell environment with:
- Standard Unix commands (ls, cd, cat, grep, find, echo, etc.)
- Semantic search via semgrep command
- Auto-indexing of memory files
- Path security (no traversal, no dangerous commands)
"""

import os
import re
import shlex
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass

# Support both relative and absolute imports
try:
    from .vector_store import VectorStore
except ImportError:
    from vector_store import VectorStore

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    output: str
    error_code: Optional[str] = None


class AgentShell:
    """
    Secure shell environment for AI agents.
    
    Provides Unix-like commands in a sandboxed environment:
    - ls, cd, pwd: Navigate directories
    - cat, head, tail: Read files
    - grep: Search for patterns
    - find: Find files by name
    - echo: Write to files (with > and >>)
    - mkdir, touch: Create directories and files
    - semgrep: Semantic search
    
    Directory Structure (Hierarchical):
    ```
    {workspace_root}/{user_email}/
    ├── user/                           # User-level data (ONLY preferences)
    │   └── preferences.md              # User preferences (theme, language, etc.)
    ├── {agent_id}/
    │   ├── agent/                      # Agent-level data (persistent across sessions)
    │   │   ├── facts/                  # Agent-specific facts, API keys, credentials
    │   │   ├── learnings/              # Agent learnings
    │   │   └── entities/               # Known entities
    │   └── {session_id}/
    │       ├── session/                # Session-level data (current session only)
    │       │   ├── workspace/          # Scratchpad for current task
    │       │   ├── history/            # Session history
    │       │   └── pending_context/    # Multi-turn pending tasks (session-specific)
    │       │       └── current.md      # Current pending context
    │       ├── conversations/          # VIRTUAL: Past chat history (read-only)
    │       │   ├── summary.md
    │       │   └── full.md
    │       └── .index/                 # Vector store index
    ```
    """
    
    # Blocked commands for security
    BLOCKED_COMMANDS = [
        "rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp",
        "sudo", "su", "curl", "wget", "ssh", "scp", "rsync",
        "kill", "pkill", "killall", "shutdown", "reboot",
        "python", "python3", "node", "ruby", "perl", "bash", "sh"
    ]
    
    # Limits
    MAX_READ_BYTES = 50 * 1024  # 50KB
    MAX_READ_LINES = 200
    MAX_LIST_ITEMS = 100
    MAX_GREP_RESULTS = 50
    MAX_FIND_RESULTS = 100
    
    # Dangerous operators
    DANGEROUS_OPERATORS = ["&&", "||", ";", "`", "$(", "${"]
    
    # Virtual directories (not real filesystem)
    VIRTUAL_DIRS = ["/session/conversations"]
    
    def __init__(
        self,
        agent_id: str,
        session_id: str,
        user_email: str = None,
        workspace_root: str = "./agent_workspaces",
        chat_logs_path: str = None,
        enable_semantic_search: bool = True
    ):
        """
        Initialize AgentShell.
        
        Args:
            agent_id: Agent identifier (MANDATORY).
            session_id: Session identifier (MANDATORY).
            user_email: User email for user-level persistence (optional but recommended).
            workspace_root: Root directory for all workspaces.
            chat_logs_path: Path to conversations.json (auto-detected if None).
            enable_semantic_search: Enable semgrep command.
        """
        if not agent_id or not session_id:
            raise ValueError("agent_id and session_id are required")
        
        self.agent_id = agent_id
        self.session_id = session_id
        self.user_email = user_email or "anonymous"
        # Sanitize email for filesystem (replace @ and . with _)
        self.user_dir_name = self.user_email.replace("@", "_at_").replace(".", "_")
        self.workspace_root = Path(workspace_root).resolve()
        
        # Chat logs path - auto-detect if not provided
        if chat_logs_path:
            self.chat_logs_path = Path(chat_logs_path)
        else:
            # Try to find conversations.json relative to src/inference/chat_logs
            possible_paths = [
                Path(__file__).parent.parent.parent / "inference" / "chat_logs" / "conversations.json",
                Path("./src/inference/chat_logs/conversations.json"),
                Path("./chat_logs/conversations.json"),
            ]
            self.chat_logs_path = None
            for p in possible_paths:
                if p.exists():
                    self.chat_logs_path = p.resolve()
                    break
        
        # Build hierarchical paths:
        # {workspace_root}/{user_email}/{agent_id}/{session_id}/
        self.user_root = (self.workspace_root / self.user_dir_name).resolve()
        self.agent_root = (self.user_root / agent_id).resolve()
        self.shell_root = (self.agent_root / session_id).resolve()
        
        # Virtual current working directory
        self.cwd = "/"
        
        # Initialize vector store for semantic search
        self.vector_store: Optional[VectorStore] = None
        if enable_semantic_search:
            index_path = self.shell_root / ".index" / "vectors.json"
            self.vector_store = VectorStore(storage_path=index_path)
        
        # Bootstrap directory structure
        self._bootstrap()
        
        log.info(f"AgentShell initialized: user={self.user_email}, agent={agent_id}, session={session_id}")
    
    def _bootstrap(self):
        """Create the hierarchical directory structure."""
        # User-level directories (ONLY preferences - nothing else)
        user_dirs = [
            self.user_root / "user",
        ]
        
        # Agent-level directories (persistent across sessions for this agent)
        # ALL facts, API keys, credentials go here
        agent_dirs = [
            self.agent_root / "agent" / "facts",
            self.agent_root / "agent" / "learnings",
            self.agent_root / "agent" / "entities",
        ]
        
        # Session-level directories (current session only)
        session_dirs = [
            self.shell_root / "session" / "workspace",
            self.shell_root / "session" / "history",
            self.shell_root / "session" / "pending_context",  # For multi-turn conversation state (session-specific)
            self.shell_root / ".index",
        ]
        
        all_dirs = user_dirs + agent_dirs + session_dirs
        for d in all_dirs:
            d.mkdir(parents=True, exist_ok=True)
        
        # Create empty pending_context file if not exists (session-specific)
        pending_context = self.shell_root / "session" / "pending_context" / "current.md"
        if not pending_context.exists():
            pending_context.write_text("", encoding="utf-8")
        
        # Create user preferences file if not exists (ONLY file in /user/)
        user_prefs = self.user_root / "user" / "preferences.md"
        if not user_prefs.exists():
            user_prefs.write_text(f"""# User Preferences

**User:** {self.user_email}
**Created:** {datetime.now().isoformat()}

## Display Settings
- theme: default
- language: en

## Notification Settings
- email_notifications: true

## Other Preferences
(Add your preferences here)
""", encoding="utf-8")
        
        # Create welcome/README file in session
        readme = self.shell_root / "README.md"
        if not readme.exists():
            readme.write_text(f"""# Agent Workspace

**User:** {self.user_email}
**Agent:** {self.agent_id}
**Session:** {self.session_id}
**Created:** {datetime.now().isoformat()}

## Directory Structure (Hierarchical)

### User Level (ONLY preferences - shared across ALL agents)
- `/user/preferences.md` - User display/notification preferences

### Agent Level (persistent across sessions for THIS agent)
- `/agent/facts/` - Agent-specific facts, API keys, credentials
- `/agent/learnings/` - Patterns and insights
- `/agent/entities/` - Known entities

### Session Level (current session only)
- `/session/workspace/` - Scratchpad for current task
- `/session/history/` - Session history
- `/session/conversations/` - [VIRTUAL] Past chat history (read-only)
  - `summary.md` - AI-generated conversation summaries
  - `full.md` - Full conversation history

## Commands

- `ls`, `cd`, `pwd` - Navigate
- `cat`, `head`, `tail` - Read files
- `grep "pattern" /path` - Search by text
- `semgrep "concept" /path` - Search by meaning
- `echo "text" > /file` - Write to file
- `find /path -name "*.md"` - Find files

## Tips

1. User preferences go to `/user/preferences.md`
2. API keys and facts go to `/agent/facts/` (persists across sessions)
3. Use `/session/workspace/` for temporary work
4. Use `semgrep` when exact grep fails
""", encoding="utf-8")
    
    def run(self, command: str) -> str:
        """
        Execute a shell command.
        
        Args:
            command: The command to execute.
            
        Returns:
            Command output as string.
        """
        command = command.strip()
        
        if not command:
            return ""
        
        # Security checks
        if ".." in command:
            return "Error: Path traversal (..) is not allowed"
        
        for op in self.DANGEROUS_OPERATORS:
            if op in command:
                return f"Error: Operator '{op}' is not allowed"
        
        # Parse command
        try:
            result = self._execute(command)
            return result.output
        except Exception as e:
            log.error(f"Command error: {command} -> {e}")
            return f"Error: {str(e)}"
    
    def _execute(self, command: str) -> CommandResult:
        """Execute a parsed command."""
        # Handle redirects
        redirect = None
        append = False
        
        if " >> " in command:
            parts = command.split(" >> ", 1)
            command = parts[0].strip()
            redirect = parts[1].strip()
            append = True
        elif " > " in command:
            parts = command.split(" > ", 1)
            command = parts[0].strip()
            redirect = parts[1].strip()
        
        # Tokenize
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return CommandResult(False, f"Parse error: {e}")
        
        if not tokens:
            return CommandResult(True, "")
        
        cmd = tokens[0].lower()
        args = tokens[1:]
        
        # Check if blocked
        if cmd in self.BLOCKED_COMMANDS:
            return CommandResult(False, f"Error: '{cmd}' is blocked for security reasons")
        
        # Dispatch to handler
        handlers = {
            "ls": self._cmd_ls,
            "cd": self._cmd_cd,
            "pwd": self._cmd_pwd,
            "cat": self._cmd_cat,
            "head": self._cmd_head,
            "tail": self._cmd_tail,
            "grep": self._cmd_grep,
            "find": self._cmd_find,
            "mkdir": self._cmd_mkdir,
            "touch": self._cmd_touch,
            "echo": lambda a: self._cmd_echo(a, redirect, append),
            "semgrep": self._cmd_semgrep,
            "tree": self._cmd_tree,
            "wc": self._cmd_wc,
            "help": self._cmd_help,
        }
        
        handler = handlers.get(cmd)
        if not handler:
            return CommandResult(False, f"Unknown command: {cmd}. Type 'help' for available commands.")
        
        result = handler(args)
        
        # Handle redirect for non-echo commands
        if redirect and cmd != "echo":
            return self._write_redirect(result.output, redirect, append)
        
        return result
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve a virtual path to real path."""
        path = path.strip()
        
        # Handle empty or current
        if not path or path == ".":
            return self._resolve_cwd()
        
        # Normalize path
        if path.startswith("/"):
            virtual = path
        else:
            if self.cwd == "/":
                virtual = "/" + path
            else:
                virtual = self.cwd + "/" + path
        
        # Clean up path
        parts = [p for p in virtual.split("/") if p and p != "."]
        clean_path = "/" + "/".join(parts)
        
        # Map virtual path to real path based on hierarchy:
        # /user/...    -> user_root/user/...
        # /agent/...   -> agent_root/agent/...
        # /session/... -> shell_root/session/...
        # /...         -> shell_root/... (default, for backwards compat)
        
        if clean_path == "/":
            return self.shell_root
        elif clean_path.startswith("/user/") or clean_path == "/user":
            sub_path = clean_path[5:].lstrip("/")  # Remove "/user" prefix
            if sub_path:
                return self.user_root / "user" / sub_path
            return self.user_root / "user"
        elif clean_path.startswith("/agent/") or clean_path == "/agent":
            sub_path = clean_path[6:].lstrip("/")  # Remove "/agent" prefix
            if sub_path:
                return self.agent_root / "agent" / sub_path
            return self.agent_root / "agent"
        elif clean_path.startswith("/session/") or clean_path == "/session":
            sub_path = clean_path[8:].lstrip("/")  # Remove "/session" prefix
            if sub_path:
                return self.shell_root / "session" / sub_path
            return self.shell_root / "session"
        else:
            # Default: map to shell_root (for any other paths)
            return self.shell_root / clean_path.lstrip("/")
    
    def _resolve_cwd(self) -> Path:
        """Resolve current working directory."""
        return self._resolve_path(self.cwd)
    
    def _to_virtual_path(self, real_path: Path) -> str:
        """Convert real path to virtual path."""
        resolved = real_path.resolve()
        
        # Check if it's under user_root/user
        try:
            rel = resolved.relative_to(self.user_root / "user")
            rel_str = str(rel).replace("\\", "/")
            if rel_str == "." or rel_str == "":
                return "/user"
            return "/user/" + rel_str
        except ValueError:
            pass
        
        # Check if it's under agent_root/agent
        try:
            rel = resolved.relative_to(self.agent_root / "agent")
            rel_str = str(rel).replace("\\", "/")
            if rel_str == "." or rel_str == "":
                return "/agent"
            return "/agent/" + rel_str
        except ValueError:
            pass
        
        # Check if it's under shell_root/session
        try:
            rel = resolved.relative_to(self.shell_root / "session")
            rel_str = str(rel).replace("\\", "/")
            if rel_str == "." or rel_str == "":
                return "/session"
            return "/session/" + rel_str
        except ValueError:
            pass
        
        # Check if it's under shell_root (general)
        try:
            rel = resolved.relative_to(self.shell_root)
            rel_str = str(rel).replace("\\", "/")
            if rel_str == "." or rel_str == "":
                return "/"
            return "/" + rel_str
        except ValueError:
            return str(real_path)
    
    def _is_inside_sandbox(self, path: Path) -> bool:
        """Check if path is inside any of the allowed sandboxes."""
        try:
            resolved_path = path.resolve()
            # Check if inside user_root, agent_root, or shell_root
            for root in [self.user_root, self.agent_root, self.shell_root]:
                try:
                    resolved_path.relative_to(root.resolve())
                    return True
                except ValueError:
                    continue
            return False
        except Exception:
            return False
    
    def _index_file(self, file_path: Path):
        """Index a file for semantic search."""
        if not self.vector_store:
            return
        
        # Index files in /user/, /agent/, and /session/
        virtual_path = self._to_virtual_path(file_path)
        if not (virtual_path.startswith("/user/") or 
                virtual_path.startswith("/agent/") or 
                virtual_path.startswith("/session/")):
            return
        
        try:
            content = file_path.read_text(encoding="utf-8")
            if content.strip():
                self.vector_store.upsert(virtual_path, content)
                log.debug(f"Indexed: {virtual_path}")
        except Exception as e:
            log.warning(f"Failed to index {virtual_path}: {e}")
    
    # =========================================================================
    # CONVERSATION HISTORY METHODS (Virtual /conversations directory)
    # =========================================================================
    
    def _load_conversations(self) -> Dict[str, Any]:
        """Load conversations from chat_logs/conversations.json."""
        if not self.chat_logs_path or not self.chat_logs_path.exists():
            return {}
        
        try:
            import json
            content = self.chat_logs_path.read_text(encoding="utf-8").strip()
            if not content:
                return {}
            return json.loads(content)
        except Exception as e:
            log.warning(f"Failed to load conversations: {e}")
            return {}
    
    def _get_session_messages(self) -> List[Dict[str, Any]]:
        """Get messages for current agent_id and session_id."""
        all_convs = self._load_conversations()
        
        if not all_convs:
            return []
        
        if self.agent_id not in all_convs:
            return []
        
        agent_sessions = all_convs[self.agent_id]
        
        if self.session_id not in agent_sessions:
            return []
        
        session_data = agent_sessions[self.session_id]
        return session_data.get("messages", [])
    
    def _get_session_summaries(self) -> List[Dict[str, Any]]:
        """Get stored summaries for current agent_id and session_id."""
        all_convs = self._load_conversations()
        
        if not all_convs:
            return []
        
        if self.agent_id not in all_convs:
            return []
        
        agent_sessions = all_convs[self.agent_id]
        
        if self.session_id not in agent_sessions:
            return []
        
        session_data = agent_sessions[self.session_id]
        return session_data.get("summaries", [])

    def _generate_conversation_summary(self) -> str:
        """
        Generate a summary of the conversation history.
        ONLY shows AI-generated summaries, NOT raw messages.
        If no summaries exist, instructs user to check full.md instead.
        """
        summaries = self._get_session_summaries()
        messages = self._get_session_messages()
        
        # Build summary header
        lines = [
            "# Conversation Summary",
            ""
        ]
        
        # If no summaries exist
        if not summaries:
            lines.extend([
                "No AI-generated summaries available yet.",
                "",
                f"**Total messages in session:** {len(messages)}",
                "",
                "To see the full conversation history, use:",
                "```",
                "cat /session/conversations/full.md",
                "```",
                "",
                "Or to see recent messages:",
                "```",
                "tail -n 50 /session/conversations/full.md",
                "```"
            ])
            return "\n".join(lines)
        
        # Display AI-generated summaries only
        lines.extend([
            f"**Total Summaries:** {len(summaries)}",
            f"**Total Messages:** {len(messages)}",
            "",
            "---",
            ""
        ])
        
        for i, summary_entry in enumerate(summaries, 1):
            summary_text = summary_entry.get("summary", "No summary text")
            summarized_at = summary_entry.get("summarized_at", "")[:19]
            message_count = summary_entry.get("message_count", 0)
            time_range = summary_entry.get("time_range", {})
            from_time = time_range.get("from", "")[:19]
            to_time = time_range.get("to", "")[:19]
            
            lines.append(f"## Summary {i}")
            lines.append(f"**Created:** {summarized_at}")
            lines.append(f"**Messages Covered:** {message_count} ({from_time} to {to_time})")
            lines.append("")
            lines.append(summary_text)
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Footer with hint
        lines.extend([
            "",
            "*For full conversation details, use: `cat /session/conversations/full.md`*"
        ])
        
        return "\n".join(lines)
    
    def _generate_full_conversation(self) -> str:
        """Generate full conversation history."""
        messages = self._get_session_messages()
        
        if not messages:
            return "# Full Conversation History\n\nNo conversation history found for this session."
        
        lines = [
            "# Full Conversation History",
            f"\n**Agent:** {self.agent_id}",
            f"**Session:** {self.session_id}",
            f"**Total Messages:** {len(messages)}",
            "",
            "---",
            ""
        ]
        
        for i, msg in enumerate(messages, 1):
            human = msg.get("human_message", "")
            ai = msg.get("ai_message", "")
            time = msg.get("end_timestamp", "")
            
            lines.append(f"## Message {i}")
            lines.append(f"**Time:** {time}")
            lines.append("")
            lines.append(f"**User:**")
            lines.append(f"```")
            lines.append(human)
            lines.append(f"```")
            lines.append("")
            lines.append(f"**Assistant:**")
            lines.append(f"```")
            lines.append(ai)
            lines.append(f"```")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _search_conversations(self, pattern: str, case_insensitive: bool = False) -> str:
        """Search conversations for a pattern."""
        messages = self._get_session_messages()
        
        if not messages:
            return "No conversation history to search."
        
        if case_insensitive:
            pattern = pattern.lower()
        
        matches = []
        for i, msg in enumerate(messages, 1):
            human = msg.get("human_message", "")
            ai = msg.get("ai_message", "")
            time = msg.get("end_timestamp", "")[:19]
            
            human_check = human.lower() if case_insensitive else human
            ai_check = ai.lower() if case_insensitive else ai
            
            if pattern in human_check:
                # Find the matching line
                for line_num, line in enumerate(human.split("\n"), 1):
                    line_check = line.lower() if case_insensitive else line
                    if pattern in line_check:
                        matches.append(f"/session/conversations/full.md:msg{i}:user:{line_num}: {line.strip()[:100]}")
            
            if pattern in ai_check:
                for line_num, line in enumerate(ai.split("\n"), 1):
                    line_check = line.lower() if case_insensitive else line
                    if pattern in line_check:
                        matches.append(f"/session/conversations/full.md:msg{i}:ai:{line_num}: {line.strip()[:100]}")
        
        if not matches:
            return f"No matches found for '{pattern}' in conversations."
        
        if len(matches) > self.MAX_GREP_RESULTS:
            matches = matches[:self.MAX_GREP_RESULTS]
            matches.append(f"... truncated ({self.MAX_GREP_RESULTS} matches shown)")
        
        return "\n".join(matches)
    
    def _is_virtual_path(self, path: str) -> bool:
        """Check if path is in a virtual directory."""
        # Normalize path
        path = path.rstrip("/")
        return path.startswith("/session/conversations") or path == "/session/conversations"
    
    def _handle_virtual_cat(self, path: str) -> CommandResult:
        """Handle cat for virtual files."""
        # Normalize path - handle both /conversations and /session/conversations
        path = path.rstrip("/")
        if path in ["/session/conversations/summary.md", "/conversations/summary.md"]:
            return CommandResult(True, self._generate_conversation_summary())
        elif path in ["/session/conversations/full.md", "/conversations/full.md"]:
            return CommandResult(True, self._generate_full_conversation())
        else:
            return CommandResult(False, f"cat: {path}: No such file (valid: summary.md, full.md)")
    
    def _handle_virtual_ls(self, path: str, long_format: bool = False) -> CommandResult:
        """Handle ls for virtual directories."""
        path = path.rstrip("/")
        if path in ["/session/conversations", "/conversations"]:
            if long_format:
                lines = [
                    "total 2",
                    "-r--r--r--  1 agent  agent  0  Jan 13 00:00 summary.md",
                    "-r--r--r--  1 agent  agent  0  Jan 13 00:00 full.md"
                ]
            else:
                lines = ["summary.md", "full.md"]
            return CommandResult(True, "\n".join(lines))
        else:
            return CommandResult(False, f"ls: {path}: No such directory")
    
    # =========================================================================
    # COMMAND IMPLEMENTATIONS
    # =========================================================================
    
    def _cmd_ls(self, args: List[str]) -> CommandResult:
        """List directory contents."""
        show_all = "-a" in args or "-la" in args or "-al" in args
        long_format = "-l" in args or "-la" in args or "-al" in args
        
        # Get path argument
        path_arg = None
        for a in args:
            if not a.startswith("-"):
                path_arg = a
                break
        
        # Resolve the path
        if path_arg:
            resolved = path_arg if path_arg.startswith("/") else f"{self.cwd.rstrip('/')}/{path_arg}"
        else:
            resolved = self.cwd
        
        # Normalize resolved path
        parts = [p for p in resolved.split("/") if p and p != "."]
        resolved = "/" + "/".join(parts) if parts else "/"
        
        # Check for virtual directories
        if self._is_virtual_path(resolved):
            return self._handle_virtual_ls(resolved, long_format)
        
        # Special handling for root - show the virtual hierarchy
        if resolved == "/":
            if long_format:
                lines = [
                    f"drw-r--r--        0 {datetime.now().strftime('%Y-%m-%d %H:%M')} user/           # User-level (all agents)",
                    f"drw-r--r--        0 {datetime.now().strftime('%Y-%m-%d %H:%M')} agent/          # Agent-level (all sessions)",
                    f"drw-r--r--        0 {datetime.now().strftime('%Y-%m-%d %H:%M')} session/        # Session-level (current)"
                ]
            else:
                lines = ["user/  agent/  session/"]
            return CommandResult(True, "\n".join(lines) if long_format else lines[0])
        
        target = self._resolve_path(path_arg or ".")
        
        if not target.exists():
            return CommandResult(False, f"ls: {path_arg or '.'}: No such directory")
        
        if not target.is_dir():
            return CommandResult(True, self._to_virtual_path(target))
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "ls: Access denied")
        
        try:
            items = list(target.iterdir())
            
            # Filter hidden files
            if not show_all:
                items = [i for i in items if not i.name.startswith(".")]
            
            items = sorted(items, key=lambda x: (not x.is_dir(), x.name.lower()))
            items = items[:self.MAX_LIST_ITEMS]
            
            # Check if we're at /session - add virtual conversations directory
            is_at_session = resolved == "/session"
            
            if long_format:
                lines = []
                # Add virtual conversations directory if at /session
                if is_at_session:
                    lines.append(f"drw-r--r--        0 {datetime.now().strftime('%Y-%m-%d %H:%M')} conversations/  [virtual]")
                for item in items:
                    try:
                        stat = item.stat()
                        is_dir = "d" if item.is_dir() else "-"
                        size = stat.st_size
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                        name = item.name + "/" if item.is_dir() else item.name
                        lines.append(f"{is_dir}rw-r--r-- {size:>8} {mtime} {name}")
                    except:
                        lines.append(f"?--------- ? ? {item.name}")
                return CommandResult(True, "\n".join(lines))
            else:
                names = []
                # Add virtual conversations directory if at /session
                if is_at_session:
                    names.append("conversations/")
                for item in items:
                    name = item.name + "/" if item.is_dir() else item.name
                    names.append(name)
                return CommandResult(True, "  ".join(names))
                
        except PermissionError:
            return CommandResult(False, "ls: Permission denied")
    
    def _cmd_cd(self, args: List[str]) -> CommandResult:
        """Change directory."""
        if not args:
            self.cwd = "/"
            return CommandResult(True, "")
        
        path = args[0]
        
        # Handle virtual directories - /session/conversations
        if path in ["/session/conversations", "session/conversations", "conversations"]:
            # If just "conversations", only valid from /session
            if path == "conversations" and self.cwd != "/session":
                return CommandResult(False, f"cd: {path}: No such directory")
            self.cwd = "/session/conversations"
            return CommandResult(True, "")
        
        # Build absolute virtual path
        if path.startswith("/"):
            virtual = path
        else:
            if self.cwd == "/":
                virtual = "/" + path
            else:
                virtual = self.cwd.rstrip("/") + "/" + path
        
        # Normalize
        parts = [p for p in virtual.split("/") if p and p != "."]
        virtual = "/" + "/".join(parts) if parts else "/"
        
        # Handle special virtual paths
        if virtual in ["/user", "/agent", "/session"]:
            self.cwd = virtual
            return CommandResult(True, "")
        
        target = self._resolve_path(path)
        
        if not target.exists():
            return CommandResult(False, f"cd: {path}: No such directory")
        
        if not target.is_dir():
            return CommandResult(False, f"cd: {path}: Not a directory")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "cd: Access denied")
        
        self.cwd = self._to_virtual_path(target)
        return CommandResult(True, "")
    
    def _cmd_pwd(self, args: List[str]) -> CommandResult:
        """Print working directory."""
        return CommandResult(True, self.cwd)
    
    def _cmd_cat(self, args: List[str]) -> CommandResult:
        """Concatenate and print files."""
        if not args:
            return CommandResult(False, "cat: missing file operand")
        
        outputs = []
        for path_arg in args:
            # Resolve the path
            if path_arg.startswith("/"):
                resolved_virtual = path_arg
            else:
                resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
            
            # Check for virtual files (conversations)
            if self._is_virtual_path(resolved_virtual):
                result = self._handle_virtual_cat(resolved_virtual)
                outputs.append(result.output)
                continue
            
            target = self._resolve_path(path_arg)
            
            if not target.exists():
                outputs.append(f"cat: {path_arg}: No such file")
                continue
            
            if target.is_dir():
                outputs.append(f"cat: {path_arg}: Is a directory")
                continue
            
            if not self._is_inside_sandbox(target):
                outputs.append(f"cat: {path_arg}: Access denied")
                continue
            
            try:
                content = target.read_text(encoding="utf-8")
                if len(content) > self.MAX_READ_BYTES:
                    content = content[:self.MAX_READ_BYTES]
                    content += f"\n... [truncated at {self.MAX_READ_BYTES} bytes]"
                outputs.append(content)
            except Exception as e:
                outputs.append(f"cat: {path_arg}: {e}")
        
        return CommandResult(True, "\n".join(outputs))
    
    def _cmd_head(self, args: List[str]) -> CommandResult:
        """Print first lines of file."""
        num_lines = 10
        path_arg = None
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    num_lines = int(args[i + 1])
                    i += 2
                    continue
                except:
                    pass
            elif args[i].startswith("-") and args[i][1:].isdigit():
                num_lines = int(args[i][1:])
            else:
                path_arg = args[i]
            i += 1
        
        if not path_arg:
            return CommandResult(False, "head: missing file operand")
        
        # Resolve the virtual path for conversations
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        
        # Check for virtual files (conversations)
        if self._is_virtual_path(resolved_virtual):
            result = self._handle_virtual_cat(resolved_virtual)
            if not result.success:
                return result
            lines = result.output.splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[:num_lines]))
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"head: {path_arg}: No such file")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"head: Access denied")
        
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[:num_lines]))
        except Exception as e:
            return CommandResult(False, f"head: {e}")
    
    def _cmd_tail(self, args: List[str]) -> CommandResult:
        """Print last lines of file."""
        num_lines = 10
        path_arg = None
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    num_lines = int(args[i + 1])
                    i += 2
                    continue
                except:
                    pass
            elif args[i].startswith("-") and args[i][1:].isdigit():
                num_lines = int(args[i][1:])
            else:
                path_arg = args[i]
            i += 1
        
        if not path_arg:
            return CommandResult(False, "tail: missing file operand")
        
        # Resolve the virtual path for conversations
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        
        # Check for virtual files (conversations)
        if self._is_virtual_path(resolved_virtual):
            result = self._handle_virtual_cat(resolved_virtual)
            if not result.success:
                return result
            lines = result.output.splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[-num_lines:]))
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"tail: {path_arg}: No such file")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"tail: Access denied")
        
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
            num_lines = min(num_lines, self.MAX_READ_LINES)
            return CommandResult(True, "\n".join(lines[-num_lines:]))
        except Exception as e:
            return CommandResult(False, f"tail: {e}")
    
    def _cmd_grep(self, args: List[str]) -> CommandResult:
        """Search for pattern in files."""
        if len(args) < 1:
            return CommandResult(False, "grep: missing pattern")
        
        # Parse options
        recursive = "-r" in args or "-R" in args
        ignore_case = "-i" in args
        show_line_nums = "-n" in args
        
        # Get pattern and path
        pattern = None
        path_arg = "."
        
        for a in args:
            if a.startswith("-"):
                continue
            if pattern is None:
                pattern = a
            else:
                path_arg = a
                break
        
        if not pattern:
            return CommandResult(False, "grep: missing pattern")
        
        # Resolve the path
        if path_arg.startswith("/"):
            resolved_virtual = path_arg
        else:
            resolved_virtual = f"{self.cwd.rstrip('/')}/{path_arg}"
        
        # Check if searching in conversations
        if self._is_virtual_path(resolved_virtual) or resolved_virtual == "/conversations":
            conv_results = self._search_conversations(pattern, ignore_case)
            return CommandResult(True, conv_results)
        
        # Compile pattern
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return CommandResult(False, f"grep: invalid pattern: {e}")
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"grep: {path_arg}: No such file or directory")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "grep: Access denied")
        
        results = []
        
        def search_file(file_path: Path):
            virtual = self._to_virtual_path(file_path)
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        if show_line_nums:
                            results.append(f"{virtual}:{i}: {line}")
                        else:
                            results.append(f"{virtual}: {line}")
                        if len(results) >= self.MAX_GREP_RESULTS:
                            return True  # Stop
            except:
                pass
            return False  # Continue
        
        if target.is_file():
            search_file(target)
        elif recursive:
            for file_path in target.rglob("*"):
                if file_path.is_file() and file_path.suffix in [".md", ".txt", ".json", ".yaml", ".yml", ""]:
                    if search_file(file_path):
                        break
        else:
            for file_path in target.iterdir():
                if file_path.is_file():
                    if search_file(file_path):
                        break
        
        if not results:
            return CommandResult(True, f"No matches for '{pattern}'")
        
        output = "\n".join(results)
        if len(results) >= self.MAX_GREP_RESULTS:
            output += f"\n... [truncated at {self.MAX_GREP_RESULTS} results]"
        
        return CommandResult(True, output)
    
    def _cmd_find(self, args: List[str]) -> CommandResult:
        """Find files by name."""
        path_arg = "."
        name_pattern = None
        file_type = None
        
        i = 0
        while i < len(args):
            if args[i] == "-name" and i + 1 < len(args):
                name_pattern = args[i + 1]
                i += 2
            elif args[i] == "-type" and i + 1 < len(args):
                file_type = args[i + 1]
                i += 2
            elif not args[i].startswith("-"):
                path_arg = args[i]
                i += 1
            else:
                i += 1
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"find: {path_arg}: No such directory")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "find: Access denied")
        
        results = []
        
        for item in target.rglob("*"):
            if len(results) >= self.MAX_FIND_RESULTS:
                break
            
            # Type filter
            if file_type == "f" and not item.is_file():
                continue
            if file_type == "d" and not item.is_dir():
                continue
            
            # Name filter
            if name_pattern and not fnmatch.fnmatch(item.name, name_pattern):
                continue
            
            results.append(self._to_virtual_path(item))
        
        if not results:
            return CommandResult(True, "No files found")
        
        output = "\n".join(results)
        if len(results) >= self.MAX_FIND_RESULTS:
            output += f"\n... [truncated at {self.MAX_FIND_RESULTS} results]"
        
        return CommandResult(True, output)
    
    def _cmd_mkdir(self, args: List[str]) -> CommandResult:
        """Create directories."""
        if not args:
            return CommandResult(False, "mkdir: missing operand")
        
        parents = "-p" in args
        
        for path_arg in args:
            if path_arg.startswith("-"):
                continue
            
            target = self._resolve_path(path_arg)
            
            if not self._is_inside_sandbox(target):
                return CommandResult(False, f"mkdir: {path_arg}: Access denied")
            
            try:
                if parents:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.mkdir(exist_ok=False)
            except FileExistsError:
                return CommandResult(False, f"mkdir: {path_arg}: File exists")
            except Exception as e:
                return CommandResult(False, f"mkdir: {e}")
        
        return CommandResult(True, "")
    
    def _cmd_touch(self, args: List[str]) -> CommandResult:
        """Create empty files."""
        if not args:
            return CommandResult(False, "touch: missing operand")
        
        for path_arg in args:
            target = self._resolve_path(path_arg)
            
            if not self._is_inside_sandbox(target):
                return CommandResult(False, f"touch: {path_arg}: Access denied")
            
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            except Exception as e:
                return CommandResult(False, f"touch: {e}")
        
        return CommandResult(True, "")
    
    def _cmd_echo(self, args: List[str], redirect: Optional[str], append: bool) -> CommandResult:
        """Echo text, optionally to a file."""
        text = " ".join(args)
        
        # Remove surrounding quotes if present
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        
        if not redirect:
            return CommandResult(True, text)
        
        return self._write_redirect(text + "\n", redirect, append)
    
    def _write_redirect(self, content: str, path: str, append: bool) -> CommandResult:
        """Write content to file via redirect."""
        target = self._resolve_path(path)
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, f"Redirect: {path}: Access denied")
        
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            
            mode = "a" if append else "w"
            with open(target, mode, encoding="utf-8") as f:
                f.write(content)
            
            # Index if in memory folder
            self._index_file(target)
            
            action = "Appended to" if append else "Wrote to"
            virtual = self._to_virtual_path(target)
            
            # Show index status for memory files
            if virtual.startswith("/memory/") and self.vector_store:
                return CommandResult(True, f"{action} {virtual} (indexed to memory)")
            return CommandResult(True, f"{action} {virtual}")
            
        except Exception as e:
            return CommandResult(False, f"Redirect error: {e}")
    
    def _cmd_semgrep(self, args: List[str]) -> CommandResult:
        """Semantic search using vector store."""
        if not self.vector_store:
            return CommandResult(False, "semgrep: Semantic search is not enabled")
        
        if not args:
            return CommandResult(False, "semgrep: missing query")
        
        # Parse arguments
        query = None
        path_prefix = None
        top_k = 10
        
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try:
                    top_k = int(args[i + 1])
                    i += 2
                    continue
                except:
                    pass
            elif not args[i].startswith("-"):
                if query is None:
                    query = args[i]
                else:
                    path_prefix = args[i]
            i += 1
        
        if not query:
            return CommandResult(False, "semgrep: missing query")
        
        # Convert path to virtual prefix
        if path_prefix:
            resolved = self._resolve_path(path_prefix)
            path_prefix = self._to_virtual_path(resolved)
        
        results = self.vector_store.search(query, path_prefix=path_prefix, top_k=top_k)
        
        if not results:
            return CommandResult(True, f"No semantic matches for '{query}'")
        
        lines = [f"Found {len(results)} semantic matches for '{query}':\n"]
        for r in results:
            score_pct = int(r.score * 100)
            lines.append(f"{r.path} [{score_pct}% match]: {r.snippet}")
        
        return CommandResult(True, "\n".join(lines))
    
    def _cmd_tree(self, args: List[str]) -> CommandResult:
        """Show directory tree."""
        path_arg = args[0] if args else "."
        max_depth = 3
        
        for i, a in enumerate(args):
            if a == "-L" and i + 1 < len(args):
                try:
                    max_depth = int(args[i + 1])
                except:
                    pass
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"tree: {path_arg}: No such directory")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "tree: Access denied")
        
        lines = [self._to_virtual_path(target)]
        
        def build_tree(path: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                items = [i for i in items if not i.name.startswith(".")]
                
                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    name = item.name + "/" if item.is_dir() else item.name
                    lines.append(f"{prefix}{connector}{name}")
                    
                    if item.is_dir() and depth < max_depth:
                        extension = "    " if is_last else "│   "
                        build_tree(item, prefix + extension, depth + 1)
            except:
                pass
        
        build_tree(target, "", 1)
        return CommandResult(True, "\n".join(lines))
    
    def _cmd_wc(self, args: List[str]) -> CommandResult:
        """Count lines, words, characters."""
        if not args:
            return CommandResult(False, "wc: missing file operand")
        
        show_lines = "-l" in args
        show_words = "-w" in args
        show_chars = "-c" in args
        
        # If no specific flag, show all
        if not (show_lines or show_words or show_chars):
            show_lines = show_words = show_chars = True
        
        path_arg = None
        for a in args:
            if not a.startswith("-"):
                path_arg = a
                break
        
        if not path_arg:
            return CommandResult(False, "wc: missing file operand")
        
        target = self._resolve_path(path_arg)
        
        if not target.exists():
            return CommandResult(False, f"wc: {path_arg}: No such file")
        
        if not self._is_inside_sandbox(target):
            return CommandResult(False, "wc: Access denied")
        
        try:
            content = target.read_text(encoding="utf-8")
            lines = len(content.splitlines())
            words = len(content.split())
            chars = len(content)
            
            parts = []
            if show_lines:
                parts.append(str(lines))
            if show_words:
                parts.append(str(words))
            if show_chars:
                parts.append(str(chars))
            parts.append(self._to_virtual_path(target))
            
            return CommandResult(True, " ".join(parts))
        except Exception as e:
            return CommandResult(False, f"wc: {e}")
    
    def _cmd_help(self, args: List[str]) -> CommandResult:
        """Show help."""
        help_text = """Available Commands:

Navigation:
  ls [path]           List directory contents
  cd [path]           Change directory
  pwd                 Print working directory
  tree [path]         Show directory tree

Reading Files:
  cat <file>          Print file contents
  head [-n N] <file>  Print first N lines (default: 10)
  tail [-n N] <file>  Print last N lines (default: 10)
  wc [-lwc] <file>    Count lines/words/chars

Searching:
  grep [-rin] <pattern> [path]    Search for text pattern
  semgrep <query> [path]          Semantic search (by meaning)
  find <path> -name <pattern>     Find files by name

Writing:
  echo "text" > file              Write to file
  echo "text" >> file             Append to file
  mkdir [-p] <path>               Create directory
  touch <file>                    Create empty file

Directory Structure (Hierarchical):

  /user/                      - User preferences ONLY (shared across ALL agents)
    └── preferences.md        - Display, notification, language settings

  /agent/                     - Agent-level (persists across sessions)
    ├── facts/                - API keys, credentials, agent-specific facts
    ├── learnings/            - Patterns and insights
    └── entities/             - Known entities (people, places, events)

  /session/                   - Session-level (current session only)
    ├── workspace/            - Working files for current task
    ├── history/              - Session history
    ├── pending_context/      - Multi-turn conversation state (session-specific)
    │   └── current.md        - Current pending action waiting for user input
    └── conversations/        - [VIRTUAL] Past chat history (read-only)
        ├── summary.md        - AI-generated summaries ONLY
        └── full.md           - Full conversation history

Storage Strategy:
  - User preferences     → /user/preferences.md
  - API keys, facts      → /agent/facts/ (persists across sessions)
  - Pending context      → /session/pending_context/current.md (session-specific)
  - Temporary work       → /session/workspace/ (current session only)

Pending Context (Multi-Turn Conversations):
  cat /session/pending_context/current.md   Check if waiting for user input
  echo "action: ..." > /session/pending_context/current.md   Create pending context
  echo "" > /session/pending_context/current.md   Clear pending context after completion

Conversation Commands:
  cat /session/conversations/summary.md   Read AI-generated summaries
  cat /session/conversations/full.md      Read full conversation
  tail -n 50 /session/conversations/full.md   Read recent messages
  grep "keyword" /session/conversations   Search conversations

Tips:
  - ALWAYS check pending_context before processing new requests
  - DELETE pending_context after completing the action
  - summary.md shows ONLY AI-generated summaries (not raw messages)
  - Use full.md or tail to see actual conversation messages
"""
        return CommandResult(True, help_text)
