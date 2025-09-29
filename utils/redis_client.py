# utils/redis_client.py
from __future__ import annotations
import os, logging, urllib.parse
from typing import Optional

logger = logging.getLogger("algogpt.redis")

# -------------------------------------------------------------------------
# Env / defaults
# -------------------------------------------------------------------------
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
CONNECT_TIMEOUT = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2.0"))   # קצר כדי לא לחסום את האפליקציה
SOCKET_TIMEOUT  = float(os.getenv("REDIS_SOCKET_TIMEOUT",  "2.0"))
CLIENT_NAME     = os.getenv("REDIS_CLIENT_NAME", "algogpt")
SSL_NO_VERIFY   = str(os.getenv("REDIS_SSL_NO_VERIFY", "0")).lower() in {"1","true","on","yes"}

# שמות מודולים: redis/valkey. שני ה-clients זהים API-wise. ננסה redis תחילה ואז valkey.
_redis_mod = None  # type: ignore

def _import_client():
    global _redis_mod
    if _redis_mod is not None:
        return
    try:
        import redis as _r  # type: ignore
        _redis_mod = _r
        return
    except Exception:
        pass
    try:
        import valkey as _r  # type: ignore
        _redis_mod = _r
        return
    except Exception:
        pass

def _mask_url(u: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(u)
        if parsed.password or parsed.username:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        return u
    except Exception:
        return "<unparseable>"

redis_client: Optional["object"] = None  # type: ignore

def _build_kwargs_from_url(url: str) -> dict:
    # Redis.from_url יקבל את רוב הפרטים מה-URL עצמו.
    # כאן רק ערכי ברירת מחדל/מוספים כלליים.
    kw = dict(
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT,
        socket_timeout=SOCKET_TIMEOUT,
        client_name=CLIENT_NAME,
    )
    if url.startswith("rediss://"):
        # בדרך כלל יש תעודה תקינה (Render), אז אין צורך לגעת.
        # אבל אם תרצה לבטל אימות תעודה (לא מומלץ) – REDIS_SSL_NO_VERIFY=1
        if SSL_NO_VERIFY:
            kw.update(ssl=True, ssl_cert_reqs=None)
    return kw

if REDIS_URL:
    _import_client()
    if _redis_mod is None:
        logger.warning({"event": "redis.unavailable", "error": "no redis/valkey client module"})
    else:
        try:
            # בונים לקוח מה-URL (תומך גם ב rediss://)
            kwargs = _build_kwargs_from_url(REDIS_URL)
            redis_client = _redis_mod.Redis.from_url(REDIS_URL, **kwargs)  # type: ignore
            try:
                redis_client.ping()  # type: ignore
                logger.info({"event": "redis.connected", "url": _mask_url(REDIS_URL)})
            except Exception as e:
                logger.warning({"event": "redis.ping_failed", "error": str(e)})
        except Exception as e:
            logger.warning({"event": "redis.unavailable", "error": str(e), "url": _mask_url(REDIS_URL)})
            redis_client = None
else:
    logger.info({"event": "redis.disabled", "reason": "REDIS_URL missing"})

def get_redis() -> Optional["object"]:  # type: ignore
    """החזר לקוח Redis/Valkey אם זמין, אחרת None."""
    return redis_client

__all__ = ["redis_client", "get_redis"]










