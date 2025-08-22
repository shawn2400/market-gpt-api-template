# utils/redis_client.py
from __future__ import annotations
import os, logging
import redis
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("algogpt.redis")

REDIS_URL = os.getenv("REDIS_URL", "dummy://")

redis_client: redis.Redis | None = None

try:
    if REDIS_URL.startswith("dummy://"):
        redis_client = None
        logger.warning("[Redis] ⚠️ Dummy mode enabled (no Redis backend)")
    else:
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
    logger.error(f"[Redis] ❌ Connection failed: {e} -> fallback to in-memory")





