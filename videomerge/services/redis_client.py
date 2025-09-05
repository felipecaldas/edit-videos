import asyncio
from redis.asyncio import Redis
from videomerge.config import REDIS_URL
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)

_redis: Redis | None = None
_lock = asyncio.Lock()


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        async with _lock:
            if _redis is None:
                logger.info("[redis] Connecting to %s", REDIS_URL)
                _redis = Redis.from_url(REDIS_URL, decode_responses=False)
    return _redis


async def close_redis():
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        finally:
            _redis = None
