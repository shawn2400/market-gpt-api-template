from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.trade_executor import execute_trade_live
from utils.ws_fallback import get_price  # ✅ WebSocket חכם למחיר חי

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
    try:
        price = req.entry or get_price(req.symbol)
        if not price:
            raise HTTPException(status_code=400, detail="❌ לא ניתן לקבל מחיר חי")
        trade_result = execute_trade_live(
            symbol=req.symbol,
            direction=req.side,
            entry=price,
            stop=req.sl,
            tp=req.tp,
            leverage=req.leverage,
            budget=req.budget
        )
        return {"status": "success", "trade": trade_result}
    except Exception as e:
        return {"status": "error", "message": str(e)}









