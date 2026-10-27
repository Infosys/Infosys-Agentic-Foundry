"""
IAF Agent Studio — Enterprise Structured Logging

Provides:
- JSONFormatter: emits each log record as a single JSON line
- HumanFormatter: human-readable console format (existing style preserved)
- ContextVars: per-request trace_id / skill / user_id injected into every log line
- setup_logging(): configure root logger with rotating JSON file + console handler

Zero third-party dependencies — stdlib only.
"""

import json
import logging
import logging.handlers
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path


# IAF_DEBUG turns the high-value channels up to DEBUG.

_DEBUG_TRUE = {"1", "true", "yes", "on", "y"}


def _debug_enabled() -> bool:
    val = (os.environ.get("IAF_DEBUG") or "").strip().lower()
    return val in _DEBUG_TRUE


# Channels shown at DEBUG when IAF_DEBUG is set; keep in sync with operator-relevant debug emitters.
_DEBUG_CHANNELS = (
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client",
    "iaf_agent_skills",                  # covers _pyexec, hook_runner, agent
    "iaf_agent_skills.hook_runner",
    "iaf_agent_skills.execution",
    "iaf_agent_skills._pyexec",
    "iaf_agent_skills.model_registry",
    "auth.keycloak_service",
    "routers.oauth",
    "routers.llm_providers",
    "routers.auth",
    "agent_os.kernel",
)



_ctx_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_ctx_skill: ContextVar[str] = ContextVar("skill", default="")
_ctx_user_id: ContextVar[str] = ContextVar("user_id", default="")


def set_request_context(*, trace_id: str = "", skill: str = "", user_id: str = "") -> None:
    """Set per-request context for the current async task."""
    _ctx_trace_id.set(trace_id)
    _ctx_skill.set(skill)
    _ctx_user_id.set(user_id)


def get_trace_id() -> str:
    return _ctx_trace_id.get()


def get_skill() -> str:
    return _ctx_skill.get()


def get_user_id() -> str:
    return _ctx_user_id.get()



_STD_RECORD_KEYS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})



class JSONFormatter(logging.Formatter):
    """
    Emit each log record as a single JSON line.

    Fields emitted:
        ts        ISO-8601 UTC timestamp (millisecond precision)
        level     LEVELNAME string
        logger    logger.name
        msg       formatted message
        trace_id  from ContextVar (omitted if empty)
        skill     from ContextVar (omitted if empty)
        user_id   from ContextVar (omitted if empty)
        exc       formatted exception traceback (omitted if no exception)
        ...       any extra={} fields passed at the call site
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        ts = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]  # milliseconds
            + "Z"
        )
        obj: dict = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Per-request context
        trace_id = _ctx_trace_id.get()
        skill = _ctx_skill.get()
        user_id = _ctx_user_id.get()
        if trace_id:
            obj["trace_id"] = trace_id
        if skill:
            obj["skill"] = skill
        if user_id:
            obj["user_id"] = user_id

        # Exception traceback
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)

        # Caller location (only for WARNING+)
        if record.levelno >= logging.WARNING:
            obj["loc"] = f"{record.filename}:{record.lineno}"

        # Catch-all: extra={} fields passed at the call site
        for key, val in record.__dict__.items():
            if key not in _STD_RECORD_KEYS and not key.startswith("_"):
                obj[key] = val

        return json.dumps(obj, default=str, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Human-readable console format — preserves the existing log style."""

    FMT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    DATEFMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self) -> None:
        super().__init__(self.FMT, datefmt=self.DATEFMT)



_logging_configured = False


def setup_logging(log_dir: Path | None = None) -> Path:
    """
    Configure enterprise logging on the root logger.

    Console handler: INFO+, human-readable (HumanFormatter)
    File handler:    DEBUG+, JSON (JSONFormatter), rotating 10 MB × 5 files

    Call once at process start (idempotent — subsequent calls are no-ops).

    Returns the log file path.
    """
    global _logging_configured
    if _logging_configured:
        return _resolve_log_file(log_dir)

    if log_dir is None:
        # Default: <server_dir>/logs/server.log
        log_dir = Path(__file__).resolve().parent.parent / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console_h = logging.StreamHandler(sys.stdout)
    console_h.setLevel(logging.INFO)
    console_h.setFormatter(HumanFormatter())
    root.addHandler(console_h)

    file_h = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,   # 10 MB per file
        backupCount=5,                # keep server.log.1 … server.log.5
        encoding="utf-8",
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(JSONFormatter())
    root.addHandler(file_h)

    debug = _debug_enabled()
    quiet_level = logging.DEBUG if debug else logging.WARNING

    _QUIET = [
        "uvicorn.access",   # HTTP access log — too verbose at DEBUG
        "httpx",
        "httpcore",
        "openai",
        "openai._base_client",
        "azure",
        "azure.core",
        "azure.identity",
        "urllib3",
        "PIL",
        "multipart",
        "watchfiles",
        "asyncio",
    ]
    for name in _QUIET:
        logging.getLogger(name).setLevel(quiet_level)

    # Keep uvicorn.error at INFO so server errors surface
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    if debug:
        # Console handler is INFO by default; lower it so DEBUG records are
        # visible in NSSM stdout / interactive shells.
        console_h.setLevel(logging.DEBUG)
        for name in _DEBUG_CHANNELS:
            logging.getLogger(name).setLevel(logging.DEBUG)

    _logging_configured = True
    logging.getLogger("iaf_server").info(
        "Logging configured — file: %s (JSON, rotating 10MB×5) IAF_DEBUG=%s",
        log_file, "1" if debug else "0",
    )
    return log_file


def _resolve_log_file(log_dir: Path | None) -> Path:
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
    return log_dir / "server.log"
