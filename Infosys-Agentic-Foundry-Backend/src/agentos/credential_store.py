# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Credential Store — Encrypted credential management for AgentOS skill agents.

Credentials (API keys, passwords, tokens) referenced in skill .md files
can be encrypted at rest using Fernet symmetric encryption, rather than
stored as plaintext.

Inspired by AgentPro's credential_store.py pattern:
  - Per-agent encryption keys stored in `.secrets/agent.key`
  - Credentials stored in `.secrets/credentials.enc` (JSON → encrypted)
  - Lazy decryption, in-memory caching for the request lifecycle

Usage:
    store = CredentialStore(agent_dir)
    store.set("hr_api_token", "Bearer eyJ...")
    token = store.get("hr_api_token")  # decrypted on read
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class CredentialStore:
    """
    Per-agent encrypted credential store using Fernet (AES-128-CBC).

    Falls back to plaintext JSON if the `cryptography` package is not installed
    (with a warning).
    """

    def __init__(self, agent_dir: Path):
        self._agent_dir = Path(agent_dir).resolve()
        self._secrets_dir = self._agent_dir / ".secrets"
        self._key_file = self._secrets_dir / "agent.key"
        self._creds_file = self._secrets_dir / "credentials.enc"
        self._cache: Optional[Dict[str, str]] = None  # lazy loaded

        if not HAS_CRYPTOGRAPHY:
            log.warning(
                "[CredentialStore] 'cryptography' package not installed. "
                "Credentials will be stored as plaintext JSON. "
                "Install with: pip install cryptography"
            )

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _ensure_key(self) -> bytes:
        """Get or create the per-agent encryption key."""
        self._secrets_dir.mkdir(parents=True, exist_ok=True)

        if self._key_file.exists():
            return self._key_file.read_bytes().strip()

        key = Fernet.generate_key() if HAS_CRYPTOGRAPHY else b"plaintext_mode"
        self._key_file.write_bytes(key)
        log.info(f"[CredentialStore] Generated new encryption key for agent")
        self._schedule_blob_sync()
        return key

    def _get_fernet(self) -> Optional[object]:
        """Get a Fernet instance (or None if crypto not available)."""
        if not HAS_CRYPTOGRAPHY:
            return None
        key = self._ensure_key()
        return Fernet(key)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, str]:
        """Load and decrypt all credentials."""
        if self._cache is not None:
            return self._cache

        if not self._creds_file.exists():
            self._cache = {}
            return self._cache

        raw = self._creds_file.read_bytes()

        if HAS_CRYPTOGRAPHY:
            try:
                f = self._get_fernet()
                decrypted = f.decrypt(raw)
                self._cache = json.loads(decrypted.decode("utf-8"))
            except (InvalidToken, Exception) as e:
                log.error(f"[CredentialStore] Failed to decrypt credentials: {e}")
                self._cache = {}
        else:
            # Plaintext fallback
            try:
                self._cache = json.loads(raw.decode("utf-8"))
            except Exception as e:
                log.error(f"[CredentialStore] Failed to load credentials: {e}")
                self._cache = {}

        return self._cache

    def _save(self, data: Dict[str, str]):
        """Encrypt and save all credentials."""
        self._secrets_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2).encode("utf-8")

        if HAS_CRYPTOGRAPHY:
            f = self._get_fernet()
            encrypted = f.encrypt(payload)
            self._creds_file.write_bytes(encrypted)
        else:
            self._creds_file.write_bytes(payload)

        self._cache = data
        self._schedule_blob_sync()

    def _schedule_blob_sync(self):
        """Best-effort push of .secrets/ to blob storage."""
        try:
            import os
            _sp = os.getenv('STORAGE_PROVIDER', '')
            if _sp:
                from src.utils.workspace_blob_sync import WorkspaceBlobSync
                from src.storage import get_storage_client
                _client = get_storage_client(_sp)
                # Extract department/agent_id from the agent_dir path
                # Pattern: .../agent_workspaces/{dept}/agentos_agents/{agent_id}/...
                parts = self._agent_dir.parts
                dept, agent_id = 'General', ''
                for i, p in enumerate(parts):
                    if p == 'agentos_agents' and i > 0 and i + 1 < len(parts):
                        dept = parts[i - 1]
                        agent_id = parts[i + 1]
                        break
                _syncer = WorkspaceBlobSync(
                    storage_client=_client,
                    workspace_root=str(self._agent_dir.parent.parent.parent),
                    department=dept,
                    agent_id=agent_id,
                    project_root=os.path.abspath("."),
                )
                _syncer.schedule_credentials_sync()
        except Exception:
            pass  # non-critical

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, default: str = "") -> str:
        """Get a credential by key. Returns default if not found."""
        creds = self._load()
        return creds.get(key, default)

    def set(self, key: str, value: str):
        """Set a credential. Encrypts and saves immediately."""
        creds = self._load()
        creds[key] = value
        self._save(creds)
        log.info(f"[CredentialStore] Credential '{key}' updated")

    def delete(self, key: str) -> bool:
        """Delete a credential. Returns True if it existed."""
        creds = self._load()
        if key in creds:
            del creds[key]
            self._save(creds)
            log.info(f"[CredentialStore] Credential '{key}' deleted")
            return True
        return False

    def list_keys(self) -> list:
        """List all credential keys (not values)."""
        return list(self._load().keys())

    def has(self, key: str) -> bool:
        """Check if a credential exists."""
        return key in self._load()

    def clear(self):
        """Delete all credentials."""
        self._save({})
        log.info("[CredentialStore] All credentials cleared")

    def export_keys_only(self) -> Dict[str, str]:
        """Export keys with masked values (for audit/display)."""
        creds = self._load()
        return {k: f"***{v[-4:]}" if len(v) > 4 else "****" for k, v in creds.items()}
