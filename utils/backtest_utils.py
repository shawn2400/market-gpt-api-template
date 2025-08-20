# utils/backtest_utils.py
from __future__ import annotations
"""
מודול backtester – אחראי על הרצת backtest אסטרטגיות.
משמש על ידי routes/backtest.py.
"""

import pandas as pd
from typing import Dict, Any, Optional, List

from utils.indicators import prepare_indicators_for_backtest


def _strategy_ema_crossover(df: pd.DataFrame) -> List[Dict[str, Any]]:
    trades = []
    position: Optional[Dict[str, Any]] = None
    balance = 1000.0

    for i in range(50, len(df)):
        row = df.iloc[i]
        close, ema21, ema50 = float(row["close"]), float(row["ema21"]), float(row["ema50"])

        if ema21 > ema50 and not position:
            position = {"side": "LONG", "entry": close}
        elif ema21 < ema50 and position and position["side"] == "LONG":
            pnl = (close - position["entry"]) / position["entry"]
            balance *= (1 + pnl)
            trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": pnl})
            position = None
    return trades


def _strategy_rsi(df: pd.DataFrame, overbought: int = 70, oversold: int = 30) -> List[Dict[str, Any]]:
    trades = []
    position: Optional[Dict[str, Any]] = None
    balance = 1000.0

    for i in range(14, len(df)):
        row = df.iloc[i]
        close, rsi = float(row["close"]), float(row["rsi"])

        if rsi < oversold and not position:
            position = {"side": "LONG", "entry": close}
        elif rsi > overbought and position and position["side"] == "LONG":
            pnl = (close - position["entry"]) / position["entry"]
            balance *= (1 + pnl)
            trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": pnl})
            position = None
    return trades


def _strategy_bollinger(df: pd.DataFrame) -> List[Dict[str, Any]]:
    trades = []
    position: Optional[Dict[str, Any]] = None
    balance = 1000.0

    for i in range(20, len(df)):
        row = df.iloc[i]
        close, upper, lower = float(row["close"]), float(row["bb_upper"]), float(row["bb_lower"])

        if close < lower and not position:
            position = {"side": "LONG", "entry": close}
        elif close > upper and position and position["side"] == "LONG":
            pnl = (close - position["entry"]) / position["entry"]
            balance *= (1 + pnl)
            trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": pnl})
            position = None
    return trades


def run_backtest(df: pd.DataFrame, strategy: str = "ema_crossover") -> Dict[str, Any]:
    """
    מריץ Backtest לפי אסטרטגיה נבחרת על DataFrame.
    df חייב להכיל עמודות [open, high, low, close, volume]
    """
    if df is None or df.empty:
        return {"ok": False, "error": "empty dataframe"}

    df = prepare_indicators_for_backtest(df)

    if strategy == "ema_crossover":
        trades = _strategy_ema_crossover(df)
    elif strategy == "rsi":
        trades = _strategy_rsi(df)
    elif strategy == "bollinger":
        trades = _strategy_bollinger(df)
    else:
        return {"ok": False, "error": f"unknown strategy: {strategy}"}

    balance = 1000.0
    for t in trades:
        balance *= (1 + t["pnl"])

    return {
        "ok": True,
        "strategy": strategy,
        "final_balance": round(balance, 2),
        "profit_pct": round(((balance / 1000.0) - 1) * 100, 2),
        "n_trades": len(trades),
        "trades": trades[-10:],  # רק 10 אחרונים
    }


  















