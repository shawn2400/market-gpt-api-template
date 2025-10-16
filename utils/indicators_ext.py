# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import os
import math

import pandas as pd  # type: ignore

def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return math.nan


def compute_vwap(df: pd.DataFrame) -> float:
    """
    מצפה לעמודות: high, low, close, volume.
    """
    tp = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    vol = pd.to_numeric(df["volume"], errors="coerce")
    denom = float(vol.sum()) if float(vol.sum()) != 0.0 else 1e-12
    vwap = (tp * vol).sum() / denom
    return float(vwap)


def compute_obv(df: pd.DataFrame) -> float:
    """
    On-Balance Volume בסיסי על close/volume.
    """
    close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float, copy=False)
    vol   = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=float, copy=False)
    obv = 0.0
    for i in range(1, len(close)):
        if close[i] > close[i-1]:
            obv += vol[i]
        elif close[i] < close[i-1]:
            obv -= vol[i]
    return float(obv)


def compute_cvd_from_trades_dev(symbol: str, limit: int = 1000) -> Optional[float]:
    """
    Dev-only: CVD מאגרגציות־טריידים של Binance (חסום כברירת־מחדל).
    דורש ALLOW_HTTP_IN_INDICATORS=1. לא לשימוש בפרודקשן חם.
    """
    if os.getenv("ALLOW_HTTP_IN_INDICATORS", "0") != "1":
        return None

    import httpx  # type: ignore
    base = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
    symbol = symbol.upper().strip()

    with httpx.Client(timeout=6.0) as c:
        r = c.get(f"{base}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": max(1, min(1000, limit))})
        r.raise_for_status()
        trades = r.json()

    cvd = 0.0
    for t in trades:
        q = _safe_float(t.get("q"))
        # maker=true => מכירה (לחץ שלילי), אחרת קנייה
        cvd += (-q if t.get("m") else q)
    return float(cvd)


__all__ = ["compute_vwap", "compute_obv", "compute_cvd_from_trades_dev"]







