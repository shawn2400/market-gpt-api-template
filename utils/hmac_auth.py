# utils/hmac_auth.py
from __future__ import annotations
import hmac, hashlib, time, os
from typing import Optional
from fastapi import Request, HTTPException, status

_HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("API_SIGNING_SECRET") or "").encode("utf-8")
_SKEW_SEC = int(os.getenv("HMAC_TS_SKEW_SEC", "120"))  # חלון זמן סביר

def _const_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return False

async def hmac_verify(request: Request) -> None:
    """
    Headers expected:
      X-Signature: hex(hmac_sha256(secret, body))
      X-Timestamp: unix seconds
      (optional) X-Id: client id   # לא נבדק, לטובת לוגים
    """
    if not _HMAC_SECRET:
        # אם אין סוד — נאפשר (Fail-Open ניתן לכיבוי ע"י קביעה ל-secret ריק = חובה)
        return

    sig = request.headers.get("x-signature", "")
    ts  = request.headers.get("x-timestamp", "")
    if not sig or not ts:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing hmac headers")

    try:
        ts_int = int(ts)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad timestamp")

    now = int(time.time())
    if abs(now - ts_int) > _SKEW_SEC:
        raise HTTPException(status_code=401, detail="stale request")

    body = await request.body()
    mac  = hmac.new(_HMAC_SECRET, body, hashlib.sha256).hexdigest()
    if not _const_eq(mac, sig.lower()):
        raise HTTPException(status_code=401, detail="invalid signature")

def hmac_protected(func):
    """דקורטור נוח לשימוש בנתיבים סינכרוניים/א-סינכרוניים"""
    import inspect, functools
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            req: Optional[Request] = kwargs.get("request")
            if req is None:
                # נסה לשלוף מה-args
                for a in args:
                    if isinstance(a, Request):
                        req = a; break
            if req is None:
                raise HTTPException(status_code=500, detail="request not provided")
            await hmac_verify(req)
            return await func(*args, **kwargs)
        return wrapper
    else:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # נתיב sync – נשתמש בתלות דרך Depends במקום דקורטור
            raise RuntimeError("Use `Depends(hmac_verify)` for sync routes")
        return wrapper
