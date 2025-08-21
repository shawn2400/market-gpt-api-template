# utils/backtest_utils.py
from __future__ import annotations
import pandas as pd
from typing import Dict, Any, Optional

from utils.indicators import prepare_indicators_for_backtest


def run_backtest(
    df: pd.DataFrame,
    strategy: str = "ema_crossover",
    initial_balance: float = 1000.0,
    max_trades: int = 200,   # ✅ חיתוך קשיח כדי למנוע תגובות ענק
) -> Dict[str, Any]:
    """
    מבצע Backtest על DataFrame נתון עם אסטרטגיה פשוטה.
    df חייב להכיל עמודות: [open, high, low, close, volume]
    """
    if df is None or df.empty:
        return {"ok": False, "error": "empty dataframe"}

    df = prepare_indicators_for_backtest(df)

    trades = []
    balance = initial_balance
    position: Optional[Dict[str, Any]] = None

    for i in range(50, len(df)):
        row = df.iloc[i]
        close = float(row["close"])

        # =========================
        # EMA Crossover Strategy
        # =========================
        if strategy == "ema_crossover":
            ema21 = float(row["ema21"])
            ema50 = float(row["ema50"])

            if ema21 > ema50 and not position:
                position = {"side": "LONG", "entry": close, "index": i}
            elif ema21 < ema50 and position and position["side"] == "LONG":
                pnl = (close - position["entry"]) / position["entry"]
                balance *= (1 + pnl)
                trades.append({
                    "side": "LONG", "entry": position["entry"], "exit": close, "pnl": round(pnl, 4)
                })
                position = None

        # =========================
        # MACD Crossover Strategy
        # =========================
        elif strategy == "macd_crossover":
            macd_line = float(row.get("macd", 0))
            macd_signal = float(row.get("macd_signal", 0))

            if macd_line > macd_signal and not position:
                position = {"side": "LONG", "entry": close, "index": i}
            elif macd_line < macd_signal and position and position["side"] == "LONG":
                pnl = (close - position["entry"]) / position["entry"]
                balance *= (1 + pnl)
                trades.append({
                    "side": "LONG", "entry": position["entry"], "exit": close, "pnl": round(pnl, 4)
                })
                position = None

        # =========================
        # Bollinger Bands Strategy
        # =========================
        elif strategy == "bollinger":
            bb_lower = float(row.get("bb_lower", 0))
            bb_upper = float(row.get("bb_upper", 0))

            if close < bb_lower and not position:
                position = {"side": "LONG", "entry": close, "index": i}
            elif close > bb_upper and position and position["side"] == "LONG":
                pnl = (close - position["entry"]) / position["entry"]
                balance *= (1 + pnl)
                trades.append({
                    "side": "LONG", "entry": position["entry"], "exit": close, "pnl": round(pnl, 4)
                })
                position = None

    # ✅ חיתוך ל־max_trades כדי למנוע ResponseTooLargeError
    trades_trimmed = trades[-max_trades:] if len(trades) > max_trades else trades

    return {
        "ok": True,
        "strategy": strategy,
        "summary": {
            "n_trades_total": len(trades),
            "n_trades_returned": len(trades_trimmed),
            "final_balance": round(balance, 2),
            "profit_pct": round(((balance / initial_balance) - 1) * 100, 2),
        },
        "trades": trades_trimmed,
    }


  















