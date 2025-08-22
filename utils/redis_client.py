# utils/redis_client.py
from __future__ import annotations
import os, logging
import redis
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("algogpt.redis")

# אם לא מוגדר -> נ fallback ל־localhost
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

redis_client: redis.Redis | None = None

try:
    if REDIS_URL.startswith("dummy://"):
        # fallback dummy mode
        redis_client = None
        logger.warning("[Redis] ⚠️ Dummy mode enabled (no Redis backend)")
    else:
        redis_client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,        # string במקום bytes
            socket_connect_timeout=5,     # fail fast אם אין חיבור
            health_check_interval=30,     # שומר חיבור בריא
        )
        redis_client.ping()
        logger.info(f"[Redis] ✅ Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    logger.error(f"[Redis] ❌ Connection failed: {e} -> fallback to in-memory")




