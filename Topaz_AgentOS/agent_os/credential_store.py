"""
Enterprise Credential Store — platform-level sensitive management.

Owned by agent_os (platform / security layer). Consumed by skills, scripts,
and any LLM tool that needs to fetch a sensitive. agent_os is tenant-agnostic —
callers must pass `config_dir` explicitly.

Features:
- Encryption at rest (Fernet AES-128, lazy import — falls back to plaintext
  if `cryptography` is not installed)
- Consumer-scoped access control
- Audit trail for all access
- Pluggable backends (Env, File, future Vault)
- No sensitive in logs

Usage:
    from agent_os.credential_store import CredentialStore

    store = CredentialStore.create(config_dir=Path("/path/to/config"))
    cred = store.get("cloudtech_api", consumer="fa_ap", purpose="API call")

Optional extras:
    pip install pyyaml          # required for the file backend
    pip install cryptography    # required for at-rest encryption (lazy)
"""

import os
import logging
import warnings
import hashlib
import threading
import time
from .atomic_io import locked_rmw_yaml_sync
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Case-insensitive substrings marking a credential field as secret-bearing.
_SENSITIVE_KEY_TOKENS = (
    "secret", "token", "password", "passwd", "pwd", "credential", "private", "api_key", "apikey",
)


def _is_sensitive_key(key: str) -> bool:
    """True if a credential field key looks secret-bearing (substring match).

    Used to (a) encrypt-at-rest in ``set()`` and (b) exclude the field from the
    non-sensitive ``fields`` map returned by ``get_metadata()``. Conservative by
    design: over-classifying a benign field only encrypts/hides it, never leaks it.
    Reserved structural keys (type/scope/ttl/metadata) are handled separately.
    """
    k = str(key).lower()
    if k == "key" or k.endswith("_key"):
        return True
    return any(tok in k for tok in _SENSITIVE_KEY_TOKENS)



@dataclass
class Credential:
    """Represents a resolved credential."""
    name: str
    type: str  # bearer, basic, api_key, oauth2
    value: Dict[str, str]  # {"token": "xxx"} or {"username": "x", "PWD": "y"}
    scope: List[str] = field(default_factory=list)  # which consumers can access
    ttl: Optional[int] = None  # seconds until refresh needed
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_header(self) -> Dict[str, str]:
        """Convert credential to HTTP header(s)."""
        if self.type == "bearer":
            return {"Authorization": f"Bearer {self.value.get('token', '')}"}
        elif self.type == "api_key":
            header_name = self.metadata.get("header_name", "X-API-Key")
            return {header_name: self.value.get("key", "")}
        elif self.type == "basic":
            import base64
            user = self.value.get("username", "")
            pwd = self.value.get("password", "")
            encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        else:
            return {}

    def to_curl_args(self) -> str:
        """Convert credential to curl -H arguments."""
        headers = self.to_header()
        args = []
        for name, value in headers.items():
            args.append(f"-H '{name}: {value}'")
        return " ".join(args)


@dataclass
class AuditEntry:
    """Audit log entry for credential access."""
    timestamp: str
    credential_name: str
    consumer: str
    purpose: str
    accessor: str  # user_id or agent_id
    success: bool
    error: Optional[str] = None



class CredentialBackend(ABC):
    @abstractmethod
    def get(self, name: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_names(self) -> List[str]:
        pass

    @abstractmethod
    def set(self, name: str, data: Dict[str, Any]) -> bool:
        pass



class EnvBackend(CredentialBackend):
    """
    Read credentials from environment variables.

    Format: CRED_{NAME}_{FIELD}
    Example:
        CRED_CLOUDTECH_API_TYPE=bearer
        CRED_CLOUDTECH_API_TOKEN=xxx
    """

    PREFIX = "CRED_"

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        prefix = f"{self.PREFIX}{name.upper()}_"
        data = {}
        for key, value in os.environ.items():
            if key.startswith(prefix):
                field = key[len(prefix):].lower()
                data[field] = value
        if not data:
            return None
        cred_type = data.pop("type", "bearer")
        scope = data.pop("scope", "").split(",") if data.get("scope") else []
        return {
            "type": cred_type,
            "value": data,
            "scope": [s.strip() for s in scope if s.strip()],
        }

    def list_names(self) -> List[str]:
        names = set()
        for key in os.environ:
            if key.startswith(self.PREFIX):
                parts = key[len(self.PREFIX):].split("_")
                if len(parts) >= 2:
                    names.add("_".join(parts[:-1]).lower())
        return list(names)

    def set(self, name: str, data: Dict[str, Any]) -> bool:
        return False



class FernetFileBackend(CredentialBackend):
    """
    Store credentials in YAML file, optionally encrypted at rest.

    Master key from: CREDENTIAL_MASTER_KEY env var (optional).
    Without a master key, file is read/written in plaintext.

    Unencrypted format (for editing):
    ```yaml
    cloudtech_api:
      type: bearer
      token: "actual_secret"
      scope: [general, invoice]
    ```
    """

    ENCRYPTED_PREFIX = "encrypted:"

    def __init__(self, config_path: Path, master_key: Optional[str] = None):
        self.config_path = config_path
        self._fernet = None
        self._cache: Dict[str, Any] = {}
        self._cache_mtime: float = 0

        key = master_key or os.getenv("CREDENTIAL_MASTER_KEY")
        if key:
            try:
                from cryptography.fernet import Fernet
                if len(key) != 44:
                    import base64
                    derived = hashlib.sha256(key.encode()).digest()
                    key = base64.urlsafe_b64encode(derived).decode()
                self._fernet = Fernet(key.encode())
                logger.info("CredentialStore: Encryption enabled")
            except ImportError:
                logger.warning(
                    "CredentialStore: cryptography not installed, using plaintext. "
                    "Install with: pip install cryptography"
                )
            except Exception as e:
                logger.warning(f"CredentialStore: Encryption init failed: {e}")

    def _load(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        mtime = self.config_path.stat().st_mtime
        if mtime == self._cache_mtime and self._cache:
            return self._cache
        try:
            import yaml
            content = self.config_path.read_text(encoding='utf-8')
            data = yaml.safe_load(content) or {}
            for name, cred in data.items():
                if isinstance(cred, dict):
                    for field, value in cred.items():
                        if isinstance(value, str) and value.startswith(self.ENCRYPTED_PREFIX):
                            cred[field] = self._decrypt(value)
            self._cache = data
            self._cache_mtime = mtime
            return data
        except Exception as e:
            logger.error(f"CredentialStore: Failed to load {self.config_path}: {e}")
            return {}

    def _encrypt(self, value: str) -> str:
        if not self._fernet:
            return value
        encrypted = self._fernet.encrypt(value.encode()).decode()
        return f"{self.ENCRYPTED_PREFIX}{encrypted}"

    def _decrypt(self, value: str) -> str:
        if not value.startswith(self.ENCRYPTED_PREFIX):
            return value
        encrypted = value[len(self.ENCRYPTED_PREFIX):]
        if not self._fernet:
            logger.warning("CredentialStore: Cannot decrypt without master key")
            return "[ENCRYPTED]"
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except Exception as e:
            logger.error(f"CredentialStore: Decryption failed: {e}")
            return "[DECRYPT_FAILED]"

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        data = self._load()
        cred = data.get(name)
        if not cred:
            return None
        cred_type = cred.get("type", "bearer")
        scope = cred.get("scope", [])
        if isinstance(scope, str):
            scope = [s.strip() for s in scope.split(",")]
        value = {}
        reserved = {"type", "scope", "ttl", "metadata"}
        for k, v in cred.items():
            if k not in reserved:
                value[k] = v
        return {
            "type": cred_type,
            "value": value,
            "scope": scope,
            "ttl": cred.get("ttl"),
            "metadata": cred.get("metadata", {}),
        }

    def list_names(self) -> List[str]:
        return list(self._load().keys())

    def set(self, name: str, data: Dict[str, Any]) -> bool:
        try:
            cred = dict(data)
            _reserved = {"type", "scope", "ttl", "metadata"}
            _encrypt = self._encrypt
            _prefix = self.ENCRYPTED_PREFIX
            _name = name
            # Encrypt every secret-bearing field, not just the legacy names.
            for field in list(cred.keys()):
                if field in _reserved:
                    continue
                if _is_sensitive_key(field) and not str(cred[field]).startswith(_prefix):
                    cred[field] = _encrypt(str(cred[field]))

            def _merge(current: dict) -> dict:
                current[_name] = cred
                return current

            locked_rmw_yaml_sync(self.config_path, _merge)
            self._cache = {}
            self._cache_mtime = 0
            logger.info(f"CredentialStore: Saved credential '{name}'")
            return True
        except Exception as e:
            logger.error(f"CredentialStore: Failed to save '{name}': {e}")
            return False

    def delete(self, name: str) -> bool:
        """Remove a credential entry from the YAML file. Returns True if found and removed."""
        try:
            data = self._load()
            if name not in data:
                return False

            def _remove(current: dict) -> dict:
                current.pop(name, None)
                return current

            locked_rmw_yaml_sync(self.config_path, _remove)
            self._cache = {}
            self._cache_mtime = 0
            logger.info(f"CredentialStore: Deleted credential '{name}'")
            return True
        except Exception as e:
            logger.error(f"CredentialStore: Failed to delete '{name}': {e}")
            return False

    def get_metadata(self, name: str) -> dict | None:
        """Return credential metadata without sensitive values (safe for API responses)."""
        data = self._load()
        cred = data.get(name)
        if not cred or not isinstance(cred, dict):
            return None
        reserved = {"type", "scope", "ttl", "metadata"}
        # Hide structural and secret-bearing fields from the API.
        fields = {k: v for k, v in cred.items() if k not in reserved and not _is_sensitive_key(k)}
        return {
            "name": name,
            "type": cred.get("type", "unknown"),
            "scope": cred.get("scope", []),
            "ttl": cred.get("ttl"),
            "metadata": cred.get("metadata", {}),
            "has_value": any(_is_sensitive_key(k) for k in cred if k not in reserved),
            "fields": fields,
        }

    def list_metadata(self) -> list[dict]:
        """Return metadata for all credentials without sensitive values."""
        data = self._load()
        return [self.get_metadata(name) for name in data if self.get_metadata(name)]



def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


_WIN_CA_BUNDLE_CACHE: Optional[str] = None


def _windows_ca_bundle() -> Optional[str]:
    """Build a PEM bundle from the Windows trust store (ROOT + CA) and cache it.

    The Infosys internal CA (InfosysCAMCH), which signs the corporate Vault
    certificate, lives in the Windows trust store but is NOT in certifi's default
    bundle. `requests` cannot read the Windows store directly, so we export it to
    a temp PEM once per process and point `verify=` at it. Returns None on any
    non-Windows platform or if export fails (caller falls back to requests default).
    """
    global _WIN_CA_BUNDLE_CACHE
    if _WIN_CA_BUNDLE_CACHE and os.path.exists(_WIN_CA_BUNDLE_CACHE):
        return _WIN_CA_BUNDLE_CACHE
    try:
        import ssl
        import tempfile
        pems, seen = [], set()
        for store in ("ROOT", "CA"):
            for cert_bytes, enc, _trust in ssl.enum_certificates(store):
                if enc != "x509_asn" or cert_bytes in seen:
                    continue
                seen.add(cert_bytes)
                pems.append(ssl.DER_cert_to_PEM_cert(cert_bytes))
        if not pems:
            return None
        fd, path = tempfile.mkstemp(prefix="agentos_win_ca_", suffix=".pem")
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write("\n".join(pems))
        _WIN_CA_BUNDLE_CACHE = path
        logger.info("VaultBackend: built Windows trust-store CA bundle (%d certs)", len(pems))
        return path
    except Exception as e:  # pragma: no cover - platform/permission dependent
        logger.warning("VaultBackend: could not build Windows CA bundle: %s", e)
        return None


def _resolve_vault_verify() -> Any:
    """Return the `verify` argument for requests calls to Vault.

    Precedence: explicit disable → explicit bundle → existing corporate bundle →
    Windows trust store (win32) → requests default (certifi).
    """
    if not _env_flag("VAULT_SSL_VERIFY", True):
        return False
    explicit = os.getenv("VAULT_CA_BUNDLE", "").strip()
    if explicit:
        return explicit
    corp = (os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE") or "").strip()
    if corp:
        return corp
    import sys
    if sys.platform == "win32":
        bundle = _windows_ca_bundle()
        if bundle:
            return bundle
    return True


class VaultBackend(CredentialBackend):
    """Read secrets from HashiCorp Vault (KV v2) via AppRole auth.

    Read-only backend added to the CredentialStore chain when ``VAULT_ENABLED``
    is set. Local backends (env/file) take precedence — Vault is the fallback
    source. Fails closed: any auth/read/network error resolves to ``None`` (the
    store then audits a miss); raw secrets and tokens are never logged.

    Name → path convention: the credential name IS the KV secret path *within*
    the mount. E.g. with ``VAULT_KV_MOUNT=dcm_staging`` a lookup of
    ``"dcm_staging/network"`` reads ``dcm_staging/data/dcm_staging/network``.
    The resolved ``Credential.value`` is the full key/value map of that secret
    (e.g. ``{"F5_Username": ..., "F5_Password": ...}``).
    """

    def __init__(
        self,
        addr: str,
        role_id: str,
        secret_id: str,
        *,
        namespace: str = "",
        kv_mount: str = "secret",
        kv_version: int = 2,
        approle_mount: str = "approle",
        static_token: str = "",
        name_prefix: str = "",
        cache_ttl: int = 300,
        default_type: str = "generic",
        timeout: int = 20,
    ) -> None:
        self.addr = addr.rstrip("/")
        self.role_id = role_id
        self.secret_id = secret_id
        self.namespace = namespace.strip()
        self.kv_mount = kv_mount.strip("/")
        self.kv_version = int(kv_version)
        self.approle_mount = approle_mount.strip("/")
        self.static_token = static_token.strip()
        self.name_prefix = name_prefix.strip()
        self.cache_ttl = max(0, int(cache_ttl))
        self.default_type = default_type or "generic"
        self.timeout = int(timeout)
        self._verify = _resolve_vault_verify()
        self._lock = threading.Lock()
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._cache: Dict[str, tuple] = {}  # name -> (expiry_ts, raw_cred dict)

    @classmethod
    def from_env(cls) -> Optional["VaultBackend"]:
        """Build from VAULT_* env vars. Returns None (with a warning) if the
        minimum required config is absent, so a misconfigured deployment keeps
        working on its local backends instead of crashing at startup."""
        addr = os.getenv("VAULT_ADDR", "").strip()
        role_id = os.getenv("VAULT_ROLE_ID", "").strip()
        secret_id = os.getenv("VAULT_SECRET_ID", "").strip()
        static_token = os.getenv("VAULT_TOKEN", "").strip()
        if not addr or (not (role_id and secret_id) and not static_token):
            logger.warning(
                "VaultBackend: VAULT_ENABLED set but VAULT_ADDR + "
                "(VAULT_ROLE_ID/VAULT_SECRET_ID or VAULT_TOKEN) are incomplete; "
                "Vault backend disabled."
            )
            return None
        return cls(
            addr=addr,
            role_id=role_id,
            secret_id=secret_id,
            namespace=os.getenv("VAULT_NAMESPACE", ""),
            kv_mount=os.getenv("VAULT_KV_MOUNT", "secret"),
            kv_version=int(os.getenv("VAULT_KV_API_VERSION", "2") or "2"),
            approle_mount=os.getenv("VAULT_APPROLE_MOUNT", "approle"),
            static_token=static_token,
            name_prefix=os.getenv("VAULT_NAME_PREFIX", ""),
            cache_ttl=int(os.getenv("VAULT_SECRET_CACHE_TTL", "300") or "300"),
            default_type=os.getenv("VAULT_DEFAULT_CRED_TYPE", "generic"),
        )


    def _headers(self, token: str = "") -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.namespace:
            h["X-Vault-Namespace"] = self.namespace
        if token:
            h["X-Vault-Token"] = token
        return h

    def _get_token(self) -> Optional[str]:
        """Return a valid client token, logging in via AppRole if needed."""
        if self.static_token:
            return self.static_token
        now = time.time()
        with self._lock:
            if self._token and now < self._token_expiry:
                return self._token
            try:
                import requests
                url = f"{self.addr}/v1/auth/{self.approle_mount}/login"
                r = requests.post(
                    url,
                    json={"role_id": self.role_id, "secret_id": self.secret_id},
                    headers=self._headers(),
                    verify=self._verify,
                    timeout=self.timeout,
                )
            except Exception as e:
                logger.warning("VaultBackend: AppRole login request failed: %s", type(e).__name__)
                return None
            if r.status_code != 200:
                logger.warning("VaultBackend: AppRole login failed (HTTP %s)", r.status_code)
                return None
            # Fail closed on a malformed body.
            try:
                payload = r.json() or {}
            except Exception:
                logger.warning("VaultBackend: AppRole login returned invalid JSON")
                return None
            auth = payload.get("auth") if isinstance(payload, dict) else None
            if not isinstance(auth, dict):
                logger.warning("VaultBackend: AppRole login response missing auth object")
                return None
            token = auth.get("client_token", "")
            if not token:
                logger.warning("VaultBackend: AppRole login returned no client_token")
                return None
            lease = int(auth.get("lease_duration") or 0)
            # Expire early, but keep expiry inside the lease.
            self._token = token
            self._token_expiry = now + max(1, lease - 60) if lease else now + 300
            return token

    def _read_path(self, secret_path: str) -> Optional[Dict[str, Any]]:
        """GET a KV secret. Returns the flat key/value data map, or None."""
        token = self._get_token()
        if not token:
            return None
        if self.kv_version == 2:
            url = f"{self.addr}/v1/{self.kv_mount}/data/{secret_path}"
        else:
            url = f"{self.addr}/v1/{self.kv_mount}/{secret_path}"
        try:
            import requests
            r = requests.get(
                url, headers=self._headers(token), verify=self._verify, timeout=self.timeout
            )
        except Exception as e:
            logger.warning("VaultBackend: read request failed: %s", type(e).__name__)
            return None
        if r.status_code == 404:
            return None  # covered by policy but absent
        if r.status_code != 200:
            # 403 = policy gap; do not leak path detail beyond the status.
            logger.warning("VaultBackend: read denied/failed (HTTP %s)", r.status_code)
            return None
        # Fail closed on a malformed 200.
        try:
            body = r.json() or {}
        except Exception:
            logger.warning("VaultBackend: KV read returned invalid JSON")
            return None
        if not isinstance(body, dict):
            return None
        if self.kv_version == 2:
            data = body.get("data")
            inner = data.get("data") if isinstance(data, dict) else None
            return inner if isinstance(inner, dict) else None
        data = body.get("data")
        return data if isinstance(data, dict) else None

    def _name_matches(self, name: str) -> bool:
        """Only query Vault for names that look like a Vault path, so ordinary
        local-credential misses never trigger a network round-trip."""
        if self.name_prefix:
            return name.startswith(self.name_prefix)
        return "/" in name


    def get(self, name: str) -> Optional[Dict[str, Any]]:
        if not name or not self._name_matches(name):
            return None
        now = time.time()
        cached = self._cache.get(name)
        if cached and now < cached[0]:
            return cached[1]
        secret_path = name[len(self.name_prefix):] if self.name_prefix else name
        secret_path = secret_path.strip("/")
        data = self._read_path(secret_path)
        if not data:
            return None
        raw = {
            "type": self.default_type,
            "value": {str(k): str(v) for k, v in data.items()},
            "scope": [],  # kernel entitlement gate still applies to connections
            "ttl": None,
            "metadata": {"source": "vault", "mount": self.kv_mount, "path": secret_path},
        }
        if self.cache_ttl:
            self._cache[name] = (now + self.cache_ttl, raw)
        return raw

    def list_names(self) -> List[str]:
        # Enumerating requires LIST capability we may not hold; keep quiet.
        return []

    def set(self, name: str, data: Dict[str, Any]) -> bool:
        return False  # read-only backend

    def health(self) -> Dict[str, Any]:
        return {
            "backend": "vault",
            "addr": self.addr,
            "namespace": self.namespace,
            "kv_mount": self.kv_mount,
            "kv_version": self.kv_version,
            "auth": "token" if self.static_token else "approle",
            "ssl_verify": self._verify is not False,
            "has_token": bool(self._token or self.static_token),
            "cached_secrets": len(self._cache),
        }



class CredentialStore:
    """
    Platform-level credential store with audit logging and consumer scoping.

    `config_dir` is required — agent_os is tenant-agnostic; callers (kernel,
    skills, scripts) must pass the directory containing credentials.yaml and
    credential_audit.log.
    """

    def __init__(
        self,
        backends: List[CredentialBackend],
        audit_path: Optional[Path] = None,
        default_accessor: str = "agent",
    ):
        self.backends = backends
        self.audit_path = audit_path
        self.default_accessor = default_accessor
        self._audit_buffer: List[AuditEntry] = []

    @classmethod
    def create(
        cls,
        config_dir: Path,
        enable_env: bool = True,
        enable_file: bool = True,
        enable_vault: Optional[bool] = None,
    ) -> "CredentialStore":
        """
        Factory: env backend + (optional) Fernet file backend in config_dir,
        plus an optional read-only HashiCorp Vault backend.

        Args:
            config_dir: Directory containing credentials.yaml + credential_audit.log.
                        REQUIRED — agent_os is tenant-agnostic.
            enable_vault: Add the Vault backend to the chain. None (default) means
                        auto-detect from ``VAULT_ENABLED`` env (off by default, so
                        behavior is unchanged unless a deployment opts in).

        Backend order is env → file → vault: local credentials always take
        precedence and Vault is consulted only for names the local backends miss.
        """
        config_dir = Path(config_dir)
        backends: List[CredentialBackend] = []
        if enable_env:
            backends.append(EnvBackend())
        if enable_file:
            backends.append(FernetFileBackend(config_dir / "credentials.yaml"))
        if enable_vault is None:
            enable_vault = _env_flag("VAULT_ENABLED", False)
        if enable_vault:
            vault = VaultBackend.from_env()
            if vault is not None:
                backends.append(vault)
        return cls(
            backends=backends,
            audit_path=config_dir / "credential_audit.log",
        )

    @staticmethod
    def _resolve_consumer_kwarg(consumer: Optional[str], kwargs: dict) -> Optional[str]:
        """
        Backwards-compat shim: accept deprecated `skill=` kwarg.
        Remove this and the **kwargs after one release cycle.
        """
        if "skill" in kwargs:
            warnings.warn(
                "CredentialStore: 'skill' parameter is deprecated; use 'consumer'",
                DeprecationWarning,
                stacklevel=3,
            )
            if consumer is None:
                consumer = kwargs.pop("skill")
            else:
                kwargs.pop("skill")
        if kwargs:
            raise TypeError(f"Unexpected keyword arguments: {list(kwargs)}")
        return consumer

    def get(
        self,
        name: str,
        consumer: Optional[str] = None,
        purpose: str = "unknown",
        accessor: Optional[str] = None,
        **kwargs,
    ) -> Optional[Credential]:
        """
        Retrieve a credential by name with consumer-scoped access control + audit.

        Args:
            name:     Credential identifier (e.g., "cloudtech_api")
            consumer: Requesting party (skill name, agent id, script name).
                      Checked against the credential's `scope` list.
            purpose:  Audit annotation — why this credential is being requested.
            accessor: User/agent ID (for audit).
        """
        consumer = self._resolve_consumer_kwarg(consumer, kwargs)
        accessor = accessor or self.default_accessor

        raw_cred = None
        for backend in self.backends:
            raw_cred = backend.get(name)
            if raw_cred:
                break

        if not raw_cred:
            self._audit(name, consumer or "unknown", purpose, accessor, False, "NOT_FOUND")
            logger.warning(f"Credential '{name}' not found")
            return None

        # Vault connections hold auth material; only readable via resolve_vault_secret().
        if (raw_cred.get("type") or "").lower() == "vault":
            self._audit(name, consumer or "any", purpose, accessor, False, "VAULT_CONNECTION_NOT_DIRECTLY_READABLE")
            logger.warning(
                "Credential '%s' is a Vault connection; its auth fields are not "
                "directly readable — use resolve_vault_secret() / ${VAULT:...}", name,
            )
            return None

        scope = raw_cred.get("scope", [])
        if scope and (not consumer or consumer not in scope):
            self._audit(
                name, consumer or "missing_consumer", purpose, accessor, False,
                f"SCOPE_DENIED: {consumer or 'missing_consumer'} not in {scope}",
            )
            logger.warning(f"Credential '{name}' not accessible from consumer '{consumer or 'missing_consumer'}'")
            return None

        cred = Credential(
            name=name,
            type=raw_cred.get("type", "bearer"),
            value=raw_cred.get("value", {}),
            scope=scope,
            ttl=raw_cred.get("ttl"),
            metadata=raw_cred.get("metadata", {}),
        )
        self._audit(name, consumer or "any", purpose, accessor, True, None)
        logger.info(f"Credential '{name}' accessed by {accessor} for: {purpose}")
        return cred

    def resolve_vault_secret(
        self,
        name: str,
        path: str,
        key: Optional[str] = None,
        *,
        consumer: Optional[str] = None,
        purpose: str = "vault secret",
        accessor: Optional[str] = None,
    ) -> Optional[Credential]:
        """Resolve a secret from a user-defined Vault *connection* stored in
        credentials.yaml as a ``type: vault`` entry.

        Unlike the global env-configured VaultBackend (one platform Vault via
        VAULT_* env), the connection here — addr / namespace / mount / AppRole
        or token — lives in the credential file and is consumer-scoped exactly
        like any other credential: a skill must be in the connection's ``scope``
        to read through it. The secret is fetched below the agent and never
        logged. Fails closed (returns None) on any miss, scope-denial, or error.

        Args:
            name:     Name of the ``type: vault`` connection credential.
            path:     KV secret path within the connection's mount (e.g. "network/prod").
            key:      Field within that secret to return. None → the whole map.
            consumer: Requesting skill; checked against the connection's scope.
        """
        accessor = accessor or self.default_accessor

        raw = None
        for backend in self.backends:
            raw = backend.get(name)
            if raw:
                break
        if not raw:
            self._audit(name, consumer or "unknown", purpose, accessor, False, "NOT_FOUND")
            logger.warning("Vault connection '%s' not found", name)
            return None

        scope = raw.get("scope", [])
        if scope and (not consumer or consumer not in scope):
            self._audit(
                name, consumer or "missing_consumer", purpose, accessor, False,
                f"SCOPE_DENIED: {consumer or 'missing_consumer'} not in {scope}",
            )
            logger.warning(
                "Vault connection '%s' not accessible from consumer '%s'",
                name, consumer or "missing_consumer",
            )
            return None

        if (raw.get("type") or "").lower() != "vault":
            self._audit(name, consumer or "any", purpose, accessor, False, "NOT_A_VAULT_CONNECTION")
            logger.warning("Credential '%s' is not a Vault connection (type=%r)", name, raw.get("type"))
            return None

        client = self._vault_client_for(name, raw)
        if client is None:
            self._audit(name, consumer or "any", purpose, accessor, False, "VAULT_CONFIG_INVALID")
            return None

        data = client._read_path((path or "").strip("/"))
        if not data:
            self._audit(name, consumer or "any", purpose, accessor, False, "VAULT_READ_FAILED")
            logger.warning("Vault read via '%s' failed or returned nothing", name)
            return None

        v = raw.get("value", {}) or {}
        cred_type = str(v.get("cred_type") or v.get("credential_type") or "generic")
        if key is not None:
            secret_val = data.get(key)
            if secret_val is None:
                self._audit(name, consumer or "any", purpose, accessor, False, f"VAULT_KEY_MISSING: {key}")
                logger.warning("Vault secret has no key '%s' (via connection '%s')", key, name)
                return None
            out_value = {key: str(secret_val)}
        else:
            out_value = {str(k): str(val) for k, val in data.items()}

        self._audit(name, consumer or "any", purpose, accessor, True, None)
        logger.info("Vault secret resolved via '%s' by %s for: %s", name, accessor, purpose)
        return Credential(
            name=f"{name}:{(path or '').strip('/')}" + (f"#{key}" if key else ""),
            type=cred_type,
            value=out_value,
            scope=scope,
            ttl=raw.get("ttl"),
            metadata={"source": "vault", "connection": name, "path": (path or "").strip("/")},
        )

    def _vault_client_for(self, name: str, raw: Dict[str, Any]) -> Optional["VaultBackend"]:
        """Build (and cache) a VaultBackend client from a stored connection.

        Cached per connection name + a fingerprint of its connection fields, so a
        rotated connection transparently rebuilds the client (dropping its stale
        token/secret cache) on the next lookup.
        """
        v = raw.get("value", {}) or {}
        addr = str(v.get("addr") or v.get("url") or "").strip()
        if not addr:
            logger.warning("Vault connection '%s' has no addr/url", name)
            return None
        role_id = str(v.get("role_id") or "").strip()
        secret_id = str(v.get("secret_id") or "").strip()
        static_token = str(v.get("token") or "").strip()
        if not static_token and not (role_id and secret_id):
            logger.warning("Vault connection '%s' needs a token or role_id+secret_id", name)
            return None

        kv_mount = str(v.get("kv_mount") or v.get("mount") or "secret")
        kv_version = int(v.get("kv_version", 2) or 2)
        approle_mount = str(v.get("approle_mount") or "approle")
        namespace = str(v.get("namespace") or "")
        fingerprint = hash((
            addr, namespace, kv_mount, str(kv_version), approle_mount,
            role_id, secret_id, static_token,
        ))
        cache = getattr(self, "_vault_clients", None)
        if cache is None:
            cache = self._vault_clients = {}
        hit = cache.get(name)
        if hit and hit[0] == fingerprint:
            return hit[1]
        client = VaultBackend(
            addr=addr,
            role_id=role_id,
            secret_id=secret_id,
            namespace=namespace,
            kv_mount=kv_mount,
            kv_version=kv_version,
            approle_mount=approle_mount,
            static_token=static_token,
            cache_ttl=int(v.get("cache_ttl", 300) or 300),
            default_type=str(v.get("cred_type") or "generic"),
        )
        cache[name] = (fingerprint, client)
        return client

    def list(self, consumer: Optional[str] = None, **kwargs) -> List[str]:
        """List credential names, optionally filtered by consumer scope."""
        consumer = self._resolve_consumer_kwarg(consumer, kwargs)
        names = set()
        for backend in self.backends:
            names.update(backend.list_names())
        if not consumer:
            return list(names)
        accessible = []
        for name in names:
            for backend in self.backends:
                raw = backend.get(name)
                if raw:
                    scope = raw.get("scope", [])
                    if not scope or consumer in scope:
                        accessible.append(name)
                    break
        return accessible

    def resolve_for_api(
        self,
        metadata: Dict[str, Any],
        consumer: Optional[str] = None,
        purpose: str = "API call",
        **kwargs,
    ) -> Optional[Credential]:
        """Resolve credential from API metadata (looks for credential_ref)."""
        consumer = self._resolve_consumer_kwarg(consumer, kwargs)
        cred_ref = metadata.get("credential_ref")
        if not cred_ref:
            auth = metadata.get("auth")
            if auth == "none" or auth is None:
                return None
            logger.debug(f"No credential_ref in metadata, auth={auth}")
            return None
        return self.get(cred_ref, consumer=consumer, purpose=purpose)

    def _audit(
        self,
        name: str,
        consumer: str,
        purpose: str,
        accessor: str,
        success: bool,
        error: Optional[str],
    ):
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            credential_name=name,
            consumer=consumer,
            purpose=purpose,
            accessor=accessor,
            success=success,
            error=error,
        )
        self._audit_buffer.append(entry)
        if self.audit_path and len(self._audit_buffer) >= 10:
            self._flush_audit()

    def _flush_audit(self):
        if not self.audit_path or not self._audit_buffer:
            return
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a") as f:
                for entry in self._audit_buffer:
                    status = "OK" if entry.success else f"DENIED:{entry.error}"
                    # Column stays "skill" for audit-log backward compatibility.
                    line = (
                        f"{entry.timestamp}|{entry.accessor}|{entry.consumer}|"
                        f"{entry.credential_name}|{entry.purpose}|{status}\n"
                    )
                    f.write(line)
            self._audit_buffer = []
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")



_default_store: Optional[CredentialStore] = None


def get_credential_store(config_dir: Path) -> CredentialStore:
    """Get or create the default credential store instance."""
    global _default_store
    if _default_store is None:
        _default_store = CredentialStore.create(config_dir=config_dir)
    return _default_store


def get_credential(
    name: str,
    config_dir: Path,
    consumer: Optional[str] = None,
    purpose: str = "unknown",
    **kwargs,
) -> Optional[Credential]:
    """Convenience function to get a credential from the default store."""
    if "skill" in kwargs:
        warnings.warn(
            "get_credential: 'skill' parameter is deprecated; use 'consumer'",
            DeprecationWarning,
            stacklevel=2,
        )
        if consumer is None:
            consumer = kwargs.pop("skill")
        else:
            kwargs.pop("skill")
    if kwargs:
        raise TypeError(f"Unexpected keyword arguments: {list(kwargs)}")
    return get_credential_store(config_dir).get(name, consumer=consumer, purpose=purpose)
