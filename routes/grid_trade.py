# routes/grid_trade.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from utils.auth import require_api_key
from utils.grid_executor import execute_grid_trade

logger = logging.getLogger("algogpt.routes.grid_trade")

router = APIRouter(
    prefix="/trade",
    tags=["Trade"],
    dependencies=[Depends(require_api_key)],
)

class GridTradeRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., regex="^(LONG|SHORT|BUY|SELL)$", example="LONG")
    budget: float = Field(..., gt=0, example=100)
    leverage: int = Field(10, ge=1, le=125, example=10)
    grids: int = Field(3, ge=1, le=20, example=3)
    dry_run: bool = Field(True, description="אם True → לא מציב הזמנות אמיתיות")

class GridTradeResponse(BaseModel):
    ok: bool
    mode: str
    symbol: str
    side: str
    base_price: Optional[float]
    budget: float
    leverage: int
    levels: Optional[list[float]] = None
    allocations: Optional[list[float]] = None
    orders: Optional[list[Dict[str, Any]]] = None
    manager: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@router.post("/grid", response_model=GridTradeResponse)
async def trade_grid(req: GridTradeRequest):
    """
    🔹 מפעיל Grid Trade עבור סימבול נתון.
    כולל יצירת פקודות Limit לפי תוכנית גריד,
    והצמדת SL/TP חכמה באמצעות grid_manager.
    """
    try:
        result = await execute_grid_trade(
            symbol=req.symbol,
            side=req.side,
            budget=req.budget,
            leverage=req.leverage,
            grids=req.grids,
            dry_run=req.dry_run,
        )
        return result
    except Exception as e:
        logger.exception("grid_trade_failed")
        raise HTTPException(status_code=500, detail=f"Grid trade failed: {e}")
