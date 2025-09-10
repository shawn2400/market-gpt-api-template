# utils/indicators.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Any

# ============================================================
# Fast, vectorized technical indicators (production-grade)
# No per-row Python loops; stable column names; NaN-safe.
# ============================================================

def _to_float_series(x: pd.Series) -> pd.Series:
    """Coerce to float Series with original index; NaN on failures."""
    if isinstance(x, pd.Series):
        s = pd.to_numeric(x, errors="coerce")
        return s.astype(float)
    # fallback
    s = pd.Series(x, copy=False)
    s = pd.to_numeric(s, errors="coerce")
    return s.astype(float)

def _rma(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder's RMA = EMA with alpha=1/period (adjust=False).
    Significantly faster and numerically stable vs. manual loops.
    """
    s = _to_float_series(series)
    if period <= 0 or s.empty:
        return pd.Series(index=s.index, dtype=float)
    alpha = 1.0 / float(period)
    return s.ewm(alpha=alpha, adjust=False).mean()

# ====================== Core Indicators ======================

def ema(series: pd.Series, period: int) -> pd.Series:
    s = _to_float_series(series)
    if period <= 0 or s.empty:
        return pd.Series(index=s.index, dtype=float)
    return s.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    s = _to_float_series(series)
    if s.empty or period <= 0:
        return pd.Series(index=s.index, dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0.0).fillna(0.0)
    loss = (-delta).clip(lower=0.0).fillna(0.0)
    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)

    # RS = avg_gain / avg_loss (∞ when loss==0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rs = rs.replace([np.inf, -np.inf], np.nan).fillna(np.inf)  # loss==0 => RS=∞ => RSI=100

    rsi_val = 100.0 - (100.0 / (1.0 + rs))
    return rsi_val.clip(0.0, 100.0)

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or period <= 0:
        return pd.Series(dtype=float)
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    tr = tr.fillna((h - l))  # first bar fallback
    return _rma(tr, period)

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or period <= 0:
        return pd.Series(dtype=float)
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))

    up_move = h.diff()
    down_move = -l.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0).fillna(0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0).fillna(0.0)

    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    tr = tr.fillna((h - l))

    atr_r = _rma(tr, period).replace(0.0, np.nan)

    plus_di = 100.0 * (_rma(plus_dm, period) / atr_r)
    minus_di = 100.0 * (_rma(minus_dm, period) / atr_r)

    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (np.abs(plus_di - minus_di) / denom) * 100.0
    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    return _rma(dx, period)

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    s = _to_float_series(series)
    if s.empty:
        empty = pd.Series(index=s.index, dtype=float)
        return empty, empty, empty
    ema_fast = ema(s, fast)
    ema_slow = ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def bollinger_bands(series: pd.Series, period: int = 20, std_factor: float = 2.0, ddof: int = 0):
    s = _to_float_series(series)
    if s.empty or period <= 0:
        empty = pd.Series(index=s.index, dtype=float)
        return empty, empty, empty
    sma = s.rolling(window=period, min_periods=period).mean()
    std = s.rolling(window=period, min_periods=period).std(ddof=ddof)
    upper = sma + std_factor * std
    lower = sma - std_factor * std
    return sma, upper, lower

# ====================== Orchestrator ======================

def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with stable, production-ready indicator columns:
    ['open','high','low','close','volume',
     'ema_21','ema_50','rsi','atr','adx',
     'macd','macd_signal','macd_hist',
     'bb_mid','bb_upper','bb_lower']
    """
    cols = [
        "open","high","low","close","volume",
        "ema_21","ema_50","rsi","atr","adx",
        "macd","macd_signal","macd_hist",
        "bb_mid","bb_upper","bb_lower",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    # Work on a copy to avoid mutating caller df
    base = df.copy()

    # Ensure base OHLCV exist and are float
    for c in ("open","high","low","close","volume"):
        base[c] = _to_float_series(base.get(c, np.nan))

    # Compute indicators (vectorized)
    base["ema_21"] = ema(base["close"], 21)
    base["ema_50"] = ema(base["close"], 50)
    base["rsi"]    = rsi(base["close"], 14)
    base["atr"]    = atr(base, 14)
    base["adx"]    = adx(base, 14)

    macd_line, macd_sig, macd_hist = macd(base["close"], 12, 26, 9)
    base["macd"] = macd_line
    base["macd_signal"] = macd_sig
    base["macd_hist"] = macd_hist

    bb_mid, bb_up, bb_low = bollinger_bands(base["close"], 20, 2.0, ddof=0)
    base["bb_mid"] = bb_mid
    base["bb_upper"] = bb_up
    base["bb_lower"] = bb_low

    # Reorder & ensure all columns present
    for c in cols:
        if c not in base.columns:
            base[c] = np.nan
    return base[cols]

__all__ = [
    "ema", "rsi", "atr", "adx", "macd", "bollinger_bands",
    "prepare_indicators_for_backtest",
]








































