# utils/telegram_notifier.py
from __future__ import annotations
import os, logging, httpx
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _TZ_IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    _TZ_IL = None

logger = logging.getLogger("algogpt.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ===== Utils =====
def _now_il_str() -> str:
    try:
        if _TZ_IL:
            return datetime.now(_TZ_IL).strftime("%d/%m/%Y | %H:%M")
        return datetime.utcnow().strftime("%d/%m/%Y | %H:%M")
    except Exception:
        return ""

async def _post_telegram(payload: Dict[str, Any]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

# ===== SL/TP Updates =====
async def notify_sl_tp_update(symbol: str, side: str, update_type: str, new_price: float) -> None:
    """
    שליחת הודעה מעוצבת על עדכון SL/TP:
    update_type: "breakeven" | "trailing" | "tp"
    """
    side_icon = "🟢" if side.upper() == "LONG" else "🔴"
    if update_type == "breakeven":
        icon, title = "✅", "SL → Breakeven"
    elif update_type == "trailing":
        icon, title = "⚠️", "Trailing SL"
    elif update_type == "tp":
        icon, title = "🎯", "Dynamic TP"
    else:
        icon, title = "ℹ️", update_type

    text = (
        f"{icon} *{title}*\n"
        f"{side_icon} {symbol.upper()} ({side.upper()})\n"
        f"📈 מחיר חדש: `{new_price:.2f}` USDT\n"
        f"⏱️ {_now_il_str()}"
    )

    await _post_telegram({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })

async def notify_info(text: str) -> None:
    await _post_telegram({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })





