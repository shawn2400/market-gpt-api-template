# routes/alerts.py
import binascii, hashlib, hmac, os, json, asyncio
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])

# ---------- HMAC helpers ----------
def _get_secret_bytes() -> Optional[bytes]:
    # עדיפות למפתח ייעודי של alerts; אחרת fallback ל-WEBHOOK_HMAC_SECRET
    secret = os.getenv("ALERTS_INGEST_HMAC_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
    if not secret:
        return None
    if os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0").lower() in ("1", "true", "yes", "on"):
        try:
            return binascii.unhexlify(secret.strip())
        except Exception:
            return None
    return secret.encode()

def _server_hexdigest(raw: bytes) -> Optional[str]:
    key = _get_secret_bytes()
    if not key:
        return None
    return hmac.new(key, raw, hashlib.sha256).hexdigest()

def _client_hexdigest_from_headers(request: Request) -> Optional[str]:
    # תומך בשני הפורמטים:
    # X-Webhook-Hmac: <hex>
    # X-Hub-Signature-256: sha256=<hex>
    hv = request.headers.get("x-webhook-hmac") or request.headers.get("X-Webhook-Hmac")
    if not hv:
        hv = request.headers.get("x-hub-signature-256") or request.headers.get("X-Hub-Signature-256")
        if hv and hv.startswith("sha256="):
            hv = hv.split("=", 1)[1]
    if not hv:
        return None
    hv = hv.strip().lower()
    return hv if len(hv) == 64 else None

# ---------- Notifiers ----------
async def _notify_telegram(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(api, json=payload)
            return bool(r.status_code == 200 and r.json().get("ok"))
    except Exception:
        return False

def _fmt_alert_msg(p: Dict[str, Any]) -> str:
    # שדות אופייניים; מתחשב בחסרים
    sym   = str(p.get("symbol", "")).upper()
    mkt   = str(p.get("market", "futures"))
    side  = str(p.get("side", "")).upper()
    score = p.get("score")
    reason= p.get("reason", "")
    qty   = p.get("qty")
    lev   = p.get("leverage")
    need  = bool(p.get("require_approval"))
    parts = [f"🟢 <b>Trade Alert</b>"]
    if sym: parts.append(f"• Symbol: <b>{sym}</b>")
    parts.append(f"• Market: {mkt}")
    if side: parts.append(f"• Side: <b>{side}</b>")
    if qty is not None: parts.append(f"• Qty: {qty}")
    if lev is not None: parts.append(f"• Leverage: x{lev}")
    if score is not None: parts.append(f"• Score: {score}")
    if reason: parts.append(f"• Reason: {reason}")
    parts.append(f"• Require approval: {'YES' if need else 'NO'}")
    return "\n".join(parts)

# ---------- Routes ----------
@router.get("/ping")
async def ping():
    return {"ok": True, "service": "alerts"}

@router.post("/_debug/alerts-hmac-check")
async def debug_hmac_check(request: Request):
    raw = await request.body()
    calc = _server_hexdigest(raw)
    return {"ok": bool(calc), "server_hex": calc, "body_len": len(raw)}

@router.post("/ingest")
async def ingest(request: Request):
    # אימות HMAC על הגוף הגולמי בדיוק כמו שיגיע
    raw = await request.body()
    server_hex = _server_hexdigest(raw)
    if not server_hex:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured"})

    client_hex = _client_hexdigest_from_headers(request)
    if not client_hex or client_hex != server_hex:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid HMAC signature"})

    # פרסינג JSON
    try:
        payload = json.loads(raw.decode("utf-8"))
        assert isinstance(payload, dict)
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_json"})

    # ולידציה בסיסית לשדות עיקריים
    symbol = str(payload.get("symbol", "")).upper()
    side   = str(payload.get("side", "")).upper()
    if not symbol or side not in ("BUY", "SELL", "LONG", "SHORT"):
        return JSONResponse(status_code=422, content={"ok": False, "error": "invalid_fields"})

    # נוטיפיקציה לטלגרם (אם מוגדר)
    msg = _fmt_alert_msg(payload)
    tg_ok = await _notify_telegram(msg)

    # כאן אפשר לשרשר לוגיקה עסקית (אישור/פתיחה/שמירה) בעתיד
    return {"ok": True, "accepted": True, "notified": {"telegram": tg_ok}}
































