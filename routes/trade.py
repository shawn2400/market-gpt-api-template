# routes/trade.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.trade_executor import execute_trade_live
from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.ws_fallback import get_price  # ✅ במקום get_live_price

router = APIRouter(tags=["Trades"])

# --- מודלים ---
class TradeRequest(BaseModel):
    symbol: str
    entry: float
    stop: float = None
    tp: float = None
    direction: str  # LONG or SHORT
    leverage: float = 20
    budget: float = 100
    use_grid: bool = False
    use_trailing: bool = False
    user_id: str = "manual"

class QuantityRequest(BaseModel):
    symbol: str
    price: float
    leverage: float
    budget: float

class SLTPRequest(BaseModel):
    direction: str
    entry: float

# --- ביצוע טרייד ---
@router.post("/execute-trade")
def execute_trade(req: TradeRequest):
    result = execute_trade_live(
        symbol=req.symbol,
        entry=req.entry,
        stop=req.stop,
        tp=req.tp,
        direction=req.direction,
        leverage=req.leverage,
        budget_usd=req.budget,
        use_grid=req.use_grid,
        use_trailing=req.use_trailing,
        user_id=req.user_id,
        take_snapshot=True
    )
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

# --- חישוב כמות ---
@router.post("/calculate-quantity")
def calculate_quantity_route(req: QuantityRequest):
    try:
        qty = calculate_quantity(req.symbol, req.price, req.leverage, req.budget)
        return {"quantity": qty}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- מחיר חי (WebSocket או REST fallback) ---
@router.get("/price/{symbol}")
def get_price_route(symbol: str):
    price = get_price(symbol)
    if not price:
        raise HTTPException(status_code=404, detail="מחיר לא נמצא")
    return {"symbol": symbol, "price": price}

# --- חישוב SL/TP ---
@router.post("/sl_tp")
def calculate_sl_tp_route(req: SLTPRequest):
    try:
        return calculate_sl_tp(req.entry, req.direction)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))








