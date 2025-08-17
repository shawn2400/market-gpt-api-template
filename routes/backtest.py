# routes/backtest.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

from utils.auth import require_bearer_token

router = APIRouter()

Side = Literal["LONG", "SHORT"]

class BacktestTrade(BaseModel):
    timestamp: int
    price: float
    side: Side
    pnl: float

class BacktestResult(BaseModel):
    symbol: str
    timeframe: str
    trades: List[BacktestTrade]
    win_rate: float
    total_pnl: float
    count: int

class BacktestRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    timeframe: str = Field("15m", pattern="^(5m|15m|1h|4h)$")
    limit: int = 200
    slippage_pct: float = 0.1

@router.post(
    "/backtest",
    operation_id="postBacktestRun",
    response_model=BacktestResult,
    dependencies=[Depends(require_bearer_token)],
)
async def run_backtest(payload: BacktestRequest):
    # דמו מינימלי; חבר לסורק האמיתי שלך אם תרצה
    trades = [
        BacktestTrade(timestamp=1723800000, price=65000, side="LONG", pnl=12.5),
        BacktestTrade(timestamp=1723800900, price=65120, side="SHORT", pnl=-4.1),
    ]
    wins = sum(1 for t in trades if t.pnl > 0)
    total = sum(t.pnl for t in trades)
    return BacktestResult(
        symbol=payload.symbol.upper(),
        timeframe=payload.timeframe,
        trades=trades,
        win_rate=(wins / len(trades) * 100.0),
        total_pnl=total,
        count=len(trades),
    )








