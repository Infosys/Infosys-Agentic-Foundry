"""Credential Resolver capability — Phase 5 facade over ``agent_os.credential_store``.

Replaces the Batch 1 ``_PassivePlaceholder("credential_resolver")`` entry with a
real adapter so the capability registry can actually swap credential backends
per tenant (Fernet file, env var, future remote vault, …) without code change
in the kernel or hooks.

Non-negotiable constraints carried from the migration plan:
  * Kernel hard-deny semantics in ``agent_os.kernel._credential_allowed`` stay
    in effect — this adapter never circumvents them.
  * Sensitive values are NEVER returned to LLM-visible surfaces (callers must
    only use the returned :class:`Credential` for substitution, never for
    prompt assembly).
  * Consumer scoping (skill identity) is mandatory — empty consumer triggers
    the kernel's SCOPE_DENIED audit, mirrored here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agent_os.credential_store import (
    Credential,
    CredentialStore,
)
from agent_os.secret_provider import CredentialStoreSecretProvider, SecretProvider, build_secret_provider

logger = logging.getLogger(__name__)


class CredentialResolverAdapter:
    """Capability-shaped facade. Resolves a credential by name + consumer scope.

    The backing CredentialStore is constructed once per (config_dir) and
    cached. Tenant overrides at the registry layer can supply a different
    adapter instance with a different ``config_dir`` or a custom backend.
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        store: Optional[CredentialStore] = None,
        provider: Optional[SecretProvider] = None,
    ) -> None:
        self._config_dir = Path(config_dir) if config_dir is not None else None
        self._provider = provider
        self._store = store

    @property
    def store(self) -> CredentialStore:
        provider = self.provider
        store = getattr(provider, "store", None)
        if store is None:
            raise RuntimeError("CredentialResolverAdapter provider does not expose a CredentialStore")
        return store

    @property
    def provider(self) -> SecretProvider:
        if self._provider is None:
            if self._store is not None:
                self._provider = CredentialStoreSecretProvider(store=self._store)
            elif self._config_dir is not None:
                self._provider = build_secret_provider(config_dir=self._config_dir)
            else:
                raise RuntimeError(
                    "CredentialResolverAdapter requires config_dir, provider, "
                    "or a pre-built CredentialStore"
                )
        return self._provider

    def resolve(
        self,
        name: str,
        *,
        consumer: str,
        accessor: str = "",
        purpose: str = "",
    ) -> Optional[Credential]:
        """Return the Credential or None if missing / scope-denied.

        ``consumer`` MUST be a non-empty skill / service identity. Empty
        consumer is treated as a scope violation and audited by the
        underlying store. This mirrors the kernel's behaviour so swappable
        backends cannot bypass scoping by accident.
        """
        if not name:
            return None
        return self.provider.resolve(
            name,
            consumer=consumer or "",
            accessor=accessor or consumer or "",
            purpose=purpose or "capability resolve",
        )

    def list_names(self, consumer: str = "") -> list[str]:
        """Return credential names visible to the given consumer scope."""
        try:
            return list(self.provider.list_names(consumer=consumer))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("CredentialResolverAdapter.list_names error: %s", exc)
            return []

    def get_metadata(self, name: str) -> Optional[dict]:
        """Return masked metadata (no sensitive values) suitable for API responses."""
        try:
            return self.provider.get_metadata(name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("CredentialResolverAdapter.get_metadata error: %s", exc)
        return None

    def audit_snapshot(self, limit: int = 50) -> list[dict]:
        """Return recent provider audit records without sensitive values."""
        try:
            return self.provider.audit_snapshot(limit=limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("CredentialResolverAdapter.audit_snapshot error: %s", exc)
            return []

    def health(self) -> dict:
        """Return provider health safe for diagnostics."""
        try:
            return self.provider.health()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("CredentialResolverAdapter.health error: %s", exc)
            return {"provider": "credential_resolver", "status": "degraded", "last_error": type(exc).__name__}
