# utils/security.py
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Optional, Dict

USE_REDIS_IDEM = os.getenv("USE_REDIS_IDEM", "0").lower() in ("1", "true", "yes")
IDEMPOTENCY_TTL_SEC = int(os.getenv("IDEMPOTENCY_TTL_SEC", "900"))
HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET", os.getenv("HMAC_SECRET", ""))).encode()

if USE_REDIS_IDEM:
    import redis
    RED = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
else:
    _IDEM: Dict[str, float] = {}

def verify_hmac(signature: Optional[str], raw_body: bytes) -> bool:
    """
    החתימה בפורמט hex של sha256 HMAC.
    אם אין HMAC_SECRET בקונפיג → נאפשר (כדי שלא ישבור dev).
    """
    if not HMAC_SECRET:
        return True
    if not signature:
        return False
    try:
        expected = hmac.new(HMAC_SECRET, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature).strip())
    except Exception:
        return False

def idem_seen(key: Optional[str]) -> bool:
    """
    זוכר מפתחות לזמן קצר ומונע כפילויות.
    מחזיר True אם כבר נראה בטווח ה־TTL.
    """
    if not key:
        return False
    now = time.time()
    if USE_REDIS_IDEM:
        k = f"idem:{key}"
        if RED.exists(k):
            return True
        RED.setex(k, IDEMPOTENCY_TTL_SEC, "1")
        return False
    # in-memory fallback
    # ניקוי ישן
    for k, v in list(_IDEM.items()):
        if now - v > IDEMPOTENCY_TTL_SEC:
            _IDEM.pop(k, None)
    if key in _IDEM:
        return True
    _IDEM[key] = now
    return False



