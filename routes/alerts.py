# routes/alerts.py
import binascii, hashlib, hmac, os, json
from typing import Optional, Dict, Any
import httpx

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])

def _get_secret_bytes() -> Optional[bytes]:
    # קודם עדיפות למפתח הייעודי של alerts, ואז fallback ל-WEBHOOK_HMAC_SECRET
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

# -------- Telegram wiring --------
TELEGRAM_ALERTS_ENABLE = os.getenv("TELEGRAM_ALERTS_ENABLE", "1").lower() in ("1", "true", "yes", "on")
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

async def _tg_send(text: str) -> Dict[str, Any]:
    if not (TELEGRAM_ALERTS_ENABLE and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return {"ok": False, "skipped": True, "reason": "telegram_not_configured"}
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(api, json=payload)
        ok = (r.status_code == 200) and bool(r.json().get("ok"))
        return {"ok": ok, "status": r.status_code, "resp": r.text[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _fmt_trade_msg(d: Dict[str, Any]) -> str:
    sym = str(d.get("symbol", "?")).upper()
    mkt = str(d.get("market", "?"))
    side = str(d.get("side", "?")).upper()
    score = d.get("score", "")
    reason = d.get("reason", "")
    need = d.get("require_approval", False)

    extra = []
    for k in ("entry", "sl", "tp", "rr", "qty", "leverage"):
        if k in d and d[k] not in (None, ""):
            extra.append(f"{k}={d[k]}")
    extra_txt = ("\n" + "\n".join(extra)) if extra else ""
    need_txt = "✅ אישור נדרש" if need else "✅ ללא צורך באישור"

    return (
        f"🚨 <b>התראת טרייד</b>\n"
        f"Symbol: <b>{sym}</b>\n"
        f"Market: {mkt}\n"
        f"Side: <b>{side}</b>\n"
        f"Score: {score}\n"
        f"Reason: {reason}\n"
        f"{need_txt}{extra_txt}"
    )

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
    raw = await request.body()
    server_hex = _server_hexdigest(raw)
    if not server_hex:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_hmac_misconfigured"})

    client_hex = _client_hexdigest_from_headers(request)
    if not client_hex or client_hex != server_hex:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid HMAC signature"})

    # parse + notify Telegram
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    msg = _fmt_trade_msg(data)
    tg = await _tg_send(msg)

    return {"ok": True, "accepted": True, "telegram": tg}































