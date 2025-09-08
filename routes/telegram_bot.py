# routes/telegram_bot.py — גרסה מלאה עם test-ping, webhook, אישור טריידים, mute וכו'

from __future__ import annotations
import logging, os, json, time
from typing import Dict, Any, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
from telegram import Update

from utils.auth import require_api_key
from utils.runtime_prefs import is_muted, set_mute, toggle_mute
from utils.telegram_notifier import handle_callback_action
from utils.security import verify_hmac, idem_seen
from utils.risk import suggest_risk
from utils.binance_client import (
    place_tp_ladder, set_breakeven_stop,
    futures_create_order, set_leverage,
    futures_mark_price, get_symbol_filters, modify_stop_loss,
)

logger = logging.getLogger("algogpt.routes.telegram")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

APP_VERSION = os.getenv("ALGOGPT_VERSION", "unknown")

class MuteRequest(BaseModel):
    state: bool

_TP_LADDER_COOLDOWN = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))
_TP_LADDER_ON_APPROVE = os.getenv("TP_LADDER_ON_APPROVE", "1").lower() in ("1", "true", "yes", "on")
_AUTO_OPEN_ON_APPROVE = os.getenv("AUTO_OPEN_ON_APPROVE", "1").lower() in ("1", "true", "yes", "on")
_HMAC_ENABLED = bool(os.getenv("WEBHOOK_HMAC_SECRET", "").strip())
_X_SIG_HDRS = ("x-algogpt-signature", "X-Algogpt-Signature", "X-Hub-Signature-256")
_X_IDEM = "X-Idempotency-Key"
_LADDER_LAST: Dict[str, float] = {}

def _require_secret(req: Request) -> None:
    wanted = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    got = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not wanted or got != wanted:
        raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

def _verify_optional_hmac(req: Request, body: bytes) -> bool:
    if not _HMAC_ENABLED:
        return True
    for h in _X_SIG_HDRS:
        if h in req.headers:
            sig_hex = req.headers[h].split("=", 1)[-1]
            return verify_hmac(sig_hex, body)
    return True

def _cooldown_ok(symbol: str) -> bool:
    now = time.time()
    if now - _LADDER_LAST.get(symbol, 0.0) >= _TP_LADDER_COOLDOWN:
        _LADDER_LAST[symbol] = now
        return True
    return False

def _side_to_exchange(side: str) -> Tuple[str, str]:
    s = (side or "").upper()
    if s in ("LONG", "BUY"): return "BUY", "LONG"
    if s in ("SHORT", "SELL"): return "SELL", "SHORT"
    return "BUY", "LONG"

def _quantize_qty(symbol: str, price: float, qty_guess: float) -> float:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or 0.001)
    min_notional = float(f.get("minNotional") or 5.0)
    qty = max(qty_guess, min_notional / max(price, 1e-12))
    steps = int(qty / step)
    return max(step, steps * step)

def _open_after_approve(symbol: str, side: str, entry_hint=None, sl_price=None, leverage_hint=None, budget_usd_hint=None):
    su = symbol.upper()
    ex_side, pos_side = _side_to_exchange(side)
    price = futures_mark_price(su) or float(entry_hint or 0.0) or 0.0
    try:
        r = suggest_risk(su, price, sl=float(sl_price or 0.0), budget_usd=budget_usd_hint, leverage=leverage_hint)
        leverage = int(r.get("leverage") or leverage_hint or 10)
        budget_usd = float(r.get("budget_usd") or budget_usd_hint or 50.0)
        qty_risk = float(r.get("quantity") or 0.0)
    except Exception:
        leverage = int(leverage_hint or 10)
        budget_usd = float(budget_usd_hint or 50.0)
        qty_risk = (budget_usd * leverage) / max(price or 1.0, 1e-12)
    qty = _quantize_qty(su, price or 1.0, qty_risk)
    lev_resp = set_leverage(su, leverage)
    order = futures_create_order(symbol=su, side=ex_side, type="MARKET", quantity=str(qty))
    sl_resp = modify_stop_loss(su, float(sl_price), position_side=pos_side) if sl_price and sl_price > 0 else None
    return {"leverage_set": lev_resp, "market_order": order, "stop_loss": sl_resp, "qty": qty, "price_ref": price, "pos_side": pos_side}

async def _send_tg(chat_id: int, text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, data={"chat_id": chat_id, "text": text})
    except Exception:
        logger.exception("failed sending telegram message")

def _normalize_cmd(txt: str) -> str:
    t = (txt or "").strip()
    if not t.startswith("/"): return t
    return t.split()[0].split("@", 1)[0].lower()

def _parse_update_safe(payload: Dict[str, Any]) -> Dict[str, Any]:
    chat_id = None; text = None; is_callback = False; update_obj = None
    try:
        update_obj = Update.de_json(payload, None)
        if update_obj and update_obj.message:
            chat_id = update_obj.message.chat.id
            text = (update_obj.message.text or "").strip()
        elif update_obj and update_obj.callback_query:
            is_callback = True
            chat_id = update_obj.callback_query.message.chat.id
            text = (update_obj.callback_query.data or "").strip()
        if chat_id:
            return {"chat_id": chat_id, "text": text, "is_callback": is_callback, "update_obj": update_obj}
    except Exception:
        pass
    msg = payload.get("message") or {}
    cbq = payload.get("callback_query") or {}
    if msg:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        is_callback = False
    elif cbq:
        text = (cbq.get("data") or "").strip()
        chat = cbq.get("message", {}).get("chat") or {}
        chat_id = chat.get("id")
        is_callback = True
    return {"chat_id": chat_id, "text": text or "", "is_callback": is_callback, "update_obj": update_obj}

@router.get("/status")
async def get_mute(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": is_muted()}

@router.post("/mute")
async def set_mute_state(req: MuteRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    set_mute(req.state)
    return {"ok": True, "mute": req.state}

@router.post("/toggle")
async def toggle_mute_state(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": toggle_mute()}

@router.post("/set-webhook")
async def set_webhook(url: str = Query(..., min_length=8), _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not token or not secret:
        raise HTTPException(500, "Telegram bot config missing")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"], "drop_pending_updates": True}
        )
        return {"ok": True, "telegram": resp.json()}

@router.get("/test-ping")
async def test_ping(chat_id: int, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    await _send_tg(chat_id, f"pong ✅ (v{APP_VERSION}) [test]")
    return {"ok": True, "sent": True, "chat_id": chat_id, "version": APP_VERSION}

@router.post("/webhook")
async def telegram_webhook(req: Request) -> Dict[str, Any]:
    _require_secret(req)
    raw = await req.body()
    if not _verify_optional_hmac(req, raw):
        return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})
    idem = req.headers.get(_X_IDEM)
    if idem and idem_seen(f"tgcb:{idem}"):
        return JSONResponse(content={"ok": True, "duplicate": True})
    try:
        payload = json.loads(raw) if raw else {}
        parsed = _parse_update_safe(payload)
        chat_id = parsed.get("chat_id")
        raw_text = parsed.get("text", "").strip()
        cmd = _normalize_cmd(raw_text)
        logger.debug("tg webhook: chat_id=%s cb=%s text=%r cmd=%r", chat_id, parsed.get("is_callback"), raw_text, cmd)
        if chat_id and cmd in ("/ping", "ping", "/start"):
            await _send_tg(chat_id, f"pong ✅ (v{APP_VERSION})")
            return {"ok": True, "echo": "ping"}
        if chat_id and cmd == "/version":
            await _send_tg(chat_id, f"AlgoGPT v{APP_VERSION}")
            return {"ok": True, "version": APP_VERSION}
        if chat_id and cmd == "/help":
            await _send_tg(chat_id, "פקודות: /ping • /version • /help\n(Callbacks נתמכים כרגיל)")
            return {"ok": True, "help": True}
        result = await handle_callback_action(parsed["update_obj"]) if parsed["update_obj"] else None
        approved = bool(result and (result.get("approved") or str(result.get("action", "")).lower() in ("approve", "approved")))
        opened = ladder = be_res = None
        if approved:
            symbol = result.get("symbol")
            side = result.get("side", "LONG")
            if _AUTO_OPEN_ON_APPROVE and symbol and side:
                opened = _open_after_approve(symbol, side, entry_hint=result.get("entry"), sl_price=result.get("sl"), leverage_hint=result.get("leverage"), budget_usd_hint=result.get("budget_usd"))
            if _TP_LADDER_ON_APPROVE and symbol and side and _cooldown_ok(symbol):
                ladder = place_tp_ladder(symbol, position_side=side)
                if os.getenv("TP_BE_ONLY_AFTER_TP1", "0") == "0":
                    be_res = set_breakeven_stop(symbol, offset_bps=float(os.getenv("TP_BE_OFFSET_BPS", "5")))
        return {"ok": True, "approved": approved, "result": result, "opened": opened, "ladder": ladder, "be": be_res}
    except Exception as e:
        logger.exception("telegram_webhook failed")
        return {"ok": False, "error": str(e)}



























