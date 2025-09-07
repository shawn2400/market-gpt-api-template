# utils/indicators.py
from __future__ import annotations
import pandas as pd, numpy as np
from collections import deque
from typing import Dict, Any

# RingBuffer לאינקרמנטלי
_RING: Dict[str, Dict[str, Any]] = {}

def _as_series(x: pd.Series) -> pd.Series:
    s = pd.to_numeric(pd.Series(x, copy=False), errors="coerce")
    return s.astype(float)

def _rma(series: pd.Series, period: int) -> pd.Series:
    s = _as_series(series)
    r = pd.Series(index=s.index, dtype=float)
    if len(s) == 0: return r
    alpha = 1.0 / float(period)
    r.iloc[0] = s.iloc[:period].mean() if len(s) >= period else s.iloc[0]
    for i in range(1, len(s)):
        r.iloc[i] = r.iloc[i - 1] * (1 - alpha) + alpha * s.iloc[i]
    return r

# ========== Indicators ==========
def ema(series: pd.Series, period: int) -> pd.Series:
    return _as_series(series).ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    s = _as_series(series)
    if s.empty: return s.copy()
    delta = s.diff().fillna(0.0)
    gain, loss = delta.clip(lower=0.0), (-delta).clip(lower=0.0)
    avg_gain, avg_loss = _rma(gain, period), _rma(loss, period)
    rs = pd.Series(np.where(avg_loss == 0.0, np.inf, avg_gain / avg_loss), index=s.index)
    return (100.0 - (100.0 / (1.0 + rs))).clip(0.0, 100.0)

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty: return pd.Series(dtype=float)
    h, l, c = _as_series(df["high"]), _as_series(df["low"]), _as_series(df["close"])
    prev_c = c.shift(1).fillna(c.iloc[0])
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return _rma(tr, period)

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty: return pd.Series(dtype=float)
    h, l, c = _as_series(df["high"]), _as_series(df["low"]), _as_series(df["close"])
    up, down = h.diff(), -l.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=l.index)
    prev_c = c.shift(1).fillna(c.iloc[0])
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr_rma = _rma(tr, period).replace(0.0, np.nan)
    plus_di = 100.0 * (_rma(plus_dm, period) / atr_rma)
    minus_di = 100.0 * (_rma(minus_dm, period) / atr_rma)
    dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0.0, np.nan)) * 100.0
    return _rma(dx.fillna(0.0), period)

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    s = _as_series(series)
    ema_fast, ema_slow = ema(s, fast), ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line

def bollinger_bands(series: pd.Series, period=20, std_factor=2.0):
    s = _as_series(series)
    sma = s.rolling(period, min_periods=period).mean()
    std = s.rolling(period, min_periods=period).std()
    return sma, sma + std_factor * std, sma - std_factor * std

# ========== Orchestrator ==========
def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["open","high","low","close","volume",
            "ema_21","ema_50","rsi","atr","adx",
            "macd","macd_signal","macd_hist",
            "bb_mid","bb_upper","bb_lower"]
    if df is None or df.empty: return pd.DataFrame(columns=cols)
    base = df.copy()
    for c in ("open","high","low","close","volume"):
        base[c] = _as_series(base.get(c, np.nan))
    base["ema_21"], base["ema_50"] = ema(base["close"], 21), ema(base["close"], 50)
    base["rsi"], base["atr"], base["adx"] = rsi(base["close"]), atr(base), adx(base)
    macd_line, sig, hist = macd(base["close"])
    base["macd"], base["macd_signal"], base["macd_hist"] = macd_line, sig, hist
    mid, up, low = bollinger_bands(base["close"])
    base["bb_mid"], base["bb_upper"], base["bb_lower"] = mid, up, low
    return base






































