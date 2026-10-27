"""Runtime-role parsing, replica guards, and Redis leader leases."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Callable


logger = logging.getLogger("iaf_server")

# OS-backed CSPRNG for backoff jitter (Fortify: Insecure Randomness).
_rng = secrets.SystemRandom()

VALID_RUNTIME_ROLES = frozenset({"api", "scheduler", "queue"})


def parse_runtime_roles(value: str) -> frozenset[str]:
    raw = str(value or "all").strip().lower()
    if raw == "all":
        return VALID_RUNTIME_ROLES
    roles = frozenset(part.strip() for part in raw.split(",") if part.strip())
    invalid = roles - VALID_RUNTIME_ROLES
    if invalid or not roles:
        supported = ", ".join(sorted(VALID_RUNTIME_ROLES))
        bad = ", ".join(sorted(invalid)) or raw
        raise ValueError(f"Invalid STUDIO_RUNTIME_ROLES value {bad!r}; expected all or {supported}")
    return roles


def validate_replica_safety(
    *,
    roles: frozenset[str],
    uvicorn_workers: int,
    queue_worker_replicas: int,
    db_backend: str,
    cc_queue_storage_backend: str = "sqlite",
) -> None:
    embedded_roles = roles.intersection({"scheduler", "queue"})
    if uvicorn_workers > 1 and embedded_roles:
        joined = ", ".join(sorted(embedded_roles))
        raise RuntimeError(
            f"UVICORN_WORKERS={uvicorn_workers} is unsafe while {joined} role(s) are embedded; "
            "run API-only replicas and separate scheduler/queue processes"
        )
    queue_store = (cc_queue_storage_backend or "sqlite").strip().lower()
    db_backend = (db_backend or "sqlite").strip().lower()
    if "queue" in roles and queue_worker_replicas > 1 and not (
        db_backend == "postgres" and queue_store == "postgres"
    ):
        raise RuntimeError(
            "Multiple queue workers require DB_BACKEND=postgres and "
            "CC_QUEUE_STORAGE_BACKEND=postgres; keep QUEUE_WORKER_REPLICAS=1 "
            "for SQLite or non-transactional claim stores"
        )


def validate_enterprise_security_config(
    *,
    strict_mode: bool,
    roles: frozenset[str],
    auth_enabled: bool,
    use_redis_sessions: bool,
    demo_public_surfaces: bool,
    allow_unsigned_file_urls: bool,
    file_url_signing_secret: str,
    queue_ingest_api_key: str,
    cors_allowed_origins: tuple[str, ...],
    agentos_kernel_backend: str = "local",
    agentos_kernel_require_remote: bool = False,
    agentos_kernel_token_secret: str = "",
    jwt_secret_env: str = "",
) -> None:
    if not strict_mode:
        return
    errors: list[str] = []
    if not auth_enabled:
        errors.append("AUTH_ENABLED must be true")
    # JWT_SECRET must be set explicitly; the per-process random default breaks tokens across replicas.
    if len(jwt_secret_env) < 32:
        errors.append(
            "JWT_SECRET must be explicitly set to at least 32 characters "
            "(unset uses a per-process random value that breaks tokens across replicas)"
        )
    if "api" in roles and not use_redis_sessions:
        errors.append("USE_REDIS_SESSIONS must be true for the API role")
    if demo_public_surfaces:
        errors.append("DEMO_PUBLIC_SURFACES must be false")
    if allow_unsigned_file_urls:
        errors.append("ALLOW_UNSIGNED_FILE_URLS must be false")
    if len(file_url_signing_secret) < 32:
        errors.append("FILE_URL_SIGNING_SECRET must contain at least 32 characters")
    if len(queue_ingest_api_key) < 32:
        errors.append("QUEUE_INGEST_API_KEY must contain at least 32 characters")
    if "*" in cors_allowed_origins:
        errors.append("CORS_ALLOWED_ORIGINS must list explicit origins")
    kernel_backend = (agentos_kernel_backend or "local").strip().lower()
    if agentos_kernel_require_remote and kernel_backend != "remote":
        errors.append("AGENTOS_KERNEL_BACKEND must be remote when AGENTOS_KERNEL_REQUIRE_REMOTE=true")
    if kernel_backend == "remote" and len(agentos_kernel_token_secret) < 32:
        errors.append("AGENTOS_KERNEL_TOKEN_SECRET must contain at least 32 characters for remote kernel execution")
    if errors:
        raise RuntimeError("Invalid strict enterprise configuration: " + "; ".join(errors))


@dataclass
class RedisLeaderLease:
    """Small compare-and-renew lease used to elect one scheduler leader."""

    redis_url: str
    key: str
    ttl_seconds: int
    client_factory: Callable[[str], object] | None = None

    def __post_init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self._client = None

    def _redis(self):
        if self._client is None:
            if self.client_factory is not None:
                self._client = self.client_factory(self.redis_url)
            else:
                import redis

                self._client = redis.Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
        return self._client

    def acquire(self) -> bool:
        return bool(self._redis().set(self.key, self.token, nx=True, ex=self.ttl_seconds))

    def renew(self) -> bool:
        result = self._redis().eval(
            """
            if redis.call('get', KEYS[1]) == ARGV[1] then
              return redis.call('expire', KEYS[1], ARGV[2])
            end
            return 0
            """,
            1,
            self.key,
            self.token,
            self.ttl_seconds,
        )
        return bool(result)

    def release(self) -> bool:
        result = self._redis().eval(
            """
            if redis.call('get', KEYS[1]) == ARGV[1] then
              return redis.call('del', KEYS[1])
            end
            return 0
            """,
            1,
            self.key,
            self.token,
        )
        return bool(result)

    def renew_resilient(self, retries: int = 2, base_delay: float = 0.2) -> bool:
        """Renew the lease while tolerating a transient Redis blip.

        Returns ``True`` while leadership is safely retained, ``False`` when it
        should be relinquished. This method **never raises** — a dropped Redis
        heartbeat must not propagate out and kill the scheduler leader loop.

        Distinguishes two failure kinds:

        * ``renew()`` returns falsy → the lease is *definitively* lost (another
          token owns the key, or it expired). Relinquish immediately, no retry,
          so we never keep scheduling against a lease we no longer hold.
        * ``renew()`` raises (``ConnectionError``/``TimeoutError`` during a blip)
          → retry up to ``retries`` times with jittered backoff. A single blip
          leaves leadership intact; only a failure that persists past the retry
          budget relinquishes.
        """
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return bool(self.renew())
            except Exception as exc:  # transient Redis/network error — do not escape
                last_exc = exc
                if attempt < retries:
                    # Full jitter keeps concurrent replicas from retrying in lockstep.
                    time.sleep(base_delay + _rng.uniform(0, base_delay))
        logger.warning(
            "Scheduler lease renew failed after %d attempt(s); relinquishing leadership: %s",
            retries + 1,
            last_exc,
        )
        return False
