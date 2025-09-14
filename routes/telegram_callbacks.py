# routes/telegram_callbacks.py
from __future__ import annotations
import os, logging, json
from typing import Any, Dict
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from utils.trade_executor import ConfirmStore

logger = logging.getLogger("algogpt.telegram.callbacks")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

async def _respond(chat_id: int, text: str):
    """שלח הודעה חוזרת בטלגרם (callback)"""
    if not TG_TOKEN:
        return
    import httpx
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, data=payload)
    except Exception as e:
        logger.warning(f"[tg] response failed: {e}")

@router.post("/callback")
async def callback_handler(req: Request):
    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    callback = update.get("callback_query")
    if not callback:
        return {"ok": True}

    data = callback.get("data") or ""
    cid = callback.get("id")
    from_user = callback.get("from") or {}
    chat_id = (callback.get("message") or {}).get("chat", {}).get("id")

    if not data.startswith("CONFIRM:"):
        return {"ok": True}

    try:
        parts = data.strip().split(":")
        if len(parts) != 3:
            raise ValueError("Invalid callback format")
        _, action, confirm_id = parts
        action = action.upper().strip()
        if action == "APPROVE":
            ConfirmStore.approve(confirm_id, approver=str(from_user.get("username") or from_user.get("id")))
            await _respond(chat_id, f"✅ טרייד אושר על ידי @{from_user.get('username', 'user')}")
        elif action == "REJECT":
            ConfirmStore.reject(confirm_id, approver=str(from_user.get("username") or from_user.get("id")))
            await _respond(chat_id, f"❌ טרייד נדחה על ידי @{from_user.get('username', 'user')}")
        else:
            await _respond(chat_id, f"⚠️ פעולה לא מזוהה: {action}")
    except Exception as e:
        logger.warning("callback error: %s", e)
        if chat_id:
            await _respond(chat_id, f"❌ שגיאה בטיפול באישור: {e}")

    return JSONResponse(content={"ok": True})
