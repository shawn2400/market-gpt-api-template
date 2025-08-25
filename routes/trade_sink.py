# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict
from utils.auth import require_api_key
from utils.telegram_api import send_message, approve_keyboard
from utils.security import verify_hmac, idem_seen
import uuid

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

class TradeIngest(BaseModel):
    trade_id: Optional[str] = None
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
    eta_sl: Optional[str] = None
    eta_tp1: Optional[str] = None
    eta_tp2: Optional[str] = None
    eta_tp3: Optional[str] = None
    reason: Optional[str] = None

def _fmt(v: Optional[float]) -> str:
    return f"`{v:.6f}`" if v is not None else "`—`"

@router.post("/trade-ingest")
async def trade_ingest(
    request: Request,
    payload: TradeIngest = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False),
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    # 1) אימות מקור (HMAC)
    raw = await request.body()
    if not verify_hmac(x_signature, raw):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2) Idempotency – מניעת כפילויות
    idem_key = x_idempotency_key or (payload.trade_id or "")
    if idem_seen(idem_key):
        return {"ok": True, "duplicate": True}

    # 3) שליחה לטלגרם (דק — ללא חישובים)
    tid = payload.trade_id or uuid.uuid4().hex[:8]
    txt = "\n".join(filter(None, [
        "🧠 *AlgoGPT — טרייד מוכן*",
        f"*{payload.symbol}* | *{payload.side.upper()}* | מחיר עכשיו: `{payload.current_price:.6f}`",
        f"כניסה: `{payload.entry:.6f}` | SL: `{payload.sl:.6f}` | TP1: {_fmt(payload.tp1)} | TP2: {_fmt(payload.tp2)} | TP3: {_fmt(payload.tp3)}",
        " | ".join(filter(None, [
            f"מינוף: `x{payload.leverage}`",
            f"תקציב: `${payload.budget_usd:.2f}`" if payload.budget_usd else None,
            f"Notional: `${payload.notional_usd:.2f}`" if payload.notional_usd else None,
            f"Qty≈ `{payload.qty:.6f}`" if payload.qty else None,
        ])),
        (f"% הצלחה: `{payload.success_pct:.1f}%`" if payload.success_pct is not None else None),
        "⏱️ *ETAs* — "
        + (f"SL: _{payload.eta_sl}_ | " if payload.eta_sl else "SL: _—_ | ")
        + (f"TP1: _{payload.eta_tp1}_ | " if payload.eta_tp1 else "TP1: _—_ | ")
        + (f"TP2: _{payload.eta_tp2}_ | " if payload.eta_tp2 else "TP2: _—_ | ")
        + (f"TP3: _{payload.eta_tp3}_" if payload.eta_tp3 else "TP3: _—_"),
        (f"סיבה: {payload.reason}" if payload.reason else None),
        f"\nID: `{tid}`"
    ]))
    res = await send_message(txt, reply_markup=approve_keyboard(tid))
    if not res.get("ok"):
        raise HTTPException(500, f"Telegram send failed: {res}")

    return {"ok": True, "trade_id": tid, "telegram": res}


