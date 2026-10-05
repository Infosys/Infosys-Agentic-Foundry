# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Skill File Cache — In-memory TTL cache for parsed skill/config files.

Avoids repeated disk I/O for _index.yaml, SKILL.md, and enterprise
context files that rarely change during a server's lifetime.

Inspired by AgentPro's kernel-level caching patterns.

Usage:
    cache = SkillFileCache(ttl_seconds=300)  # 5-minute TTL
    content = cache.get(path)
    if content is None:
        content = path.read_text(encoding="utf-8")
        cache.put(path, content)

    # Or use the one-liner:
    content = cache.get_or_load(path)

    # For YAML:
    data = cache.get_yaml(path)
"""

import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class SkillFileCache:
    """
    Thread-safe in-memory cache with TTL eviction.

    Entries are evicted on access if expired (lazy eviction).
    Also supports manual invalidation and stats tracking.
    """

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 500):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: Dict[str, Tuple[Any, float]] = {}  # key → (value, expire_ts)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Core cache operations
    # ------------------------------------------------------------------

    def get(self, path: Path) -> Optional[str]:
        """Get cached file content. Returns None on miss or expiry."""
        key = str(path.resolve())
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expire_ts = entry
            if time.time() > expire_ts:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def put(self, path: Path, content: str):
        """Store file content with TTL."""
        key = str(path.resolve())
        with self._lock:
            # Evict oldest if at capacity
            if len(self._store) >= self._max_entries and key not in self._store:
                self._evict_oldest()
            self._store[key] = (content, time.time() + self._ttl)

    def get_or_load(self, path: Path, encoding: str = "utf-8") -> Optional[str]:
        """Get from cache or load from disk. Returns None if file doesn't exist."""
        content = self.get(path)
        if content is not None:
            return content

        if not path.exists() or not path.is_file():
            return None

        try:
            content = path.read_text(encoding=encoding)
            self.put(path, content)
            return content
        except Exception as e:
            log.warning(f"[SkillFileCache] Failed to read {path}: {e}")
            return None

    def get_yaml(self, path: Path) -> Optional[Dict]:
        """Load and cache a YAML file, returning parsed dict."""
        if not HAS_YAML:
            return None
        key = f"yaml:{path.resolve()}"
        with self._lock:
            entry = self._store.get(key)
            if entry:
                value, expire_ts = entry
                if time.time() <= expire_ts:
                    self._hits += 1
                    return value
                del self._store[key]

        self._misses += 1
        content = self.get_or_load(path)
        if content is None:
            return None

        try:
            data = yaml.safe_load(content)
            with self._lock:
                self._store[key] = (data, time.time() + self._ttl)
            return data
        except Exception as e:
            log.warning(f"[SkillFileCache] Failed to parse YAML {path}: {e}")
            return None

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def invalidate(self, path: Path):
        """Remove a specific file from cache."""
        key = str(path.resolve())
        yaml_key = f"yaml:{path.resolve()}"
        with self._lock:
            self._store.pop(key, None)
            self._store.pop(yaml_key, None)

    def invalidate_prefix(self, prefix_path: Path):
        """Invalidate all entries under a directory."""
        prefix = str(prefix_path.resolve())
        with self._lock:
            to_delete = [k for k in self._store if k.lstrip("yaml:").startswith(prefix)]
            for k in to_delete:
                del self._store[k]
        if to_delete:
            log.info(f"[SkillFileCache] Invalidated {len(to_delete)} entries under {prefix_path}")

    def clear(self):
        """Clear entire cache."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_oldest(self):
        """Evict the entry closest to expiry (already expired first)."""
        if not self._store:
            return
        now = time.time()
        # First pass: evict expired entries
        expired = [k for k, (_, exp) in self._store.items() if exp < now]
        if expired:
            for k in expired:
                del self._store[k]
            return
        # Otherwise evict the one closest to expiry
        oldest_key = min(self._store, key=lambda k: self._store[k][1])
        del self._store[oldest_key]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
                "ttl_seconds": self._ttl,
                "max_entries": self._max_entries,
            }


# ---------------------------------------------------------------------------
# Singleton instance (shared across the application)
# ---------------------------------------------------------------------------

_default_cache: Optional[SkillFileCache] = None


def get_skill_cache(ttl_seconds: int = 300) -> SkillFileCache:
    """Get or create the global SkillFileCache singleton."""
    global _default_cache
    if _default_cache is None:
        _default_cache = SkillFileCache(ttl_seconds=ttl_seconds)
    return _default_cache
