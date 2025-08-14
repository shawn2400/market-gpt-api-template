# routes/grid.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from utils.grid_utils import execute_grid_trade

router = APIRouter(prefix="/grid", tags=["Grid"])

class GridTradeRequest(BaseModel):
    symbol: str = Field(..., description="למשל BTCUSDT")
    budget: float = Field(..., gt=0, description="תקציב כולל ב-USDT")
    grid_count: int = Field(6, ge=2, le=50, description="מספר רמות רשת (>=2)")
    grid_pct: float = Field(0.4, gt=0, le=5, description="אחוז הפרדה בין רמות (למשל 0.4 = 0.4%)")
    leverage: int = Field(20, ge=1, le=125, description="מינוף (רק ל-Futures)")
    futures: bool = Field(True, description="True=Futures, False=Spot")
    tp_pct: float = Field(1.5, gt=0, le=10, description="TP אחוזי לכל רמה")
    sl_pct: float = Field(1.0, gt=0, le=10, description="SL אחוזי לכל רמה")

@router.post("/trade")
async def grid_trade(req: GridTradeRequest):
    """
    פתיחת גריד (Spot/Futures) לפי הפרמטרים שנשלחו.
    אם פעולות כתיבה מושבתות — תקבל DRY plan מפורט (נוח לבדיקה).
    """
    try:
        res = await execute_grid_trade(
            symbol=req.symbol,
            budget_usd=req.budget,
            grid_count=req.grid_count,
            grid_pct=req.grid_pct,
            leverage=req.leverage,
            futures=req.futures,
            tp_pct=req.tp_pct,
            sl_pct=req.sl_pct,
        )
        if res.get("status") in ("success", "dry_run"):
            return res
        raise HTTPException(status_code=400, detail=res.get("error", "grid trade failed"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))








