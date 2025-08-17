from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from utils.auth import require_bearer_token
from utils.binance_trader import binance_futures_trade
from utils.ai_analysis import predict_optimal_sl_tp

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: str
    entry: float
    quantity: float

@router.post("/trade/live")
async def execute_trade(req: TradeRequest, auth: bool = Depends(require_bearer_token)):
    if req.side not in ["LONG", "SHORT"]:
        raise HTTPException(status_code=400, detail="Side must be LONG or SHORT")
    
    sl, tp = await predict_optimal_sl_tp(req.symbol, req.side, req.entry)
    
    result = await binance_futures_trade(
        symbol=req.symbol,
        side=req.side,
        entry=req.entry,
        quantity=req.quantity,
        sl=sl,
        tp=tp,
    )
    
    return {"status": "executed", "sl": sl, "tp": tp, "result": result}





