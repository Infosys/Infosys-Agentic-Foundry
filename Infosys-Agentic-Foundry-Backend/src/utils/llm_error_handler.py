# src/utils/llm_error_handler.py
#
# Provider-agnostic LLM error classification and handling.
#
# Design principles:
#   1. No hard dependency on litellm — works with openai SDK alone.
#      When litellm is installed, its more granular exceptions are used.
#   2. For known providers (openai, litellm), map to structured error_types.
#   3. For UNKNOWN providers / exception classes (Claude, Qwen, local models, …),
#      pass the original error message through transparently so framework users
#      see exactly what the model returned — no misleading rewrites.
#   4. HTTP status code heuristics as a safety net for any provider.

from typing import Callable, Any, Dict, List, Optional, Tuple
from functools import wraps
from contextlib import asynccontextmanager

from src.utils.errors import LLMInfrastructureError
from telemetry_wrapper import logger as log


# ────────────────────────────────────────────────────────────────────────────
# 1. Build the ordered error map at import time.
#    litellm is optional — if not installed, we just skip its exception types.
# ────────────────────────────────────────────────────────────────────────────

# Each entry: (exception_class, error_type_key, user_message)
# ORDER MATTERS — more specific subclasses MUST appear before parent classes.
LLM_ERROR_MAP: List[Tuple[type, str, str]] = []

# -- Optional litellm exceptions (most granular, checked first) -------------
try:
    from litellm.exceptions import (
        ContextWindowExceededError as _LiteLLMContextWindow,
        ContentPolicyViolationError as _LiteLLMContentPolicy,
        ServiceUnavailableError as _LiteLLMServiceUnavailable,
        Timeout as _LiteLLMTimeout,
    )
    LLM_ERROR_MAP.extend([
        (_LiteLLMContextWindow, "context_length",
         "Message too long. Please reduce the length of your input."),
        (_LiteLLMContentPolicy, "content_policy",
         "Request was blocked due to content policy. Please rephrase your message."),
        (_LiteLLMServiceUnavailable, "service_unavailable",
         "The LLM service is temporarily unavailable. Please try again later."),
        (_LiteLLMTimeout, "timeout",
         "The LLM request timed out. Please try again."),
    ])
    _HAS_LITELLM = True
except ImportError:
    _HAS_LITELLM = False

# -- openai SDK exceptions (always available) --------------------------------
from openai import APIConnectionError, APIStatusError, APIError
from openai._exceptions import (
    RateLimitError, BadRequestError, AuthenticationError,
    ContentFilterFinishReasonError,
)

LLM_ERROR_MAP.extend([
    (ContentFilterFinishReasonError, "content_policy",
     "Request was blocked due to content policy. Please rephrase your message."),
    (RateLimitError, "rate_limit",
     "Too many requests. Please wait a moment and try again."),
    (AuthenticationError, "invalid_credentials",
     "Invalid model credentials. Please contact support."),
    (APIConnectionError, "connection_error",
     "Unable to connect to the LLM service. Please try again later."),
    # BadRequestError is last among openai types — litellm subclasses already matched above
    (BadRequestError, "bad_request",
     "The request was rejected by the LLM service."),
])

# Collect all exception types for fast isinstance checks
_KNOWN_LLM_EXCEPTION_TYPES: Tuple[type, ...] = tuple(
    exc_cls for exc_cls, _, _ in LLM_ERROR_MAP
) + (APIStatusError, APIError, LLMInfrastructureError)


# ────────────────────────────────────────────────────────────────────────────
# 2. HTTP status code → error_type mapping (provider-agnostic safety net)
#    Any exception exposing .status_code will be classified even if its
#    class is unknown (e.g. a new provider SDK we've never seen).
# ────────────────────────────────────────────────────────────────────────────

_STATUS_CODE_MAP: Dict[int, str] = {
    400: "bad_request",
    401: "invalid_credentials",
    403: "content_policy",
    408: "timeout",
    413: "context_length",
    429: "rate_limit",
    500: "server_error",
    502: "connection_error",
    503: "service_unavailable",
    504: "timeout",
}


# ────────────────────────────────────────────────────────────────────────────
# 3. Message-pattern heuristics (last resort, provider-agnostic)
#    Scans the error string for common keywords regardless of exception class.
# ────────────────────────────────────────────────────────────────────────────

_MESSAGE_PATTERNS: List[Tuple[List[str], str]] = [
    (["rate limit", "rate_limit", "too many requests", "throttl"],           "rate_limit"),
    (["context length", "context_length", "maximum context", "token limit",
      "max_tokens", "too many tokens"],                                      "context_length"),
    (["content filter", "content_filter", "content policy", "content_policy",
      "moderation", "safety filter", "blocked"],                             "content_policy"),
    (["authentication", "auth", "api key", "api_key", "unauthorized",
      "invalid key"],                                                        "invalid_credentials"),
    (["timeout", "timed out", "deadline exceeded"],                          "timeout"),
    (["connection", "connect", "unreachable", "network"],                    "connection_error"),
    (["unavailable", "service unavailable", "overloaded"],                   "service_unavailable"),
]


def _match_message_pattern(exc_str: str) -> Optional[str]:
    """Return error_type if any keyword pattern matches, else None."""
    for keywords, error_type in _MESSAGE_PATTERNS:
        for kw in keywords:
            if kw in exc_str:
                return error_type
    return None


# ────────────────────────────────────────────────────────────────────────────
# 4. Provider info extraction (for logging)
# ────────────────────────────────────────────────────────────────────────────

def _get_provider_info(exc: Exception) -> str:
    """Extract provider/model info from litellm exceptions for logging.
    These attributes (.llm_provider, .model) are litellm-specific — they do
    NOT exist on plain openai or other provider SDK exceptions."""
    if not _HAS_LITELLM:
        return ""
    # Only read these attrs from actual litellm exception instances
    llm_provider = getattr(exc, 'llm_provider', None)
    model = getattr(exc, 'model', None) if llm_provider else None
    parts = []
    if llm_provider:
        parts.append(f"provider={llm_provider}")
    if model:
        parts.append(f"model={model}")
    return f" [{', '.join(parts)}]" if parts else ""


# ────────────────────────────────────────────────────────────────────────────
# 5. Core classification
# ────────────────────────────────────────────────────────────────────────────

def classify_llm_exception(exc: Exception) -> Tuple[str, str]:
    """
    Classify an LLM exception into (error_type, user_message).

    Classification order:
      1. Exact exception class match (openai + optional litellm)
      2. HTTP status code from exc.status_code (any provider)
      3. Message keyword heuristics (any provider)
      4. Transparent pass-through — returns the original error message
         so unknown-provider errors are never masked.
    """
    # --- Tier 1: known exception classes ---
    for exc_class, error_type, message in LLM_ERROR_MAP:
        if isinstance(exc, exc_class):
            return error_type, message

    # --- Tier 2: HTTP status code (works for any SDK that sets .status_code) ---
    status_code = getattr(exc, 'status_code', None)
    if status_code and status_code in _STATUS_CODE_MAP:
        return _STATUS_CODE_MAP[status_code], str(exc)

    # --- Tier 3: message pattern heuristics ---
    exc_str = str(exc).lower()
    matched_type = _match_message_pattern(exc_str)
    if matched_type:
        return matched_type, str(exc)

    # --- Tier 4: generic openai API error ---
    if isinstance(exc, (APIError, APIStatusError)):
        return "api_error", str(exc)

    # --- Fallback: pass through the original message transparently ---
    return "unknown", str(exc)


def is_llm_exception(exc: Exception) -> bool:
    """
    Check if exception is a known LLM infrastructure exception.
    Returns True for openai, litellm (when installed), and already-wrapped errors.
    """
    if isinstance(exc, _KNOWN_LLM_EXCEPTION_TYPES):
        return True
    # Also treat anything with an HTTP status_code attr as an LLM error
    # (covers unknown provider SDKs like anthropic, cohere, etc.)
    if hasattr(exc, 'status_code') and isinstance(getattr(exc, 'status_code', None), int):
        return True
    return False


# ────────────────────────────────────────────────────────────────────────────
# 6. Context manager
# ────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def handle_llm_errors(session_id: str = None, writer: Callable = None):
    """
    Async context manager that catches LLM exceptions and converts them
    to LLMInfrastructureError with proper error_type.

    Works for any provider:
      - openai / Azure  → caught by class
      - litellm (if installed) → caught by class (more granular)
      - Unknown providers (Claude SDK, Qwen, local models, …) → caught by
        status_code / message heuristics; original error message preserved.

    Usage:
        async with handle_llm_errors(session_id, writer):
            response = await llm.ainvoke(...)
    """
    try:
        yield
    except LLMInfrastructureError:
        # Already wrapped, just re-raise
        raise
    except Exception as e:
        if is_llm_exception(e):
            error_type, user_message = classify_llm_exception(e)
            provider_info = _get_provider_info(e)

            # Write failure status if writer provided
            if writer:
                writer({"Node Name": "Thinking...", "Status": "Failed"})

            # Log with session + provider context
            log_msg = f"[{session_id}] " if session_id else ""
            log.error(f"{log_msg}LLM error ({error_type}){provider_info}: {e}", exc_info=True)

            raise LLMInfrastructureError(user_message, type=error_type) from e
        else:
            # Not an LLM error, re-raise as-is
            raise