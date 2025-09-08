# ✅ גרסה תקינה של routes/telegram_bot.py כולל /test-ping

from __future__ import annotations
import logging, os, json, time
from typing import Dict, Any, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
from telegram import Update

from utils.auth import require_api_key
from utils.runtime_prefs import is_muted, set_mute, toggle_mute
from utils.telegram_notifier import handle_callback_action
from utils.security import verify_hmac, idem_seen
from utils.risk import suggest_risk
from utils.binance_client import (
    place_tp_ladder, set_breakeven_stop,
    futures_create_order, set_leverage,
    futures_mark_price, get_symbol_filters, modify_stop_loss,
)

logger = logging.getLogger("algogpt.routes.telegram")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

APP_VERSION = os.getenv("ALGOGPT_VERSION", "unknown")

class MuteRequest(BaseModel):
    state: bool

@router.get("/test-ping")
async def test_ping(chat_id: int, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, data={"chat_id": chat_id, "text": f"pong ✅ (v{APP_VERSION}) [test]"})
        except Exception:
            logger.exception("Failed sending telegram message")
    return {"ok": True, "sent": True, "chat_id": chat_id, "version": APP_VERSION}

@router.get("/status")
async def get_mute(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": is_muted()}

@router.post("/mute")
async def set_mute_state(req: MuteRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    set_mute(req.state)
    return {"ok": True, "mute": req.state}

@router.post("/toggle")
async def toggle_mute_state(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": toggle_mute()}

@router.post("/set-webhook")
async def set_webhook(url: str = Query(..., min_length=8), _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not token or not secret:
        raise HTTPException(500, "Telegram bot config missing")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"], "drop_pending_updates": True}
        )
        return {"ok": True, "telegram": resp.json()}

@router.post("/webhook")
async def telegram_webhook(req: Request) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if token and req.headers.get("X-Telegram-Bot-Api-Secret-Token") != token:
        raise HTTPException(status_code=403, detail="Invalid secret")

    raw = await req.body()
    try:
        payload = json.loads(raw)
    except Exception:
        return {"ok": False, "error": "Invalid payload"}

    update = Update.de_json(payload, None)
    chat_id = None
    if update and update.message:
        chat_id = update.message.chat.id
        text = (update.message.text or "").strip()
    elif update and update.callback_query:
        chat_id = update.callback_query.message.chat.id
        text = (update.callback_query.data or "").strip()
    else:
        return {"ok": True, "skip": True}

    cmd = (text or "").split()[0].split("@", 1)[0].lower()
    if chat_id and cmd in ("/ping", "ping", "/start"):
        await test_ping(chat_id)
        return {"ok": True, "echo": "ping"}
    if chat_id and cmd == "/version":
        await test_ping(chat_id)
        return {"ok": True, "version": APP_VERSION}
    return {"ok": True, "ignored": True}




























