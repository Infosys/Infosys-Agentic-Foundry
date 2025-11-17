import functools
import hashlib
import json
from telemetry_wrapper import logger as log
from typing import Callable
from src.config import cache_config  # use module, not direct vars to avoid stale references
from datetime import datetime
import asyncio
import time

# Helper to resolve client each use

async def _resolve_cache_client():
    if not cache_config.ENABLE_CACHING:
        return None
    client = await cache_config.get_cache()
    if client is None:
        return None
    return client


class CacheableRepository:
    async def _namespace(self):
        return self.__class__.__name__

    @classmethod
    def cache(cls, ttl=None, namespace=None):
        return cache_result(ttl=ttl, namespace=namespace)  # ttl already passed explicitly in decorators

    async def invalidate_entity(self, method_name: str, *args, namespace=None, **kwargs):
        client = await _resolve_cache_client()
        if client is None:
            return
        method = getattr(self, method_name, None)
        if method and namespace is None:
            await invalidate_entity_cache(await self._namespace(), method, *args, **kwargs)
        else:
            await invalidate_entity_cache(namespace, method, *args, **kwargs)
            

    async def invalidate_all_method_cache(self, method_name: str):
        client = await _resolve_cache_client()
        if client is None:
            return
        method = getattr(self, method_name, None)
        if method:
            await invalidate_all_variants(await self._namespace(), method)
            log.info(f"Invalidated all cache variants for method: {method_name}")


async def make_cache_key(namespace: str, func: Callable, *args, **kwargs) -> str:
    filtered_args = []
    for i, arg in enumerate(args):
        if i == 0 and hasattr(arg, '__dict__'):
            continue
        if arg is None:
            continue
        filtered_args.append(arg)
    
    # Filter out None values from kwargs
    filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    
    raw_key = json.dumps({
        "func": func.__qualname__,
        "args": filtered_args,
        "kwargs": filtered_kwargs
    }, sort_keys=True, default=str)
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    final_key = f"{namespace or 'global'}:{func.__name__}:{hashed}"
    return final_key


def cache_result(ttl: int = 300, namespace: str = "default", lock_timeout: int = 1):
    # Must remain sync (decorator factory); wrapper is async
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            log.info("------- CACHING STARTED -------")
            client = await _resolve_cache_client()
            if client is None:
                if cache_config.ENABLE_CACHING:
                    log.warning("Caching enabled but Redis client unavailable; executing function directly")
                return await func(*args, **kwargs)

            key = await make_cache_key(namespace, func, *args, **kwargs)
            lock_key = key + ":lock"

            try:
                cached_value = client.get(key)
                if cached_value is not None:
                    log.info(f"Cache HIT: {key}")
                    return json.loads(cached_value, object_hook=datetime_parser)
                else:
                    log.info(f"Cache MISS: {key}")
            except Exception as e:
                log.error(f"Redis GET error for {key}: {e}; bypassing cache")
                return await func(*args, **kwargs)

            try:
                got_lock = client.set(lock_key, 1, ex=lock_timeout, nx=True)
                if got_lock:
                    start_time = time.time()
                    result = await func(*args, **kwargs)
                    exec_time = (time.time() - start_time) * 1000
                    log.info(f"Computed fresh result for {key} in {exec_time:.2f} ms; caching with ttl={ttl}")
                    try:
                        client.set(key, json.dumps(result, cls=DateTimeEncoder), ex=ttl)
                    except Exception as e:
                        log.error(f"Redis SET error for {key}: {e}")
                    finally:
                        try:
                            client.delete(lock_key)
                            log.info("------- CACHING COMPLETED -------")
                        except Exception:
                            pass
                    return result
                else:
                    # Wait for another worker to populate
                    for _ in range(lock_timeout * 10):
                        await asyncio.sleep(0.1)
                        cached_value = client.get(key)
                        if cached_value is not None:
                            log.info(f"Cache filled after wait: {key}")
                            return json.loads(cached_value, object_hook=datetime_parser)
                    log.warning(f"Lock wait timeout; executing underlying function for {key}")
                    return await func(*args, **kwargs)
            except Exception as e:
                log.error(f"Cache wrapper error for {key}: {e}; executing function directly")
                return await func(*args, **kwargs)
        return wrapper
    return decorator


async def invalidate_entity_cache(namespace: str, func: Callable, *args, **kwargs):
    client = await _resolve_cache_client()
    if client is None:
        return
    key = await make_cache_key(namespace, func, *args, **kwargs)
    try:
        client.delete(key)
        log.info(f"Invalidated cache key: {key}")
    except Exception as e:
        log.error(f"Error invalidating key {key}: {e}")


async def invalidate_all_variants(namespace: str, func: Callable):
    client = await _resolve_cache_client()
    if client is None:
        return
    prefix = f"{namespace}:{func.__name__}:"
    cursor = 0
    keys_to_delete = []
    try:
        while True:
            cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*")
            keys_to_delete.extend(keys)
            if cursor == 0:
                break
        if keys_to_delete:
            client.delete(*keys_to_delete)
            log.info(f"Invalidated {len(keys_to_delete)} keys for {namespace}:{func.__name__}")
        else:
            log.info(f"No keys to invalidate for {namespace}:{func.__name__}")
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