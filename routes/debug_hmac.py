# routes/debug_hmac.py
from __future__ import annotations
import os, hmac, hashlib, base64
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

router = APIRouter()

def _get_secret_bytes() -> tuple[bytes, str]:
    # העדפה: WEBHOOK_HMAC_SECRET; אם חסר — OPS_SIGN_SECRET
    raw = os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or ""
    raw = raw.strip()
    used = "WEBHOOK_HMAC_SECRET" if os.getenv("WEBHOOK_HMAC_SECRET") else "OPS_SIGN_SECRET"
    # אם זה בדיוק 64 תווי hex – פרש כ-hex, אחרת כ-utf8
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw), used
        except Exception:
            pass
    return raw.encode("utf-8"), used

def _clean_sig(v: str) -> str:
    v = (v or "").strip()
    if v.lower().startswith("sha256="):
        v = v.split("=", 1)[1].strip()
    return v

@router.post("/_debug/hmac")
async def echo_hmac(request: Request):
    raw = await request.body()
    secret, used_name = _get_secret_bytes()
    digest = hmac.new(secret, raw, hashlib.sha256).digest()
    hex_srv = digest.hex()
    b64_srv = base64.b64encode(digest).decode()

    hdrs = request.headers
    cand = {"x-signature": hdrs.get("x-signature",""),
            "x-webhook-hmac": hdrs.get("x-webhook-hmac",""),
            "x-hub-signature-256": hdrs.get("x-hub-signature-256","")}
    cand_clean = {k:_clean_sig(v) for k,v in cand.items()}

    match_hex = any(_clean_sig(v).lower() == hex_srv for v in cand.values())
    match_b64 = any(_clean_sig(v) == b64_srv for v in cand.values())

    # hints
    s1 = os.getenv("OPS_SIGN_SECRET",""); s2 = os.getenv("WEBHOOK_HMAC_SECRET","")
    def mask(s: str) -> str:
        if not s: return ""
        return s[:6]+"..."+s[-4:] if len(s) > 10 else "***"

    return JSONResponse({
        "ok": True,
        "len_body": len(raw),
        "server_hex": hex_srv,
        "server_b64": b64_srv,
        "headers_raw": cand,
        "headers_clean": cand_clean,
        "match_hex": match_hex,
        "match_b64": match_b64,
        "secret_hints": {"OPS_SIGN_SECRET": mask(s1), "WEBHOOK_HMAC_SECRET": mask(s2), "using": used_name},
    })



