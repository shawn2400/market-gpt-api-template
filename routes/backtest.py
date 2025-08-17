# routes/backtest.py
from __future__ import annotations

from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_bearer_token
from utils.backtest_utils import run_basic_backtest  # נדרש שתהיה לך פונקציה כזו

router = APIRouter()

TimeframeLiteral = Literal["5m", "15m", "1h", "4h"]

class BacktestRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    timeframe: TimeframeLiteral = "15m"
    limit: int = 200
    slippage_pct: float = 0.1

class BacktestTrade(BaseModel):
    timestamp: int
    price: float
    side: Literal["LONG", "SHORT"]
    pnl: float

class BacktestResult(BaseModel):
    symbol: str
    timeframe: str
    trades: list[BacktestTrade]
    win_rate: float
    total_pnl: float
    count: int

@router.post(
    "/backtest",
    tags=["Backtest"],
    operation_id="postBacktestRun",
    dependencies=[Depends(require_bearer_token)],
    response_model=BacktestResult,
)
async def backtest(req: BacktestRequest):
    try:
        result = await run_basic_backtest(
            symbol=req.symbol,
            timeframe=req.timeframe,
            limit=req.limit,
            slippage_pct=req.slippage_pct,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"backtest failed: {e}")







