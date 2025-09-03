# utils/alerts.py
from __future__ import annotations
import os
import asyncio
from typing import Optional, Dict, Any
import logging

from utils import telegram_api  # מקור יחיד לשכבת טלגרם

logger = logging.getLogger("algogpt.alerts")

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()

_TG_REC   = (os.getenv("TG_NOTIFY_RECONCILE","1").strip().lower() in ("1","true","yes","on"))
_TG_GRID  = (os.getenv("TG_NOTIFY_GRID","1").strip().lower() in ("1","true","yes","on"))
_TG_MNGR  = (os.getenv("TG_NOTIFY_MANAGER","0").strip().lower() in ("1","true","yes","on"))

def _ensure_chat_id() -> str:
    if not ADMIN_CHAT_ID:
        raise RuntimeError("ADMIN_CHAT_ID/TELEGRAM_CHAT_ID is not set")
    return ADMIN_CHAT_ID

# ─────────────────────────────────────────────────────────────────────────────
# Proxies (API יציב לשאר המערכת)
# ─────────────────────────────────────────────────────────────────────────────
async def send_telegram_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[int|str] = None,
    silent: bool = False,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """
    שכבת proxy אחידה לשליחת הודעות. ברירת מחדל ל-admin chat אם לא סופק chat_id.
    """
    if chat_id is None:
        chat_id = _ensure_chat_id()
    return await telegram_api.send_message(
        text=text,
        reply_markup=reply_markup,
        chat_id=chat_id,
        silent=silent,
        parse_mode=parse_mode,
        disable_preview=disable_preview,
    )

async def edit_telegram_message(
    chat_id: int|str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """
    proxy לעריכת הודעה קיימת.
    """
    return await telegram_api.edit_message(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_preview=disable_preview,
    )

async def telegram_get_me() -> Dict[str, Any]:
    return await telegram_api.get_me()

async def telegram_send_chat_action(action: str = "typing") -> Dict[str, Any]:
    chat_id = _ensure_chat_id()
    return await telegram_api.send_chat_action(action=action, chat_id=chat_id)

# ─────────────────────────────────────────────────────────────────────────────
# שמירה על תאימות לאחור (שמות היסטוריים)
# ─────────────────────────────────────────────────────────────────────────────
async def send_telegram_alert(
    message: str,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """
    אליאס היסטורי ל-send_telegram_message.
    """
    return await send_telegram_message(
        text=message,
        parse_mode=parse_mode,
        disable_preview=disable_preview,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Helpers תוכן
# ─────────────────────────────────────────────────────────────────────────────
def _coerce_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s in ("LONG", "BUY"):
        return "LONG"
    if s in ("SHORT", "SELL"):
        return "SHORT"
    return s or "LONG"

def format_trade_alert(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    size_usd: float = 50.0,
    *,
    note: str = "",
    quality: Optional[float] = None,
    success_pct: Optional[float] = None,
) -> str:
    sym = (symbol or "").upper().strip()
    side_n = _coerce_side(side)
    q_str = f"\n• Quality: *{quality:.2f}*/10" if isinstance(quality, (int, float)) else ""
    s_str = f"\n• Success Rate: *{success_pct:.1f}%*" if isinstance(success_pct, (int, float)) else ""
    n_str = f"\n• Note: _{note}_" if note else ""
    txt = (
        "🔔 *AlgoGPT – Trade Alert*\n"
        f"*{sym}* • *{side_n}*\n"
        f"• Entry: `{entry:.6f}`\n"
        f"• SL: `{sl:.6f}`\n"
        f"• TP1: `{tp1:.6f}`\n"
        f"• TP2: `{tp2:.6f}`\n"
        f"• Size ≈ ${size_usd:.2f}"
        f"{q_str}{s_str}{n_str}"
    )
    return txt

# ─────────────────────────────────────────────────────────────────────────────
# fire-and-forget קלים
# ─────────────────────────────────────────────────────────────────────────────
def _fire_and_forget(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(coro)
    except Exception:
        pass

def tg_info(text: str) -> None:
    _fire_and_forget(send_telegram_message(f"ℹ️ {text}"))

def tg_warn(text: str) -> None:
    _fire_and_forget(send_telegram_message(f"⚠️ {text}"))

def tg_ok(text: str) -> None:
    _fire_and_forget(send_telegram_message(f"✅ {text}"))

def tg_err(text: str) -> None:
    _fire_and_forget(send_telegram_message(f"❌ {text}"))

def tg_rec(text: str) -> None:
    if _TG_REC:
        _fire_and_forget(send_telegram_message(text))

def tg_grid(text: str) -> None:
    if _TG_GRID:
        _fire_and_forget(send_telegram_message(text))

def tg_mngr(text: str) -> None:
    if _TG_MNGR:
        _fire_and_forget(send_telegram_message(text))







