# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from utils.backtest_utils import run_backtest
import requests, pandas as pd, os, json, uuid, asyncio, time
from pathlib import Path

router = APIRouter(tags=["Backtest"])

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


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
    df["time"] = pd.to_datetime(df["open_time"], unit="ms").dt.strftime("%Y-%m-%d %H:%M:%S")
    return df[["time","open","high","low","close","volume"]]


# =====================
# Models
# =====================
class BacktestSummary(BaseModel):
    total_candles: int
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
    stress: Optional[StressMetrics] = None
    candles_url: Optional[str] = None


# =====================
# Cache Cleaner
# =====================
async def cache_cleaner(interval: int = 3600, max_files: int = 100, max_age: int = 86400):
    """
    מנקה קבצי cache ישנים כל X שניות:
    - מוחק קבצים מעל max_files (שומר רק אחרונים)
    - מוחק קבצים ישנים מ־max_age (ברירת מחדל 24 שעות)
    """
    while True:
        try:
            files = sorted(CACHE_DIR.glob("backtest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            now = time.time()

            # מוחק קבצים ישנים מדי
            for f in files:
                if now - f.stat().st_mtime > max_age:
                    f.unlink(missing_ok=True)

            # שומר רק max_files
            for f in files[max_files:]:
                f.unlink(missing_ok=True)

        except Exception as e:
            print(f"[CacheCleaner] Error: {e}")

        await asyncio.sleep(interval)


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
    מריץ Backtest ומחזיר סיכום + לינק להורדת הנרות כקובץ JSON.
    """
    df = fetch_klines(symbol, interval, limit)
    raw: Dict[str, Any] = run_backtest(df, strategy=strategy, initial_balance=1000.0)

    # ✅ שמירה לקובץ JSON ב־static/cache
    file_id = uuid.uuid4().hex[:8]
    fname = f"backtest_{symbol}_{file_id}.json"
    fpath = CACHE_DIR / fname
    candles_out = df.to_dict(orient="records")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(candles_out, f)

    summary = BacktestSummary(
        total_candles=len(df),
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
        candles_url=f"/static/cache/{fname}"
    )
















