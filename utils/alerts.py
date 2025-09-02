# utils/alerts.py
from __future__ import annotations
from typing import Any, Dict, Optional
import os
import httpx

from .telegram_api import send_message  # ה־HTTP wrapper שלנו לבוט
from .runtime_prefs import TelePrefs

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE  = f"https://api.telegram.org/bot{TOKEN}"

tprefs = TelePrefs()

# ---------- Helpers to Bot API (no python-telegram-bot) ----------
async def telegram_get_me() -> Dict[str, Any]:
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{BASE}/getMe")
        return r.json()

async def telegram_send_chat_action(action: str = "typing", chat_id: Optional[int|str] = None) -> Dict[str, Any]:
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    cid = chat_id or os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(f"{BASE}/sendChatAction", json={"chat_id": cid, "action": action})
        return r.json()

# ---------- Message formatting ----------
def format_trade_alert(
    symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float,
    size_usd: float = 50, *, note: str = "", quality: float | None = None, success_pct: float | None = None
) -> str:
    s = str(side or "").upper()
    q = f" | ⭐️ איכות: {quality:.1f}" if isinstance(quality, (int, float)) else ""
    sp = f" | 🎯 הצלחה: {success_pct:.1f}%" if isinstance(success_pct, (int, float)) else ""
    note_line = f"\n📝 {note}" if note else ""
    return (
        f"🔔 *Trade Alert* — *{symbol}* ({s})\n"
        f"• Entry: `{entry}`\n"
        f"• SL: `{sl}` | TP1: `{tp1}` | TP2: `{tp2}`\n"
        f"• Size: `${size_usd:.0f}`{q}{sp}{note_line}"
    )

# ---------- Single send (wrapper) ----------
async def send_telegram_alert(
    text: str,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
    chat_id: Optional[int|str] = None,
    silent: bool = False,
) -> Dict[str, Any]:
    # שימוש ב־utils.telegram_api.send_message (אין תלות ב־telegram.*)
    return await send_message(
        text=text,
        reply_markup=None,
        chat_id=chat_id,
        silent=silent,
        parse_mode=parse_mode,
    )

# ---------- Optional: bundling hooks ----------
# אם בעתיד תרצה חבילות/פין – אפשר להרחיב כאן עם TelePrefs (כבר מוזרק).
# כרגע שומרים את זה lean כדי למנוע תלותים ומשקל מיותר.


