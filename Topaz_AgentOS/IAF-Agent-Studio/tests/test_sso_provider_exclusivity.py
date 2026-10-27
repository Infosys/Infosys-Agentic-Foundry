"""Exactly one SSO IdP (Microsoft/Entra via MSAL, or Keycloak) may be active
at a time; local password login is independent and may run alongside either
(AUTH_MICROSOFT_ENABLED is decoupled from AUTH_PROVIDER). MSAL's redirect URI
must always land on the same standard callback path Keycloak uses
(/auth/callback) rather than an operator-configurable, arbitrary path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).resolve().parents[1]
HARNESS_DIR = STUDIO_DIR.parent
for _p in [STUDIO_DIR, HARNESS_DIR, HARNESS_DIR / "IAF-Agent-Skills"]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.config import _check_sso_provider_exclusivity, _normalize_msal_redirect_uri


def test_microsoft_enabled_rejects_keycloak_enabled():
    with pytest.raises(RuntimeError, match="mutually|cannot both be set|AUTH_MICROSOFT_ENABLED"):
        _check_sso_provider_exclusivity(True, True)


def test_microsoft_enabled_allowed_when_keycloak_disabled():
    _check_sso_provider_exclusivity(True, False)  # must not raise


def test_microsoft_disabled_allowed_with_keycloak_enabled():
    _check_sso_provider_exclusivity(False, True)  # must not raise


def test_microsoft_disabled_allowed_with_keycloak_disabled():
    _check_sso_provider_exclusivity(False, False)  # must not raise


def test_msal_redirect_uri_normalizes_onto_standard_callback_path():
    assert (
        _normalize_msal_redirect_uri("http://localhost:3003/auth-callback")
        == "http://localhost:3003/auth/callback"
    )


def test_msal_redirect_uri_normalizes_login_page_path():
    assert (
        _normalize_msal_redirect_uri("https://host.example.com/login")
        == "https://host.example.com/auth/callback"
    )


def test_msal_redirect_uri_preserves_scheme_host_port():
    assert (
        _normalize_msal_redirect_uri("https://agentos.example.com:9443/whatever")
        == "https://agentos.example.com:9443/auth/callback"
    )


def test_msal_redirect_uri_empty_stays_empty():
    assert _normalize_msal_redirect_uri("") == ""


def test_msal_redirect_uri_malformed_passes_through_unchanged():
    # No scheme/host to anchor on — leave as-is so the real error (a bad env
    # value) surfaces as an Azure AD redirect_uri_mismatch, not a silent swap.
    assert _normalize_msal_redirect_uri("not-a-url") == "not-a-url"
