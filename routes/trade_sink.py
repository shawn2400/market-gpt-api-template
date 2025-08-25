# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from utils.auth import require_api_key
from utils.telegram_api import send_message, approve_keyboard
import uuid

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

class TradeIngest(BaseModel):
    trade_id: Optional[str] = None  # אם יש לך מזהה משלך, אפשר להביא; אחרת ניצור
    symbol: str
    side: str = Field(..., pattern="^(?i)(LONG|SHORT)$")
    current_price: float
    leverage: int
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    success_pct: Optional[float] = None
    budget_usd: Optional[float] = None
    notional_usd: Optional[float] = None
    qty: Optional[float] = None

    # ETA מוכנות (אם ה-Core שלך כבר מחשב)
    eta_sl: Optional[str] = None
    eta_tp1: Optional[str] = None
    eta_tp2: Optional[str] = None
    eta_tp3: Optional[str] = None

    # תקציר/סיבה ("למה הוא בחור")
    reason: Optional[str] = None

def _fmt(v: Optional[float]) -> str:
    return f"`{v:.6f}`" if v is not None else "`—`"

@router.post("/trade-ingest")
async def trade_ingest(payload: TradeIngest = Body(...)):
    # אין חישובים! רק פורמט → טלגרם
    tid = payload.trade_id or uuid.uuid4().hex[:8]
    txt = "\n".join([
        "🧠 *AlgoGPT — טרייד מוכן*",
        f"*{payload.symbol}* | *{payload.side.upper()}* | מחיר עכשיו: `{payload.current_price:.6f}`",
        f"כניסה: `{payload.entry:.6f}` | SL: `{payload.sl:.6f}` | TP1: {_fmt(payload.tp1)} | TP2: {_fmt(payload.tp2)} | TP3: {_fmt(payload.tp3)}",
        f"מינוף: `x{payload.leverage}`"
        + (f" | תקציב: `${payload.budget_usd:.2f}`" if payload.budget_usd else "")
        + (f" | Notional: `${payload.notional_usd:.2f}`" if payload.notional_usd else "")
        + (f" | Qty≈ `{payload.qty:.6f}`" if payload.qty else ""),
        (f"% הצלחה: `{payload.success_pct:.1f}%`" if payload.success_pct is not None else ""),
        "⏱️ *ETAs* — "
        + (f"SL: _{payload.eta_sl}_ | " if payload.eta_sl else "SL: _—_ | ")
        + (f"TP1: _{payload.eta_tp1}_ | " if payload.eta_tp1 else "TP1: _—_ | ")
        + (f"TP2: _{payload.eta_tp2}_ | " if payload.eta_tp2 else "TP2: _—_ | ")
        + (f"TP3: _{payload.eta_tp3}_" if payload.eta_tp3 else "TP3: _—_"),
        (f"סיבה: {payload.reason}" if payload.reason else "")
    ])

    kb = approve_keyboard(tid)
    res = await send_message(txt, reply_markup=kb)
    if not res.get("ok"):
        raise HTTPException(500, f"Telegram send failed: {res}")
    return {"ok": True, "trade_id": tid, "telegram": res}
