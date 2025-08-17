# utils/correlation.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os, time
import numpy as np
import pandas as pd
import requests

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 correlation"})

def _klines(symbol: str, interval: str, limit: int = 300) -> Optional[pd.DataFrame]:
    url = f"{FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
    for _ in range(2):
        try:
            r = _S.get(url, timeout=7)
            if r.status_code == 200:
                arr = r.json()
                df = pd.DataFrame(arr, columns=[
                    "openTime","open","high","low","close","volume",
                    "closeTime","qv","nTrades","takerBase","takerQuote","x"
                ])
                for c in ("open","high","low","close","volume"):
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df["ts"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
                return df[["ts","close"]]
        except Exception:
            time.sleep(0.4)
    return None

def _prep_returns(df: pd.DataFrame) -> pd.Series:
    s = df["close"].astype(float).pct_change().dropna()
    return s

def _beta_y_on_x(y: pd.Series, x: pd.Series) -> Optional[float]:
    try:
        # align
        j = pd.concat([y, x], axis=1).dropna()
        if len(j) < 10:
            return None
        coef = np.polyfit(j.iloc[:,1].values, j.iloc[:,0].values, 1)
        return float(coef[0])
    except Exception:
        return None

def _lead_lag(y: pd.Series, x: pd.Series, max_lag: int = 5) -> Optional[int]:
    try:
        best_lag, best_val = 0, -9
        for lag in range(-max_lag, max_lag+1):
            if lag > 0:
                v = y[lag:].corr(x[:-lag])
            elif lag < 0:
                v = y[:lag].corr(x[-lag:])
            else:
                v = y.corr(x)
            if pd.notna(v) and v > best_val:
                best_val, best_lag = v, lag
        return int(best_lag)
    except Exception:
        return None

def correlate_to_btc(symbols: List[str], ref_symbol: str = "BTCUSDT", timeframe: str = "15m", window: int = 200) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    btc = _klines(ref_symbol, timeframe, limit=window + 20)
    if btc is None or btc.empty:
        return out
    r_btc = _prep_returns(btc).tail(window)

    for sym in symbols:
        try:
            df = _klines(sym, timeframe, limit=window + 20)
            if df is None or df.empty:
                continue
            r_alt = _prep_returns(df).tail(window)
            j = pd.concat([r_alt, r_btc], axis=1, keys=["alt","btc"]).dropna()
            if len(j) < 30:
                continue
            corr = float(j["alt"].corr(j["btc"]))
            beta = _beta_y_on_x(j["alt"], j["btc"])
            lag  = _lead_lag(j["alt"], j["btc"])
            out.append({
                "symbol": sym,
                "ref_symbol": ref_symbol,
                "window": int(min(window, len(j))),
                "corr_close": round(corr, 4),
                "beta": None if beta is None else round(beta, 4),
                "lead_lag_bars": lag,
                "note": "lag>0: ALT lagging BTC; lag<0: ALT leading"
            })
        except Exception:
            continue
    out.sort(key=lambda x: (abs(x["corr_close"]) if x.get("corr_close") is not None else 0), reverse=True)
    return out

