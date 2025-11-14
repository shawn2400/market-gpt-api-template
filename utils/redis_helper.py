# utils/redis_helper.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, asyncio, time, random, logging
from typing import Any, Optional
from contextlib import asynccontextmanager

_aioredis = None
try:
    import aioredis  # type: ignore
    _aioredis = aioredis
except Exception:
    pass

REDIS_URL = os.getenv("REDIS_URL", "")
_logger = logging.getLogger("algogpt.redis_lock")

async def get_redis():
    if not _aioredis or not REDIS_URL:
        return None
    return await _aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

async def set_json(key: str, value: Any, *, ttl_sec: Optional[int] = None) -> bool:
    r = await get_redis()
    if not r:
        return False
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if ttl_sec and ttl_sec > 0:
        await r.set(key, data, ex=int(ttl_sec))
    else:
        await r.set(key, data)
    return True

async def get_json(key: str) -> Any:
    r = await get_redis()
    if not r:
        return None
    raw = await r.get(key)
    return json.loads(raw) if raw else None

@asynccontextmanager
async def acquire_sltp_lock(symbol: str, side: str, timeout_sec: int = 30, retry_timeout_sec: int = 3):
    """
    Distributed lock for SL/TP orchestration.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        timeout_sec: Lock expiry (30s default - protection against crashes)
        retry_timeout_sec: Max time to retry acquiring lock (3s default)
        
    Yields:
        True if lock acquired, raises RuntimeError if busy
        
    Example:
        async with acquire_sltp_lock("BTCUSDT", "LONG"):
            # Atomic SL/TP updates here
            pass
    """
    lock_key = f"sltp_lock:{symbol}:{side}"
    lock_value = f"{os.getpid()}:{time.time()}"
    r = await get_redis()
    
    if not r:
        _logger.warning(f"⚠️ Redis unavailable - proceeding WITHOUT lock (DEGRADED MODE)")
        yield True  # Degraded mode - allow operation but log warning
        return
    
    acquired = False
    start_time = time.time()
    
    try:
        # Retry loop with exponential backoff
        while (time.time() - start_time) < retry_timeout_sec:
            # Try to acquire lock (SET NX with expiry)
            acquired = await r.set(lock_key, lock_value, ex=timeout_sec, nx=True)
            
            if acquired:
                _logger.debug(f"🔒 Lock acquired: {lock_key}")
                yield True
                return
            
            # Lock is busy - wait with jitter
            jitter = random.uniform(0.05, 0.15)  # 50-150ms jitter
            await asyncio.sleep(jitter)
        
        # Failed to acquire lock within retry_timeout_sec
        raise RuntimeError(f"⏱️ SL/TP lock busy: {symbol} {side} (timeout after {retry_timeout_sec}s)")
        
    finally:
        # Release lock if we acquired it
        if acquired and r:
            try:
                # Only delete if value matches (prevents deleting someone else's lock)
                lua_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
                """
                await r.eval(lua_script, 1, lock_key, lock_value)
                _logger.debug(f"🔓 Lock released: {lock_key}")
            except Exception as e:
                _logger.warning(f"Failed to release lock {lock_key}: {e}")


