# utils/cache_fallback.py
from __future__ import annotations
import logging, asyncio, time
from typing import Any
from utils.redis_client import redis_client

logger = logging.getLogger("algogpt.cache_fallback")

# --- In-memory fallback store ---
_LOCAL_STORE: dict[str, tuple[Any, float | None]] = {}

def _set_local(key: str, value: Any, expire: int | None = None):
    exp_ts = time.time() + expire if expire else None
    _LOCAL_STORE[key] = (value, exp_ts)

def _get_local(key: str):
    val = _LOCAL_STORE.get(key)
    if not val:
        return None
    value, exp_ts = val
    if exp_ts and exp_ts < time.time():
        _LOCAL_STORE.pop(key, None)
        return None
    return value

# --- Unified API for Redis or Local store ---
async def set_value(key: str, value: str, expire: int | None = None) -> bool:
    if redis_client:
        try:
            await asyncio.to_thread(redis_client.set, key, value, ex=expire)
            return True
        except Exception as e:
            logger.warning(f"[CacheFallback] Redis set error: {e}")
    _set_local(key, value, expire)
    return True

async def get_value(key: str):
    if redis_client:
        try:
            return await asyncio.to_thread(redis_client.get, key)
        except Exception as e:
            logger.warning(f"[CacheFallback] Redis get error: {e}")
    return _get_local(key)

async def delete_value(key: str) -> bool:
    if redis_client:
        try:
            await asyncio.to_thread(redis_client.delete, key)
            return True
        except Exception as e:
            logger.warning(f"[CacheFallback] Redis delete error: {e}")
    _LOCAL_STORE.pop(key, None)
    return True

async def lpush(key: str, value: str):
    if redis_client:
        try:
            await asyncio.to_thread(redis_client.lpush, key, value)
            return
        except Exception as e:
            logger.warning(f"[CacheFallback] Redis lpush error: {e}")
    arr = _get_local(key) or []
    if isinstance(arr, list):
        arr.insert(0, value)
        _set_local(key, arr, 3600)

async def ltrim(key: str, start: int, end: int):
    if redis_client:
        try:
            await asyncio.to_thread(redis_client.ltrim, key, start, end)
            return
        except Exception as e:
            logger.warning(f"[CacheFallback] Redis ltrim error: {e}")
    arr = _get_local(key) or []
    if isinstance(arr, list):
        _set_local(key, arr[start:end + 1], 3600)




