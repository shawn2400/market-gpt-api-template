# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from utils.backtest_utils import run_backtest
from utils.indicators import prepare_indicators_for_backtest
import requests
import pandas as pd
import os

router = APIRouter(tags=["Backtest"])

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "qv","nTrades","taker_base","taker_quote","x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]


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
    stress: Optional[StressMetrics] = None   # ✅ שדות סטטיסטיקה מתקדמים


# =====================
# Endpoint
# =====================
@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = "ema_crossover",
    interval: str = Query("1h"),
    limit: int = Query(500, ge=50, le=1000),
    stress: bool = Query(False, description="החזרת נתוני Stress Metrics (max drawdown, risk/reward וכו')")
):
    """
    מריץ Backtest (מוגבל ל־1000 נרות).
    """
    df = fetch_klines(symbol, interval, limit)
    raw: Dict[str, Any] = run_backtest(df, strategy=strategy, initial_balance=1000.0)

    summary = BacktestSummary(
        total_candles=len(df),
        returned_candles=len(df),
        trades=int(raw.get("n_trades", 0)),
        profit_pct=float(raw.get("profit_pct", 0.0)),
        final_balance=float(raw.get("final_balance", 0.0)),
    )

    stress_out: Optional[StressMetrics] = None
    if stress and "stress" in raw:
        stress_out = StressMetrics(**raw["stress"])

    return BacktestResult(
        ok=True,
        symbol=symbol,
        strategy=strategy,
        summary=summary,
        stress=stress_out,
    )
















