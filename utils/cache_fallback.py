# utils/cache_fallback.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, logging
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("algogpt.cache")

# -------- key/value tiny cache (sync) --------
# key -> (value, expire_ts or None)
_KV_CACHE: Dict[str, Tuple[Any, Optional[float]]] = {}

def set_value(key: str, value: Any, ttl_sec: Optional[float] = None) -> None:
    exp = (time.time() + float(ttl_sec)) if ttl_sec else None
    _KV_CACHE[key] = (value, exp)

def get_value(key: str, default: Any = None) -> Any:
    tup = _KV_CACHE.get(key)
    if not tup:
        return default
    val, exp = tup
    if exp and time.time() > exp:
        try:
            del _KV_CACHE[key]
        except Exception:
            pass
        return default
    return val

def get_or_set(key: str, factory, ttl_sec: Optional[float] = None) -> Any:
    val = get_value(key, None)
    if val is not None:
        return val
    val = factory()
    set_value(key, val, ttl_sec)
    return val

# -------- list-like API with optional Redis backend (async) --------
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
_VALID_SCHEMES = ("redis://", "rediss://", "unix://")
_use_memory_only = True
_aioredis = None
_redis = None

try:
    if REDIS_URL and REDIS_URL.startswith(_VALID_SCHEMES):
        import redis.asyncio as aioredis  # type: ignore
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
        s = max(0, start)
        e = max(0, stop) + 1  # inclusive in Redis
        keep = list(dq)[s:e]
        dq.clear()
        dq.extend(keep)
        return True
    if _use_memory_only:
        return await _fb()
    return await _safe_call(_redis.ltrim(key, start, stop), _fb)

async def lrange(key: str, start: int, stop: int) -> List[str]:
    async def _fb():
        dq = _mem_lists[key]
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

__all__ = [
    "set_value", "get_value", "get_or_set",
    "lpush", "ltrim", "lrange", "ping",
]








