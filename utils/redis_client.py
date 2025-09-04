# utils/redis_client.py
from __future__ import annotations
import os, logging
import redis
from typing import Optional

logger = logging.getLogger("algogpt.redis")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

redis_client: Optional[redis.Redis] = None
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"[Redis] Connected to {REDIS_URL}")
except Exception as e:
    logger.warning(f"[Redis] Disabled (url={REDIS_URL}) err={e}")
    redis_client = None

def get_redis() -> Optional[redis.Redis]:
    """Return redis client if available, else None."""
    return redis_client










