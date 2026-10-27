# AGENTS.md

> Instructions for AI coding agents working on this codebase.

## Project Overview

**AgentOS** is a filesystem-based agent framework. Instead of building custom tools for every operation, agents interact through a single `run_shell_command` tool with Unix-like commands in a sandboxed environment.

### Architecture
```
agent_os/
├── kernel.py        # Core engine - SafeKernel class (all command implementations)
├── safe_path.py     # Security layer - path resolution and sandboxing
├── vector_store.py  # Semantic search - SimpleEmbedder + VectorStore
├── tools.py         # LangChain/OpenAI tool wrappers
├── prompts.py       # System prompt templates (minimal, temporal, customer_service)
└── tests/           # pytest test suite
```

### Key Classes
- `SafeKernel` - Main entry point. Initialize with `data_root`, `tenant_id`, `agent_id`
- `SafePath` - Resolves virtual paths to real paths, blocks traversal attacks
- `VectorStore` - Stores embeddings for `semgrep` semantic search
- `FileLock` - Thread-safe file locking with optional OS-level locking
- `RateLimiter` - Sliding window rate limiter for command throttling

### Tool Names
When configuring agent tools, use these names:
- `shell` - File system access (ls, cat, echo, mkdir, find, grep, head, tail, tree, wc)
- `run_sql_query` - Database query execution (if SQL tool is enabled)

## write_file() Method (NEW)

Direct file writing that bypasses shell parsing. Use for content with special characters:

```python
# Shell-safe alternative to echo with special chars
result = kernel.write_file(
    virtual_path="/me/uploads/code.py",
    content="print('Hello $USER')",  # Contains $ that would be interpreted
    append=False
)
# Returns: "Wrote to /me/uploads/code.py"

# Append mode
kernel.write_file("/me/log.txt", "New entry\n", append=True)

# Binary content
kernel.write_file("/me/image.png", binary_data, append=False)
```

### Why Use write_file()?

The `echo` command parses content through shell, causing issues with:
- Backticks: `` `command` ``
- Dollar signs: `$VAR`, `$(command)`
- Quotes: `'` and `"`
- Backslashes: `\n`, `\t`

`write_file()` writes raw content directly to disk.

### Auto-Indexing

Files written to `/memory/` are automatically indexed for semantic search:

```python
result = kernel.write_file("/memory/notes/meeting.md", content)
# Returns: "Wrote to /memory/notes/meeting.md (indexed to memory)"
```

## Redirect Quote Handling (NEW)

Redirect targets can now have quotes (useful for paths with spaces):

```python
# Works with quoted paths
kernel.run_shell_command("echo 'data' > '/me/My Documents/file.txt'")
kernel.run_shell_command('echo "data" >> "/me/Project Files/log.txt"')
```

Quotes are automatically stripped from redirect targets.

## Confirmation Protocol (NEW)

SafeKernel supports a confirmation flow for write operations:

```python
kernel = SafeKernel(
    data_root="./data",
    tenant_id="company",
    agent_id="assistant",
    require_confirmation=True,  # Enable confirmation mode
    confirm_operations=["write", "delete"],  # Which ops need confirmation
    confirm_paths=["/me/"]  # Only these paths need confirmation (None = all)
)

# In confirmation mode, write commands return a prompt instead of executing
result = kernel.run_shell_command("echo 'data' > /me/file.txt")
# Returns: "⚠️ Confirmation required: write to /me/file.txt. Re-run with confirmed=True"

# After user confirms:
result = kernel.run_shell_command("echo 'data' > /me/file.txt", confirmed=True)
# Executes the write
```

### Integration with Agent

The `require_confirmation` flag can be toggled at runtime:

```python
# From WebSocket handler in IAF-Agent-Studio
kernel.require_confirmation = msg.human_approval  # True = ask first
agent.auto_run = not msg.human_approval  # False = ask first
```

## Database Access Pattern

Agents query databases through the `run_sql_query` tool — **no credentials files needed**. The system uses SQLite files stored inside the sandboxed virtual filesystem.

### How It Works

```
User: "find pending US invoices"
  → Router selects skill: invoice_dbs
  → SKILL.md declares: tools: [shell, run_sql_query]
  → SkillAgent._create_sql_tool() creates the run_sql_query @tool
  → Agent reads schema: cat /shared/databases/_index.md
  → Agent calls: run_sql_query(database="/shared/databases/invoices_us.db", query="SELECT ...")
  → kernel._resolve_path() translates virtual → real path
  → sqlite3.connect(real_path) → execute → formatted results
```

### Enabling SQL for a Skill

In the skill's `SKILL.md` frontmatter, declare `run_sql_query` in the tools list:

```yaml
---
name: invoice_dbs
tools:
  - shell
  - run_sql_query    # Triggers _create_sql_tool() in SkillAgent
databases:
  invoices_us:
    location: "/shared/databases/invoices_us.db"
  invoices_eu:
    location: "/shared/databases/invoices_eu.db"
---
```

### Database File Layout

```
enterprise_data/tenants/{tenant}/shared/databases/
├── _index.md                  # Agent reads first — which DB to use
├── invoices_us.db             # SQLite file (US region)
├── invoices_eu.db             # SQLite file (EU region)
├── invoices_archive.db        # SQLite file (historical)
├── invoices_us/
│   └── _schema.md             # Table schemas as markdown
├── invoices_eu/
│   └── _schema.md
└── schema/                    # Used by standalone demo agents
    ├── employees.md
    └── activities.md
```

### Schema Discovery Pattern

The agent discovers database schema by **reading markdown docs**, not by running `PRAGMA table_info`:

1. `cat /shared/databases/_index.md` → learn which databases exist, which to use
2. `cat /shared/databases/invoices_us/_schema.md` → learn table columns, types, relationships
3. Construct SQL → `run_sql_query(database="...", query="SELECT ...")`

This is the **"documentation as knowledge base"** pattern — schema docs are maintained alongside the `.db` files.

### Security Guards

| Guard | How |
|-------|-----|
| Path sandboxing | `kernel._resolve_path()` blocks escaping tenant directory |
| SELECT-only | Blocks DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE |
| RBAC | `config.yaml` controls which skills can use `run_sql_query` |
| No credentials | SQLite files on disk — no connection strings or passwords |

### Adding a New Database

1. Create the `.db` file: `enterprise_data/tenants/{tenant}/shared/databases/my_new.db`
2. Create schema docs: `enterprise_data/tenants/{tenant}/shared/databases/my_new/_schema.md`
3. Update `_index.md` with the new database entry
4. Create or update a skill with `run_sql_query` in its tools list
5. Add selection rules to the skill's `INSTRUCTIONS.md`

### Standalone Demo Pattern

For standalone scripts (like `dilo_agent_db.py`), the pattern is self-contained:
- `setup_database()` creates SQLite DB + sample data at startup
- `setup_schema_docs()` writes markdown to `/shared/databases/schema/`
- `run_sql_query` tool uses a hardcoded `DB_PATH` instead of virtual paths

## Build and Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests (36 tests)
pytest tests/test_agentos.py -v

# Run specific test class
pytest tests/test_agentos.py::TestSecurity -v

# Run with coverage
pytest tests/test_agentos.py --cov=. --cov-report=term-missing
```

## Code Style Guidelines

- **Python 3.10+** required
- **Type hints** on all function signatures
- **Docstrings** for all public methods (Google style)
- **No external dependencies** for core kernel (stdlib only)
- **Optional dependencies** for LangChain integration
- Use `datetime.now(timezone.utc)` not `datetime.utcnow()` (deprecated)
- Max line length: 100 characters
- Use `Path` from pathlib, not string path manipulation

## Testing Instructions

1. **Always run tests before committing:**
   ```bash
   pytest tests/test_agentos.py -v
   ```

2. **Test categories:**
   - `TestSecurity` - Path traversal, command injection, permission checks
   - `TestFileOperations` - ls, cat, grep, find, head, tail
   - `TestWriteOperations` - echo, mkdir, touch, auto-indexing
   - `TestSemanticSearch` - semgrep functionality
   - `TestTreeAndWc` - tree and wc commands
   - `TestPersistence` - Memory survives kernel restart

3. **When adding new commands:**
   - Add handler in `kernel.py` `_execute()` method
   - Add to `handlers` dict
   - Write tests for success and error cases
   - Test security implications (can it escape sandbox?)

4. **When modifying security:**
   - Run full security test suite
   - Test path traversal with `..`
   - Test command injection with `&&`, `||`, `;`, `|`
   - Verify blocked commands list is enforced

## Security Considerations

### NEVER allow:
- Path traversal outside sandbox (`..` in paths)
- Command chaining (`&&`, `||`, `;`, `|`, backticks, `$()`)
- Direct shell execution (no subprocess, no os.system)
- Writing to `/shared/` or `/global/` directories
- Blocked commands: `rm`, `sudo`, `curl`, `wget`, `python`, `chmod`, etc.

### When adding features:
- All paths must go through `_resolve_path()` 
- All commands must go through `_parse_command()` for injection check
- Check `_is_writable()` before any write operation
- Log all commands to audit trail

## File Organization

### Virtual Path Mapping
```
/                    → agent_root/
/workspace/          → agent_root/workspace/
/memory/             → agent_root/memory/ (auto-indexed)
/shared/             → tenant shared/ (read-only)
/global/             → global_shared/ (read-only)
/users/{id}/         → agent_root/users/{id}/
```

### Adding New Commands
1. Add method `_cmd_yourcommand(self, args: List[str]) -> str` in kernel.py
2. Add to `handlers` dict in `_execute()` method
3. Handle errors gracefully - return error strings, don't raise
4. Respect `MAX_*` limits for resource protection
5. Add tests in `test_agentos.py`

## PR and Commit Guidelines

- **Commit format:** `feat|fix|docs|test|refactor: description`
- **PR title:** `[AgentOS] Brief description`
- **All PRs must:**
  - Pass all 36+ tests
  - Have no deprecation warnings
  - Include tests for new functionality
  - Update DEVELOPER_GUIDE.md if API changes

## Common Tasks

### Adding a new blocked command
```python
# In kernel.py, add to BLOCKED_COMMANDS list:
BLOCKED_COMMANDS = [
    "rm", "rmdir", ..., "your_command"
]
```

### Adding a new prompt template
```python
# In prompts.py, add new constant:
SYSTEM_PROMPT_YOUR_USECASE = """..."""

# Add to get_prompt_for_use_case() function
```

### Modifying folder structure
```python
# In kernel.py _bootstrap() method, add to dirs list:
dirs = [
    self.agent_root / "your_new_folder",
    ...
]
```

## Debugging Tips

- Check `.audit/commands.jsonl` for command history
- Check `.index/vectors.json` for indexed documents
- Use `tree /memory` to see folder structure
- Use `semgrep "query"` to test semantic search
- Run single test: `pytest tests/test_agentos.py::TestSecurity::test_path_traversal_blocked -v`

## Dependencies

### Required (core)
- Python 3.10+ (stdlib only)

### Optional (LangChain integration)
- langgraph>=0.2.0
- langchain-core>=0.3.0
- langchain-openai>=0.2.0
- python-dotenv>=1.0.0

### Development
- pytest>=8.0.0

## SafeKernel Constructor Parameters

```python
SafeKernel(
    data_root: str,                    # Root directory for all data
    tenant_id: str,                    # Tenant/organization ID
    agent_id: str,                     # Agent identifier
    
    # RBAC parameters
    user_id: Optional[str] = None,     # Current user (for /me/ path)
    user_role: str = "user",           # user | manager | admin | auditor
    team_id: Optional[str] = None,     # User's team
    
    # Team resolution (choose one)
    managed_users: List[str] = None,   # Static list of managed users
    team_file_path: str = None,        # Path to teams.json
    team_resolver_callback = None,     # Custom resolver function
    
    # Options
    vector_store: VectorStore = None,  # For semantic search
    enable_audit_log: bool = True,     # Log all commands
    rate_limit: int = 60,              # Max commands per window
    rate_window: int = 60,             # Window in seconds
    
    # Confirmation (NEW)
    require_confirmation: bool = False,
    confirm_operations: List[str] = ["write", "delete"],
    confirm_paths: List[str] = None,   # None = all paths
)
```
