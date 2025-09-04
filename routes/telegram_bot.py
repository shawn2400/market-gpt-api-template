# routes/telegram_bot.py
from __future__ import annotations
import logging
import os
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
import httpx

from utils.auth import require_api_key
from utils.runtime_prefs import is_muted, set_mute, toggle_mute

logger = logging.getLogger("algogpt.telegram_bot")

router = APIRouter(
    prefix="/telegram",
    tags=["Telegram"],
    dependencies=[Depends(require_api_key)],
)

# ===================== Models =====================
class MuteRequest(BaseModel):
    state: bool

class WebhookRequest(BaseModel):
    url: str

# ===================== Endpoints =====================

@router.get("/status", summary="Get mute status")
async def get_mute_status(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": is_muted()}


@router.post("/mute", summary="Set mute state")
async def set_mute_state(req: MuteRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        set_mute(req.state)
        logger.info("[telegram_bot] mute set to %s", req.state)
        return {"ok": True, "mute": req.state}
    except Exception as e:
        logger.error("[telegram_bot] set_mute error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle", summary="Toggle mute state")
async def toggle_mute_state(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        new_state = toggle_mute()
        logger.info("[telegram_bot] mute toggled to %s", new_state)
        return {"ok": True, "mute": new_state}
    except Exception as e:
        logger.error("[telegram_bot] toggle_mute error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set-webhook", summary="Set Telegram Webhook")
async def set_telegram_webhook(
    req: WebhookRequest = Body(...),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    מגדיר Webhook לבוט טלגרם המבוסס על TELEGRAM_BOT_TOKEN
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not set")

    try:
        tg_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        async with httpx.AsyncClient() as client:
            resp = await client.post(tg_api_url, json={"url": req.url})
            resp.raise_for_status()
            result = resp.json()
            return {"ok": True, "telegram": result}
    except Exception as e:
        logger.error("[telegram_bot] set-webhook failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to set webhook: {e}")



















