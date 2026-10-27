"""CSP nonce helpers — per-request script/style allowlisting (SEC-4)."""
from __future__ import annotations

import re
import secrets

_SCRIPT_OPEN_RE = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>", re.IGNORECASE)
_STYLE_OPEN_RE = re.compile(r"<style([^>]*)>", re.IGNORECASE)
_HEAD_TAG_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)
_BOOTSTRAP_MARKER = "__CSP_NONCE__"


def generate_nonce() -> str:
    """Return a fresh, unguessable per-request CSP nonce."""
    return secrets.token_urlsafe(16)


def inject_nonce(html: str, nonce: str) -> str:
    """Stamp ``nonce="..."`` onto every inline ``<script>``/``<style>`` tag, and expose the same token to client-side JS as ``window.__CSP_NONCE__``."""

    def _script_sub(match: "re.Match[str]") -> str:
        attrs = match.group(1)
        if "nonce=" in attrs.lower():
            return match.group(0)
        return f"<script{attrs} nonce=\"{nonce}\">"

    def _style_sub(match: "re.Match[str]") -> str:
        attrs = match.group(1)
        if "nonce=" in attrs.lower():
            return match.group(0)
        return f"<style{attrs} nonce=\"{nonce}\">"

    html = _SCRIPT_OPEN_RE.sub(_script_sub, html)
    html = _STYLE_OPEN_RE.sub(_style_sub, html)
    html = _inject_nonce_bootstrap(html, nonce)
    return html


def _inject_nonce_bootstrap(html: str, nonce: str) -> str:
    """Insert ``<script nonce="...">window.__CSP_NONCE__="...";</script>``"""
    if _BOOTSTRAP_MARKER in html:
        return html
    match = _HEAD_TAG_RE.search(html)
    if not match:
        return html
    bootstrap = f'<script nonce="{nonce}">window.{_BOOTSTRAP_MARKER}="{nonce}";</script>'
    insert_at = match.end()
    return html[:insert_at] + bootstrap + html[insert_at:]

