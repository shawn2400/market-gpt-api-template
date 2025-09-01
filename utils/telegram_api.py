# utils/telegram_api.py
from __future__ import annotations
from typing import Any, Dict, Optional
import os
import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID", "")).strip()
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""

def _ensure():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    if not API_BASE:
        raise RuntimeError("Telegram API base not initialized")

async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    *,
    chat_id: Optional[int] = None,
    parse_mode: str = "Markdown",
    disable_notification: bool = False,
) -> Dict[str, Any]:
    """
    שולח הודעה. אם לא נמסר chat_id – ייפולברירת מחדל ל-DEFAULT_CHAT_ID מה-ENV.
    מחזיר את JSON תשובת טלגרם (כולל message_id ב-result.message_id).
    """
    _ensure()
    target_chat = chat_id or DEFAULT_CHAT_ID
    if not target_chat:
        raise RuntimeError("chat_id missing and DEFAULT_CHAT_ID not set")
    payload: Dict[str, Any] = {
        "chat_id": target_chat,
        "text": text,
        "disable_notification": disable_notification,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{API_BASE}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()

async def edit_message(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    *,
    parse_mode: str = "Markdown",
) -> Dict[str, Any]:
    """
    עורך הודעה קיימת לפי chat_id + message_id.
    """
    _ensure()
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{API_BASE}/editMessageText", json=payload)
        r.raise_for_status()
        return r.json()



