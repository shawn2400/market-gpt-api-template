# utils/indicators_ext.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Any

from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import StochRSIIndicator

def _num(x): 
    try: 
        return float(x)
    except Exception:
        return np.nan

def enrich_ext(
    df: pd.DataFrame,
    *,
    ema_fast: int = 21,
    ema_slow: int = 50,
    adx_len: int = 14,
    st_period: int = 10,
    st_factor: float = 3.0,
    ich_conv: int = 9,
    ich_base: int = 26,
    ich_span_b: int = 52,
) -> pd.DataFrame:
    """
    מוסיף: EMA מהירים/איטיים, ADX, Supertrend, Ichimoku, StochRSI
    """
    d = df.copy()
    for c in ("open","high","low","close","volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d.dropna(inplace=True)
    if len(d) < max(ich_span_b + ich_base, ema_slow + adx_len + st_period + 20):
        return d

    close = d["close"]; high = d["high"]; low = d["low"]

    # EMA
    d["ema_fast"] = EMAIndicator(close=close, window=ema_fast).ema_indicator()
    d["ema_slow"] = EMAIndicator(close=close, window=ema_slow).ema_indicator()

    # ADX
    d["adx"] = ADXIndicator(high=high, low=low, close=close, window=adx_len).adx()

    # Supertrend
    atr = AverageTrueRange(high=high, low=low, close=close, window=st_period).average_true_range()
    hl2 = (high + low) / 2.0
    upper = hl2 + st_factor * atr
    lower = hl2 - st_factor * atr
    # טריילינג בסיסי
    st = pd.Series(index=d.index, dtype=float)
    dir_up = True
    last_upper = last_lower = np.nan
    for i in range(len(d)):
        u = upper.iat[i]; l = lower.iat[i]; c = close.iat[i]
        if i == 0:
            st.iat[i] = l
            dir_up = True
            last_upper, last_lower = u, l
            continue
        if c > last_upper:
            dir_up = True
        elif c < last_lower:
            dir_up = False
        if dir_up:
            last_lower = max(l, last_lower) if not np.isnan(last_lower) else l
            st.iat[i] = last_lower
        else:
            last_upper = min(u, last_upper) if not np.isnan(last_upper) else u
            st.iat[i] = last_upper
    d["supertrend"] = st
    d["st_trend_up"] = (close >= st)

    # Ichimoku (ללא שיפט קדימה לצורכי סיגנל "כאן ועכשיו")
    conv = (high.rolling(ich_conv).max() + low.rolling(ich_conv).min()) / 2
    base = (high.rolling(ich_base).max() + low.rolling(ich_base).min()) / 2
    span_b = (high.rolling(ich_span_b).max() + low.rolling(ich_span_b).min()) / 2
    span_a = (conv + base) / 2
    d["ich_conv"] = conv
    d["ich_base"] = base
    d["ich_span_a"] = span_a
    d["ich_span_b"] = span_b
    d["ich_bull"] = (close > span_a) & (close > span_b) & (conv > base)
    d["ich_bear"] = (close < span_a) & (close < span_b) & (conv < base)

    # StochRSI
    try:
        stoch = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
        d["stochrsi_k"] = stoch.stochrsi_k()
        d["stochrsi_d"] = stoch.stochrsi_d()
    except Exception:
        d["stochrsi_k"] = np.nan
        d["stochrsi_d"] = np.nan

    return d

def market_structure(
    d: pd.DataFrame,
    *,
    lookback: int = 5,
    pivot_span: int = 3,
) -> Dict[str, Any]:
    """
    זיהוי HH/HL/LL/LH פשוט על סמך פיבוטים אחרונים.
    """
    if d is None or d.empty:
        return {"ms": None, "note": "no data"}
    high = d["high"]; low = d["low"]
    # חישוב פיבוטים
    ph = high.rolling(pivot_span).max()
    pl = low.rolling(pivot_span).min()
    pivots = []
    for i in range(pivot_span, len(d)-pivot_span):
        if high.iat[i] >= ph.iat[i] and high.iat[i] >= high[i-pivot_span:i+pivot_span+1].max():
            pivots.append(("H", i, high.iat[i]))
        if low.iat[i] <= pl.iat[i] and low.iat[i] <= low[i-pivot_span:i+pivot_span+1].min():
            pivots.append(("L", i, low.iat[i]))
    pivots = pivots[-(lookback*2):]
    if len(pivots) < 4:
        return {"ms": None, "note": "not enough pivots"}

    # קלאסיפיקציה אחרונה: השוואת שני שיאים ושני שפלים אחרונים
    highs = [p for p in pivots if p[0] == "H"][-2:]
    lows  = [p for p in pivots if p[0] == "L"][-2:]
    ms = None
    if len(highs) == 2 and len(lows) == 2:
        ms_high = "HH" if highs[-1][2] > highs[-2][2] else "LH"
        ms_low  = "HL" if lows[-1][2]  > lows[-2][2]  else "LL"
        # גזירת מגמה
        if ms_high == "HH" and ms_low == "HL":
            ms = "BULL"
        elif ms_high == "LH" and ms_low == "LL":
            ms = "BEAR"
        else:
            ms = "RANGE"
    return {"ms": ms}


