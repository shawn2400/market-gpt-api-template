# routes/grid.py
from fastapi import APIRouter
from pydantic import BaseModel
from utils.grid_utils import execute_grid

router = APIRouter()

class GridTradeRequest(BaseModel):
    symbol: str
    budget: float
    grid_count: int = 6
    grid_pct: float = 0.4
    leverage: int = 20
    futures: bool = True
    tp_pct: float = 1.5
    sl_pct: float = 1.0

@router.post("/grid/trade")
async def grid_trade(data: GridTradeRequest):
    try:
        orders = execute_grid(
            symbol=data.symbol,
            budget=data.budget,
            grid_count=data.grid_count,
            grid_pct=data.grid_pct,
            leverage=data.leverage,
            futures=data.futures,
            tp_pct=data.tp_pct,
            sl_pct=data.sl_pct
        )
        return {"status": "success", "orders": orders}
    except Exception as e:
        return {"status": "error", "message": str(e)}







