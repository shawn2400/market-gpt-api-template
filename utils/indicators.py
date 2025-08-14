import numpy as np
import pandas as pd
import logging
from typing import Optional

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, MACD, EMAIndicator
from ta.volatility import AverageTrueRange

# --- פרמטרים ---
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

_MIN_ROWS_ABS = 100
_LONGEST_WIN = max(_EMA_SLOW, _MACD_SLOW, _ATR, _ADX, _RSI, _ST_PERIOD) + 20

def _ensure_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(df.columns):
        logging.warning(f"[indicators] חסרות עמודות: {needed - set(df.columns)}")
        return pd.DataFrame()

    df = df.copy()

    # טיפוסים
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # אינדקס זמן
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df.set_index("timestamp", inplace=True)
        else:
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")

    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="last")]

    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)

    return df

def _enough_rows(df: pd.DataFrame) -> bool:
    if len(df) < max(_MIN_ROWS_ABS, _LONGEST_WIN):
        logging.warning(f"[indicators] מעט מדי נרות: {len(df)}")
        return False
    return True

def _supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.Series:
    atr = AverageTrueRange(df["high"], df["low"], df["close"], window=period, fillna=True).average_true_range()
    hl2 = (df["high"] + df["low"]) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    st = pd.Series(index=df.index, dtype="float64")
    dir_up = df["close"].iloc[0] >= lower.iloc[0]
    st.iloc[0] = lower.iloc[0] if dir_up else upper.iloc[0]

    for i in range(1, len(df)):
        prev_st = st.iloc[i - 1]
        close = df["close"].iloc[i]
        dir_up = close > prev_st if close != prev_st else dir_up
        st.iloc[i] = lower.iloc[i] if dir_up else upper.iloc[i]

    return st.ffill()

def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"]
    cum_vol = volume.cumsum()
    cum_tp_vol = (tp * volume).cumsum()
    return cum_tp_vol / cum_vol

def compute_indicators(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    base = _ensure_df(df)
    if base.empty or not _enough_rows(base):
        return pd.DataFrame()

    try:
        df = base.copy()

        df["ema_21"] = EMAIndicator(df["close"], window=_EMA_FAST, fillna=True).ema_indicator()
        df["ema_50"] = EMAIndicator(df["close"], window=_EMA_SLOW, fillna=True).ema_indicator()
        df["rsi"] = RSIIndicator(df["close"], window=_RSI, fillna=True).rsi()
        df["adx"] = ADXIndicator(df["high"], df["low"], df["close"], window=_ADX, fillna=True).adx()
        df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"], window=_ATR, fillna=True).average_true_range()

        macd = MACD(df["close"], window_fast=_MACD_FAST, window_slow=_MACD_SLOW, window_sign=_MACD_SIGNAL, fillna=True)
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_hist"] = macd.macd_diff()

        df["vwap"] = _vwap(df)
        st = _supertrend(df, period=_ST_PERIOD, multiplier=_ST_MULT)
        df["supertrend"] = st
        df["supertrend_dir"] = np.where(df["close"] >= st, 1, -1).astype("int8")

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        fields = [
            "rsi", "adx", "atr", "macd", "macd_signal", "macd_hist",
            "ema_21", "ema_50", "vwap", "supertrend", "supertrend_dir"
        ]
        df[fields] = df[fields].ffill().bfill()
        df.dropna(subset=fields, inplace=True)

        if df.empty:
            logging.warning("[indicators] אין נתונים לאחר חישוב וניקוי.")
            return pd.DataFrame()

        df["pattern"] = "unknown"
        return df

    except Exception as e:
        logging.exception("[indicators] שגיאה בעת חישוב אינדיקטורים")
        return pd.DataFrame()





















