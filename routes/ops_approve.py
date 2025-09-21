# routes/ops_approve.py
from __future__ import annotations
import os, json, time, hmac, hashlib
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import HTMLResponse

# Redis (async)
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

# ------------------ Router ------------------
router = APIRouter(tags=["ops-approval"])

# ------------------ Config ------------------
NS            = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL     = os.getenv("REDIS_URL", "")
KEY_TICKET    = lambda tid: f"{NS}:ticket:{tid}"
TICKET_TTL    = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))  # 30 דקות
PUBLIC_HOST   = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET   = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

# Telegram (אופציונלי)
BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_ENV   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ADMIN_IDS_ENV = os.getenv("TELEGRAM_ADMIN_IDS", "").strip()

# ------------------ Utils ------------------
def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto'>"
        f"<h2>{msg}</h2></body>"
    )

async def _redis():
    """יוצר לקוח Redis אסינכרוני."""
    if not aioredis:
        raise HTTPException(status_code=500, detail="redis.asyncio not available")
    if not REDIS_URL:
        raise HTTPException(status_code=500, detail="REDIS_URL not set")
    return aioredis.from_url(REDIS_URL, decode_responses=True)

def _expired(ts: float, ttl_sec: int = 60 * 15) -> bool:
    try:
        return (time.time() - float(ts)) > ttl_sec
    except Exception:
        return True

def _sign_hex(secret_hex: str, payload: bytes) -> str:
    """מחשב HMAC-SHA256 כ־HEX. secret יכול להיות hex באורך 64 או מחרוזת רגילה."""
    key = bytes.fromhex(secret_hex) if len(secret_hex) == 64 else secret_hex.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def _require(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

def _kb(approve_url: str, reject_url: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "url": approve_url},
            {"text": "❌ Reject",  "url": reject_url},
        ]]
    }

def _resolve_chat_id() -> Optional[str]:
    if CHAT_ID_ENV:
        return CHAT_ID_ENV
    if ADMIN_IDS_ENV:
        parts = [x.strip() for x in ADMIN_IDS_ENV.split(",") if x.strip()]
        if parts:
            return parts[0]
    return None

# ------------------ Core actions ------------------
async def _load_ticket(ticket_id: str) -> Dict[str, Any]:
    r = await _redis()
    raw = await r.get(KEY_TICKET(ticket_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Invalid or expired approval id")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted ticket payload")
    return data

async def _execute_via_signed_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
    """מבצע בפועל דרך /ops/approve/signed עם חתימת HMAC זהה לקליינט."""
    if not PUBLIC_HOST:
        raise HTTPException(status_code=500, detail="PUBLIC_HOST not set")
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_HMAC_SECRET/OPS_SIGN_SECRET not set")

    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    sig = _sign_hex(HMAC_SECRET, raw)
    url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve/signed"
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(url, content=raw,
                           headers={"Content-Type": "application/json", "X-Signature": sig})
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "status": r.status_code, "text": r.text}
        if r.status_code >= 400 or not j.get("ok"):
            raise HTTPException(status_code=502, detail=f"approve/signed failed: {j}")
        return j

async def _send_tg_message(text: str, approve_url: str, reject_url: str) -> Optional[dict]:
    """שולח הודעת טלגרם עם כפתורי אישור/דחייה (אם הוגדרו פרטי בוט)."""
    if not BOT_TOKEN:
        return None
    chat_id = _resolve_chat_id()
    if not chat_id:
        return None
    kb = _kb(approve_url, reject_url)
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
                "reply_markup": json.dumps(kb),
            },
        )
        try:
            j = r.json()
        except Exception:
            j = {"ok": False, "raw": r.text}
        if not j.get("ok"):
            # לא מפיל את הראוט—פשוט מדווח כשליחה נכשלה
            return {"ok": False, "error": j}
        return j

# ------------------ Routes ------------------

@router.post("/ops/ticket", summary="Create LIVE approval ticket and (optionally) send Telegram")
async def create_ticket(payload: Dict[str, Any] = Body(...)):
    """
    יוצר טיקט ב־Redis ושולח הודעת טלגרם עם כפתורי אישור/דחייה (אם מוגדר בוט).
    גוף לדוגמה:
    {
      "ticket_id": "T_ABC" (אופציונלי),
      "symbol": "BTCUSDT", "side": "BUY|SELL|LONG|SHORT",
      "qty": 0.001, "lev": 10, "budget": 10,
      "position_side": "BOTH" (אופציונלי, ברירת מחדל BOTH),
      "note": "live demo" (אופציונלי)
    }
    """
    import secrets
    _require(PUBLIC_HOST, "PUBLIC_HOST/WEBHOOK_HOST must be set")

    ticket_id = (payload.get("ticket_id") or f"T_{secrets.token_hex(4)}").strip()
    symbol    = (payload.get("symbol") or "").strip().upper()
    side_in   = (payload.get("side") or "").strip().upper()
    qty       = float(payload.get("qty") or 0)
    lev       = int(float(payload.get("lev") or 0))
    budget    = float(payload.get("budget") or 0)
    position_side = (payload.get("position_side") or "BOTH").strip().upper()
    note      = (payload.get("note") or "").strip()

    _require(symbol and side_in in ("BUY","SELL","LONG","SHORT") and qty > 0 and lev > 0 and budget > 0,
             "invalid fields")
    side = "BUY" if side_in in ("BUY", "LONG") else "SELL"

    rec = {
        "ts": time.time(),
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
        },
    }

    r = await _redis()
    await r.set(KEY_TICKET(ticket_id), json.dumps(rec), ex=TICKET_TTL)

    approve_url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve?id={ticket_id}"
    reject_url  = f"{PUBLIC_HOST.rstrip('/')}/ops/reject?id={ticket_id}"
    txt_lines = [
        "⚠️ <b>Approval Needed</b>",
        f"• Ticket: <code>{ticket_id}</code>",
        f"• {symbol} {side} qty={qty} lev={lev} budget={budget}",
    ]
    if note:
        txt_lines.append(f"• Note: {note}")
    txt_lines.append("— — —")
    txt_lines.append("בחר:")
    tg_res = await _send_tg_message("\n".join(txt_lines), approve_url, reject_url)

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "telegram": tg_res or {"ok": False, "sent": False},
    }

@router.get("/ops/ticket/{ticket_id}", summary="Get ticket status")
async def ticket_status(ticket_id: str):
    r = await _redis()
    raw = await r.get(KEY_TICKET(ticket_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Ticket not found")
    try:
        data = json.loads(raw)
    except Exception:
        data = {"raw": raw}
    return {"ok": True, "ticket": data}

@router.get("/ops/approve")
async def approve(id: str = Query(..., description="ticket_id")):
    rec = await _load_ticket(id)
    if _expired(rec.get("ts", 0), ttl_sec=TICKET_TTL):
        try:
            r = await _redis()
            await r.delete(KEY_TICKET(id))
        except Exception:
            pass
        raise HTTPException(status_code=410, detail="Approval link expired")

    req = rec.get("req") or {}
    # ביצוע אמיתי דרך ה-endpoint החתום שכבר תקין אצלך
    await _execute_via_signed_endpoint(req)

    # מחיקת הטיקט אחרי ביצוע
    try:
        r = await _redis()
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass
    return _html("✅ Approved! Order executed on Binance Futures.")

@router.get("/ops/reject")
async def reject(id: str = Query(..., description="ticket_id")):
    try:
        r = await _redis()
        await r.delete(KEY_TICKET(id))
    except Exception:
        pass
    return _html("❌ Rejected. Order cancelled.")










