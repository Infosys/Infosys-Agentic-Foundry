# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Skill-agent tools — give the LLM the ability to read, list, search
files and execute code within the agent's workspace directory.

Production-hardened with:
  - SafePath sandbox (no '..' traversal)
  - AST-scanned Python execution (blocks dangerous imports)
  - Subprocess isolation with timeout + memory limit
  - Rate limiting (sliding window)
  - Audit logging (every tool call logged)
  - Output size caps

Inspired by AgentPro's kernel.py and smart_code_executor patterns.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import tool

from src.config.application_config import app_config

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_OUTPUT_CHARS = 10_000
PYTHON_TIMEOUT_SECONDS = int(os.getenv("SKILL_PYTHON_TIMEOUT", "30"))
RATE_LIMIT_MAX = int(os.getenv("SKILL_RATE_LIMIT_MAX", "120"))
RATE_LIMIT_WINDOW = int(os.getenv("SKILL_RATE_LIMIT_WINDOW", "60"))

# Maximum file size (bytes) that read_file_from_mount will process.
# Files larger than this are rejected to prevent OOM in the subprocess.
MAX_FILE_READ_BYTES = int(os.getenv("SKILL_MAX_FILE_READ_MB", "50")) * 1024 * 1024

# Imports BLOCKED in execute_python_code (security)
BLOCKED_IMPORTS = frozenset({
    "subprocess", "shutil",
    "ctypes", "socket", "http.server",
    "multiprocessing", "threading",
    "signal", "pty", "fcntl",
    "importlib", "runpy", "code", "codeop",
    "webbrowser", "antigravity",
    "pickle", "shelve", "marshal",
    # Sandbox escape vectors — block alternative file I/O modules
    # NOTE: io is ALLOWED because io.BytesIO is needed for in-memory file
    # processing (e.g., reading .msg, .xlsx from blob bytes). The actual
    # file write protection is enforced by _restricted_open patching io.open.
    "codecs",    # codecs.open() bypasses builtins.open patch
    "tempfile",  # tempfile.NamedTemporaryFile() creates writable files
    "pathlib",   # pathlib.Path.read_text() / write_text() bypass sandbox
})

# Maximum memory (bytes) a subprocess can use — 256 MB default
MAX_MEMORY_BYTES = int(os.getenv("SKILL_MAX_MEMORY_MB", "256")) * 1024 * 1024

# Dangerous built-in function calls blocked at AST level
BLOCKED_BUILTINS = frozenset({
    "exec", "eval", "compile", "__import__", "breakpoint",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
})

# Dangerous attribute calls blocked at AST level (obj.method)
BLOCKED_ATTR_CALLS = frozenset({
    "os.system", "os.popen", "os.execvp", "os.execv", "os.execve",
    "os.fork", "os.kill", "os.remove", "os.unlink", "os.rmdir",
    "os.rename", "os.makedirs", "os.mkdir",
    "shutil.rmtree", "shutil.move", "shutil.copy", "shutil.copy2",
    "pathlib.Path.write_text", "pathlib.Path.write_bytes",
    "pathlib.Path.read_text", "pathlib.Path.read_bytes",
    "pathlib.Path.unlink", "pathlib.Path.rmdir", "pathlib.Path.rename",
    "pathlib.Path.open",
    "io.open", "codecs.open",
})

# Dangerous attribute names blocked regardless of the object they're called on.
# This catches chained / aliased access like  x = os; x.system("cmd")
_BLOCKED_ATTR_NAMES = frozenset({
    "system", "popen", "execvp", "execv", "execve", "fork",
    "rmtree", "write_text", "write_bytes",
})

# Runtime security prelude injected into every executed script.
# This monkey-patches builtins to restrict file writes and network access
# even if the AST scanner misses something (defence-in-depth).
#
# NOTE: The file-reader prelude (_FILE_READER_PRELUDE) is injected AFTER
# this prelude when a path mapping is available, giving execute_python_code
# the ability to read binary/complex files (PDF, Excel, DOCX, …) from
# any mounted virtual path.
_RUNTIME_SECURITY_PRELUDE = '''
import builtins as _builtins
import os as _os

# --- Restrict open() to read-only mode (unless path is in writable allowlist) ---
# Capture _original_open via default argument so it survives `del` cleanup.
_original_open = _builtins.open

# Build writable-path allowlist from env var (set by host when read-write mounts exist)
import json as _json, base64 as _b64w
_writable_dirs = []
_wd_raw = _os.environ.get("_AGTOS_WRITABLE_PATHS", "")
if _wd_raw:
    try:
        _writable_dirs = _json.loads(_b64w.b64decode(_wd_raw).decode("utf-8"))
    except Exception:
        pass
# Scrub from env so user code cannot read it
_os.environ.pop("_AGTOS_WRITABLE_PATHS", None)
del _json, _b64w

def _restricted_open(file, mode="r", *args, _orig=_original_open, _wdirs=_writable_dirs, _abspath=_os.path.abspath, _normcase=_os.path.normcase, **kwargs):
    _mode = mode.lower() if isinstance(mode, str) else str(mode)
    if any(c in _mode for c in ("w", "a", "x", "+")):
        # Allow writes only to paths under writable mount directories
        # Use normcase for case-insensitive comparison on Windows
        _path = _normcase(_abspath(str(file)))
        _allowed = False
        for _wd in _wdirs:
            if _path.startswith(_normcase(_wd)):
                _allowed = True
                break
        if not _allowed:
            raise PermissionError(f"File write operations are not allowed in sandboxed execution (mode={mode!r})")
    # Block reading sensitive paths
    _path = str(file)
    _sensitive = ("/etc/passwd", "/etc/shadow", ".env", ".git/config", "id_rsa", "credentials")
    for _s in _sensitive:
        if _s in _path.replace("\\\\", "/").lower():
            raise PermissionError(f"Access to sensitive file is not allowed: {_path}")
    return _orig(file, mode, *args, **kwargs)
_builtins.open = _restricted_open

# Also patch io.open — libraries like openpyxl/zipfile call io.open() directly,
# which bypasses builtins.open.  This ensures _restricted_open is enforced.
import io as _io_mod
_io_mod.open = _restricted_open
del _io_mod

# --- Block low-level os.open() write flags (defence-in-depth) ---
_OS_WRITE_MASK = _os.O_WRONLY | _os.O_RDWR | _os.O_CREAT | _os.O_APPEND | _os.O_TRUNC
_os_open_orig = _os.open
def _restricted_os_open(path, flags, *args, _orig=_os_open_orig, _wmask=_OS_WRITE_MASK, _wdirs=_writable_dirs, _abspath=_os.path.abspath, _normcase=_os.path.normcase, **kwargs):
    if flags & _wmask:
        _path = _normcase(_abspath(str(path)))
        _allowed = False
        for _wd in _wdirs:
            if _path.startswith(_normcase(_wd)):
                _allowed = True
                break
        if not _allowed:
            raise PermissionError("Low-level file write (os.open) is not allowed in sandboxed execution")
    return _orig(path, flags, *args, **kwargs)
_os.open = _restricted_os_open
del _os_open_orig, _OS_WRITE_MASK, _writable_dirs


# --- Block os.environ access to secrets ---
class _SafeEnviron:
    _BLOCKED = {"SECRET", "PASSWORD", "TOKEN", "API_KEY", "PRIVATE", "CREDENTIAL", "DATABASE_URL"}
    __slots__ = ("_real_env",)
    def __init__(self, real_env):
        object.__setattr__(self, "_real_env", real_env)
    def _is_blocked(self, key):
        ku = key.upper() if isinstance(key, str) else str(key).upper()
        return any(b in ku for b in self._BLOCKED)
    def get(self, key, default=None):
        if self._is_blocked(key):
            return default
        return self._real_env.get(key, default)
    def __getitem__(self, key):
        if self._is_blocked(key):
            raise KeyError(key)
        return self._real_env[key]
    def __contains__(self, key):
        if self._is_blocked(key):
            return False
        return key in self._real_env
    def __setitem__(self, key, value):
        if self._is_blocked(key):
            raise PermissionError(f"Cannot set sensitive env var: {key}")
        self._real_env[key] = value
    def __delitem__(self, key):
        if self._is_blocked(key):
            raise PermissionError(f"Cannot delete sensitive env var: {key}")
        del self._real_env[key]
    def __getattr__(self, name):
        # Whitelist safe methods that libraries like requests/urllib3 rely on
        _SAFE = {"copy", "update", "pop", "setdefault", "__len__",
                 "__iter__", "__str__", "__bool__", "__eq__", "__ne__"}
        if name in _SAFE:
            return getattr(dict(self.items()), name)
        raise AttributeError(f"Access denied: os.environ.{name}")
    def keys(self):
        return [k for k in self._real_env.keys() if not self._is_blocked(k)]
    def values(self):
        return [self._real_env[k] for k in self.keys()]
    def items(self):
        return [(k, self._real_env[k]) for k in self.keys()]
    def __iter__(self):
        return iter(self.keys())
    def __len__(self):
        return len(self.keys())
    def copy(self):
        return dict(self.items())
    def __repr__(self):
        return repr(dict(self.items()))
_os.environ = _SafeEnviron(_os.environ)
del _builtins, _os, _original_open
'''


# ---------------------------------------------------------------------------
# File-Reader Prelude — injected into sandbox when path_mapping is set
# ---------------------------------------------------------------------------
#
# Provides two functions pre-loaded into every sandbox execution:
#   read_file_from_mount(virtual_path)  — read any file type
#   list_files_in_mount(virtual_path)   — list directory contents
#
# The mapping JSON (_path_mapping.json) is written to the sandbox dir at
# execution time and DELETED after loading so the agent never sees raw
# real-filesystem paths.

_FILE_READER_PRELUDE = '''
# ---- File-Reader helpers (auto-injected by AgentOS) ----
def _setup_file_readers():
    import json as _json
    import os as _os
    import base64 as _b64_mod

    _MAX_READ = {max_read}  # bytes — enforced before any file I/O

    _mapping = {}
    # Mapping is passed via env var to avoid any disk-based exposure.
    _map_b64 = _os.environ.get("_AGTOS_PATH_MAP", "")
    if _map_b64:
        try:
            _mapping = _json.loads(_b64_mod.b64decode(_map_b64).decode("utf-8"))
        except Exception:
            pass
        # Scrub the env var so agent code never sees raw real paths.
        try:
            del _os.environ._real_env["_AGTOS_PATH_MAP"]
        except Exception:
            pass

    def _resolve(vpath):
        """Map a virtual path to its real filesystem path.

        Security:
          - Resolves symlinks via os.path.realpath()
          - Validates the resolved path is still inside the mount root
          - Blocks path-traversal (../) that escapes the mount
        """
        vpath = vpath.replace("\\\\", "/")
        if not vpath.startswith("/"):
            vpath = "/" + vpath
        best_prefix = ""
        best_real = ""
        for vp, info in _mapping.items():
            if vpath == vp or vpath.startswith(vp + "/"):
                if len(vp) > len(best_prefix):
                    best_prefix = vp
                    best_real = info["real_path"]
        if not best_prefix:
            avail = ", ".join(sorted(_mapping.keys())) if _mapping else "(none)"
            raise FileNotFoundError(
                f"No mounted path matches \'{vpath}\'. Available mounts: {avail}"
            )
        rel = vpath[len(best_prefix):].lstrip("/")
        joined = _os.path.join(best_real, rel) if rel else best_real
        # Resolve symlinks + normalise to a canonical absolute path
        real_resolved = _os.path.realpath(joined)
        mount_resolved = _os.path.realpath(best_real)
        # Containment check: resolved path MUST stay inside mount root
        if not (real_resolved == mount_resolved
                or real_resolved.startswith(mount_resolved + _os.sep)):
            raise PermissionError(
                f"Access denied: path escapes the mount boundary ({vpath})"
            )
        return real_resolved

    def read_file_from_mount(virtual_path):
        """Read any file from a mounted virtual path.

        Supports: PDF, Excel (.xlsx/.xls), CSV, DOCX, PPTX, JSON, YAML/YML,
                  XML, HTML, TXT, MD, LOG, PY, and all common text formats.
                  For images: returns base64-encoded data string.

        Args:
            virtual_path: e.g. "/company_policies/report.pdf"
        Returns:
            str: Extracted text content of the file.
        """
        # _resolve() handles traversal/symlink checks and raises on escape.
        real = _resolve(virtual_path)
        if not _os.path.exists(real):
            raise FileNotFoundError(f"File not found: {virtual_path}")
        if not _os.path.isfile(real):
            raise IsADirectoryError(f"Path is a directory, not a file: {virtual_path}")

        # ---- File size guard (#3) ----
        fsize = _os.path.getsize(real)
        if fsize > _MAX_READ:
            mb = round(fsize / (1024 * 1024), 1)
            cap = round(_MAX_READ / (1024 * 1024), 1)
            raise ValueError(
                f"File too large ({mb} MB) — limit is {cap} MB: {virtual_path}"
            )

        ext = _os.path.splitext(real)[1].lower()

        # All file-format readers are wrapped in a try/except so that
        # library-level exceptions never leak real filesystem paths (#2).
        try:
            return _read_by_ext(real, ext, virtual_path)
        except (FileNotFoundError, IsADirectoryError, PermissionError, ValueError):
            raise  # These already use virtual_path — safe to propagate.
        except Exception as _e:
            # Sanitise: strip any real-path fragments from the message.
            _msg = str(_e)
            for _vp, _info in _mapping.items():
                _rp = _info.get("real_path", "")
                if _rp and _rp in _msg:
                    _msg = _msg.replace(_rp, _vp)
            raise RuntimeError(
                f"Error reading {virtual_path}: {_msg}"
            ) from None

    def _read_by_ext(real, ext, virtual_path):
        """Dispatch file reading by extension (internal)."""

        # ---- PDF ----
        if ext == ".pdf":
            try:
                import pdfplumber
                parts = []
                with pdfplumber.open(real) as pdf:
                    for i, page in enumerate(pdf.pages):
                        t = page.extract_text()
                        if t:
                            parts.append(f"--- Page {i+1} ---\\n{t}")
                return "\\n\\n".join(parts) if parts else "(PDF contains no extractable text)"
            except ImportError:
                try:
                    import PyPDF2
                    parts = []
                    with open(real, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        for i, page in enumerate(reader.pages):
                            t = page.extract_text()
                            if t:
                                parts.append(f"--- Page {i+1} ---\\n{t}")
                    return "\\n\\n".join(parts) if parts else "(PDF contains no extractable text)"
                except ImportError:
                    return "Error: Install pdfplumber or PyPDF2 to read PDF files."

        # ---- Excel ----
        if ext in (".xlsx", ".xls"):
            try:
                import pandas as pd
                xls = pd.ExcelFile(real)
                parts = []
                for sheet in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet)
                    parts.append(f"--- Sheet: {sheet} ---\\n{df.to_string(index=False)}")
                return "\\n\\n".join(parts)
            except ImportError:
                return "Error: Install pandas and openpyxl to read Excel files."

        # ---- CSV ----
        if ext == ".csv":
            try:
                import pandas as pd
                df = pd.read_csv(real)
                return df.to_string(index=False)
            except ImportError:
                import csv as _csv
                with open(real, "r", encoding="utf-8") as f:
                    rows = list(_csv.reader(f))
                return "\\n".join(",".join(row) for row in rows)

        # ---- Word DOCX ----
        if ext == ".docx":
            try:
                from docx import Document
                doc = Document(real)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables_text = []
                for table in doc.tables:
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        tables_text.append(" | ".join(cells))
                result = "\\n".join(paragraphs)
                if tables_text:
                    result += "\\n\\n--- Tables ---\\n" + "\\n".join(tables_text)
                return result if result.strip() else "(DOCX contains no extractable text)"
            except ImportError:
                return "Error: Install python-docx to read DOCX files."

        # ---- PowerPoint PPTX ----
        if ext == ".pptx":
            try:
                from pptx import Presentation
                prs = Presentation(real)
                parts = []
                for i, slide in enumerate(prs.slides):
                    texts = []
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            texts.append(shape.text)
                    if texts:
                        parts.append(f"--- Slide {i+1} ---\\n" + "\\n".join(texts))
                return "\\n\\n".join(parts) if parts else "(PPTX contains no extractable text)"
            except ImportError:
                return "Error: Install python-pptx to read PPTX files."

        # ---- JSON ----
        if ext == ".json":
            with open(real, "r", encoding="utf-8") as f:
                data = _json.load(f)
            return _json.dumps(data, indent=2, ensure_ascii=False)

        # ---- YAML ----
        if ext in (".yaml", ".yml"):
            try:
                import yaml
                with open(real, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                return _json.dumps(data, indent=2, ensure_ascii=False) if data else ""
            except ImportError:
                with open(real, "r", encoding="utf-8") as f:
                    return f.read()

        # ---- Images ----
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".svg"):
            if ext == ".svg":
                with open(real, "r", encoding="utf-8") as f:
                    return f.read()
            size = _os.path.getsize(real)
            with open(real, "rb") as f:
                b64 = _b64_mod.b64encode(f.read()).decode("ascii")
            return f"[Image: {_os.path.basename(real)}, {size} bytes]\\nbase64:{b64}"

        # ---- Generic text (try multiple encodings) ----
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(real, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue

        # ---- Binary fallback ----
        with open(real, "rb") as f:
            raw = f.read()
        return (
            f"[Binary file: {_os.path.basename(real)}, {len(raw)} bytes]\\n"
            f"base64:{_b64_mod.b64encode(raw).decode('ascii')}"
        )

    def list_files_in_mount(virtual_path="/"):
        """List files and directories in a mounted virtual path.

        Args:
            virtual_path: e.g. "/company_policies/" or "/" for all mounts.
        Returns:
            list[str]: Sorted list of names (directories end with /).
        """
        if virtual_path in ("", "/"):
            return sorted(list(_mapping.keys()))
        # _resolve() enforces containment + symlink resolution.
        real = _resolve(virtual_path)
        if not _os.path.exists(real):
            raise FileNotFoundError(f"Directory not found: {virtual_path}")
        if not _os.path.isdir(real):
            raise NotADirectoryError(f"Not a directory: {virtual_path}")
        entries = []
        for name in sorted(_os.listdir(real)):
            full = _os.path.join(real, name)
            # Skip entries that would resolve outside mount root (symlink guard)
            try:
                _resolve(virtual_path.rstrip("/") + "/" + name)
            except (PermissionError, FileNotFoundError):
                continue
            entries.append(name + "/" if _os.path.isdir(full) else name)
        return entries

    def resolve_path(virtual_path):
        """Resolve a virtual mount path to its real filesystem path.

        Use this when you need to pass a file path to pandas, open(), or
        any library that requires a real filesystem path.

        Example:
            import pandas as pd
            df = pd.read_csv(resolve_path('/motiva_demo/inventory.csv'))

        Args:
            virtual_path: e.g. "/motiva_demo/inventory.csv"
        Returns:
            str: The real filesystem path.
        Raises:
            FileNotFoundError: If no mount matches the virtual path.
        """
        return _resolve(virtual_path)

    return read_file_from_mount, list_files_in_mount, _read_by_ext, resolve_path


read_file_from_mount, list_files_in_mount, _read_by_ext, resolve_path = _setup_file_readers()
del _setup_file_readers

# ---- Auto-resolve virtual paths in open() / os.path / pathlib ----
# This makes code like pd.read_csv('/motiva_demo/file.csv') work
# transparently without the LLM needing to call resolve_path() explicitly.
import builtins as _ar_builtins
import os as _ar_os

_ar_prev_open = _ar_builtins.open  # already _restricted_open from security prelude
_ar_orig_exists = _ar_os.path.exists  # capture BEFORE the os.path patching loop

def _auto_resolve_open(file, mode="r", *args, _prev=_ar_prev_open, _exists=_ar_orig_exists, _resolve=resolve_path, **kwargs):
    """Wrapper around open() that auto-resolves virtual mount paths."""
    _p = str(file)
    _orig_p = _p
    if _p.startswith("/") and not _exists(_p):
        try:
            _p = _resolve(_p)
        except (FileNotFoundError, PermissionError):
            pass  # Not a virtual path — let the original open() handle the error
    try:
        return _prev(_p, mode, *args, **kwargs)
    except Exception as _e:
        # Sanitize: do not leak resolved real filesystem paths in error messages
        if _p != _orig_p:
            _msg = str(_e).replace(_p, _orig_p).replace(_p.replace("/", "\\\\"), _orig_p)
            raise type(_e)(_msg) from None
        raise

_ar_builtins.open = _auto_resolve_open

# Also patch io.open so libraries (openpyxl → zipfile → io.open) go through
# the auto-resolve path resolution.  Without this, pd.read_excel('/virtual/x.xlsx')
# fails because zipfile.ZipFile calls io.open() directly.
import io as _ar_io
_ar_io.open = _auto_resolve_open
del _ar_io

# Also patch os.path.exists / os.path.isfile / os.path.isdir / os.path.getsize
# so that os.path.exists('/motiva_demo/file.csv') returns True
_ar_osp = _ar_os.path  # capture before del
for _ar_fn_name in ("exists", "isfile", "isdir", "getsize"):
    _ar_orig = getattr(_ar_osp, _ar_fn_name)
    def _make_wrapper(_orig_fn):
        def _wrapper(path, *args, **kwargs):
            _p = str(path)
            if _p.startswith("/") and not _orig_fn(_p):
                try:
                    _p = resolve_path(_p)
                except (FileNotFoundError, PermissionError):
                    pass
            return _orig_fn(_p, *args, **kwargs)
        return _wrapper
    setattr(_ar_osp, _ar_fn_name, _make_wrapper(_ar_orig))

del _ar_builtins, _ar_os, _ar_prev_open, _ar_orig_exists, _ar_osp, _ar_orig, _ar_fn_name, _make_wrapper
'''


# ---------------------------------------------------------------------------
# Path-mapping generator — builds virtual→real mapping from agent_config.json
# ---------------------------------------------------------------------------

def _generate_path_mapping(agent_dir: Path) -> dict:
    """
    Generate a virtual-path → real-path mapping dict for the code executor.

    Reads ``additional_paths`` from  ``agent_dir/agent_config.json`` and
    builds the same mount names that :class:`AgentShell` would create.

    Also includes ``/skills/`` and ``/enterprise_context/`` so the code
    executor can read binary files placed there too.

    Returns
    -------
    dict
        ``{virtual_prefix: {"real_path": str}, ...}``
        Empty dict when no paths are configured.
    """
    mapping: dict = {}

    # ----- Built-in mounts derivable from agent_dir -----
    for vname, sub in (("skills", "skills"), ("enterprise_context", "enterprise_context"), ("agent", "agent")):
        d = (agent_dir / sub).resolve()
        if d.exists():
            mapping[f"/{vname}"] = {"real_path": str(d), "permission": "read"}

    # ----- Additional paths from agent_config.json -----
    config_path = agent_dir / "agent_config.json"
    if not config_path.exists():
        return mapping

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        additional_paths = cfg.get("additional_paths") or []
    except Exception as exc:
        log.warning(f"[skill_tools] Could not read agent_config.json: {exc}")
        return mapping

    if not additional_paths:
        return mapping

    # dept_root = agent_workspaces/{dept}/
    dept_root = agent_dir.parent.parent
    builtin_prefixes = {"/user", "/databases", "/skills", "/enterprise_context", "/agent", "/session"}
    used_names: set = set()

    # --- Build effective allowed roots (agent-level + optional server override) ---
    # 1. Agent-level roots from agent_config.json
    _agent_roots: list[Path] = []
    for _r in (cfg.get("allowed_absolute_mount_roots") or []):
        _r = str(_r).strip()
        if _r:
            _agent_roots.append(Path(_r).resolve())

    # 1b. Auto-derive roots from absolute entries when none were configured.
    #     Mirrors the same logic in AgentShell.__init__() to prevent the
    #     path-mapping from silently omitting absolute mounts.
    #     Only auto-derive when the key is None (not configured);
    #     an explicit empty list [] means "disabled".
    if cfg.get("allowed_absolute_mount_roots") is None and not _agent_roots:
        for _entry in additional_paths:
            if _entry.get("absolute"):
                _raw = _entry.get("path", "").strip()
                if _raw:
                    _p = Path(_raw).resolve()
                    _agent_roots.append(_p if _p.is_dir() else _p.parent)
        if _agent_roots:
            _seen: set[Path] = set()
            _deduped: list[Path] = []
            for _ar in _agent_roots:
                if _ar not in _seen:
                    _seen.add(_ar)
                    _deduped.append(_ar)
            _agent_roots = _deduped
            log.info(
                f"[skill_tools] Auto-derived allowed_absolute_mount_roots "
                f"from additional_paths: {[str(r) for r in _agent_roots]}"
            )

    # 2. Server-level roots from env (optional hard constraint)
    _server_roots_raw = app_config.ALLOWED_ABSOLUTE_MOUNT_ROOTS
    _server_roots: list[Path] = []
    if _server_roots_raw:
        for _r in _server_roots_raw.split(","):
            _r = _r.strip()
            if _r:
                # Security: reject paths containing traversal sequences
                if ".." in _r:
                    log.warning(f"[skill_tools] Rejecting mount root with traversal: {_r!r}")
                    continue
                # Validate path contains only safe characters
                import re as _re
                if not _re.match(r'^[a-zA-Z0-9_/\\:.\- ]+$', _r):
                    log.warning(f"[skill_tools] Rejecting mount root with invalid characters: {_r!r}")
                    continue
                _resolved = Path(os.path.realpath(_r))
                _server_roots.append(_resolved)

    # 3. Compute effective roots
    _allowed_abs_roots: list[Path] = []
    if _agent_roots:
        if _server_roots:
            for ar in _agent_roots:
                for sr in _server_roots:
                    try:
                        if ar.is_relative_to(sr):
                            _allowed_abs_roots.append(ar)
                            break
                    except (TypeError, AttributeError):
                        if str(ar).startswith(str(sr)):
                            _allowed_abs_roots.append(ar)
                            break
        else:
            _allowed_abs_roots = _agent_roots

    for entry in additional_paths:
        rel_path = entry.get("path", "").strip().replace("\\", "/").strip("/")
        permission = entry.get("permission", "read").strip().lower()
        is_absolute = entry.get("absolute", False)
        if not rel_path:
            continue

        mount_name = Path(rel_path).name.strip()
        if not mount_name:
            continue

        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in mount_name.lower())
        if not safe_name:
            continue

        virtual_prefix = f"/{safe_name}"
        if virtual_prefix in builtin_prefixes or safe_name in used_names:
            continue

        if is_absolute:
            abs_path_str = entry.get("path", "").strip().replace("\\", "/")
            real_path = Path(abs_path_str).resolve()
            # Must be under an allowed root
            if not _allowed_abs_roots:
                continue
            if not any(
                real_path.is_relative_to(ar) if hasattr(real_path, "is_relative_to")
                else str(real_path).startswith(str(ar))
                for ar in _allowed_abs_roots
            ):
                continue
            if not real_path.exists():
                continue
        else:
            real_path = (dept_root / rel_path).resolve()
            if not real_path.exists():
                continue

        mapping[virtual_prefix] = {"real_path": str(real_path), "permission": permission}
        used_names.add(safe_name)

    return mapping


# ---------------------------------------------------------------------------
# Rate Limiter (sliding window, per-agent)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding window rate limiter — prevents runaway tool calls. Thread-safe."""

    def __init__(self, max_requests: int = RATE_LIMIT_MAX, window_seconds: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque = deque()
        self._lock = __import__("threading").Lock()

    def check(self) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_requests:
                return False
            self._timestamps.append(now)
            return True

    @property
    def remaining(self) -> int:
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            active = sum(1 for t in self._timestamps if t >= cutoff)
        return max(0, self.max_requests - active)


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------

class AuditLogger:
    """Append-only JSONL audit log for tool calls."""

    def __init__(self, agent_dir: Path):
        self._log_dir = agent_dir / ".audit"
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def log(self, tool_name: str, args: dict, result_preview: str,
            success: bool, duration_ms: float, error: str = ""):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "args": args,
            "success": success,
            "duration_ms": round(duration_ms, 1),
            "result_preview": result_preview[:200],
            "error": error[:500] if error else "",
        }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self._log_dir / f"tool_audit_{today}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.warning(f"[AuditLogger] Failed to write audit log: {e}")


# ---------------------------------------------------------------------------
# Exec/Eval Wrapper — injected into the sandbox to provide Jupyter-style
# automatic result capture.  The user code is passed via the __AGTX_CODE__
# environment variable (base64-encoded).  The wrapper:
#   1. Parses the code into an AST
#   2. If the last statement is a bare expression (not print/assign/etc.),
#      pops it off, exec()s the body, then eval()s the expression
#   3. Prints the evaluated result to stdout so the host captures it
# ---------------------------------------------------------------------------
_EXEC_EVAL_WRAPPER = '''
import ast as __xr_ast
import base64 as __xr_b64
import os as __xr_os
import sys as __xr_sys

__xr_code = __xr_b64.b64decode(__xr_os.environ.get("__AGTX_CODE__", "")).decode("utf-8")
# Scrub the env var so agent code cannot read the raw source
__xr_os.environ.pop("__AGTX_CODE__", None)

# Build namespace that includes prelude functions (resolve_path, etc.)
__xr_ns = dict(globals())

try:
    __xr_tree = __xr_ast.parse(__xr_code)
except SyntaxError as __xr_e:
    print(f"SyntaxError: {__xr_e}", file=__xr_sys.stderr)
    __xr_sys.exit(1)

# Detect if last statement is a bare expression (not a print() call)
__xr_capture = False
if __xr_tree.body and isinstance(__xr_tree.body[-1], __xr_ast.Expr):
    __xr_last_val = __xr_tree.body[-1].value
    __xr_is_print = (
        isinstance(__xr_last_val, __xr_ast.Call)
        and isinstance(getattr(__xr_last_val, "func", None), __xr_ast.Name)
        and __xr_last_val.func.id == "print"
    )
    if not __xr_is_print:
        __xr_capture = True

if __xr_capture:
    __xr_last_node = __xr_tree.body.pop()
    # Execute all statements except the last expression
    exec(compile(__xr_tree, "<user>", "exec"), __xr_ns)
    # Evaluate the last expression in the same namespace
    __xr_result = eval(
        compile(__xr_ast.Expression(body=__xr_last_node.value), "<expr>", "eval"),
        __xr_ns,
    )
    if __xr_result is not None:
        print(__xr_result)
else:
    exec(compile(__xr_tree, "<user>", "exec"), __xr_ns)
'''


# ---------------------------------------------------------------------------
# AST Security Scanner for Python code
# ---------------------------------------------------------------------------

def _scan_code_ast(code: str) -> Optional[str]:
    """
    Parse Python code into AST and block dangerous imports/calls.
    Returns an error message if blocked, None if safe.

    Defence-in-depth: This is the *first* layer.  The runtime security
    prelude (_RUNTIME_SECURITY_PRELUDE) is the *second* layer.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error in code: {e}"

    for node in ast.walk(tree):
        # Block: import subprocess
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_root = alias.name.split(".")[0]
                if module_root in BLOCKED_IMPORTS or alias.name in BLOCKED_IMPORTS:
                    return f"Blocked import: '{alias.name}' is not allowed for security reasons."

        # Block: from subprocess import ...
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_root = node.module.split(".")[0]
                if module_root in BLOCKED_IMPORTS or node.module in BLOCKED_IMPORTS:
                    return f"Blocked import: 'from {node.module}' is not allowed for security reasons."

        # Block dangerous built-in calls: exec(), eval(), compile(), etc.
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_BUILTINS:
                return f"Blocked function: '{func.id}()' is not allowed for security reasons."
            elif isinstance(func, ast.Attribute):
                # Direct pattern: os.system(...)
                if isinstance(func.value, ast.Name):
                    full_name = f"{func.value.id}.{func.attr}"
                    if full_name in BLOCKED_ATTR_CALLS:
                        return f"Blocked call: '{full_name}()' is not allowed for security reasons."
                # Chained pattern: pathlib.Path.write_text(...)
                elif isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name):
                    full_name = f"{func.value.value.id}.{func.value.attr}.{func.attr}"
                    if full_name in BLOCKED_ATTR_CALLS:
                        return f"Blocked call: '{full_name}()' is not allowed for security reasons."
                # Catch aliased / chained attribute calls:
                # x = os; x.system("cmd") — we block the attribute name itself
                if func.attr in _BLOCKED_ATTR_NAMES:
                    return f"Blocked call: '.{func.attr}()' is not allowed for security reasons."

        # Block: writing to files via `with open(..., 'w')` — catch string literals in open() args
        # (This is a heuristic; runtime prelude is the hard blocker)

    return None  # Code is safe


# ---------------------------------------------------------------------------
# Windows Job Object — enforce memory limits on child processes
# ---------------------------------------------------------------------------

def _run_with_windows_limits(cmd, *, max_memory: int, **kwargs):
    """
    Run a subprocess on Windows with a memory limit enforced via a Job Object.

    Uses ctypes to call Win32 APIs:
      - CreateJobObjectW / SetInformationJobObject (LIMIT_PROCESS_MEMORY)
      - AssignProcessToJobObject

    Falls back to a plain subprocess.run() if Job Object creation fails
    (better to run without limits than to crash).

    Returns a subprocess.CompletedProcess compatible object.
    """
    if sys.platform != "win32":
        return subprocess.run(cmd, **kwargs)

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Win32 constants
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JobObjectExtendedLimitInformation = 9  # info class enum

    # JOBOBJECT_BASIC_LIMIT_INFORMATION (aligned for 64-bit)
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job_handle = None
    try:
        # Create anonymous Job Object
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            log.warning("[SkillTools] CreateJobObjectW failed; running without memory limit")
            return subprocess.run(cmd, **kwargs)

        # Set memory limit
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = max_memory

        ok = kernel32.SetInformationJobObject(
            job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            log.warning("[SkillTools] SetInformationJobObject failed; running without memory limit")
            kernel32.CloseHandle(job_handle)
            return subprocess.run(cmd, **kwargs)

        # Extract timeout from kwargs (Popen doesn't accept 'timeout')
        timeout = kwargs.pop("timeout", None)
        # Popen doesn't accept 'capture_output' — translate to PIPE
        capture_output = kwargs.pop("capture_output", False)
        if capture_output:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE

        # Start the process
        proc = subprocess.Popen(cmd, **kwargs)

        # Assign to job object (best effort — process may already be running fine)
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc.pid
        )
        if handle:
            kernel32.AssignProcessToJobObject(job_handle, handle)
            kernel32.CloseHandle(handle)

        # Wait for completion with timeout
        try:
            stdout_data, stderr_data = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode,
            stdout=stdout_data,
            stderr=stderr_data,
        )
    except subprocess.TimeoutExpired:
        raise  # Re-raise so outer handler catches it
    except Exception as e:
        log.warning(f"[SkillTools] Windows Job Object setup failed ({e}); falling back to plain run")
        # Restore kwargs for subprocess.run fallback
        if "stdout" in kwargs:
            kwargs.pop("stdout", None)
            kwargs.pop("stderr", None)
            kwargs["capture_output"] = True
        return subprocess.run(cmd, **kwargs)
    finally:
        if job_handle:
            kernel32.CloseHandle(job_handle)


# ---------------------------------------------------------------------------
# Tool Factory
# ---------------------------------------------------------------------------

def create_skill_tools(agent_dir: Path) -> list:
    """
    Create LangChain tools scoped to the given agent directory.

    Returns a list containing:
        [execute_python_code]

    The tool automatically detects ``additional_paths`` in the agent's
    ``agent_config.json`` and injects a virtual-path → real-path mapping
    into the sandbox so that ``execute_python_code`` can read *any* file
    type (PDF, Excel, DOCX, PPTX, …) via the pre-loaded helper functions
    ``read_file_from_mount()`` and ``list_files_in_mount()``.

    Note: File browsing/reading/searching is now handled by
    ``run_shell_command`` via AgentShell virtual paths:
        - ``cat /skills/<name>/SKILL.md``  (replaces read_agent_file)
        - ``ls /skills/``                  (replaces list_agent_files)
        - ``grep -r "keyword" /skills/``   (replaces search_agent_files)
    """
    rate_limiter = RateLimiter()
    audit = AuditLogger(agent_dir)

    # Pre-compute the virtual-path → real-path mapping once at tool-creation
    # time. This mapping is written into the sandbox at each execution so
    # the file-reader prelude can resolve virtual paths to real files.
    _path_mapping: dict = _generate_path_mapping(agent_dir)
    if _path_mapping:
        log.info(
            f"[skill_tools] Path mapping for code executor: "
            f"{list(_path_mapping.keys())}"
        )

    def _check_rate_limit(tool_name: str) -> Optional[str]:
        if not rate_limiter.check():
            msg = f"Rate limit exceeded ({RATE_LIMIT_MAX} calls/{RATE_LIMIT_WINDOW}s)."
            audit.log(tool_name, {}, "", False, 0, msg)
            return f"Error [RATE_LIMITED]: {msg}"
        return None

    # NOTE: list_agent_files, read_agent_file, search_agent_files have been
    # removed.  Their functionality is now provided by AgentShell's
    # run_shell_command tool via virtual paths:
    #   cat /skills/<name>/SKILL.md   (replaces read_agent_file)
    #   ls /skills/                   (replaces list_agent_files)
    #   grep -r "keyword" /skills/    (replaces search_agent_files)

    @tool
    def execute_python_code(code: str) -> str:
        """Execute Python code and return the output (stdout + return value).

        Use this tool when you need to:
        - Make HTTP API calls (using the 'requests' library)
        - Process or transform data programmatically
        - Perform calculations
        - Programmatically process file data (e.g. pandas analysis on Excel)

        **NOTE:** To simply *read* a file (PDF, Excel, DOCX, etc.), prefer
        ``run_shell_command(command="readfile <filename>")`` — it is simpler
        and supports auto-discovery by filename.  Use ``execute_python_code``
        with ``read_file_from_mount()`` only when you need to *programmatically
        process* the data (e.g. filter rows, compute statistics, join tables).

        **Pre-loaded helper functions (for programmatic file processing):**

        - ``read_file_from_mount(virtual_path)`` — reads the file and returns
          extracted text.  Supports: PDF, Excel (.xlsx/.xls), CSV, DOCX, PPTX,
          JSON, YAML, XML, HTML, TXT, MD, images, and all common formats.

        - ``list_files_in_mount(virtual_path)`` — lists files and directories.

        Example — programmatic processing:
            content = read_file_from_mount("/company_policies/financials.xlsx")
            # ... process data with pandas, compute stats, etc.
            print(content)

        The code runs in a hardened sandbox with multi-layer security:
        - Layer 1 (AST): Blocks dangerous imports, calls and builtins at parse time
        - Layer 2 (Runtime): Monkey-patches open() to read-only, sanitises os.environ
        - Layer 3 (Subprocess): Isolated mode (-I), separate sandbox directory,
          memory limits (256 MB), CPU timeout, sensitive env vars stripped

        You CANNOT:
        - Write files to disk (open with 'w'/'a'/'x' is blocked)
        - Import subprocess, socket, ctypes, shutil, pickle, etc.
        - Call exec(), eval(), os.system(), os.popen(), etc.
        - Read sensitive files (.env, id_rsa, /etc/shadow, etc.)

        Args:
            code: The Python code to execute. Write complete, runnable code.
                  Use print() to produce output that will be returned.
                  Example:
                      import requests
                      resp = requests.get("http://example.com/api")
                      print(resp.json())
        """
        start = time.time()
        rl_err = _check_rate_limit("execute_python_code")
        if rl_err:
            return rl_err

        log.info(f"[execute_python_code] Executing code ({len(code)} chars)")

        # --- Step 1: AST security scan ---
        scan_error = _scan_code_ast(code)
        if scan_error:
            audit.log("execute_python_code", {"code_len": len(code)}, scan_error, False, (time.time()-start)*1000, scan_error)
            return f"Security Error: {scan_error}"

        # --- Step 2: Execute in subprocess with sandbox + runtime restrictions ---
        try:
            # Create an isolated temp sandbox directory
            sandbox_dir = tempfile.mkdtemp(prefix="skill_sandbox_")

            # Mapping is passed via env var (base64-encoded JSON) to avoid
            # writing real-path data to disk — even transiently (#4).

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8",
                dir=sandbox_dir,
            ) as tmp:
                # Inject runtime security prelude BEFORE user code
                tmp.write(_RUNTIME_SECURITY_PRELUDE)
                # Inject file-reader prelude when path mapping is available
                if _path_mapping:
                    tmp.write("\n")
                    # Interpolate the MAX_FILE_READ_BYTES constant into the prelude.
                    # Use .replace() instead of .format() because the prelude
                    # contains many Python f-string curly braces ({var}).
                    tmp.write(_FILE_READER_PRELUDE.replace("{max_read}", str(MAX_FILE_READ_BYTES)))
                tmp.write("\n# --- Exec/eval wrapper ---\n")
                tmp.write(_EXEC_EVAL_WRAPPER)
                tmp_path = tmp.name

            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"  # Force UTF-8 mode for child process on Windows
                # Strip sensitive env vars from subprocess
                for key in list(env.keys()):
                    if any(s in key.upper() for s in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "PRIVATE", "CREDENTIAL")):
                        del env[key]
                # Prevent subprocess from importing from the main project
                env.pop("PYTHONPATH", None)

                # Pass path mapping via env var (base64 JSON) — not disk (#4)
                if _path_mapping:
                    import base64 as _b64
                    env["_AGTOS_PATH_MAP"] = _b64.b64encode(
                        json.dumps(_path_mapping).encode("utf-8")
                    ).decode("ascii")

                    # Pass writable real-path dirs so _restricted_open can
                    # allowlist writes to read-write mounted folders.
                    _writable_real_dirs = [
                        v["real_path"] for v in _path_mapping.values()
                        if v.get("permission") == "read-write"
                    ]
                    if _writable_real_dirs:
                        env["_AGTOS_WRITABLE_PATHS"] = _b64.b64encode(
                            json.dumps(_writable_real_dirs).encode("utf-8")
                        ).decode("ascii")

                # Pass user code via env var (base64) for exec/eval wrapper
                import base64 as _b64_code
                env["__AGTX_CODE__"] = _b64_code.b64encode(
                    code.encode("utf-8")
                ).decode("ascii")

                # Build subprocess flags for resource limitation
                kwargs = dict(
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=PYTHON_TIMEOUT_SECONDS,
                    env=env,
                    cwd=sandbox_dir,  # isolated temp directory, NOT system tempdir
                )

                # On Windows, memory limits are enforced via Job Objects
                # inside the _run_with_windows_limits helper (no special
                # creationflags needed in kwargs).
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    # On Linux/macOS, use preexec_fn to set memory + CPU limits
                    def _set_limits():
                        import resource
                        # Memory limit
                        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
                        # CPU time limit (same as timeout, backup)
                        resource.setrlimit(resource.RLIMIT_CPU, (PYTHON_TIMEOUT_SECONDS, PYTHON_TIMEOUT_SECONDS))
                    kwargs["preexec_fn"] = _set_limits

                # On Windows, use Popen + Job Object for memory limits
                # instead of subprocess.run to enforce resource constraints.
                if sys.platform == "win32":
                    result = _run_with_windows_limits(
                        [sys.executable, "-I", tmp_path],
                        max_memory=MAX_MEMORY_BYTES,
                        **kwargs,
                    )
                else:
                    result = subprocess.run(
                        [sys.executable, "-I", tmp_path],  # -I = isolated mode (no user site, no PYTHONPATH)
                        **kwargs,
                    )

                stdout = result.stdout or ""
                stderr = result.stderr or ""

                if result.returncode == 0:
                    output = stdout.strip() if stdout.strip() else "(Code executed successfully but produced no output)"
                    audit.log("execute_python_code", {"code_len": len(code)}, f"OK: {output[:200]}", True, (time.time()-start)*1000)
                    return output[:MAX_OUTPUT_CHARS]
                else:
                    error_msg = stderr.strip() or stdout.strip() or "Unknown error"
                    output = ""
                    if stdout.strip():
                        output += f"Partial output:\n{stdout.strip()}\n\n"
                    output += f"Error (exit code {result.returncode}):\n{error_msg}"
                    audit.log("execute_python_code", {"code_len": len(code)}, output[:200], False, (time.time()-start)*1000, error_msg[:500])
                    return output[:MAX_OUTPUT_CHARS]
            finally:
                # Clean up temp file and sandbox directory
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                try:
                    import shutil as _shutil
                    _shutil.rmtree(sandbox_dir, ignore_errors=True)
                except Exception:
                    pass

        except subprocess.TimeoutExpired:
            msg = f"Error: Code execution timed out after {PYTHON_TIMEOUT_SECONDS} seconds."
            audit.log("execute_python_code", {"code_len": len(code)}, msg, False, (time.time()-start)*1000, "timeout")
            return msg
        except Exception as e:
            msg = f"Error executing code: {e}"
            audit.log("execute_python_code", {"code_len": len(code)}, msg, False, (time.time()-start)*1000, str(e))
            return msg

    return [execute_python_code]


# ---------------------------------------------------------------------------
# Helper: Directory tree for system prompt
# ---------------------------------------------------------------------------

def get_directory_tree(agent_dir: Path, max_depth: int = 3) -> str:
    """Generate a tree-like directory listing for the system prompt."""

    def _tree(path: Path, prefix: str = "", depth: int = 0) -> List[str]:
        if depth > max_depth or not path.exists():
            return []
        items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        lines = []
        for item in items:
            if item.name.startswith(".") or item.name == "__pycache__":
                continue
            rel = str(item.relative_to(agent_dir)).replace("\\", "/")
            if item.is_dir():
                lines.append(f"{prefix}{rel}/")
                lines.extend(_tree(item, prefix + "  ", depth + 1))
            else:
                lines.append(f"{prefix}{rel}")
        return lines

    lines = _tree(agent_dir)
    return "\n".join(lines) if lines else "No files found."
