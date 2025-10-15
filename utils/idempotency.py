# utils/idempotency.py
from __future__ import annotations
import os, time, json, hashlib, logging, inspect
from typing import Optional, Dict, Any, Tuple

try:
    from utils.redis_client import get_redis  # יציב: מחזיר קליינט סינכרוני או אסינכרוני
except Exception:
    get_redis = lambda: None  # type: ignore

log = logging.getLogger("algogpt.idem")

DEFAULT_TTL_SEC = int(os.getenv("IDEMPOTENCY_WEBHOOK_TTL_SEC", "30"))

# in-memory fallback (רק לשוליים / כשאין Redis)
_mem: Dict[str, float] = {}

def _digest_key(parts: Tuple[Any, ...]) -> str:
    raw = json.dumps(parts, separators=(",", ":"), sort_keys=True, default=str)
    return "idem:wh:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

async def _redis_setnx_ex(r: Any, key: str, value: str, ttl_sec: int) -> bool:
    """
    מאחד לוגיקה לקליינטים סינכרוניים/אסינכרוניים:
    - אם יש r.set(..., nx=True, ex=ttl) — נשתמש בזה.
    - אחרת ננסה setnx + expire.
    - מתחשב במקרה שהקריאה מחזירה awaitable.
    """
    ttl = max(1, int(ttl_sec or 0))

    # case 1: set(name, value, nx=True, ex=ttl)
    if hasattr(r, "set"):
        fn = getattr(r, "set")
        try:
            res = fn(key, value, nx=True, ex=ttl)
            if inspect.isawaitable(res):
                res = await res  # type: ignore[assignment]
            return bool(res)
        except TypeError:
            # חלק מהדרייברים לא תומכים nx/ex ב־set, ננסה setnx+expire
            pass
        except Exception as e:
            log.debug("idempotency.redis.set error: %s", e)

    # case 2: setnx + expire
    if hasattr(r, "setnx"):
        try:
            res = r.setnx(key, value)
            if inspect.isawaitable(res):
                res = await res
            ok = bool(res)
            if ok and hasattr(r, "expire"):
                ex_res = r.expire(key, ttl)
                if inspect.isawaitable(ex_res):
                    await ex_res
            return ok
        except Exception as e:
            log.debug("idempotency.redis.setnx/expire error: %s", e)

    # לא נתמך/נכשל
    return False

async def check_and_set(parts: Tuple[Any, ...], ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
    """
    מחזיר True אם זו הפעם הראשונה (שמנו key), אחרת False (כפילות).
    עובד מול Redis (async או sync). אם אין/נכשל — נופל לזיכרון מקומי.
    """
    key = _digest_key(parts)
    now = time.time()

    # Redis first
    r = None
    try:
        r = get_redis()
    except Exception:
        r = None

    if r is not None:
        try:
            ok = await _redis_setnx_ex(r, key, str(int(now)), ttl_sec)
            if ok:
                return True
        except Exception as e:
            log.warning("idempotency.redis_error: %s", e)

    # === Memory fallback ===
    ts = _mem.get(key, 0.0)
    if now - ts < ttl_sec:
        return False
    _mem[key] = now

    # ניקוי עדין
    try:
        cutoff = max(2 * ttl_sec, 120)
        for k, v in list(_mem.items()):
            if now - v > cutoff:
                _mem.pop(k, None)
    except Exception:
        _mem.clear()
    return True

async def idem_for_request(
    body: bytes,
    headers: Dict[str, str],
    extra: Optional[Dict[str, Any]] = None,
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> bool:
    """
    בונה מפתח Idempotency ל־Webhook/בקשה: חתימה/טיימסטמפ/אוט' + האש של ה־body + extra (אופציונלי).
    """
    sig = headers.get("x-signature") or headers.get("X-Signature") or headers.get("X-Hub-Signature-256") or ""
    ts  = headers.get("X-Signature-Timestamp") or headers.get("x-signature-timestamp") or ""
    auth= headers.get("Authorization") or headers.get("authorization") or ""
    parts = (
        sig,
        ts,
        auth[:64],  # לא שומרים את כל הטוקן
        hashlib.sha256(body or b"").hexdigest(),
        json.dumps(extra or {}, sort_keys=True, separators=(",", ":")),
    )
    return await check_and_set(parts, ttl_sec=ttl_sec)

__all__ = ["check_and_set", "idem_for_request", "DEFAULT_TTL_SEC"]




