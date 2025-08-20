# utils/analyze.py
from __future__ import annotations
import pandas as pd
import numpy as np
import requests
import os
import logging
from typing import Dict, Any

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    """Fetch recent kline (candlestick) data from Binance Futures REST API."""
    try:
        url = f"{FUTURES_BASE}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        r.raise_for_status()
        arr = r.json()
        if not arr:
            return pd.DataFrame()
        cols = [
            "open_time","open","high","low","close","volume","close_time",
            "qv","nTrades","taker_base","taker_quote","ignore"
        ]
        df = pd.DataFrame(arr, columns=cols)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        logging.warning(f"[analyze._fetch_klines] {e}")
        return pd.DataFrame()

def _calc_rsi(series: pd.Series, period: int = 14) -> float | None:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else None

def _calc_adx(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period * 2:
        return None
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = low.diff().abs()
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(period).mean()
    return float(adx.iloc[-1]) if not adx.empty else None

def _calc_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period + 1:
        return None
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1]) if not atr.empty else None

def analyze_symbol(symbol: str, interval: str = "15m", limit: int = 200) -> Dict[str, Any]:
    """Perform a basic TA scan on the given symbol."""
    df = _fetch_klines(symbol, interval, limit)
    if df.empty:
        return {"ok": False, "reason": "no data"}

    close = df["close"]
    rsi = _calc_rsi(close)
    adx = _calc_adx(df)
    atr = _calc_atr(df)
    volume = float(df["volume"].iloc[-1]) if not df.empty else None
    trend = "UP" if rsi and rsi > 55 else ("DOWN" if rsi and rsi < 45 else "SIDE")

    signal = None
    if rsi and rsi < 30:
        signal = "LONG"
    elif rsi and rsi > 70:
        signal = "SHORT"

    return {
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "rsi": rsi,
        "adx": adx,
        "atr": atr,
        "volume": volume,
        "trend": trend,
        "signal": signal,
        "quality_score": 7 if signal else 5,
        "confidence": 0.7 if signal else 0.4,
        "close": float(close.iloc[-1]) if not df.empty else None,
    }





































