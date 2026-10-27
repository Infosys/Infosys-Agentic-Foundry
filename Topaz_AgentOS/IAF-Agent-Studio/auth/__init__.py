"""
IAF Agent Studio — Auth package

Provides pluggable authentication with provider abstraction.
Phase 1: LocalAuthProvider (bcrypt + JWT)
Phase 2: MicrosoftProvider, GoogleProvider (OIDC/OAuth2)
"""

from auth.base import AuthProvider, UserRecord, UserStore

__all__ = ["AuthProvider", "UserRecord", "UserStore"]
