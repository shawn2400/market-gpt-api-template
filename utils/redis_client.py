# utils/redis_client.py
from __future__ import annotations
import os
import logging
import redis
import asyncio
from dotenv import load_dotenv
from utils import cache  # fallback in-memory cache

# --- Load env vars ---
load_dotenv(override=True)

logger = logging.getLogger("algogpt.redis")

# --- Redis URL ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client: redis.Redis | None = None
_use_fallback = False

try:
    redis_client = redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    redis_client.ping()
    logger.info(f"[Redis] ✅ Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    _use_fallback = True
    logger.error(f"[Redis] ❌ Connection failed: {e} → using in-memory fallback")


# --- Wrappers (Redis → fallback) ---

async def set_value(key: str, value: str, expire: int | None = None) -> bool:
    if _use_fallback or not redis_client:
        await cache.aget_or_set(key, expire or 60, lambda: value)
        return True
    try:
        redis_client.set(key, value, ex=expire)
        return True
    except Exception as e:
        logger.error(f"[Redis] set_value error for {key}: {e}")
        return False


async def get_value(key: str) -> str | None:
    if _use_fallback or not redis_client:
        val = await cache.aget_or_set(key, 0, lambda: None)  # לא טוען מחדש
        return val
    try:
        return redis_client.get(key)
    except Exception as e:
        logger.error(f"[Redis] get_value error for {key}: {e}")
        return None


async def delete_value(key: str) -> bool:
    if _use_fallback or not redis_client:
        # ב־cache נשתמש ב־purge_expired (מוחק ממילא)
        return True
    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        logger.error(f"[Redis] delete_value error for {key}: {e}")
        return False


async def lpush(key: str, value: str):
    if _use_fallback or not redis_client:
        # fallback: מחזיקים רשימה בזיכרון
        existing = await cache.aget_or_set(key, 3600, lambda: [])
        if isinstance(existing, list):
            existing.insert(0, value)
            await cache.aget_or_set(key, 3600, lambda: existing)
        return
    try:
        redis_client.lpush(key, value)
    except Exception as e:
        logger.error(f"[Redis] lpush error for {key}: {e}")


async def ltrim(key: str, start: int, end: int):
    if _use_fallback or not redis_client:
        existing = await cache.aget_or_set(key, 3600, lambda: [])
        if isinstance(existing, list):
            new_list = existing[start:end+1]
            await cache.aget_or_set(key, 3600, lambda: new_list)
        return
    try:
        redis_client.ltrim(key, start, end)
    except Exception as e:
        logger.error(f"[Redis] ltrim error for {key}: {e}")


