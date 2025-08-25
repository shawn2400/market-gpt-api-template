# utils/telegram_api.py
from __future__ import annotations
import os
from typing import Optional, Dict, Any
import httpx

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))

if not TOKEN:
    # לא מפיל את השירות; מי שקורא לפונקציות יקבל שגיאה בריצה
    pass

def _ensure():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

def approve_keyboard(trade_id: str, include_analyze_button: Optional[bool] = None) -> Dict[str, Any]:
    """
    מחזיר inline keyboard סטנדרטי לטרייד.
    אם INCLUDE_ANALYZE_BUTTON=1 ב-.env (או פרמטר מפורש) — יתווסף כפתור '🧠 ניתוח GPT'.
    """
    if include_analyze_button is None:
        include_analyze_button = os.getenv("INCLUDE_ANALYZE_BUTTON", "0").lower() in ("1","true","yes")
    row = [
        {"text": "✅ אשר", "callback_data": f"approve:{trade_id}"},
        {"text": "✏️ כוונן", "callback_data": f"adjust:{trade_id}"},
        {"text": "🛑 דחה",  "callback_data": f"reject:{trade_id}"},
    ]
    if include_analyze_button:
        row.insert(1, {"text": "🧠 ניתוח GPT", "callback_data": f"analyze:{trade_id}"})
    return {"inline_keyboard": [row]}

async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[str | int] = None,
    disable_preview: bool = True,
):
    _ensure()
    if not chat_id:
        if not CHAT_ID_DEFAULT:
            raise RuntimeError("TELEGRAM_CHAT_ID not configured and chat_id not provided")
        chat_id = CHAT_ID_DEFAULT

    # הגנה על אורך
    if len(text) > 3900:
        text = text[:3900] + "\n…"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": disable_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()

async def edit_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    disable_preview: bool = True,
):
    _ensure()
    if len(text) > 3900:
        text = text[:3900] + "\n…"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": disable_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)
        r.raise_for_status()
        return r.json()
