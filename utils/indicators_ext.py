# utils/indicators_ext.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import StochRSIIndicator

# Market Structure (לא להפיל את הייבוא אם חסר)
try:
    from utils.market_structure import add_market_structure_columns as _ms_add
except Exception:
    _ms_add = None

def add_extended_indicators(
    df: pd.DataFrame,
    *,
    ema_fast: int = 21,
    ema_slow: int = 50,
    adx_len: int = 14,
    st_period: int = 10,
    st_factor: float = 3.0,
    ichimoku_conv: int = 9,
    ichimoku_base: int = 26,
    ichimoku_span_b: int = 52,
    ms_lookback: int = 5,
    ms_pivot_span: int = 3,
) -> pd.DataFrame:
    """
    מוסיף EMA, ADX, ATR/Supertrend, Ichimoku, StochRSI, Market-Structure (ms_label/ms_trend),
    ועמודות סיכום: trend_dir, trending.
    """
    d = df.copy()
    for c in ("open","high","low","close","volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d.dropna(inplace=True)
    if d.empty:
        return d

    close = d["close"]; high = d["high"]; low = d["low"]

    # EMA
    d["ema_fast"] = EMAIndicator(close=close, window=ema_fast).ema_indicator()
    d["ema_slow"] = EMAIndicator(close=close, window=ema_slow).ema_indicator()

    # ADX
    d["adx"] = ADXIndicator(high=high, low=low, close=close, window=adx_len).adx()

    # ATR + Supertrend (טריילינג בסיסי)
    d["atr"] = AverageTrueRange(high=high, low=low, close=close, window=st_period).average_true_range()
    hl2 = (high + low) / 2.0
    upper = hl2 + st_factor * d["atr"]
    lower = hl2 - st_factor * d["atr"]
    st = pd.Series(index=d.index, dtype=float)
    last_upper = np.nan; last_lower = np.nan; dir_up = True
    for i in range(len(d)):
        u = float(upper.iat[i]); l = float(lower.iat[i]); c = float(close.iat[i])
        if i == 0:
            st.iat[i] = l
            last_upper, last_lower = u, l
            dir_up = True
            continue
        if c > last_upper: dir_up = True
        elif c < last_lower: dir_up = False
        if dir_up:
            last_lower = max(l, last_lower) if not np.isnan(last_lower) else l
            st.iat[i] = last_lower
        else:
            last_upper = min(u, last_upper) if not np.isnan(last_upper) else u
            st.iat[i] = last_upper
    d["supertrend"] = st
    d["st_trend_up"] = (close >= st)

    # Ichimoku (ללא שיפט קדימה)
    conv   = (high.rolling(ichimoku_conv).max() + low.rolling(ichimoku_conv).min()) / 2
    base   = (high.rolling(ichimoku_base).max() + low.rolling(ichimoku_base).min()) / 2
    span_b = (high.rolling(ichimoku_span_b).max() + low.rolling(ichimoku_span_b).min()) / 2
    span_a = (conv + base) / 2
    d["ich_conv"] = conv
    d["ich_base"] = base
    d["ich_span_a"] = span_a
    d["ich_span_b"] = span_b
    d["ich_bull"] = (close > span_a) & (close > span_b) & (conv > base)
    d["ich_bear"] = (close < span_a) & (close < span_b) & (conv < base)
    d["ichimoku_state"] = np.where(d["ich_bull"], "BULL", np.where(d["ich_bear"], "BEAR", "NEUTRAL"))

    # StochRSI
    try:
        stoch = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
        d["stoch_k"] = stoch.stochrsi_k()
        d["stoch_d"] = stoch.stochrsi_d()
    except Exception:
        d["stoch_k"] = np.nan
        d["stoch_d"] = np.nan

    # Market Structure (ms_label/ms_trend)
    try:
        if _ms_add:
            d = _ms_add(
                d,
                ms_lookback=int(ms_lookback),
                ms_pivot_span=int(ms_pivot_span),
                high_col="high",
                low_col="low",
            )
        else:
            if "ms_label" not in d.columns: d["ms_label"] = ""
            if "ms_trend" not in d.columns: d["ms_trend"] = "RANGE"
    except Exception:
        if "ms_label" not in d.columns: d["ms_label"] = ""
        if "ms_trend" not in d.columns: d["ms_trend"] = "RANGE"

    # סיכום מגמה
    trend_dir = np.where(d["ema_fast"] > d["ema_slow"], "UP",
                 np.where(d["ema_fast"] < d["ema_slow"], "DOWN", "FLAT"))
    d["trend_dir"] = trend_dir
    d["trending"] = (d["adx"] >= 20) & (trend_dir != "FLAT")

    return d


def extended_score_last_row(row: pd.Series) -> tuple[float, str, float, str]:
    """
    מחזיר: (score 0..10, side 'LONG'/'SHORT', confidence 0..100, reason)
    חישוב פשוט לפי הסכמת אינדיקטורים (EMA/ADX/Supertrend/Ichimoku/MS/StochRSI).
    """
    ema_fast = float(row.get("ema_fast") or 0.0)
    ema_slow = float(row.get("ema_slow") or 0.0)
    st_up    = bool(row.get("st_trend_up"))
    ich      = str(row.get("ichimoku_state") or "NEUTRAL")
    ms_trend = str(row.get("ms_trend") or "RANGE")
    adx      = float(row.get("adx") or 0.0)
    k        = float(row.get("stoch_k") or row.get("stochrsi_k") or 0.0)
    dval     = float(row.get("stoch_d") or row.get("stochrsi_d") or 0.0)

    # כיוון בסיסי
    side = "LONG" if (ema_fast >= ema_slow and st_up) else "SHORT"

    votes = 0; total = 0; reasons: list[str] = []

    # EMA
    total += 1
    if (side == "LONG" and ema_fast >= ema_slow) or (side == "SHORT" and ema_fast <= ema_slow):
        votes += 1; reasons.append("EMA align")

    # ADX
    total += 1
    if adx >= 20:
        votes += 1; reasons.append(f"ADX {adx:.1f}")

    # Supertrend
    total += 1
    if (side == "LONG" and st_up) or (side == "SHORT" and not st_up):
        votes += 1; reasons.append("Supertrend")

    # Ichimoku
    total += 1
    if (side == "LONG" and ich == "BULL") or (side == "SHORT" and ich == "BEAR"):
        votes += 1; reasons.append(f"Ich:{ich}")

    # Market Structure
    total += 1
    if (side == "LONG" and ms_trend == "UP") or (side == "SHORT" and ms_trend == "DOWN"):
        votes += 1; reasons.append(f"MS:{ms_trend}")

    # StochRSI
    total += 1
    if (side == "LONG" and k >= dval) or (side == "SHORT" and k <= dval):
        votes += 1; reasons.append("StochRSI")

    score = round((votes / max(1, total)) * 10.0, 2)
    conf  = round((votes / max(1, total)) * 100.0, 1)
    reason = ", ".join(reasons) if reasons else "weak"
    return (score, side, conf, reason)





