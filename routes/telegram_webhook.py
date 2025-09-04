# routes/telegram_webhook.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import logging
import os
import httpx

router = APIRouter(prefix="/telegram", tags=["Telegram Webhook"])

logger = logging.getLogger("algogpt.telegram.webhook")

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SEND_MESSAGE_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" if TELEGRAM_TOKEN else None

async def send_message(chat_id: int, text: str):
    if not TELEGRAM_TOKEN or not SEND_MESSAGE_API:
        logger.warning("[telegram_webhook] Missing TELEGRAM_BOT_TOKEN, can't send message")
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(SEND_MESSAGE_API, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.warning(f"[telegram_webhook] Failed to send message: {e}")

@router.post("/webhook")
async def telegram_webhook(req: Request):
    try:
        data = await req.json()
        logger.info({"event": "telegram_webhook_received", "data": data})

        # Extract chat + text
        message = data.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if not chat_id or not text:
            return {"ok": True, "note": "no chat_id or text"}

        # Echo back message
        await send_message(chat_id, f"✅ קיבלתי: {text}")

        return {"ok": True, "received": text}

    except Exception as e:
        logger.error(f"[telegram_webhook] Error: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})





