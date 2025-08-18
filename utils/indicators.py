# utils/indicators_ext.py
from __future__ import annotations
import numpy as np
import pandas as pd

try:
    from ta.trend import EMAIndicator, ADXIndicator, IchimokuIndicator
    from ta.momentum import StochasticOscillator
    from ta.volatility import AverageTrueRange
    _HAS_TA = True
except Exception:
    _HAS_TA = False


def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    for c in ("open", "high", "low", "close", "volume"):
        if c not in work.columns:
            raise ValueError("DataFrame must contain OHLCV columns")
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work.dropna(subset=["open", "high", "low", "close"], inplace=True)
    return work


def _supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 10, factor: float = 3.0) -> pd.Series:
    """מימוש סטנדרטי של Supertrend (ATR-based). מחזיר קו ה-ST."""
    if period <= 1:
        period = 10
    if factor <= 0:
        factor = 3.0

    atr = AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()
    hl2 = (high + low) / 2.0
    upper = hl2 + factor * atr
    lower = hl2 - factor * atr

    fu = upper.copy()
    fl = lower.copy()
    st = pd.Series(index=close.index, dtype="float64")

    # אתחול
    fu.iloc[0] = upper.iloc[0]
    fl.iloc[0] = lower.iloc[0]
    st.iloc[0] = upper.iloc[0]

    for i in range(1, len(close)):
        fu.iloc[i] = upper.iloc[i] if (upper.iloc[i] < fu.iloc[i - 1] or close.iloc[i - 1] > fu.iloc[i - 1]) else fu.iloc[i - 1]
        fl.iloc[i] = lower.iloc[i] if (lower.iloc[i] > fl.iloc[i - 1] or close.iloc[i - 1] < fl.iloc[i - 1]) else fl.iloc[i - 1]

        if st.iloc[i - 1] == fu.iloc[i - 1]:
            st.iloc[i] = fu.iloc[i] if close.iloc[i] <= fu.iloc[i] else fl.iloc[i]
        else:
            st.iloc[i] = fl.iloc[i] if close.iloc[i] >= fl.iloc[i] else fu.iloc[i]

    return st


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
    מוסיף אינדיקטורים ושדות טרנד/תיאור. אם ta לא זמין, מחזיר DataFrame ריק.
    """
    if not _HAS_TA:
        return pd.DataFrame()

    work = _ensure_ohlcv(df)
    if work.empty:
        return pd.DataFrame()

    close = work["close"]
    high = work["high"]
    low = work["low"]

    # EMA / ADX
    work["ema_fast"] = EMAIndicator(close, window=int(ema_fast)).ema_indicator()
    work["ema_slow"] = EMAIndicator(close, window=int(ema_slow)).ema_indicator()
    work["adx"] = ADXIndicator(high, low, close, window=int(adx_len)).adx()

    # Stoch
    stoch = StochasticOscillator(high, low, close, window=14, smooth_window=3)
    work["stoch_k"] = stoch.stoch()
    work["stoch_d"] = stoch.stoch_signal()

    # ATR (גם לצורכי ניקוד)
    work["atr"] = AverageTrueRange(high, low, close, window=max(14, int(st_period))).average_true_range()

    # Supertrend
    work["supertrend"] = _supertrend(high, low, close, period=int(st_period), factor=float(st_factor))

    # Ichimoku (מצב קלוד בסיסי)
    try:
        ich = IchimokuIndicator(high, low, window1=int(ichimoku_conv), window2=int(ichimoku_base), window3=int(ichimoku_span_b))
        span_a = ich.ichimoku_a()
        span_b = ich.ichimoku_b()
    except Exception:
        # fallback פשוט אם הגרסה לא תואמת
        conv = (high.rolling(int(ichimoku_conv)).max() + low.rolling(int(ichimoku_conv)).min()) / 2.0
        base = (high.rolling(int(ichimoku_base)).max() + low.rolling(int(ichimoku_base)).min()) / 2.0
        span_a = (conv + base) / 2.0
        span_b = (high.rolling(int(ichimoku_span_b)).max() + low.rolling(int(ichimoku_span_b)).min()) / 2.0

    cloud_top = np.maximum(span_a, span_b)
    cloud_bot = np.minimum(span_a, span_b)
    ich_state = np.where(close > cloud_top, "BULLISH",
                  np.where(close < cloud_bot, "BEARISH", "NEUTRAL"))
    work["ichimoku_state"] = ich_state

    # כיוון טרנד + דגל trending
    trend_dir = np.where(work["ema_fast"] > work["ema_slow"], "UP",
                 np.where(work["ema_fast"] < work["ema_slow"], "DOWN", "FLAT"))
    work["trend_dir"] = trend_dir
    work["trending"] = (work["adx"] >= 20.0) & (trend_dir != "FLAT")

    # "Market structure" גס (HH/HL, LH/LL, RANGE)
    look = max(2, int(ms_lookback))
    span = max(1, int(ms_pivot_span))
    roll_max = close.rolling(look).max().shift(span)
    roll_min = close.rolling(look).min().shift(span)
    ms_lbl = np.where(close >= roll_max, "HH/HL",
              np.where(close <= roll_min, "LH/LL", "RANGE"))
    work["ms_trend"] = ms_lbl
    work["ms_label"] = ms_lbl  # שדה תואם לשימושים שונים

    return work


def extended_score_last_row(row: pd.Series) -> tuple[float, str, int, str]:
    """
    מחזיר (score[0..10], side['LONG'/'SHORT'], confidence[0..100], reason)
    ניקוד היברידי: ADX, EMA, Supertrend, Ichimoku, Stoch.
    """
    try:
        adx = float(row.get("adx", 0.0) or 0.0)
        ema_fast = float(row.get("ema_fast", 0.0) or 0.0)
        ema_slow = float(row.get("ema_slow", 0.0) or 0.0)
        close = float(row.get("close", 0.0) or 0.0)
        st_val = float(row.get("supertrend", close) or close)
        ich = str(row.get("ichimoku_state", "NEUTRAL") or "NEUTRAL").upper()
        k = float(row.get("stoch_k", 50.0) or 50.0)
        d = float(row.get("stoch_d", 50.0) or 50.0)
        trend_dir = str(row.get("trend_dir", "FLAT") or "FLAT").upper()
        trending = bool(row.get("trending", False))

        bull_checks = 0
        bull_checks += 1 if ema_fast > ema_slow else 0
        bull_checks += 1 if close > st_val else 0
        bull_checks += 1 if ich == "BULLISH" else 0

        bear_checks = 0
        bear_checks += 1 if ema_fast < ema_slow else 0
        bear_checks += 1 if close < st_val else 0
        bear_checks += 1 if ich == "BEARISH" else 0

        side = "LONG" if bull_checks >= bear_checks else "SHORT"

        # Directional score (0..5)
        dir_score = (max(bull_checks, bear_checks) / 3.0) * 5.0

        # ADX score (0..3) – משוקלל מתון
        adx_score = max(0.0, min(3.0, (adx / 40.0) * 3.0))  # adx=40 ⇒ 3pts

        # Stoch bonus (0..1)
        if side == "LONG":
            stoch_bonus = 1.0 if k >= d else 0.0
        else:
            stoch_bonus = 1.0 if k <= d else 0.0

        # Trending bonus (0..1)
        tr_bonus = 1.0 if trending else 0.0

        raw = dir_score + adx_score + stoch_bonus + tr_bonus
        score = float(max(0.0, min(10.0, round(raw, 2))))

        conf = int(max(0, min(100, round(30 + adx * 2 + (10 if trending else 0) + (5 if dir_score >= 3.5 else 0)))))

        reason = f"{side} • dir={dir_score:.1f}, adx={adx:.1f}, stoch={'K>D' if k>=d else 'K<D'}, ich={ich}, trending={trending}"
        return score, side, conf, reason
    except Exception:
        return 0.0, "LONG", 50, "scoring_error"

































