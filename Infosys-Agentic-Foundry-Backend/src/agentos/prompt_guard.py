# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Prompt Injection Guard — Detect and block adversarial queries before LLM execution.

Provides a configurable, rule-based prompt injection detector that can be
registered as a ``before_llm`` hook.  Catches common attack families:

  * Role hijacking  (``"ignore previous instructions"``)
  * System-prompt exfiltration (``"repeat your system prompt"``)
  * Delimiter injection (markdown/XML delimiters used to escape context)
  * Encoding evasion (base64 commands, Unicode tricks)
  * Tool abuse prompts (``"call os.system"``)

Design:
  * Lightweight regex scan — zero LLM round-trips, <1 ms per query.
  * Configurable threshold via ``PROMPT_GUARD_THRESHOLD`` (0-100).
  * Set ``PROMPT_GUARD_MODE=block`` to raise ``PromptInjectionError``
    or ``PROMPT_GUARD_MODE=log`` to log-only (default: ``block``).
"""

import os
import re
import time
import threading
import unicodedata
from typing import List, Tuple, Optional

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration via environment
# ---------------------------------------------------------------------------

PROMPT_GUARD_THRESHOLD = int(os.getenv("PROMPT_GUARD_THRESHOLD", "20"))
PROMPT_GUARD_MODE = os.getenv("PROMPT_GUARD_MODE", "block").lower()  # "block" or "log"
PROMPT_GUARD_ENABLED = os.getenv("PROMPT_GUARD_ENABLED", "true").lower() in ("true", "1", "yes")


class PromptInjectionError(Exception):
    """Raised when a prompt injection attack is detected and mode is 'block'."""
    pass


# ---------------------------------------------------------------------------
# Pattern definitions  (pattern_regex, weight, label)
# ---------------------------------------------------------------------------

_PATTERNS: List[Tuple[re.Pattern, int, str]] = [
    # --- Role hijacking ---
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?|context)", re.I), 30, "role_hijack"),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior|above)?.*?(instructions?|rules?|constraints?)", re.I), 30, "role_hijack"),
    (re.compile(r"forget\s+(everything|all|your|the)\s+(previous|prior)?.*?(instructions?|rules?|training)", re.I), 25, "role_hijack"),
    (re.compile(r"you\s+are\s+now\s+(DAN|a\s+different|an?\s+unrestricted|an?\s+evil)", re.I), 35, "role_hijack"),
    (re.compile(r"(entering|switch\s+to|activate)\s+(developer|admin|god|root|sudo|jailbreak)\s+mode", re.I), 35, "role_hijack"),
    (re.compile(r"new\s+instructions?\s*:", re.I), 20, "role_hijack"),
    (re.compile(r"override\s+(your|all|the|system)\s+(safety|rules?|instructions?|guidelines?)", re.I), 30, "role_hijack"),

    # --- System prompt exfiltration ---
    (re.compile(r"(repeat|show|print|display|reveal|output|echo)\s+(your|the)?\s*(system\s+prompt|instructions?|initial\s+prompt|hidden\s+prompt)", re.I), 30, "exfiltration"),
    (re.compile(r"what\s+(are|is|were)\s+your\s+(original|system|initial|hidden)\s+(instructions?|prompt|rules?)", re.I), 25, "exfiltration"),
    (re.compile(r"(copy|paste|dump)\s+(the\s+)?(entire\s+)?system\s+(prompt|message|instructions?)", re.I), 30, "exfiltration"),

    # --- Delimiter injection ---
    (re.compile(r"```\s*system", re.I), 20, "delimiter_inject"),
    (re.compile(r"<\s*/?\s*system\s*>", re.I), 20, "delimiter_inject"),
    (re.compile(r"\[SYSTEM\]", re.I), 15, "delimiter_inject"),
    (re.compile(r"<<\s*SYS\s*>>", re.I), 15, "delimiter_inject"),
    (re.compile(r"###\s*(SYSTEM|INSTRUCTION|ADMIN)", re.I), 15, "delimiter_inject"),

    # --- Encoding evasion ---
    (re.compile(r"base64\s*:\s*[A-Za-z0-9+/=]{20,}", re.I), 20, "encoding_evasion"),
    (re.compile(r"eval\s*\(\s*atob\s*\(", re.I), 25, "encoding_evasion"),
    (re.compile(r"\\u0073\\u0079\\u0073\\u0074\\u0065\\u006d", re.I), 25, "encoding_evasion"),  # "system" in unicode escapes

    # --- Tool/code abuse ---
    (re.compile(r"(call|run|execute|use)\s+os\.(system|popen|exec)", re.I), 25, "tool_abuse"),
    (re.compile(r"import\s+subprocess", re.I), 15, "tool_abuse"),
    (re.compile(r"(curl|wget|nc|netcat)\s+.*(http|ftp|tcp)", re.I), 15, "tool_abuse"),
    (re.compile(r"__import__\s*\(", re.I), 20, "tool_abuse"),

    # --- Multi-turn manipulation ---
    (re.compile(r"(pretend|act\s+as\s+if|assume|imagine)\s+(that\s+)?(you\s+)?(are|have|were)\s+(not\s+)?(an?\s+)?(restricted|filtered|safe|bound|constrained)", re.I), 25, "manipulation"),
    (re.compile(r"(do\s+not|don'?t)\s+(follow|obey|respect|apply)\s+(your|the|any)\s+(rules?|restrictions?|guidelines?|safety)", re.I), 30, "manipulation"),
]


# ---------------------------------------------------------------------------
# Metrics (thread-safe counters)
# ---------------------------------------------------------------------------

class _GuardMetrics:
    """Thread-safe counters for prompt guard telemetry."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_scans = 0
        self.total_blocked = 0
        self.total_flagged = 0
        self.by_category: dict = {}

    def record_scan(self, blocked: bool, categories: List[str]):
        with self._lock:
            self.total_scans += 1
            if blocked:
                self.total_blocked += 1
            elif categories:
                self.total_flagged += 1
            for cat in categories:
                self.by_category[cat] = self.by_category.get(cat, 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_scans": self.total_scans,
                "total_blocked": self.total_blocked,
                "total_flagged": self.total_flagged,
                "by_category": dict(self.by_category),
            }


guard_metrics = _GuardMetrics()


# ---------------------------------------------------------------------------
# Text normalisation helpers — defeat evasion via Unicode tricks, leetspeak,
# zero-width characters, and homoglyphs.
# ---------------------------------------------------------------------------

# Zero-width / invisible characters to strip
_ZERO_WIDTH_RE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f"
    r"\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069]+"
)

# Leetspeak mapping (common substitutions)
_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "@": "a", "$": "s", "!": "i", "+": "t",
})


def _normalise_text(text: str) -> str:
    """Apply layered normalisation to defeat evasion techniques.

    1. Unicode NFKC normalisation (homoglyphs / confusables).
    2. Strip zero-width / invisible characters.
    3. Strip non-ASCII letters that survived NFKC (e.g. Cyrillic lookalikes).
    4. Leetspeak substitution.
    """
    # Step 1: NFKC normalise
    text = unicodedata.normalize("NFKC", text)

    # Step 2: Strip zero-width / invisible chars
    text = _ZERO_WIDTH_RE.sub("", text)

    # Step 3: Replace non-ASCII letters with closest ASCII equivalent,
    #         or drop them if they have no ASCII decomposition.
    cleaned_chars = []
    for ch in text:
        if ord(ch) < 128:
            cleaned_chars.append(ch)
        elif unicodedata.category(ch).startswith("L"):
            # Try to get an ASCII equivalent via decomposition
            decomp = unicodedata.decomposition(ch)
            if decomp:
                # First code point of decomposition is usually the base char
                base = decomp.split()[0].lstrip("<").rstrip(">")
                try:
                    cleaned_chars.append(chr(int(base, 16)))
                except (ValueError, OverflowError):
                    cleaned_chars.append(ch)
            else:
                # No decomposition — keep as-is (will still be caught by regex)
                cleaned_chars.append(ch)
        else:
            cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    # Step 4: Leetspeak substitution
    text = text.translate(_LEET_MAP)

    return text


# ---------------------------------------------------------------------------
# Core scan function
# ---------------------------------------------------------------------------

def scan_prompt(text: str) -> Tuple[int, List[Tuple[str, int, str]]]:
    """Scan *text* for injection patterns.

    Returns ``(risk_score, matches)`` where *matches* is a list of
    ``(label, weight, matched_text)`` tuples.

    Risk score is the sum of matched pattern weights (capped at 100).
    """
    if not text:
        return 0, []

    # Apply layered normalisation to defeat evasion
    text = _normalise_text(text)

    matches: List[Tuple[str, int, str]] = []
    for pattern, weight, label in _PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append((label, weight, m.group()[:60]))

    score = min(sum(w for _, w, _ in matches), 100)
    return score, matches


def check_prompt(query: str) -> dict:
    """Full check: scan + enforce mode.

    Returns a dict with ``allowed``, ``risk_score``, ``matches``, ``mode``.
    Raises ``PromptInjectionError`` if mode is ``block`` and score >= threshold.
    """
    if not PROMPT_GUARD_ENABLED:
        return {"allowed": True, "risk_score": 0, "matches": [], "mode": "disabled"}

    score, matches = scan_prompt(query)
    categories = list({label for label, _, _ in matches})
    blocked = score >= PROMPT_GUARD_THRESHOLD and PROMPT_GUARD_MODE == "block"

    guard_metrics.record_scan(blocked, categories)

    result = {
        "allowed": not blocked,
        "risk_score": score,
        "matches": [(lbl, w, txt) for lbl, w, txt in matches],
        "mode": PROMPT_GUARD_MODE,
    }

    if matches:
        match_summary = ", ".join(f"{lbl}({w})" for lbl, w, _ in matches)
        if blocked:
            log.warning(
                f"[PromptGuard] BLOCKED query (score={score}, threshold={PROMPT_GUARD_THRESHOLD}): "
                f"{match_summary} | query='{query[:100]}'"
            )
            raise PromptInjectionError(
                f"Query blocked by prompt injection guard (risk_score={score}). "
                f"Matched patterns: {match_summary}"
            )
        else:
            log.info(
                f"[PromptGuard] Flagged query (score={score}, threshold={PROMPT_GUARD_THRESHOLD}): "
                f"{match_summary}"
            )

    return result


# ---------------------------------------------------------------------------
# Hook integration — register as before_llm / on_agent_start hooks
# ---------------------------------------------------------------------------

def create_prompt_guard_hook(runner):
    """Register prompt injection guard hooks on the given HookRunner.

    Registers:
      - ``on_agent_start`` hook at priority 10 (runs before logging hooks)
        to scan the raw user query.
    """
    from src.agentos.hook_runner import ToolBlockedError

    @runner.on_agent_start(priority=10)
    def _guard_on_agent_start(agent_id, session_id, query, **kw):
        """Scan the user query at agent-start time (earliest interception point)."""
        try:
            check_prompt(query)
        except PromptInjectionError:
            raise ToolBlockedError(
                f"Prompt injection detected in query. "
                f"Agent {agent_id[:12]}... blocked."
            )

    log.debug("[PromptGuard] Guard hooks registered on HookRunner")


__all__ = [
    "PromptInjectionError",
    "scan_prompt",
    "check_prompt",
    "guard_metrics",
    "create_prompt_guard_hook",
    "PROMPT_GUARD_THRESHOLD",
    "PROMPT_GUARD_MODE",
    "PROMPT_GUARD_ENABLED",
]
