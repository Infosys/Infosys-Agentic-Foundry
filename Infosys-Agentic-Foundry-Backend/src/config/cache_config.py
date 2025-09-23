import os
import redis
from dotenv import load_dotenv

load_dotenv()

# Check if caching is enabled (default to False)
ENABLE_CACHING = os.getenv("ENABLE_CACHING", "False").lower() == "true"
    
# Redis connection is only established when caching is enabled
default_cache = None
if ENABLE_CACHING:
    default_cache = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=int(os.getenv("REDIS_DB", 0)),
        decode_responses=True,
        password=os.getenv("REDIS_PASSWORD")
    )

EXPIRY_TIME = int(os.getenv("CACHE_EXPIRY_TIME", 600))


# from diskcache import Cache

# # Cache stored in a local directory
# default_cache = Cache("cache_dir")
# EXPIRY_TIME = 60
