"""
EntityValidator: Allowlist/blocklist for auto-registered entities.

Prevents noisy entities (amounts, IDs, dates, column names) from being
auto-registered in entity_registry. Used by auto_register_entities().
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# Built-in blocklist: patterns and literals that should never be auto-registered
_BLOCKLIST_LITERALS: Set[str] = {
    "active", "pending", "posted", "known", "net45", "net60", "open",
    "blocked", "usd", "transaction_id", "amount", "currency", "transaction_type",
    "status", "posting_date", "due_date", "gl_account", "cost_center",
    "description", "preference_update",
}

_BLOCKLIST_REGEXES: List[re.Pattern] = [
    re.compile(r"^\$[\d,]+\.?\d*$"),           # $8,500, $1,000
    re.compile(r"^[\d,]+\.?\d*$"),              # 180000.0, 200000.0
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),        # 2026-02-20
    re.compile(r"^po-\d"),                      # po-2026-0042
    re.compile(r"^apt-\d"),                     # apt-2026-0029
    re.compile(r"^ap-reg-"),                    # ap-reg-001
    re.compile(r"^inv-"),                       # inv-gf-8500
    re.compile(r"^0-30$"),                      # aging bucket
    re.compile(r"^30-60$"),
    re.compile(r"^60-90$"),
    re.compile(r"^90\+$"),
    re.compile(r"credit_limit.*\d"),           # credit_limit_950000.0
    re.compile(r"^21000-"),                     # GL code
    re.compile(r"^cc-\d+$"),                    # cc-400
]
# Euro amounts
_EURO_PATTERN = "€"


def _load_config(config_path: Optional[Path]) -> tuple:
    """Load allowlist and blocklist_extra from YAML or JSON. Returns (allowlist, blocklist_extra)."""
    allowlist: List[str] = []
    blocklist_extra: List[str] = []
    if not config_path or not config_path.exists():
        return allowlist, blocklist_extra
    try:
        content = config_path.read_text(encoding="utf-8")
        # Try YAML first
        try:
            import yaml
            data = yaml.safe_load(content) or {}
        except ImportError:
            import json
            data = json.loads(content) if content.strip() else {}
        allowlist = [str(x).strip().lower() for x in data.get("allowlist", []) if x]
        blocklist_extra = [str(x).strip().lower() for x in data.get("blocklist_extra", []) if x]
    except Exception as e:
        logger.warning("EntityValidator: failed to load config %s: %s", config_path, e)
    return allowlist, blocklist_extra


class EntityValidator:
    """
    Validates entity names before auto-registration.
    - Blocklist: always reject (amounts, IDs, dates, generic terms, column names).
    - Allowlist: optional; if non-empty, only allow matching names.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Args:
            config_path: Path to entity_validation.yaml (or .json).
                         If None or missing, use blocklist-only mode (allowlist empty).
        """
        self._config_path = config_path
        self._allowlist: List[str] = []
        self._blocklist_extra: Set[str] = set()
        self._load()

    def _load(self) -> None:
        self._allowlist, extra = _load_config(self._config_path)
        self._blocklist_extra = set(extra)

    def is_blocked(self, name: str) -> bool:
        """Return True if the entity name matches blocklist (should not register)."""
        if not name or len(name.strip()) < 3:
            return True
        n = name.strip().lower()
        if n in _BLOCKLIST_LITERALS:
            return True
        if n in self._blocklist_extra:
            return True
        if _EURO_PATTERN in n:
            return True
        for pat in _BLOCKLIST_REGEXES:
            if pat.search(n):
                return True
        return False

    def is_allowed(self, name: str) -> bool:
        """
        Return True if the entity name is in the allowlist.
        If allowlist is empty, return True (allow all except blocklist).
        """
        if not self._allowlist:
            return True
        n = name.strip().lower()
        for allowed in self._allowlist:
            if allowed in n or n in allowed:
                return True
        return False

    def should_register(self, name: str) -> bool:
        """
        Combined check: not blocked AND (allowlist empty or allowed).
        """
        if self.is_blocked(name):
            return False
        return self.is_allowed(name)
