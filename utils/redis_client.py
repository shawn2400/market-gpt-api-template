# utils/redis_client.py
import os
import logging
import redis
from dotenv import load_dotenv

# --- Load env vars (useful for local dev) ---
load_dotenv(override=True)

logger = logging.getLogger("algogpt.redis")

# --- Redis URL (Render Key-Value → REDIS_URL) ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client: redis.Redis | None = None

try:
    redis_client = redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,           # string במקום bytes
        socket_connect_timeout=5,        # fail fast אם אין חיבור
        health_check_interval=30,        # שומר חיבור בריא
    )
    # בדיקה ראשונית שהחיבור חי
    redis_client.ping()
    logger.info(f"[Redis] ✅ Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    logger.error(f"[Redis] ❌ Connection failed: {e}")


# --- API functions ---

def set_value(key: str, value: str, expire: int | None = None) -> bool:
    """שומר key->value עם TTL (expire בשניות) אם ניתן"""
    if not redis_client:
        return False
    try:
        redis_client.set(key, value, ex=expire)
        return True
    except Exception as e:
        logger.error(f"[Redis] set_value error for {key}: {e}")
        return False


def get_value(key: str) -> str | None:
    """מחזיר value מתוך Redis אם קיים"""
    if not redis_client:
        return None
    try:
        return redis_client.get(key)
    except Exception as e:
        logger.error(f"[Redis] get_value error for {key}: {e}")
        return None


def delete_value(key: str) -> bool:
    """מוחק key מ־Redis"""
    if not redis_client:
        return False
    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        logger.error(f"[Redis] delete_value error for {key}: {e}")
        return False

