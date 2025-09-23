import functools
import hashlib
import json
from telemetry_wrapper import logger as log
from typing import Callable, Any
from src.config.cache_config import default_cache, ENABLE_CACHING
import json
from datetime import datetime
import asyncio
import time


class CacheableRepository:
    def _namespace(self):
        return self.__class__.__name__

    @classmethod
    def cache(cls, ttl=None, namespace=None):
        # Still return the decorator even if caching is disabled
        # The decorator will handle the check internally
        return cache_result(ttl=ttl or cls.EXPIRY_TIME, namespace=namespace)

    def invalidate_entity(self, method_name: str, *args, **kwargs):
        # If caching is disabled, no need to invalidate
        if not ENABLE_CACHING or default_cache is None:
            return
            
        method = getattr(self, method_name, None)
        if method:
            invalidate_entity_cache(self._namespace(), method, *args, **kwargs)

    def invalidate_all_method_cache(self, method_name: str):
        # If caching is disabled, no need to invalidate
        if not ENABLE_CACHING or default_cache is None:
            return
            
        method = getattr(self, method_name, None)
        if method:
            print(self._namespace())
            invalidate_all_variants(self._namespace(), method)
            log.info(f"Invalidated all cache variants for method: {method_name}")


def make_cache_key(namespace: str, func: Callable, *args, **kwargs) -> str:
    raw_key = json.dumps({
        "func": func.__qualname__,
        "args": args,
        "kwargs": kwargs
    }, sort_keys=True, default=str)
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    final_key = f"{namespace}:{func.__name__}:{hashed}"
    return final_key


def cache_result(ttl: int = 300, namespace: str = "default", lock_timeout: int = 5):
    """
    Async decorator for caching function results in Redis.

    - ttl: cache expiration in seconds
    - namespace: groups cache keys logically
    - lock_timeout: seconds to hold lock during recompute
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # If caching is disabled or Redis is not connected, bypass the cache logic
            if not ENABLE_CACHING or default_cache is None:
                return await func(*args, **kwargs)
                
            key = make_cache_key(namespace, func, *args, **kwargs)
            lock_key = key + ":lock"

            try:
                cached_value = default_cache.get(key)
                if cached_value is not None:
                    log.info(f"Cache HIT for key: {key}")
                    return json.loads(cached_value, object_hook=datetime_parser)
                else:
                    log.info(f"Cache MISS for key: {key}")
            except Exception as e:
                log.error(f"Redis GET error for key {key}: {e}")
                # Fall through to compute result directly

            got_lock = False
            try:
                # Try to acquire recomputation lock
                got_lock = default_cache.set(lock_key, 1, ex=lock_timeout, nx=True)
                if got_lock:
                    start_time = time.time()
                    result = await func(*args, **kwargs)
                    exec_time = (time.time() - start_time) * 1000
                    log.info(f"Computed fresh result for {key} in {exec_time:.2f} ms")

                    try:
                        default_cache.set(key, json.dumps(result, cls=DateTimeEncoder), ex=ttl)
                    except Exception as e:
                        log.error(f"Redis SET error for key {key}: {e}")
                    finally:
                        default_cache.delete(lock_key)
                    return result
                else:
                    # Wait up to lock_timeout seconds for another worker to fill the cache
                    for _ in range(lock_timeout * 10):
                        await asyncio.sleep(0.1)
                        cached_value = default_cache.get(key)
                        if cached_value is not None:
                            log.info(f"Cache filled after lock wait for key: {key}")
                            return json.loads(cached_value, object_hook=datetime_parser)
                    log.warning(f"Timeout waiting for cache key: {key} after lock")
                    return await func(*args, **kwargs)
            except Exception as e:
                log.error(f"Error in cache_result wrapper for {key}: {e}")
                return await func(*args, **kwargs)

        wrapper._namespace = namespace
        wrapper._cache_func = func
        return wrapper
    return decorator


def invalidate_entity_cache(namespace: str, func: Callable, *args, **kwargs):
    # If caching is disabled or Redis is not connected, no need to invalidate
    if not ENABLE_CACHING or default_cache is None:
        return
        
    key = make_cache_key(namespace, func, *args, **kwargs)
    try:
        default_cache.delete(key)
        log.info(f"Invalidated cache key: {key}")
    except Exception as e:
        log.error(f"Error invalidating key {key}: {e}")


def invalidate_all_variants(namespace: str, func: Callable):
    """
    Invalidate all cache keys for a given function (regardless of args)
    """
    # If caching is disabled or Redis is not connected, no need to invalidate
    if not ENABLE_CACHING or default_cache is None:
        return
        
    prefix = f"{namespace}:{func.__name__}:"
    cursor = 0
    keys_to_delete = []
    try:
        while True:
            cursor, keys = default_cache.scan(cursor=cursor, match=f"{prefix}*")
            keys_to_delete.extend(keys)
            if cursor == 0:
                break
        if keys_to_delete:
            default_cache.delete(*keys_to_delete)
            log.info(f"Invalidated {len(keys_to_delete)} keys for {namespace}:{func.__name__}")
        else:
            log.info(f"No keys found for {namespace}:{func.__name__}")
    except Exception as e:
        log.error(f"Error scanning keys for {namespace}:{func.__name__}: {e}")

        
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def datetime_parser(dct):
    for k, v in dct.items():
        if isinstance(v, str):
            try:
                dct[k] = datetime.fromisoformat(v)
            except ValueError:
                pass
    return dct
        






