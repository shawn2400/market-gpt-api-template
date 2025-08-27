# utils/cache_fallback.py
from __future__ import annotations
import os, logging
from collections import defaultdict, deque
from typing import Deque, Dict, List

logger = logging.getLogger("algogpt.redis")

REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

_VALID_SCHEMES = ("redis://", "rediss://", "unix://")
_use_memory_only = True
_aioredis = None
_redis = None

try:
    if REDIS_URL and REDIS_URL.startswith(_VALID_SCHEMES):
        import redis.asyncio as aioredis  # redis>=4.2
        _aioredis = aioredis
        _redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            health_check_interval=30,
            socket_connect_timeout=3,
        )
        _use_memory_only = False
        logger.info("[Redis] using real redis backend: %s", REDIS_URL)
    else:
        _use_memory_only = True
        if REDIS_URL and REDIS_URL.lower() != "memory://" and REDIS_URL != "":
            logger.info("[Redis] unsupported scheme '%s' → using in-memory store", REDIS_URL)
        else:
            logger.info("[Redis] using in-memory store")
except Exception as e:
    logger.warning("[Redis] init failed (%s) → using in-memory store", e)
    _use_memory_only = True
    _aioredis = None
    _redis = None

_mem_lists: Dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=5000))

async def _safe_call(coro, fallback):
    global _use_memory_only, _redis
    if _use_memory_only or _redis is None:
        return await fallback()
    try:
        return await coro
    except Exception as e:
        if not _use_memory_only:
            logger.warning("[Redis] connection lost (%s) → falling back to in-memory", e)
        _use_memory_only = True
        _redis = None
        return await fallback()

async def lpush(key: str, value: str):
    async def _fb():
        _mem_lists[key].appendleft(value)
        return len(_mem_lists[key])
    if _use_memory_only:
        return await _fb()
    return await _safe_call(_redis.lpush(key, value), _fb)

async def ltrim(key: str, start: int, stop: int):
    async def _fb():
        dq = _mem_lists[key]
        if start < 0: start = 0
        if stop < 0:  stop = 0
        keep = list(dq)[start: stop + 1]
        dq.clear()
        dq.extend(keep)
        return True
    if _use_memory_only:
        return await _fb()
    return await _safe_call(_redis.ltrim(key, start, stop), _fb)

async def lrange(key: str, start: int, stop: int) -> List[str]:
    """מקביל ל־LRANGE ב־Redis, עם fallback לזיכרון"""
    async def _fb():
        dq = _mem_lists[key]
        # Redis כולל את stop, Python slicing לא → מוסיפים +1
        return list(dq)[start: stop + 1]
    if _use_memory_only:
        return await _fb()
    return await _safe_call(_redis.lrange(key, start, stop), _fb)

async def ping() -> bool:
    if _use_memory_only or _redis is None:
        return True
    try:
        return (await _redis.ping()) is True
    except Exception:
        return False







