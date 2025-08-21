# utils/cache_fallback.py
from __future__ import annotations
import logging
from utils import cache
from utils.redis_client import redis_client

logger = logging.getLogger("algogpt.cache_fallback")

# --- API אחיד ל־Redis או In-Memory ---

async def set_value(key: str, value: str, expire: int | None = None) -> bool:
    if redis_client:
        try:
            redis_client.set(key, value, ex=expire)
            return True
        except Exception as e:
            logger.error(f"[CacheFallback] Redis set error: {e}")
    # fallback
    await cache.aget_or_set(key, expire or 60, lambda: value)
    return True


async def get_value(key: str):
    if redis_client:
        try:
            return redis_client.get(key)
        except Exception as e:
            logger.error(f"[CacheFallback] Redis get error: {e}")
    return await cache.aget_or_set(key, 0, lambda: None)


async def delete_value(key: str) -> bool:
    if redis_client:
        try:
            redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"[CacheFallback] Redis delete error: {e}")
    return True


async def lpush(key: str, value: str):
    if redis_client:
        try:
            redis_client.lpush(key, value)
            return
        except Exception as e:
            logger.error(f"[CacheFallback] Redis lpush error: {e}")
    existing = await cache.aget_or_set(key, 3600, lambda: [])
    if isinstance(existing, list):
        existing.insert(0, value)
        await cache.aget_or_set(key, 3600, lambda: existing)


async def ltrim(key: str, start: int, end: int):
    if redis_client:
        try:
            redis_client.ltrim(key, start, end)
            return
        except Exception as e:
            logger.error(f"[CacheFallback] Redis ltrim error: {e}")
    existing = await cache.aget_or_set(key, 3600, lambda: [])
    if isinstance(existing, list):
        new_list = existing[start:end+1]
        await cache.aget_or_set(key, 3600, lambda: new_list)

