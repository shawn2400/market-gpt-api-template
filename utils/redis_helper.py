# utils/redis_helper.py
from __future__ import annotations
import os
import logging
from typing import Optional

log = logging.getLogger("algogpt.redis")
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

def redis_enabled() -> bool:
    return bool(aioredis and REDIS_URL)

async def get_redis():
    """
    מחזיר client אסינכרוני עם timeouts קצרים ו-healthcheck.
    במקרה של כשל – מחזיר None ולא מפיל את היישום.
    """
    if not redis_enabled():
        return None
    try:
        return aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT","1.5")),
            socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT","1.5")),
            health_check_interval=int(os.getenv("REDIS_HEALTHCHECK_SEC","30")),
            retry_on_timeout=True,
        )
    except Exception as e:
        log.warning({"event":"redis.client_init_failed","error":str(e)})
        return None

