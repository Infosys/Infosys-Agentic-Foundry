"""Binding resolver — turns a canonical data intent into a client-bound query.

Skills declare an abstract need (a canonical `query_intent` in their
data_contract.yaml). This resolver reads the tenant's active binding
(`/shared/config/active_binding.yaml`), loads the matching binding pack, and
returns an executable query (database + dialect + SQL + params) — OR runs it and
returns canonical rows. This is the single seam that makes one capability work
across many clients: swap the binding, not the skill.

Client-agnostic; no skill or client names hardcoded here.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml


class BindingResolver:
    def __init__(self, tenant_root: str, canonical_root: str | None = None):
        # tenant_root: .../enterprise_root/tenants/<client>
        self.tenant_root = Path(tenant_root)
        self.canonical_root = Path(canonical_root) if canonical_root else None
        cfg_path = self._real("/shared/config/active_binding.yaml")
        self.cfg = yaml.safe_load(cfg_path.read_text())
        self.active_binding = self.cfg.get("active_binding")
        self.domains = self.cfg.get("domains", {})

    # Virtual "/shared/X" -> real "<tenant_root>/shared/X"
    def _real(self, virtual: str) -> Path:
        return self.tenant_root / virtual.lstrip("/")

    def _load_domain_bindings(self, domain: str) -> dict[str, dict]:
        d = self._real(self.domains[domain])
        return {f.stem: yaml.safe_load(f.read_text()) for f in sorted(Path(d).glob("*.yaml"))}

    def _canonical_intent_defaults(self, intent: str) -> dict:
        if not self.canonical_root:
            return {}
        model = yaml.safe_load((self.canonical_root / "finance_model.yaml").read_text())
        spec = (model.get("query_intents", {}) or {}).get(intent, {}) or {}
        return {k: v.get("default") for k, v in (spec.get("params", {}) or {}).items()
                if isinstance(v, dict) and "default" in v}

    def _active_pack(self, domain: str) -> dict:
        """Return the binding pack for self.active_binding ONLY.

        Resolving against every pack and taking the first that defines an intent can
        execute SQL against the wrong client's database when two packs share an intent
        name. Select the active binding by filename stem, else by a declared
        binding/name field.
        """
        packs = self._load_domain_bindings(domain)
        if self.active_binding in packs:
            return packs[self.active_binding]
        for pack in packs.values():
            if (pack.get("binding") or pack.get("name")) == self.active_binding:
                return pack
        raise KeyError(
            f"active binding '{self.active_binding}' not found among '{domain}' binding packs"
        )

    def resolve_intent(self, domain: str, intent: str, params: dict | None = None) -> dict:
        """Return {binding, dialect, database, sql, params} for the active binding."""
        merged = {**self._canonical_intent_defaults(intent), **(params or {})}
        pack = self._active_pack(domain)
        intents = pack.get("query_intents", {}) or {}
        if intent not in intents:
            raise KeyError(
                f"query_intent '{intent}' not found in active binding "
                f"'{self.active_binding}' for domain '{domain}'"
            )
        src = pack.get("source", {}) or {}
        db = str(self._real(src["database"])) if src.get("type") == "sqlite" else src.get("database")
        return {
            "binding": self.active_binding,
            "dialect": src.get("dialect"),
            "database": db,
            "sql": intents[intent],
            "params": merged,
        }

    def fetch(self, domain: str, intent: str, params: dict | None = None) -> list[dict]:
        """Resolve + execute a SQLite-backed intent, returning canonical rows."""
        resolved = self.resolve_intent(domain, intent, params)
        if resolved["dialect"] != "sqlite":
            raise NotImplementedError(f"fetch() supports sqlite only; got {resolved['dialect']}")
        con = sqlite3.connect(resolved["database"])
        con.row_factory = sqlite3.Row
        try:
            # Named-param binding (:name) — no string interpolation, no injection.
            rows = [dict(r) for r in con.execute(resolved["sql"], resolved["params"])]
        finally:
            con.close()
        return rows
