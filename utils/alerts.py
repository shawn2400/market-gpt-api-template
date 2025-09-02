# utils/alerts.py
from __future__ import annotations
import os
import asyncio
from typing import Optional, Dict, Any
import logging

import httpx

logger = logging.getLogger("algogpt.alerts")

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()

def _api_base() -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def _ensure_chat_id() -> str:
    if not ADMIN_CHAT_ID:
        raise RuntimeError("ADMIN_CHAT_ID/TELEGRAM_CHAT_ID is not set")
    return ADMIN_CHAT_ID

async def _post(method: str, data: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{_api_base()}/{method}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, data=data)
        try:
            js = r.json()
        except Exception:
            js = {"ok": False, "status_code": r.status_code, "text": r.text}
        if not js.get("ok", False):
            logger.warning({"event": "tg_api_error", "method": method, "status": r.status_code, "resp": js})
        return js

async def telegram_get_me() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{_api_base()}/getMe")
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status_code": r.status_code, "text": r.text}

async def telegram_send_chat_action(action: str = "typing") -> Dict[str, Any]:
    chat_id = _ensure_chat_id()
    return await _post("sendChatAction", {"chat_id": chat_id, "action": action})

def _coerce_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s in ("LONG", "BUY"):  # נוח
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

async def send_telegram_alert(
    message: str,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    chat_id = _ensure_chat_id()
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true" if disable_preview else "false",
        "disable_notification": "false",
    }
    return await _post("sendMessage", data)



