"""Central policy for files that must never be exposed through the browser file
APIs (list / read / serve / write / upload / delete), regardless of role or a
broad ``file:*`` entitlement.

Two independent rules:

- **Protected PATHS** — exact virtual paths consumed by credential/config wiring
  (e.g. the tenant credential store), never through a file surface.
- **Protected EXTENSIONS** — private-key / key material. Public certificates
  (``.crt`` / ``.cer``) are *not* secret and are intentionally excluded.

Callers MUST normalize the virtual path with :func:`norm_vpath` before the
membership check. ``norm_vpath`` canonicalizes ``.`` / ``..`` / duplicate
separators, so equivalents like ``/shared/config/./credentials.yaml`` or
``/shared/config//credentials.yaml`` cannot slip past the exact-set comparison
while still resolving to the protected file on disk.
"""
from __future__ import annotations

import posixpath
from os.path import splitext
from pathlib import Path

# Exact virtual paths blocked from the file API (compared lowercase).
PROTECTED_PATHS = {
    "/shared/config/credentials.yaml",
}

# Private-key material is never served; .pem is protected, public certs (.crt/.cer) are not.
PROTECTED_EXTS = {".key", ".pem", ".pfx", ".p12", ".jks", ".keystore"}

# The credential store is blocked by basename under any root.
PROTECTED_NAMES = {"credentials.yaml"}


def norm_vpath(p: str) -> str:
    """Canonicalize a virtual path for a protected-path comparison: unify
    separators, collapse ``.`` / ``..`` / duplicate slashes, drop a trailing
    slash, and lowercase. Anchored at ``/`` so ``..`` can never escape above the
    root. Returns ``"/"`` for an empty path."""
    raw = (p or "").strip().replace("\\", "/")
    if not raw:
        return "/"
    collapsed = posixpath.normpath("/" + raw.lstrip("/"))
    return collapsed.rstrip("/").lower() or "/"


def is_protected_path(virtual_path: str) -> bool:
    """True if the (canonicalized) virtual path is an exact protected path."""
    return norm_vpath(virtual_path) in PROTECTED_PATHS


def is_protected_ext(name: str) -> bool:
    """True if the filename/path carries a protected (key-material) extension.

    Canonicalizes first (via :func:`norm_vpath`) so a trailing ``/`` or ``/.``
    — which ``os.path.splitext`` would otherwise read as "no extension" — cannot
    slip a ``server.key/`` past the key-material block while ``_resolve_path``
    still reaches the real file."""
    return splitext(norm_vpath(name))[1].lower() in PROTECTED_EXTS


def is_protected_name(name: str) -> bool:
    """True if the basename is a protected filename (the credential store),
    regardless of directory or root."""
    return posixpath.basename(norm_vpath(name)) in PROTECTED_NAMES


def is_protected(virtual_path: str) -> bool:
    """True if the path is protected by ANY rule (exact path, protected basename,
    or key-material extension) — the single check every file surface should
    apply to a *requested* virtual path."""
    return (
        is_protected_path(virtual_path)
        or is_protected_name(virtual_path)
        or is_protected_ext(virtual_path)
    )


def resolve_contained(base, rel: str) -> "Path | None":
    """Resolve ``rel`` under ``base`` FOLLOWING symlinks, and return the real
    :class:`Path` only if it is safe to expose. Returns ``None`` when the target:

    - escapes ``base`` (``..`` traversal or a symlink pointing outside), or
    - resolves to protected material (credential store by basename, or key
      material by extension) — this is what closes the symlink-alias bypass,
      because the check runs on the *resolved* target, not the requested alias.

    Callers still apply :func:`is_protected` to the requested path for a clear
    early 403; this is the second gate that makes traversal/symlinks safe.
    """
    try:
        base_r = Path(base).resolve()
        real = (base_r / str(rel)).resolve()
        real_rel = real.relative_to(base_r)  # raises if it escaped base
    except (ValueError, OSError):
        return None
    if is_protected_name(real.name) or is_protected_ext(real.name):
        return None
    # Also honor exact protected virtual paths for shared-tree callers.
    if is_protected_path("/shared/" + str(real_rel).replace("\\", "/")):
        return None
    return real
