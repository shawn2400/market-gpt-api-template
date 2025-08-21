# utils/data_fetcher.py
from __future__ import annotations
import os
import requests
import pandas as pd

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def fetch_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 500
) -> pd.DataFrame:
    """
    מושך Klines מ-Binance ומחזיר DataFrame מוכן ל-backtest.
    כולל עמודות: open, high, low, close, volume
    """
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(
        url,
        params={"symbol": symbol.upper(), "interval": interval, "limit": int(limit)},
        timeout=10
    )
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qv", "nTrades", "taker_base", "taker_quote", "x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])

    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df[["open", "high", "low", "close", "volume"]]
