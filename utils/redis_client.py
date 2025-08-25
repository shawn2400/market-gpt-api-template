# utils/redis_client.py
from __future__ import annotations
import os, logging, redis

logger = logging.getLogger("algogpt.redis")

_raw = os.getenv("REDIS_URL", "")
REDIS_URL = (_raw or "").strip()

redis_client: redis.Redis | None = None

def _mask(url: str) -> str:
    # redis://user:pass@host:6379 -> redis://user:****@host:6379
    try:
        if "@" in url and "://" in url:
            head, tail = url.split("://", 1)
            creds_host = tail.split("@", 1)
            if len(creds_host) == 2:
                creds, host = creds_host
                if ":" in creds:
                    u, p = creds.split(":", 1)
                    return f"{head}://{u}:****@{host}"
        return url
    except Exception:
        return url

try:
    if not REDIS_URL:
        redis_client = None
        logger.warning("[Redis] ⚠️ REDIS_URL not set → using in-memory fallback only")
    else:
        redis_client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            health_check_interval=30,
        )
        redis_client.ping()
        logger.info(f"[Redis] ✅ Connected to { _mask(REDIS_URL) }")
except Exception as e:
    redis_client = None
    logger.error(f"[Redis] ❌ Connection failed ({_mask(REDIS_URL)}): {e} -> fallback to in-memory")






