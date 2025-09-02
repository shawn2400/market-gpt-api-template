# utils/alerts.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from telegram.constants import ParseMode  # type: ignore

from utils.runtime_prefs import TelePrefs
from utils.telegram_api import send_message, edit_message, get_me, send_chat_action

tprefs = TelePrefs()

# ─────────────────────────────
# Bundling / Snooze / Pin logic
# ─────────────────────────────
async def should_suppress_alert(symbol: str, trade_id: Optional[str]) -> bool:
    if symbol and await tprefs.is_snoozed_symbol(symbol):
        return True
    if trade_id and await tprefs.is_snoozed_trade(trade_id):
        return True
    return False

async def send_alert_or_bundle(payload: Dict[str, Any], chat_id: Optional[int | str] = None) -> None:
    """
    payload example:
      {"type":"near_tp","symbol":"BTCUSDT","trade_id":"abc","text":"...","short":"..."}
    """
    if await should_suppress_alert(payload.get("symbol", ""), payload.get("trade_id")):
        return

    # bundle if window>0
    cid = chat_id or 0  # runtime prefs use int keys
    bundle_sec = await tprefs.get_bundle_window(int(cid) if cid else 0)
    if bundle_sec > 0:
        await tprefs.bundle_enqueue(int(cid), payload)
        return

    await send_message(text=payload["text"], chat_id=chat_id, parse_mode="Markdown")

async def bundle_tick(bot_chat_id: int) -> None:
    """
    Flush the bundle queue and send one consolidated message.
    """
    items = await tprefs.bundle_flush(int(bot_chat_id), max_items=200)
    if not items:
        return

    lines: List[str] = []
    for it in items:
        sym = it.get("symbol", "?")
        typ = it.get("type", "event")
        tip = it.get("short", "")
        lines.append(f"• [{typ}] {sym} {tip}".strip())

    text = "📦 *Bundled alerts*\n" + "\n".join(lines)
    await send_message(text=text, chat_id=bot_chat_id, parse_mode="Markdown")

async def update_pinned_summary(summary_text: str, chat_id: int) -> None:
    """
    Update or create a pinned summary message.
    """
    if not await tprefs.is_pin_summary(chat_id):
        return

    msg_id = await tprefs.get_pin_message_id(chat_id)
    if msg_id is None:
        res = await send_message(text=summary_text, chat_id=chat_id, parse_mode="Markdown")
        try:
            message_id = int(((res or {}).get("result") or {}).get("message_id"))
            await tprefs.set_pin_message_id(chat_id, message_id)
        except Exception:
            pass
        return

    # Try edit; if fails → send new and remember id
    res = await edit_message(chat_id=chat_id, message_id=msg_id, text=summary_text, parse_mode="Markdown")
    if not (res or {}).get("ok"):
        res2 = await send_message(text=summary_text, chat_id=chat_id, parse_mode="Markdown")
        try:
            message_id = int(((res2 or {}).get("result") or {}).get("message_id"))
            await tprefs.set_pin_message_id(chat_id, message_id)
        except Exception:
            pass

# ─────────────────────────────
# Simple Telegram wrappers used by routes
# ─────────────────────────────
async def send_telegram_alert(message: str, parse_mode: str = "Markdown", disable_preview: bool = True) -> Dict[str, Any]:
    return await send_message(text=message, parse_mode=parse_mode)

async def telegram_get_me() -> Dict[str, Any]:
    return await get_me()

async def telegram_send_chat_action(action: str = "typing") -> Dict[str, Any]:
    return await send_chat_action(action)

# ─────────────────────────────
# Formatting helpers
# ─────────────────────────────
def format_trade_alert(
    symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float, size_usd: float,
    *, note: str = "", quality: Optional[float] = None, success_pct: Optional[float] = None
) -> str:
    side_u = (side or "").upper()
    q_txt = f"\n• Quality: *{quality:.2f}*/10" if isinstance(quality, (int, float)) else ""
    s_txt = f"\n• Win prob: *{success_pct:.1f}%*" if isinstance(success_pct, (int, float)) else ""
    n_txt = f"\n• Note: _{note}_" if note else ""
    return (
        f"🔔 *{symbol}* — *{side_u}*\n"
        f"• Entry: `{entry}`\n"
        f"• SL: `{sl}`\n"
        f"• TP1/TP2: `{tp1}` / `{tp2}`\n"
        f"• Size: ~${size_usd:.0f}"
        f"{q_txt}{s_txt}{n_txt}"
    )


