# utils/indicators_ext.py
from __future__ import annotations
from typing import Optional
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import StochasticOscillator

from utils.indicators import prepare_indicators_for_backtest

def add_extended_indicators(
    df: pd.DataFrame,
    *, ema_fast: int = 21, ema_slow: int = 50, adx_len: int = 14,
    st_period: int = 10, st_factor: float = 3.0,  # שמור לפרמטריות עתידית
    ichimoku_conv: int = 9, ichimoku_base: int = 26, ichimoku_span_b: int = 52,
    ms_lookback: int = 5, ms_pivot_span: int = 3,
) -> pd.DataFrame:
    base = prepare_indicators_for_backtest(df)
    if base.empty:
        return base

    close = base["close"]; high = base["high"]; low = base["low"]

    base["ema_fast"] = EMAIndicator(close, window=int(ema_fast)).ema_indicator()
    base["ema_slow"] = EMAIndicator(close, window=int(ema_slow)).ema_indicator()
    base["adx"] = ADXIndicator(high=high, low=low, close=close, window=int(adx_len)).adx()

    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    base["stoch_k"] = stoch.stoch()
    base["stoch_d"] = stoch.stoch_signal()

    # טרנד פשוט + כיוון
    base["trending"] = (base["adx"] > 20) & (abs(base["ema_fast"] - base["ema_slow"]) / base["close"] > 0.002)
    base["trend_dir"] = pd.Series("FLAT", index=base.index)
    base.loc[base["ema_fast"] > base["ema_slow"], "trend_dir"] = "UP"
    base.loc[base["ema_fast"] < base["ema_slow"], "trend_dir"] = "DOWN"

    # placeholders קריאים:
    base["ichimoku_state"] = "NEUTRAL"
    base["ms_trend"] = base["trend_dir"]
    base["supertrend"] = base["ema_fast"]  # placeholder עד למימוש מלא

    return base

def extended_score_last_row(row: pd.Series) -> tuple[float, str, int, str]:
    """
    ציון 0..10, כיוון LONG/SHORT, אמון 0..100, ורציונל קצר.
    """
    adx = float(row.get("adx") or 0.0)
    ema_fast = float(row.get("ema_fast") or 0.0)
    ema_slow = float(row.get("ema_slow") or 0.0)
    dir_ = str(row.get("trend_dir") or "FLAT")
    trending = bool(row.get("trending") is True)

    # בסיס: הפרדת EMA + ADX
    sep = abs(ema_fast - ema_slow) / max(1e-9, float(row.get("close") or 1.0))
    score = 10.0 * min(1.0, (adx / 40.0) * (sep / 0.01 + 0.2))

    side = "LONG" if ema_fast >= ema_slow else "SHORT"
    if not trending:
        score *= 0.6

    conf = int(max(0, min(100, adx * 2)))
    reason = f"{dir_} ema_fast={ema_fast:.4f} ema_slow={ema_slow:.4f} adx={adx:.1f}"

    return round(score, 2), side, conf, reason








