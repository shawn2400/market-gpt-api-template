# utils/telegram_api.py
from __future__ import annotations
import os, httpx
from typing import Dict, Any, Optional

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API       = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{API}/{method}", json=payload)
        try:
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e), "status": r.status_code, "body": r.text}

async def send_message(text: str, reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown"):
    if not BOT_TOKEN or not CHAT_ID:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN/CHAT_ID"}
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await tg_call("sendMessage", payload)

async def edit_message(chat_id: Any, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await tg_call("editMessageText", payload)

def approve_keyboard(trade_id: str) -> Dict[str, Any]:
    return {"inline_keyboard":[
        [
            {"text":"✅ אשר",  "callback_data":f"approve:{trade_id}"},
            {"text":"✏️ כוונן", "callback_data":f"adjust:{trade_id}"},
            {"text":"🛑 דחה",  "callback_data":f"reject:{trade_id}"},
        ]
    ]}

