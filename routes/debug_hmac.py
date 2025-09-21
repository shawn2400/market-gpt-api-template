# routes/debug_hmac.py
from __future__ import annotations
import os, hmac, hashlib, base64
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

router = APIRouter()

def _get_secret_bytes() -> bytes:
    """
    עדיפות:
    1) OPS_SIGN_SECRET (אם קיים)
    2) WEBHOOK_HMAC_SECRET
    אם הסטרינג באורך 64 תווים hex – נהפוך ל-bytes. אחרת, ניקח UTF-8.
    """
    raw = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
    s = raw.strip()
    if len(s) == 64:
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

@router.get("/_debug/hmac")
async def hmac_info():
    # public ping (לבדיקת 200 ללא מפתח)
    return JSONResponse({"ok": True})

@router.post("/_debug/hmac")
async def hmac_compute(request: Request):
    """
    מחשב HMAC-SHA256 על גוף הבקשה (raw bytes) עם אותו סוד של /ops/approve/signed.
    מחזיר גם HEX וגם Base64 לצורך השוואה.
    """
    body = await request.body()
    secret = _get_secret_bytes()
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    hex_srv = digest.hex()
    b64_srv = base64.b64encode(digest).decode()

    hdrs = request.headers
    cand_names = ["x-signature", "x-webhook-hmac", "x-hub-signature-256"]
    got_raw = {n: hdrs.get(n, "") for n in cand_names}
    got_clean = {n: _clean_sig(v) for n, v in got_raw.items()}

    match_hex = any(_clean_sig(v).lower() == hex_srv for v in got_raw.values())
    match_b64 = any(_clean_sig(v) == b64_srv for v in got_raw.values())

    def _hint(k: str) -> str:
        val = os.getenv(k, "")
        if len(val) > 10:
            return f"{val[:6]}...{val[-4:]}"
        return val

    return JSONResponse({
        "ok": True,
        "len_body": len(body),
        "server_hex": hex_srv,
        "server_b64": b64_srv,
        "headers_raw": got_raw,
        "headers_clean": got_clean,
        "match_hex": match_hex,
        "match_b64": match_b64,
        "secret_hints": {
            "OPS_SIGN_SECRET": _hint("OPS_SIGN_SECRET"),
            "WEBHOOK_HMAC_SECRET": _hint("WEBHOOK_HMAC_SECRET"),
            "using": "OPS_SIGN_SECRET" if os.getenv("OPS_SIGN_SECRET") else "WEBHOOK_HMAC_SECRET",
        },
    })



