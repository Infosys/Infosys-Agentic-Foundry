# AgentOS — Kernel Internals

## Overview

`SafeKernel` is the execution core of AgentOS. It wraps all tool execution in a sandboxed, auditable environment that enforces path-based access control, command blocking, rate limiting, and per-user RBAC — all while exposing a single clean interface to the LLM: `run_shell_command(command)`.

The design philosophy is deliberate: instead of dozens of custom tools, the kernel teaches the LLM familiar Unix commands and handles safety internally. This leverages the LLM's existing knowledge of shell commands while keeping the trust boundary thin and auditable.

Studio creates kernels through `agent_os.kernel_runtime.create_kernel_runtime()`.
`AGENTOS_KERNEL_BACKEND=local` returns an in-process `SafeKernel`. With
`AGENTOS_KERNEL_BACKEND=remote`, the main agent process uses
`RemoteKernelRuntime` and sends signed requests to `IAF-Agent-Studio/kernel_worker.py`.
Any other value **fails closed** — `create_kernel_runtime()` raises `ValueError` rather than
silently falling back to the in-process `local` kernel (which, in a shared deployment, would
run untrusted code in the API process).
The worker owns the actual `SafeKernel`, so shell commands, `write_file`,
Python subprocesses, credential handles, path checks, and audit writes execute
inside the kernel boundary while keeping the same tool contract for the agent.

---

## Kernel Architecture

```
LLM / SkillAgent
       ↓
SafeKernel.run_shell_command(command, confirmed=False)
       ↓
rate_limiter.check()           ← sliding window (60 req/60s)
       ↓
_execute(command, confirmed)
       ↓
_parse_command(command)        ← tokenize, block dangerous operators
       ↓
BLOCKED_COMMANDS check         ← static denylist
       ↓
_requires_confirmation()       ← write-op confirmation gate
       ↓
handlers[cmd](args)            ← per-command implementation
       ↓
_log_command()                 ← append-only JSONL audit trail
       ↓
Return output string
```

---

## Initialization

```python
SafeKernel(
    data_root: str,                   # Enterprise root directory (required)
    tenant_id: str,                   # required
    agent_id: str,                    # required
    user_id: str | None = None,
    user_role: str = UserRole.USER,   # "user" | "manager" | "admin" | "auditor"
    team_id: str | None = None,
    managed_users: list[str] | None = None,          # Option A: static team list
    team_file_path: str | None = None,               # Option B: teams.json
    team_resolver_callback: callable | None = None,  # Option C: external callback
    vector_store: VectorStore | None = None,
    enable_audit_log: bool = True,
    rate_limit: int | None = None,    # per-user; default 60 (DEFAULT_RATE_LIMIT)
    rate_window: int | None = None,   # default 60 (DEFAULT_RATE_WINDOW)
    require_confirmation: bool = False,
    confirm_operations: list[str] | None = None,  # default ["write", "delete"]
    confirm_paths: list[str] | None = None,       # None means all paths
    local_mount: str | None = None,   # Optional external filesystem mount
    secret_provider: Any | None = None,  # Optional vault/secret provider override
)
```

**Initialization sequence:**
1. Validate and resolve all directory paths
2. Initialize `SafePath` for path sandboxing
3. Set up RBAC via `TeamResolver`
4. Initialize `RateLimiter` with configured window
5. Initialize `VectorStore` for semantic memory indexing
6. Detect ripgrep binary for accelerated grep
7. Call `_bootstrap()` to create the agent directory structure

The kernel also tracks `current_skill` for credential access. When an agent calls `get_credential`, the kernel passes the active skill (falling back to agent id) as the credential consumer and the authenticated user as accessor, so scoped credentials cannot be fetched without a concrete consumer identity. When external access governance is enabled, the kernel also receives the request-bound entitlement checker and verifies the external resources linked to a credential before resolving the credential. External resource label/risk and skill context are passed into the normalized policy provider input so enterprise policy adapters can make action-level decisions without reading kernel internals. Resolution then goes through the `SecretProvider` boundary; the default `CredentialStoreSecretProvider` delegates to the existing env/file/Fernet `CredentialStore`, while enterprise vault adapters can be injected without changing the kernel command path. The kernel returns only a masked `$CRED_*` variable. `SkillAgent` attaches its `HookRunner` to `SafeKernel`; kernel-internal `get_credential` calls now emit safe `PreToolUse`/`PostToolUse` contexts containing only credential name/field metadata and non-secret outcome summaries.

**`_bootstrap()` creates:**
```
{agent_root}/
  workspace/          scratchpad (cleared per session)
  memory/
    learnings/
    history/
  users/{user_id}/
    profile.md        agent-specific user profile
  .audit/             audit log directory
  .index/             vector store index
```

---

## Command Dispatch

The kernel maps Unix command names to internal handler methods. All handlers follow the same signature: `_cmd_{name}(args: List[str]) → str`.

| Command | Handler | Description |
|---|---|---|
| `ls` | `_cmd_ls` | Directory listing |
| `dir` | `_cmd_ls` | Alias for `ls` |
| `cd` | `_cmd_cd` | Change virtual working directory |
| `pwd` | `_cmd_pwd` | Print virtual working directory |
| `cat` | `_cmd_cat` | File reading |
| `head` | `_cmd_head` | First N lines |
| `tail` | `_cmd_tail` | Last N lines |
| `grep` | `_cmd_grep` | Pattern search |
| `find` | `_cmd_find` | File discovery |
| `mkdir` | `_cmd_mkdir` | Directory creation |
| `touch` | `_cmd_touch` | File creation |
| `echo` | `_cmd_echo` | Write to file or stdout |
| `semgrep` | `_cmd_semgrep` | Semantic search |
| `tree` | `_cmd_tree` | Directory tree |
| `wc` | `_cmd_wc` | Word/line/char count |
| `curl` | `_cmd_curl` | HTTP requests |
| `python3` | `_cmd_python3` | Python execution |

`get_credential` and (when enabled) `python3` are dispatched via dedicated fast-paths in `_execute()` before `_parse_command()` runs, because their argument strings legitimately contain characters (`;`, `|`, quotes) that the generic parser would reject. `python3` is only added to the handler map when `python3_enabled` is true; otherwise it falls through to `BLOCKED_COMMANDS`.

Unrecognised commands return an error message — they are never passed to the OS shell.

---

## Command Parsing

`_parse_command(command: str) → (cmd_name, args)`:

1. **Tokenizer** — respects single and double quotes; splits on whitespace
2. **Dangerous operator blocking** — raises `SecurityError` if `&&`, `||`, `;`, `` ` ``, `$(`, `${` appear anywhere in the command
3. **Pipe restriction** — `|` is blocked except for `curl` piped into an allowlisted read-only
   filter (`grep`/`egrep`/`fgrep`/`head`/`tail`/`wc`/`sort`/`uniq`/`cut`/`tr`/`jq`). The
   pipeline runs as chained argv arrays with **no shell** (`_run_argv_pipeline`); a downstream
   interpreter (`python3`/`bash`/`sh`/`node`/`awk`/…) returns `Error [PIPE_BLOCKED]`. This
   prevents the download-and-execute RCE pattern `curl <url> | python3`.
4. **Redirection parsing** — `>` and `>>` are extracted and handled per-command (not via OS shell)

---

## Blocked Commands

Static denylist checked before dispatch:

```python
BLOCKED_COMMANDS = [
    "rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp",
    "sudo", "su", "wget", "ssh", "scp", "rsync",
    "kill", "pkill", "killall", "shutdown", "reboot",
    "dd", "mkfs", "mount", "umount", "fdisk",
    "python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh",
]
```

Note: `curl` is **not** blocked — it is served by the `_cmd_curl` handler for API
calls. `python3` is listed here but is only reached when `python3_enabled` is false;
when Python execution is enabled the `python3` fast-path handles it first.

Any attempt to run a blocked command returns an explicit error without executing.

---

## Confirmation Protocol

When `require_confirmation=True` (the constructor default is `False`; Studio enables it per deployment), write operations require a two-step flow:

**Step 1 — First call:** `_requires_confirmation()` detects a write operation targeting a sensitive path. Returns a human-readable confirmation request string instead of executing.

**Step 2 — Second call:** Same command with `confirmed=True` bypasses the gate and executes.

`_requires_confirmation()` only fires for operation types listed in `confirm_operations`
(default `["write", "delete"]`):
- Write operations: `echo ... > file`, `touch`
- Delete: `rm`
- `mkdir` — only when `"mkdir"` is added to `confirm_operations` (not a default)
- When `confirm_paths` is configured, only targets matching one of those path prefixes require confirmation

File locking is thread-safe: Python `threading.Lock` + OS-level `fcntl.flock` on Unix.

---

## Rate Limiting

`RateLimiter` implements a sliding window counter:

```python
class RateLimiter:
    def __init__(self, max_requests=60, window_seconds=60)
    def check() → None  # Raises RateLimitExceeded if over limit
```

- Maintains a deque of request timestamps
- On each `check()`, prunes timestamps older than `window_seconds`
- If `len(timestamps) >= max_requests`, raises `RateLimitExceeded(retry_after=...)`
- Applied at the start of every `run_shell_command()` call

---

## Audit Logging

Every command execution is logged to an append-only JSONL file:

**Location:** `{agent_root}/.audit/commands_{YYYY-MM-DD}.jsonl`

**Format:**
```json
{
  "timestamp": "2026-04-13T09:23:41.123456+00:00",
  "command": "cat /me/profile.md",
  "output_preview": "# Global Profile: madhan...",
  "success": true,
  "duration_ms": 7
}
```

**Retention policy:**
- Logs older than 1 day are compressed to `.gz`
- Logs older than 30 days are deleted
- File locking prevents concurrent writes from corrupting entries

Toggle with `enable_audit_log=False` to disable (useful in test environments).

External access decisions are written separately to `{tenant_root}/shared/databases/external_access_audit.jsonl`. These events record user, skill, action, resource, allow/deny, and redacted command previews for credential, DB, MCP, and kernel-observed HTTP access.

---

## Memory Auto-Indexing

Writing to `/memory/` paths automatically indexes the file into the `VectorStore`:

- **Trigger paths:** any path under `{agent_root}/memory/`
- **Methods that trigger indexing:** `write_file()`, `_cmd_echo()` (when writing to file)
- **`_index_file(path)`** reads the file content and calls `VectorStore.add(path, content)`
- **Retrieval:** `semgrep "query"` uses BM25 ranking over all indexed files (top 10 results, max 60 files scanned)

This means any notes, learnings, or context the LLM writes to `/memory/` become immediately searchable via natural language.

---

## Python3 Execution Security

**Untrusted multi-tenant guard (first gate):** when `AGENTOS_UNTRUSTED_EXECUTION_GUARD=true`,
`SafeKernel.__init__` forces `python3_enabled = False` regardless of `AGENT_PYTHON3_ENABLED`.
`python3` then falls through to `BLOCKED_COMMANDS` and returns `Error [COMMAND_BLOCKED]`. This
closes the most direct tenant-reachable arbitrary-code path in shared/SaaS deployments; the
pure-Python command surface (`ls`/`cat`/`grep`/…) is unaffected. The AST layers below apply
only when python3 execution is enabled (trusted single-tenant deployments).

`_cmd_python3` applies multiple security layers before running any Python code:

**Layer 1 — AST scanning:**
Parses code into an AST and blocks:
- Imports: `subprocess`, `multiprocessing`, `socket`, `socketserver`, `ctypes`, `cffi`, `pty`, `tty`, `http`, `urllib`, `httpx`, `requests`, `aiohttp`, `httplib2`
- Calls: `os.system`, `os.popen`, `os.execv`, `os.execve`, `os.execvp`, `os.fork`, `os.spawn`, `os.spawnl`, `__import__`
- Builtins: `exec`, `eval`, `compile` — prevents dynamic code generation that could bypass import restrictions (e.g., `exec("import socket")`)

When external SQL governance is enabled, the AST pass also inspects `sqlite3.connect(...)` calls with literal database paths and checks `external:db.<name>` entitlements before execution. This prevents bypassing `run_sql_query` by querying tenant SQLite databases through Python.

Before AST scanning, `_parse_python3_args()` normalizes supported invocation forms into code:
- `python3 -c "<code>"`
- `python3 - << 'EOF' ... EOF`
- `python3 << 'EOF' ... EOF`
- `python3 /virtual/script.py`

**Layer 2 — Virtual path rewriting:**
Regex replaces virtual paths (`/me/`, `/shared/`, `/users/`) with real filesystem paths before execution.

**Layer 3 — Clean environment:**
Builds a minimal `PATH`, `PYTHONPATH`, `HOME`, and `LANG` environment, enables
`PYTHONNOUSERSITE` and `PYTHONDWRITEBYTECODE`, and does not pass
`CREDENTIAL_MASTER_KEY` or the parent process environment.

**Layer 4 — Resource limits (Unix):**
Prepends an isolated Python bootstrap that applies `resource.setrlimit()` for
CPU time and address space before executing requested code.

**Layer 5 — Sandbox user:**
When `AGENT_PYTHON3_SANDBOX_USER` is set, runs isolated Python as a separate OS
user via `sudo -n -u {user} -- python -I`. Strict enterprise mode rejects a
Python-enabled kernel if this user is not configured.

**Gating:**
- Requires `AGENT_PYTHON3_ENABLED=true`
- Timeout: `AGENT_PYTHON3_TIMEOUT` env var (default 30s)
- Warns on startup if enabled without a sandbox user outside strict mode
- Raises at construction when enabled without a sandbox user and
  `ENTERPRISE_STRICT_MODE=true`

---

## RBAC System

### Roles

| Role | Access |
|---|---|
| `USER` | Own folder only: `/users/{user_id}/` |
| `MANAGER` | Own + all team members' folders |
| `ADMIN` | All folders in tenant |
| `AUDITOR` | All folders, read-only |

### Access Check

`_check_user_access(virtual_path)`:
1. Parses `user_id` from `/users/{id}/...` path components
2. For `MANAGER`/`ADMIN`: checks if target user is in `managed_users` list
3. For `AUDITOR`: allows reads, blocks writes
4. Raises `AccessDeniedError` on violation

### Team Resolution (Three Modes)

```python
class TeamResolver:
    mode: str  # "static" | "file" | "callback"
```

| Mode | Source | Cache |
|---|---|---|
| `static` | `managed_users` list passed at init | N/A |
| `file` | `teams.json` in tenant config | 5-minute TTL |
| `callback` | `resolver_callback(user_id, team_id) → List[str]` | Per-call |

---

## Error Types

| Error | When raised |
|---|---|
| `SecurityError` | Dangerous operator, `..` path traversal, blocked command, or (when using `SafePath.resolve()`) resolved path outside sandbox |
| `AccessDeniedError` | RBAC check failed |
| `RateLimitExceeded` | Sliding window exceeded |
| `PermissionError` | Write to readonly path |
| `FileNotFoundError` | `cat`/`head`/`tail` on missing file |

All errors return a descriptive string to the LLM — they do not crash the agent loop.

---

## `write_file()` Direct Method

A bypass method for file writing that skips shell parsing:

```python
kernel.write_file(
    path: str,          # Virtual path (e.g., "/memory/notes.md")
    content: str,       # File content
    append: bool = False
) → str
```

- Resolves virtual path to real path via `_resolve_path()` (see `safe_path_design.md` for symlink/containment caveats)
- Permission-checks before writing
- Auto-indexes if path is under `/memory/`
- Returns status string

Used when the LLM needs to write structured content without shell escaping concerns.

---

## File Read Cache (optional, `AGENTOS_KERNEL_FILE_CACHE`)

An opt-in, per-kernel, in-process read-through cache for **whole-file** reads. It exists to cut
repeat reads of hot files (agent profiles, context `.md`, policies) when `enterprise_root` lives on
a higher-latency **shared/network filesystem** (EFS / Azure Files / NFS) in a multi-instance
deployment. It is **off by default** — when disabled the read path is byte-identical to before.

- **Enable:** `AGENTOS_KERNEL_FILE_CACHE` set to `1`/`true`/`on`/`yes` (read once in `__init__`).
- **State:** `self._file_cache: {(real_path, encoding, errors) -> (mtime, content)}`, guarded by a
  `threading.Lock`. Bounded: `_FILE_CACHE_MAX_ENTRIES = 512` (dict cleared wholesale when exceeded),
  `_FILE_CACHE_MAX_BYTES = 1_000_000` (files larger than 1 MB are read but never cached).
- **`_read_text_cached(resolved, encoding, errors)`** — the single read helper the cached commands
  call. If the flag is off (or `stat()` fails) it falls back to a plain `resolved.read_text(...)`.
  Otherwise it compares the current `st_mtime` against the cached entry: **hit only when mtime is
  unchanged**, so an external writer bumping the file always forces a fresh read — the cache can
  never serve stale content.
- **`_invalidate_file_cache(resolved)`** — pops every cache key for that real path.
- **Readers routed through the cache:** `_cmd_cat`, `_cmd_grep`, `_cmd_wc`, `_cmd_semgrep`.
  **Deliberately NOT cached:** `_cmd_ls`, `_cmd_find` (directory listings, not file bodies) and
  `_cmd_head`/`_cmd_tail` (partial reads). The natural-command surface (`ls`/`grep`/`cat`/…) is
  otherwise unchanged — same handlers, same `_resolve_path()`, same output.
- **Invalidation on write:** `write_file()`, `_cmd_echo()` (file target), and the `semgrep` autofix
  `write_text` path all call `_invalidate_file_cache()` after writing, so a subsequent read reflects
  the new bytes even within the same mtime granularity.

> The cache is scoped to a single `SafeKernel` instance (one process). It is a latency optimization,
> not a coherence layer: cross-instance freshness still relies on `mtime`, which is why the entry is
> mtime-validated on every hit rather than TTL'd.
