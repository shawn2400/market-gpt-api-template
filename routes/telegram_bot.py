# routes/telegram_bot.py
from __future__ import annotations
import logging, os
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel
import httpx

from utils.auth import require_api_key
from utils.runtime_prefs import is_muted, set_mute, toggle_mute
from utils.tp_helper import on_approve_trade_async

logger = logging.getLogger("algogpt.routes.telegram_bot")

router = APIRouter(prefix="/telegram", tags=["Telegram"])

# ─────────────────────────────
# Models
# ─────────────────────────────
class MuteRequest(BaseModel):
    state: bool

class WebhookRequest(BaseModel):
    url: str

# ─────────────────────────────
# Helpers
# ─────────────────────────────
def _require_secret(req: Request) -> None:
    """בודק שה־Webhook של טלגרם הגיע עם הטוקן הסודי שהוגדר ב־.env"""
    wanted = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    got = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not wanted:
        raise HTTPException(status_code=500, detail="TELEGRAM_WEBHOOK_SECRET not set")
    if got != wanted:
        raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

# ─────────────────────────────
# Admin Endpoints (API-Key)
# ─────────────────────────────
@router.get("/status")
async def get_mute(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "mute": is_muted()}

@router.post("/mute")
async def set_mute_state(req: MuteRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    set_mute(req.state)
    logger.info("[telegram_bot] mute set to %s", req.state)
    return {"ok": True, "mute": req.state}

@router.post("/toggle")
async def toggle_mute_state(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    new_state = toggle_mute()
    logger.info("[telegram_bot] mute toggled to %s", new_state)
    return {"ok": True, "mute": new_state}

@router.post("/set-webhook")
async def set_webhook(req: WebhookRequest = Body(...), _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not token or not secret:
        raise HTTPException(500, "Telegram bot config missing")

    tg_api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(tg_api_url, json={
                "url": req.url,
                "secret_token": secret,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": True,
            })
            resp.raise_for_status()
            return {"ok": True, "telegram": resp.json()}
    except Exception as e:
        logger.error("[telegram_bot] set-webhook failed: %s", e)
        raise HTTPException(500, f"Failed to set webhook: {e}")

# ─────────────────────────────
# Public Webhook (Telegram)
# ─────────────────────────────
@router.post("/webhook")
async def telegram_webhook(req: Request) -> Dict[str, Any]:
    _require_secret(req)
    data = await req.json()
    try:
        cb = (data.get("callback_query") or {})
        if cb and str(cb.get("data", "")).startswith("approve:"):
            try:
                _, symbol, side = cb["data"].split(":")
            except Exception:
                symbol, side = "UNKNOWN", "LONG"

            decision = {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "ai_summary": cb.get("message", {}).get("text", ""),
            }

            resp = await on_approve_trade_async(decision)
            logger.info("[telegram.webhook] approve resp: %s", resp)

        return {"ok": True}
    except Exception as e:
        logger.error("[telegram.webhook] error: %s", e)
        return {"ok": False, "error": str(e)}






















