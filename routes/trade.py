from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from utils.auth import require_bearer_token
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price

router = APIRouter(
    dependencies=[Depends(require_bearer_token)]
)

# --- מודלים ---

class TradeRequest(BaseModel):
    symbol: str
    direction: str  # LONG / SHORT
    budget: float   # USDT להשקעה

class SLTPRequest(BaseModel):
    symbol: str
    direction: str
    entry: float


# --- ENDPOINTS ---

@router.post("/execute")
async def execute_trade(data: TradeRequest):
    """
    מבצע טרייד בפועל לפי הנתונים שנשלחו
    """
    try:
        result = await execute_trade_live(
            symbol=data.symbol,
            direction=data.direction.upper(),
            budget=data.budget
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trade execution failed: {str(e)}")


@router.get("/price")
async def get_symbol_price(symbol: str):
    """
    מחזיר מחיר חי מסביבת Binance (WebSocket עם fallback)
    """
    try:
        price = await get_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Price fetch failed: {str(e)}")


@router.post("/sltp")
async def get_sltp(data: SLTPRequest):
    """
    מחשב SL/TP אופטימליים לפי AI (או fallback)
    """
    try:
        sl, tp = await predict_optimal_sl_tp(data.symbol, data.direction, data.entry)
        return {
            "symbol": data.symbol,
            "direction": data.direction,
            "entry": data.entry,
            "sl": sl,
            "tp": tp
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SL/TP prediction failed: {str(e)}")







