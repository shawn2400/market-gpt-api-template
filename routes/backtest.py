# routes/backtest.py
from __future__ import annotations
import os, json, uuid
from pathlib import Path
from typing import Optional, Dict, Any

import requests
import pandas as pd
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict

from utils.auth import require_api_key
from utils.backtest_utils import run_backtest

router = APIRouter(
    prefix="/backtest",
    tags=["Backtest"],
    dependencies=[Depends(require_api_key)],
)

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ============== Helpers ==============
def fetch_klines(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    try:
        url = f"{FUTURES_BASE}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
        r.raise_for_status()
        arr = r.json()
    except Exception as e:
        raise HTTPException(502, f"failed to fetch klines: {e}")

    cols = ["open_time","open","high","low","close","volume","close_time",
            "qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms").dt.strftime("%Y-%m-%d %H:%M:%S")
    return df[["time","open","high","low","close","volume"]]

def _run(symbol: str, strategy: str, interval: str, limit: int, stress: bool) -> Dict[str, Any]:
    df = fetch_klines(symbol, interval, limit)
    raw: Dict[str, Any] = run_backtest(df, strategy=strategy, initial_balance=1000.0)

    # כתיבת קובץ נרות לפורטלים/דיבוג
    file_id = uuid.uuid4().hex[:8]
    fname = f"backtest_{symbol}_{file_id}.json"
    fpath = CACHE_DIR / fname
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f)

    summary = {
        "total_candles": len(df),
        "trades": int(raw.get("n_trades", 0)),
        "profit_pct": float(raw.get("profit_pct", 0.0)),
        "final_balance": float(raw.get("final_balance", 0.0)),
    }

    out: Dict[str, Any] = {
        "ok": True,
        "symbol": symbol,
        "strategy": strategy,
        "summary": summary,
        "candles_url": f"/static/cache/{fname}",
    }
    if stress and "stress" in raw:
        out["stress"] = raw["stress"]
    return out

# ============== Models ==============
class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol: str = Field(..., examples=["BTCUSDT"])
    strategy: str = Field("ema_crossover")
    interval: str = Field("1h")
    limit: int = Field(500, ge=50, le=1000)
    stress: bool = Field(False, description="החזרת נתוני Stress Metrics")
    # שדה 'mode' נצרך בסמוק — נאפשר ומתעלמים ממנו
    mode: Optional[str] = Field(None, description="ignored")

# ============== Endpoints ==============
@router.get("")
async def backtest_get(
    symbol: str,
    strategy: str = Query("ema_crossover"),
    interval: str = Query("1h"),
    limit: int = Query(500, ge=50, le=1000),
    stress: bool = Query(False),
) -> Dict[str, Any]:
    """GET קומפקטי (פרמטרים בשורת כתובת)"""
    return _run(symbol, strategy, interval, limit, stress)

@router.post("")
async def backtest_post(req: BacktestRequest) -> Dict[str, Any]:
    """POST גוף JSON (תואם לסמוק שלך)"""
    return _run(req.symbol, req.strategy, req.interval, req.limit, req.stress)
















