# routes/ops_approve.py
from __future__ import annotations
import os, hmac, hashlib, base64, json
from typing import Optional
from fastapi import APIRouter, Request, Header
from starlette.responses import JSONResponse

router = APIRouter()

def _secret_bytes() -> bytes:
    raw = os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or ""
    raw = raw.strip()
    if len(raw) == 64:
        try: return bytes.fromhex(raw)
        except Exception: pass
    return raw.encode("utf-8")

def _const_hmac(raw: bytes) -> bytes:
    return hmac.new(_secret_bytes(), raw, hashlib.sha256).digest()

def _eq(a: str, b: str) -> bool:
    try: return hmac.compare_digest(a, b)
    except Exception: return a == b

@router.post("/ops/approve/signed", tags=["ops"])
async def approve_signed(request: Request, x_signature: Optional[str] = Header(default=None)):
    """
    מאשר פעולה חתומה.
    - גוף הבקשה = JSON גולמי.
    - הכותרת X-Signature יכולה להיות:
        * hex של SHA256 HMAC
        * או base64 של הדיג'סט
        * או "sha256=<hex>"
    """
    raw = await request.body()
    if not raw:
        return JSONResponse(status_code=400, content={"detail": "Empty body"})

    # חשב בצד שרת
    srv_digest = _const_hmac(raw)
    srv_hex = srv_digest.hex()
    srv_b64 = base64.b64encode(srv_digest).decode()

    sig = (x_signature or "").strip()
    sig_clean = sig.split("=",1)[1].strip() if sig.lower().startswith("sha256=") else sig
    ok = False
    if sig_clean:
        # קבל גם hex וגם b64
        ok = _eq(sig_clean.lower(), srv_hex) or _eq(sig_clean, srv_b64)

    if not ok:
        return JSONResponse(status_code=401, content={
            "detail": "Bad signature",
            "server_hex": srv_hex,
            "server_b64": srv_b64,
        })

    # פרס JSON (אינו משנה לחתימה – חתמנו על ה-raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return JSONResponse(status_code=400, content={"detail": f"Invalid JSON: {e}"})

    # מינימום ולידציה בסיסית
    for k in ("action","ticket_id","symbol","side","qty","lev","budget"):
        if k not in payload:
            return JSONResponse(status_code=422, content={"detail": f"Missing field: {k}"})

    # כאן היית קורא לאקזקיושן/טיקט וכד'… (השארתי כהדמיה)
    return {"ok": True, "approved": True, "echo": payload}







