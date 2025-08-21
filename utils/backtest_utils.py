# utils/backtest_utils.py
from __future__ import annotations
import pandas as pd
from typing import Dict, Any, Optional
from utils.indicators import prepare_indicators_for_backtest


def run_backtest(
    df: pd.DataFrame,
    strategy: str = "ema_crossover",
    initial_balance: float = 1000.0,
    fee_rate: float = 0.0004,     # 0.04% עמלת Binance
    leverage: int = 1,            # מינוף – ברירת מחדל 1×
    stress_mode: bool = False,    # מצב אגרסיבי
) -> Dict[str, Any]:
    """
    Backtest עם תמיכה ב-LONG/SHORT, מינוף ו-Stress Mode.
    df חייב לכלול: [open, high, low, close, volume].
    אסטרטגיות: ema_crossover | macd_crossover | bollinger
    """

    if df is None or df.empty:
        return {"ok": False, "error": "empty dataframe"}

    df = prepare_indicators_for_backtest(df)

    trades = []
    balance = initial_balance
    position: Optional[Dict[str, Any]] = None

    # מגביל מינוף ל־100 מקסימום כדי לא לעוף
    lev = max(1, min(leverage, 100))

    for i in range(50, len(df)):
        row = df.iloc[i]
        close = float(row["close"])

        # =============== EMA CROSSOVER ===============
        if strategy == "ema_crossover":
            ema21 = float(row["ema21"])
            ema50 = float(row["ema50"])

            if ema21 > ema50 and not position:
                position = {"side": "LONG", "entry": close}
            elif ema21 < ema50 and not position:
                position = {"side": "SHORT", "entry": close}

            elif ema21 < ema50 and position and position["side"] == "LONG":
                pnl = (close - position["entry"]) / position["entry"]
                pnl = pnl * lev - fee_rate * 2
                balance *= (1 + pnl)
                trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": round(pnl, 5)})
                position = None

            elif ema21 > ema50 and position and position["side"] == "SHORT":
                pnl = (position["entry"] - close) / position["entry"]
                pnl = pnl * lev - fee_rate * 2
                balance *= (1 + pnl)
                trades.append({"side": "SHORT", "entry": position["entry"], "exit": close, "pnl": round(pnl, 5)})
                position = None

        # =============== MACD CROSSOVER ===============
        elif strategy == "macd_crossover":
            macd_line = float(row.get("macd", 0))
            macd_signal = float(row.get("macd_signal", 0))

            if macd_line > macd_signal and not position:
                position = {"side": "LONG", "entry": close}
            elif macd_line < macd_signal and not position:
                position = {"side": "SHORT", "entry": close}

            elif macd_line < macd_signal and position and position["side"] == "LONG":
                pnl = (close - position["entry"]) / position["entry"]
                pnl = pnl * lev - fee_rate * 2
                balance *= (1 + pnl)
                trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": round(pnl, 5)})
                position = None

            elif macd_line > macd_signal and position and position["side"] == "SHORT":
                pnl = (position["entry"] - close) / position["entry"]
                pnl = pnl * lev - fee_rate * 2
                balance *= (1 + pnl)
                trades.append({"side": "SHORT", "entry": position["entry"], "exit": close, "pnl": round(pnl, 5)})
                position = None

        # =============== BOLLINGER ===============
        elif strategy == "bollinger":
            bb_lower = float(row.get("bb_lower", 0))
            bb_upper = float(row.get("bb_upper", 0))

            if close < bb_lower and not position:
                position = {"side": "LONG", "entry": close}
            elif close > bb_upper and not position:
                position = {"side": "SHORT", "entry": close}

            elif close > bb_upper and position and position["side"] == "LONG":
                pnl = (close - position["entry"]) / position["entry"]
                pnl = pnl * lev - fee_rate * 2
                balance *= (1 + pnl)
                trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": round(pnl, 5)})
                position = None

            elif close < bb_lower and position and position["side"] == "SHORT":
                pnl = (position["entry"] - close) / position["entry"]
                pnl = pnl * lev - fee_rate * 2
                balance *= (1 + pnl)
                trades.append({"side": "SHORT", "entry": position["entry"], "exit": close, "pnl": round(pnl, 5)})
                position = None

    # =======================
    # Stress Mode
    # =======================
    if stress_mode:
        # סימולציה עם drawdown קיצוני
        worst_trade = min([t["pnl"] for t in trades], default=0)
        best_trade = max([t["pnl"] for t in trades], default=0)
        stress_info = {
            "max_drawdown_pct": round(worst_trade * 100, 2),
            "max_win_pct": round(best_trade * 100, 2),
            "risk_reward_ratio": round(abs(best_trade / worst_trade), 2) if worst_trade < 0 else None
        }
    else:
        stress_info = {}

    return {
        "ok": True,
        "strategy": strategy,
        "leverage": lev,
        "final_balance": round(balance, 2),
        "profit_pct": round(((balance / initial_balance) - 1) * 100, 2),
        "n_trades": len(trades),
        "trades": trades,
        "stress": stress_info,
    }


  















