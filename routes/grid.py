# routes/grid.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from utils.grid_utils import execute_grid

router = APIRouter(prefix="/grid", tags=["Grid Trading"])

class GridTradeRequest(BaseModel):
    symbol: str = Field(..., example="ETHUSDT")
    budget: float = Field(..., gt=0, example=100)
    grid_count: int = Field(ge=2, le=20, default=6, example=6)
    grid_pct: float = Field(ge=0.1, le=5.0, default=0.5, example=0.5)
    leverage_min: int = Field(default=10, example=10)
    leverage_max: int = Field(default=35, example=25)
    direction: Literal["BOTH", "BUY", "SELL"] = "BOTH"
    tp_pct: float = Field(ge=0.1, le=10.0, default=1.0, example=1.0)
    sl_pct: float = Field(ge=0.1, le=10.0, default=1.0, example=1.0)
    futures: bool = Field(default=True)

@router.post("/trade")
def grid_trade(req: GridTradeRequest):
    """
    מבצע פקודות Grid ל־Binance Futures/Spot עם SL/TP לפי תקציב, כמות רמות ומינוף.
    """
    try:
        result = execute_grid(
            symbol=req.symbol,
            budget=req.budget,
            grid_count=req.grid_count,
            grid_pct=req.grid_pct,
            leverage_min=req.leverage_min,
            leverage_max=req.leverage_max,
            futures=req.futures,
            direction=req.direction,
            tp_pct=req.tp_pct,
            sl_pct=req.sl_pct
        )
        return {"status": "success", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"שגיאה בהרצת גריד: {e}")
