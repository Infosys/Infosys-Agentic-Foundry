"""
shared/user_display.py — Resolve owner ids/emails to display names for the UI.

`created_by` is stored as server truth: an email (skills, context, files,
credentials) or a user_id (cron jobs, personal skills). For display we show
the user's display name instead. Best-effort: always falls back to the
original value when the auth store or the user record is unavailable.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional


async def _resolve_one(store, owner: str) -> Optional[str]:
    """Look up a display name by email (contains '@') or by user_id."""
    try:
        rec = await (store.get_by_email(owner) if "@" in owner else store.get_by_id(owner))
    except Exception:
        return None
    return getattr(rec, "display_name", None) if rec else None


async def display_name(owner: str) -> str:
    """Return the display name for an owner email/user_id, or the input
    unchanged if it can't be resolved."""
    if not owner or not isinstance(owner, str):
        return owner
    try:
        from auth.factory import get_store
        store = await get_store()
    except Exception:
        return owner
    return (await _resolve_one(store, owner)) or owner


async def apply_display_names(items: Iterable[dict], key: str = "created_by",
                              display_key: Optional[str] = None) -> None:
    """In place: add ``item[display_key]`` (default ``<key>_display``) with the
    resolved display name, leaving ``item[key]`` — the stable identity used for
    ownership checks — untouched. Unresolved owners fall back to the raw value."""
    display_key = display_key or f"{key}_display"
    items = list(items)
    owners = {
        it.get(key) for it in items
        if isinstance(it, dict) and isinstance(it.get(key), str) and it.get(key)
    }
    if not owners:
        return
    try:
        from auth.factory import get_store
        store = await get_store()
    except Exception:
        return
    # Resolve owners concurrently so latency does not scale with distinct owners.
    owner_list = list(owners)
    resolved = await asyncio.gather(*(_resolve_one(store, o) for o in owner_list))
    name_map: dict[str, str] = {o: nm for o, nm in zip(owner_list, resolved) if nm}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get(key), str) and it.get(key):
            it[display_key] = name_map.get(it[key], it[key])
