"""Server-side document text extraction for file browser previews."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EXTRACTABLE_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".doc", ".ppt",
}


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


def extract_document(path: str | Path, max_chars: int = 8000) -> tuple[str, str]:
    """Return (text, extractor_name). Raises RuntimeError when extraction fails."""
    file_path = Path(path)
    if not file_path.is_file():
        raise RuntimeError(f"File not found: {path}")

    ext = file_path.suffix.lower()
    if ext not in EXTRACTABLE_EXTENSIONS:
        raise RuntimeError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(EXTRACTABLE_EXTENSIONS))}"
        )

    for name in ("pdfminer", "pdfplumber", "PIL", "markitdown"):
        logging.getLogger(name).setLevel(logging.WARNING)

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


def extract_file_text(
    real_path: Path,
    *,
    tenant_id: str = "company",
    max_chars: int = 8000,
) -> tuple[str, str]:
    """Return (text, extractor_name) for a file on disk."""
    del tenant_id  # kept for API compatibility; extraction is tenant-agnostic
    text, method = extract_document(real_path, max_chars=max_chars)
    logger.debug("Extracted %s via %s (%d chars)", real_path.name, method, len(text))
    return text, method


def pdf_page_count(real_path: Path) -> int | None:
    """Best-effort PDF page count for preview metadata."""
    if real_path.suffix.lower() != ".pdf":
        return None
    try:
        import pdfplumber

        with pdfplumber.open(str(real_path)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None
