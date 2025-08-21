# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from utils.backtest_utils import run_backtest

router = APIRouter(tags=["Backtest"])


# =====================
# Models
# =====================
class BacktestCandle(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class StressInfo(BaseModel):
    max_drawdown_pct: Optional[float] = None
    max_win_pct: Optional[float] = None
    risk_reward_ratio: Optional[float] = None


class BacktestSummary(BaseModel):
    total_candles: int
    returned_candles: int
    trades: int
    profit_pct: float
    leverage: int
    stress: Optional[StressInfo] = None


class BacktestResult(BaseModel):
    ok: bool = True
    symbol: str
    strategy: str
    summary: BacktestSummary
    candles: List[BacktestCandle] = Field(default_factory=list)


# =====================
# Endpoint
# =====================
@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = Query("ema_crossover"),
    limit: int = Query(500, ge=50, le=1000, description="מספר נרות מקסימלי לטעינה"),
    max_return: int = Query(200, ge=50, le=500, description="מספר מקסימלי של נרות שיוחזרו ללקוח"),
    leverage: int = Query(1, ge=1, le=50, description="מינוף לחישוב ה־PnL"),
    stress: bool = Query(False, description="הפעלת Stress Mode לחישוב Drawdown וכו'"),
):
    """
    מריץ Backtest (מוגבל ל־1000 נרות).  
    מחזיר עד `max_return` נרות אחרונים + נתוני Stress Mode אם הופעל.
    """
    raw: Dict[str, Any] = run_backtest(
        df=None,  # ⚠️ צריך להביא DF מחוץ לפונקציה – כאן נניח ש-run_backtest יודע למשוך
        strategy=strategy,
        initial_balance=1000.0,
        leverage=leverage,
        stress_mode=stress,
    )

    candles: List[BacktestCandle] = [BacktestCandle(**c) for c in raw.get("candles", [])]
    total = len(candles)

    if total > max_return:
        candles = candles[-max_return:]

    summary = BacktestSummary(
        total_candles=total,
        returned_candles=len(candles),
        trades=int(raw.get("n_trades", 0)),
        profit_pct=float(raw.get("profit_pct", 0.0)),
        leverage=int(raw.get("leverage", leverage)),
        stress=StressInfo(**raw["stress"]) if stress and raw.get("stress") else None,
    )

    return BacktestResult(
        ok=True,
        symbol=raw.get("symbol", symbol),
        strategy=raw.get("strategy", strategy),
        summary=summary,
        candles=candles,
    )



  















