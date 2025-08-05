# routes/trade.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.trade_execution_core import execute_trade_live
from utils.ws_fallback import get_price
import time

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: str  # LONG / SHORT
    entry: float = None  # אם לא ניתן, יילקח מחיר שוק
    sl: float = None
    tp: float = None
    budget: float = 100
    leverage: float = 10

@router.post("/trade")
async def place_trade(req: TradeRequest):
    symbol = req.symbol.upper()

    # שלב 1: הבאת מחיר נוכחי
    price = req.entry or get_price(symbol, max_age_sec=10)
    if price is None:
        raise HTTPException(
            status_code=400,
            detail=f"❌ לא ניתן לקבל מחיר עדכני עבור {symbol} – טרייד לא בוצע"
        )

    # שלב 2: שליחת הטרייד בפועל עם הגנות נוספות מה-core
    trade_result = execute_trade_live(
        symbol=symbol,
        entry=price,
        stop=req.sl,
        tp=req.tp,
        direction=req.side,
        leverage=req.leverage,
        budget_usd=req.budget
    )

    if trade_result["status"] == "error":
        raise HTTPException(
            status_code=400,
            detail=trade_result.get("error", "שגיאה לא ידועה")
        )

    return {"status": "success", "trade": trade_result["result"]}













