"""Enterprise root scaffolding helpers."""

from __future__ import annotations

from pathlib import Path

from iaf_agentos.config import resolve_data_root, sanitize_tenant_id


def _ensure_data_root(data_root: str, tenant_id: str) -> Path:
    """Create minimal enterprise_root structure if it does not exist."""
    safe_tenant = sanitize_tenant_id(tenant_id)
    root = resolve_data_root(data_root)
    tenant_root = root / "tenants" / safe_tenant

    if not tenant_root.exists():
        (tenant_root / "skills").mkdir(parents=True, exist_ok=True)
        (tenant_root / "shared" / "contexts").mkdir(parents=True, exist_ok=True)
        (tenant_root / "agents").mkdir(parents=True, exist_ok=True)
        index_path = tenant_root / "skills" / "_index.yaml"
        if not index_path.exists():
            index_path.write_text(
                'version: "1.0"\ndefault_skill: general\nskills:\n  general:\n'
                '    description: "General-purpose assistant"\n',
                encoding="utf-8",
            )

    return root
