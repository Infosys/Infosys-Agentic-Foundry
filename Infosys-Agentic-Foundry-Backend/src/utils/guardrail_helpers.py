"""
Shared guardrail error handling utilities.

Centralises detection, classification, and formatting of guardrail /
content-policy / PII violations so that every agent template (react,
planner-executor, meta, etc.) and tool-onboarding code can reuse the
same logic without duplication.
"""
from __future__ import annotations
import json
import re
from contextvars import ContextVar
from typing import Optional, Tuple
from telemetry_wrapper import logger as log

guardrail_type_ctx: ContextVar[Optional[str]] = ContextVar("guardrail_type", default=None)

class GuardrailRegistry:
    """Registry of available guardrail types for dropdown and validation.

    Populated exclusively from the LiteLLM proxy at startup via
    ``sync_from_proxy()``.  No hardcoded guardrail types live here.
    """

    def __init__(self):
        self._types: dict[str, dict] = {}
        self._synced: bool = False

    async def sync_from_proxy(self) -> bool:
        """Fetch available guardrail types from the LiteLLM proxy.

        Returns ``True`` if the sync succeeded.  On failure the registry
        stays empty — only ``"none"`` will be valid.
        Skips entirely when USE_LITELLM_PROXY_FLAG is not enabled.
        """
        import os, httpx
        use_litellm_proxy = os.getenv("USE_LITELLM_PROXY_FLAG", "false").lower() == "true"
        if not use_litellm_proxy:
            return False
        proxy_url = os.getenv("LITELLM_ENDPOINT", "http://localhost:8080").rstrip("/")
        url = f"{proxy_url}/guardrail-providers"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            providers = data.get("guardrail_types", [])
            synced: dict[str, dict] = {}
            for p in providers:
                key = p.get("key", "").lower()
                if key and key != "none":
                    synced[key] = {
                        "key": key,
                        "label": p.get("label", key),
                        "description": p.get("description", ""),
                        "proxy_provider": key,
                    }
            self._types = synced
            self._synced = bool(synced)
            if synced:
                log.info(f"GuardrailRegistry synced from proxy: {list(synced.keys())}")
            else:
                log.warning("Proxy returned no guardrail providers")
            return self._synced
        except Exception as exc:
            log.error(f"Failed to load guardrail types from proxy ({url}): {exc}")
            self._types = {}
            self._synced = False
            return False

    @property
    def is_synced(self) -> bool:
        return self._synced

    def is_valid(self, key: str) -> bool:
        return key.lower() == "none" or key.lower() in self._types

    def get_proxy_provider(self, key: str) -> str:
        entry = self._types.get(key.lower())
        return entry["proxy_provider"] if entry else key.lower()

    def get_available_types(self) -> list[dict]:
        """Return available types for frontend dropdown (includes 'none')."""
        result = [{"key": "none", "label": "None", "description": "No guardrails applied"}]
        for entry in sorted(self._types.values(), key=lambda x: x["label"]):
            result.append({"key": entry["key"], "label": entry["label"], "description": entry["description"]})
        return result

    def get_registered_keys(self) -> list[str]:
        return list(self._types.keys())

    def get_default_provider(self) -> str | None:
        """Return the first registered provider key, or ``None`` if empty."""
        keys = self.get_registered_keys()
        return keys[0] if keys else None


guardrail_registry = GuardrailRegistry()


GUARDRAIL_KEYWORDS = (
    "contentpolicyviolation", "content_policy_violation",
    "guardrail", "was flagged for:", "request blocked",
    "policy violation", "content moderation failed",
    "jailbreak", "guardrailviolation", "guardrail violation",
    "pii protection", "content_filter", "content management policy",
)

PII_KEYWORDS = (
    "request blocked", "sensitive pii", "pii entities", "pii protection",
)

MODERATION_KEYWORDS = (
    "was flagged for:", "policy violation", "content moderation failed",
    "jailbreak", "contentpolicyviolation", "content_policy_violation",
    "guardrailviolation", "guardrail violation",
    "content_filter", "content management policy",
)

ERROR_PREFIXES = (
    "Error Occurred in Executor Agent: ",
    "Error Occurred in Meta Agent: ",
    "Having error in astream ",
)

EXCEPTION_PREFIXES = (
    "litellm.BadRequestError: litellm.ContentPolicyViolationError: ",
    "litellm.ContentPolicyViolationError: ",
    "litellm.exceptions.ContentPolicyViolationError: ",
    "ContentPolicyViolationError: ",
    "GuardrailError: ",
)

TERMINATORS = (
    "', 'type'", "', \"type\"", "\nDuring task",
    "\\nDuring task", "During task with name",
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_guardrail_exception(exc: Exception) -> bool:
    """Return *True* if *exc* looks like a guardrail / content-policy violation."""

    try:
        from src.models.guardrail_aware_llm import GuardrailError
        if isinstance(exc, GuardrailError):
            return True
        cause = getattr(exc, "__cause__", None)
        if cause and isinstance(cause, GuardrailError):
            return True
    except ImportError:
        pass

    err_lower = str(exc).lower()
    return any(kw in err_lower for kw in GUARDRAIL_KEYWORDS)


def extract_guardrail_exception(exc: Exception) -> Optional["GuardrailError"]:
    """If *exc* is (or wraps) a ``GuardrailError``, return it; else ``None``."""
    try:
        from src.models.guardrail_aware_llm import GuardrailError
        if isinstance(exc, GuardrailError):
            return exc
        cause = getattr(exc, "__cause__", None)
        if cause and isinstance(cause, GuardrailError):
            return cause
    except ImportError:
        pass
    return None


def strip_guardrail_prefixes(err_str: str) -> str:
    """Strip wrapper prefixes and trailing artifacts from a guardrail error string."""
    clean = err_str
    for prefix in ERROR_PREFIXES:
        if prefix in clean:
            clean = clean.split(prefix, 1)[-1]
            break
    for exc_prefix in EXCEPTION_PREFIXES:
        if exc_prefix in clean:
            clean = clean.split(exc_prefix, 1)[-1]
            break
    if clean.startswith("Error code:"):
        for exc_prefix in (
            "litellm.ContentPolicyViolationError: ",
            "ContentPolicyViolationError: ",
        ):
            if exc_prefix in clean:
                clean = clean.split(exc_prefix, 1)[-1]
                break
    for terminator in TERMINATORS:
        idx = clean.find(terminator)
        if idx > 0:
            clean = clean[:idx]
            break
    return clean.strip().rstrip(".'\"").replace("\\n", "\n").strip()


def _extract_guardrail_detail(err_str: str) -> Optional[dict]:
    """Extract the JSON detail block from a guardrail error string, if present."""
    match = re.search(r'\[GUARDRAIL_DETAIL\](.*?)\[/GUARDRAIL_DETAIL\]', err_str, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return None


def _format_rai_moderation_detail(detail: dict) -> str:
    """Format RAI moderation detail into a readable report."""
    lines = []
    lines.append(f"**Overall Status:** {detail.get('overall_status', 'N/A')}")

    reasons = detail.get('failure_reasons', [])
    if reasons:
        lines.append(f"**Failure Reasons:** {', '.join(reasons)}")

    moderated_text = detail.get('moderated_text', '')
    if moderated_text:
        display_text = moderated_text[:100] + ('...' if len(moderated_text) > 100 else '')
        lines.append(f"**Moderated Text:** \"{display_text}\"")

    checks = detail.get('checks', [])
    if checks:
        lines.append("\n**Detailed Check Results:**")
        for check in checks:
            name = check.get('check', 'Unknown')
            result = check.get('result', 'N/A')
            icon = "FAILED" if result == "FAILED" else ("PASSED" if result == "PASSED" else result)
            lines.append(f"\n  **{name}** — {icon}")

            if 'score' in check and check['score'] != 'N/A':
                lines.append(f"    Score: {check['score']} (Threshold: {check.get('threshold', 'N/A')})")

            if 'scores' in check:
                for metric, score in check['scores'].items():
                    lines.append(f"    {metric}: {score}")
                if 'threshold' in check:
                    lines.append(f"    Threshold: {check['threshold']}")

            if 'flagged_topics' in check:
                flagged = check['flagged_topics']
                if flagged:
                    lines.append(f"    Flagged Topics (score >= {check.get('threshold', 'N/A')}):")
                    for topic, score in sorted(flagged.items(), key=lambda x: -x[1]):
                        lines.append(f"      - {topic}: {score}")
                all_scores = check.get('all_topic_scores', {})
                passed = {t: s for t, s in all_scores.items() if t not in flagged}
                if passed:
                    lines.append(f"    Passed Topics:")
                    for topic, score in sorted(passed.items()):
                        lines.append(f"      - {topic}: {score}")

            if 'words_found' in check and check['words_found']:
                lines.append(f"    Words Found: {', '.join(check['words_found'])}")

    return "\n".join(lines)


def _format_pii_detail(detail: dict) -> str:
    """Format PII protection detail into a readable report."""
    lines = []
    lines.append(f"**Overall Status:** {detail.get('overall_status', 'N/A')}")

    blocked = detail.get('blocked_entities', [])
    if blocked:
        lines.append(f"\n**Blocked PII Entities ({len(blocked)}):**")
        for ent in blocked:
            lines.append(f"  - Type: **{ent.get('type', 'N/A')}** | "
                         f"Value: {ent.get('value', 'N/A')} | "
                         f"Score: {ent.get('score', 'N/A')} | "
                         f"Position: {ent.get('position', 'N/A')}")

    configured = detail.get('entities_configured_to_block', [])
    if configured:
        lines.append(f"\n**Entities Configured to Block:** {', '.join(configured)}")

    return "\n".join(lines)


def format_guardrail_user_response(err_str: str) -> Optional[str]:
    """
    Classify a guardrail error string and return a guardrail alert message,
    or ``None`` when the string does not look like a guardrail error.

    Returns one of:
    - ``**Privacy Protection Alert** …`` for PII violations
    - ``**Content Policy Alert** …``  for moderation violations
    - ``None`` if the error is not guardrail-related
    
    If the error contains a [GUARDRAIL_DETAIL] block, a detailed report
    of all check results is included.
    """
    err_lower = err_str.lower()
    if not any(kw in err_lower for kw in GUARDRAIL_KEYWORDS):
        return None

    clean_msg = strip_guardrail_prefixes(err_str)
    # Remove the detail tag from the clean message shown to the user
    clean_msg = re.sub(r'\[GUARDRAIL_DETAIL\].*?\[/GUARDRAIL_DETAIL\]', '', clean_msg, flags=re.DOTALL).strip()

    detail = _extract_guardrail_detail(err_str)

    if any(kw in err_lower for kw in PII_KEYWORDS):
        header = f"**Privacy Protection Alert**\n\n{clean_msg}"
        footer = ("\nFor your privacy and security, please rephrase your question "
                  "without including sensitive personal information.")
        if detail and detail.get('guardrail_type') == 'pii_protection':
            return f"{header}\n\n---\n**Guardrail Check Details:**\n{_format_pii_detail(detail)}\n---\n{footer}"
        return f"{header}\n{footer}"

    header = f"**Content Policy Alert**\n\n{clean_msg}"
    footer = "\nPlease rephrase your question to comply with our content guidelines."
    if detail and detail.get('guardrail_type') == 'rai_moderation':
        return f"{header}\n\n---\n**Guardrail Check Details:**\n{_format_rai_moderation_detail(detail)}\n---\n{footer}"
    return f"{header}\n{footer}"


def get_guardrail_response_from_exception(exc: Exception) -> Optional[str]:
    """
    High-level helper: given an exception, return a guardrail alert
    message if it is a guardrail error, otherwise ``None``.
    """

    guardrail_err = extract_guardrail_exception(exc)
    if guardrail_err:
        return format_guardrail_user_response(str(guardrail_err.message))
    return format_guardrail_user_response(str(exc))


def get_guardrail_response_from_errors(error_list: list) -> Optional[str]:
    """
    Scan a list of error strings/objects and return the first guardrail-
    guardrail alert message, or ``None`` if none of them are guardrail errors.
    """
    for err in error_list:
        guardrail_message = format_guardrail_user_response(str(err))
        if guardrail_message:
            return guardrail_message
    return None


def log_guardrail_or_exception(error_msg: str, exc: Exception) -> None:
    """
    Log at *warning* level (no traceback) when the exception is guardrail-
    related, otherwise at *error* level with full traceback.
    """
    if is_guardrail_exception(exc):
        log.warning(f"Guardrail/moderation check triggered: {error_msg}")
    else:
        log.error(error_msg, exc_info=True)
