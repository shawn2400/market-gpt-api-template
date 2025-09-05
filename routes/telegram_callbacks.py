# routes/telegram_callbacks.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from telegram import Update
import json

from utils.telegram_notifier import handle_callback_action

router = APIRouter(prefix="/telegram/callbacks", tags=["TelegramCallbacks"])

@router.post("/")
async def telegram_callback_webhook(request: Request):
    try:
        body = await request.body()
        update = Update.de_json(json.loads(body), None)
        result = await handle_callback_action(update)
        return JSONResponse(content={"ok": True, "result": result})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


