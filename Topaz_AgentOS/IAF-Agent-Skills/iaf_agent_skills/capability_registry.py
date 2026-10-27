"""Passive capability registry for AgentPro runtime adapters.

The registry is intentionally small and side-effect free. Phase 1 uses it as a
directory over existing implementations so startup can validate dependencies and
log configured providers before any behavior is moved behind adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Mapping


class CapabilityRegistryError(RuntimeError):
    """Base error for capability registry failures."""


class DuplicateCapabilityError(CapabilityRegistryError):
    """Raised when a capability is registered more than once."""


class MissingCapabilityError(CapabilityRegistryError):
    """Raised when a required capability is absent."""


class CapabilityDependencyError(CapabilityRegistryError):
    """Raised when capability dependencies are missing or cyclic."""


@dataclass(frozen=True)
class CapabilityRegistration:
    """Metadata for one capability implementation."""

    name: str
    instance: Any
    implementation: str
    version: str | None = None
    owner: str | None = None
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """Return deterministic, log-safe metadata for startup diagnostics."""
        return {
            "name": self.name,
            "implementation": self.implementation,
            "version": self.version,
            "owner": self.owner,
            "dependencies": sorted(self.dependencies),
            "enabled": self.enabled,
            "metadata": dict(sorted(self.metadata.items())),
        }


class CapabilityRegistry:
    """Thread-safe directory of runtime capability implementations."""

    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityRegistration] = {}
        self._tenant_overrides: dict[str, dict[str, CapabilityRegistration]] = {}
        self._lock = RLock()

    def register(
        self,
        name: str,
        instance: Any,
        *,
        implementation: str | None = None,
        version: str | None = None,
        owner: str | None = None,
        dependencies: tuple[str, ...] | list[str] = (),
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> CapabilityRegistration:
        """Register a default capability implementation."""
        capability_name = self._normalize_name(name)
        with self._lock:
            if capability_name in self._capabilities:
                raise DuplicateCapabilityError(f"Capability '{capability_name}' is already registered")
            registration = self._make_registration(
                capability_name,
                instance,
                implementation=implementation,
                version=version,
                owner=owner,
                dependencies=dependencies,
                enabled=enabled,
                metadata=metadata,
            )
            self._capabilities[capability_name] = registration
            return registration

    def register_tenant_override(
        self,
        tenant_id: str,
        name: str,
        instance: Any,
        *,
        implementation: str | None = None,
        version: str | None = None,
        owner: str | None = None,
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> CapabilityRegistration:
        """Register a tenant-specific implementation for an existing capability."""
        tenant_key = self._normalize_name(tenant_id)
        capability_name = self._normalize_name(name)
        with self._lock:
            if capability_name not in self._capabilities:
                raise MissingCapabilityError(f"Capability '{capability_name}' is not registered")
            tenant_capabilities = self._tenant_overrides.setdefault(tenant_key, {})
            if capability_name in tenant_capabilities:
                raise DuplicateCapabilityError(
                    f"Tenant '{tenant_key}' already has an override for capability '{capability_name}'"
                )
            registration = self._make_registration(
                capability_name,
                instance,
                implementation=implementation,
                version=version,
                owner=owner,
                dependencies=(),
                enabled=enabled,
                metadata=metadata,
            )
            tenant_capabilities[capability_name] = registration
            return registration

    def get(self, name: str) -> CapabilityRegistration:
        """Return the default registration for a capability."""
        capability_name = self._normalize_name(name)
        with self._lock:
            try:
                return self._capabilities[capability_name]
            except KeyError as exc:
                raise MissingCapabilityError(f"Capability '{capability_name}' is not registered") from exc

    def require(self, name: str, *, tenant_id: str | None = None) -> Any:
        """Return a capability instance or raise if it is absent."""
        return self.resolve(name, tenant_id=tenant_id)

    def resolve(self, name: str, *, tenant_id: str | None = None) -> Any:
        """Resolve a capability instance, using tenant override when present."""
        return self.resolve_registration(name, tenant_id=tenant_id).instance

    def resolve_registration(self, name: str, *, tenant_id: str | None = None) -> CapabilityRegistration:
        """Resolve capability metadata, using tenant override when present."""
        capability_name = self._normalize_name(name)
        with self._lock:
            if tenant_id:
                tenant_key = self._normalize_name(tenant_id)
                tenant_registration = self._tenant_overrides.get(tenant_key, {}).get(capability_name)
                if tenant_registration is not None:
                    return tenant_registration
            return self.get(capability_name)

    def validate_dependencies(self) -> None:
        """Validate that registered default capabilities form an acyclic graph."""
        with self._lock:
            capability_names = set(self._capabilities)
            for registration in self._capabilities.values():
                missing_dependencies = [
                    dependency for dependency in registration.dependencies if dependency not in capability_names
                ]
                if missing_dependencies:
                    missing_text = ", ".join(sorted(missing_dependencies))
                    raise CapabilityDependencyError(
                        f"Capability '{registration.name}' depends on missing capability: {missing_text}"
                    )
            self._validate_no_cycles()

    def snapshot(self) -> list[dict[str, Any]]:
        """Return deterministic, redacted startup metadata for all defaults."""
        with self._lock:
            return [self._capabilities[name].snapshot() for name in sorted(self._capabilities)]

    def tenant_snapshot(self, tenant_id: str) -> list[dict[str, Any]]:
        """Return deterministic, redacted metadata for tenant overrides."""
        tenant_key = self._normalize_name(tenant_id)
        with self._lock:
            tenant_capabilities = self._tenant_overrides.get(tenant_key, {})
            return [tenant_capabilities[name].snapshot() for name in sorted(tenant_capabilities)]

    def _validate_no_cycles(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        path: list[str] = []

        def visit(capability_name: str) -> None:
            if capability_name in visited:
                return
            if capability_name in visiting:
                cycle_start = path.index(capability_name)
                cycle = path[cycle_start:] + [capability_name]
                raise CapabilityDependencyError("Capability dependency cycle detected: " + " -> ".join(cycle))
            visiting.add(capability_name)
            path.append(capability_name)
            for dependency in self._capabilities[capability_name].dependencies:
                visit(dependency)
            path.pop()
            visiting.remove(capability_name)
            visited.add(capability_name)

        for capability_name in sorted(self._capabilities):
            visit(capability_name)

    @staticmethod
    def _make_registration(
        name: str,
        instance: Any,
        *,
        implementation: str | None,
        version: str | None,
        owner: str | None,
        dependencies: tuple[str, ...] | list[str],
        enabled: bool,
        metadata: Mapping[str, Any] | None,
    ) -> CapabilityRegistration:
        normalized_dependencies = tuple(CapabilityRegistry._normalize_name(dep) for dep in dependencies)
        implementation_name = implementation or type(instance).__name__
        return CapabilityRegistration(
            name=name,
            instance=instance,
            implementation=implementation_name,
            version=version,
            owner=owner,
            dependencies=normalized_dependencies,
            enabled=enabled,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("Capability names must be non-empty")
        return normalized