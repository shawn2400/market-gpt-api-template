# utils/indicators.py
import numpy as np
import pandas as pd
import logging

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, MACD, EMAIndicator
from ta.volatility import AverageTrueRange

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

def _ensure_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        missing = need - set(df.columns)
        logging.warning(f"[indicators] חסרות עמודות לבסיס: {missing}")
        return pd.DataFrame()
    out = df.copy()
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if not isinstance(out.index, pd.DatetimeIndex):
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
            out.set_index("timestamp", inplace=True)
        else:
            out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    out.sort_index(inplace=True)
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)
    return out

def _supertrend(df: pd.DataFrame, period: int = _ST_PERIOD, multiplier: float = _ST_MULT) -> pd.Series:
    atr = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"],
        window=period, fillna=True
    ).average_true_range()

    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper = upper_basic.copy()
    lower = lower_basic.copy()

    # במקום fillna(method="ffill")
    upper.ffill(inplace=True)
    lower.ffill(inplace=True)

    st = pd.Series(index=df.index, dtype=float)
    dir_up = True
    for i in range(len(df)):
        if i == 0:
            st.iloc[i] = lower.iloc[i] if df["close"].iloc[i] >= lower.iloc[i] else upper.iloc[i]
            dir_up = df["close"].iloc[i] >= lower.iloc[i]
            continue

        prev_st = st.iloc[i - 1]
        if df["close"].iloc[i] > prev_st:
            dir_up = True
        elif df["close"].iloc[i] < prev_st:
            dir_up = False

        st.iloc[i] = lower.iloc[i] if dir_up else upper.iloc[i]

    # במקום fillna(method="ffill")
    st.ffill(inplace=True)
    return st

def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, np.nan)
    cum_vol = vol.cumsum()
    vwap = (tp * vol).cumsum() / cum_vol
    return vwap

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    base = _ensure_df(df)
    if base.empty:
        return pd.DataFrame()
    if len(base) < 100:
        logging.warning(f"[indicators] מעט מדי נרות ({len(base)}). דרוש לפחות 100.")
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

        # SuperTrend
        st_line = _supertrend(out, period=_ST_PERIOD, multiplier=_ST_MULT)
        out["supertrend"] = st_line
        out["supertrend_dir"] = np.where(out["close"] >= st_line, 1, -1)

        # ניקוי ותיקון NaN/Inf
        cols_needed = [
            "rsi", "adx", "atr", "macd", "macd_signal", "macd_hist",
            "ema_21", "ema_50", "vwap", "supertrend", "supertrend_dir"
        ]
        out.replace([np.inf, -np.inf], np.nan, inplace=True)
        out[cols_needed] = out[cols_needed].ffill().bfill()
        out.dropna(subset=cols_needed, inplace=True)

        if out.empty:
            logging.warning("[indicators] לאחר חישוב וניקוי – אין נתונים. מחזיר ריק.")
            return pd.DataFrame()

        # שדה דמה לתבנית (אם יש לך מחולל דפוסים – תוכל לעדכן כאן)
        out["pattern"] = "unknown"
        return out
    except Exception as e:
        logging.error(f"[indicators] שגיאה בחישוב אינדיקטורים: {e}", exc_info=True)
        return pd.DataFrame()



















