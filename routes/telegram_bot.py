from __future__ import annotations
import logging, os, json
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
import httpx
from telegram import Update

from utils.auth import require_api_key
from utils.runtime_prefs import is_muted, set_mute, toggle_mute

logger = logging.getLogger("algogpt.routes.telegram")

router = APIRouter(prefix="/telegram", tags=["Telegram"])
__all__ = ["router"]

APP_VERSION = os.getenv("ALGOGPT_VERSION", "unknown")


# ───────────────────────────────────────────────
# Models
# ───────────────────────────────────────────────
class MuteRequest(BaseModel):
    state: bool


# ───────────────────────────────────────────────
# Internal util – Send ping to Telegram
# ───────────────────────────────────────────────
async def _send_ping(chat_id: int, msg: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, data={"chat_id": chat_id, "text": msg})
    except Exception:
        logger.exception("Failed sending telegram message")


# ───────────────────────────────────────────────
# GET /telegram/test-ping
# ───────────────────────────────────────────────
@router.get("/test-ping", summary="בדיקת בוט טלגרם", description="שליחת הודעת 'pong' לטלגרם לצורך בדיקה")
async def test_ping(chat_id: int, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    msg = f"pong ✅ (v{APP_VERSION}) [test]"
    await _send_ping(chat_id, msg)
    return {"ok": True, "sent": True, "chat_id": chat_id, "version": APP_VERSION}


# ───────────────────────────────────────────────
# GET /telegram/status
# ───────────────────────────────────────────────
@router.get("/status", summary="בדיקת מצב השתקה")
async def get_mute(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": is_muted()}


# ───────────────────────────────────────────────
# POST /telegram/mute
# ───────────────────────────────────────────────
@router.post("/mute", summary="הפעלת/ביטול mute")
async def set_mute_state(req: MuteRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    set_mute(req.state)
    return {"ok": True, "mute": req.state}


# ───────────────────────────────────────────────
# POST /telegram/toggle
# ───────────────────────────────────────────────
@router.post("/toggle", summary="החלפת מצב mute")
async def toggle_mute_state(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": toggle_mute()}


# ───────────────────────────────────────────────
# POST /telegram/set-webhook
# ───────────────────────────────────────────────
@router.post("/set-webhook", summary="הגדרת Webhook לטלגרם")
async def set_webhook(url: str = Query(..., min_length=8), _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not token or not secret:
        raise HTTPException(500, "Telegram bot config missing")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": True
            }
        )
        return {"ok": True, "telegram": resp.json()}


# ───────────────────────────────────────────────
# POST /telegram/webhook
# ───────────────────────────────────────────────
@router.post("/webhook", summary="קלט מטלגרם (Webhook)")
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
        await _send_ping(chat_id, f"pong ✅ (v{APP_VERSION})")
        return {"ok": True, "echo": "ping"}
    if chat_id and cmd == "/version":
        await _send_ping(chat_id, f"AlgoGPT v{APP_VERSION}")
        return {"ok": True, "version": APP_VERSION}
    return {"ok": True, "ignored": True}



























