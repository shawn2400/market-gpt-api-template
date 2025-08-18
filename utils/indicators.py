# utils/indicators.py
from __future__ import annotations
import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volume import OnBalanceVolumeIndicator
from ta.volatility import AverageTrueRange

def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    for c in ("open","high","low","close","volume"):
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work.dropna(subset=["open","high","low","close","volume"], inplace=True)
    if work.empty:
        return pd.DataFrame()

    close = work["close"]; high = work["high"]; low = work["low"]; vol = work["volume"]

    work["rsi"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    work["macd"] = macd.macd()
    work["macd_sig"] = macd.macd_signal()
    work["macd_hist"] = macd.macd_diff()
    work["ema_21"] = EMAIndicator(close=close, window=21).ema_indicator()
    work["ema_50"] = EMAIndicator(close=close, window=50).ema_indicator()
    work["adx"] = ADXIndicator(high=high, low=low, close=close, window=14).adx()
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    work["stoch_k"] = stoch.stoch()
    work["stoch_d"] = stoch.stoch_signal()
    work["atr"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    work["volume_mean"] = vol.rolling(30, min_periods=5).mean()
    obv = OnBalanceVolumeIndicator(close=close, volume=vol).on_balance_volume()
    work["obv"] = obv
    work["obv_trend_up"] = obv.diff().rolling(5, min_periods=1).mean() > 0

    tp = (high + low + close) / 3.0
    vwap = (tp * vol).cumsum() / (vol.replace(0, np.nan)).cumsum()
    work["vwap"] = vwap
    work["vwap_trend_up"] = (close > vwap)

    if "timestamp" not in work.columns:
        if "open_time" in work.columns: work.rename(columns={"open_time": "timestamp"}, inplace=True)
        elif "openTime" in work.columns: work.rename(columns={"openTime": "timestamp"}, inplace=True)
    return work

# תאימות לאחור ללוגים/יבוא קיימים:
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return prepare_indicators_for_backtest(df)

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return prepare_indicators_for_backtest(df)

__all__ = ["prepare_indicators_for_backtest", "compute_indicators", "add_indicators"]
































