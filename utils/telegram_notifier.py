# utils/telegram_notifier.py
# תפקיד: שליחה בפועל ל־Telegram (כולל public feed אם מופעל)
# כולל טעינת תבניות מ־static/telegram_ui_templates.json + inline buttons

import os
import httpx
import json
from pathlib import Path
from typing import Optional, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

TEMPLATE_PATH = Path("static/telegram_ui_templates.json")
TEMPLATES = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8")) if TEMPLATE_PATH.exists() else {}

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
PUBLIC_FEED_CHANNEL_ID = os.getenv("PUBLIC_FEED_CHANNEL_ID")
ENABLE_PUBLIC_FEED = str(os.getenv("ENABLE_PUBLIC_FEED", "0")).lower() in ("1", "true", "yes", "on")

TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _template(key: str, **kwargs) -> str:
    return TEMPLATES.get(key, "").format(**kwargs)


def _send(text: str, chat_id: Optional[str] = None, reply_markup: Optional[Any] = None):
    if not BOT_TOKEN or not chat_id:
        return
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        httpx.post(f"{TG_BASE}/sendMessage", json=payload, timeout=4.0)
    except Exception:
        pass


# ========== Notifications ==========

def notify_tp_hit(symbol: str, price: float, tp_level: int):
    text = _template("tp_hit", symbol=symbol.upper(), price=price, tpn=tp_level)
    _send(text, ADMIN_CHAT_ID)
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)


def notify_sl_hit(symbol: str, price: float):
    text = _template("sl_hit", symbol=symbol.upper(), price=price)
    _send(text, ADMIN_CHAT_ID)
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)


def notify_be_moved(symbol: str, old_sl: float, new_sl: float):
    text = _template("breakeven_move", symbol=symbol.upper(), old_sl=old_sl, new_sl=new_sl)
    _send(text, ADMIN_CHAT_ID)
    if ENABLE_PUBLIC_FEED and PUBLIC_FEED_CHANNEL_ID:
        _send(text, PUBLIC_FEED_CHANNEL_ID)


# ========== Trade Card + Inline Buttons ==========

def send_trade_card(symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float, tp3: float,
                     lev: int, rr: float, interval: str, trade_id: str):
    key = "trade_card_long" if side.upper() == "LONG" else "trade_card_short"
    text = _template(
        key,
        symbol=symbol.upper(),
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        lev=lev,
        rr=rr,
        interval=interval,
        trade_id=trade_id
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ אשר", callback_data=f"approve:{trade_id}"),
            InlineKeyboardButton("❌ דחה", callback_data=f"reject:{trade_id}")
        ]
    ]).to_dict()
    _send(text, ADMIN_CHAT_ID, reply_markup=keyboard)


# ========== Callback Handler ==========

async def handle_callback_action(update: Update):
    try:
        if not update.callback_query:
            return "no_callback"

        data = update.callback_query.data or ""
        if ":" not in data:
            return "invalid"

        action, trade_id = data.split(":", 1)
        user = update.effective_user
        username = user.username or user.first_name or "user"

        if action == "approve":
            msg = f"✅ טרייד אושר ע""י {username} ({trade_id})"
        elif action == "reject":
            msg = f"❌ טרייד נדחה ע""י {username} ({trade_id})"
        else:
            msg = f"⚠️ פעולה לא מוכרת: {action}"

        _send(msg, ADMIN_CHAT_ID)
        await update.callback_query.answer(text="בוצע", show_alert=False)
        return action

    except Exception as e:
        return f"error: {str(e)}"


