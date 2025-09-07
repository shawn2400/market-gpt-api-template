# utils/security.py
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Optional, Dict
from fastapi import Request, HTTPException, status

# === Env ===
USE_REDIS_IDEM = os.getenv("USE_REDIS_IDEM", "0").lower() in ("1", "true", "yes")
IDEMPOTENCY_TTL_SEC = int(os.getenv("IDEMPOTENCY_TTL_SEC", "900"))

# נקרא גם מהשם הישן HMAC_SECRET אם יש
HMAC_SECRET_RAW = os.getenv("WEBHOOK_HMAC_SECRET", os.getenv("HMAC_SECRET", ""))
HMAC_SECRET = HMAC_SECRET_RAW.encode("utf-8") if HMAC_SECRET_RAW else b""

API_BEARER = (os.getenv("API_BEARER_TOKEN", "")).strip()

# === Storage for idempotency ===
if USE_REDIS_IDEM:
    import redis
    RED = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
else:
    _IDEM: Dict[str, float] = {}

# === Helpers ===
def _parse_signature(sig_header: Optional[str]) -> Optional[str]:
    """
    תומך גם ב-X-Algogpt-Signature: sha256=<hex> וגם בערך hex טהור.
    """
    if not sig_header:
        return None
    sig = str(sig_header).strip()
    if "=" in sig:
        scheme, val = sig.split("=", 1)
        if scheme.lower() != "sha256":
            return None
        return val.strip()
    return sig

def verify_hmac(signature: Optional[str], raw_body: bytes) -> bool:
    """
    אם אין HMAC_SECRET → לא נכשל (נוח לפיתוח).
    אם יש HMAC_SECRET → נדרוש חתימה תואמת.
    """
    if not HMAC_SECRET:
        return True
    sig = _parse_signature(signature)
    if not sig:
        return False
    try:
        expected = hmac.new(HMAC_SECRET, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

def verify_bearer(request: Request) -> None:
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
    זוכר מפתחות idempotency לזמן קצר. מחזיר True אם כבר נראה.
    """
    if not key:
        return False
    now = time.time()
    if USE_REDIS_IDEM:
        rk = f"idem:{key}"
        if RED.exists(rk):
            return True
        RED.setex(rk, IDEMPOTENCY_TTL_SEC, "1")
        return False
    # in-memory fallback + ניקוי הישן
    for k, ts in list(_IDEM.items()):
        if now - ts > IDEMPOTENCY_TTL_SEC:
            _IDEM.pop(k, None)
    if key in _IDEM:
        return True
    _IDEM[key] = now
    return False

def _make_idem_key(request: Request, body: bytes) -> str:
    """
    לוקח X-Idempotency-Key אם יש; אחרת יוצר גיבוב מהנתיב+גוף.
    """
    key = (
        request.headers.get("idempotency-key")
        or request.headers.get("x-idempotency-key")
        or ""
    ).strip()
    if key:
        return key
    # גיבוב דטרמיניסטי מהנתיב+גוף
    h = hashlib.sha256()
    h.update(request.url.path.encode("utf-8"))
    h.update(b"||")
    h.update(body or b"")
    return h.hexdigest()

async def guard(request: Request) -> dict:
    """
    Bearer חובה (אם קיים ב-ENV), HMAC חובה אם יש WEBHOOK_HMAC_SECRET, 
    ו-idempotency אוטומטי.
    מחזיר {"duplicate": True/False}
    """
    verify_bearer(request)
    body = await request.body()

    # HMAC: נקבל מ-X-Algogpt-Signature או X-Hub-Signature-256
    sig = (
        request.headers.get("x-algogpt-signature")
        or request.headers.get("X-Algogpt-Signature")
        or request.headers.get("x-hub-signature-256")
        or request.headers.get("X-Hub-Signature-256")
    )
    if not verify_hmac(sig, body):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad signature")

    # Idempotency
    ikey = _make_idem_key(request, body)
    dup = idem_seen(ikey)
    return {"duplicate": dup, "idem_key": ikey}



