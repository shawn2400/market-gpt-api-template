# utils/redis_client.py
from __future__ import annotations
import os, logging
from typing import Optional

logger = logging.getLogger("algogpt.redis")

REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

redis_client: Optional["redis.Redis"] = None  # type: ignore[name-defined]

if REDIS_URL:
    try:
        import redis  # type: ignore
        # socket_connect_timeout קצר כדי לא לתקוע את האפליקציה אם אין חיבור
        redis_client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True, socket_connect_timeout=2.0
        )
        try:
            redis_client.ping()
            logger.info({"event": "redis.connected", "url": REDIS_URL})
        except Exception as e:
            logger.warning({"event": "redis.ping_failed", "error": str(e)})
    except Exception as e:
        logger.warning({"event": "redis.unavailable", "error": str(e), "url": REDIS_URL})
        redis_client = None
else:
    logger.info({"event": "redis.disabled", "reason": "REDIS_URL missing"})

def get_redis() -> Optional["redis.Redis"]:  # type: ignore[name-defined]
    """החזר לקוח Redis אם זמין, אחרת None."""
    return redis_client

__all__ = ["redis_client", "get_redis"]










