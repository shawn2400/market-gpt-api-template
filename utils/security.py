# utils/security.py
from __future__ import annotations
import os, hmac, hashlib, time
from typing import Optional

# HMAC
_HMAC_SECRET = (os.getenv("OUTGOING_HMAC_SECRET") or os.getenv("HMAC_SECRET") or "").encode()

def verify_hmac(signature_hex: Optional[str], body: bytes) -> bool:
    """
    אימות HMAC-SHA256 על גוף הבקשה.
    אם לא הוגדר secret — נאשר אוטומטית (לצורך פיתוח).
    """
    if not _HMAC_SECRET:
        return True
    if not signature_hex:
        return False
    digest = hmac.new(_HMAC_SECRET, body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(digest, signature_hex)
    except Exception:
        return digest == signature_hex

# Idempotency (זיכרון או Redis)
_USE_REDIS = os.getenv("USE_REDIS_IDEMPOTENCY","0").lower() in ("1","true","yes")
_TTL = int(os.getenv("IDEMPOTENCY_TTL_SECONDS","600"))

if _USE_REDIS:
    import redis
    _RED = redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), decode_responses=True)
else:
    _idem_map: dict[str, float] = {}

def idem_seen(key: str) -> bool:
    """
    מחזיר True אם המפתח כבר נראה לאחרונה (בתוך TTL).
    אחרת מסמן אותו ומחזיר False.
    """
    if not key:
        return False
    now = time.time()
    if _USE_REDIS:
        if _RED.setnx(f"idem:{key}", int(now)):
            _RED.expire(f"idem:{key}", _TTL)
            return False
        return True
    # in-memory
    # ניקוי זנבות פשוט
    for k, ts in list(_idem_map.items()):
        if now - ts > _TTL:
            _idem_map.pop(k, None)
    if key in _idem_map:
        return True
    _idem_map[key] = now
    return False

