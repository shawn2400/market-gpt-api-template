# utils/telegram_api.py
from __future__ import annotations
import os
from typing import Any, Dict, Optional
import httpx
import logging

logger = logging.getLogger("algogpt.telegram")

# === Config ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""

def _chat_default(chat_id: Optional[int | str]) -> str:
    """החזרת chat_id ברירת מחדל אם לא סופק"""
    return str(chat_id or os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "")


async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[int | str] = None,
    silent: bool = False,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """שליחת הודעה לטלגרם"""
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    payload: Dict[str, Any] = {
        "chat_id": _chat_default(chat_id),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": bool(disable_preview),
        "disable_notification": bool(silent),
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE}/sendMessage", json=payload)
            return r.json()
    except Exception as e:
        logger.error(f"send_message failed: {e}")
        return {"ok": False, "error": str(e)}


async def edit_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """עריכת הודעה קיימת"""
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    payload: Dict[str, Any] = {
        "chat_id": str(chat_id),
        "message_id": int(message_id),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": bool(disable_preview),
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE}/editMessageText", json=payload)
            return r.json()
    except Exception as e:
        logger.error(f"edit_message failed: {e}")
        return {"ok": False, "error": str(e)}


async def get_me() -> Dict[str, Any]:
    """בדיקת זהות הבוט (getMe)"""
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BASE}/getMe")
            return r.json()
    except Exception as e:
        logger.error(f"get_me failed: {e}")
        return {"ok": False, "error": str(e)}


async def send_chat_action(
    action: str = "typing",
    chat_id: Optional[int | str] = None,
) -> Dict[str, Any]:
    """שליחת אינדיקציית פעולה (typing, upload_photo וכו')"""
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    payload = {"chat_id": _chat_default(chat_id), "action": action}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE}/sendChatAction", json=payload)
            return r.json()
    except Exception as e:
        logger.error(f"send_chat_action failed: {e}")
        return {"ok": False, "error": str(e)}








