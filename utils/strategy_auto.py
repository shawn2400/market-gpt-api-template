# utils/strategy_auto.py
from __future__ import annotations
import os
from typing import Tuple

import pandas as pd

try:
    from utils.binance_client import get_klines_df
except Exception:
    def get_klines_df(symbol: str, interval: str = "15m", limit: int = 120):
        return None

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _pick_by_ema(df: pd.DataFrame) -> Tuple[str, str, str]:
    """EMA21>EMA50 → LONG, אחרת SHORT."""
    close = df["close"].astype(float)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)
    is_long = bool(ema21.iloc[-1] > ema50.iloc[-1])
    side = "BUY" if is_long else "SELL"
    position_side = "LONG" if is_long else "SHORT"
    reason = f"ema21_vs_ema50:{ema21.iloc[-1]:.2f}>{ema50.iloc[-1]:.2f}" if is_long else f"ema21_vs_ema50:{ema21.iloc[-1]:.2f}<={ema50.iloc[-1]:.2f}"
    return side, position_side, reason

def _fallback_pick() -> Tuple[str, str, str]:
    # ברירת מחדל שמרנית
    return "BUY", "LONG", "fallback_default"

async def pick_side_for_symbol(symbol: str) -> Tuple[str, str, str]:
    """
    מחזיר (side, position_side, reason)
    side: BUY/SELL, position_side: LONG/SHORT
    """
    sym = symbol.upper()
    interval = os.getenv("DEFAULT_INTERVAL", "15m")
    try:
        df = get_klines_df(sym, interval=interval, limit=120)
        if df is None or getattr(df, "empty", False):
            return _fallback_pick()
        return _pick_by_ema(df)
    except Exception:
        return _fallback_pick()

