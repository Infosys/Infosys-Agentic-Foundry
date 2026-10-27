"""
Tool Factory Module

Extracted from agent.py to improve modularity.
Creates LangChain @tool functions for the SkillAgent.

Usage:
    from .tool_factory import create_shell_tool, create_sql_tool, create_write_file_tool
    
    shell = create_shell_tool(kernel, auto_run=True)
    sql = create_sql_tool(kernel, sql_write_allowed=False)
    write = create_write_file_tool(kernel)
"""

import json
import logging
import os
import re
import sqlite3
try:
    from .sqlite_util import connect as _sqlite_connect
except ImportError:
    from sqlite_util import connect as _sqlite_connect
from typing import Optional, Callable, Any, Dict, List

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Maximum nesting depth for invoke_skill / invoke_plan to prevent infinite recursion.
# Depth 0 = top-level agent, depth 1 = child, depth 2 = grandchild (blocked).
MAX_INVOKE_DEPTH = 2

# Maximum number of steps allowed in a single invoke_plan call.
MAX_PLAN_STEPS = 10

MAX_RESULT_CHARS = 8000



def create_shell_tool(kernel, auto_run: bool = True):
    """
    Create the shell tool for filesystem operations.
    
    Args:
        kernel: SafeKernel instance for command execution
        auto_run: If True, execute without confirmation. If False, return pending approval.
    
    Returns:
        LangChain @tool function
    """
    @tool
    def shell(command: str, confirmed: bool = True) -> str:
        """Execute a shell command in the secure filesystem.
        
        Args:
            command: Shell command to execute (ls, cat, grep, echo, mkdir, rm, find, head, tail)
            confirmed: Reserved for future use. Always defaults to True for agent operations.
        
        Paths: /me/ (user folder), /workspace/ (agent workspace), /shared/ (shared data), /memory/ (agent memory - READ ONLY), /local/ (user's local desktop folder - read/write if configured)
        
        Supported commands:
        - Read: ls, cat, grep, find, head, tail
        - Write: echo "text" > file, echo "text" >> file, mkdir -p, rm
        
        CRITICAL SHELL RESTRICTIONS (violations will ALWAYS fail):
        - NEVER use || && ; | $() ${} or backticks in commands
        - ONE command per call. No chaining. No piping.
        - WRONG: grep "term" file || true    ← WILL FAIL
        - WRONG: ls /dir && echo "done"       ← WILL FAIL
        - WRONG: cat file | grep term          ← WILL FAIL
        - RIGHT: grep "term" file
        - RIGHT: grep -i "term" file
        - If grep finds nothing it returns "No matches found" — do NOT add || true
        
        IMPORTANT - Efficient File Writing:
        - BATCH writes: Use escaped newlines to write multiple lines in ONE command
        - Example: echo "Line 1\\nLine 2\\nLine 3" > /path/file.txt
        - Do NOT call echo many times for each line - this wastes steps!
        - Do NOT use heredoc syntax (cat << EOF) - it is not supported
        
        File Search Strategy — use the right command for each situation:
        - Know exact path:            cat '/local/folder/file.md'
        - Know folder, not filename:  grep -r -i -l 'keyword' '/local/folder/'
        - Know part of filename:      find '/local/folder' -name '*pattern*'
        - Know file extension:        find /local -name '*.mmd'
        - Know number prefix:         find '/local/folder' -name '7.1.2*'
        - Keyword grep finds nothing: try synonyms — grep -r -i -l 'alt keyword' '/local/folder/'
        - Filename grep finds nothing: grep -r -i -l 'keyword' /local/  (broaden to parent)

        ALWAYS quote paths containing spaces with single quotes — paths like
        '/local/Invoice To Pay_md/' MUST be quoted or the shell splits on spaces.

        find supports glob patterns via -name (always recursive):
          find '/local/Invoice To Pay_md' -name '*process_flow*'   ← all process flow files
          find '/local/Procure to Pay_md' -name '7.1.2*'           ← files starting with 7.1.2
          find /local -name '*.mmd'                                ← all Mermaid files
          find /local -name '*invoice*'                            ← substring match anywhere

        grep supports content search (use BEFORE cat to avoid reading wrong file):
          grep -r -i -l 'approve invoices' '/local/Invoice To Pay_md/'
          grep -r -i -l 'payment run' '/local/Invoice To Pay_md/'
          grep -n -i 'three-way match' '/local/folder/file.md'     ← line numbers inside file

        Example:
          shell(command="ls /me/tasks")
          shell(command="echo '# Title\\n\\n## Section 1\\nContent here' > /me/notes.md")
          shell(command="cat /shared/policies/rules.md")
          shell(command="ls /memory/history/")
          shell(command="grep 'keyword' /memory/history/2026-01-26/file.jsonl")
          shell(command="find '/local/Invoice To Pay_md' -name '*process_flow*'")
          shell(command="find '/local/Procure to Pay_md' -name '7.1.2*'")
          shell(command="grep -r -i -l 'approve invoices' '/local/Invoice To Pay_md/'")
        """
        # === P0 EXPLAINABILITY: Classify and log the operation ===
        # Use quote-aware tokenization so paths with spaces log correctly
        def _tokenize_for_log(cmd: str) -> list:
            tokens, cur, in_q, qc = [], "", False, None
            for ch in cmd:
                if ch in ('"', "'") and not in_q:
                    in_q, qc = True, ch
                elif ch == qc and in_q:
                    in_q, qc = False, None
                elif ch == " " and not in_q:
                    if cur: tokens.append(cur); cur = ""
                else:
                    cur += ch
            if cur: tokens.append(cur)
            return tokens

        cmd_parts = _tokenize_for_log(command.strip())
        cmd_name = cmd_parts[0] if cmd_parts else ""

        # Extract file path from command
        file_path = None
        if len(cmd_parts) > 1:
            # For cat, head, tail, ls - path is usually the last arg
            if cmd_name in ['cat', 'head', 'tail', 'ls']:
                file_path = cmd_parts[-1]
            # For grep - path is after pattern (last non-flag token)
            elif cmd_name == 'grep' and len(cmd_parts) > 2:
                file_path = cmd_parts[-1]
            # For echo with redirection - extract target path
            elif cmd_name == 'echo' and ('>' in command or '>>' in command):
                match = re.search(r'>+\s*(\S+)', command)
                if match:
                    file_path = match.group(1)
            # For mkdir, rm - path is the argument
            elif cmd_name in ['mkdir', 'rm']:
                file_path = cmd_parts[-1].replace('-p', '').replace('-rf', '').strip()
        
        # Determine operation type and icon
        if cmd_name == 'cat':
            op_type = "📖 Reading"
        elif cmd_name in ['head', 'tail']:
            op_type = f"📖 Reading ({cmd_name})"
        elif cmd_name == 'ls':
            op_type = "📂 Listing"
        elif cmd_name == 'grep':
            op_type = "🔍 Searching"
        elif cmd_name == 'find':
            op_type = "🔍 Finding"
        elif cmd_name == 'echo' and '>' in command:
            op_type = "✏️ Writing"
        elif cmd_name == 'mkdir':
            op_type = "📁 Creating directory"
        elif cmd_name == 'rm':
            op_type = "🗑️ Deleting"
        else:
            op_type = "⚡ Executing"
        
        # Check if this is a memory access
        is_memory_access = False
        if file_path:
            if 'MEMORY.md' in file_path or 'memory_details' in file_path:
                is_memory_access = True
                memory_action = "recall" if cmd_name in ['cat', 'head', 'tail', 'grep'] else "update"
                logger.info("Memory %s: %s", memory_action, file_path)
        
        # Log the operation with file path
        if file_path and not is_memory_access:
            logger.info("%s: %s", op_type, file_path)
        elif not is_memory_access:
            cmd_preview = command[:200] + "..." if len(command) > 200 else command
            logger.info("%s: %s", op_type, cmd_preview)
        
        # Execute the command (respect auto_run setting from UI toggle)
        # auto_run=True means skip confirmation, auto_run=False means ask first
        result = kernel.run_shell_command(command, confirmed=auto_run)
        
        # Check if kernel requires confirmation (ask-first mode)
        if "⚠️ CONFIRMATION REQUIRED" in result:
            logger.info("Confirmation required for: %s", op_type)
            op_match = re.search(r'Operation: (\w+)', result)
            target_match = re.search(r'Target: (.+?)\n', result)
            operation = op_match.group(1) if op_match else cmd_name
            target = target_match.group(1) if target_match else (file_path or "unknown")
            
            # Return structured pending approval response
            return f"__PENDING_APPROVAL__|{operation}|{target}|{command}"
        
        # Log result status with context
        # Only flag as error on actual shell failure patterns — not on content containing the word "error"
        _shell_error_patterns = (
            "No such file or directory",
            "Permission denied",
            "command not found",
            "cannot access",
            "Traceback (most recent call last)",
            "SyntaxError",
            "ModuleNotFoundError",
            "ImportError",
            "FileNotFoundError",
        )
        _is_shell_error = any(p in result for p in _shell_error_patterns)
        if _is_shell_error:
            logger.error("Failed: %s", result[:80])
        else:
            lines = result.count('\n') + 1 if result else 0
            size_hint = f"{len(result)} chars" if len(result) < 1000 else f"{len(result)//1024}KB"
            
            if cmd_name in ['cat', 'head', 'tail']:
                logger.info("Read %d lines (%s)", lines, size_hint)
            elif cmd_name == 'ls':
                items = len([l for l in result.split('\n') if l.strip()])
                logger.info("Found %d items", items)
            elif cmd_name in ['grep', 'find']:
                matches = len([l for l in result.split('\n') if l.strip()])
                logger.info("Found %d matches", matches)
            elif cmd_name == 'echo' and '>' in command:
                logger.info("File written")
            elif cmd_name == 'mkdir':
                logger.info("Directory created")
            elif cmd_name == 'rm':
                logger.info("Deleted")
            else:
                logger.info("Done (%d lines)", lines)

        # Tool result budget: persist large results to workspace/tmp so the
        # LLM context window isn't flooded. The agent can grep/head the file.
        _MAX_SHELL_RESULT = 10_000
        if len(result) > _MAX_SHELL_RESULT:
            import uuid as _uuid
            from pathlib import Path as _Path
            _tmp_dir = _Path(kernel.agent_root) / "workspace" / "tmp"
            _tmp_dir.mkdir(parents=True, exist_ok=True)
            _fname = f"iaf_result_{_uuid.uuid4().hex[:8]}.txt"
            (_tmp_dir / _fname).write_text(result, encoding="utf-8")
            _vpath = f"/workspace/tmp/{_fname}"
            logger.warning(
                "Shell result too large (%d chars) — saved to %s", len(result), _vpath
            )
            return (
                f"[Result truncated: {len(result)} chars total — full output saved to {_vpath}]\n"
                f"Preview (first 500 chars):\n{result[:500]}\n...\n\n"
                f"To get specific sections use:\n"
                f"  shell(command=\"head -n 50 '{_vpath}'\")\n"
                f"  shell(command=\"grep 'keyword' '{_vpath}'\")\n"
                f"  shell(command=\"tail -n 30 '{_vpath}'\")"
            )

        return result

    return shell



def _format_pg_result(columns: List[str], rows: list) -> str:
    """Format Postgres rows the same shape as the SQLite path (header + 50-row cap)."""
    if not rows:
        return "Query returned no results."
    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows[:50]:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    if len(rows) > 50:
        lines.append(f"... and {len(rows) - 50} more rows")
    lines.append(f"\n({len(rows)} total rows)")
    return "\n".join(lines)


def _run_pg_query(indexer, resource, query: str, is_select: bool, db_name: str) -> str:
    """Execute a query for a Postgres-backed db resource, scoped and guarded.

    - Connects through the KnowledgeIndexer seam (``search_path`` already set to the
      agent's ``kn_`` schema); override only if the resource names a different schema.
    - ``SET LOCAL statement_timeout`` on every query (runaway guard).
    - ``read_only`` resources drop to a least-privilege role via ``SET LOCAL ROLE`` so
      table isolation is enforced by Postgres privileges, not by regex — the real boundary.
    - SELECT → formatted rows; INSERT/UPDATE/DELETE → commit + rowcount.
    """
    if indexer is None or getattr(indexer, "backend", "sqlite") != "postgres":
        return (f"Error: '{db_name}' is a Postgres resource but no Postgres knowledge "
                f"engine is available in this context.")
    timeout_ms = os.getenv("AGENTOS_SQL_STATEMENT_TIMEOUT_MS", "5000")
    try:
        timeout_ms = str(int(timeout_ms))
    except Exception:
        timeout_ms = "5000"
    ro_role = None
    if resource is not None and getattr(resource, "read_only", False):
        ro_role = (
            (resource.metadata.get("role") if getattr(resource, "metadata", None) else None)
            or os.getenv("AGENTOS_SQL_RO_ROLE", "agentos_graph_ro")
        )
    schema = (getattr(resource, "schema", "") or "").strip()
    try:
        with indexer.connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SET LOCAL statement_timeout = '{timeout_ms}ms'")
            if schema and schema.lower() != "self":
                safe_schema = re.sub(r"[^a-zA-Z0-9_]", "_", schema).lower()[:63]
                cur.execute(f'SET LOCAL search_path TO "{safe_schema}"')
            if ro_role:
                safe_role = re.sub(r"[^a-zA-Z0-9_]", "_", ro_role)[:63]
                try:
                    cur.execute(f'SET LOCAL ROLE "{safe_role}"')
                except Exception as _rex:
                    return (f"Error: read-only role '{ro_role}' is unavailable ({_rex}); "
                            f"refusing to run the query unscoped.")
            cur.execute(query)
            if is_select:
                rows = cur.fetchall()
                cols = [d.name for d in cur.description] if cur.description else []
                return _format_pg_result(cols, rows)
            conn.commit()
            verb = query.strip().split()[0].upper() if query.strip() else "WRITE"
            return f"Success: {verb} affected {cur.rowcount} row(s)."
    except Exception as e:
        return f"SQL Error (postgres): {e}"


def create_sql_tool(kernel, sql_write_allowed: bool = False, indexer=None, connections=None):
    """
    Create the SQL query tool for database operations (backend-aware gateway).

    Args:
        kernel: SafeKernel instance for path resolution + entitlement.
        sql_write_allowed: If True, allow INSERT/UPDATE/DELETE. If False, SELECT only.
        indexer: Optional KnowledgeIndexer, required to reach Postgres-backed db
                 resources (provides the pooled engine + the agent's schema via
                 ``indexer.connect()``). SQLite/file resources work without it.
        connections: The skill's data connections (list of {type,name,config}) from
                 SKILL.md frontmatter — routes non-SQLite engines (sqlserver/postgres/
                 mysql/oracle) via the matching driver, secrets from the credential store.

    Returns:
        LangChain @tool function
    """
    # name → connection dict, from the skill's data connections (Connections UI)
    _conn_map = {}
    for _c in (connections or []):
        if isinstance(_c, dict) and _c.get("name"):
            _conn_map[str(_c["name"])] = _c

    @tool
    def run_sql_query(database: str, query: str) -> str:
        """Execute a SQL query against a configured database.

        `database` is EITHER a named data connection defined in the skill's
        Connections (SQLite / SQL Server / PostgreSQL) OR a virtual path to a
        local SQLite file (e.g. "/shared/databases/invoices_us.db"). The tool
        routes to the right engine automatically. SELECT-only unless the skill
        sets sql_mode: read_write (SQLite path only).

        Args:
            database: A connection name (e.g. "ViewitSQL") or a SQLite file path.
            query: SQL query to execute (SELECT for safety).

        Returns:
            Query results as formatted text, or an error message.

        Example:
            run_sql_query(database="ViewitSQL",
                          query="SELECT TOP 20 * FROM dbo.FailedJobs")
        """
        _conn = _conn_map.get(database)
        _external_engine: Optional[str] = None
        _external_cfg: dict = {}
        if _conn:
            _external_cfg = _conn.get("config", {}) or {}
            _engine = str(_external_cfg.get("engine") or "sqlite").strip().lower()
            if _engine in ("sqlserver", "mssql", "sql server"):
                _external_engine = "sqlserver"
            elif _engine in ("postgres", "postgresql", "pg"):
                _external_engine = "postgres"
            elif _engine in ("mysql", "mariadb"):
                _external_engine = "mysql"
            elif _engine in ("oracle", "oracledb"):
                _external_engine = "oracle"
            elif _engine and _engine not in ("sqlite", "sqlite3"):
                return (f"Error: database engine '{_engine}' is not supported yet "
                        "(available: sqlite, sqlserver, postgres, mysql, oracle).")
            else:
                # sqlite connection → use its configured path, then fall through
                _sqlite_path = (_external_cfg.get("path")
                                or _external_cfg.get("host")
                                or _external_cfg.get("database"))
                if _sqlite_path:
                    database = str(_sqlite_path)

        db_name = database.split('/')[-1] if '/' in database else database
        
        query_upper = query.strip().upper()
        tables = []
        # Simple table extraction from SELECT ... FROM table
        from_match = re.search(r'FROM\s+(\w+)', query_upper)
        if from_match:
            tables.append(from_match.group(1).lower())
        join_matches = re.findall(r'JOIN\s+(\w+)', query_upper)
        tables.extend([t.lower() for t in join_matches])
        
        table_info = f" → tables: {', '.join(tables)}" if tables else ""
        logger.info("Querying: %s%s", db_name, table_info)
        
        query_preview = query[:60].replace('\n', ' ') + "..." if len(query) > 60 else query.replace('\n', ' ')
        logger.debug("SQL: %s", query_preview)
        
        # ── Resolve the db resource + backend (SQLite file path OR named PG resource) ──
        resource = None
        try:
            if hasattr(kernel, "tenant_root"):
                from agent_os.external_access import resource_for_database
                resource = resource_for_database(kernel.tenant_root, database)
        except Exception as _rex:
            logger.debug("resource_for_database failed for %s: %s", database, _rex)
            resource = None
        backend = ((getattr(resource, "backend", "") or "") if resource else "").lower()

        # ── Classify the query (both backends). WITH ... = recursive-CTE read. ──
        _has_write_kw = bool(re.search(r'\b(INSERT|UPDATE|DELETE)\b', query_upper))
        is_select = (query_upper.startswith("SELECT") or query_upper.startswith("WITH")) and not _has_write_kw
        is_safe_write = query_upper.startswith(("INSERT", "UPDATE", "DELETE"))
        is_dangerous_ddl = query_upper.startswith(("DROP", "ALTER", "CREATE", "TRUNCATE", "VACUUM"))

        # ── Write gating: DDL never; read-only resources never; else per sql_mode ──
        if not is_select:
            if is_dangerous_ddl:
                logger.error("DDL blocked: %s", query_upper.split()[0])
                return "Error: DDL operations (DROP, ALTER, CREATE, TRUNCATE) are never allowed."
            if resource is not None and getattr(resource, "read_only", False):
                logger.warning("Write blocked: '%s' is a read-only resource", db_name)
                return f"Error: '{database}' is a read-only resource; writes are not permitted."
            if not is_safe_write or not sql_write_allowed:
                logger.error("Write blocked (sql_mode: read_only)")
                return "Error: Only SELECT queries allowed. Set sql_mode: read_write in SKILL.md to enable writes."
            logger.info("SQL write (%s): allowed by sql_mode", query_upper.split()[0])

        allowed_tables = set(t.lower() for t in (getattr(resource, "allowed_tables", ()) or ()))
        _role_enforced = bool(resource is not None and getattr(resource, "read_only", False))
        if allowed_tables and not _role_enforced:
            extra = set(tables) - allowed_tables
            if extra:
                logger.warning("Query on '%s' references disallowed table(s): %s", db_name, extra)
                return (f"Error: query references table(s) not permitted for '{database}': "
                        f"{sorted(extra)}. Allowed: {sorted(allowed_tables)}.")

        # ── Entitlement (per resource + operation) ──
        operation = "read" if is_select else ("delete" if query_upper.startswith("DELETE") else "write")
        if hasattr(kernel, "database_allowed"):
            allowed, reason = kernel.database_allowed(database, operation)
            if not allowed:
                logger.warning("SQL entitlement denied for %s: %s", db_name, reason)
                return f"Error: {reason}"

        if _external_engine is not None:
            return _run_external_sql(kernel, _external_engine, database, _external_cfg, query)

        # ── Route to Postgres for named PG resources (no filesystem path) ──
        if backend == "postgres":
            return _run_pg_query(indexer, resource, query, is_select, db_name)

        # ── SQLite / file path (unchanged behaviour below) ──
        try:
            real_path = kernel._resolve_path(database)
        except Exception as e:
            logger.error("Invalid database path")
            return f"Error: Invalid database path '{database}' - {str(e)}"

        if not real_path.exists():
            logger.error("Database not found")
            return f"Error: Database not found at '{database}'. Use 'cat /shared/databases/_index.md' to see available databases."
        
        try:
            conn = _sqlite_connect(real_path, row_factory=sqlite3.Row)
            # Enforce read-only at SQLite level for SELECT queries
            if is_select:
                conn.execute("PRAGMA query_only = ON")
            # Block statement stacking
            if ";" in query.rstrip().rstrip(";"):
                conn.close()
                return "Error: Multi-statement queries are not allowed."
            cursor = conn.cursor()
            _BLOCKED_DDL_RE = re.compile(r'\b(DROP|ALTER|CREATE|TRUNCATE|VACUUM)\b', re.IGNORECASE)
            if _BLOCKED_DDL_RE.search(query):
                conn.close()
                return "Error: DDL operations are not allowed."
            cursor.execute(query)
            
            # For write operations, commit and return affected rows
            if not is_select:
                conn.commit()
                affected = cursor.rowcount
                conn.close()
                logger.info("SQL %s: %d row(s) affected", query_upper.split()[0], affected)
                return f"Success: {query_upper.split()[0]} affected {affected} row(s)."
            
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                logger.info("Query returned 0 rows")
                return "Query returned no results."
            
            # Enhanced result logging
            columns = rows[0].keys()
            logger.info("Result: %d rows x %d columns", len(rows), len(columns))
            
            # Format results as table
            columns = rows[0].keys()
            result_lines = []
            
            # Header
            result_lines.append(" | ".join(columns))
            result_lines.append("-" * len(result_lines[0]))
            
            # Data rows (limit to 50 for readability)
            for row in rows[:50]:
                result_lines.append(" | ".join(str(row[col]) for col in columns))
            
            if len(rows) > 50:
                result_lines.append(f"... and {len(rows) - 50} more rows")
            
            result_lines.append(f"\n({len(rows)} total rows)")

            output = "\n".join(result_lines)

            # Tool result budget: persist large SQL results to workspace/tmp
            _MAX_SQL_RESULT = 10_000
            if len(output) > _MAX_SQL_RESULT:
                import uuid as _uuid
                from pathlib import Path as _Path
                _tmp_dir = _Path(kernel.agent_root) / "workspace" / "tmp"
                _tmp_dir.mkdir(parents=True, exist_ok=True)
                _fname = f"iaf_sql_{_uuid.uuid4().hex[:8]}.txt"
                (_tmp_dir / _fname).write_text(output, encoding="utf-8")
                _vpath = f"/workspace/tmp/{_fname}"
                logger.warning(
                    "SQL result too large (%d chars) — saved to %s", len(output), _vpath
                )
                return (
                    f"[SQL result truncated: {len(output)} chars total — full output saved to {_vpath}]\n"
                    f"Preview (first 500 chars):\n{output[:500]}\n...\n\n"
                    f"To narrow results add WHERE/LIMIT clauses, or:\n"
                    f"  shell(command=\"grep 'keyword' '{_vpath}'\")\n"
                    f"  shell(command=\"head -n 100 '{_vpath}'\")"
                )

            return output
            
        except sqlite3.Error as e:
            return f"SQL Error: {str(e)}"
        except Exception as e:
            return f"Error executing query: {str(e)}"

    return run_sql_query


def _expand_conn_refs(kernel, cfg: dict) -> dict:
    """Expand ``${VAULT:...}`` / ``${CRED:...}`` / ``${VAR}`` placeholders in a data
    connection config, so a skill can reference a scoped Vault secret (or stored
    credential) directly in the connection fields (host/username/password/etc.).
    Scope is enforced against the running skill. Returns cfg unchanged if no
    credential store is available."""
    if not isinstance(cfg, dict):
        return cfg
    try:
        provider = kernel._get_secret_provider()
        store = getattr(provider, "store", None)
    except Exception:
        store = None
    if store is None:
        return cfg
    try:
        from agent_os.secret_refs import expand_secret_refs_in_obj, iter_ref_targets
        consumer = getattr(kernel, "current_skill", None) or kernel.agent_id
        checker = getattr(kernel, "_credential_allowed", None)
        if callable(checker):
            for cred_name in {name for _kind, name in iter_ref_targets(cfg)}:
                try:
                    allowed, _reason = checker(cred_name)
                except Exception as ge:
                    logger.warning("Credential gate check failed for '%s': %s", cred_name, ge)
                    allowed = False
                if not allowed:
                    logger.warning(
                        "Secret ref '%s' denied by external-access policy; leaving "
                        "connection refs unexpanded", cred_name,
                    )
                    return cfg  # leave placeholders → connect fails, surfacing the denial
        return expand_secret_refs_in_obj(cfg, store, consumer, purpose="data_connection")
    except Exception as e:  # never let ref-expansion break a connection outright
        logger.warning("Data connection ref expansion failed: %s", e)
        return cfg


def _resolve_conn_password(kernel, cfg: dict):
    """Resolve a data connection's password. Prefers a credential-store reference
    (cfg['credential'] / ['credential_ref']) so the secret never sits in the skill
    file; falls back to an inline cfg['password'] if present.

    Returns (password, source_label)."""
    cred_name = cfg.get("credential") or cfg.get("credential_ref")
    if cred_name:
        _checker = getattr(kernel, "_credential_allowed", None)
        if callable(_checker):
            try:
                _allowed, _gate_reason = _checker(cred_name)
            except Exception as _gate_err:
                logger.warning("Credential gate check failed for '%s': %s", cred_name, _gate_err)
                _allowed = False
            if not _allowed:
                logger.warning("Credential '%s' denied by external-access policy (run_sql_query)", cred_name)
                return None, "denied"
        try:
            provider = kernel._get_secret_provider()
            cred = provider.resolve(
                cred_name,
                consumer=getattr(kernel, "current_skill", None) or kernel.agent_id,
                accessor=getattr(kernel, "user_id", None) or kernel.agent_id,
                purpose="run_sql_query",
            )
            if cred and getattr(cred, "value", None):
                v = cred.value
                pwd = v.get("password") or v.get("PWD") or v.get("pwd") or v.get("secret")
                if pwd:
                    return pwd, f"credential:{cred_name}"
        except Exception as e:
            logger.warning("Credential '%s' resolve failed: %s", cred_name, e)
    return cfg.get("password"), ("inline" if cfg.get("password") else "none")


def _format_sql_rows(kernel, columns, rows, engine_label: str) -> str:
    """Shared row→table formatter + large-result overflow (mirrors the SQLite tool).
    `rows` is a list of sequences aligned to `columns`."""
    if not rows:
        return "Query returned no results."
    logger.info("%s result: %d rows x %d columns", engine_label, len(rows), len(columns))
    lines = [" | ".join(str(c) for c in columns)]
    lines.append("-" * len(lines[0]))
    for row in rows[:50]:
        lines.append(" | ".join(str(v) for v in row))
    if len(rows) > 50:
        lines.append(f"... and {len(rows) - 50} more rows")
    lines.append(f"\n({len(rows)} total rows)")
    output = "\n".join(lines)

    _MAX_SQL_RESULT = 10_000
    if len(output) > _MAX_SQL_RESULT:
        import uuid as _uuid
        from pathlib import Path as _Path
        _tmp_dir = _Path(kernel.agent_root) / "workspace" / "tmp"
        _tmp_dir.mkdir(parents=True, exist_ok=True)
        _fname = f"iaf_sql_{_uuid.uuid4().hex[:8]}.txt"
        (_tmp_dir / _fname).write_text(output, encoding="utf-8")
        _vpath = f"/workspace/tmp/{_fname}"
        logger.warning("SQL result too large (%d chars) — saved to %s", len(output), _vpath)
        return (
            f"[SQL result truncated: {len(output)} chars total — full output saved to {_vpath}]\n"
            f"Preview (first 500 chars):\n{output[:500]}\n...\n\n"
            f"To narrow results add WHERE/TOP clauses, or:\n"
            f"  shell(command=\"head -n 100 '{_vpath}'\")"
        )
    return output


def _run_external_sql(kernel, engine: str, conn_name: str, cfg: dict, query: str) -> str:
    """Execute a READ-ONLY query against a remote SQL engine (sqlserver/postgres)
    described by a skill data connection. Host/port/database/username come from the
    connection config; the password is resolved from the credential store (preferred)
    or an inline field. SELECT/WITH only — writes/DDL/EXEC are blocked."""
    # Expand ${VAULT:...}/${CRED:...}/${VAR} refs in the connection fields first,
    # so a skill can point host/username/password at a scoped Vault secret.
    cfg = _expand_conn_refs(kernel, cfg)
    host = cfg.get("host") or cfg.get("server")
    user = cfg.get("username") or cfg.get("user")
    db = str(cfg.get("database") or "").strip()
    default_port = {"sqlserver": 1433, "postgres": 5432, "mysql": 3306, "oracle": 1521}.get(engine, 1433)
    try:
        port = int(str(cfg.get("port") or default_port).strip() or default_port)
    except (TypeError, ValueError):
        port = default_port
    pwd, pwd_src = _resolve_conn_password(kernel, cfg)

    missing = [k for k, v in (("host", host), ("username", user), ("password", pwd)) if not v]
    if missing:
        return (f"Error: connection '{conn_name}' is missing {', '.join(missing)}. "
                "Store the password in the credential store and set the connection's "
                "`credential` to its name (host/port/database/username live on the connection).")

    # ── Read-only safety ──
    q = query.strip().rstrip(";").strip()
    qu = q.upper()
    if not (qu.startswith("SELECT") or qu.startswith("WITH")):
        return "Error: only read-only SELECT queries are allowed."
    if re.search(r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|EXEC|EXECUTE|GRANT|REVOKE|BACKUP|RESTORE)\b', q, re.IGNORECASE):
        return "Error: write / DDL / EXEC statements are not allowed (read-only)."
    if ";" in q:
        return "Error: multi-statement queries are not allowed."

    logger.info("SQL[%s] conn=%s host=%s:%s db=%s pwd=%s",
                engine, conn_name, host, port, db or "(default)", pwd_src)

    def _cols_rows_from_cursor(cur):
        """DB-API cursor → (columns, rows-as-tuples) after execute."""
        _rows = cur.fetchall()
        _cols = [d[0] for d in cur.description] if cur.description else []
        return _cols, _rows

    try:
        if engine == "sqlserver":
            try:
                import pymssql
            except ImportError:
                return "Error: SQL Server driver not installed. Run: pip install pymssql"
            conn = pymssql.connect(server=host, port=str(port), user=user, password=pwd,
                                   database=(db or None), login_timeout=15, timeout=30)
            try:
                cur = conn.cursor(as_dict=True)
                cur.execute(q)
                dict_rows = cur.fetchall()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            if not dict_rows:
                return "Query returned no results."
            columns = list(dict_rows[0].keys())
            rows = [[r.get(c) for c in columns] for r in dict_rows]

        elif engine == "postgres":
            try:
                import psycopg
            except ImportError:
                return "Error: PostgreSQL driver not installed. Run: pip install 'psycopg[binary]'"
            conn = psycopg.connect(host=host, port=port, dbname=(db or None),
                                   user=user, password=pwd, connect_timeout=15)
            try:
                cur = conn.cursor()
                cur.execute(q)
                columns, rows = _cols_rows_from_cursor(cur)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        elif engine == "mysql":
            try:
                import pymysql
            except ImportError:
                return "Error: MySQL driver not installed. Run: pip install pymysql"
            conn = pymysql.connect(host=host, port=port, user=user, password=pwd,
                                   database=(db or None), connect_timeout=15, read_timeout=30)
            try:
                cur = conn.cursor()
                cur.execute(q)
                columns, rows = _cols_rows_from_cursor(cur)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        elif engine == "oracle":
            try:
                import oracledb  # thin mode — no Oracle client install needed
            except ImportError:
                return "Error: Oracle driver not installed. Run: pip install oracledb"
            # Oracle: the connection's `database` field is the SERVICE NAME (or SID).
            dsn = oracledb.makedsn(host, port, service_name=db) if db else f"{host}:{port}"
            conn = oracledb.connect(user=user, password=pwd, dsn=dsn)
            try:
                cur = conn.cursor()
                cur.execute(q)
                columns, rows = _cols_rows_from_cursor(cur)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            return f"Error: engine '{engine}' is not supported."
    except Exception as e:
        return f"{engine} connection/query failed ({host}:{port}): {e}"

    return _format_sql_rows(kernel, columns, rows, engine)



def create_fetch_canonical_tool(kernel):
    """Create the fetch_canonical tool.

    Resolves a skill's declared canonical query intent (from its data_contract.yaml)
    against the tenant's ACTIVE binding, executes it read-only, and returns canonical
    rows. This is how a client-agnostic capability gets grounded data without writing
    client SQL — swap the binding, not the skill.
    """
    @tool
    def fetch_canonical(intent: str, params_json: str = "{}") -> str:
        """Fetch grounded canonical finance data for a declared query intent.

        Use the intent name from the current skill's data_contract.yaml. Examples:
        invoice_history, vendor_master, journal_history, po_match, requisition_queue,
        ar_open_items, customer_master, billing_queue, fixed_asset_register, kpi_set,
        bank_fee_postings, cashflow_series, settlement_book, counterparty_master.

        Args:
            intent: the canonical query intent name to fetch.
            params_json: optional JSON object of params, e.g. '{"lookback_months": 12}'.

        Returns:
            Canonical rows as formatted text, or an error message.
        """
        import json as _json
        import re as _re
        import sqlite3 as _sq
        import yaml as _yaml
        from pathlib import Path as _P
        try:
            params = _json.loads(params_json) if params_json else {}
            if not isinstance(params, dict):
                params = {}
        except Exception:
            params = {}
        # Active binding selector (tenant-scoped virtual path).
        try:
            cfg = _yaml.safe_load(kernel._resolve_path("/shared/config/active_binding.yaml").read_text())
        except Exception as e:
            return f"Error: no active binding config (/shared/config/active_binding.yaml): {e}"
        domains = cfg.get("domains", {}) or {}
        _defaults = {"lookback_months": 12, "lookback_days": 30, "period": None}
        for _dom, _vpath in domains.items():
            try:
                _dir = kernel._resolve_path(_vpath)
            except Exception:
                continue
            for f in sorted(_P(_dir).glob("*.yaml")):
                try:
                    pack = _yaml.safe_load(f.read_text())
                except Exception:
                    continue
                qi = (pack.get("query_intents") or {})
                if intent not in qi:
                    continue
                sql = qi[intent]
                src = pack.get("source", {}) or {}
                if (src.get("dialect") or "").lower() != "sqlite":
                    return f"Error: intent '{intent}' binding is not sqlite (got {src.get('dialect')})."
                try:
                    db_real = kernel._resolve_path(src["database"])
                except Exception as e:
                    return f"Error: cannot resolve binding database: {e}"
                if hasattr(kernel, "database_allowed"):
                    _allowed, _reason = kernel.database_allowed(src["database"], "read")
                    if not _allowed:
                        logger.warning("fetch_canonical entitlement denied for %s: %s", src["database"], _reason)
                        return f"Error: {_reason}"
                # Fill any :named params the SQL needs but the caller omitted.
                for p in set(_re.findall(r":(\w+)", sql)):
                    params.setdefault(p, _defaults.get(p))
                try:
                    con = _sq.connect(str(db_real)); con.row_factory = _sq.Row
                    con.execute("PRAGMA query_only = ON")
                    rows = [dict(r) for r in con.execute(sql, params)]
                    con.close()
                except Exception as e:
                    return f"Error executing intent '{intent}': {e}"
                if not rows:
                    return f"{intent}: no rows"
                cols = list(rows[0].keys())
                out = [" | ".join(cols), "-" * max(8, len(" | ".join(cols)))]
                for r in rows[:50]:
                    out.append(" | ".join("" if r[c] is None else str(r[c]) for c in cols))
                if len(rows) > 50:
                    out.append(f"... and {len(rows) - 50} more rows")
                out.append(f"\n({len(rows)} rows via binding '{cfg.get('active_binding')}')")
                return "\n".join(out)
        return f"Error: intent '{intent}' not found in any active binding under {list(domains)}"

    return fetch_canonical



def create_write_file_tool(kernel):
    """
    Create the write_file tool for direct file writing (no shell escaping).

    Confirmation/approval is handled upstream by the stream intercept layer
    in agent._run_with_stream_intercept() — this tool always executes when called.

    Args:
        kernel: SafeKernel instance for file operations

    Returns:
        LangChain @tool function
    """
    @tool
    def write_file(path: str, content: str, append: bool = False) -> str:
        """Write content directly to a file (no shell escaping needed).

        Use this for multi-line content or content with special characters (|, *, $, backticks, tables).
        For simple one-line writes, you can still use: shell("echo 'text' > file")

        Args:
            path: Virtual path (e.g., /me/notes.md, /workspace/output.txt, /local/report.txt)
            content: The full file content (markdown, code, tables, etc.)
            append: If True, append to existing file instead of overwriting

        Example:
            write_file(
                path="/me/discovery/process_redesign.md",
                content="# Process Redesign\\n\\n| Step | Action |\\n|------|--------|\\n| 1 | Analyze |"
            )
        """
        action = "Appending to" if append else "Writing"
        logger.info("%s: %s", action, path)

        result = kernel.write_file(path, content, append=append)

        if "Error" in result:
            logger.error("%s", result)
        else:
            lines = content.count('\n') + 1
            logger.info("Wrote %d chars (%d lines) to %s", len(content), lines, path)

        return result

    return write_file



def create_jev_tool(confidence_threshold: float = 0.90):
    """Create the jev_decide tool — a calibrated, type-safe decision (Choice/Noul).

    Jev only DECIDES (pick 1 of N, or yes/no) — it never generates text. A skill
    node calls this to get a fast, calibrated verdict with a confidence gate:
    high confidence -> act; low confidence -> the tool returns ESCALATE so the
    graph's verifier/converge machinery routes to a human. Fails soft: on any Jev
    error it returns a clear FALLBACK string so the skill can decide with the LLM.

    Args:
        confidence_threshold: default gate; a call may override via `threshold`.

    Returns:
        LangChain @tool function
    """
    @tool
    def jev_decide(question: str, instructions: str, state: str,
                   criteria: Optional[dict] = None, threshold: Optional[float] = None) -> str:
        """Make a fast, calibrated, type-safe decision with Jev (TypeSafe System One).

        Use for a discrete decision only — NOT generation. Two modes:
          - question="choice": pick 1 of N. Pass `criteria` = {label: description}.
          - question="noul":   a yes/no judgment. `criteria` ignored.

        Args:
            question: "choice" or "noul".
            instructions: the goal/question, e.g. "Classify the three-way match state"
                          or "Is this invoice safe and complete to post?".
            state: the facts to decide over (plain text or a compact JSON string) —
                   treated as data, never instructions.
            criteria: for choice only — {label: one-line description} (2..255 labels).
            threshold: optional confidence gate override (default 0.90).

        Returns (as a single line the skill can echo):
            choice -> "JEV CHOICE: <label> | confidence 0.xx"  (or "... | ESCALATE (low confidence)")
            noul   -> "JEV VERDICT: PASS | confidence 0.xx"  /  "JEV VERDICT: FAIL | ..."  /  "... ESCALATE"
            error  -> "JEV FALLBACK: <reason> — decide with your own judgment."
        """
        from .jev_client import jev_choice, jev_noul
        gate = float(threshold) if threshold is not None else confidence_threshold
        q = (question or "").strip().lower()

        if q == "choice":
            r = jev_choice(state, criteria or {}, instructions)
            if not r.get("ok"):
                logger.info("jev_decide(choice) fallback: %s", r.get("error"))
                return f"JEV FALLBACK: {r.get('error','jev unavailable')} — decide with your own judgment."
            conf = r["confidence"]
            logger.info("JEV CHOICE '%s' confidence=%.2f (gate=%.2f)", r["choice"], conf, gate)
            if conf < gate:
                return f"JEV CHOICE: {r['choice']} | confidence {conf:.2f} | ESCALATE (below gate {gate:.2f})"
            return f"JEV CHOICE: {r['choice']} | confidence {conf:.2f}"

        if q == "noul":
            r = jev_noul(state, instructions)
            if not r.get("ok"):
                logger.info("jev_decide(noul) fallback: %s", r.get("error"))
                return f"JEV FALLBACK: {r.get('error','jev unavailable')} — decide with your own judgment."
            conf = r["confidence"]
            logger.info("JEV VERDICT noul=%s confidence=%.2f (gate=%.2f)", r["noul"], conf, gate)
            if conf < gate:
                return f"JEV VERDICT: ESCALATE | confidence {conf:.2f} (below gate {gate:.2f}) — send to a human."
            return f"JEV VERDICT: {'PASS' if r['noul'] else 'FAIL'} | confidence {conf:.2f}"

        return "JEV FALLBACK: question must be 'choice' or 'noul' — decide with your own judgment."

    return jev_decide



# Columns whose value is a flag; rendered as yes/no instead of the raw 0/1.
_JEV_BOOLEAN_FIELDS = {
    "gr_posted", "is_duplicate", "posted", "approved", "released",
    "gr_confirmed", "on_hold", "blocked",
}
# Friendlier checklist labels for a few well-known columns (facts unchanged).
_JEV_FIELD_LABELS = {
    "gr_posted": "goods_receipt_posted",
    "gl_account": "gl_account",
    "cost_center": "cost_centre",
    "tax_code": "tax_code",
    "is_duplicate": "is_duplicate",
}


def _jev_format_checklist(row: dict, fields: list) -> str:
    """Render a DB row into the SAME checklist string every run (deterministic).

    - boolean columns  -> yes / no
    - NULL/empty        -> MISSING
    - everything else   -> the raw value
    This is the whole point of jev_verify: the evidence handed to Jev is built by
    code, not paraphrased by an LLM, so the calibrated confidence is stable.
    """
    parts = []
    for f in fields:
        label = _JEV_FIELD_LABELS.get(f, f)
        val = row.get(f)
        if val is None or (isinstance(val, str) and not val.strip()):
            parts.append(f"{label}=MISSING")
        elif f in _JEV_BOOLEAN_FIELDS:
            truthy = str(val).strip().lower() in ("1", "true", "yes", "y", "t")
            parts.append(f"{label}={'yes' if truthy else 'no'}")
        else:
            parts.append(f"{label}={val}")
    return ", ".join(parts)


def create_jev_verify_tool(kernel, confidence_threshold: float = 0.65):
    """Create the jev_verify tool — a DETERMINISTIC, calibrated readiness verdict.

    Unlike `jev_decide` (where the LLM writes the `state` it hands Jev, so the same
    case can be worded differently run-to-run and Jev's confidence wobbles), this
    tool does the fact-gathering itself:

        jev_verify(case_id) -> reads the declared columns from SQL
                            -> builds the IDENTICAL checklist string every run
                            -> asks Jev a calibrated yes/no (noul)
                            -> returns PASS / FAIL / ESCALATE

    The LLM node just calls it and echoes the verdict — it cannot paraphrase the
    evidence, so the verdict is stable for the same underlying data. Fails soft:
    on any DB/Jev error it returns a clear FALLBACK string so the skill can decide
    with its own judgment.

    Args:
        kernel: SafeKernel — resolves the (virtual) DB path and enforces entitlement.
        confidence_threshold: gate below which a "yes" becomes ESCALATE.
    """
    @tool
    def jev_verify(case_id: str,
                   database: str = "/shared/databases/fin_p2p_demo.db",
                   table: str = "ap_cases",
                   fields: str = "gr_posted,gl_account,cost_center,tax_code,is_duplicate",
                   question: str = ("Is this AP invoice safe and complete to post: goods receipt "
                                    "posted, GL account and cost centre present, tax code valid, "
                                    "and not a duplicate?"),
                   threshold: Optional[float] = None) -> str:
        """Deterministically verify a case is ready, using Jev (TypeSafe System One).

        Call this with just the case_id — the tool reads the readiness columns from
        the database itself and builds the exact same evidence checklist every time,
        so Jev's calibrated verdict is stable (no LLM paraphrasing in between).

        Args:
            case_id: the case/invoice id to verify (e.g. "INV-2026-501884").
            database: virtual DB path (default the P2P demo db).
            table: table holding the case row (default ap_cases).
            fields: comma-separated readiness columns to build the checklist from.
            question: the calibrated yes/no Jev must judge.
            threshold: optional confidence-gate override (default 0.80).

        Returns (one line the skill can echo verbatim):
            "JEV VERDICT: PASS | confidence 0.xx | checklist: <...>"
            "JEV VERDICT: FAIL | confidence 0.xx | checklist: <...>"
            "JEV VERDICT: ESCALATE | confidence 0.xx (below gate) | checklist: <...>"
            "JEV FALLBACK: <reason> — decide with your own judgment."
        """
        from .jev_client import jev_noul
        gate = float(threshold) if threshold is not None else confidence_threshold
        field_list = [f.strip() for f in (fields or "").split(",") if f.strip()]
        if not case_id or not case_id.strip():
            return "JEV FALLBACK: jev_verify needs a case_id — decide with your own judgment."
        if not field_list:
            return "JEV FALLBACK: jev_verify needs at least one readiness field — decide with your own judgment."

        # ── Entitlement (same gate the SQL tool uses) ──
        try:
            if hasattr(kernel, "database_allowed"):
                allowed, reason = kernel.database_allowed(database, "read")
                if not allowed:
                    return f"JEV FALLBACK: database not permitted ({reason}) — decide with your own judgment."
        except Exception as e:
            logger.debug("jev_verify entitlement check failed (%s) — continuing.", e)

        # ── Read the exact columns (deterministic, parameterised, read-only) ──
        safe_cols = [c for c in field_list if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c)]
        if len(safe_cols) != len(field_list):
            return "JEV FALLBACK: invalid field name in jev_verify — decide with your own judgment."
        safe_table = table if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table or "") else "ap_cases"
        try:
            real_path = kernel._resolve_path(database)
        except Exception as e:
            return f"JEV FALLBACK: invalid database path ({e}) — decide with your own judgment."
        if not real_path.exists():
            return f"JEV FALLBACK: database not found ({database}) — decide with your own judgment."
        try:
            conn = _sqlite_connect(real_path, row_factory=sqlite3.Row)
            conn.execute("PRAGMA query_only = ON")
            sql = f"SELECT {', '.join(safe_cols)} FROM {safe_table} WHERE case_id = ? LIMIT 1"
            cur = conn.execute(sql, (case_id.strip(),))
            row = cur.fetchone()
            conn.close()
        except sqlite3.Error as e:
            return f"JEV FALLBACK: SQL error ({e}) — decide with your own judgment."
        if row is None:
            return f"JEV FALLBACK: no {safe_table} row for case_id {case_id} — decide with your own judgment."

        checklist = _jev_format_checklist({k: row[k] for k in row.keys()}, safe_cols)
        logger.info("jev_verify case=%s checklist=[%s]", case_id, checklist)

        # ── One calibrated yes/no over the IDENTICAL evidence ──
        r = jev_noul(checklist, question)
        if not r.get("ok"):
            logger.info("jev_verify fallback: %s", r.get("error"))
            return f"JEV FALLBACK: {r.get('error','jev unavailable')} — decide with your own judgment."
        conf = r["confidence"]
        logger.info("JEV VERDICT (verify) noul=%s confidence=%.2f (gate=%.2f) case=%s",
                    r["noul"], conf, gate, case_id)
        if not r["noul"]:
            return f"JEV VERDICT: FAIL | confidence {conf:.2f} | checklist: {checklist}"
        if conf < gate:
            return (f"JEV VERDICT: ESCALATE | confidence {conf:.2f} (below gate {gate:.2f}) "
                    f"— send to a human | checklist: {checklist}")
        return f"JEV VERDICT: PASS | confidence {conf:.2f} | checklist: {checklist}"

    return jev_verify



def create_jev_vision_tool(confidence_threshold: float = 0.80):
    """Create the jev_see tool — a calibrated, type-safe decision over a camera frame.

    Mirrors jev_decide (Choice/Noul + confidence gate) but the input is an image
    reference (a local frame path or an id the edge resolves). Use inside a worker
    node to classify a scene; low confidence returns ESCALATE so converge/verify
    routes to a human.

    Args:
        confidence_threshold: default gate; a call may override via `threshold`.
    """
    @tool
    def jev_see(image_ref: str, question: str, instructions: str = "",
                criteria: Optional[dict] = None, options: Optional[str] = None,
                threshold: Optional[float] = None) -> str:
        """Make a calibrated, type-safe decision about a camera frame (no generation).

        Two modes:
          - question="choice": pick 1 of N. Pass `criteria` = {label: description}
            OR `options` = "a,b,c". `instructions` is the visual question.
          - question="noul":   a yes/no judgment. `instructions` is the question.

        Args:
            image_ref: local frame path (base64'd to the edge) or an id the edge resolves.
            question: "choice" or "noul".
            instructions: the visual question, e.g. "What is on the shelf section?".
            criteria: for choice — {label: one-line description} (2..255 labels).
            options: for choice — comma-separated labels (alternative to criteria).
            threshold: optional confidence-gate override (default 0.80).

        Returns (one line the skill can echo):
            choice -> "VISION CHOICE: <label> | confidence 0.xx"  (or "... | ESCALATE (below gate)")
            noul   -> "VISION VERDICT: PASS|FAIL | confidence 0.xx"  (or "... ESCALATE")
            error  -> "VISION FALLBACK: <reason> — send to a human."
        """
        from .vision_client import vision_choice, vision_noul
        gate = float(threshold) if threshold is not None else confidence_threshold
        q = (question or "").strip().lower()
        if not image_ref or not image_ref.strip():
            return "VISION FALLBACK: jev_see needs an image_ref — send to a human."

        if q == "choice":
            crit = criteria or {o.strip(): o.strip()
                                for o in (options or "").split(",") if o.strip()}
            r = vision_choice(image_ref, crit, instructions or "Classify the image.")
            if not r.get("ok"):
                logger.info("jev_see(choice) fallback: %s", r.get("error"))
                return f"VISION FALLBACK: {r.get('error','vision unavailable')} — send to a human."
            conf = r["confidence"]
            logger.info("VISION CHOICE '%s' confidence=%.2f (gate=%.2f)", r["choice"], conf, gate)
            if conf < gate:
                return f"VISION CHOICE: {r['choice']} | confidence {conf:.2f} | ESCALATE (below gate {gate:.2f})"
            return f"VISION CHOICE: {r['choice']} | confidence {conf:.2f}"

        if q == "noul":
            r = vision_noul(image_ref, instructions or "Does the condition hold in this image?")
            if not r.get("ok"):
                logger.info("jev_see(noul) fallback: %s", r.get("error"))
                return f"VISION FALLBACK: {r.get('error','vision unavailable')} — send to a human."
            conf = r["confidence"]
            logger.info("VISION VERDICT noul=%s confidence=%.2f (gate=%.2f)", r["noul"], conf, gate)
            if conf < gate:
                return f"VISION VERDICT: ESCALATE | confidence {conf:.2f} (below gate {gate:.2f}) — send to a human."
            return f"VISION VERDICT: {'PASS' if r['noul'] else 'FAIL'} | confidence {conf:.2f}"

        return "VISION FALLBACK: question must be 'choice' or 'noul' — send to a human."

    return jev_see


def create_jev_vision_verify_tool(kernel, confidence_threshold: float = 0.65):
    """Create the jev_vision_verify tool — a calibrated PASS/FAIL/ESCALATE over a frame.

    The verifier analog of jev_verify for the physical world: the LLM does NOT
    describe the scene; it passes the raw frame + a FIXED question to the edge, and
    Jev-style calibrated yes/no decides. This removes the paraphrasing source of
    wobble (the frame itself is the evidence). Fails soft to ESCALATE.

    Args:
        kernel: SafeKernel — used for the camera/vision entitlement check if present.
        confidence_threshold: gate below which a "yes" becomes ESCALATE.
    """
    @tool
    def jev_vision_verify(image_ref: str,
                          question: str = "Is the required condition satisfied in this image?",
                          threshold: Optional[float] = None) -> str:
        """Deterministically verify a condition holds in a camera frame, via the edge VLM.

        Args:
            image_ref: local frame path (base64'd to the edge) or an id the edge resolves.
            question: the fixed calibrated yes/no the model must judge.
            threshold: optional confidence-gate override (default 0.65).

        Returns (one line the skill can echo verbatim):
            "VISION VERDICT: PASS | confidence 0.xx | q: <...>"
            "VISION VERDICT: FAIL | confidence 0.xx | q: <...>"
            "VISION VERDICT: ESCALATE | confidence 0.xx (below gate) | q: <...>"
            "VISION FALLBACK: <reason> — send to a human."
        """
        from .vision_client import vision_noul
        gate = float(threshold) if threshold is not None else confidence_threshold
        if not image_ref or not image_ref.strip():
            return "VISION FALLBACK: jev_vision_verify needs an image_ref — send to a human."

        # ── Camera/vision entitlement (mirrors the SQL database_allowed gate) ──
        try:
            if hasattr(kernel, "vision_allowed"):
                allowed, reason = kernel.vision_allowed(image_ref, "read")
                if not allowed:
                    return f"VISION FALLBACK: camera not permitted ({reason}) — send to a human."
        except Exception as e:
            logger.debug("jev_vision_verify entitlement check failed (%s) — continuing.", e)

        r = vision_noul(image_ref, question)
        if not r.get("ok"):
            logger.info("jev_vision_verify fallback: %s", r.get("error"))
            return f"VISION FALLBACK: {r.get('error','vision unavailable')} — send to a human."
        conf = r["confidence"]
        logger.info("VISION VERDICT (verify) noul=%s confidence=%.2f (gate=%.2f)", r["noul"], conf, gate)
        if not r["noul"]:
            return f"VISION VERDICT: FAIL | confidence {conf:.2f} | q: {question}"
        if conf < gate:
            return (f"VISION VERDICT: ESCALATE | confidence {conf:.2f} (below gate {gate:.2f}) "
                    f"— send to a human | q: {question}")
        return f"VISION VERDICT: PASS | confidence {conf:.2f} | q: {question}"

    return jev_vision_verify



def create_memory_tool(memory, get_retrieval_mode: Callable[[], str], get_cached_embedding: Callable[[], Optional[list]] = None, get_entity_hint: Callable[[], Optional[str]] = None):
    """
    Create the query_memory tool for agent-driven context retrieval.
    
    Args:
        memory: AgentMemory instance for knowledge/episode search
        get_retrieval_mode: Callable that returns current mode ('scan', 'semantic', 'hybrid')
        get_cached_embedding: Optional callable that returns cached query embedding
    
    Returns:
        LangChain @tool function
    """
    # Simple stopword set for noun extraction (no LLM needed)
    _STOPWORDS = {
        "the", "is", "are", "was", "were", "what", "show", "me", "get", "find",
        "for", "of", "and", "or", "with", "from", "to", "a", "an", "in", "on",
        "at", "by", "how", "when", "where", "who", "can", "do", "does", "did",
        "has", "have", "had", "all", "any", "this", "that", "about", "list",
        "give", "tell", "check", "look", "need", "want", "please", "its", "my"
    }

    def _key_nouns(q: str) -> List[str]:
        """Extract key nouns from query by stripping stopwords."""
        words = re.findall(r'\b\w{3,}\b', q.lower())
        return [w for w in words if w not in _STOPWORDS][:6]

    @tool
    def query_memory(query: str, scope: str = "all") -> str:
        """Search the agent's persistent knowledge base for relevant context.

        Uses a tiered cascade: entity-specific facts first (newest), then
        query-similarity search, then broadened noun search as fallback.
        Always returns file paths so you can grep for more detail if needed.

        Args:
            query: Natural language search (e.g., "FastShip payment terms",
                   "vendors on quality hold", "what happened with the BOFA dispute")
            scope: "knowledge" | "episodes" | "all" (default)

        Returns:
            Ranked context records + file paths for deeper shell/grep search.
        """
        logger.debug("QUERY_MEMORY called: query='%s', scope='%s'", query, scope)

        try:
            entity_hint = get_entity_hint() if get_entity_hint else None
            kr_mode     = get_retrieval_mode()
            cached_emb  = get_cached_embedding() if get_cached_embedding else None
            nouns       = _key_nouns(query)

            knowledge_results: List[Dict] = []
            episode_results:   List[Dict] = []

            if scope in ("all", "knowledge", "entities", "decisions"):

                # TIER 1 — entity exact lookup via xref (newest first)
                if entity_hint:
                    try:
                        tier1 = memory.knowledge_indexer.search_by_entity(
                            entity_name=entity_hint, top_k=5
                        )
                        for r in tier1:
                            knowledge_results.append({
                                "_source": "knowledge", "_tier": 1,
                                "type": r.get("knowledge_type", "knowledge"),
                                "summary": r.get("summary", ""),
                                "ts": r.get("ts", ""),
                                "id": r.get("id", ""),
                                "match_method": r.get("match_method", "entity_xref"),
                            })
                        logger.info("query_memory TIER1 knowledge xref: entity=%s → %d records", entity_hint, len(tier1))
                    except Exception as e:
                        logger.error("Tier1 entity lookup failed: %s", e)

                tier1_ids = {r["id"] for r in knowledge_results}

                # TIER 2 — semantic on full query
                if kr_mode in ("semantic", "hybrid"):
                    try:
                        tier2 = memory.knowledge_indexer.search_similar(
                            query=query, top_k=8, min_score=0.3,
                            _precomputed_embedding=cached_emb,
                        )
                        for r in tier2:
                            if r.get("id") in tier1_ids:
                                continue
                            knowledge_results.append({
                                "_source": "knowledge", "_tier": 2,
                                "type": r.get("knowledge_type", "knowledge"),
                                "summary": r.get("summary", ""),
                                "ts": r.get("ts", ""),
                                "score": r.get("score", 0),
                                "id": r.get("id", ""),
                                "match_method": r.get("match_method", "semantic"),
                            })
                        logger.debug("TIER2 semantic → %d records", len(tier2))
                    except Exception as e:
                        logger.error("Tier2 semantic failed: %s", e)
                        kr_mode = "scan"

                tier1_2_ids = {r["id"] for r in knowledge_results}

                # TIER 3 — broaden to key nouns only (when thin results)
                if len(knowledge_results) < 3 and nouns:
                    try:
                        tier3 = memory.knowledge_indexer.search_similar(
                            query=" ".join(nouns), top_k=5, min_score=0.25,
                            _precomputed_embedding=None,
                        )
                        for r in tier3:
                            if r.get("id") in tier1_2_ids:
                                continue
                            knowledge_results.append({
                                "_source": "knowledge", "_tier": 3,
                                "type": r.get("knowledge_type", "knowledge"),
                                "summary": r.get("summary", ""),
                                "ts": r.get("ts", ""),
                                "id": r.get("id", ""),
                                "match_method": "nouns_broadened",
                            })
                        logger.debug("TIER3 nouns=%s → %d records", nouns, len(tier3))
                    except Exception as e:
                        logger.error("Tier3 noun search failed: %s", e)

                # TIER 4 — JSONL grep fallback (only if all tiers empty)
                if not knowledge_results and nouns:
                    try:
                        grep_results = memory.grep_context_graph(nouns, max_results=10)
                        for r in grep_results:
                            if r.get("_source") == "knowledge":
                                r["_tier"] = 4
                                knowledge_results.append(r)
                        logger.debug("TIER4 grep → %d records", len(grep_results))
                    except Exception as e:
                        logger.error("Tier4 grep fallback failed: %s", e)

            if scope in ("all", "episodes"):

                ep_tier1_ids: set = set()

                # TIER 1 — entity xref on episodes
                if entity_hint:
                    try:
                        rows = memory.knowledge_indexer.expand_by_entities(
                            {entity_hint.lower(), f"vendor:{entity_hint.lower()}"},
                            record_type="episode", top_k=5)
                        for row in rows:
                            rid = row.get("id")
                            ep_tier1_ids.add(rid)
                            episode_results.append({
                                "_source": "episode", "_tier": 1,
                                "timestamp": row.get("ts") or "",
                                "skill": row.get("skill") or "",
                                "query": (row.get("user_input") or "")[:100],
                                "response_summary": (row.get("summary") or "")[:200],
                                "id": rid, "match_method": "entity_xref",
                            })
                        logger.info("query_memory TIER1 episode xref: entity=%s → %d episodes", entity_hint, len(rows))
                    except Exception as e:
                        logger.error("Episode tier1 xref failed: %s", e)

                # TIER 2 — semantic episode search
                if kr_mode in ("semantic", "hybrid"):
                    try:
                        sem_eps = memory.knowledge_indexer.search_episodes(
                            query=query, top_k=5, min_score=0.3,
                            _precomputed_embedding=cached_emb,
                        )
                        for ep in sem_eps:
                            if ep.get("id") in ep_tier1_ids:
                                continue
                            episode_results.append({
                                "_source": "episode", "_tier": 2,
                                "timestamp": ep.get("ts", ""),
                                "skill": ep.get("skill", ""),
                                "query": ep.get("user_input", "")[:100],
                                "response_summary": ep.get("summary", "")[:200],
                                "score": ep.get("score", 0),
                                "id": ep.get("id", ""),
                                "match_method": ep.get("match_method", "semantic"),
                            })
                        logger.debug("EP TIER2 semantic → %d episodes", len(sem_eps))
                    except Exception as e:
                        logger.error("Episode tier2 semantic failed: %s", e)
                        kr_mode = "scan"

                # TIER 3 — JSONL grep fallback for episodes
                if len(episode_results) < 2:
                    try:
                        grep_eps = memory.search_episodes_agentic(
                            query, max_results=5, scope="recent",
                            _precomputed_keywords=nouns,
                        )
                        ep_seen = {r.get("id") for r in episode_results}
                        for ep in grep_eps:
                            if ep.get("id") in ep_seen:
                                continue
                            episode_results.append({
                                "_source": "episode", "_tier": 3,
                                "timestamp": ep.get("timestamp", ""),
                                "skill": ep.get("skill", ""),
                                "query": ep.get("user_input", "")[:100],
                                "response_summary": ep.get("response_summary", "")[:200],
                            })
                        logger.debug("EP TIER3 grep → %d episodes", len(grep_eps))
                    except Exception as e:
                        logger.error("Episode tier3 grep failed: %s", e)

            all_results = knowledge_results + episode_results
            if not all_results:
                # Still return file paths so agent can grep directly
                formatted = "No structured records found.\n"
            else:
                formatted = memory.format_context_for_prompt(
                    [r for r in all_results if r.get("_source") != "episode"],
                    max_chars=1200,
                )
                if episode_results:
                    ep_lines = ["\n### Past Conversations (newest first):"]
                    for ep in episode_results:
                        ep_lines.append(
                            f"- [{ep.get('timestamp','?')}] ({ep.get('skill','?')}) "
                            f"Q: {ep.get('query','')}"
                        )
                        if ep.get("response_summary"):
                            ep_lines.append(f"  ↳ {ep['response_summary']}")
                    formatted += "\n".join(ep_lines)

            try:
                k_path  = getattr(memory, 'knowledge_jsonl_path', None)
                ep_files = memory._get_recent_episode_files(days=7, entity_hint=entity_hint)
                ep_lines_paths = "\n".join(f"  {p}" for p in ep_files[:5]) or "  (none found)"
                grep_hint = entity_hint or (nouns[0] if nouns else query[:20])
                formatted += f"""

## Search deeper (shell + grep)
Knowledge file : {k_path}
Recent episodes:
{ep_lines_paths}
Grep tip: grep -i "{grep_hint}" <file_path>
If results above are thin (<3), grep the files above with different keyword variations."""
            except Exception as fp_err:
                logger.warning("File path block failed (non-fatal): %s", fp_err)

            logger.debug("query_memory returning %d chars", len(formatted))
            return formatted

        except Exception as e:
            logger.error("query_memory error: %s", e)
            return f"Memory search failed: {str(e)}"
    
    return query_memory



def create_invoke_skill_tool(router, agent_factory_fn: Callable, current_depth: int):
    """
    Create the invoke_skill tool for cross-skill delegation inside the ReAct loop.

    The tool routes a sub-task to the best-matching skill via the router, creates
    a child SkillAgent, and returns its result. The child agent has incremented
    _invoke_depth so it cannot recurse beyond MAX_INVOKE_DEPTH.

    Args:
        router: SkillRouter instance for matching tasks to skills.
        agent_factory_fn: Callable(skill_name) -> SkillAgent. Creates a child
                          agent pre-configured with incremented depth.
        current_depth: The invoking agent's _invoke_depth (0 = top-level).

    Returns:
        LangChain @tool function.
    """

    @tool
    def invoke_skill(task: str, context: str = "", target_skill: str = "") -> str:
        """Delegate a sub-task to another skill and return its result.

        Use this when you need capabilities outside your current skill —
        for example, fetching AR data while you are the general agent.
        The framework will automatically route the task to the best skill,
        or you can specify target_skill to bypass routing entirely.

        Args:
            task: A clear, self-contained description of what you need done.
                  Write it as if briefing a colleague — include relevant details.
            context: Optional prior results or background the target skill needs.
                     Keep it concise (key data points, not full histories).
            target_skill: Optional skill name to call directly, bypassing the router.
                          Use when you know exactly which skill you need (e.g. "file_explorer").
                          Leave empty to let the framework route automatically.

        Returns:
            The result from the delegated skill (may be truncated to 4000 chars).
        """
        if not task or not task.strip():
            return "Error: task cannot be empty. Describe what you need done."

        if current_depth >= MAX_INVOKE_DEPTH:
            return (
                f"Error: Maximum delegation depth ({MAX_INVOKE_DEPTH}) reached. "
                f"Cannot delegate further. Handle this task with your own tools."
            )

        try:
            # Route the task — use target_skill if provided, otherwise let router decide
            if target_skill and target_skill.strip():
                skill_name = target_skill.strip()
                logger.info(
                    "invoke_skill [depth=%d]: task='%s' -> skill='%s' (direct)",
                    current_depth, task[:80], skill_name,
                )
            else:
                skill_name = router.match(task)
                logger.info(
                    "invoke_skill [depth=%d]: task='%s' -> skill='%s'",
                    current_depth, task[:80], skill_name,
                )

            # Build the full prompt for the child agent
            child_query = task
            if context:
                child_query = f"{task}\n\nContext:\n{context[:2000]}"

            # Create child agent and run (agent_factory_fn handles depth increment)
            child_agent = agent_factory_fn(skill_name)
            result = child_agent.run(
                child_query,
                skill_name=skill_name,
                skip_memory=True,   # Children skip memory ops for speed
                light_mode=True,    # Skip heavy context loading
            )

            # Truncate long results to stay within token budget
            if isinstance(result, tuple):
                result = result[0]  # (response, tool_calls) format
            result = str(result)
            if len(result) > MAX_RESULT_CHARS:
                result = result[:MAX_RESULT_CHARS] + "\n... (truncated)"

            logger.info(
                "invoke_skill [depth=%d]: skill='%s' returned %d chars",
                current_depth, skill_name, len(result),
            )
            return result

        except Exception as e:
            logger.error("invoke_skill failed: %s", e, exc_info=True)
            return f"Error: Skill delegation failed — {type(e).__name__}: {str(e)[:300]}"

    return invoke_skill



def create_create_plan_tool(agent, llm, router):
    """
    Create the create_plan tool for ReAct agents.

    Generates a DAG execution plan via PlannerEngine, stores it on the agent
    for later execution, and returns the plan display for user confirmation.
    Does NOT execute — the user must approve via plan_action{action:"approve"}.

    Args:
        agent:  The SkillAgent instance (plan stored as agent._plan_store[plan_id]).
        llm:    LangChain chat model (prefer light_llm for speed).
        router: SkillRouter for building available_skills list.
    """

    @tool
    def create_plan(goal: str, feedback: str = "", existing_plan_id: str = "") -> str:
        """Generate a multi-skill execution plan and present it to the user for approval.

        Use this when the user's request spans multiple domains or skills and you
        cannot answer it with your own tools alone. The plan will be shown to the
        user who can then approve, reject, or request modifications.

        Args:
            goal: The user's original request or goal (copy it verbatim).
            feedback: Optional modification instruction when revising an existing plan
                      (e.g. "add a GL reconciliation step between step 1 and 2").
            existing_plan_id: Plan ID of the plan being modified. Leave empty for
                              a new plan. When provided the existing step IDs and
                              skills are preserved and only the requested change applied.

        Returns:
            Formatted plan display string with plan_id for user confirmation.
        """
        from .planner import PlannerEngine, build_planner_context
        from .plan_critic import PlanCritic

        available_skills = [s["name"] for s in router.list_skills()]
        skill_descriptions = {s["name"]: s.get("description", "") for s in router.list_skills()}

        existing_plan = None
        if existing_plan_id:
            plan_store = getattr(agent, '_plan_store', {})
            existing_plan = plan_store.get(existing_plan_id)

        # Plan cache hint — if a similar approved plan was found before routing,
        # use its steps as a starting template (LLM adapts for current entities)
        if not existing_plan:
            _cache_hit = getattr(agent, '_plan_cache_hit', None)
            if _cache_hit and _cache_hit.get("execution_mode") == "planned":
                existing_plan = {"steps": _cache_hit.get("plan_steps", [])}
                logger.info("create_plan: using plan_cache template (score=%.2f, plan_id=%s)",
                            _cache_hit["score"], _cache_hit["plan_id"])

        # Augment goal with feedback if modifying
        query = f"{goal}\n\nUser refinement: {feedback}" if feedback else goal

        # Detected domains: use existing plan's domains or derive from skill list
        detected_domains = []
        if existing_plan:
            detected_domains = existing_plan.get("detected_domains", [])

        _ectx = getattr(agent, '_entity_context', None)
        entity_context = build_planner_context(_ectx) if _ectx else ""

        # Grab progress tracker so we can emit sub-steps into the reasoning stepper.
        # Stored on agent by agent.run() — None if called outside normal run() path.
        _tracker = getattr(agent, '_progress_tracker', None)

        def _sub(label: str, detail: str = None, status: str = "active"):
            if _tracker:
                try:
                    _tracker.sub_step(label, detail=detail, status=status)
                except Exception:
                    pass

        engine = PlannerEngine(llm=llm)
        _sub("Generating plan...", detail=f"{len(available_skills)} skills available")
        plan = engine.generate_plan(
            query=query,
            detected_domains=detected_domains,
            available_skills=available_skills,
            skill_descriptions=skill_descriptions,
            existing_plan=existing_plan,
            entity_context=entity_context,
        )

        if "error" in plan:
            _sub("Plan generation failed", status="error")
            return f"Could not generate plan: {plan['error']}"

        n_steps = len(plan.get("steps", []))
        _sub("Generating plan...", detail=f"{n_steps} steps", status="completed")

        # Preserve detected_domains on the plan for future modifications
        plan["detected_domains"] = detected_domains

        critique_display = ""
        if getattr(agent, 'enable_critique', False):
            try:
                _indexer = getattr(agent, 'memory', None)
                _indexer = getattr(_indexer, 'indexer', None)  # AgentMemory.indexer
                critic = PlanCritic(llm=llm, indexer=_indexer)
                _sub("Running critique...")
                critique = critic.critique(plan, entity_context, query)
                plan["critique"] = critique  # stored for reference
                critique_display = critic.format_for_display(critique)
                _conf = critique.get("confidence", "high")
                _issues = critique.get("issues", [])
                if _issues:
                    _sub(
                        "Critique complete",
                        detail=f"confidence={_conf} — {len(_issues)} issue(s) found",
                        status="completed",
                    )
                else:
                    _sub("Critique complete", detail=f"confidence={_conf}, no issues", status="completed")
                logger.info(
                    "create_plan: critique confidence=%s issues=%d",
                    _conf, len(_issues),
                )
            except Exception as _ce:
                _sub("Critique skipped", detail="internal error", status="error")
                logger.warning("create_plan: critique failed (non-fatal): %s", _ce)

        # Store plan for execution after user approves
        if not hasattr(agent, '_plan_store'):
            agent._plan_store = {}
        display = engine.format_plan_for_display(plan) + critique_display
        plan["display"] = display  # stored so chat.py can render verbatim
        agent._plan_store[plan["plan_id"]] = plan
        # Also set _pending_plan so execute_confirmed_plan() works unchanged
        agent._pending_plan = plan
        logger.info("create_plan: generated plan %s with %d steps",
                    plan["plan_id"], len(plan.get("steps", [])))
        return display

    return create_plan



def create_invoke_plan_tool(
    agent_factory_fn: Callable,
    tools_map_fn: Callable,
    current_depth: int,
    router=None,
):
    """
    Create the invoke_plan tool for structured multi-skill DAG execution.

    The tool accepts a JSON plan describing steps with dependencies, constructs
    Step objects in-memory, and dispatches to ParallelEngine or WorkflowEngine.

    Args:
        agent_factory_fn: Callable(skill_name) -> SkillAgent child factory.
        tools_map_fn: Callable() -> dict of action->function for engines.
        current_depth: The invoking agent's _invoke_depth.
        router: Optional SkillRouter for validating skill names in steps.

    Returns:
        LangChain @tool function.
    """

    @tool
    def invoke_plan(plan_json: str) -> str:
        """Execute a multi-skill plan IMMEDIATELY without user confirmation.

        WARNING: This tool executes right away — the user will NOT see a plan
        preview or get a chance to approve or modify before execution.

        Use this ONLY when the user has already explicitly approved the steps
        (e.g. "just run it", "no need to confirm") or when execution is trivially
        safe and reversible.

        For multi-domain queries where the user should review the plan first,
        call create_plan instead — it generates the same DAG but shows it to the
        user for approval before running anything.

        Args:
            plan_json: A JSON string with the execution plan. Schema:
                {
                  "mode": "parallel" or "workflow",
                  "steps": [
                    {
                      "name": "step_id",
                      "skill": "skill_name",
                      "task": "What this step should do",
                      "depends_on": ["other_step_id"]
                    }
                  ]
                }

                - mode "parallel": Independent steps run concurrently;
                  steps with depends_on wait for their dependencies.
                - mode "workflow": Steps run strictly in order.
                - Use {{step_name.output}} in a task to reference
                  a prior step's result.

        Returns:
            Combined results from all steps, formatted with status.
        """
        import asyncio
        import time as _time

        if current_depth >= MAX_INVOKE_DEPTH:
            return (
                f"Error: Maximum delegation depth ({MAX_INVOKE_DEPTH}) reached. "
                f"Cannot execute plan. Handle tasks with your own tools."
            )

        try:
            plan = json.loads(plan_json)
        except (json.JSONDecodeError, TypeError) as e:
            return f"Error: Invalid plan JSON — {e}"

        mode = plan.get("mode", "parallel")
        if mode not in ("parallel", "workflow"):
            return f"Error: mode must be 'parallel' or 'workflow', got '{mode}'"

        steps_raw = plan.get("steps")
        if not steps_raw or not isinstance(steps_raw, list):
            return "Error: Plan must include a non-empty 'steps' array."

        if len(steps_raw) > MAX_PLAN_STEPS:
            return f"Error: Plan exceeds {MAX_PLAN_STEPS} steps (got {len(steps_raw)})."

        all_step_names = {s.get("name") for s in steps_raw if isinstance(s, dict)}
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                return f"Error: Step {i} must be a JSON object."
            name = s.get("name")
            if not name:
                return f"Error: Step {i} missing required 'name' field."
            if not s.get("skill"):
                return f"Error: Step '{name}' missing required 'skill' field."
            if not s.get("task"):
                return f"Error: Step '{name}' missing required 'task' field."
            for dep in s.get("depends_on", []):
                if dep not in all_step_names:
                    return f"Error: Step '{name}' depends on unknown step '{dep}'."

        # Check for duplicate names
        seen_names = set()
        for s in steps_raw:
            name = s.get("name")
            if name in seen_names:
                return f"Error: Duplicate step name '{name}'."
            seen_names.add(name)

        if router:
            for s in steps_raw:
                if not router.skill_exists(s["skill"]):
                    return f"Error: Unknown skill '{s['skill']}' in step '{s['name']}'."

        try:
            from .execution import Step, ParallelEngine, WorkflowEngine
        except ImportError:
            # Fallback for direct module loading (e.g., tests)
            from execution import Step, ParallelEngine, WorkflowEngine

        steps = []
        for s in steps_raw:
            steps.append(Step(
                name=s["name"],
                action="skill",
                skill=s["skill"],
                task=s["task"],
                depends_on=s.get("depends_on", []),
            ))

        start_time = _time.time()
        tools_map = tools_map_fn()

        try:
            if mode == "parallel":
                engine = ParallelEngine(tools_map, agent_factory=agent_factory_fn)
                # Handle asyncio nesting (same pattern as _run_parallel in agent.py)
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        engine_results = pool.submit(
                            asyncio.run, engine.run(steps)
                        ).result(timeout=120)
                else:
                    engine_results = asyncio.run(engine.run(steps))

            else:  # workflow
                engine = WorkflowEngine(tools_map, agent_factory=agent_factory_fn)
                engine_results = engine.run(steps)

        except ValueError as e:
            # Circular dependency or other structural error from engine
            return f"Error: Plan execution failed — {e}"
        except Exception as e:
            logger.error("invoke_plan engine failed: %s", e, exc_info=True)
            return f"Error: Plan execution failed — {type(e).__name__}: {str(e)[:300]}"

        duration_ms = int((_time.time() - start_time) * 1000)
        lines = [f"## Plan Execution Results ({mode} mode, {duration_ms}ms)\n"]
        successful = sum(1 for r in engine_results.values() if r.success)
        lines.append(
            f"**Steps:** {len(engine_results)} | "
            f"**Succeeded:** {successful} | "
            f"**Failed:** {len(engine_results) - successful}\n"
        )

        for name, result in engine_results.items():
            status = "✅" if result.success else "❌"
            lines.append(f"{status} **{name}** ({result.duration_ms}ms)")
            if result.error:
                lines.append(f"   Error: {result.error}")

        # Append step outputs (truncated per step)
        lines.append("\n---\n")
        for name, result in engine_results.items():
            if result.success and result.output:
                output = str(result.output)
                if len(output) > MAX_RESULT_CHARS:
                    output = output[:MAX_RESULT_CHARS] + "\n... (truncated)"
                lines.append(f"### {name}\n{output}\n")

        logger.info(
            "invoke_plan [depth=%d]: mode=%s steps=%d succeeded=%d in %dms",
            current_depth, mode, len(engine_results), successful, duration_ms,
        )
        return "\n".join(lines)

    return invoke_plan
