# utils/telegram_api.py
from __future__ import annotations
import os
from typing import Any, Dict, Optional
import httpx

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE  = f"https://api.telegram.org/bot{TOKEN}"

def _chat_default(chat_id: Optional[int | str]) -> int | str:
    if chat_id is not None:
        return chat_id
    return os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""

async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[int | str] = None,
    silent: bool = False,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """
    שליחת הודעה לטלגרם (owner). מאפשר שליטה ב-disable_web_page_preview.
    """
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
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{BASE}/sendMessage", json=payload)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status_code": r.status_code, "text": r.text}

async def edit_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """
    עריכת הודעה קיימת.
    """
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": bool(disable_preview),
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{BASE}/editMessageText", json=payload)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status_code": r.status_code, "text": r.text}

async def get_me() -> Dict[str, Any]:
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/getMe")
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status_code": r.status_code, "text": r.text}

async def send_chat_action(action: str = "typing", chat_id: Optional[int | str] = None) -> Dict[str, Any]:
    if not TOKEN:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    payload = {"chat_id": _chat_default(chat_id), "action": action}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{BASE}/sendChatAction", json=payload)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status_code": r.status_code, "text": r.text}







