# routes/debug_hmac.py
from __future__ import annotations
import os, hmac, hashlib, base64
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

router = APIRouter()

def _get_secret_bytes() -> bytes:
    """
    אותו סוד של /ops/approve/signed:
    קודם OPS_SIGN_SECRET, אם לא – WEBHOOK_HMAC_SECRET.
    מזהה אוטומטית hex-64 (key bytes) או טקסט רגיל (utf-8).
    """
    s = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
    s = s.strip()
    if len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s):
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    return s.encode("utf-8")

def _clean_sig(v: str) -> str:
    v = (v or "").strip()
    if v.lower().startswith("sha256="):
        v = v.split("=", 1)[1].strip()
    return v

@router.post("/_debug/hmac")
async def debug_hmac(request: Request):
    raw = await request.body()
    secret = _get_secret_bytes()

    dig = hmac.new(secret, raw, hashlib.sha256).digest()
    hex_srv = dig.hex()
    b64_srv = base64.b64encode(dig).decode()

    # חתימות בכותרות אפשריות
    hdrs = request.headers
    cand_names = ["x-signature", "x-webhook-hmac", "x-hub-signature-256"]
    got = {n: hdrs.get(n, "") for n in cand_names}
    got_clean = {n: _clean_sig(v) for n, v in got.items()}

    match_hex = any(_clean_sig(v).lower() == hex_srv for v in got.values())
    match_b64 = any(_clean_sig(v) == b64_srv for v in got.values())

    # רמז על הסוד מבלי לחשוף
    s_ops = (os.getenv("OPS_SIGN_SECRET") or "").strip()
    s_wh  = (os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()
    def hint(s: str) -> str:
        return s[:6] + "..." + s[-4:] if len(s) > 10 else ("<empty>" if not s else "<short>")
    hints = {
        "OPS_SIGN_SECRET": hint(s_ops),
        "WEBHOOK_HMAC_SECRET": hint(s_wh),
        "using": "OPS_SIGN_SECRET" if s_ops else ("WEBHOOK_HMAC_SECRET" if s_wh else "<none>"),
    }

    return JSONResponse({
        "ok": True,
        "len_body": len(raw),
        "server_hex": hex_srv,
        "server_b64": b64_srv,
        "headers_raw": got,
        "headers_clean": got_clean,
        "match_hex": match_hex,
        "match_b64": match_b64,
        "secret_hints": hints,
    })

@router.post("/_debug/echo-hmac")
async def echo_hmac(request: Request):
    """
    זהה ל-debug_hmac אבל נשמר לשם תאימות לאחור.
    """
    return await debug_hmac(request)


