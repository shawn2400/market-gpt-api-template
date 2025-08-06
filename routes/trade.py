# routes/trade.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.trade_executor import execute_trade_live
from utils.ws_fallback import get_price

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: str  # LONG / SHORT
    entry: float = None  # אם לא ניתן – יילקח מחיר שוק
    sl: float = None
    tp: float = None
    budget: float = 100
    leverage: float = 10

@router.post("/trade")
async def place_trade(req: TradeRequest):
    symbol = req.symbol.upper()

    # שלב 1: מחיר עדכני (אם לא ניתן)
    price = req.entry or get_price(symbol, max_age_sec=10)
    if price is None:
        raise HTTPException(
            status_code=400,
            detail=f"❌ לא ניתן לקבל מחיר עדכני עבור {symbol} – טרייד לא בוצע"
        )

    # שלב 2: שליחת הטרייד בפועל – await ישיר
    trade_result = await execute_trade_live(
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

















