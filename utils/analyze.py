# utils/analyze.py
from __future__ import annotations
from typing import Dict, Any
import requests
import os
import pandas as pd

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

def analyze_symbol(symbol: str, interval: str = "15m") -> Dict[str, Any]:
    """
    Core analysis: fetch klines, calculate indicators, return signals.
    """
    df = fetch_klines(symbol, interval=interval, limit=200)
    if df.empty:
        return {"ok": False, "reason": "no-data", "symbol": symbol}

    ind = prepare_indicators_for_backtest(df)
    if ind.empty:
        return {"ok": False, "reason": "no-indicators", "symbol": symbol}

    last = ind.iloc[-1].to_dict()
    out: Dict[str, Any] = {k: float(v) if isinstance(v, (int,float)) else v for k,v in last.items()}
    out.update({
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "close": float(df["close"].iloc[-1]),
    })
    return out





