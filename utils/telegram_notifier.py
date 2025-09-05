# utils/telegram_notifier.py
import os, httpx, json
from pathlib import Path
from typing import Optional
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from utils.analytics_logger import log_event

TEMPLATE_PATH = Path("static/telegram_ui_templates.json")
TEMPLATES = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8")) if TEMPLATE_PATH.exists() else {}

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
PUBLIC_FEED_CHANNEL_ID = os.getenv("PUBLIC_FEED_CHANNEL_ID")
ENABLE_PUBLIC_FEED = str(os.getenv("ENABLE_PUBLIC_FEED", "0")).lower() in ("1", "true", "yes", "on")

TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def _template(key: str, **kwargs) -> str:
    return TEMPLATES.get(key, "").format(**kwargs)

def _send(text: str, chat_id: Optional[str] = None, reply_markup: Optional[dict] = None):
    if not BOT_TOKEN or not chat_id:
        return
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        httpx.post(f"{TG_BASE}/sendMessage", json=payload, timeout=4.0)
    except Exception as e:
        log_event("telegram_send_failed", {"error": str(e), "chat_id": chat_id})

def notify_trade_card(symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float, tp3: float, lev: int, rr: float, interval: str, trade_id: str):
    key = "trade_card_long" if side.upper() == "LONG" else "trade_card_short"
    text = _template(key, symbol=symbol, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, lev=lev, rr=rr, interval=interval, trade_id=trade_id)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ אשר", callback_data=f"approve:{trade_id}"),
        InlineKeyboardButton("❌ דחה", callback_data=f"reject:{trade_id}")
    ]])

    _send(text, ADMIN_CHAT_ID, reply_markup=keyboard.to_dict())
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)

def notify_tp_hit(symbol: str, price: float, tp_level: int):
    text = _template("tp_hit", symbol=symbol.upper(), price=price, tpn=tp_level)
    _send(text, ADMIN_CHAT_ID)
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)
    log_event("tp_hit", {"symbol": symbol, "price": price, "tp_level": tp_level})

def notify_sl_hit(symbol: str, price: float):
    text = _template("sl_hit", symbol=symbol.upper(), price=price)
    _send(text, ADMIN_CHAT_ID)
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)
    log_event("sl_hit", {"symbol": symbol, "price": price})

def notify_be_moved(symbol: str, old_sl: float, new_sl: float):
    text = _template("breakeven_move", symbol=symbol.upper(), old_sl=old_sl, new_sl=new_sl)
    _send(text, ADMIN_CHAT_ID)
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)
    log_event("be_moved", {"symbol": symbol, "old_sl": old_sl, "new_sl": new_sl})

async def handle_callback_action(update) -> dict:
    try:
        query = update.callback_query
        if not query or not query.data:
            return {"ok": False, "error": "empty callback"}

        action, trade_id = query.data.split(":", 1)
        symbol = trade_id.split("_")[0]  # לדוגמה אם trade_id=BTCUSDT_123

        if action == "approve":
            text = _template("approved", symbol=symbol, reason="אושר")
            _send(text, ADMIN_CHAT_ID)
            log_event("trade_approved", {"trade_id": trade_id, "symbol": symbol, "user": query.from_user.id})
        elif action == "reject":
            text = _template("rejected", symbol=symbol, reason="נדחה")
            _send(text, ADMIN_CHAT_ID)
            log_event("trade_rejected", {"trade_id": trade_id, "symbol": symbol, "user": query.from_user.id})
        else:
            return {"ok": False, "error": f"unknown action {action}"}

        return {"ok": True, "action": action, "trade_id": trade_id}
    except Exception as e:
        log_event("callback_error", {"error": str(e)})
        return {"ok": False, "error": str(e)}


