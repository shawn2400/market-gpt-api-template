# FILE: utils/telegram_api.py
from __future__ import annotations
import os
from typing import Any, Dict, Optional, Union
import httpx
import logging

logger = logging.getLogger("algogpt.telegram")

# === Tokens and Base URL ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""

# Optional global parse mode from ENV: "", "HTML", "MarkdownV2"
PARSE_MODE_ENV = (os.getenv("TELEGRAM_PARSE_MODE", "") or "").strip() or None


def _chat_default(chat_id: Optional[Union[int, str]]) -> Union[int, str]:
    """
    קובע chat_id ברירת מחדל:
    קודם chat_id שנשלח לפונקציה, אחרת ADMIN_CHAT_ID או TELEGRAM_CHAT_ID מהסביבה.
    שומר מחרוזת אם זו מחרוזת; מנסה להמיר למספר אם אפשר.
    """
    if chat_id is not None:
        return chat_id
    val = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""
    try:
        if val and str(val).lstrip("-").isdigit():
            return int(val)
    except Exception:
        pass
    return val or ""


async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[Union[int, str]] = None,
    silent: bool = False,
    parse_mode: Optional[str] = None,
    disable_preview: bool = True,
) -> Dict[str, Any]:
    """
    שולח הודעה. אם parse_mode לא נשלח, נשתמש ב-TELEGRAM_PARSE_MODE מה-ENV (אם הוגדר),
    אחרת לא נשלח parse_mode כלל (מונע 400 במקרה של תווים 'רגישים').
    """
    if not TOKEN or not BASE:
        logger.error("TELEGRAM_BOT_TOKEN missing")
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}

    # 🛡️ FIX: Respect explicit parse_mode="" as "no formatting"
    # Only apply PARSE_MODE_ENV if parse_mode is None (not provided)
    if parse_mode is None:
        parse_mode = PARSE_MODE_ENV
    elif parse_mode == "":
        parse_mode = None  # Empty string means "no parse_mode"

    payload: Dict[str, Any] = {
        "chat_id": _chat_default(chat_id),
        "text": text,
        "disable_web_page_preview": bool(disable_preview),
        "disable_notification": bool(silent),
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE}/sendMessage", json=payload)
            # 🛡️ FIX: Log detailed error on 400
            if r.status_code == 400:
                logger.error({"event":"telegram_400_error","payload":payload,"response":r.text})
            return r.json()
    except Exception as e:
        logger.error("send_message failed: %s", e)
        return {"ok": False, "error": str(e)}


async def edit_message(
    chat_id: Union[int, str],
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: Optional[str] = None,
    disable_preview: bool = True,
) -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}

    if parse_mode is None:
        parse_mode = PARSE_MODE_ENV

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": bool(disable_preview),
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE}/editMessageText", json=payload)
            return r.json()
    except Exception as e:
        logger.error("edit_message failed: %s", e)
        return {"ok": False, "error": str(e)}


async def get_me() -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BASE}/getMe")
            return r.json()
    except Exception as e:
        logger.error("get_me failed: %s", e)
        return {"ok": False, "error": str(e)}


async def send_chat_action(
    action: str = "typing",
    chat_id: Optional[Union[int, str]] = None
) -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}

    payload = {"chat_id": _chat_default(chat_id), "action": action}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE}/sendChatAction", json=payload)
            return r.json()
    except Exception as e:
        logger.error("send_chat_action failed: %s", e)
        return {"ok": False, "error": str(e)}










