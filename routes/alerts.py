# routes/alerts.py
import binascii, hashlib, hmac, os
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])

def _get_secret_bytes() -> Optional[bytes]:
    secret = os.getenv("ALERTS_INGEST_HMAC_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
    if not secret:
        return None
    is_hex = os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX","0").lower() in ("1","true","yes","on")
    try:
        return binascii.unhexlify(secret.strip()) if is_hex else secret.encode()
    except Exception:
        return None

def _server_hexdigest(raw: bytes) -> Optional[str]:
    key = _get_secret_bytes()
    if not key:
        return None
    return hmac.new(key, raw, hashlib.sha256).hexdigest()

def _client_hexdigest_from_headers(request: Request) -> Optional[str]:
    hv = request.headers.get("x-webhook-hmac") or request.headers.get("X-Webhook-Hmac")
    if not hv:
        hv = request.headers.get("x-hub-signature-256") or request.headers.get("X-Hub-Signature-256")
        if hv and hv.startswith("sha256="):
            hv = hv.split("=",1)[1]
    if not hv:
        return None
    hv = hv.strip().lower()
    return hv if len(hv) == 64 else None

@router.get("/ping")
async def ping():
    return {"ok": True, "service": "alerts"}

@router.post("/_debug/alerts-hmac-check")
async def debug_hmac_check(request: Request):
    raw = await request.body()
    calc = _server_hexdigest(raw)
    if not calc:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured"})
    return {"ok": True, "server_hex": calc, "body_len": len(raw)}

@router.post("/ingest")
async def ingest(request: Request):
    raw = await request.body()
    server_hex = _server_hexdigest(raw)
    if not server_hex:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured"})

    client_hex = _client_hexdigest_from_headers(request)
    if not client_hex:
        return JSONResponse(status_code=401, content={"ok": False, "error": "missing_hmac_header"})
    if client_hex != server_hex:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid HMAC signature"})

    # TODO: parse JSON ולשלוח נוטיפיקציה (טלגרם/סלאק) אם צריך
    return {"ok": True, "accepted": True}
































