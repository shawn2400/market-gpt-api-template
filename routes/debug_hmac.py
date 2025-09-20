# routes/debug_hmac.py
from fastapi import APIRouter, Request
import os, hmac, hashlib, base64

router = APIRouter()

def _extract_sig(s: str) -> str:
    s = (s or "").strip()
    if s.lower().startswith("sha256="):
        return s.split("=", 1)[1].strip()
    return s

@router.post("/_debug/echo-hmac", include_in_schema=False)
async def echo_hmac(request: Request):
    # הסוד שטעון בשרת
    secret_str = os.getenv("WEBHOOK_HMAC_SECRET", "")
    secret = secret_str.encode("utf-8")

    # גוף RAW בדיוק כפי שהתקבל
    body_bytes = await request.body()

    # חישוב digest
    digest = hmac.new(secret, body_bytes, hashlib.sha256).digest()
    hex_sig = digest.hex()
    b64_sig = base64.b64encode(digest).decode()

    # מה הגיע בכותרות (לבדיקה)
    hdr = request.headers.get("x-webhook-hmac") or request.headers.get("x-hub-signature-256") or ""
    given = _extract_sig(hdr)

    return {
        "ok": True,
        "received_len": len(body_bytes),
        "received_preview": body_bytes[:200].decode("utf-8", "ignore"),
        "env_secret_len": len(secret_str),
        "expected": {
            "hex": hex_sig,
            "b64": b64_sig,
            "with_prefix_hex": f"sha256={hex_sig}",
            "with_prefix_b64": f"sha256={b64_sig}",
        },
        "given_header_raw": hdr,
        "given_normalized": given,
    }
