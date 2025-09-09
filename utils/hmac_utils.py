# utils/hmac_utils.py
from __future__ import annotations
import os
import hmac
import hashlib
import time
import logging
from typing import Optional

logger = logging.getLogger("algogpt.hmac")

# ===== נסה להשתמש במימוש המרכזי (אם קיים) לשמירה על אחידות בין מודולים =====
try:
    from utils.security import verify_hmac as _sec_verify_hmac  # type: ignore
    from utils.security import idem_seen as _sec_idem_seen      # type: ignore
except Exception:
    _sec_verify_hmac = None
    _sec_idem_seen = None

# ===== תצורה =====
_secret_str = (
    os.getenv("WEBHOOK_HMAC_SECRET")
    or os.getenv("HMAC_SECRET")
    or ""
).strip()
SECRET: bytes = _secret_str.encode("utf-8") if _secret_str else b""

# TTL לברירת מחדל לאידמפוטנסיות (שניות)
_IDEM_TTL = int(os.getenv("IDEMPOTENCY_TTL_SEC", "300"))

# Redis (אופציונלי)
_RED = None
if os.getenv("REDIS_URL"):
    try:
        import redis  # type: ignore
        _RED = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    except Exception as e:
        logger.warning("Redis unavailable for idem_seen: %s", e)
        _RED = None


# ===== Helpers =====
def _extract_sig(s: Optional[str]) -> str:
    """
    מחלץ את ה-hex מהחתימה.
    תומך ב:
      - "sha256=<hex>"
      - "sha256=<hex>, t=<ts>"
      - "<hex>" נקי
    """
    if not s:
        return ""
    s = str(s).strip()

    # אם הגיע Header מרובה רכיבים (פסיקים), נאתר את רכיב sha256=
    if "," in s and "sha256=" in s.lower():
        for part in s.split(","):
            part = part.strip()
            if part.lower().startswith("sha256="):
                return part.split("=", 1)[1].strip()

    # צורה רגילה עם תחילית
    if s.lower().startswith("sha256="):
        return s.split("=", 1)[1].strip()

    # אחרת נניח שזה hex ישיר
    return s


def _hmac_sha256_hex(secret: bytes, body: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


# ===== Public API =====
def verify_hmac(signature: Optional[str], raw_body: bytes) -> bool:
    """
    אימות HMAC-SHA256 של גוף הבקשה (raw_body) מול חתימה (signature).
    מחזיר True אם תואם, אחרת False.

    חתימות נתמכות:
      - "sha256=<hex>"
      - "<hex>" נקי
    """
    # העדפה למימוש מרכזי אם זמין
    if _sec_verify_hmac is not None:
        try:
            return bool(_sec_verify_hmac(signature, raw_body))
        except Exception:
            # נפילה חזרה למימוש המקומי
            pass

    if not SECRET:
        logger.warning("WEBHOOK_HMAC_SECRET/HMAC_SECRET not configured")
        return False

    sig = _extract_sig(signature).lower()
    if not sig:
        return False

    try:
        mac = _hmac_sha256_hex(SECRET, raw_body).lower()
        return hmac.compare_digest(mac, sig)
    except Exception:
        return False


def verify_inbound(body: bytes, signature: str) -> bool:
    """
    תאימות לאחור: חתימה שנקראה בעבר כ-(body, signature).
    """
    return verify_hmac(signature, body)


def idem_seen(key: Optional[str]) -> bool:
    """
    בדיקת אידמפוטנסיות. מחזיר:
      - True אם המפתח נראה לאחרונה (כפילות)
      - False אם טרי (מסמן כעת עם TTL)

    Redis אם זמין, אחרת בזיכרון מקומי.
    """
    # העדפה למימוש מרכזי אם זמין
    if _sec_idem_seen is not None:
        try:
            return bool(_sec_idem_seen(key))
        except Exception:
            pass

    if not key:
        return False

    # Redis backend
    if _RED is not None:
        try:
            # SET NX EX: יוצר אם לא קיים (מחזיר True אם חדש)
            created = _RED.set(f"idem:{key}", "1", nx=True, ex=_IDEM_TTL)
            return not bool(created)  # אם לא נוצר – כבר קיים => כפילות
        except Exception as e:
            logger.warning("Redis idem_seen error: %s", e)

    # In-memory fallback
    now = time.time()
    _MemIdem.cleanup(now)
    if _MemIdem.exists(key, now):
        return True
    _MemIdem.add(key, now + _IDEM_TTL)
    return False


# ===== In-memory idem implementation =====
class _MemIdem:
    _store: dict[str, float] = {}
    _last_gc: float = 0.0
    _GC_EVERY: float = 60.0

    @classmethod
    def exists(cls, key: str, now: float) -> bool:
        exp = cls._store.get(key)
        return bool(exp and exp > now)

    @classmethod
    def add(cls, key: str, exp: float) -> None:
        cls._store[key] = exp

    @classmethod
    def cleanup(cls, now: float) -> None:
        if now - cls._last_gc < cls._GC_EVERY:
            return
        cls._last_gc = now
        dead = [k for k, exp in cls._store.items() if exp <= now]
        for k in dead:
            cls._store.pop(k, None)


__all__ = ["verify_hmac", "verify_inbound", "idem_seen"]








