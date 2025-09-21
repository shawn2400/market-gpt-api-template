# routes/debug_hmac.py
from __future__ import annotations
import os, hmac, hashlib, base64
from fastapi import APIRouter, Request, Header
from starlette.responses import JSONResponse

router = APIRouter()

def _get_secret_bytes() -> bytes:
    s = (os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()
    if len(s) == 64:
        try:
            return bytes.fromhex(s)
        except Exception:
            pass
    return s.encode("utf-8")

def _clean(v: str) -> str:
    v = (v or "").strip()
    if v.lower().startswith("sha256="):
        v = v.split("=", 1)[1].strip()
    return v

@router.post("/_debug/hmac", include_in_schema=False)
async def echo_hmac(request: Request, x_signature: str = Header(default=""),
                    x_webhook_hmac: str = Header(default=""),
                    x_hub_signature_256: str = Header(default="")):
    raw = await request.body()
    secret = _get_secret_bytes()
    dig = hmac.new(secret, raw, hashlib.sha256).digest()
    hex_srv = dig.hex()
    b64_srv = base64.b64encode(dig).decode()

    headers_raw = {
        "x-signature": x_signature,
        "x-webhook-hmac": x_webhook_hmac,
        "x-hub-signature-256": x_hub_signature_256,
    }
    headers_clean = {k: _clean(v) for k, v in headers_raw.items()}

    match_hex = any(_clean(v).lower() == hex_srv for v in headers_raw.values())
    match_b64 = any(_clean(v) == b64_srv for v in headers_raw.values())

    def _hint(v: str) -> str:
        return v[:6] + "..." + v[-4:] if len(v) > 10 else v

    return JSONResponse({
        "ok": True,
        "len_body": len(raw),
        "server_hex": hex_srv,
        "server_b64": b64_srv,
        "headers_raw": headers_raw,
        "headers_clean": headers_clean,
        "match_hex": match_hex,
        "match_b64": match_b64,
        "secret_hints": {
            "OPS_SIGN_SECRET": _hint(os.getenv("OPS_SIGN_SECRET", "")),
            "WEBHOOK_HMAC_SECRET": _hint(os.getenv("WEBHOOK_HMAC_SECRET", "")),
            "using": "OPS_SIGN_SECRET" if os.getenv("OPS_SIGN_SECRET") else "WEBHOOK_HMAC_SECRET",
        },
    })


