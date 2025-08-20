# utils/redis_client.py
import os
import logging
import redis
from dotenv import load_dotenv

# Load .env if exists (local dev)
load_dotenv()

logger = logging.getLogger("algogpt.redis")

# Redis URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

try:
    redis_client = redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,  # return strings instead of bytes
        socket_connect_timeout=5,  # fail fast if unreachable
        health_check_interval=30,
    )
    # Quick test connection
    redis_client.ping()
    logger.info(f"[Redis] Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    logger.error(f"[Redis] Failed to connect to {REDIS_URL}: {e}")


def set_value(key: str, value: str, expire: int | None = None) -> bool:
    """שומר ערך ב־Redis עם מפתח"""
    if not redis_client:
        return False
    try:
        redis_client.set(key, value, ex=expire)
        return True
    except Exception as e:
        logger.error(f"[Redis] set_value error for {key}: {e}")
        return False


def get_value(key: str) -> str | None:
    """מחזיר ערך מ־Redis לפי מפתח"""
    if not redis_client:
        return None
    try:
        return redis_client.get(key)
    except Exception as e:
        logger.error(f"[Redis] get_value error for {key}: {e}")
        return None


def delete_value(key: str) -> bool:
    """מוחק ערך לפי מפתח"""
    if not redis_client:
        return False
    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        logger.error(f"[Redis] delete_value error for {key}: {e}")
        return False
