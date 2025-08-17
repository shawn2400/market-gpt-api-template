from __future__ import annotations
import math
import time
from typing import Dict, Any, List

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

from utils.scanner_utils import fetch_ohlcv

def _to_float(x, d=0.0) -> float:
    try:
        v = float(x)
        if v != v or math.isinf(v):
            return d
        return v
    except Exception:
        return d

async def run_backtest_for_symbol(
    *,
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
    slippage_pct: float = 0.1,
) -> Dict[str, Any]:
    df = await fetch_ohlcv(symbol.upper(), interval=timeframe, limit=limit)
    if df.empty or len(df) < 60:
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "trades": [],
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "count": 0,
        }

    close = df["close"]
    ema21 = EMAIndicator(close=close, window=21).ema_indicator()
    rsi14 = RSIIndicator(close=close, window=14).rsi()

    trades: List[Dict[str, Any]] = []
    pos: Dict[str, Any] | None = None  # {"side": "LONG"/"SHORT", "entry": float, "ts": int, "bars": int}

    for i in range(len(df)):
        c = _to_float(close.iloc[i])
        ts = int(df.index[i].timestamp())
        if i < 30 or c <= 0:
            continue
        ema = _to_float(ema21.iloc[i])
        rsi = _to_float(rsi14.iloc[i])
        # אותות פשוטים
        long_sig = c > ema and rsi >= 55
        short_sig = c < ema and rsi <= 45

        # יציאה: היפוך אות או מקסימום 6 נרות
        if pos:
            exit_now = False
            if pos["side"] == "LONG" and short_sig:
                exit_now = True
            elif pos["side"] == "SHORT" and long_sig:
                exit_now = True
            elif pos["bars"] >= 6:
                exit_now = True
            if exit_now:
                entry = _to_float(pos["entry"])
                pnl = (c - entry) if pos["side"] == "LONG" else (entry - c)
                trades.append({"timestamp": ts, "price": c, "side": pos["side"], "pnl": round(pnl, 6)})
                pos = None
                continue
            pos["bars"] += 1
            continue

        # כניסה
        if long_sig:
            pos = {"side": "LONG", "entry": c, "ts": ts, "bars": 0}
        elif short_sig:
            pos = {"side": "SHORT", "entry": c, "ts": ts, "bars": 0}

    # אם נשארה פוזיציה פתוחה – נסגור במחיר אחרון
    if pos:
        c = _to_float(close.iloc[-1])
        entry = _to_float(pos["entry"])
        pnl = (c - entry) if pos["side"] == "LONG" else (entry - c)
        trades.append({"timestamp": int(time.time()), "price": c, "side": pos["side"], "pnl": round(pnl, 6)})

    total = sum(_to_float(t["pnl"]) for t in trades)
    wins = sum(1 for t in trades if _to_float(t["pnl"]) > 0)
    count = len(trades)
    win_rate = (wins / count * 100.0) if count else 0.0

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "trades": trades,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total, 6),
        "count": count,
    }














