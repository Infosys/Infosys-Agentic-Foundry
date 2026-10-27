#!/usr/bin/env python3
"""
Extract text from PDF/Office attachments via markitdown.

Usage:
    python3 /shared/scripts/extract_document.py '/me/uploads/file.pdf' [max_chars]

Examples:
    python3 /shared/scripts/extract_document.py '/me/uploads/report.pdf'
    python3 /shared/scripts/extract_document.py '/me/uploads/My Report.pptx' 12000

Prints extracted text to stdout (UTF-8). Exit 1 on failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_OFFICE_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".doc", ".ppt"}
# Printable path text only: no control characters and none of the Windows-reserved <>|"?*.
_PATH_ARG_RE = re.compile(r'^[^\x00-\x1f\x7f<>|"?*]{1,4096}$')


def _tenant_root() -> Path:
    """``<tenant>`` for this script, which lives at ``<tenant>/shared/scripts/``."""
    return Path(__file__).resolve().parents[2]


def _confined_input(path: str) -> Path:
    """Validate the CLI path and confine it to this tenant's tree.

    The shell tool rewrites virtual paths (/me/, /shared/, /workspace/, /users/) to real
    paths inside the tenant tree before invoking this script, so anything resolving
    outside that tree is refused.
    """
    if not isinstance(path, str) or not _PATH_ARG_RE.fullmatch(path):
        raise RuntimeError("Invalid file path argument")
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"Invalid file path argument: {exc}") from None
    if not resolved.is_relative_to(_tenant_root()):
        raise RuntimeError(f"Access denied: {path} is outside the tenant workspace")
    return Path(str(resolved).encode("utf-8").decode("utf-8"))


def _safe_text(value: str | None) -> str:
    return (value or "").strip()


def _extract_with_markitdown(path: str) -> str:
    from markitdown import MarkItDown

    result = MarkItDown().convert(path)
    text = getattr(result, "text_content", None) or getattr(result, "markdown", None)
    return _safe_text(text)


def _extract_pdf_pdfplumber(path: str) -> str:
    import pdfplumber

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = _safe_text(page.extract_text())
            if text:
                chunks.append(text)
    return "\n\n".join(chunks).strip()


def _extract_pdf_pdfminer(path: str) -> str:
    from pdfminer.high_level import extract_text

    return _safe_text(extract_text(path))


def extract_document(path: str, max_chars: int = 8000) -> tuple[str, str]:
    """Return (text, extractor_name). Raises RuntimeError when extraction fails."""
    file_path = _confined_input(path)
    if not file_path.is_file():
        raise RuntimeError(f"File not found: {path}")

    ext = file_path.suffix.lower()
    if ext not in _OFFICE_EXTENSIONS:
        raise RuntimeError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(_OFFICE_EXTENSIONS))}"
        )

    errors: list[str] = []
    resolved = str(file_path)

    try:
        text = _extract_with_markitdown(resolved)
        if text:
            return text[:max_chars], "markitdown"
        errors.append("markitdown returned empty text")
    except Exception as exc:
        errors.append(f"markitdown: {exc}")

    if ext == ".pdf":
        for name, extractor in (
            ("pdfplumber", _extract_pdf_pdfplumber),
            ("pdfminer", _extract_pdf_pdfminer),
        ):
            try:
                text = extractor(resolved)
                if text:
                    return text[:max_chars], name
                errors.append(f"{name} returned empty text")
            except Exception as exc:
                errors.append(f"{name}: {exc}")

    detail = "; ".join(errors) or "no extractor produced text"
    raise RuntimeError(
        f"Could not extract text from {file_path.name}. {detail}. "
        "If this is a scanned/image-only PDF, OCR is required."
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file_path> [max_chars]", file=sys.stderr)
        return 1

    path = sys.argv[1]
    try:
        max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    except ValueError:
        print("max_chars must be an integer", file=sys.stderr)
        return 1

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        text, method = extract_document(path, max_chars=max_chars)
        if not text:
            print(
                f"ERROR: Extraction via {method} produced no text "
                f"(file may be image-only): {path}",
                file=sys.stderr,
            )
            return 1
        print(text)
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"ERROR: Missing dependency: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
