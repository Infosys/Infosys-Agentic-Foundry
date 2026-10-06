# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

import os
from typing import Optional, Dict, Any

import jwt
from telemetry_wrapper import logger as log

INITIAL_SUPERADMIN_EMAILS: list = [
    e.strip().lower()
    for e in os.getenv("INITIAL_SUPERADMIN_EMAILS", "").split(",")
    if e.strip()
]


class AzureADService:
    """
    Azure AD pass-through service.

    Decodes the JWT payload without signature verification.
    Identity is resolved by looking up the email claim in the IAF database;
    no JWKS, audience, or appid checks are performed.
    """

    async def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode an Azure AD token without signature verification and return claims.
        Returns None if the token is not a valid JWT structure.
        """
        try:
            claims = jwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["RS256", "HS256"],
            )
            log.info(f"Azure AD token decoded for upn={claims.get('upn') or claims.get('email')}")
            return claims
        except Exception as e:
            log.warning(f"Azure AD token decode failed: {e}")
            return None

    # Keep validate_token as an alias so callers don't need updating.
    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        return await self.decode_token(token)
