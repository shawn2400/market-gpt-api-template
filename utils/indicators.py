# utils/indicators_utils.py
from __future__ import annotations
import pandas as pd
import numpy as np
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
    work.dropna(inplace=True)

    close = work["close"]; high = work["high"]; low = work["low"]; vol = work["volume"]

    work["rsi"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    work["macd_hist"] = macd.macd_diff()
    work["ema_21"] = EMAIndicator(close=close, window=21).ema_indicator()
    work["adx"] = ADXIndicator(high=high, low=low, close=close, window=14).adx()
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    work["stoch_k"] = stoch.stoch()
    work["atr"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    # נפחים:
    work["volume_mean"] = vol.rolling(30, min_periods=5).mean()
    obv = OnBalanceVolumeIndicator(close=close, volume=vol).on_balance_volume()
    work["obv"] = obv
    work["obv_trend"] = obv.diff().rolling(5).mean() > 0

    # VWAP טרנד פשוט (אינדיקציה):
    tp = (high + low + close) / 3.0
    vwap = (tp * vol).cumsum() / (vol.replace(0, np.nan)).cumsum()
    work["vwap"] = vwap
    work["vwap_trend"] = (close > vwap)

    # תאריכים
    if "timestamp" not in work.columns and "open_time" in work.columns:
        work.rename(columns={"open_time": "timestamp"}, inplace=True)

    return work






























