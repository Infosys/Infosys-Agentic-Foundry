"""Resolve the user folder key for agent sandbox paths (/me/, uploads, etc.).

Auth identities carry a stable ``user_id`` (often a UUID) and an ``email``.
User uploads and profile files live under::

    tenants/{tenant}/agents/{agent}/users/{filesystem_user}/

That folder name has historically been the user's **email** when available.
Callers that pass the UUID into ``SafeKernel`` will see empty ``/me/uploads``
while the file browser (bound to email) shows files — the mismatch this module
prevents.
"""

from __future__ import annotations

from pathlib import Path


def filesystem_user_id(
    *,
    email: str | None = None,
    user_id: str | None = None,
    fallback: str = "demo",
) -> str:
    """Return the canonical folder name under ``agents/{agent}/users/``."""
    for candidate in (email, user_id, fallback):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return fallback


def filesystem_user_id_from_principal(principal, *, fallback: str = "demo") -> str:
    return filesystem_user_id(
        email=getattr(principal, "email", None),
        user_id=getattr(principal, "user_id", None),
        fallback=fallback,
    )


def coerce_filesystem_user_id(
    *,
    user_id: str,
    data_root: Path,
    tenant_id: str,
    agent_id: str,
    email: str | None = None,
) -> str:
    """Pick an existing users/ folder when UUID and email disagree."""
    preferred = filesystem_user_id(email=email, user_id=user_id)
    users_root = (
        Path(data_root).resolve()
        / "tenants"
        / tenant_id
        / "agents"
        / agent_id
        / "users"
    )
    if not users_root.is_dir():
        return preferred

    if (users_root / preferred).exists():
        return preferred

    # UUID auth with files stored under email (legacy uploads).
    if email and email != preferred and (users_root / email).exists():
        return email

    # Email auth but caller passed UUID — prefer email for new layouts.
    if email and "@" in email:
        return email

    return preferred
