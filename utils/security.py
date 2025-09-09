# utils/security.py
from __future__ import annotations
import os
import time
import hmac
import hashlib
import logging
from typing import Optional, Dict
from fastapi import Request, HTTPException, status

logger = logging.getLogger("algogpt.security")

# ===== Env =====
USE_REDIS_IDEM = os.getenv("USE_REDIS_IDEM", "0").lower() in ("1", "true", "yes", "on")
IDEMPOTENCY_TTL_SEC = int(os.getenv("IDEMPOTENCY_TTL_SEC", "900"))

# נקרא גם מהשם הישן HMAC_SECRET אם יש
_HMAC_SECRET_RAW = os.getenv("WEBHOOK_HMAC_SECRET", os.getenv("HMAC_SECRET", ""))
HMAC_SECRET: bytes = _HMAC_SECRET_RAW.encode("utf-8") if _HMAC_SECRET_RAW else b""

API_BEARER = (os.getenv("API_BEARER_TOKEN", "")).strip()

# ===== Redis (optional) =====
RED = None
_REDIS_OK = False
if USE_REDIS_IDEM:
    try:
        import redis  # type: ignore
        RED = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        _REDIS_OK = True
    except Exception as e:
        logger.warning("Redis unavailable for idempotency: %s", e)
        RED = None
        _REDIS_OK = False

# in-memory idem fallback
_IDEM: Dict[str, float] = {}

# ===== Helpers =====
def _parse_signature(sig_header: Optional[str]) -> Optional[str]:
    """
    מחלץ hex של HMAC מהכותרת. תומך ב:
      - 'sha256=<hex>'
      - 'sha256=<hex>, t=<ts>'
      - '<hex>' נקי
    """
    if not sig_header:
        return None
    s = str(sig_header).strip()

    # מרובה רכיבים עם פסיקים
    if "," in s and "sha256=" in s.lower():
        for part in s.split(","):
            part = part.strip()
            if part.lower().startswith("sha256="):
                return part.split("=", 1)[1].strip() or None

    # צורה רגילה
    if s.lower().startswith("sha256="):
        return s.split("=", 1)[1].strip() or None

    # hex נקי
    return s or None


def verify_hmac(signature: Optional[str], raw_body: bytes) -> bool:
    """
    אם אין HMAC_SECRET → מחזיר True (פיתוח נוח).
    אם יש HMAC_SECRET → דורש התאמה מלאה (HMAC-SHA256).
    """
    if not HMAC_SECRET:
        return True  # dev convenience

    sig = _parse_signature(signature)
    if not sig:
        return False

    try:
        expected = hmac.new(HMAC_SECRET, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected.lower(), sig.lower())
    except Exception:
        return False


def verify_bearer(request: Request) -> None:
    """
    אם הוגדר API_BEARER_TOKEN ב-ENV → נדרוש Bearer.
    אחרת—נעבור (פיתוח).
    """
    if not API_BEARER:
        return
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = auth.split(" ", 1)[1].strip()
    if token != API_BEARER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad bearer")


def idem_seen(key: Optional[str]) -> bool:
    """
    זוכר מפתחות idempotency לזמן קצר.
    מחזיר True אם כבר נראה לאחרונה (כפילות), אחרת False.
    """
    if not key:
        return False

    now = time.time()

    # Redis backend אם זמין
    if USE_REDIS_IDEM and _REDIS_OK and RED is not None:
        try:
            rk = f"idem:{key}"
            # SET NX EX: יצירה אם לא קיים; מחזיר True אם חדש
            created = RED.set(rk, "1", nx=True, ex=IDEMPOTENCY_TTL_SEC)
            return not bool(created)  # אם כבר קיים → duplicate=True
        except Exception as e:
            logger.warning("Redis idem_seen error: %s", e)

    # in-memory fallback + ניקוי ישנים
    for k, ts in list(_IDEM.items()):
        if now - ts > IDEMPOTENCY_TTL_SEC:
            _IDEM.pop(k, None)

    if key in _IDEM:
        return True
    _IDEM[key] = now
    return False


def _make_idem_key(request: Request, body: bytes) -> str:
    """
    לוקח X-Idempotency-Key / Idempotency-Key אם יש; אחרת גיבוב נתיב+גוף.
    """
    key = (
        request.headers.get("idempotency-key")
        or request.headers.get("Idempotency-Key")
        or request.headers.get("x-idempotency-key")
        or request.headers.get("X-Idempotency-Key")
        or ""
    ).strip()
    if key:
        return key

    # גיבוב דטרמיניסטי מהנתיב + גוף
    h = hashlib.sha256()
    h.update(request.url.path.encode("utf-8"))
    h.update(b"||")
    h.update(body or b"")
    return h.hexdigest()


async def guard(request: Request) -> dict:
    """
    שמירה מרכזית לראוטים רגישים:
      - Bearer חובה אם קיים ב-ENV.
      - HMAC חובה אם הוגדר WEBHOOK_HMAC_SECRET/HMAC_SECRET.
      - Idempotency (Redis או in-memory).

    מחזיר: {"duplicate": bool, "idem_key": str}
    """
    # Bearer (אם הוגדר)
    verify_bearer(request)

    # גוף הבקשה (raw)
    body = await request.body()

    # HMAC (אם הוגדר סוד)
    sig = (
        request.headers.get("x-algogpt-signature")
        or request.headers.get("X-Algogpt-Signature")
        or request.headers.get("x-hub-signature-256")
        or request.headers.get("X-Hub-Signature-256")
        or request.headers.get("x-signature")
        or request.headers.get("X-Signature")
    )
    if not verify_hmac(sig, body):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad signature")

    # Idempotency
    ikey = _make_idem_key(request, body)
    dup = idem_seen(ikey)
    return {"duplicate": dup, "idem_key": ikey}


__all__ = [
    "verify_hmac",
    "verify_bearer",
    "idem_seen",
    "guard",
]



