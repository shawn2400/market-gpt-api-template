# routes/telegram_routes.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import logging
import os
import httpx

logger = logging.getLogger("algogpt.telegram")

router = APIRouter(prefix="/telegram", tags=["Telegram"])

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://algogpt-docker.onrender.com")


@router.post("/set-webhook")
async def set_webhook():
    if not TELEGRAM_TOKEN:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing TELEGRAM_BOT_TOKEN env"})

    webhook_url = f"{WEBHOOK_HOST}/telegram/webhook"
    telegram_api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(telegram_api, json={"url": webhook_url})
            res.raise_for_status()
            result = res.json()
            return {"ok": True, "telegram_response": result}
    except Exception as e:
        logger.error(f"[telegram] set-webhook error: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@router.post("/webhook")
async def telegram_webhook(req: Request):
    try:
        body = await req.json()
        logger.info({"event": "telegram_incoming", "body": body})
        return {"ok": True}
    except Exception as e:
        logger.error(f"[telegram] webhook error: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
