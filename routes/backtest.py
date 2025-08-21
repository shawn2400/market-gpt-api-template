# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List
from utils.backtest_engine import run_backtest

router = APIRouter()

class BacktestCandle(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

class BacktestResult(BaseModel):
    symbol: str
    strategy: str
    trades: int
    profit_pct: float
    candles: List[BacktestCandle]

@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = "ema_cross",
    limit: int = Query(500, ge=50, le=2000)
):
    """
    מריץ Backtest מוגבל עד 2000 נרות.
    """
    result = run_backtest(symbol, strategy=strategy, limit=limit)
    return BacktestResult(**result)












