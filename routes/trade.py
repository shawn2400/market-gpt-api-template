# routes/trade.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.trade_executor import execute_trade_live  # ✅ גרסה רשמית שלך
from utils.ws_fallback import get_price  # ✅ לשליפת מחיר חי

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: str  # LONG / SHORT
    entry: float = None  # אם לא ניתן – יילקח מחיר שוק
    sl: float = None
    tp: float = None
    budget: float = 100
    leverage: int = 10

@router.post("/trade")
async def place_trade(req: TradeRequest):
    symbol = req.symbol.upper()

    # אם לא סופק מחיר כניסה – נשלוף מה־WebSocket
    price = req.entry or await get_price(symbol)
    if price is None:
        raise HTTPException(
            status_code=400,
            detail=f"❌ לא ניתן לקבל מחיר עדכני עבור {symbol} – טרייד לא בוצע"
        )

    # ביצוע טרייד חי בפועל
    trade_result = await execute_trade_live(
        symbol=symbol,
        entry=price,
        stop=req.sl,
        tp=req.tp,
        direction=req.side,
        leverage=req.leverage,
        budget_usd=req.budget
    )

    if trade_result.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=trade_result.get("error", "שגיאה לא ידועה")
        )

    return {"status": "success", "trade": trade_result["result"]}
