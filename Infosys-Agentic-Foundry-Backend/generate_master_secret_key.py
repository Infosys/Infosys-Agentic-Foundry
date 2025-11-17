#!/usr/bin/env python3
"""
Minimal utility to generate and print a secure master secret key.

Usage (PowerShell):
    python -m src.tools.generate_master_secret_key
or
    python src/tools/generate_master_secret_key.py

Outputs a 256-bit (32 random bytes) base64-encoded secret each run.
"""

from __future__ import annotations
import base64
import secrets

DEFAULT_NUM_BYTES = 32  # 256 bits


def generate_master_secret_key(num_bytes: int = DEFAULT_NUM_BYTES) -> str:
    """
    Generate a cryptographically secure random key.

    Parameters
    ----------
    num_bytes : int
        Number of random bytes (>=16 recommended). Default 32.

    Returns
    -------
    str
        Base64-encoded key string.
    """
    if num_bytes < 16:
        raise ValueError("num_bytes must be >= 16 for adequate entropy")
    key_bytes = secrets.token_bytes(num_bytes)
    return base64.b64encode(key_bytes).decode("ascii")


def main() -> None:
    # Simple direct print for capture or piping.
    print(generate_master_secret_key())


if __name__ == "__main__":  # pragma: no cover
    main()