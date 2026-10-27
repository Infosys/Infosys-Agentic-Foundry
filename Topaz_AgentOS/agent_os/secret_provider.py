"""Provider boundary for AgentOS sensitive.

The default provider wraps the existing CredentialStore so local env/file/Fernet
behavior remains unchanged while runtime call sites can resolve through a
replaceable, diagnostics-safe contract.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .credential_store import Credential, CredentialStore


class SecretProviderError(RuntimeError):
    """Base error raised by sensitive providers."""


class SecretProviderUnavailable(SecretProviderError):
    """Raised when a configured provider cannot resolve sensitive."""


@runtime_checkable
class SecretProvider(Protocol):
    """Minimal sensitive provider contract consumed by kernel and adapters."""

    def resolve(
        self,
        name: str,
        *,
        consumer: str,
        accessor: str = "",
        purpose: str = "",
    ) -> Credential | None:
        """Return a credential or None when missing/denied."""

    def list_names(self, consumer: str = "") -> list[str]:
        """Return credential names visible to the consumer."""

    def get_metadata(self, name: str) -> dict[str, Any] | None:
        """Return metadata that does not include sensitive values."""

    def audit_snapshot(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent audit records without values."""

    def health(self) -> dict[str, Any]:
        """Return provider health without sensitive values."""


_SENSITIVE_KEYS = {
    "authorization",
    "password",
    "secret",
    "token",
    "key",
    "api_key",
    "apikey",
    "client_secret",
    "access_token",
    "refresh_token",
    "value",
}


def _safe_metadata(value: Any, *, limit: int = 512) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_KEYS:
                cleaned[key_text] = "[REDACTED]"
            else:
                cleaned[key_text] = _safe_metadata(item, limit=limit)
        return cleaned
    if isinstance(value, list):
        return [_safe_metadata(item, limit=limit) for item in value[:50]]
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 14] + "...[TRUNCATED]"
    return value


def _safe_error(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    return type(exc).__name__


class CredentialStoreSecretProvider:
    """SecretProvider backed by the existing CredentialStore implementation."""

    def __init__(
        self,
        config_dir: str | Path | None = None,
        *,
        store: CredentialStore | Any | None = None,
        enable_env: bool = True,
        enable_file: bool = True,
        provider_name: str = "local_credential_store",
    ) -> None:
        if config_dir is None and store is None:
            raise ValueError("CredentialStoreSecretProvider requires config_dir or store")
        self.config_dir = Path(config_dir) if config_dir is not None else None
        self._store = store
        self.enable_env = enable_env
        self.enable_file = enable_file
        self.provider_name = provider_name
        self.resolve_count = 0
        self.success_count = 0
        self.miss_count = 0
        self.error_count = 0
        self._last_error: Exception | None = None

    @property
    def store(self) -> CredentialStore | Any:
        if self._store is None:
            if self.config_dir is None:
                raise SecretProviderUnavailable("missing credential config directory")
            self._store = CredentialStore.create(
                config_dir=self.config_dir,
                enable_env=self.enable_env,
                enable_file=self.enable_file,
            )
        return self._store

    def resolve(
        self,
        name: str,
        *,
        consumer: str,
        accessor: str = "",
        purpose: str = "",
    ) -> Credential | None:
        self.resolve_count += 1
        try:
            credential = self.store.get(
                name,
                consumer=consumer or "",
                accessor=accessor or consumer or "",
                purpose=purpose or "secret provider resolve",
            )
        except SecretProviderError as exc:
            self.error_count += 1
            self._last_error = exc
            raise
        except Exception as exc:  # pragma: no cover - defensive provider wrapper
            self.error_count += 1
            self._last_error = exc
            raise SecretProviderUnavailable("local credential store unavailable") from exc

        self._last_error = None
        if credential is None:
            self.miss_count += 1
        else:
            self.success_count += 1
        return credential

    def resolve_vault_secret(
        self,
        name: str,
        path: str,
        key: str | None = None,
        *,
        consumer: str,
        accessor: str = "",
        purpose: str = "",
    ) -> Credential | None:
        """Resolve a live secret from a scoped ``type: vault`` connection stored
        in credentials.yaml (see ``CredentialStore.resolve_vault_secret``). Kept
        on the provider so kernel / tool call sites go through the same boundary
        as ``resolve()``. Returns None if the backing store lacks Vault support."""
        resolver = getattr(self.store, "resolve_vault_secret", None)
        if not callable(resolver):
            return None
        self.resolve_count += 1
        try:
            credential = resolver(
                name,
                path,
                key,
                consumer=consumer or "",
                accessor=accessor or consumer or "",
                purpose=purpose or "vault secret",
            )
        except SecretProviderError as exc:
            self.error_count += 1
            self._last_error = exc
            raise
        except Exception as exc:  # pragma: no cover - defensive provider wrapper
            self.error_count += 1
            self._last_error = exc
            raise SecretProviderUnavailable("vault resolve failed") from exc

        self._last_error = None
        if credential is None:
            self.miss_count += 1
        else:
            self.success_count += 1
        return credential

    def list_names(self, consumer: str = "") -> list[str]:
        try:
            return list(self.store.list(consumer=consumer or ""))
        except Exception as exc:  # pragma: no cover - defensive diagnostics path
            self.error_count += 1
            self._last_error = exc
            return []

    def get_metadata(self, name: str) -> dict[str, Any] | None:
        for backend in getattr(self.store, "backends", []):
            getter = getattr(backend, "get_metadata", None)
            if not getter:
                continue
            try:
                metadata = getter(name)
            except Exception as exc:  # pragma: no cover - defensive diagnostics path
                self.error_count += 1
                self._last_error = exc
                continue
            if metadata:
                return _safe_metadata(metadata)
        return None

    def audit_snapshot(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit or 50), 500))
        records: list[dict[str, Any]] = []
        audit_path = getattr(self.store, "audit_path", None)
        if audit_path:
            path = Path(audit_path)
            if path.exists():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-bounded_limit:]:
                    parsed = self._parse_audit_line(line)
                    if parsed:
                        records.append(parsed)
        for entry in getattr(self.store, "_audit_buffer", [])[-bounded_limit:]:
            records.append({
                "timestamp": getattr(entry, "timestamp", ""),
                "accessor": getattr(entry, "accessor", ""),
                "consumer": getattr(entry, "consumer", ""),
                "credential_name": getattr(entry, "credential_name", ""),
                "purpose": getattr(entry, "purpose", ""),
                "success": bool(getattr(entry, "success", False)),
                "error": getattr(entry, "error", None),
            })
        return [_safe_metadata(item) for item in records[-bounded_limit:]]

    def health(self) -> dict[str, Any]:
        return _safe_metadata({
            "provider": self.provider_name,
            "status": "degraded" if self._last_error else "ok",
            "config_dir": str(self.config_dir) if self.config_dir is not None else None,
            "enable_env": self.enable_env,
            "enable_file": self.enable_file,
            "resolve_count": self.resolve_count,
            "success_count": self.success_count,
            "miss_count": self.miss_count,
            "error_count": self.error_count,
            "last_error": _safe_error(self._last_error),
            "audit_buffer_count": len(getattr(self.store, "_audit_buffer", [])),
        })

    @staticmethod
    def _parse_audit_line(line: str) -> dict[str, Any] | None:
        parts = line.split("|", 5)
        if len(parts) != 6:
            return None
        timestamp, accessor, consumer, credential_name, purpose, status = parts
        success = status == "OK"
        error = None if success else status.removeprefix("DENIED:")
        return {
            "timestamp": timestamp,
            "accessor": accessor,
            "consumer": consumer,
            "credential_name": credential_name,
            "purpose": purpose,
            "success": success,
            "error": error,
        }


def build_secret_provider(
    *,
    config_dir: str | Path,
    provider_name: str | None = None,
    enable_env: bool = True,
    enable_file: bool = True,
) -> SecretProvider:
    """Build the configured sensitive provider.

    Only the local CredentialStore provider is implemented in this MVP. Cloud
    vault providers should be added after SDK learning tests confirm behavior.
    """
    selected = (provider_name or os.getenv("SECRET_PROVIDER", "local")).strip().lower()
    if selected not in {"local", "credential_store", "local_credential_store"}:
        raise SecretProviderUnavailable(f"unsupported secret provider: {selected}")
    return CredentialStoreSecretProvider(
        config_dir=config_dir,
        enable_env=enable_env,
        enable_file=enable_file,
    )
