# utils/indicators.py
import pandas as pd
import numpy as np

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    roll_up = pd.Series(gain, index=series.index).rolling(period).mean()
    roll_down = pd.Series(loss, index=series.index).rolling(period).mean()
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
    minus_dm = -df["low"].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = atr(df, period)
    plus_di = 100 * (plus_dm.rolling(period).sum() / tr.rolling(period).sum())
    minus_di = 100 * (minus_dm.rolling(period).sum() / tr.rolling(period).sum())
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(period).mean()

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def bollinger_bands(series: pd.Series, period: int = 20, std_factor: float = 2.0):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + std_factor * std
    lower = sma - std_factor * std
    return sma, upper, lower

def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()

    # EMA
    df["ema21"] = ema(df["close"], 21)
    df["ema50"] = ema(df["close"], 50)

    # RSI
    df["rsi"] = rsi(df["close"], 14)

    # ATR + ADX
    df["atr"] = atr(df)
    df["adx"] = adx(df)

    # MACD
    macd_line, signal_line, hist = macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = hist

    # Bollinger Bands
    mid, upper, lower = bollinger_bands(df["close"])
    df["bb_mid"] = mid
    df["bb_upper"] = upper
    df["bb_lower"] = lower

    return df



































