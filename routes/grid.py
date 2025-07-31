# ✅ routes/grid.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from utils.grid_utils import execute_grid

router = APIRouter(prefix="/grid", tags=["Grid"])

# משתנה גלובלי לשמירת סטטוס הגריד האחרון
last_grid_result = {}

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
    מבצע פקודות גריד עם SL/TP ל-Binance ומעדכן את סטטוס הגריד האחרון.
    """
    global last_grid_result
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
        last_grid_result = result
        return {"status": "success", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"\u05e9\u05d2\u05d9\u05d0\u05d4 \u05d1\u05d4\u05e8\u05e6\u05ea \u05d2\u05e8\u05d9\u05d3: {e}")

@router.get("/status")
def grid_status():
    """
    מחזיר את הסטטוס האחרון של הגריד שבוצע.
    """
    if not last_grid_result:
        raise HTTPException(status_code=404, detail="\u05dc\u05d0 \u05d1\u05d5\u05e6\u05e2 \u05d2\u05e8\u05d9\u05d3 \u05e2\u05d3\u05d9\u05df")
    return last_grid_result


