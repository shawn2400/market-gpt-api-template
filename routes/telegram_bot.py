# routes/telegram_bot.py
from __future__ import annotations
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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

# ===================== Endpoints =====================
@router.get("/status", summary="Get mute status")
async def get_mute_status(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    מחזיר את מצב ההשתקה (mute/unmute).
    """
    return {"ok": True, "mute": is_muted()}


@router.post("/mute", summary="Set mute state")
async def set_mute_state(req: MuteRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    משנה את מצב ההשתקה למצב נתון (mute/unmute).
    """
    try:
        set_mute(req.state)
        logger.info("[telegram_bot] mute set to %s", req.state)
        return {"ok": True, "mute": req.state}
    except Exception as e:
        logger.error("[telegram_bot] set_mute error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle", summary="Toggle mute state")
async def toggle_mute_state(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    הופך את מצב ההשתקה (אם היה mute -> unmute, ואם לא -> mute).
    """
    try:
        new_state = toggle_mute()
        logger.info("[telegram_bot] mute toggled to %s", new_state)
        return {"ok": True, "mute": new_state}
    except Exception as e:
        logger.error("[telegram_bot] toggle_mute error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


















