"""Login privacy notice + mandatory acknowledgement service.

PIA Data Privacy controls 1 (Transparency) and 3 (Declaration & Acknowledgement).

Responsibilities
----------------
1. Resolve the active privacy notice (title, version, markdown body) from
   tenant-aware config. The body ships as a tenant default and is fully
   configurable via ``PRIVACY_NOTICE_PATH`` / ``PRIVACY_NOTICE_VERSION``.
2. Record a user's acceptance to the **existing** auth audit sink
   (``auth.audit.log_event`` → Redis stream + durable SQLite), event
   ``PRIVACY_ACK_ACCEPTED``. No parallel store is introduced.
3. Answer "has this user accepted the *current* notice version?" by reading the
   same durable audit sink, with a small in-process positive cache so the
   middleware gate stays cheap.

Everything here is inert unless ``PRIVACY_ACK_REQUIRED`` is true — with the flag
off, :func:`notice_status` reports ``required=False`` and the gate never blocks.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("iaf_server.privacy.service")


class PrivacyAcceptanceNotPersisted(RuntimeError):
    """Raised when a privacy acceptance was accepted by callers but the durable
    audit sink did not commit. The endpoint MUST surface this so the client
    retries and the gate stays closed — silently caching would fake compliance
    evidence that never landed on disk."""


# Positive acceptances are monotonic for a given (user, tenant, version): once true
# they never become false, so caching them for the process lifetime is safe and
# avoids a SQLite read on every gated request. The tenant is part of the key so a
# multi-tenant identity that accepts in one tenant is NOT treated as accepted in
# another. Negative results are never cached (those are exactly the users we still
# want to prompt/gate).
_accept_cache: set[tuple[str, str, str]] = set()

# The notice body rarely changes; cache it briefly to avoid re-reading the file
# on every /auth/privacy/notice hit. Keyed by resolved path + mtime.
_notice_cache: dict = {}
_NOTICE_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class PrivacyNotice:
    required: bool
    version: str
    title: str
    markdown: str

    def to_public_dict(self) -> dict:
        return {
            "required": self.required,
            "version": self.version,
            "title": self.title,
            "markdown": self.markdown,
        }


def _cfg():
    from shared import config as cfg
    return cfg


def _resolve_tenant(tenant_id: Optional[str]) -> str:
    """Normalise a tenant id, falling back to the configured default tenant.

    Acceptance is scoped per tenant, so a stable non-empty tenant string is
    required for the cache key and the audit-row comparison.
    """
    if tenant_id:
        return str(tenant_id)
    return str(getattr(_cfg(), "TENANT_ID", "company"))


def _load_notice_markdown() -> str:
    """Read the active notice body (tenant-aware). Never raises: returns a minimal
    built-in fallback if the file is missing so the gate can still show *something*."""
    cfg = _cfg()
    try:
        path = cfg.resolve_privacy_notice_path()
    except Exception:  # pragma: no cover - defensive
        path = None

    now = time.time()
    if path is not None:
        try:
            mtime = path.stat().st_mtime
            cached = _notice_cache.get("v")
            if (
                cached
                and cached["path"] == str(path)
                and cached["mtime"] == mtime
                and now - cached["at"] < _NOTICE_TTL_SECONDS
            ):
                return cached["text"]
            text = path.read_text(encoding="utf-8")
            _notice_cache["v"] = {"path": str(path), "mtime": mtime, "text": text, "at": now}
            return text
        except Exception as exc:
            logger.warning("privacy notice unreadable at %s: %s", path, exc)

    return (
        "# Data Privacy Notice & Declaration\n\n"
        "By continuing you confirm that you will not process Personal Data of other "
        "individuals using AgentOS-V1.0.0 agents unless approved by the Data Privacy "
        "Office, and you accept full accountability for data you process."
    )


def get_notice(*, include_body: bool = True) -> PrivacyNotice:
    """Return the active notice descriptor. ``required`` reflects PRIVACY_ACK_REQUIRED."""
    cfg = _cfg()
    required = bool(getattr(cfg, "PRIVACY_ACK_REQUIRED", False))
    version = str(getattr(cfg, "PRIVACY_NOTICE_VERSION", "1.0.0"))
    title = str(getattr(cfg, "PRIVACY_NOTICE_TITLE", "Data Privacy Notice"))
    markdown = _load_notice_markdown() if include_body else ""
    return PrivacyNotice(required=required, version=version, title=title, markdown=markdown)


def has_accepted(
    user_id: str,
    tenant_id: Optional[str] = None,
    version: Optional[str] = None,
) -> bool:
    """True if ``user_id`` has an audited acceptance of ``version`` for ``tenant_id``.

    Acceptance is scoped by tenant: an audited acceptance recorded under a
    different tenant does NOT satisfy the gate for this tenant. Legacy rows written
    before tenant scoping (no ``tenant_id`` in details) are honoured for backward
    compatibility so existing users are not re-prompted.
    """
    if not user_id:
        return False
    cfg = _cfg()
    version = version or str(getattr(cfg, "PRIVACY_NOTICE_VERSION", "1.0.0"))
    tenant = _resolve_tenant(tenant_id)
    key = (str(user_id), tenant, str(version))
    if key in _accept_cache:
        return True
    try:
        from auth import audit
        row = audit.get_latest_event(audit.PRIVACY_ACK_ACCEPTED, user_id=str(user_id))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("privacy acceptance lookup failed: %s", exc)
        return False
    if not row:
        return False
    details = row.get("details") or {}
    if str(details.get("notice_version")) != str(version):
        return False
    stored_tenant = details.get("tenant_id")
    # None/"" => legacy pre-scoping row (accept any tenant); otherwise must match.
    if stored_tenant not in (None, "", tenant):
        return False
    _accept_cache.add(key)
    return True


async def record_acceptance(
    *,
    user_id: str,
    tenant_id: Optional[str],
    email: Optional[str] = None,
    ip: Optional[str] = None,
    version: Optional[str] = None,
) -> dict:
    """Persist a PRIVACY_ACK_ACCEPTED event to the auth audit sink and cache it.

    Returns the recorded ``{user_id, tenant_id, notice_version, accepted_at}``.

    Raises ``PrivacyAcceptanceNotPersisted`` if the durable audit write did not
    commit — otherwise the process would report success and cache a phantom
    acceptance even though the compliance evidence never landed. Callers
    (currently the /auth/privacy/accept endpoint) surface this as a 5xx so the
    client retries and the gate stays closed.
    """
    cfg = _cfg()
    version = version or str(getattr(cfg, "PRIVACY_NOTICE_VERSION", "1.0.0"))
    from datetime import datetime, timezone
    accepted_at = datetime.now(timezone.utc).isoformat()
    details = {
        "notice_version": str(version),
        "tenant_id": tenant_id,
        "accepted_at": accepted_at,
        "control": "PIA-DP-1/3 transparency+declaration",
    }
    durable = False
    try:
        from auth import audit
        # log_event returns True iff the durable SQLite sink committed.
        durable = bool(await audit.log_event(
            audit.PRIVACY_ACK_ACCEPTED,
            user_id=str(user_id),
            email=email,
            ip=ip,
            details=details,
            success=True,
        ))
    except Exception as exc:
        logger.warning("privacy acceptance audit write failed: %s", exc)
        durable = False
    if not durable:
        raise PrivacyAcceptanceNotPersisted(
            "Privacy acknowledgement was not durably persisted; refusing to "
            "cache acceptance so the user is re-prompted on the next request."
        )
    _accept_cache.add((str(user_id), _resolve_tenant(tenant_id), str(version)))
    return {
        "user_id": str(user_id),
        "tenant_id": tenant_id,
        "notice_version": str(version),
        "accepted_at": accepted_at,
    }


def notice_status(user_id: Optional[str], tenant_id: Optional[str] = None) -> dict:
    """Compact status for the frontend gate / middleware.

    ``required`` is true only when the flag is on. ``accepted`` reflects whether the
    user has acknowledged the current version for ``tenant_id``. When ``required`` is
    false the caller must treat access as ungated (existing behaviour preserved).
    """
    notice = get_notice(include_body=False)
    accepted = (not notice.required) or has_accepted(user_id or "", tenant_id, notice.version)
    return {
        "required": notice.required,
        "version": notice.version,
        "title": notice.title,
        "accepted": bool(accepted),
    }


def is_exempt_role(role: Optional[str]) -> bool:
    """Break-glass safety valve: never gate configured exempt roles."""
    if not role:
        return False
    cfg = _cfg()
    return str(role).strip().lower() in set(getattr(cfg, "PRIVACY_ACK_EXEMPT_ROLES", ()))


def clear_cache_for_testing() -> None:
    _accept_cache.clear()
    _notice_cache.clear()
