# routes/indicators.py
from __future__ import annotations
from typing import Dict, Any
import os
import requests
import pandas as pd
from fastapi import APIRouter, Query, Path

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

router = APIRouter(tags=["Indicators"])

def _fetch_klines(symbol: str, interval: str = "1h", limit: int = 180) -> pd.DataFrame:
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

@router.get("/indicators", operation_id="getIndicatorsSample")
async def get_indicators_sample() -> Dict[str, Any]:
    return {
        "ok": True,
        "sample": {
            "rsi": 55.2,
            "ema_21": 123.45,
            "adx": 18.7,
            "atr": 2.3,
            "vwap_trend": True,
        },
    }

@router.get("/indicators/{symbol}", operation_id="getIndicatorsSymbol")
async def get_indicators_symbol(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    timeframe: str = Query("1h"),
    limit: int = Query(180, ge=50, le=1500),
) -> Dict[str, Any]:
    try:
        df = _fetch_klines(symbol, timeframe, limit)
        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            return {"ok": False, "note": "no data"}
        row = ind.iloc[-1].to_dict()
        # המרה ל-float/bool פשוטים למניעת בעיות сериалיזציה
        out: Dict[str, Any] = {k: (float(v) if isinstance(v, (int,float)) else (bool(v) if isinstance(v, (bool,)) else v))
                               for k,v in row.items()}
        out["ok"] = True
        out["symbol"] = symbol
        out["timeframe"] = timeframe
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}








