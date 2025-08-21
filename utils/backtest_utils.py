# utils/backtest_utils.py
from __future__ import annotations
"""
מודול Backtester – אחראי על הרצת backtest לאסטרטגיות.
משמש על ידי routes/backtest.py.
"""
import pandas as pd
from typing import Dict, Any, Optional, List

from utils.indicators import prepare_indicators_for_backtest


def run_backtest(
    df: pd.DataFrame,
    strategy: str = "ema_crossover",
    initial_balance: float = 1000.0,
    leverage: int = 1,
    stress_mode: bool = False,
) -> Dict[str, Any]:
    """
    מבצע Backtest על DataFrame נתון עם אסטרטגיה פשוטה.
    df חייב להכיל עמודות: [open, high, low, close, volume]
    """
    if df is None or df.empty:
        return {"ok": False, "error": "empty dataframe"}

    df = prepare_indicators_for_backtest(df)

    trades: List[Dict[str, Any]] = []
    balance = initial_balance
    position: Optional[Dict[str, Any]] = None
    equity_curve: List[float] = [initial_balance]

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
                pnl = ((close - position["entry"]) / position["entry"]) * leverage
                balance *= (1 + pnl)
                trades.append({
                    "side": "LONG",
                    "entry": position["entry"],
                    "exit": close,
                    "pnl_pct": round(pnl * 100, 2)
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
                pnl = ((close - position["entry"]) / position["entry"]) * leverage
                balance *= (1 + pnl)
                trades.append({
                    "side": "LONG",
                    "entry": position["entry"],
                    "exit": close,
                    "pnl_pct": round(pnl * 100, 2)
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
                pnl = ((close - position["entry"]) / position["entry"]) * leverage
                balance *= (1 + pnl)
                trades.append({
                    "side": "LONG",
                    "entry": position["entry"],
                    "exit": close,
                    "pnl_pct": round(pnl * 100, 2)
                })
                position = None

        equity_curve.append(balance)

    # =========================
    # Stress Mode
    # =========================
    stress: Dict[str, Any] = {}
    if stress_mode and equity_curve:
        peak = equity_curve[0]
        max_dd = 0.0
        max_win = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
            gain = (eq / initial_balance - 1)
            max_win = max(max_win, gain)
        risk_reward = (max_win * 100 / max_dd * 100) if max_dd > 0 else None
        stress = {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "max_win_pct": round(max_win * 100, 2),
            "risk_reward_ratio": round(risk_reward, 2) if risk_reward else None
        }

    return {
        "ok": True,
        "strategy": strategy,
        "trades": trades,
        "final_balance": round(balance, 2),
        "profit_pct": round(((balance / initial_balance) - 1) * 100, 2),
        "n_trades": len(trades),
        "leverage": leverage,
        "stress": stress if stress_mode else None,
        # ❗ כדי למנוע ResponseTooLarge, לא נחזיר את כל ה־candles כאן.
        "candles": []  
    }


  















