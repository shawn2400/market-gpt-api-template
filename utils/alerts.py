# utils/alerts.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from telegram.constants import ParseMode

from utils.runtime_prefs import TelePrefs

tprefs = TelePrefs()


async def should_suppress_alert(symbol: str, trade_id: Optional[str]) -> bool:
    """
    שער השתקה: מחזיר True אם הסימבול/טרייד מושתקים ב-TTL.
    """
    if symbol and await tprefs.is_snoozed_symbol(symbol):
        return True
    if trade_id and await tprefs.is_snoozed_trade(trade_id):
        return True
    return False


async def send_alert_or_bundle(bot, chat_id: int, payload: Dict[str, Any]) -> None:
    """
    שיגור התראה בודדת או הכנסת לאצווה (bundle).
    payload: {"type":"near_tp","symbol":"BTCUSDT","trade_id":"abc","text":"...","short":"..."}
    """
    if await should_suppress_alert(payload.get("symbol", ""), payload.get("trade_id")):
        return

    bundle_sec = await tprefs.get_bundle_window(chat_id)
    if bundle_sec > 0:
        await tprefs.bundle_enqueue(chat_id, payload)
        return

    await bot.send_message(chat_id=chat_id, text=payload["text"])


async def bundle_tick(bot, chat_id: int) -> None:
    """
    רוקן את תור ה-bundle ושלח הודעה מרוכזת אחת. לקרוא מלולאת ה-watchdog הקיימת.
    """
    items = await tprefs.bundle_flush(chat_id, max_items=200)
    if not items:
        return

    lines: List[str] = []
    for it in items:
        sym = it.get("symbol", "?")
        typ = it.get("type", "event")
        tip = it.get("short", "")
        lines.append(f"• [{typ}] {sym} {tip}".strip())

    text = "📦 *Bundled alerts*\n" + "\n".join(lines)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)


async def update_pinned_summary(bot, chat_id: int, summary_text: str) -> None:
    """
    עדכון הודעת סיכום מוצמדת ע"י edit; יצירה + pin אם אין.
    """
    if not await tprefs.is_pin_summary(chat_id):
        return

    msg_id = await tprefs.get_pin_message_id(chat_id)
    if msg_id is None:
        msg = await bot.send_message(chat_id=chat_id, text=summary_text, parse_mode=ParseMode.MARKDOWN)
        await tprefs.set_pin_message_id(chat_id, msg.message_id)
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        except Exception:
            pass
        return

    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=summary_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # אם ההודעה נמחקה/פגה – צור חדשה ושמור message_id
        msg = await bot.send_message(chat_id=chat_id, text=summary_text, parse_mode=ParseMode.MARKDOWN)
        await tprefs.set_pin_message_id(chat_id, msg.message_id)

