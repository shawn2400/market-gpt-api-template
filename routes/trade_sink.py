# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict
from utils.auth import require_api_key
from utils.telegram_api import send_message, approve_keyboard
import os, uuid, time

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

# Idempotency (אופציונלי) – זיכרון זמני למניעת שכפול הודעות
_IDEM_CACHE: Dict[str, float] = {}
_IDEM_TTL = 60 * 10  # 10 דקות

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
    # אבטחה (אופציונלי): חתימה HMAC מצד ה-Core (נבדקת ע"י reverse proxy/תוסף)
    signature: Optional[str] = None

def _fmt(v: Optional[float]) -> str:
    return f"`{v:.6f}`" if v is not None else "`—`"

def _idem_ok(key: Optional[str]) -> bool:
    if not key:
        return True
    now = time.time()
    # ניקוי ישן
    for k, ts in list(_IDEM_CACHE.items()):
        if now - ts > _IDEM_TTL:
            _IDEM_CACHE.pop(k, None)
    if key in _IDEM_CACHE:
        return False
    _IDEM_CACHE[key] = now
    return True

@router.post("/trade-ingest")
async def trade_ingest(
    payload: TradeIngest = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False)
):
    # מניעת כפילויות (אופציונלי)
    idem_key = x_idempotency_key or (payload.trade_id or "")
    if not _idem_ok(idem_key):
        return {"ok": True, "duplicate": True}

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
        (f"סיבה: {payload.reason}" if payload.reason else None)
    ]))

    kb = approve_keyboard(tid)
    res = await send_message(txt, reply_markup=kb)
    if not res.get("ok"):
        raise HTTPException(500, f"Telegram send failed: {res}")
    return {"ok": True, "trade_id": tid, "telegram": res}

