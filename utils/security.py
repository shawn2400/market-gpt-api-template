# utils/security.py
from __future__ import annotations
import os, hmac, hashlib, time
from typing import Optional

HMAC_SECRET = os.getenv("HMAC_SECRET", "").encode()
IDEMPOTENCY_TTL = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "600"))

# Redis (אופציונלי)
_USE_REDIS = os.getenv("USE_REDIS_IDEMPOTENCY", "0").lower() in ("1","true","yes")
_r = None
if _USE_REDIS:
    try:
        import redis
        _r = redis.StrictRedis.from_url(os.getenv("REDIS_URL"))
    except Exception as e:
        _r = None  # fallback בהמשך

# זיכרון מקומי כגיבוי
_IDEM = {}

def verify_hmac(x_signature: Optional[str], raw_body: bytes) -> bool:
    """
    מאמת שה־POST הגיע מה-Core שלך:
    Header: X-Signature = hex(hmac_sha256(HMAC_SECRET, raw_body))
    """
    if not HMAC_SECRET:
        # אם לא הוגדר secret – לא נכשל; השארת פתוח בכוונה (דבג/סטייג׳ינג)
        return True
    if not x_signature:
        return False
    expected = hmac.new(HMAC_SECRET, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, x_signature)

def idem_seen(key: Optional[str]) -> bool:
    """
    מחזיר True אם כבר ראינו את ה-idempotency key לאחרונה (כלומר כפילות),
    אחרת מסמן אותו ומחזיר False.
    """
    if not key:
        return False

    now = int(time.time())

    # Redis backend
    if _r:
        try:
            # setnx + expire (אטומי)
            added = _r.set(name=f"idemp:{key}", value=str(now), nx=True, ex=IDEMPOTENCY_TTL)
            return (added is None) or (added is False)
        except Exception:
            pass  # ניפול ל-in-memory אם Redis לא זמין

    # In-memory fallback
    # ניקוי ישנים
    for k, ts in list(_IDEM.items()):
        if now - ts > IDEMPOTENCY_TTL:
            _IDEM.pop(k, None)

    if key in _IDEM:
        return True
    _IDEM[key] = now
    return False
