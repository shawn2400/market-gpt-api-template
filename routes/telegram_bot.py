# routes/telegram_bot.py
from __future__ import annotations
import logging
import os
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from pydantic import BaseModel
import httpx

from utils.auth import require_api_key
from utils.runtime_prefs import is_muted, set_mute, toggle_mute
from utils.tp_helper import on_approve_trade_async

logger = logging.getLogger("algogpt.telegram_bot")

# Router ללא תלות גורפת (נדרוש API-Key רק בנקודות אדמיניסטרציה)
router = APIRouter(prefix="/telegram", tags=["Telegram"])

# ===================== Models =====================
class MuteRequest(BaseModel):
    state: bool

class WebhookRequest(BaseModel):
    url: str

# ===================== Helpers =====================
def _require_telegram_secret_or_403(req: Request) -> None:
    """מאמת את הכותרת של טלגרם מול TELEGRAM_WEBHOOK_SECRET."""
    wanted = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not wanted:
        raise HTTPException(status_code=500, detail="TELEGRAM_WEBHOOK_SECRET not set")
    got = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if got != wanted:
        raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

# ===================== Admin Endpoints (API-Key) =====================
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
    מגדיר Webhook לבוט טלגרם, כולל secret_token לאימות ההדר.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not set")
    if not secret:
        raise HTTPException(status_code=500, detail="TELEGRAM_WEBHOOK_SECRET not set")

    try:
        tg_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        payload = {
            "url": req.url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(tg_api_url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            return {"ok": True, "telegram": result}
    except Exception as e:
        logger.error("[telegram_bot] set-webhook failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to set webhook: {e}")

# ===================== Public Webhook (Telegram) =====================
@router.post("/webhook", summary="Telegram webhook (public, secret header)")
async def telegram_webhook(req: Request) -> Dict[str, Any]:
    """
    נקודת כניסה לטלגרם — מאומתת ע״י X-Telegram-Bot-Api-Secret-Token.
    מטפלת ב-callback 'approve:<symbol>:<side>' ומקימה סולם TP.
    """
    _require_telegram_secret_or_403(req)
    data = await req.json()
    try:
        cb = (data.get("callback_query") or {})
        if cb:
            msg = cb.get("message") or {}
            text = msg.get("text") or ""
            d = cb.get("data") or ""
            if d.startswith("approve:"):
                try:
                    _, symbol, side = d.split(":")
                except Exception:
                    symbol, side = "UNKNOWN", "LONG"

                decision = {
                    "symbol": (symbol or "UNKNOWN").upper(),
                    "side": (side or "LONG").upper(),
                    "ai_summary": text,  # יאפשר ל-parser לשלוף TP אם הופיעו בטקסט
                }

                # Async — לא חוסם; כולל cooldown פנימי נגד כפילויות
                resp = await on_approve_trade_async(decision)
                logger.info("[tg.webhook] approve ladder resp: %s", resp)

        # אפשר להרחיב כאן פקודות טקסט /mute on|off וכו' אם תרצה
        return {"ok": True}
    except Exception as e:
        logger.error("[tg.webhook] error: %s", e)
        return {"ok": False, "error": str(e)}




















