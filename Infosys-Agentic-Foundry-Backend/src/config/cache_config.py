import os
import redis
from dotenv import load_dotenv
from telemetry_wrapper import logger as log

load_dotenv()

# Check if caching is enabled (default to False)
ENABLE_CACHING = os.getenv("ENABLE_CACHING", "False").lower() == "true"

# Redis connection / pool references
redis_pool = None
default_cache = None

if ENABLE_CACHING:
    try:
        # Create a connection pool so connections are reused instead of re-created
        log.info("Redis connection is getting started")
        redis_pool = redis.ConnectionPool(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
            password=os.getenv("REDIS_PASSWORD"),
            max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", 20)),
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", 2.0)),
            socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT", 2.0)),
            decode_responses=True,
        )
        # Client that draws from the pool
        default_cache = redis.Redis(connection_pool=redis_pool, retry_on_timeout=True)
        log.info("Successfully connected to Redis cache using connection pool")
    except (redis.ConnectionError, redis.TimeoutError, redis.AuthenticationError) as e:
        log.info(f"Redis connection failed: {str(e)}. Caching will be disabled.")
        ENABLE_CACHING = False
        default_cache = None

EXPIRY_TIME = int(os.getenv("CACHE_EXPIRY_TIME", 600))


async def get_cache():
    """Return a Redis client instance (from the pool) or None if caching disabled."""
    if ENABLE_CACHING and default_cache is not None:
        return default_cache
    return None

# from diskcache import Cache
# default_cache = Cache("cache_dir")
# EXPIRY_TIME = 60