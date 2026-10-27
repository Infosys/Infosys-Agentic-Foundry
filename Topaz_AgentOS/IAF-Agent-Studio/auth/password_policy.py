"""
auth/password_policy.py — PWD complexity and history rules

Rules are config-driven (shared/config.py).
Both server-side and client-side rules are derived from the same source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PasswordPolicy:
    min_length: int = 8
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True
    special_chars: str = r"!@#$%^&*()_+\-=\[\]{}|;:',.<>?/"
    max_length: int = 128

    def validate(self, password: str) -> Optional[str]:
        """
        Returns an error message string if the PWD fails policy,
        or None if it is acceptable.
        """
        if len(password) < self.min_length:
            return f"Password must be at least {self.min_length} characters."
        if len(password) > self.max_length:
            return f"Password must not exceed {self.max_length} characters."
        if self.require_uppercase and not re.search(r"[A-Z]", password):
            return "Password must contain at least one uppercase letter."
        if self.require_lowercase and not re.search(r"[a-z]", password):
            return "Password must contain at least one lowercase letter."
        if self.require_digit and not re.search(r"\d", password):
            return "Password must contain at least one digit."
        if self.require_special and not re.search(
            r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/\\]", password
        ):
            return "Password must contain at least one special character (!@#$%^&* etc.)."
        return None

    def to_frontend_rules(self) -> dict:
        """Serializable dict for frontend validation (same rules, no server round-trip)."""
        return {
            "min_length": self.min_length,
            "max_length": self.max_length,
            "require_uppercase": self.require_uppercase,
            "require_lowercase": self.require_lowercase,
            "require_digit": self.require_digit,
            "require_special": self.require_special,
        }


# Singleton — loaded from config on first use
_policy: Optional[PasswordPolicy] = None


def get_policy() -> PasswordPolicy:
    global _policy
    if _policy is None:
        try:
            from shared.config import (
                AUTH_PASSWORD_MIN_LENGTH,
                AUTH_PASSWORD_REQUIRE_UPPERCASE,
                AUTH_PASSWORD_REQUIRE_DIGIT,
                AUTH_PASSWORD_REQUIRE_SPECIAL,
            )
            _policy = PasswordPolicy(
                min_length=AUTH_PASSWORD_MIN_LENGTH,
                require_uppercase=AUTH_PASSWORD_REQUIRE_UPPERCASE,
                require_digit=AUTH_PASSWORD_REQUIRE_DIGIT,
                require_special=AUTH_PASSWORD_REQUIRE_SPECIAL,
            )
        except ImportError:
            _policy = PasswordPolicy()
    return _policy
