# utils/redis_lock.py
"""
🔒 Redis Lock Manager - Enhanced Edition
Timeout: 2000ms, Retry: 3x with exponential backoff, Graceful degradation
"""

from __future__ import annotations
import os
import time
import random
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager, contextmanager

logger = logging.getLogger("algogpt.redis_lock")

# Environment config
REDIS_LOCK_TIMEOUT_MS = int(os.getenv("REDIS_LOCK_TIMEOUT_MS", "2000"))  # 2000ms default
REDIS_LOCK_TTL_SEC = int(os.getenv("REDIS_LOCK_TTL_SEC", "30"))  # 30s TTL
REDIS_LOCK_RETRY_COUNT = int(os.getenv("REDIS_LOCK_RETRY_COUNT", "3"))  # 3 attempts


def _get_redis_sync():
    """Get sync Redis client"""
    try:
        from utils.redis_client import get_redis
        return get_redis()
    except Exception as e:
        logger.debug(f"Redis sync client unavailable: {e}")
        return None


async def _get_redis_async():
    """Get async Redis client"""
    try:
        import aioredis
        redis_url = os.getenv("REDIS_URL", "")
        if not redis_url:
            return None
        return await aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    except Exception as e:
        logger.debug(f"Redis async client unavailable: {e}")
        return None


class RedisLockManager:
    """Enhanced Redis Lock Manager with retry logic and graceful degradation"""
    
    def __init__(
        self,
        lock_key: str,
        timeout_ms: int = REDIS_LOCK_TIMEOUT_MS,
        ttl_sec: int = REDIS_LOCK_TTL_SEC,
        retry_count: int = REDIS_LOCK_RETRY_COUNT
    ):
        self.lock_key = lock_key
        self.timeout_ms = timeout_ms
        self.ttl_sec = ttl_sec
        self.retry_count = retry_count
        self.lock_value = f"{os.getpid()}:{time.time()}:{random.randint(1000, 9999)}"
        self.acquired = False
    
    def _try_acquire_sync(self, redis_client) -> bool:
        """Try to acquire lock synchronously"""
        try:
            # SET NX with expiry
            result = redis_client.set(self.lock_key, self.lock_value, ex=self.ttl_sec, nx=True)
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to acquire lock {self.lock_key}: {e}")
            return False
    
    def _release_sync(self, redis_client):
        """Release lock synchronously"""
        try:
            # Lua script to delete only if value matches
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            redis_client.eval(lua_script, 1, self.lock_key, self.lock_value)
            logger.debug(f"🔓 Lock released: {self.lock_key}")
        except Exception as e:
            logger.warning(f"Failed to release lock {self.lock_key}: {e}")
    
    async def _try_acquire_async(self, redis_client) -> bool:
        """Try to acquire lock asynchronously"""
        try:
            result = await redis_client.set(self.lock_key, self.lock_value, ex=self.ttl_sec, nx=True)
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to acquire lock {self.lock_key}: {e}")
            return False
    
    async def _release_async(self, redis_client):
        """Release lock asynchronously"""
        try:
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await redis_client.eval(lua_script, 1, self.lock_key, self.lock_value)
            logger.debug(f"🔓 Lock released: {self.lock_key}")
        except Exception as e:
            logger.warning(f"Failed to release lock {self.lock_key}: {e}")


@contextmanager
def redis_lock(
    lock_key: str,
    timeout_ms: int = REDIS_LOCK_TIMEOUT_MS,
    ttl_sec: int = REDIS_LOCK_TTL_SEC,
    retry_count: int = REDIS_LOCK_RETRY_COUNT,
    graceful_degradation: bool = True
):
    """
    🔒 Synchronous Redis lock with retry logic
    
    Args:
        lock_key: Unique lock identifier
        timeout_ms: Total timeout in milliseconds (default: 2000ms)
        ttl_sec: Lock TTL in seconds (default: 30s)
        retry_count: Number of retry attempts (default: 3)
        graceful_degradation: Allow operation without lock if Redis unavailable
    
    Example:
        with redis_lock("trade:BTCUSDT:update"):
            # Protected code here
            update_position()
    """
    manager = RedisLockManager(lock_key, timeout_ms, ttl_sec, retry_count)
    redis_client = _get_redis_sync()
    
    # Graceful degradation - Redis unavailable
    if not redis_client:
        if graceful_degradation:
            logger.warning(f"⚠️ Redis unavailable - proceeding WITHOUT lock (DEGRADED MODE): {lock_key}")
            yield True
            return
        else:
            raise RuntimeError(f"Redis unavailable and graceful degradation disabled for {lock_key}")
    
    # Try to acquire lock with retries
    start_time = time.time()
    timeout_sec = timeout_ms / 1000.0
    attempt = 0
    
    try:
        while attempt < retry_count and (time.time() - start_time) < timeout_sec:
            attempt += 1
            
            if manager._try_acquire_sync(redis_client):
                manager.acquired = True
                logger.debug(f"🔒 Lock acquired on attempt {attempt}: {lock_key}")
                yield True
                return
            
            # Exponential backoff with jitter
            if attempt < retry_count:
                backoff_ms = min(100 * (2 ** (attempt - 1)), 400)  # 100ms, 200ms, 400ms
                jitter_ms = random.uniform(0, backoff_ms * 0.3)  # 30% jitter
                sleep_time = (backoff_ms + jitter_ms) / 1000.0
                
                logger.debug(f"Lock busy, retry {attempt}/{retry_count} after {sleep_time:.3f}s: {lock_key}")
                time.sleep(sleep_time)
        
        # Failed to acquire lock
        if graceful_degradation:
            logger.warning(f"⏱️ Lock timeout after {attempt} attempts - proceeding WITHOUT lock (DEGRADED MODE): {lock_key}")
            yield True
        else:
            raise RuntimeError(f"Lock timeout after {attempt} attempts: {lock_key}")
            
    finally:
        # Release lock if acquired
        if manager.acquired and redis_client:
            manager._release_sync(redis_client)


@asynccontextmanager
async def redis_lock_async(
    lock_key: str,
    timeout_ms: int = REDIS_LOCK_TIMEOUT_MS,
    ttl_sec: int = REDIS_LOCK_TTL_SEC,
    retry_count: int = REDIS_LOCK_RETRY_COUNT,
    graceful_degradation: bool = True
):
    """
    🔒 Async Redis lock with retry logic
    
    Args:
        lock_key: Unique lock identifier
        timeout_ms: Total timeout in milliseconds (default: 2000ms)
        ttl_sec: Lock TTL in seconds (default: 30s)
        retry_count: Number of retry attempts (default: 3)
        graceful_degradation: Allow operation without lock if Redis unavailable
    
    Example:
        async with redis_lock_async("trade:BTCUSDT:update"):
            # Protected async code here
            await update_position()
    """
    manager = RedisLockManager(lock_key, timeout_ms, ttl_sec, retry_count)
    redis_client = await _get_redis_async()
    
    # Graceful degradation - Redis unavailable
    if not redis_client:
        if graceful_degradation:
            logger.warning(f"⚠️ Redis unavailable - proceeding WITHOUT lock (DEGRADED MODE): {lock_key}")
            yield True
            return
        else:
            raise RuntimeError(f"Redis unavailable and graceful degradation disabled for {lock_key}")
    
    # Try to acquire lock with retries
    start_time = time.time()
    timeout_sec = timeout_ms / 1000.0
    attempt = 0
    
    try:
        while attempt < retry_count and (time.time() - start_time) < timeout_sec:
            attempt += 1
            
            if await manager._try_acquire_async(redis_client):
                manager.acquired = True
                logger.debug(f"🔒 Lock acquired on attempt {attempt}: {lock_key}")
                yield True
                return
            
            # Exponential backoff with jitter
            if attempt < retry_count:
                backoff_ms = min(100 * (2 ** (attempt - 1)), 400)  # 100ms, 200ms, 400ms
                jitter_ms = random.uniform(0, backoff_ms * 0.3)  # 30% jitter
                sleep_time = (backoff_ms + jitter_ms) / 1000.0
                
                logger.debug(f"Lock busy, retry {attempt}/{retry_count} after {sleep_time:.3f}s: {lock_key}")
                await asyncio.sleep(sleep_time)
        
        # Failed to acquire lock
        if graceful_degradation:
            logger.warning(f"⏱️ Lock timeout after {attempt} attempts - proceeding WITHOUT lock (DEGRADED MODE): {lock_key}")
            yield True
        else:
            raise RuntimeError(f"Lock timeout after {attempt} attempts: {lock_key}")
            
    finally:
        # Release lock if acquired
        if manager.acquired and redis_client:
            await manager._release_async(redis_client)


# Backwards compatibility alias
acquire_sltp_lock = redis_lock_async


__all__ = ["redis_lock", "redis_lock_async", "acquire_sltp_lock", "RedisLockManager"]
