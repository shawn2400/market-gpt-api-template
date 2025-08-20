# utils/correlation.py
from __future__ import annotations
import os, math
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
import requests

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 correlation",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

def _klines(symbol: str, interval: str, limit: int = 500) -> Optional[pd.Series]:
    try:
        url = f"{FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
        r = _S.get(url, timeout=8)
        if r.status_code != 200:
            return None
        arr = r.json()
        df = pd.DataFrame(arr, columns=[
            "openTime","open","high","low","close","volume","closeTime",
            "qv","nTrades","takerBase","takerQuote","x"
        ])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        s = df["close"].astype(float)
        s.index = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        return s
    except Exception:
        return None

def _safe_pct_change(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    return s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

def _lead_lag(a: pd.Series, b: pd.Series, max_lag: int = 10) -> int:
    best_lag, best_corr = 0, -2.0
    a = (a - a.mean()) / (a.std(ddof=0) or 1.0)
    b = (b - b.mean()) / (b.std(ddof=0) or 1.0)
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            c = np.corrcoef(a[-lag:], b[:len(b)+lag])[0,1]
        elif lag > 0:
            c = np.corrcoef(a[:len(a)-lag], b[lag:])[0,1]
        else:
            c = np.corrcoef(a, b)[0,1]
        if not np.isnan(c) and c > best_corr:
            best_corr, best_lag = c, lag
    return int(best_lag)

def _beta(alt_ret: pd.Series, btc_ret: pd.Series) -> Optional[float]:
    try:
        cov = np.cov(alt_ret, btc_ret)[0,1]
        var_btc = np.var(btc_ret)
        if var_btc <= 0 or math.isnan(cov):
            return None
        return float(cov / var_btc)
    except Exception:
        return None

def compute_correlation(
    symbols: List[str],
    ref_symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    window: int = 200,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ref_close = _klines(ref_symbol, timeframe, limit=max(300, window+20))
    if ref_close is None or ref_close.empty:
        return out
    ref_ret = _safe_pct_change(ref_close).tail(window)

    for sym in symbols:
        if sym == ref_symbol:
            continue
        s = _klines(sym, timeframe, limit=max(300, window+20))
        if s is None or s.empty:
            out.append({
                "symbol": sym, "ref_symbol": ref_symbol, "window": window,
                "corr_close": None, "beta": None, "lead_lag_bars": None,
                "note": "no data"
            })
            continue
        ret = _safe_pct_change(s)
        df = pd.concat({"alt": ret, "btc": ref_ret}, axis=1).dropna()
        if df.empty:
            out.append({
                "symbol": sym, "ref_symbol": ref_symbol, "window": window,
                "corr_close": None, "beta": None, "lead_lag_bars": None,
                "note": "no overlap"
            })
            continue
        df = df.tail(window)
        corr = float(df["alt"].corr(df["btc"])) if len(df) >= 5 else None
        beta = _beta(df["alt"], df["btc"])
        lag = _lead_lag(df["alt"], df["btc"], max_lag=10) if len(df) >= 40 else 0
        out.append({
            "symbol": sym,
            "ref_symbol": ref_symbol,
            "window": int(window),
            "corr_close": None if corr is None or math.isnan(corr) else float(corr),
            "beta": beta,
            "lead_lag_bars": int(lag),
            "note": "ok",
        })
    return out

# ✅ Alias לשם הישן (routes/analytics.py)
correlate_to_btc = compute_correlation



