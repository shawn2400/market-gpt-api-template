# utils/indicators_ext.py
from __future__ import annotations
from typing import Tuple, Literal
import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import StochasticOscillator
from ta.volatility import AverageTrueRange

Side = Literal["LONG", "SHORT"]

# -------- Ichimoku --------
def _ichimoku(df: pd.DataFrame, conv: int, base: int, span_b: int) -> pd.DataFrame:
    hi = df["high"]; lo = df["low"]; close = df["close"]

    conv_line = (hi.rolling(conv).max() + lo.rolling(conv).min()) / 2.0
    base_line = (hi.rolling(base).max() + lo.rolling(base).min()) / 2.0
    span_b_line = (hi.rolling(span_b).max() + lo.rolling(span_b).min()) / 2.0

    out = pd.DataFrame(index=df.index)
    out["ich_conv"] = conv_line
    out["ich_base"] = base_line
    out["ich_span_b"] = span_b_line

    # סטייט: BULL אם המחיר מעל conv/base ו־conv>base; BEAR אם הפוך; אחרת NEUTRAL
    st = np.where((close > conv_line) & (conv_line > base_line), "BULL",
         np.where((close < conv_line) & (conv_line < base_line), "BEAR", "NEUTRAL"))
    out["ichimoku_state"] = st.astype(str)

    return out

# -------- Supertrend --------
def _supertrend(df: pd.DataFrame, period: int = 10, factor: float = 3.0) -> pd.Series:
    """
    מימוש Supertrend בסיסי.
    """
    atr = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=period).average_true_range()
    hl2 = (df["high"] + df["low"]) / 2.0
    upperband = hl2 + factor * atr
    lowerband = hl2 - factor * atr

    st = pd.Series(index=df.index, dtype=float)
    trend_up = True
    prev = np.nan

    for i in range(len(df)):
        if i == 0:
            st.iat[i] = lowerband.iat[i]
            prev = st.iat[i]
            continue

        if df["close"].iat[i] > prev:
            st.iat[i] = max(lowerband.iat[i], prev)
            trend_up = True
        else:
            st.iat[i] = min(upperband.iat[i], prev)
            trend_up = False

        prev = st.iat[i]

    return st

# -------- Market Structure (פיבוטים פשוטים) --------
def _pivot_labels(df: pd.DataFrame, lookback: int = 5, span: int = 3) -> Tuple[pd.Series, pd.Series]:
    """
    מחזיר (ms_label, ms_trend)
    ms_label: אחד מ["HH","HL","LH","LL","—"]
    ms_trend: "UP"/"DOWN"/"RANGE"
    """
    hi = df["high"].rolling(span, center=True).max()
    lo = df["low"].rolling(span, center=True).min()

    piv_hi = (df["high"] == hi)
    piv_lo = (df["low"] == lo)

    last_hi = pd.Series(index=df.index, dtype=float)
    last_lo = pd.Series(index=df.index, dtype=float)

    cur_hi = np.nan
    cur_lo = np.nan
    for i in range(len(df)):
        if piv_hi.iat[i]:
            cur_hi = df["high"].iat[i]
        if piv_lo.iat[i]:
            cur_lo = df["low"].iat[i]
        last_hi.iat[i] = cur_hi
        last_lo.iat[i] = cur_lo

    # השוואת פיבוטים אחרונים
    label = pd.Series("—", index=df.index, dtype=object)
    trend = pd.Series("RANGE", index=df.index, dtype=object)

    for i in range(1, len(df)):
        hh = (last_hi.iat[i] > last_hi.iat[i-1]) if not np.isnan(last_hi.iat[i-1]) else False
        hl = (last_lo.iat[i] > last_lo.iat[i-1]) if not np.isnan(last_lo.iat[i-1]) else False
        lh = (last_hi.iat[i] < last_hi.iat[i-1]) if not np.isnan(last_hi.iat[i-1]) else False
        ll = (last_lo.iat[i] < last_lo.iat[i-1]) if not np.isnan(last_lo.iat[i-1]) else False

        if hh and hl:
            label.iat[i] = "HH"
            trend.iat[i] = "UP"
        elif lh and ll:
            label.iat[i] = "LL"
            trend.iat[i] = "DOWN"
        elif hh:
            label.iat[i] = "HH"
            trend.iat[i] = "UP"
        elif ll:
            label.iat[i] = "LL"
            trend.iat[i] = "DOWN"
        elif hl:
            label.iat[i] = "HL"
            trend.iat[i] = "UP"
        elif lh:
            label.iat[i] = "LH"
            trend.iat[i] = "DOWN"
        else:
            label.iat[i] = "—"
            trend.iat[i] = "RANGE"

    return label, trend

# -------- הוספת אינדיקטורים מורחבים --------
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
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()

    # וידוא טיפוסים
    for c in ("open", "high", "low", "close", "volume"):
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work.dropna(subset=["open","high","low","close","volume"], inplace=True)
    if work.empty:
        return pd.DataFrame()

    # EMA/ADX/Stoch
    work["ema_fast"] = EMAIndicator(close=work["close"], window=int(ema_fast)).ema_indicator()
    work["ema_slow"] = EMAIndicator(close=work["close"], window=int(ema_slow)).ema_indicator()
    adx = ADXIndicator(high=work["high"], low=work["low"], close=work["close"], window=int(adx_len))
    work["adx"] = adx.adx()

    stoch = StochasticOscillator(high=work["high"], low=work["low"], close=work["close"], window=14, smooth_window=3)
    work["stoch_k"] = stoch.stoch()
    work["stoch_d"] = stoch.stoch_signal()

    # ATR + Supertrend
    work["atr"] = AverageTrueRange(high=work["high"], low=work["low"], close=work["close"], window=max(7, min(50, int(st_period)))).average_true_range()
    work["supertrend"] = _supertrend(work, period=int(st_period), factor=float(st_factor))

    # Ichimoku
    ich = _ichimoku(work, conv=int(ichimoku_conv), base=int(ichimoku_base), span_b=int(ichimoku_span_b))
    work = pd.concat([work, ich], axis=1)

    # Market structure
    ms_label, ms_trend = _pivot_labels(work, lookback=int(ms_lookback), span=int(ms_pivot_span))
    work["ms_label"] = ms_label
    work["ms_trend"] = ms_trend

    # מגמת טרנד כללית
    trend_dir = np.where((work["ema_fast"] > work["ema_slow"]) & (work["close"] > work["ema_fast"]), "UP",
                 np.where((work["ema_fast"] < work["ema_slow"]) & (work["close"] < work["ema_fast"]), "DOWN", "FLAT"))
    work["trend_dir"] = trend_dir.astype(str)

    # דגל trending (בפועל /multi_scan מפעיל סינון חיצוני לפי min_adx)
    work["trending"] = (work["trend_dir"] != "FLAT") & (work["adx"] >= 20.0)

    return work

# -------- ציון/צד/קונפידנס לשורה האחרונה --------
def extended_score_last_row(row: pd.Series) -> Tuple[float, Side, int, str]:
    """
    מחזיר (score [0..10], side, confidence [0..100], reason<=140ch)
    """
    close = float(row.get("close", np.nan))
    ema_f = float(row.get("ema_fast", np.nan))
    ema_s = float(row.get("ema_slow", np.nan))
    adx = float(row.get("adx", 0.0))
    st_k = float(row.get("stoch_k", 50.0))
    st_d = float(row.get("stoch_d", 50.0))
    ich_state = str(row.get("ichimoku_state", "NEUTRAL") or "NEUTRAL")
    st_value = float(row.get("supertrend", np.nan))
    ms_trend = str(row.get("ms_trend", "RANGE") or "RANGE")
    tdir = str(row.get("trend_dir", "FLAT") or "FLAT")

    # צד ברירת מחדל
    side: Side = "LONG" if (tdir == "UP") else ("SHORT" if tdir == "DOWN" else ("LONG" if close >= ema_f else "SHORT"))

    # רכיבי ציון
    score = 0.0
    reasons: list[str] = []

    # EMA alignment
    if np.isfinite(ema_f) and np.isfinite(ema_s):
        if ema_f > ema_s:
            score += 2.0
            reasons.append("EMA↑")
        elif ema_f < ema_s:
            score += 2.0
            reasons.append("EMA↓")

    # Price vs EMA_fast
    if np.isfinite(close) and np.isfinite(ema_f):
        if close > ema_f: score += 1.0
        else: score += 0.5

    # ADX strength (0..2)
    score += max(0.0, min(2.0, (adx / 25.0)))  # adx 50 -> 2.0
    if adx >= 20: reasons.append(f"ADX={int(adx)}")

    # Stoch alignment (0..1)
    if st_k > st_d and side == "LONG":
        score += 0.7; reasons.append("Stoch✓")
    elif st_k < st_d and side == "SHORT":
        score += 0.7; reasons.append("Stoch✓")
    else:
        score += 0.3

    # Ichimoku bias (0..2)
    if ich_state == "BULL" and side == "LONG":
        score += 1.5; reasons.append("Ich BULL")
    elif ich_state == "BEAR" and side == "SHORT":
        score += 1.5; reasons.append("Ich BEAR")
    else:
        score += 0.5

    # Supertrend agreement (0..1)
    if np.isfinite(st_value) and np.isfinite(close):
        if (side == "LONG" and close >= st_value) or (side == "SHORT" and close <= st_value):
            score += 0.8; reasons.append("ST✓")
        else:
            score += 0.2

    # Market structure (0..1)
    if ms_trend == "UP" and side == "LONG":
        score += 0.8; reasons.append("MS↑")
    elif ms_trend == "DOWN" and side == "SHORT":
        score += 0.8; reasons.append("MS↓")
    else:
        score += 0.3

    # Trending/Trend dir bonus (0..1)
    if tdir == "UP" and side == "LONG":
        score += 0.6; reasons.append("Trend↑")
    elif tdir == "DOWN" and side == "SHORT":
        score += 0.6; reasons.append("Trend↓")
    else:
        score += 0.2

    score = float(max(0.0, min(10.0, round(score, 2))))

    # Confidence נגזר מציון, עם דגש על ADX
    conf = int(max(0, min(100, round( (score/10.0)*70 + max(0.0, min(30.0, adx)) ))))

    reason = " ".join(reasons)[:140]
    return score, side, conf, reason







