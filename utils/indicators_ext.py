# utils/indicators_ext.py
from __future__ import annotations
import math
from typing import Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd

from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import StochRSIIndicator

# Market Structure (Pivot/HH/HL/LH/LL, מגמה)
from utils.market_structure import add_market_structure_columns


def _to_float(x, default: float = np.nan) -> float:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return default
    except Exception:
        return default


def _ensure_numeric_ohlcv(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def enrich_base_indicators(
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
    מוסיף אינדיקטורים בסיסיים:
      EMA(fast/slow), ADX, ATR, Supertrend (פשוט), Ichimoku (conv/base/span_a/span_b + דגלים),
      StochRSI (k/d), flags: st_trend_up
    שומר גם עמודות עזר תחת שמות קצרים שהקוד Downstream מצפה להם.
    """
    d = _ensure_numeric_ohlcv(df)
    d.dropna(subset=["open", "high", "low", "close"], inplace=True)

    if len(d) < max(ich_span_b + ich_base, ema_slow + adx_len + st_period + 20):
        # מעט מידי ברים — נחזיר כפי שהוא (ימנע חישובי NaN כבדים)
        return d

    close = d["close"]
    high = d["high"]
    low = d["low"]

    # EMA
    d["ema_fast"] = EMAIndicator(close=close, window=int(ema_fast)).ema_indicator()
    d["ema_slow"] = EMAIndicator(close=close, window=int(ema_slow)).ema_indicator()

    # ADX
    d["adx"] = ADXIndicator(high=high, low=low, close=close, window=int(adx_len)).adx()

    # ATR (נשמרה גם לצורך נגישות downstream)
    atr_series = AverageTrueRange(high=high, low=low, close=close, window=int(st_period)).average_true_range()
    d["atr"] = atr_series

    # Supertrend (גרסה קלה ומהירה – "כאן ועכשיו")
    hl2 = (high + low) / 2.0
    upper = hl2 + float(st_factor) * atr_series
    lower = hl2 - float(st_factor) * atr_series
    st = pd.Series(index=d.index, dtype=float)
    last_upper = np.nan
    last_lower = np.nan
    dir_up = True
    for i in range(len(d)):
        u = upper.iat[i]
        l = lower.iat[i]
        c = close.iat[i]
        if i == 0:
            st.iat[i] = l
            last_upper, last_lower = u, l
            dir_up = True
            continue
        # Flip לפי פריצה
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

    # Ichimoku components (ללא הסטה קדימה)
    conv = (high.rolling(int(ich_conv)).max() + low.rolling(int(ich_conv)).min()) / 2.0
    base = (high.rolling(int(ich_base)).max() + low.rolling(int(ich_base)).min()) / 2.0
    span_b = (high.rolling(int(ich_span_b)).max() + low.rolling(int(ich_span_b)).min()) / 2.0
    span_a = (conv + base) / 2.0

    d["ich_conv"] = conv
    d["ich_base"] = base
    d["ich_span_a"] = span_a
    d["ich_span_b"] = span_b
    d["ich_bull"] = (close > span_a) & (close > span_b) & (conv > base)
    d["ich_bear"] = (close < span_a) & (close < span_b) & (conv < base)

    # StochRSI
    try:
        stoch = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
        d["stoch_k"] = stoch.stochrsi_k()
        d["stoch_d"] = stoch.stochrsi_d()
    except Exception:
        d["stoch_k"] = np.nan
        d["stoch_d"] = np.nan

    # State Labels
    ich_state = np.where(d["ich_bull"], "BULL", np.where(d["ich_bear"], "BEAR", "NEUTRAL"))
    d["ichimoku_state"] = ich_state

    # כיוון מגמה "פשוט"
    d["trend_dir"] = np.where(d["ema_fast"] > d["ema_slow"], "UP", "DOWN")
    # טרנדינג: ADX>20 כהערכה מהירה
    d["trending"] = (d["adx"] >= 20.0)

    return d


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
    עטיפה מלאה: אינדיקטורים + Market Structure (ms_label/ms_trend).
    תואם את הקריאות מ־routes/multi_scan.py.
    """
    d = enrich_base_indicators(
        df,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        adx_len=adx_len,
        st_period=st_period,
        st_factor=st_factor,
        ich_conv=ichimoku_conv,
        ich_base=ichimoku_base,
        ich_span_b=ichimoku_span_b,
    )

    # הזרקת Market Structure (אם לא קיים כבר)
    if ("ms_label" not in d.columns) or ("ms_trend" not in d.columns):
        try:
            d = add_market_structure_columns(
                d,
                ms_lookback=int(ms_lookback),
                ms_pivot_span=int(ms_pivot_span),
                high_col="high",
                low_col="low",
            )
        except Exception:
            # במקרה של תקלה — נמשיך בלי לזרוק שגיאה
            d["ms_label"] = ""
            d["ms_trend"] = "RANGE"

    # תאימות: ודא שקיימות כל העמודות שה־routes מצפה להן
    for col, default in [
        ("adx", np.nan),
        ("ema_fast", np.nan),
        ("ema_slow", np.nan),
        ("atr", np.nan),
        ("ichimoku_state", "NEUTRAL"),
        ("stoch_k", np.nan),
        ("stoch_d", np.nan),
        ("supertrend", np.nan),
        ("trend_dir", "DOWN"),
        ("trending", False),
        ("ms_label", ""),
        ("ms_trend", "RANGE"),
        ("close", np.nan),
    ]:
        if col not in d.columns:
            d[col] = default

    return d


def extended_score_last_row(row: pd.Series) -> Tuple[float, Optional[str], int, str]:
    """
    מחזיר: (score:0..10, side: LONG/SHORT/None, confidence:0..100, reason:str)
    ניקוד דטרמיניסטי, משלב EMA/ADX/Ichimoku/Supertrend/MS/StochRSI.
    """
    # קריאות בטוחות
    ema_fast = _to_float(row.get("ema_fast"))
    ema_slow = _to_float(row.get("ema_slow"))
    adx = _to_float(row.get("adx"), 0.0)
    st_up = bool(row.get("st_trend_up"))
    ich_state = str(row.get("ichimoku_state") or "NEUTRAL")
    ms_trend = str(row.get("ms_trend") or "RANGE")
    k = _to_float(row.get("stoch_k"))
    d = _to_float(row.get("stoch_d"))

    score = 5.0   # נתחיל מאמצע טווח (0..10)
    long_bias = 0.0
    short_bias = 0.0
    reasons = []

    # EMA cross
    if np.isfinite(ema_fast) and np.isfinite(ema_slow):
        if ema_fast > ema_slow:
            score += 1.0; long_bias += 1.0; reasons.append("ema_fast>ema_slow")
        elif ema_fast < ema_slow:
            score -= 1.0; short_bias += 1.0; reasons.append("ema_fast<ema_slow")

    # ADX strength
    if adx >= 25:
        score += 1.0; reasons.append("adx>=25")
    elif adx >= 20:
        score += 0.5; reasons.append("adx>=20")
    elif adx < 15:
        score -= 0.5; reasons.append("adx<15")

    # Supertrend
    if st_up:
        score += 1.0; long_bias += 0.5; reasons.append("supertrend_up")
    else:
        score -= 1.0; short_bias += 0.5; reasons.append("supertrend_down")

    # Ichimoku state
    if ich_state == "BULL":
        score += 1.5; long_bias += 1.0; reasons.append("ich_bull")
    elif ich_state == "BEAR":
        score -= 1.5; short_bias += 1.0; reasons.append("ich_bear")

    # Market Structure
    if ms_trend == "UP":
        score += 1.5; long_bias += 1.0; reasons.append("ms_up")
    elif ms_trend == "DOWN":
        score -= 1.5; short_bias += 1.0; reasons.append("ms_down")

    # StochRSI relative
    if np.isfinite(k) and np.isfinite(d):
        if k > d and k < 0.85:
            score += 0.5; long_bias += 0.25; reasons.append("stoch_bullish")
        elif k < d and k > 0.15:
            score -= 0.5; short_bias += 0.25; reasons.append("stoch_bearish")

    # קלמפ 0..10
    score = float(max(0.0, min(10.0, round(score, 2))))

    # כיוון מוצע
    side: Optional[str]
    if long_bias > short_bias and score >= 5.2:
        side = "LONG"
    elif short_bias > long_bias and score <= 4.8:
        side = "SHORT"
    else:
        side = None

    # Confidence לפי מרחק מהמרכז + עקביות ביאס
    center_dist = abs(score - 5.0) / 5.0  # 0..1
    bias_spread = abs(long_bias - short_bias) / max(1.0, (long_bias + short_bias + 1e-9))
    confidence = int(max(0.0, min(1.0, 0.6 * center_dist + 0.4 * bias_spread)) * 100)

    reason = ", ".join(reasons) if reasons else "neutral"
    return score, side, confidence, reason



