# routes/ops_approve.py
from __future__ import annotations
import os, hmac, hashlib, json
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

router = APIRouter()

def _get_secret_bytes() -> bytes:
    """
    עדיפות ל-OPS_SIGN_SECRET; נפילה ל-WEBHOOK_HMAC_SECRET.
    אם האורך בדיוק 64 תווים HEX – נמיר ל-bytes.
    אחרת – נתייחס כסטרינג-בייטס.
    """
    s = (os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    return s.encode("utf-8")

def _hmac_hex(raw: bytes) -> str:
    return hmac.new(_get_secret_bytes(), raw, hashlib.sha256).hexdigest()

@router.post("/ops/approve/signed", tags=["ops"])
async def ops_approve_signed(request: Request, x_signature: str = Header(default="")):
    """
    מאשר בקשה חתומה. הלקוח חייב:
      - לשלוח את גוף ה-JSON בטווח הבייטים המדויק (ללא שינוי)
      - לחשב HMAC-SHA256 עם hexkey=<SECRET> (HEX->BYTES)
      - לשים את ההקס בכותרת X-Signature
    """
    raw = await request.body()
    srv_sig = _hmac_hex(raw)
    got_sig = (x_signature or "").strip().lower()

    if not got_sig:
        return JSONResponse(status_code=400, content={"detail": "Missing signature"})

    if not hmac.compare_digest(got_sig, srv_sig):
        return JSONResponse(status_code=400, content={"detail": "Bad signature"})

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON"})

    # כאן תוכל לממש את האישור בפועל (שליחת טיקט לביצוע וכו')
    # כרגע נחזיר echo לאימות.
    return JSONResponse({
        "ok": True,
        "verified": True,
        "payload": payload,
    })







