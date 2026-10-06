"""
Two-layer LRU cache for Smart Code Executor.

Layer 1: Goal → Generated Code  (avoids re-calling LLM for same goal)
Layer 2: Goal + Files → Execution Result  (avoids re-executing identical tasks)
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

from src.agentos.code_executor.config import CacheConfig

logger = logging.getLogger("agentos.code_executor.cache")


class LRUCache:
    """Thread-safe LRU cache with per-entry TTL."""

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            value, expiry = entry
            if time.time() > expiry:
                # Expired
                del self._cache[key]
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        with self._lock:
            ttl = ttl or self._default_ttl
            expiry = time.time() + ttl

            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = (value, expiry)
            else:
                # Evict oldest if at capacity
                while len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = (value, expiry)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
                "default_ttl": self._default_ttl,
            }


class CacheManager:
    """
    Two-layer caching for the code executor.

    - **Goal cache**: Maps (goal + language) → generated code.
      Avoids calling the LLM again for repeated identical goals.

    - **Result cache**: Maps (goal + language + file content hashes) → execution result.
      Avoids re-executing identical tasks.
    """

    def __init__(self, config: CacheConfig):
        self.config = config
        self.goal_code_cache = LRUCache(
            max_size=config.goal_cache_max_size,
            default_ttl=config.goal_cache_ttl,
        )
        self.result_cache = LRUCache(
            max_size=config.result_cache_max_size,
            default_ttl=config.result_cache_ttl,
        )

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # -------------------------------------------------------------------
    # Goal → Code cache
    # -------------------------------------------------------------------

    def get_cached_code(self, goal: str, language: str) -> Optional[str]:
        if not self.enabled:
            return None
        key = self._goal_key(goal, language)
        code = self.goal_code_cache.get(key)
        if code:
            logger.debug(f"Goal cache HIT: {goal[:60]}")
        return code

    def cache_code(self, goal: str, language: str, code: str):
        if not self.enabled:
            return
        key = self._goal_key(goal, language)
        self.goal_code_cache.set(key, code)

    # -------------------------------------------------------------------
    # Goal + Files → Result cache
    # -------------------------------------------------------------------

    def get_cached_result(
        self, goal: str, language: str, files: Optional[Dict[str, str]] = None
    ) -> Optional[Dict]:
        if not self.enabled:
            return None
        key = self._result_key(goal, language, files)
        result = self.result_cache.get(key)
        if result:
            logger.debug(f"Result cache HIT: {goal[:60]}")
        return result

    def cache_result(
        self,
        goal: str,
        language: str,
        result: Dict,
        files: Optional[Dict[str, str]] = None,
    ):
        if not self.enabled:
            return
        key = self._result_key(goal, language, files)
        self.result_cache.set(key, result)

    # -------------------------------------------------------------------
    # Invalidation
    # -------------------------------------------------------------------

    def invalidate_goal(self, goal: str, language: str):
        key = self._goal_key(goal, language)
        self.goal_code_cache.delete(key)
        # Also invalidate any result cache entries for this goal
        # (we can't enumerate all file combos, so this is best-effort)
        result_key = self._result_key(goal, language, None)
        self.result_cache.delete(result_key)

    def clear_all(self):
        self.goal_code_cache.clear()
        self.result_cache.clear()

    def stats(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "goal_cache": self.goal_code_cache.stats(),
            "result_cache": self.result_cache.stats(),
        }

    # -------------------------------------------------------------------
    # Key generation
    # -------------------------------------------------------------------

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def _goal_key(cls, goal: str, language: str) -> str:
        normalized = goal.strip().lower()
        return f"goal:{cls._hash(normalized + '|' + language)}"

    @classmethod
    def _result_key(
        cls, goal: str, language: str, files: Optional[Dict[str, str]]
    ) -> str:
        normalized = goal.strip().lower()
        parts = [normalized, language]
        if files:
            for fname in sorted(files.keys()):
                parts.append(f"{fname}:{cls._hash(files[fname])}")
        return f"result:{cls._hash('|'.join(parts))}"
