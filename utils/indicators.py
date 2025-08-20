# utils/indicators.py
import pandas as pd
import numpy as np

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    roll_up = pd.Series(gain).rolling(period).mean()
    roll_down = pd.Series(loss).rolling(period).mean()
    rs = roll_up / roll_down
    return 100.0 - (100.0 / (1.0 + rs))

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    plus_dm = df["high"].diff()
    minus_dm = df["low"].diff().abs()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = atr(df, period)
    plus_di = 100 * (plus_dm.rolling(period).sum() / tr)
    minus_di = 100 * (minus_dm.rolling(period).sum() / tr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(period).mean()

def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["ema21"] = ema(df["close"], 21)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df)
    df["adx"] = adx(df)
    return df



































