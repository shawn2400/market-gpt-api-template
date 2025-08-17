# routes/backtest.py

from fastapi import APIRouter, Query
from typing import Optional, List
from pydantic import BaseModel
from utils.backtest_utils import run_backtest

router = APIRouter()

class BacktestResult(BaseModel):
    timestamp: int
    price: float
    score: float
    rsi: Optional[float]
    adx: Optional[float]
    trend: Optional[str]
    pattern: Optional[str]

@router.get("/backtest", response_model=List[BacktestResult])
async def backtest(
    symbol: str = Query(..., example="BTCUSDT"),
    interval: str = Query("15m", example="15m"),
    limit: int = Query(200, ge=100, le=1000),
):
    result = run_backtest(symbol=symbol, interval=interval, limit=limit)
    return result or []
