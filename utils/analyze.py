# utils/analyze.py
"""
Analyzer module for AlgoGPT.
משתמש ב-Binance klines + utils.indicators כדי לחשב אינדיקטורים אמיתיים.
"""

import os
import requests
import pandas as pd
from typing import Dict, Any
from utils.indicators import prepare_indicators_for_backtest

# Binance Futures REST
FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    """
    מביא נתוני נרות (klines) מ-Binance וממיר ל-DataFrame.
    """
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
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

def analyze_symbol(symbol: str, market: str = "futures", interval: str = "15m", limit: int = 200) -> Dict[str, Any]:
    """
    מבצע ניתוח טכני על סימבול נתון ומחזיר dict עם אינדיקטורים.
    """
    try:
        df = _fetch_klines(symbol, interval, limit)
        if df.empty:
            return {"symbol": symbol, "market": market, "interval": interval, "error": "no data"}

        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            return {"symbol": symbol, "market": market, "interval": interval, "error": "indicator calc failed"}

        row = ind.iloc[-1].to_dict()

        # החזרת ערכים נקיים (float/bool)
        out: Dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, (int, float)):
                out[k] = float(v)
            elif isinstance(v, (bool,)):
                out[k] = bool(v)
            else:
                out[k] = v

        out.update({
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "close": float(df["close"].iloc[-1]),
        })

        return out
    except Exception as e:
        return {"symbol": symbol, "market": market, "interval": interval, "error": str(e)}


