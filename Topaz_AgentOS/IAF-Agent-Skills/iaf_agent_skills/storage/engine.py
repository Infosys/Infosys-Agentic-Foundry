"""Storage engine: connection factory + SQL dialect per configured backend.

Backend selection (first non-empty wins):
  1. Host-registered provider config (``get_provider_setting('DB_BACKEND')``).
  2. Process environment (``DB_BACKEND``).
  3. Default: ``sqlite``.

SQLite uses the pragma-hardened helper in :mod:`iaf_agent_skills.sqlite_util`
(no extra dependencies). Postgres lazily imports ``psycopg`` (+ optional
``psycopg_pool``) only when selected, so importing this module never requires
those packages on the SQLite path.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from ..sqlite_util import connect as _sqlite_connect

logger = logging.getLogger(__name__)

BACKEND_SQLITE = "sqlite"
BACKEND_POSTGRES = "postgres"
VALID_BACKENDS = (BACKEND_SQLITE, BACKEND_POSTGRES)


def _config(name: str) -> Optional[str]:
    """Resolve a config value from the runtime bridge, then the environment."""
    try:
        from ..runtime_bridge import get_provider_setting
        val = get_provider_setting(name)
        if val:
            return val
    except Exception:
        pass
    val = os.getenv(name)
    return val or None


def resolve_backend() -> str:
    """Return the configured backend name (defaults to ``sqlite``)."""
    raw = (_config("DB_BACKEND") or BACKEND_SQLITE).strip().lower()
    if raw not in VALID_BACKENDS:
        logger.warning("Unknown DB_BACKEND=%r; falling back to sqlite", raw)
        return BACKEND_SQLITE
    return raw


class StorageEngine:
    """Base engine. Subclasses own connection creation + dialect specifics."""

    backend: str = ""

    @property
    def is_postgres(self) -> bool:
        return self.backend == BACKEND_POSTGRES

    def placeholder(self, index: int = 0) -> str:  # noqa: ARG002
        raise NotImplementedError

    @contextmanager
    def connect(self) -> Iterator[Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend}


class SqliteEngine(StorageEngine):
    """SQLite backend. Zero extra dependencies; pragma-hardened connections.

    A ``db_path`` is required. Because SQLite is file-per-scope, the engine is
    typically instantiated per database file (knowledge index, evidence, etc.).
    """

    backend = BACKEND_SQLITE

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def placeholder(self, index: int = 0) -> str:  # noqa: ARG002
        return "?"

    @contextmanager
    def connect(self) -> Iterator[Any]:
        conn = _sqlite_connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def health(self) -> dict[str, Any]:
        info: dict[str, Any] = {"backend": self.backend, "db_path": self.db_path}
        try:
            with self.connect() as conn:
                info["reachable"] = bool(conn.execute("SELECT 1").fetchone())
        except Exception as exc:
            info["reachable"] = False
            info["error"] = str(exc)
        return info


def _pool_reset(conn) -> None:
    """Reset per-connection session state before a pooled connection is reused.

    The knowledge/conversation/evidence seams run ``SET LOCAL search_path TO "<schema>"``
    on scoped operations. In practice a pooled connection can be returned still carrying
    that scoped ``search_path`` (without ``public``); the next borrower then can't resolve
    objects in ``public`` — e.g. the pgvector ``vector`` type — and silently degrades. Run
    ``RESET ALL`` on return so every checkout starts from the server default. Best-effort:
    the pool discards a connection this raises on."""
    try:
        if getattr(conn, "closed", False):
            return
        conn.rollback()  # end any transaction the previous borrower left open
        with conn.cursor() as cur:
            cur.execute("RESET ALL")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


class PostgresEngine(StorageEngine):
    """PostgreSQL backend for multi-node / HA deployments.

    Requires ``pip install 'psycopg[binary]'`` (and ``pgvector`` for vector
    search). ``psycopg_pool`` is used when available for connection pooling,
    otherwise a direct connection is opened per ``connect()``.

    DSN resolution: ``DATABASE_URL`` config/env.
    """

    backend = BACKEND_POSTGRES

    def __init__(self, dsn: Optional[str] = None, *, pool_size: int = 10):
        self.dsn = dsn or _config("DATABASE_URL")
        if not self.dsn:
            raise RuntimeError(
                "DB_BACKEND=postgres requires DATABASE_URL (postgresql://<user>@<host>:5432/<db>)"
            )
        try:
            self._pool_size = int(_config("DB_POOL_SIZE") or pool_size)
        except (TypeError, ValueError):
            self._pool_size = pool_size
        self._pool = None
        self._pool_lock = threading.Lock()
        self._db_ensured = False

    def placeholder(self, index: int = 0) -> str:  # noqa: ARG002
        return "%s"

    def _get_pool(self):
        """Lazily build a connection pool (psycopg_pool) if available."""
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is not None:
                return self._pool
            if not self._db_ensured:
                self._ensure_database()
                self._db_ensured = True
            try:
                from psycopg_pool import ConnectionPool  # type: ignore
                self._pool = ConnectionPool(
                    conninfo=self.dsn,
                    min_size=1,
                    max_size=self._pool_size,
                    open=True,
                    reset=_pool_reset,
                )
                logger.info("PostgresEngine: connection pool ready (max=%d)", self._pool_size)
            except Exception as exc:
                logger.info("PostgresEngine: psycopg_pool unavailable (%s); per-call connect", exc)
                self._pool = False  # sentinel: no pooling
            return self._pool

    def _split_dsn_for_admin(self) -> tuple[str, str]:
        """Return ``(target_dbname, maintenance_dsn)`` for a URL-style DSN.

        The maintenance DSN points at the always-present ``postgres`` database so
        we can issue ``CREATE DATABASE`` for the target. Returns ``("", "")`` when
        the DSN is not URL-style (e.g. key/value form) and cannot be rewritten.
        """
        from urllib.parse import urlsplit, urlunsplit

        try:
            parts = urlsplit(self.dsn)
        except Exception:
            return "", ""
        if not parts.scheme.startswith("postgres"):
            return "", ""
        dbname = (parts.path or "").lstrip("/")
        if not dbname:
            return "", ""
        admin_dsn = urlunsplit(parts._replace(path="/postgres"))
        return dbname, admin_dsn

    def _ensure_database(self) -> None:
        """Create the target database on a fresh instance if it does not exist.

        Best-effort: tries a quick connect to the configured database; only when
        that fails specifically because the database is missing (SQLSTATE 3D000)
        does it connect to the ``postgres`` maintenance database and run
        ``CREATE DATABASE``. Any other failure (auth, host unreachable) is left
        for the normal connect path to surface. Never raises.
        """
        try:
            import psycopg  # type: ignore
        except ImportError:
            return
        try:
            with psycopg.connect(self.dsn, connect_timeout=5):
                return  # database exists and is reachable
        except psycopg.OperationalError as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate != "3D000" and "does not exist" not in str(exc).lower():
                return  # a different problem (auth/host) — don't mask it here
        except Exception:
            return

        dbname, admin_dsn = self._split_dsn_for_admin()
        if not dbname or not admin_dsn:
            return
        try:
            with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as admin:
                with admin.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                    if cur.fetchone():
                        return
                    # Identifier can't be parameterised; dbname comes from our own
                    # DSN config, not user input. Quote defensively.
                    cur.execute('CREATE DATABASE "%s"' % dbname.replace('"', '""'))
            logger.info("PostgresEngine: created missing database '%s' (fresh instance)", dbname)
        except Exception as exc:  # noqa: BLE001 - best-effort bootstrap
            logger.warning("PostgresEngine: could not auto-create database '%s': %s", dbname, exc)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg  # type: ignore  # noqa: F401
        except ImportError as exc:  # pragma: no cover - deploy-time dependency
            raise RuntimeError(
                "DB_BACKEND=postgres requires psycopg. Install with: "
                "pip install 'psycopg[binary]' pgvector"
            ) from exc

        pool = self._get_pool()
        if pool:
            with pool.connection() as conn:
                yield conn  # psycopg_pool handles commit/rollback/return
            return

        import psycopg  # type: ignore
        conn = psycopg.connect(self.dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def health(self) -> dict[str, Any]:
        info: dict[str, Any] = {"backend": self.backend, "pool_size": self._pool_size}
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                info["reachable"] = bool(cur.fetchone())
        except Exception as exc:
            info["reachable"] = False
            info["error"] = str(exc)
        return info

    def close(self) -> None:
        """Close the connection pool for a graceful shutdown. Safe to call multiple
        times; a no-op when psycopg_pool was unavailable (per-call connect mode).

        ``self._pool`` may be ``None`` (never built), ``False`` (sentinel for
        "pooling unavailable"), or a live ``ConnectionPool``.

        The pool reference is swapped out under ``_pool_lock`` so that
        concurrent ``_get_pool()`` callers never receive a pool that is
        simultaneously being closed.
        """
        with self._pool_lock:
            pool = self._pool
            self._pool = None
        if pool and hasattr(pool, "close"):
            try:
                pool.close()
                logger.info("PostgresEngine: connection pool closed")
            except Exception as exc:  # pragma: no cover - shutdown best-effort
                logger.warning("PostgresEngine: pool close failed: %s", exc)

    def pool_stats(self) -> dict:
        """psycopg_pool stats (pool_size, pool_available, requests_waiting, …) for /metrics.
        Returns {} when pooling is unavailable (per-call-connect mode)."""
        pool = self._pool  # avoid building a pool just to sample
        if pool and pool is not False and hasattr(pool, "get_stats"):
            try:
                return dict(pool.get_stats())
            except Exception:
                return {}
        return {}



_engines_lock = threading.Lock()
_sqlite_engines: dict[str, SqliteEngine] = {}
_postgres_engine: Optional[PostgresEngine] = None


def get_engine(db_path: Optional[Union[str, Path]] = None) -> StorageEngine:
    """Return the :class:`StorageEngine` for the active backend.

    Args:
        db_path: Required for SQLite (the file to open). Ignored for Postgres,
            where a single pooled engine serves every scope.
    """
    global _postgres_engine
    backend = resolve_backend()

    if backend == BACKEND_POSTGRES:
        with _engines_lock:
            if _postgres_engine is None:
                _postgres_engine = PostgresEngine()
            return _postgres_engine

    # SQLite
    if db_path is None:
        raise ValueError("get_engine(db_path=...) is required for the sqlite backend")
    key = str(db_path)
    with _engines_lock:
        eng = _sqlite_engines.get(key)
        if eng is None:
            eng = SqliteEngine(key)
            _sqlite_engines[key] = eng
        return eng


def reset_engine() -> None:
    """Clear cached engines (tests / config reload)."""
    global _postgres_engine
    with _engines_lock:
        if _postgres_engine is not None:
            try:
                _postgres_engine.close()
            except Exception:
                pass
        _sqlite_engines.clear()
        if _postgres_engine is not None:
            _postgres_engine.close()
        _postgres_engine = None


def close_engines() -> None:
    """Gracefully close pooled engines — call from the server lifespan shutdown so the
    Postgres connection pool (shared by the queue + knowledge index) is drained cleanly."""
    global _postgres_engine
    with _engines_lock:
        if _postgres_engine is not None:
            _postgres_engine.close()
            _postgres_engine = None
