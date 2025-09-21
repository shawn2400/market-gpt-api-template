# routes/ops_ticket.py
from __future__ import annotations
import os, json, time, hmac, hashlib, httpx, secrets
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import JSONResponse

# Redis (async)
try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None  # type: ignore

router = APIRouter(prefix="/ops", tags=["Ops"])

# --- ENV ---
REDIS_URL   = os.getenv("REDIS_URL", "")
NS          = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
KEY_TICKET  = lambda tid: f"{NS}:ticket:{tid}"
TICKET_TTL  = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))  # ברירת מחדל 30 דקות

PUBLIC_HOST = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ADMIN_ONLY  = (os.getenv("TELEGRAM_ADMIN_ONLY", "1").lower() in ("1","true","yes","on"))
ADMIN_IDS   = [x.strip() for x in (os.getenv("TELEGRAM_ADMIN_IDS","").split(",")) if x.strip()]

WEBHOOK_HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

# --- helpers ---
async def _redis():
    if not aioredis:
        raise HTTPException(status_code=500, detail="redis.asyncio not available")
    if not REDIS_URL:
        raise HTTPException(status_code=500, detail="REDIS_URL not set")
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

def _now() -> float: return time.time()

def _require(cond: bool, msg: str):
    if not cond: raise HTTPException(status_code=400, detail=msg)

def _build_inline_keyboard(approve_url: str, reject_url: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "url": approve_url},
                {"text": "❌ Reject",  "url": reject_url},
            ]
        ]
    }

async def _send_telegram_message(text: str, approve_url: str, reject_url: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not set")
    chat_id = CHAT_ID or (ADMIN_IDS[0] if ADMIN_IDS else "")
    if not chat_id:
        raise HTTPException(status_code=500, detail="TELEGRAM_CHAT_ID/ADMIN_IDS not set")

    kb = _build_inline_keyboard(approve_url, reject_url)
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(api, data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "reply_markup": json.dumps(kb),
        })
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "raw": r.text}
        if not j.get("ok"):
            raise HTTPException(status_code=502, detail=f"telegram sendMessage failed: {j}")
        return j

# --- Schemas (פשוטים ללא Pydantic מלא כדי לא לתלות תלויות) ---
def _coerce_float(x: Any, name: str) -> float:
    try:
        return float(x)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid {name}")

def _sanitize_side(x: str) -> str:
    x = (x or "").strip().upper()
    _require(x in ("BUY","SELL","LONG","SHORT"), "side must be BUY/SELL or LONG/SHORT")
    return "BUY" if x in ("BUY","LONG") else "SELL"

# ---------- API ----------
@router.get("/ticket/{ticket_id}", summary="Get ticket status (Redis)")
async def ticket_status(ticket_id: str):
    r = await _redis()
    raw = await r.get(KEY_TICKET(ticket_id))
    if raw:
        try: data = json.loads(raw)
        except Exception: data = {"raw": raw}
        return JSONResponse({"ok": True, "ticket": data})
    h = await r.hgetall(KEY_TICKET(ticket_id))
    if h:
        return JSONResponse({"ok": True, "ticket": h})
    raise HTTPException(status_code=404, detail="Ticket not found")

@router.post("/ticket", summary="Create approval ticket and send Telegram", description="LIVE")
async def create_ticket(payload: Dict[str, Any] = Body(...)):
    """
    payload example:
    {
      "ticket_id":"T_123",       # optional; if missing will be generated
      "symbol":"BTCUSDT",
      "side":"BUY",
      "qty":0.001,
      "lev":10,
      "budget":10,
      "note":"optional",
      "position_side":"BOTH"     # optional (default BOTH)
    }
    """
    _require(PUBLIC_HOST, "PUBLIC_HOST/WEBHOOK_HOST must be set (https://... without trailing slash)")

    ticket_id = (payload.get("ticket_id") or f"T_{secrets.token_hex(4)}").strip()
    symbol    = (payload.get("symbol") or "").strip().upper()
    side      = _sanitize_side(payload.get("side",""))
    qty       = _coerce_float(payload.get("qty"), "qty")
    lev       = int(_coerce_float(payload.get("lev"), "lev"))
    budget    = _coerce_float(payload.get("budget"), "budget")
    position_side = (payload.get("position_side") or "BOTH").strip().upper()
    note      = (payload.get("note") or "").strip()

    _require(symbol and qty > 0 and lev > 0 and budget > 0, "missing/invalid fields")

    # נשמור ב-Redis
    r = await _redis()
    rec = {
        "ts": _now(),
        "ticket_id": ticket_id,
        "req": {
            "action": "approve",
            "ticket_id": ticket_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": None,
            "lev": lev,
            "position_side": position_side,
            "budget": budget,
            "note": note,
        }
    }
    await r.set(KEY_TICKET(ticket_id), json.dumps(rec), ex=TICKET_TTL)

    # לינקים (מאובטחים ע"י HMAC בהמשך ב-ops_approval)
    approve_url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve?id={ticket_id}"
    reject_url  = f"{PUBLIC_HOST.rstrip('/')}/ops/reject?id={ticket_id}"

    # הודעת טלגרם
    txt = (
        f"⚠️ <b>Approval Needed</b>\n"
        f"• Ticket: <code>{ticket_id}</code>\n"
        f"• {symbol} {side} qty={qty} lev={lev} budget={budget}\n"
        + (f"• Note: {note}\n" if note else "")
        + "— — —\nבחר:"
    )
    tg = await _send_telegram_message(txt, approve_url, reject_url)
    return JSONResponse({"ok": True, "ticket_id": ticket_id, "telegram": tg})


