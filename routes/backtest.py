# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from utils.backtest_utils import run_backtest   # ✅ שם נכון (utils/backtest_utils.py)

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


class BacktestSummary(BaseModel):
    total_candles: int
    returned_candles: int
    trades: int
    profit_pct: float
    final_balance: float


class StressMetrics(BaseModel):
    max_drawdown_pct: float
    max_win_pct: float
    risk_reward_ratio: Optional[float] = None


class BacktestResult(BaseModel):
    ok: bool = True
    symbol: str
    strategy: str
    summary: BacktestSummary
    candles: List[BacktestCandle] = Field(default_factory=list)
    stress: Optional[StressMetrics] = None   # ✅ שדות סטטיסטיקה מתקדמים


# =====================
# Endpoint
# =====================
@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = "ema_crossover",
    limit: int = Query(500, ge=50, le=1000),  # ✅ מגבלה קשיחה
    max_return: int = Query(200, ge=50, le=500, description="מספר מקסימלי של נרות שיוחזרו ללקוח"),
    stress: bool = Query(False, description="החזרת נתוני Stress Metrics (max drawdown, risk/reward וכו')")
):
    """
    מריץ Backtest (מוגבל ל־1000 נרות). מחזיר עד `max_return` נרות אחרונים.
    אם `stress=true` יוחזרו גם נתוני Stress Metrics.
    """
    raw: Dict[str, Any] = run_backtest(symbol, strategy=strategy, initial_balance=1000.0)

    candles: List[BacktestCandle] = [BacktestCandle(**c) for c in raw.get("candles", [])]
    total = len(candles)

    # ✅ חותכים להחזרה רק X נרות אחרונים
    if total > max_return:
        candles = candles[-max_return:]

    summary = BacktestSummary(
        total_candles=total,
        returned_candles=len(candles),
        trades=int(raw.get("n_trades", 0)),
        profit_pct=float(raw.get("profit_pct", 0.0)),
        final_balance=float(raw.get("final_balance", 0.0)),
    )

    stress_out: Optional[StressMetrics] = None
    if stress and "stress" in raw:
        stress_out = StressMetrics(**raw["stress"])

    return BacktestResult(
        ok=True,
        symbol=raw.get("symbol", symbol),
        strategy=raw.get("strategy", strategy),
        summary=summary,
        candles=candles,
        stress=stress_out,
    )
















