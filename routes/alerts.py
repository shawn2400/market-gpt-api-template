# routes/alerts.py
import binascii, hashlib, hmac, os, json
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

router = APIRouter(prefix="/alerts", tags=["alerts"])

def _get_secret_bytes() -> Optional[bytes]:
    # קודם מפתח ייעודי, אם אין – fallback
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
    # תמיכה בשני פורמטים
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
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured", "body_len": len(raw)})
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

    # Parse JSON
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    # Notify Telegram (אופציונלי – רק אם הגדרות קיימות)
    notified = {"telegram": False}
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if bot_token and chat_id:
        text = (
            "📈 *New Trade Signal*\n"
            f"• Symbol: `{payload.get('symbol','?')}`\n"
            f"• Market: `{payload.get('market','?')}`\n"
            f"• Side: `{payload.get('side','?')}`\n"
            f"• Qty: `{payload.get('qty','?')}`  Lev: `{payload.get('leverage','?')}`\n"
            f"• Score: `{payload.get('score','?')}`\n"
            f"• Reason: {payload.get('reason','')}\n"
            f"• Require Approval: `{payload.get('require_approval', False)}`"
        )
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.post(url, json={
                    "chat_id": int(chat_id) if chat_id.isdigit() else chat_id,
                    "text": text, "parse_mode": "Markdown"
                })
            notified["telegram"] = r.status_code == 200
        except Exception:
            notified["telegram"] = False

    return {"ok": True, "accepted": True, "notified": notified}

































