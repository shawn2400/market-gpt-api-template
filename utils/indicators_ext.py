# utils/indicators_ext.py
from __future__ import annotations
from typing import Dict, Any, Optional
import os, math
import pandas as pd
import numpy as np

# Utilities that may be reused by indicators implementations

def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return math.nan

def compute_vwap(df: pd.DataFrame) -> float:
    tp = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    vol = pd.to_numeric(df["volume"], errors="coerce")
    vwap = (tp * vol).sum() / max(1e-12, float(vol.sum()))
    return float(vwap)

def compute_obv(df: pd.DataFrame) -> float:
    close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float, copy=False)
    vol   = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=float, copy=False)
    obv = 0.0
    for i in range(1, len(close)):
        if close[i] > close[i-1]: obv += vol[i]
        elif close[i] < close[i-1]: obv -= vol[i]
    return float(obv)

# Optional dev-only CVD fallback (disabled in prod)
# NOTE: NO network by default; indicators must rely on **feeds for orderflow.
def compute_cvd_from_trades_dev(symbol: str, limit: int = 1000) -> Optional[float]:
    if os.getenv("ALLOW_HTTP_IN_INDICATORS", "0") != "1":
        return None
    # Dev helper: best-effort (blocking) fallback; not for production
    import httpx
    base = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
    symbol = symbol.upper().strip()
    with httpx.Client(timeout=6.0) as c:
        r = c.get(f"{base}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": max(1, min(1000, limit))})
        r.raise_for_status()
        trades = r.json()
    cvd = 0.0
    for t in trades:
        q = _safe_float(t.get("q"))
        cvd += (-q if t.get("m") else q)
    return float(cvd)










