import os
import httpx
import json
from pathlib import Path
from typing import Optional

TEMPLATE_PATH = Path("static/telegram_ui_templates.json")
TEMPLATES = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8")) if TEMPLATE_PATH.exists() else {}

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
PUBLIC_FEED_CHANNEL_ID = os.getenv("PUBLIC_FEED_CHANNEL_ID")
ENABLE_PUBLIC_FEED = str(os.getenv("ENABLE_PUBLIC_FEED", "0")).lower() in ("1", "true", "yes", "on")

TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def _template(key: str, **kwargs) -> str:
    return TEMPLATES.get(key, "").format(**kwargs)

def _send(text: str, chat_id: Optional[str] = None):
    if not BOT_TOKEN or not chat_id:
        return
    try:
        httpx.post(f"{TG_BASE}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }, timeout=4.0)
    except Exception:
        pass

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

