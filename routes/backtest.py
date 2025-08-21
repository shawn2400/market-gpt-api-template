# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from utils.backtest_engine import run_backtest

router = APIRouter(tags=["Backtest"])

class BacktestCandle(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

class BacktestSummary(BaseModel):
    total_candles: int
    returned_candles: int
    trades: int
    profit_pct: float

class BacktestResult(BaseModel):
    ok: bool = True
    symbol: str
    strategy: str
    summary: BacktestSummary
    candles: List[BacktestCandle] = Field(default_factory=list)

@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = "ema_cross",
    limit: int = Query(500, ge=50, le=1000),  # ✅ מגבלה קשיחה
    max_return: int = Query(200, ge=50, le=500, description="מספר מקסימלי של נרות שיוחזרו ללקוח")
):
    """
    מריץ Backtest (מוגבל ל־1000 נרות). מחזיר עד `max_return` נרות אחרונים.
    """
    raw: Dict[str, Any] = run_backtest(symbol, strategy=strategy, limit=limit)

    candles: List[BacktestCandle] = [BacktestCandle(**c) for c in raw.get("candles", [])]
    total = len(candles)

    # ✅ חותכים להחזרה רק X נרות אחרונים
    if total > max_return:
        candles = candles[-max_return:]

    summary = BacktestSummary(
        total_candles=total,
        returned_candles=len(candles),
        trades=int(raw.get("trades", 0)),
        profit_pct=float(raw.get("profit_pct", 0.0)),
    )

    return BacktestResult(
        ok=True,
        symbol=raw.get("symbol", symbol),
        strategy=raw.get("strategy", strategy),
        summary=summary,
        candles=candles,
    )













