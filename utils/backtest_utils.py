# utils/backtester.py
from __future__ import annotations
"""
מודול backtester – אחראי על הרצת backtest אסטרטגיות.
משמש על ידי routes/backtest.py.
"""
import pandas as pd
from typing import Dict, Any, Optional

from utils.indicators import prepare_indicators_for_backtest

def run_backtest(df: pd.DataFrame, strategy: str = "ema_crossover") -> Dict[str, Any]:
    """
    מבצע Backtest על DataFrame נתון עם אסטרטגיה פשוטה.
    df חייב להכיל עמודות: [open, high, low, close, volume]
    """
    if df is None or df.empty:
        return {"ok": False, "error": "empty dataframe"}

    df = prepare_indicators_for_backtest(df)

    trades = []
    balance = 1000.0  # capital התחלתי
    position: Optional[Dict[str, Any]] = None

    for i in range(50, len(df)):
        row = df.iloc[i]
        close = float(row["close"])
        ema21 = float(row["ema21"])
        ema50 = float(row["ema50"])

        # כניסה ל־LONG
        if ema21 > ema50 and not position:
            position = {"side": "LONG", "entry": close, "index": i}

        # סגירה של LONG
        elif ema21 < ema50 and position and position["side"] == "LONG":
            pnl = (close - position["entry"]) / position["entry"]
            balance *= (1 + pnl)
            trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": pnl})
            position = None

    return {
        "ok": True,
        "strategy": strategy,
        "trades": trades,
        "final_balance": round(balance, 2),
        "n_trades": len(trades),
    }


  















