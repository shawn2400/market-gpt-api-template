# routes/alerts.py
import binascii, hashlib, hmac, os, json, logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger("algogpt.alerts")
router = APIRouter(prefix="/alerts", tags=["alerts"])

# ---------- HMAC ----------
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

# ---------- Ticket store / executor ----------
try:
    # אם קיים executor פנימי, נעדיף אותו
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    # fallback שמוגדר ב-main
    from main import ConfirmStore  # type: ignore

def _coerce_bool(v, default=False) -> bool:
    if isinstance(v, bool): return v
    s = str(v).strip().lower()
    if s in ("1","true","yes","on"): return True
    if s in ("0","false","no","off"): return False
    return bool(default)

def _mk_ticket(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol":   str(payload.get("symbol","")).upper(),
        "market":   str(payload.get("market","futures")).lower(),
        "side":     str(payload.get("side","")).upper(),         # BUY/SELL
        "qty":      float(payload.get("qty", 0)),
        "leverage": int(payload.get("leverage", 1)),
        "score":    float(payload.get("score", 0)),
        "reason":   str(payload.get("reason", "")),
        "require_approval": _coerce_bool(payload.get("require_approval", True)),
    }

# ביצוע אמיתי ב-Binance Futures (MARKET). אם יש wrapper פנימי – נשתמש בו; אחרת נשתמש ב-python-binance.
async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # נסה wrapper פנימי אם קיים
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)  # חותם חוזר: {"ok": True/False, ...}
    except Exception:
        pass

    # נפעיל ישירות את python-binance
    try:
        from binance.client import Client
    except Exception as e:
        logger.error("binance import failed: %s", e)
        return {"ok": False, "error": "binance_client_import_failed", "detail": str(e)}

    try:
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not api_key or not api_sec:
            return {"ok": False, "error": "binance_keys_missing"}

        client = Client(api_key, api_sec)
        symbol   = ticket["symbol"]
        side     = ticket["side"]                # BUY / SELL
        qty      = float(ticket["qty"])
        leverage = int(ticket.get("leverage", 1))

        # עדכון מינוף (שקט אם נכשל)
        try:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("futures_change_leverage failed: %s", e)

        # הזמנה בשוק (MARKET). במצב hedge, הצד נקבע לפי side בלבד.
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty,
            newClientOrderId=f"ALG_{symbol}_{side}"
        )
        return {"ok": True, "exchange": "binance_futures", "order": order}
    except Exception as e:
        logger.error("futures_create_order failed: %s", e)
        return {"ok": False, "error": "order_failed", "detail": str(e)}

# ---------- Telegram ----------
async def _notify_telegram(payload: Dict[str, Any], ticket_id: Optional[str], executed: Optional[Dict[str, Any]] = None) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return False

    public_host = (os.getenv("PUBLIC_HOST","") or os.getenv("WEBHOOK_HOST","")).rstrip("/")
    approve_url = reject_url = ""
    if ticket_id and public_host:
        approve_url = f"{public_host}/ops/approve?ticket_id={ticket_id}"
        reject_url  = f"{public_host}/ops/reject?ticket_id={ticket_id}"

    lines = [
        "📈 *New Trade Signal*",
        f"• Symbol: `{payload.get('symbol','?')}`",
        f"• Market: `{payload.get('market','?')}`",
        f"• Side: `{payload.get('side','?')}`",
        f"• Qty: `{payload.get('qty','?')}`  Lev: `{payload.get('leverage','?')}`",
        f"• Score: `{payload.get('score','?')}`",
        f"• Reason: {payload.get('reason','')}",
        f"• Require Approval: `{payload.get('require_approval', True)}`",
    ]
    if ticket_id:
        lines += [f"• Ticket: `{ticket_id}`"]
        if approve_url and reject_url:
            lines += [f"✅ {approve_url}", f"❌ {reject_url}"]
    if executed is not None:
        lines += [f"• Executed: `{executed.get('ok')}`"]

    text = "\n".join(lines)
    url  = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, json={
                "chat_id": int(chat_id) if chat_id.isdigit() else chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
        return r.status_code == 200
    except Exception as e:
        logger.warning("telegram notify failed: %s", e)
        return False

# ---------- Routes ----------
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
    # אימות HMAC
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

    ticket = _mk_ticket(payload)
    if not ticket["symbol"] or not ticket["side"] or ticket["qty"] <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad_ticket_params"})

    # צור טיקט אישור
    ticket_id = ConfirmStore.create(ticket)
    executed_result: Optional[Dict[str, Any]] = None

    # אם לא נדרש אישור — בצע מיד
    if not ticket["require_approval"]:
        executed_result = await _execute_trade(ticket)

    # נוטיפיקציה לטלגרם
    notified = await _notify_telegram({**ticket}, ticket_id=ticket_id, executed=executed_result)

    resp: Dict[str, Any] = {"ok": True, "accepted": True, "ticket_id": ticket_id, "notified": {"telegram": notified}}
    if executed_result is not None:
        resp["executed"] = executed_result
    return resp

































