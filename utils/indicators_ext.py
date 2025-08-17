# utils/indicators_ext.py
from __future__ import annotations
import math
from typing import Tuple, Literal, Optional
import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange
from ta.trend import ADXIndicator, EMAIndicator
from ta.momentum import StochasticOscillator

TrendDir = Literal["UP","DOWN","FLAT"]

def _nan_to_none(x):
    return None if (x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))) else float(x)

def _supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series,
    period: int = 10, factor: float = 3.0
) -> Tuple[pd.Series, pd.Series]:
    """
    מחזיר (supertrend, direction) – direction: +1 למגמה עולה, -1 יורדת, NaN אם לא זמין.
    אימפלמנטציה קלילה, נטולת תלות חיצונית מעבר ל-ta. 
    """
    atr = AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()
    hl2 = (high + low) / 2.0
    upperband = hl2 + factor * atr
    lowerband = hl2 - factor * atr

    # טריילינג בנדים
    final_upper = upperband.copy()
    final_lower = lowerband.copy()
    for i in range(1, len(close)):
        final_upper.iat[i] = min(upperband.iat[i], final_upper.iat[i-1]) if close.iat[i-1] > final_upper.iat[i-1] else upperband.iat[i]
        final_lower.iat[i] = max(lowerband.iat[i], final_lower.iat[i-1]) if close.iat[i-1] < final_lower.iat[i-1] else lowerband.iat[i]

    st = pd.Series(index=close.index, dtype="float64")
    dir_ = pd.Series(index=close.index, dtype="float64")  # +1 / -1
    dir_.iat[0] = np.nan
    st.iat[0] = np.nan

    for i in range(1, len(close)):
        if close.iat[i] > final_upper.iat[i-1]:
            dir_.iat[i] = +1.0
        elif close.iat[i] < final_lower.iat[i-1]:
            dir_.iat[i] = -1.0
        else:
            dir_.iat[i] = dir_.iat[i-1]

        st.iat[i] = final_lower.iat[i] if dir_.iat[i] == +1.0 else final_upper.iat[i]

    return st, dir_

def _ichimoku(
    high: pd.Series, low: pd.Series,
    conv_len: int = 9, base_len: int = 26, span_b_len: int = 52
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    מחזיר (conversion, base, span_a, span_b).
    """
    conv = (high.rolling(conv_len).max() + low.rolling(conv_len).min()) / 2.0
    base = (high.rolling(base_len).max() + low.rolling(base_len).min()) / 2.0
    span_a = ((conv + base) / 2.0).shift(base_len)
    span_b = ((high.rolling(span_b_len).max() + low.rolling(span_b_len).min()) / 2.0).shift(base_len)
    return conv, base, span_a, span_b

def _market_structure(
    high: pd.Series, low: pd.Series, lookback: int = 5, piv_span: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """
    מזהה פיבוטים (swing highs/lows) ותגית אחרונה: HH/HL/LL/LH.
    מחזיר (label, trend) – trend: UP/DOWN/FLAT לפי רצף אחרון.
    """
    # פיבוטים בסיסיים
    ph = (high.shift(piv_span) < high) & (high.shift(-piv_span) < high)
    pl = (low.shift(piv_span) > low) & (low.shift(-piv_span) > low)

    piv_label = pd.Series(index=high.index, dtype=object)
    piv_label[ph] = "PH"
    piv_label[pl] = "PL"

    ms_label = pd.Series(index=high.index, dtype=object)
    ms_trend = pd.Series(index=high.index, dtype=object)

    last_h: Optional[float] = None
    last_l: Optional[float] = None
    last_type: Optional[str] = None

    for i in range(len(high)):
        lab = piv_label.iat[i]
        if lab == "PH":
            if last_h is not None:
                ms_label.iat[i] = "HH" if high.iat[i] > last_h else "LH"
            last_h = high.iat[i]
            last_type = "H"
        elif lab == "PL":
            if last_l is not None:
                ms_label.iat[i] = "HL" if low.iat[i] > last_l else "LL"
            last_l = low.iat[i]
            last_type = "L"

        # מגמה בקירוב: עדיפה UP אם HH/HL הופיע באחרונה, DOWN אם LH/LL
        recent = ms_label[max(0, i - lookback): i + 1]
        if ("HH" in (recent.values)) or ("HL" in (recent.values)):
            ms_trend.iat[i] = "UP"
        elif ("LL" in (recent.values)) or ("LH" in (recent.values)):
            ms_trend.iat[i] = "DOWN"
        else:
            ms_trend.iat[i] = "FLAT"

    return ms_label.fillna(""), ms_trend.fillna("FLAT")

def _stoch_rsi_like(close: pd.Series, window: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
    """
    Stoch “לייט”: משתמש ב־Stochastic (לא RSI) אבל נותן איתותים מספיק טובים למהירות.
    """
    # אם יש לך utils.indicators.prepare_indicators_for_backtest שמחשבת rsi – אפשר להשתמש בהדבקה משם.
    # כאן נבחר ב-Stochastic מהיר על HIGH/LOW/CLOSE (כבר מחושב בקבצים אצלך).
    # לשמירה על תאימות – נחשב מחדש (לא יקר).
    # נדרשת נוכחות עמודות high/low/close.
    st = StochasticOscillator(high=close.rolling(2).max(),  # קירוב – מפשט תלות
                              low=close.rolling(2).min(),
                              close=close, window=window, smooth_window=smooth_k)
    k = st.stoch()
    d = k.rolling(smooth_d).mean()
    return k, d

def add_extended_indicators(
    df: pd.DataFrame,
    *,
    ema_fast: int = 21,
    ema_slow: int = 50,
    adx_len: int = 14,
    st_period: int = 10,
    st_factor: float = 3.0,
    ichimoku_conv: int = 9, ichimoku_base: int = 26, ichimoku_span_b: int = 52,
    ms_lookback: int = 5, ms_pivot_span: int = 3,
) -> pd.DataFrame:
    """
    מוסיף עמודות:
      ema_fast, ema_slow, adx, atr
      supertrend, st_dir
      ichimoku_conv, ichimoku_base, ichimoku_span_a, ichimoku_span_b, ichimoku_state
      stoch_k, stoch_d
      ms_label, ms_trend
      trend_dir (UP/DOWN/FLAT), trending (bool)
    """
    if df is None or df.empty:
        return df

    work = df.copy()
    for c in ("open","high","low","close","volume"):
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work.dropna(inplace=True)

    close = work["close"]; high = work["high"]; low = work["low"]

    # בסיס
    work["ema_fast"] = EMAIndicator(close=close, window=ema_fast).ema_indicator()
    work["ema_slow"] = EMAIndicator(close=close, window=ema_slow).ema_indicator()
    work["adx"] = ADXIndicator(high=high, low=low, close=close, window=adx_len).adx()
    work["atr"] = AverageTrueRange(high=high, low=low, close=close, window=adx_len).average_true_range()

    # Supertrend
    st_val, st_dir = _supertrend(high, low, close, period=st_period, factor=st_factor)
    work["supertrend"] = st_val
    work["st_dir"] = st_dir  # +1 / -1

    # Ichimoku
    conv, base, span_a, span_b = _ichimoku(high, low, ichimoku_conv, ichimoku_base, ichimoku_span_b)
    work["ichimoku_conv"] = conv
    work["ichimoku_base"] = base
    work["ichimoku_span_a"] = span_a
    work["ichimoku_span_b"] = span_b

    def _ichimoku_state_row(i: int) -> str:
        c = work["close"].iat[i]
        a = work["ichimoku_span_a"].iat[i]
        b = work["ichimoku_span_b"].iat[i]
        if np.isnan(a) or np.isnan(b) or np.isnan(c):
            return ""
        top, bot = (a, b) if a >= b else (b, a)
        if c > top: return "BULL_ABOVE"
        if c < bot: return "BEAR_BELOW"
        return "IN_CLOUD"

    work["ichimoku_state"] = [ _ichimoku_state_row(i) for i in range(len(work)) ]

    # StochRSI-like
    k, d = _stoch_rsi_like(close)
    work["stoch_k"] = k
    work["stoch_d"] = d

    # Market Structure
    ms_label, ms_trend = _market_structure(high, low, lookback=ms_lookback, piv_span=ms_pivot_span)
    work["ms_label"] = ms_label
    work["ms_trend"] = ms_trend

    # מגמה מאוחדת
    def _trend_row(i: int) -> TrendDir:
        adx = work["adx"].iat[i]
        ef  = work["ema_fast"].iat[i]
        es  = work["ema_slow"].iat[i]
        sdir= work["st_dir"].iat[i]
        mstr= work["ms_trend"].iat[i]
        if any(np.isnan(v) for v in (adx, ef, es, sdir)) or not isinstance(mstr, str):
            return "FLAT"
        up_votes = int(ef > es) + int(sdir == 1.0) + int(mstr == "UP")
        dn_votes = int(ef < es) + int(sdir == -1.0) + int(mstr == "DOWN")
        if adx >= 20 and up_votes >= 2:
            return "UP"
        if adx >= 20 and dn_votes >= 2:
            return "DOWN"
        return "FLAT"

    work["trend_dir"] = [ _trend_row(i) for i in range(len(work)) ]
    work["trending"] = work["trend_dir"].isin(["UP","DOWN"])

    return work

def extended_score_last_row(row: pd.Series) -> Tuple[float, Optional[str], int, str]:
    """
    ניקוד 0..10 + side + confidence + reason קצר.
    """
    score = 5.0
    reason_bits = []

    ef = _nan_to_none(row.get("ema_fast"))
    es = _nan_to_none(row.get("ema_slow"))
    adx = _nan_to_none(row.get("adx"))
    atr = _nan_to_none(row.get("atr"))
    st_dir = _nan_to_none(row.get("st_dir"))
    ich = str(row.get("ichimoku_state") or "")
    k = _nan_to_none(row.get("stoch_k"))
    d = _nan_to_none(row.get("stoch_d"))
    ms = str(row.get("ms_label") or "")
    mstr = str(row.get("ms_trend") or "")
    close = _nan_to_none(row.get("close"))

    # EMA cross
    if ef is not None and es is not None:
        if ef > es: score += 1.0; reason_bits.append("ema↑")
        elif ef < es: score -= 1.0; reason_bits.append("ema↓")

    # ADX strength
    if adx is not None:
        if adx >= 25: score += 0.8; reason_bits.append(f"adx≥25")
        elif adx < 18: score -= 0.5; reason_bits.append("adx<18")

    # Supertrend direction
    if st_dir == 1.0: score += 0.7; reason_bits.append("st=UP")
    elif st_dir == -1.0: score -= 0.7; reason_bits.append("st=DOWN")

    # Ichimoku state
    if ich == "BULL_ABOVE": score += 0.6; reason_bits.append("ichi>cloud")
    elif ich == "BEAR_BELOW": score -= 0.6; reason_bits.append("ichi<cloud")

    # StochRSI momentum
    if k is not None and d is not None:
        if k > d and (k < 80): score += 0.4; reason_bits.append("stoch↑")
        elif k < d and (k > 20): score -= 0.4; reason_bits.append("stoch↓")

    # Market structure
    if mstr == "UP" and (ms in ("HH","HL")):
        score += 0.7; reason_bits.append("MS↑")
    elif mstr == "DOWN" and (ms in ("LL","LH")):
        score -= 0.7; reason_bits.append("MS↓")

    # גבולות
    score = max(0.0, min(10.0, score))

    # כיוון/בטחון
    side: Optional[str] = None
    if score >= 6.6: side = "LONG"
    elif score <= 3.4: side = "SHORT"

    conf = 70
    if score >= 8.5 or score <= 1.5: conf = 90
    elif score >= 7.5 or score <= 2.5: conf = 80

    reason = " ".join(reason_bits[:6])
    return round(score, 2), side, conf, reason

