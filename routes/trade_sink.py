# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict
import uuid

# הגנות
try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return None

from utils.security import verify_hmac, idem_seen
from utils.telegram_api import send_message, approve_keyboard

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
    """
    מקבל טרייד מוכן מה-Core/וורקר → שולח הודעת טרייד לטלגרם עם כפתורי פעולה.
    אבטחה: HMAC (X-Signature) + Idempotency (X-Idempotency-Key או trade_id).
    """
    raw = await request.body()

    # 1) אימות מקור (HMAC)
    if not verify_hmac(x_signature, raw):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2) Idempotency – מניעת כפילויות
    idem_key = x_idempotency_key or (payload.trade_id or "")
    if idem_key and idem_seen(idem_key):
        return {"ok": True, "duplicate": True}

    # 3) בונה טקסט הודעה
    tid = payload.trade_id or uuid.uuid4().hex[:8]
    lines = [
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
    ]
    txt = "\n".join([ln for ln in lines if ln])

    # 4) שליחה לטלגרם עם מקלדת
    kb = approve_keyboard(tid)  # יוסיף "🧠 ניתוח GPT" אם INCLUDE_ANALYZE_BUTTON=1
    res = await send_message(txt, reply_markup=kb)
    ok = bool(res and res.get("ok", False))
    if not ok:
        raise HTTPException(500, f"Telegram send failed: {res}")

    return {"ok": True, "trade_id": tid, "telegram": res}



