# routes/portfolio.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Optional
from utils.portfolio import portfolio

router = APIRouter()


@router.get("/state", tags=["Portfolio"])
async def get_portfolio_state():
    """
    ✅ מחזיר מצב עדכני של התיק:
    - balance נוכחי
    - פוזיציות פתוחות
    - היסטוריית טריידים
    """
    return portfolio.get_portfolio_state()


@router.post("/open", tags=["Portfolio"])
async def open_trade(
    symbol: str,
    side: str,
    entry: float,
    qty: float = Query(..., description="כמות נכס (ביחידות, לא USD)"),
    leverage: int = Query(10, description="מינוף (לברירת מחדל 10x)"),
    sl: Optional[float] = Query(None, description="Stop Loss"),
    tp: Optional[float] = Query(None, description="Take Profit"),
    budget: Optional[float] = Query(None, description="תקציב (USD)"),
):
    """
    ✅ פתיחת טרייד חדש בתיק (לא ישירות ב־Binance).
    """
    try:
        trade = portfolio.open_trade(
            symbol=symbol,
            side=side,
            entry=entry,
            qty=qty,
            leverage=leverage,
            sl=sl,
            tp=tp,
            budget=budget,
        )
        return {"ok": True, "trade": trade}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/close", tags=["Portfolio"])
async def close_trade(symbol: str, close_price: float):
    """
    ✅ סגירת טרייד פתוח לפי סימבול.
    מחשב PnL ומעדכן Balance.
    """
    try:
        trade = portfolio.close_trade(symbol, close_price)
        return {"ok": True, "trade": trade}
    except Exception as e:
        return {"ok": False, "error": str(e)}
