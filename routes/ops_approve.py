# routes/ops_approve.py
from __future__ import annotations
import os, json, time, hmac, hashlib, secrets, logging
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import HTMLResponse
import httpx

logger = logging.getLogger("algogpt.ops_approve")
router = APIRouter(tags=["ops-approval"])

# -------- Optional Redis ----------
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

NS            = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL     = os.getenv("REDIS_URL", "")
PUBLIC_HOST   = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET   = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
BOT_TOKEN     = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TICKET_TTL_SEC= int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))

def KEY_TICKET(tid: str) -> str:
    return f"{NS}:ticket:{tid}"

async def _redis():
    if not (aioredis and REDIS_URL):
        raise RuntimeError("redis_unavailable")
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# -------- ConfirmStore fallback ----------
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    from main import ConfirmStore  # type: ignore

# -------- Execution: place MARKET on Binance (same as alerts) --------
async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # נסה wrapper פנימי אם קיים
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    except Exception:
        pass
    # python-binance ישיר
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
        symbol   = str(ticket.get("symbol","")).upper()
        side     = str(ticket.get("side","")).upper()
        qty      = float(ticket.get("qty", 0))
        leverage = int(ticket.get("leverage", 1))
        if not(symbol and side and qty > 0 and leverage > 0):
            return {"ok": False, "error": "bad_ticket_params"}
        try:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("futures_change_leverage failed: %s", e)
        order = client.futures_create_order(
            symbol=symbol, side=side, type="MARKET", quantity=qty,
            newClientOrderId=f"ALG_{symbol}_{side}"
        )
        return {"ok": True, "exchange": "binance_futures", "order": order}
    except Exception as e:
        logger.error("futures_create_order failed: %s", e)
        return {"ok": False, "error": "order_failed", "detail": str(e)}

# -------- Telegram --------
async def _send_telegram_html(text: str, approve_url: Optional[str] = None, reject_url: Optional[str] = None) -> Dict[str, Any]:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    payload: Dict[str, Any] = {
        "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if approve_url or reject_url:
        payload["reply_markup"] = {"inline_keyboard":[[
            {"text":"✅ Approve","url":approve_url or PUBLIC_HOST or "https://example.com"},
            {"text":"❌ Reject","url":reject_url or PUBLIC_HOST or "https://example.com"},
        ]]}
    async with httpx.AsyncClient(timeout=12.0) as cli:
        r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        try: data = r.json()
        except Exception: data = {"ok": False, "status": r.status_code, "text": r.text}
    return data

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto'>"
        f"<h2>{msg}</h2></body>"
    )

def _expired(ts: float, ttl_sec: int = TICKET_TTL_SEC) -> bool:
    try: return (time.time() - float(ts)) > ttl_sec
    except Exception: return True

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

# -------- Storage abstraction: find ticket either in Redis or ConfirmStore --------
async def _load_ticket(tid: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    מחפש קודם ב-Redis (אם קיים), אחרת ב-ConfirmStore.
    מחזיר (ticket_payload, source).
    """
    # Redis
    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            raw = await r.get(KEY_TICKET(tid))
            if raw:
                rec = json.loads(raw)
                if not _expired(rec.get("ts", 0)):  # תקף
                    return rec.get("req") or rec, "redis"
        except Exception as e:
            logger.warning("redis_load_failed: %s", e)
    # ConfirmStore
    try:
        for it in (ConfirmStore.pending() or []):
            if str(it.get("ticket_id")) == str(tid):
                return it, "confirmstore"
    except Exception as e:
        logger.warning("confirmstore_load_failed: %s", e)
    return None, "none"

async def _delete_ticket(tid: str, source: str) -> None:
    if source == "redis" and aioredis and REDIS_URL:
        try:
            r = await _redis(); await r.delete(KEY_TICKET(tid))
            return
        except Exception as e:
            logger.warning("redis_delete_failed: %s", e)
    # ConfirmStore
    try:
        ConfirmStore.decide(tid, approved=False)  # מחיקה לוגית
    except Exception:
        pass

# -------------------- API --------------------

@router.post("/ops/ticket", summary="Create approval ticket (supports Redis + ConfirmStore) – sends Telegram")
async def create_ticket(
    payload: Dict[str, Any] = Body(..., description="symbol, side, qty, leverage, optional: note, position_side, budget"),
):
    symbol = (payload.get("symbol") or "").upper().strip()
    side   = (payload.get("side") or "").upper().strip()
    qty    = float(payload.get("qty") or payload.get("quantity") or 0)
    lev    = int(payload.get("leverage") or payload.get("lev") or 0)
    note   = payload.get("note") or ""
    position_side = (payload.get("position_side") or "BOTH").upper()
    budget = float(payload.get("budget") or payload.get("budget_usd") or 0.0)

    if not (symbol and side and qty > 0 and lev > 0):
        raise HTTPException(status_code=422, detail="Missing/invalid fields (symbol/side/qty/leverage)")

    tid = payload.get("ticket_id") or f"T_{secrets.token_hex(4)}"
    req_body = {
        "ticket_id": tid, "symbol": symbol, "side": side, "qty": qty,
        "leverage": lev, "position_side": position_side, "budget": budget, "note": note
    }
    # שמירה בשני המקומות (ככל האפשר)
    try: ConfirmStore.create(dict(req_body))  # לא יכשל אם כבר קיים – ידרוס
    except Exception: pass
    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            rec = {"ts": time.time(), "req": req_body, "note": note}
            await r.setex(KEY_TICKET(tid), TICKET_TTL_SEC, json.dumps(rec, separators=(",", ":")))
        except Exception as e:
            logger.warning("redis_set_failed: %s", e)

    approve_url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve?ticket_id={tid}" if PUBLIC_HOST else ""
    reject_url  = f"{PUBLIC_HOST.rstrip('/')}/ops/reject?ticket_id={tid}"  if PUBLIC_HOST else ""

    pretty = (
        "⚠️ <b>Approval Needed</b>\n"
        f"• Ticket: <code>{tid}</code>\n"
        f"• {symbol} {side} qty={qty} lev={lev}\n"
        f"• Note: {note}\n— — —\nבחר:"
    )
    tg_resp = await _send_telegram_html(pretty, approve_url=approve_url or None, reject_url=reject_url or None)
    return {"ok": True, "ticket_id": tid, "approve_url": approve_url, "reject_url": reject_url, "telegram_result": tg_resp}

@router.get("/ops/approve", summary="Approve ticket (supports ticket_id) -> executes trade")
async def approve(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Invalid or expired ticket")
    # ביצוע בפועל
    exec_res = await _execute_trade(ticket)
    # הודעת טלגרם
    try:
        sym, side, qty = ticket.get("symbol",""), ticket.get("side",""), ticket.get("qty","")
        await _send_telegram_html(
            f"✅ <b>Approved</b>\n"
            f"• Ticket: <code>{ticket_id}</code>\n"
            f"• {sym} {side} qty={qty}\n"
            f"— — —\n<code>{json.dumps(exec_res, ensure_ascii=False)}</code>"
        )
    except Exception: pass
    # סגירת הטיקט
    try: ConfirmStore.decide(ticket_id, approved=True)
    except Exception: pass
    await _delete_ticket(ticket_id, source)
    return _html("✅ Approved! Order executed.")

# תאימות לאחור: /ops/approve-link?id=...
@router.get("/ops/approve-link", summary="Approve legacy link (?id=...)")
async def approve_link(id: str = Query(..., description="ticket_id")):
    return await approve(ticket_id=id)

@router.get("/ops/reject", summary="Reject ticket (delete) – supports ticket_id")
async def reject(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    await _delete_ticket(ticket_id, source)
    try:
        await _send_telegram_html(
            f"❌ <b>Rejected</b>\n• Ticket: <code>{ticket_id}</code>\n— — —\nNo action was taken."
        )
    except Exception: pass
    try: ConfirmStore.decide(ticket_id, approved=False)
    except Exception: pass
    return _html("❌ Rejected. Order cancelled.")

# -------- Signed execution endpoint (נשאר כפי שהוא) --------
@router.post("/ops/approve/signed", summary="Internal signed approve endpoint (executes trade)")
async def approve_signed(request: Request):
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="HMAC secret not set")
    raw = await request.body()
    got = request.headers.get("X-Signature", "") or ""
    want = _sign_hex(HMAC_SECRET, raw)
    if not hmac.compare_digest(got, want):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    exec_res = await _execute_trade(payload)
    ok = bool(exec_res.get("ok"))
    if not ok:
        raise HTTPException(status_code=502, detail={"execute_error": exec_res})
    return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "internal_execute": exec_res}










