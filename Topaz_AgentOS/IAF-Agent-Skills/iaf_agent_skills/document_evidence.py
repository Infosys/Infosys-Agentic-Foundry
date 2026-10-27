"""
Document Evidence Layer — Evidence Collector

Captures file reads that occur during agent tool execution and builds an
evidence bundle that travels with the agent response. Works for all
execution paths: WebSocket chat, REST API, cron, queue.

The collector hooks into _run_with_stream_intercept at the tool boundary
so it sees full output BEFORE any truncation happens downstream.
"""

import hashlib
import hmac
import logging
import os
import re
import shlex
import time
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlencode

from .runtime_bridge import default_agent_id, default_tenant_id

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.1"

_INFRA_PATTERNS = [
    r"[/\\]?skills[/\\].*[/\\]SKILL\.md$",
    r"(?:^|[/\\])SKILL\.md$",
    r"[/\\]taxonomy[/\\]",
    r"[/\\]memory[/\\]",
    r"[/\\]knowledge[/\\]",
    r"[/\\]\.git[/\\]",
    r"__pycache__",
    r"\.pyc$",
    r"\.jsonl$",
    r"config\.env$",
    r"[/\\]logs[/\\]",
]

_READ_COMMANDS = {"cat", "head", "tail", "less", "grep", "awk", "sed"}

# Commands where the first positional argument is a PATTERN, not a path.
# For these, path extraction starts from the second positional argument.
_PATTERN_FIRST_COMMANDS = {"grep", "egrep", "fgrep", "rg", "ag", "awk", "sed"}

# ── Regex to find document paths inside any command string (e.g. python3 -c) ─
# Catches: md.convert('/local/file.docx'), open('/local/file.pdf'), etc.
_QUOTED_DOC_PATH_RE = re.compile(
    r"""['"]((?:[^'"]*[/\\])[^'"]*\.(?:pdf|docx|doc|pptx|ppt|xlsx|xls|xlsm|csv|md|txt|json|yaml|yml|html|xml|png|jpg|jpeg))['"]\s*""",
    re.IGNORECASE,
)
_TRUNCATED_OUTPUT_RE = re.compile(
    "\\[Result truncated:\\s*(\\d+)\\s*chars total\\s*(?:\\u2014|-)\\s*"
    "full output saved to\\s+([^\\]\\s]+)\\]\\s*"
    "Preview \\(first \\d+ chars\\):\\s*(.*?)\\n\\.\\.\\.",
    re.DOTALL,
)

_HIGHLIGHT_STOPWORDS = {
    "about", "action", "actions", "after", "agent", "answer", "artifact",
    "based", "call", "check", "content", "could", "data", "document",
    "documents", "evidence", "file", "files", "found", "from", "given",
    "highlight", "highlights", "item", "items", "meeting", "mention",
    "mentioned", "please", "planning", "query", "reference", "referenced",
    "references", "result", "results", "seen", "source", "summary",
    "summarize", "target", "text", "that", "there", "this", "tool",
    "transcript", "using", "what", "when", "where", "with", "would", "yes",
    "connect", "archive", "local", "markitdown", "python", "print",
}

_MIME_MAP = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":  "application/vnd.ms-excel",
    ".csv":  "text/csv",
    ".md":   "text/markdown",
    ".txt":  "text/plain",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml":  "application/yaml",
    ".html": "text/html",
    ".xml":  "application/xml",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
}



def _is_infrastructure(path: str) -> bool:
    for pattern in _INFRA_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return True
    return False


def _source_fingerprint(source_uri: str) -> str:
    """Stable hash for grouping repeated reads of the same source."""
    return hashlib.sha256(source_uri.encode()).hexdigest()


def _doc_id(source_uri: str) -> str:
    """Backward-compatible document id used by the existing chat UI."""
    return hashlib.sha256(source_uri.encode()).hexdigest()[:16]


def _content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8", errors="replace")).hexdigest()


def _mime_type(path: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    return _MIME_MAP.get(ext, "application/octet-stream")


def _artifact_type_from_mime(mime_type: str) -> str:
    if mime_type == "application/pdf":
        return "pdf"
    if (
        mime_type in ("application/msword", "application/vnd.ms-powerpoint")
        or "wordprocessingml" in mime_type
        or "presentationml" in mime_type
    ):
        return "document"
    if mime_type in ("text/csv", "application/vnd.ms-excel") or "spreadsheet" in mime_type:
        return "table"
    if mime_type == "application/json":
        return "json"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("text/") or mime_type in ("application/xml", "application/yaml"):
        return "text"
    return "binary"


def _is_read_command(command: str) -> bool:
    if not command or not command.strip():
        return False
    cmd = command.strip().split()[0].split("/")[-1]
    return cmd in _READ_COMMANDS


def _is_document_path(token: str) -> bool:
    """
    Return True only if a token looks like a path to a real document file.
    Rejects: glob patterns (*.docx), bare directories (/local), flag values.
    """
    if not token:
        return False
    # Reject glob patterns
    if '*' in token or '?' in token or '[' in token:
        return False
    p = PurePosixPath(token)
    ext = p.suffix.lower()
    # Must have a known file extension — bare directories have no suffix
    if not ext or ext not in _MIME_MAP:
        return False
    return True


def _extract_paths_from_command(command: str) -> list:
    """
    Heuristically extract file paths from a shell command.
    Handles: cat /path/file.pdf, head -n 50 /path/file.md,
             grep "pattern" /path/file.csv (skips the pattern arg).
    Rejects: glob patterns, directory paths, flag value arguments.
    """
    clean = re.split(r'[|>&;]', command)[0].strip()
    try:
        tokens = shlex.split(clean)  # correctly handles quoted paths with spaces
    except ValueError:
        tokens = clean.split()       # fallback for unclosed quotes
    if not tokens:
        return []

    cmd_name = tokens[0].split("/")[-1]
    pattern_first = cmd_name in _PATTERN_FIRST_COMMANDS

    paths = []
    skip_next = False
    positional_count = 0  # positional (non-flag) args seen so far

    for i, token in enumerate(tokens):
        if i == 0:
            continue  # command name itself
        if skip_next:
            skip_next = False
            continue
        if token.startswith('-'):
            # Single-letter flag that takes a value (e.g. -n 50, -f file)
            if re.match(r'^-[a-zA-Z]$', token):
                skip_next = True
            continue

        clean_token = token.strip("'\"")
        positional_count += 1

        # For grep/awk/sed the first positional arg is the pattern — skip it
        if pattern_first and positional_count == 1:
            continue

        if _is_document_path(clean_token):
            paths.append(clean_token)

    return paths


def _extract_tool_search_terms(tool_input: str) -> list[str]:
    """Extract explicit grep/awk/sed search patterns from tool input."""
    if not tool_input:
        return []
    clean = re.split(r'[|>&;]', tool_input)[0].strip()
    try:
        tokens = shlex.split(clean)
    except ValueError:
        tokens = clean.split()
    if not tokens:
        return []
    cmd_name = tokens[0].split("/")[-1]
    if cmd_name not in _PATTERN_FIRST_COMMANDS:
        return []
    terms = []
    skip_next = False
    for i, token in enumerate(tokens[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            # grep -e pattern / sed -f file style options take a value; most
            # other flags like -n/-i do not.
            if token in ("-e", "--regexp", "-f", "--file"):
                skip_next = False if token in ("-e", "--regexp") else True
            continue
        if _is_document_path(token):
            continue
        terms.append(token)
        break
    return terms


def _highlight_candidates(response_text: str, *, source: str = "response") -> list[tuple[int, str, str]]:
    """Return deterministic candidate terms with priority and reason."""
    text = response_text or ""
    candidates: list[tuple[int, str, str]] = []

    def add(priority: int, term: str, reason: str):
        clean = re.sub(r"\s+", " ", (term or "").strip(" `*_.,:;!?()[]{}<>\"'"))
        if clean:
            candidates.append((priority, clean, reason))

    for m in re.finditer(r"""[`"']([^`"']{3,80})[`"']""", text):
        add(0, m.group(1), "quoted_or_backticked_term")

    for m in re.finditer(r"\b[A-Z]{2,}[-_][A-Z0-9][A-Z0-9_-]{1,}\b", text):
        add(1, m.group(), "business_reference_code")
    for m in re.finditer(r"\b[A-Z]{1,5}\d{1,5}[A-Z0-9_-]*\b", text):
        add(1, m.group(), "mixed_alphanumeric_code")
    for m in re.finditer(r"\b[A-Za-z]+(?:[A-Z][a-z0-9]+)+\b", text):
        add(1, m.group(), "camel_case_or_product_token")
    for m in re.finditer(r"\b[A-Z0-9]{4,}(?:[-_][A-Z0-9]{2,})*\b", text):
        add(1, m.group(), "uppercase_business_token")

    for m in re.finditer(r"[$EURINR]?\s*\d[\d,]*(?:\.\d+)?", text):
        add(2, m.group(), "numeric_or_amount")

    # Proper nouns / names. Response text only contributes multi-word names.
    # Single-word entity highlights should come from query/search/quotes/codes.
    for m in re.finditer(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,3}\b", text):
        term = m.group()
        word_count = len(term.split())
        if word_count > 1:
            add(3, term, "proper_noun_or_name")
        elif source == "query":
            add(0, term, "query_entity_term")

    # Important single words are allowed from the user's query only. Response
    # prose is too noisy for this class.
    if source == "query":
        for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b", text):
            add(0, m.group(), "query_keyword")

    return candidates


def _is_highlight_candidate(term: str, reason: str) -> bool:
    clean = (term or "").strip()
    if not clean:
        return False
    lowered = clean.lower()
    if lowered in _HIGHLIGHT_STOPWORDS:
        return False
    if len(clean) < 4 and not re.search(r"\d", clean):
        return False
    if reason == "query_keyword" and len(clean) < 4:
        return False
    if re.fullmatch(r"\d{1,2}", clean):
        return False
    return True


def _find_highlight_occurrences(content: str, term: str) -> tuple[int, list[tuple[int, int, str]]]:
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)
    matches = [(m.start(), m.end(), content[m.start():m.end()]) for m in pattern.finditer(content or "")]
    return len(matches), matches[:3]


def _dedupe_highlights(highlights: list) -> list:
    deduped = []
    seen = set()
    for highlight in highlights:
        key = (str(highlight.get("term", "")).lower(), highlight.get("char_start"), highlight.get("char_end"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(highlight)
    return deduped


def _configured_highlight_enabled(highlight_config: dict | None) -> bool:
    if not isinstance(highlight_config, dict) or not highlight_config:
        return False
    return highlight_config.get("enabled", True) is not False


def _configured_highlight_reason(entry: dict, default: str) -> str:
    reason = str(entry.get("reason") or default).strip()
    return reason[:80] if reason else default


def _extract_configured_highlights(content: str, highlight_config: dict | None) -> list:
    """Apply optional SKILL.md evidence_highlights rules."""
    if not content or not _configured_highlight_enabled(highlight_config):
        return []

    highlights = []

    for raw_entry in (highlight_config or {}).get("terms", []) or []:
        if isinstance(raw_entry, str):
            term = raw_entry
            reason = "configured_term"
        elif isinstance(raw_entry, dict):
            term = str(raw_entry.get("term") or raw_entry.get("text") or "").strip()
            reason = _configured_highlight_reason(raw_entry, "configured_term")
        else:
            continue
        if not term or not _is_highlight_candidate(term, reason):
            continue
        _, occurrences = _find_highlight_occurrences(content, term)
        for start, end, exact_text in occurrences:
            highlights.append({
                "term": exact_text,
                "char_start": start,
                "char_end": end,
                "reason": reason,
            })
            if len(highlights) >= 20:
                return _dedupe_highlights(highlights)[:20]

    for raw_entry in (highlight_config or {}).get("patterns", []) or []:
        if isinstance(raw_entry, str):
            pattern_text = raw_entry
            reason = "configured_pattern"
            name = ""
        elif isinstance(raw_entry, dict):
            pattern_text = str(raw_entry.get("regex") or raw_entry.get("pattern") or "").strip()
            reason = _configured_highlight_reason(raw_entry, "configured_pattern")
            name = str(raw_entry.get("name") or "").strip()
        else:
            continue
        if not pattern_text or len(pattern_text) > 300:
            continue
        try:
            pattern = re.compile(pattern_text, re.IGNORECASE)
        except re.error as exc:
            logger.warning("Invalid evidence_highlights regex %r ignored: %s", name or pattern_text[:40], exc)
            continue
        for match in pattern.finditer(content):
            exact_text = match.group(0).strip()
            if not exact_text or not _is_highlight_candidate(exact_text, reason):
                continue
            highlights.append({
                "term": exact_text,
                "char_start": match.start(),
                "char_end": match.end(),
                "reason": reason,
            })
            if len(highlights) >= 20:
                return _dedupe_highlights(highlights)[:20]

    return _dedupe_highlights(highlights)[:20]


def _extract_llm_highlight_terms(*, highlight_config: dict | None = None, **_kwargs) -> list[str]:
    """
    Placeholder for future optional LLM-suggested evidence terms.

    It intentionally returns no terms today. A future implementation must only
    run when explicitly enabled in SKILL.md/config and must validate terms
    against evidence text before returning them.
    """
    llm_cfg = (highlight_config or {}).get("llm_suggestions") or {}
    if not isinstance(llm_cfg, dict) or llm_cfg.get("enabled") is not True:
        return []
    logger.info("LLM evidence highlight suggestions are configured but not implemented; skipping.")
    return []


def _extract_highlight_terms(
    response_text: str,
    content: str,
    query_text: str = "",
    tool_input: str = "",
    highlight_config: dict | None = None,
) -> list:
    """
    Find terms present in BOTH the agent response AND the document content.
    Captures: currency amounts, numeric codes, reference numbers, quoted strings.
    Returns list of {term, char_start, char_end, reason}.
    """
    configured_enabled = _configured_highlight_enabled(highlight_config)
    if not content or (not response_text and not configured_enabled):
        return []

    highlights = _extract_configured_highlights(content, highlight_config) if configured_enabled else []
    seen_terms = {str(h.get("term", "")).lower() for h in highlights if h.get("term")}
    candidates = []
    for term in _extract_tool_search_terms(tool_input):
        candidates.append((0, term, "tool_search_term"))
    candidates.extend(_highlight_candidates(query_text, source="query"))
    if response_text:
        candidates.extend(_highlight_candidates(response_text, source="response"))
    for term in _extract_llm_highlight_terms(highlight_config=highlight_config):
        candidates.append((4, term, "llm_suggested_term"))
    candidates = sorted(candidates, key=lambda item: item[0])

    for priority, term, reason in candidates:
        term_key = term.lower()
        if term_key in seen_terms or not _is_highlight_candidate(term, reason):
            continue
        if any(term_key != accepted and term_key in accepted for accepted in seen_terms):
            continue
        occurrence_count, occurrences = _find_highlight_occurrences(content, term)
        if occurrence_count == 0:
            continue
        # Very frequent prose terms create noisy yellow wash. Keep codes/numbers
        # because repeated business identifiers can still be useful.
        if occurrence_count > 20 and priority >= 3:
            continue
        for start, end, exact_text in occurrences:
            highlights.append({
                "term": exact_text,
                "char_start": start,
                "char_end": end,
                "reason": reason,
            })
        seen_terms.add(term_key)
        if len(highlights) >= 20:
            break

    return _dedupe_highlights(highlights)[:20]  # cap per document


def _is_error_output(content: str) -> bool:
    stripped = (content or "").lstrip()
    return (
        stripped.startswith("Error [")
        or stripped.startswith("Error:")
        or stripped.startswith("Traceback (most recent call last):")
        or stripped.startswith("Exception:")
        or " is not a text file." in stripped
    )


def _looks_like_raw_pdf_scrape(content: str) -> bool:
    """Detect binary/PDF object dumps masquerading as extracted text."""
    if not content:
        return False
    sample = content[:8192]
    markers = (
        "StructTreeRoot",
        "ViewerPreferences",
        "FontDescriptor",
        "DescendantFonts",
        "CIDSystemInfo",
        "CDEFGHIJSTUVWXYZ",
    )
    marker_hits = sum(1 for marker in markers if marker in sample)
    if marker_hits >= 2:
        return True
    if re.search(r"([A-Z])\1{80,}", sample):
        return True
    object_ref_count = len(re.findall(r"\b\d+\s+0\s+R\b", sample))
    return object_ref_count >= 12 and marker_hits >= 1


def _parse_truncated_output(content: str) -> dict:
    match = _TRUNCATED_OUTPUT_RE.search(content or "")
    if not match:
        return {}
    return {
        "observed_chars": int(match.group(1)),
        "saved_output_path": match.group(2).strip(),
        "preview": match.group(3).strip(),
    }


def _build_serve_url(path: str, tenant_id: str, agent_id: str, user_id: str) -> str:
    resolved_tenant = tenant_id or default_tenant_id()
    resolved_agent = agent_id or default_agent_id()
    resolved_user = user_id or "demo"
    params: dict[str, object] = {
        "path": path,
        "agent_id": resolved_agent,
        "user_id": resolved_user,
        "tenant_id": resolved_tenant,
    }
    signing_secret = os.getenv("FILE_URL_SIGNING_SECRET", "").strip()
    if signing_secret:
        try:
            ttl = max(30, min(int(os.getenv("FILE_URL_TTL_SECONDS", "300")), 3600))
        except ValueError:
            ttl = 300
        expires = int(time.time()) + ttl
        payload = "\n".join(
            (resolved_tenant, resolved_agent, resolved_user, path, str(expires))
        ).encode("utf-8")
        params["expires"] = expires
        params["signature"] = hmac.new(
            signing_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    return f"/api/files/serve?{urlencode(params)}"


def _build_evidence_urls(trace_id: str, evidence_id: str) -> dict:
    if not trace_id or not evidence_id:
        return {"content_url": "", "text_url": ""}
    base = f"/api/evidence/{trace_id}/items/{evidence_id}"
    return {
        "content_url": f"{base}/content",
        "text_url": f"{base}/text",
    }



class EvidenceCollector:
    """
    Attached to an AgentSkill instance for one run().

    Lifecycle:
        1. agent.run() creates self._evidence_collector = EvidenceCollector()
        2. _run_with_stream_intercept calls record_tool_call() on each agent chunk
        3. _run_with_stream_intercept calls record_tool_result() on each tools chunk
           — this is the full output BEFORE downstream truncation
        4. After run() has the response string, caller calls get_bundle(response)
        5. bundle stored as agent._evidence_bundle, included in response payload
    """

    def __init__(self):
        self._pending: dict = {}   # tool_call_id → {name, args}
        self._reads: list = []
        self._items: list = []
        self._start = time.time()

    def record_tool_call(self, tool_call_id: str, tool_name: str, tool_args: dict):
        """Called when agent chunk arrives — store args by id for later matching."""
        if tool_call_id:
            self._pending[tool_call_id] = {"name": tool_name, "args": tool_args}

    def record_tool_result(self, tool_call_id: str, tool_name: str, content: str):
        """
        Called when tools chunk arrives — full output before any truncation.
        Captures shell reads via two strategies:
          1. Classic read commands (cat/head/tail/grep…): parsed with shlex
          2. Any command containing a quoted document path (python3 -c, etc.)
        """
        if tool_name not in ("shell", "bash", "run_shell", "shell_tool"):
            return

        pending = self._pending.pop(tool_call_id, None)
        if not pending:
            return

        command = pending.get("args", {}).get("command", "")
        if not command:
            return

        # Strategy 1: known read commands — use structured parser
        if _is_read_command(command):
            paths = _extract_paths_from_command(command)
        else:
            # Strategy 2: any command — regex-scan for quoted document paths
            # Catches python3 -c "md.convert('/local/file.docx')", open(), etc.
            paths = [m.group(1) for m in _QUOTED_DOC_PATH_RE.finditer(command)]

        if not paths:
            return

        content_str = content if isinstance(content, str) else str(content)

        # Skip output that looks like a directory listing (each non-empty line
        # is an absolute path) — this is find/ls output, not document content.
        lines = [l for l in content_str.splitlines() if l.strip()]
        if lines and sum(1 for l in lines if l.strip().startswith('/')) / len(lines) > 0.7:
            return

        base_has_error = _is_error_output(content_str)
        truncated_output = _parse_truncated_output(content_str)

        for path in paths:
            if _is_infrastructure(path):
                continue
            evidence_id = str(uuid.uuid4())
            fingerprint = _source_fingerprint(path)
            now = datetime.now(timezone.utc).isoformat()
            mime_type = _mime_type(path)
            has_error = base_has_error or (
                mime_type == "application/pdf" and _looks_like_raw_pdf_scrape(content_str)
            )
            if has_error:
                observed_chars = 0
                excerpt = ""
                content_hash = ""
                truncated = False
            elif truncated_output:
                observed_chars = truncated_output["observed_chars"]
                excerpt = truncated_output["preview"][:8192]
                content_hash = _content_hash(excerpt)
                truncated = True
            else:
                observed_chars = len(content_str)
                excerpt = content_str[:8192]  # up to 8 KB for display
                content_hash = _content_hash(content_str)
                truncated = observed_chars > len(excerpt)
            error_text = (
                content_str[:2000]
                if base_has_error
                else "Output appears to be raw PDF/binary data, not extracted text."
                if has_error
                else ""
            )
            logger.debug("Evidence captured: %s (cmd=%s, %d chars)", path, command[:60], observed_chars)
            self._reads.append({
                "evidence_id":    evidence_id,
                "doc_id":         _doc_id(path),
                "source_fingerprint": fingerprint,
                "content_hash":   content_hash,
                "content_strategy": "resolve_on_demand",
                "source_uri":     path,
                "source_type":    "local",
                "display_name":   PurePosixPath(path).name,
                "mime_type":      mime_type,
                "command":        command,
                "observed_chars": observed_chars,
                "excerpt":        excerpt,
                "read_at":        now,
                "has_error":      has_error,
                "error":          error_text,
                "saved_output_path": truncated_output.get("saved_output_path", ""),
            })
            metadata = {}
            if truncated_output:
                metadata["saved_output_path"] = truncated_output.get("saved_output_path", "")
                metadata["saved_output_chars"] = truncated_output.get("observed_chars", 0)
            self._items.append({
                "evidence_id":    evidence_id,
                "source_fingerprint": fingerprint,
                "content_hash":   content_hash,
                "content_strategy": "resolve_on_demand",
                "source_type":    "local",
                "artifact_type":  _artifact_type_from_mime(mime_type),
                "source_uri":     path,
                "display_name":   PurePosixPath(path).name,
                "mime_type":      mime_type,
                "metadata":       metadata,
                "provenance": {
                    "tool": "shell",
                    "input": command,
                    "read_at": now,
                    "has_error": has_error,
                    "error": error_text,
                    "saved_output_path": truncated_output.get("saved_output_path", ""),
                },
                "extracted_text": {
                    "available": bool(excerpt) and not has_error,
                    "excerpt": excerpt,
                    "truncated": truncated,
                    "observed_chars": observed_chars,
                },
                "structured_data": {},
                "highlights": [],
            })

    def record_sql_result(self, query: str, result_text: str, database: str = "",
                          metadata: Optional[dict] = None):
        """Capture an ephemeral SQL result as evidence."""
        self._record_ephemeral(
            source_type="db",
            artifact_type="table",
            source_uri=f"db://{database or 'default'}",
            display_name=database or "SQL Result",
            mime_type="text/plain",
            tool="run_sql_query",
            tool_input=query,
            content=result_text or "",
            metadata={"database": database, **(metadata or {})},
        )

    def record_api_response(self, method: str, url: str, response_text: str,
                            status_code: Optional[int] = None,
                            metadata: Optional[dict] = None):
        """Capture an ephemeral API response as evidence."""
        self._record_ephemeral(
            source_type="api",
            artifact_type="json" if (response_text or "").lstrip().startswith(("{", "[")) else "text",
            source_uri=f"api://{method.upper()} {url}",
            display_name=f"{method.upper()} {url}",
            mime_type="application/json" if (response_text or "").lstrip().startswith(("{", "[")) else "text/plain",
            tool="api_call",
            tool_input=f"{method.upper()} {url}",
            content=response_text or "",
            metadata={"status_code": status_code, **(metadata or {})},
        )

    def record_memory_hit(self, query: str, result_text: str, metadata: Optional[dict] = None):
        """Capture memory/knowledge retrieval as evidence."""
        self._record_ephemeral(
            source_type="memory",
            artifact_type="memory",
            source_uri=f"memory://{uuid.uuid4()}",
            display_name="Memory Lookup",
            mime_type="text/plain",
            tool="query_memory",
            tool_input=query,
            content=result_text or "",
            metadata=metadata or {},
        )

    def _record_ephemeral(self, source_type: str, artifact_type: str,
                          source_uri: str, display_name: str, mime_type: str,
                          tool: str, tool_input: str, content: str,
                          metadata: Optional[dict] = None):
        """Record evidence whose original payload must be stored at capture time."""
        evidence_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        content_str = content if isinstance(content, str) else str(content)
        excerpt = content_str[:8192]
        self._items.append({
            "evidence_id": evidence_id,
            "source_fingerprint": _source_fingerprint(source_uri),
            "content_hash": _content_hash(content_str),
            "content_strategy": "stored_payload",
            "source_type": source_type,
            "artifact_type": artifact_type,
            "source_uri": source_uri,
            "display_name": display_name,
            "mime_type": mime_type,
            "metadata": metadata or {},
            "provenance": {
                "tool": tool,
                "input": tool_input,
                "read_at": now,
            },
            "extracted_text": {
                "available": bool(excerpt),
                "excerpt": excerpt,
                "truncated": len(content_str) > len(excerpt),
                "observed_chars": len(content_str),
            },
            "structured_data": {},
            "stored_payload": content_str,
            "highlights": [],
        })

    def get_bundle(self, response_text: str = "", query_text: str = "",
                   trace_id: str = "", tenant_id: str = "", agent_id: str = "",
                   user_id: str = "", execution_source: str = "chat",
                   highlight_config: dict | None = None) -> dict:
        """
        Build the final evidence bundle. Merges repeated reads of the same
        document and computes highlight term offsets from the response text.
        Returns empty dict when no business documents were read.
        """
        if not self._items and not self._reads:
            return {}

        docs: dict = {}
        for read in self._reads:
            did = read["doc_id"]
            if did not in docs:
                docs[did] = {
                    "doc_id":       did,
                    "source_uri":   read["source_uri"],
                    "source_type":  read["source_type"],
                    "display_name": read["display_name"],
                    "mime_type":    read["mime_type"],
                    "serve_url":    _build_serve_url(
                                        read["source_uri"], tenant_id,
                                        agent_id, user_id),
                    "reads":        [],
                    "excerpt":      read["excerpt"],
                    "highlights":   [],
                    "source_fingerprint": read["source_fingerprint"],
                }
            docs[did]["reads"].append({
                "evidence_id":    read["evidence_id"],
                "command":        read["command"],
                "observed_chars": read["observed_chars"],
                "read_at":        read["read_at"],
                "has_error":      read.get("has_error", False),
                "error":          read.get("error", ""),
                "saved_output_path": read.get("saved_output_path", ""),
            })
            # Keep the longest excerpt for highlight matching
            if len(read["excerpt"]) > len(docs[did]["excerpt"]):
                docs[did]["excerpt"] = read["excerpt"]

        for doc in docs.values():
            read_inputs = " ".join(read.get("command", "") for read in doc.get("reads", []))
            doc["highlights"] = _extract_highlight_terms(
                response_text, doc["excerpt"], query_text=query_text,
                tool_input=read_inputs, highlight_config=highlight_config)

        saved_output_sources = {}
        for item in self._items:
            metadata = item.get("metadata") or {}
            saved_path = metadata.get("saved_output_path") or (item.get("provenance") or {}).get("saved_output_path")
            if saved_path and item.get("source_uri"):
                saved_output_sources[saved_path] = item.get("source_uri")

        evidence_items = []
        for seq, item in enumerate(self._items, start=1):
            item_copy = dict(item)
            source_uri = item_copy.get("source_uri", "")
            derived_from = saved_output_sources.get(source_uri)
            if derived_from:
                item_copy["source_fingerprint"] = _source_fingerprint(derived_from)
            item_copy["capture_seq"] = seq
            urls = _build_evidence_urls(trace_id, item_copy["evidence_id"])
            item_copy.update(urls)
            metadata = dict(item_copy.get("metadata") or {})
            metadata.update({
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "user_id": user_id,
            })
            if derived_from:
                metadata["derived_from_source_uri"] = derived_from
                metadata["evidence_role"] = "extraction_text"
            item_copy["metadata"] = metadata
            excerpt = ((item_copy.get("extracted_text") or {}).get("excerpt") or "")
            provenance_input = (item_copy.get("provenance") or {}).get("input", "")
            item_copy["highlights"] = _extract_highlight_terms(
                response_text, excerpt, query_text=query_text,
                tool_input=provenance_input, highlight_config=highlight_config
            )
            # The payload is persisted by the Studio evidence store, not shipped
            # in every chat response.
            item_copy.pop("stored_payload", None)
            evidence_items.append(item_copy)

        source_items_by_uri = {
            item.get("source_uri"): item
            for item in evidence_items
            if item.get("source_uri") and (item.get("metadata") or {}).get("evidence_role") != "extraction_text"
        }
        for item in evidence_items:
            metadata = item.get("metadata") or {}
            source_uri = metadata.get("derived_from_source_uri")
            if not source_uri or not item.get("highlights"):
                continue
            source_item = source_items_by_uri.get(source_uri)
            if not source_item:
                continue
            source_item["highlights"] = _dedupe_highlights(
                (source_item.get("highlights") or []) + (item.get("highlights") or [])
            )[:20]

        return {
            "schema_version":   SCHEMA_VERSION,
            "trace_id":         trace_id,
            "tenant_id":        tenant_id,
            "agent_id":         agent_id,
            "user_id":          user_id,
            "execution_source": execution_source,
            "documents":        list(docs.values()),
            "evidence_items":   evidence_items,
            "source_documents_count": len(docs),
            "evidence_items_count": len(evidence_items),
            "generated_at":     datetime.now(timezone.utc).isoformat(),
        }
