# utils/indicators_ext.py
from __future__ import annotations
from typing import Dict, Any, Optional
import pandas as pd
import httpx
import math, os

from utils.get_klines import get_klines as _get_klines_sync

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

def _safe_float(x) -> float:
    try: return float(x)
    except Exception: return math.nan

def compute_vwap(df: pd.DataFrame) -> float:
    # Typical price = (H+L+C)/3
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vwap = (tp * df["volume"]).sum() / max(1e-12, df["volume"].sum())
    return float(vwap)

def compute_obv(df: pd.DataFrame) -> float:
    close = df["close"].values
    vol = df["volume"].values
    obv = 0.0
    for i in range(1, len(close)):
        if close[i] > close[i-1]: obv += vol[i]
        elif close[i] < close[i-1]: obv -= vol[i]
    return float(obv)

def compute_cvd_from_trades(symbol: str, limit: int = 1000) -> float:
    # aggTrades: m == isBuyerMaker (True -> SELL aggression), False -> BUY aggression
    symbol = symbol.upper().strip()
    with httpx.Client(timeout=6.0) as c:
        r = c.get(f"{_FAPI}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": max(1, min(1000, limit))})
        r.raise_for_status()
        trades = r.json()
    cvd = 0.0
    for t in trades:
        q = _safe_float(t.get("q"))
        if t.get("m"):  # SELL
            cvd -= q
        else:           # BUY
            cvd += q
    return float(cvd)

def advanced_indicators(symbol: str, interval: str = "15m", limit: int = 200, market: str = "futures", with_cvd: bool = False) -> Dict[str, Any]:
    df = _get_klines_sync(symbol, interval=interval, limit=max(50, min(1500, int(limit))), market_type=market)
    if df is None or len(df) < 10:
        return {"ok": False, "error": "klines_unavailable", "symbol": symbol.upper(), "interval": interval}
    vwap = compute_vwap(df)
    obv = compute_obv(df)
    out = {"ok": True, "symbol": symbol.upper(), "interval": interval, "limit": limit, "vwap": vwap, "obv": obv}
    if with_cvd:
        try:
            out["cvd"] = compute_cvd_from_trades(symbol)
        except Exception as e:
            out["cvd_error"] = str(e)
    return out









