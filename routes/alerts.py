# routes/alerts.py
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.alerts import (
    send_telegram_alert, telegram_get_me, telegram_send_chat_action, format_trade_alert
)

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
    dependencies=[Depends(require_api_key)],
)

class SendRequest(BaseModel):
    message: str = Field(..., min_length=1)
    parse_mode: Optional[str] = Field("Markdown")
    disable_preview: bool = True

class TradeAlert(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(?i)(LONG|SHORT)$")
    entry: float
    sl: float
    tp1: float
    tp2: float
    size_usd: float = 50
    note: str = ""
    quality: Optional[float] = None
    success_pct: Optional[float] = None

@router.get("/ping")
async def ping():
    return {"ok": True}

@router.get("/status")
async def status():
    me = await telegram_get_me()
    typing = await telegram_send_chat_action("typing")
    return {"ok": True, "getMe": me, "chatAction": typing}

@router.post("/test")
async def test():
    msg = "🔔 *AlgoGPT Alerts* — בדיקת בוט הצליחה.\nאם אתה רואה את זה בטלגרם, הכל תקין."
    res = await send_telegram_alert(msg)
    return {"ok": bool(res.get("ok")), "response": res}

@router.post("/send")
async def send(req: SendRequest = Body(...)):
    res = await send_telegram_alert(req.message, req.parse_mode or "Markdown", req.disable_preview)
    return {"ok": bool(res.get("ok")), "response": res}

@router.post("/trade")
async def trade_alert(req: TradeAlert = Body(...)):
    text = format_trade_alert(
        req.symbol, req.side, req.entry, req.sl, req.tp1, req.tp2, req.size_usd,
        note=req.note, quality=req.quality, success_pct=req.success_pct
    )
    res = await send_telegram_alert(text)
    return {"ok": bool(res.get("ok")), "response": res, "text": text}


