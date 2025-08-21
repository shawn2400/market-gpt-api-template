# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os, requests, pandas as pd

from utils.backtest_utils import run_backtest

router = APIRouter(tags=["Backtest"])

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")


# ======================
# Binance helper
# ======================
def _fetch_klines(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "qv","nTrades","taker_base","taker_quote","x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]


# ======================
# Models
# ======================
class BacktestCandle(BaseModel):
    time: Optional[str] = None
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
    leverage: int
    final_balance: float


class StressInfo(BaseModel):
    max_drawdown_pct: Optional[float] = None
    max_win_pct: Optional[float] = None
    risk_reward_ratio: Optional[float] = None


class BacktestResult(BaseModel):
    ok: bool = True
    symbol: str
    strategy: str
    summary: BacktestSummary
    trades: List[Dict[str, Any]] = Field(default_factory=list)
    candles: List[BacktestCandle] = Field(default_factory=list)
    stress: Optional[StressInfo] = None


# ======================
# Endpoint
# ======================
@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = Query("ema_crossover", description="אסטרטגיה: ema_crossover | macd_crossover | bollinger"),
    interval: str = Query("1h", description="טיימפריים לטעינת הנרות"),
    limit: int = Query(500, ge=50, le=1000, description="כמות נרות לטעינה"),
    max_return: int = Query(200, ge=50, le=500, description="מספר מקסימלי של נרות שיוחזרו ללקוח"),
    leverage: int = Query(1, ge=1, le=100, description="מינוף להרצת הבק-טסט (מקסימום 100×)"),
    stress_mode: bool = Query(False, description="הפעלת Stress Mode (בדיקת Drawdown/Win קיצוניים)"),
):
    """
    מריץ Backtest (מוגבל ל־1000 נרות).
    מחזיר עד `max_return` נרות אחרונים + סיכום כולל.
    כולל תמיכה ב־Leverage וב־Stress Mode.
    """
    df = _fetch_klines(symbol, interval, limit)
    if df.empty:
        return BacktestResult(
            ok=False,
            symbol=symbol,
            strategy=strategy,
            summary=BacktestSummary(
                total_candles=0, returned_candles=0,
                trades=0, profit_pct=0.0, leverage=leverage, final_balance=0.0
            ),
            candles=[],
            trades=[],
            stress=None,
        )

    raw: Dict[str, Any] = run_backtest(
        df=df,
        strategy=strategy,
        initial_balance=1000.0,
        leverage=leverage,
        stress_mode=stress_mode,
    )

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
        leverage=int(raw.get("leverage", leverage)),
        final_balance=float(raw.get("final_balance", 0.0)),
    )

    stress_info = raw.get("stress") or None
    if stress_info:
        stress_info = StressInfo(**stress_info)

    return BacktestResult(
        ok=True,
        symbol=symbol,
        strategy=raw.get("strategy", strategy),
        summary=summary,
        trades=raw.get("trades", []),
        candles=candles,
        stress=stress_info,
    )















