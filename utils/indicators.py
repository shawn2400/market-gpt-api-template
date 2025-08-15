# utils/indicators.py
import numpy as np
import pandas as pd
import logging
from typing import Optional, List, Dict

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, MACD, EMAIndicator
from ta.volatility import AverageTrueRange

# --- פרמטרים דיפולטיים ---
_RSI = 14
_ADX = 14
_ATR = 14
_EMA_FAST = 21
_EMA_SLOW = 50
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_ST_PERIOD = 10
_ST_MULT = 3.0

_MIN_ROWS_ABS = 100  # מינימום כללי
_LONGEST_WIN = max(_EMA_SLOW, _MACD_SLOW, _ATR, _ADX, _RSI, _ST_PERIOD) + 20


def _ensure_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """מאחד, מנרמל ומוודא שה־DataFrame מוכן לחישוב אינדיקטורים."""
    if df is None or df.empty:
        return pd.DataFrame()

    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        missing = need - set(df.columns)
        logging.warning(f"[indicators] חסרות עמודות לבסיס: {missing}")
        return pd.DataFrame()

    out = df.copy()

    # המרת סוגי נתונים
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")

    # אינדקס זמן
    if not isinstance(out.index, pd.DatetimeIndex):
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
            out.set_index("timestamp", inplace=True)
        else:
            out.index = pd.to_datetime(out.index, utc=True, errors="coerce")

    out.sort_index(inplace=True)
    out = out[~out.index.duplicated(keep="last")]

    # ניקוי ראשוני
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)

    return out


def _enough_rows(df: pd.DataFrame) -> bool:
    n = len(df)
    if n < _MIN_ROWS_ABS or n < _LONGEST_WIN:
        logging.warning(f"[indicators] מעט מדי נרות ({n}). דרוש לפחות max({_MIN_ROWS_ABS}, {_LONGEST_WIN})")
        return False
    return True


def _supertrend(df: pd.DataFrame, period: int = _ST_PERIOD, multiplier: float = _ST_MULT) -> pd.Series:
    """חישוב קו SuperTrend בסיסי מבוסס ATR."""
    atr = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"],
        window=period, fillna=True
    ).average_true_range()

    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper = upper_basic.copy().ffill()
    lower = lower_basic.copy().ffill()

    st = pd.Series(index=df.index, dtype="float64")
    # מצב התחלתי
    close0 = df["close"].iloc[0]
    lower0 = lower.iloc[0]
    upper0 = upper.iloc[0]
    dir_up = close0 >= lower0
    st.iloc[0] = lower0 if dir_up else upper0

    closes = df["close"].to_numpy()
    up_vals = upper.to_numpy()
    low_vals = lower.to_numpy()

    for i in range(1, len(df)):
        prev_st = st.iloc[i - 1]
        c = closes[i]
        if c > prev_st:
            dir_up = True
        elif c < prev_st:
            dir_up = False
        st.iloc[i] = low_vals[i] if dir_up else up_vals[i]

    return st.ffill()


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype("float64")
    vol = vol.where(vol > 0, np.nan)
    cum_vol = vol.cumsum()
    vwap = (tp * vol).cumsum() / cum_vol
    return vwap


# ---------- זיהוי תבניות נרות ----------
def _body(o: pd.Series, c: pd.Series) -> pd.Series:
    return (c - o).abs()

def _is_bull(o, c) -> pd.Series:  # ירוק
    return c > o

def _is_bear(o, c) -> pd.Series:  # אדום
    return c < o

def _wick_upper(h, o, c) -> pd.Series:
    return h - np.maximum(o, c)

def _wick_lower(l, o, c) -> pd.Series:
    return np.minimum(o, c) - l

def _pct_of(x: pd.Series, base: pd.Series, eps: float = 1e-12) -> pd.Series:
    return x / (base.replace(0, eps))

def _patterns_all(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    מחזיר מילון עם מסכות (Series[bool]) לכל תבנית + 'pattern' כמחרוזת.
    תבניות: Doji, Bullish Engulfing, Bearish Engulfing, Hammer, Inverted Hammer, Shooting Star,
            Morning Star, Evening Star.
    """
    o = df["open"]; h = df["high"]; l = df["low"]; c = df["close"]
    rng = (h - l).replace(0, np.nan)
    body = _body(o, c)
    u = _wick_upper(h, o, c)
    d = _wick_lower(l, o, c)

    # ספים יחסיים לגודל הנר
    body_small = _pct_of(body, rng) <= 0.15     # גוף קטן מאד
    body_large = _pct_of(body, rng) >= 0.6      # גוף גדול
    upper_long = _pct_of(u, rng) >= 0.6
    lower_long = _pct_of(d, rng) >= 0.6

    is_bull = _is_bull(o, c)
    is_bear = _is_bear(o, c)

    # Doji
    doji = body_small

    # Engulfing (דורש נר קודם)
    o_prev = o.shift(1); c_prev = c.shift(1)
    prev_bull = (c_prev > o_prev)
    prev_bear = (c_prev < o_prev)
    bullish_engulf = is_bull & prev_bear & (o <= c_prev) & (c >= o_prev)
    bearish_engulf = is_bear & prev_bull & (o >= c_prev) & (c <= o_prev)

    # Hammer / Inverted Hammer / Shooting Star
    hammer = lower_long & (~upper_long) & (body > 0) & (_pct_of(body, rng) <= 0.35)
    inv_hammer = upper_long & (~lower_long) & (body > 0) & (_pct_of(body, rng) <= 0.35) & is_bull
    shooting_star = upper_long & (~lower_long) & (body > 0) & (_pct_of(body, rng) <= 0.35) & is_bear

    # Morning/Evening Star (3 נרות בסיסי)
    o_prev2 = o.shift(2); c_prev2 = c.shift(2)
    rng_prev2 = (h.shift(2) - l.shift(2)).replace(0, np.nan)
    large_prev2 = _pct_of(_body(o_prev2, c_prev2), rng_prev2) >= 0.5
    small_body_prev = _pct_of(_body(o_prev, c_prev), (h.shift(1) - l.shift(1)).replace(0, np.nan)) <= 0.25

    morning_star = (
        large_prev2 & (c_prev2 < o_prev2) &   # נר 1 אדום גדול
        small_body_prev &                     # נר 2 קטן/דוג'י
        is_bull & body_large &                # נר 3 ירוק גדול
        (c >= (o_prev2 + c_prev2) / 2)        # סגירה מעל חצי הגוף של נר 1
    )

    evening_star = (
        large_prev2 & (c_prev2 > o_prev2) &   # נר 1 ירוק גדול
        small_body_prev &                     # נר 2 קטן/דוג'י
        is_bear & body_large &                # נר 3 אדום גדול
        (c <= (o_prev2 + c_prev2) / 2)        # סגירה מתחת לחצי הגוף של נר 1
    )

    # מחרוזת תבניות משולבת לכל שורה
    names = [
        ("Doji", doji),
        ("Bullish Engulfing", bullish_engulf),
        ("Bearish Engulfing", bearish_engulf),
        ("Hammer", hammer),
        ("Inverted Hammer", inv_hammer),
        ("Shooting Star", shooting_star),
        ("Morning Star", morning_star),
        ("Evening Star", evening_star),
    ]

    labdf = pd.DataFrame({n: m.fillna(False) for n, m in names}, index=df.index)

    def _join_row(row: pd.Series) -> str:
        xs = [name for name, on in zip(labdf.columns, row.values) if bool(on)]
        return ", ".join(xs) if xs else "unknown"

    pattern_str = labdf.apply(_join_row, axis=1)

    out: Dict[str, pd.Series] = {f"is_{n.lower().replace(' ', '_')}": m for n, m in names}
    out["pattern"] = pattern_str
    return out


def compute_indicators(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    מחזיר DataFrame עם העמודות:
    rsi, adx, atr, macd, macd_signal, macd_hist, ema_21, ema_50, vwap,
    supertrend, supertrend_dir, volume_mean, pattern,
    is_doji, is_bullish_engulfing, is_bearish_engulfing, is_hammer,
    is_inverted_hammer, is_shooting_star, is_morning_star, is_evening_star, trend

    אם אין מספיק נתונים – מחזיר DF ריק.
    """
    base = _ensure_df(df)
    if base.empty:
        return pd.DataFrame()
    if not _enough_rows(base):
        return pd.DataFrame()

    out = base.copy()
    try:
        # EMA
        out["ema_21"] = EMAIndicator(close=out["close"], window=_EMA_FAST, fillna=True).ema_indicator()
        out["ema_50"] = EMAIndicator(close=out["close"], window=_EMA_SLOW, fillna=True).ema_indicator()

        # RSI
        out["rsi"] = RSIIndicator(close=out["close"], window=_RSI, fillna=True).rsi()

        # ADX
        adx_ind = ADXIndicator(high=out["high"], low=out["low"], close=out["close"], window=_ADX, fillna=True)
        out["adx"] = adx_ind.adx()

        # ATR
        out["atr"] = AverageTrueRange(
            high=out["high"], low=out["low"], close=out["close"], window=_ATR, fillna=True
        ).average_true_range()

        # MACD
        macd = MACD(
            close=out["close"],
            window_fast=_MACD_FAST,
            window_slow=_MACD_SLOW,
            window_sign=_MACD_SIGNAL,
            fillna=True
        )
        out["macd"] = macd.macd()
        out["macd_signal"] = macd.macd_signal()
        out["macd_hist"] = macd.macd_diff()

        # VWAP
        out["vwap"] = _vwap(out)

        # SuperTrend + כיוון
        st_line = _supertrend(out, period=_ST_PERIOD, multiplier=_ST_MULT)
        out["supertrend"] = st_line
        out["supertrend_dir"] = np.where(out["close"] >= st_line, 1, -1).astype("int8")

        # ממוצע נפח
        out["volume_mean"] = out["volume"].rolling(50, min_periods=1).mean()

        # תבניות נרות (מחרוזת + דגלים)
        try:
            pats = _patterns_all(out)
            # pattern string
            out["pattern"] = pats["pattern"].astype("string")
            # דגלים בינאריים 0/1
            for col, mask in pats.items():
                if col == "pattern":
                    continue
                out[col] = mask.fillna(False).astype("int8")
        except Exception as e:
            logging.debug(f"[indicators] pattern detection skipped: {e}")
            out["pattern"] = "unknown"
            # דגלים בינאריים כברירת מחדל 0
            for col in (
                "is_doji", "is_bullish_engulfing", "is_bearish_engulfing",
                "is_hammer", "is_inverted_hammer", "is_shooting_star",
                "is_morning_star", "is_evening_star"
            ):
                out[col] = np.int8(0)

        # ניקוי NaN/Inf
        cols_needed = [
            "rsi", "adx", "atr", "macd", "macd_signal", "macd_hist",
            "ema_21", "ema_50", "vwap", "supertrend", "supertrend_dir", "volume_mean"
        ]
        out.replace([np.inf, -np.inf], np.nan, inplace=True)
        out[cols_needed] = out[cols_needed].ffill().bfill()
        out.dropna(subset=cols_needed, inplace=True)

        if out.empty:
            logging.warning("[indicators] לאחר חישוב וניקוי – אין נתונים. מחזיר ריק.")
            return pd.DataFrame()

        # --- נגזרת מגמה 'trend' לשימוש בשכבות אחרות ---
        # היגיון: UP אם ema21>ema50 וגם close>ema21; DOWN אם ema21<ema50 וגם close<ema21; אחרת SIDEWAYS
        cond_up = (out["ema_21"] > out["ema_50"]) & (out["close"] > out["ema_21"])
        cond_dn = (out["ema_21"] < out["ema_50"]) & (out["close"] < out["ema_21"])
        trend_series = pd.Series("SIDEWAYS", index=out.index, dtype="string")
        trend_series[cond_up] = "UP"
        trend_series[cond_dn] = "DOWN"
        out["trend"] = trend_series

        return out

    except Exception as e:
        logging.error(f"[indicators] שגיאה בחישוב אינדיקטורים: {e}", exc_info=True)
        return pd.DataFrame()



























