# utils/backtest_utils.py
from __future__ import annotations
import pandas as pd
from typing import Dict, Any, Optional


from utils.indicators import prepare_indicators_for_backtest


def _calc_stress(trades: list[Dict[str, Any]], initial_balance: float, final_balance: float) -> Dict[str, Any]:
    if not trades:
        return {"max_drawdown_pct": 0.0, "max_win_pct": 0.0, "risk_reward_ratio": None}

    # ממירים לרווחים באחוזים
    pnls = [t["pnl"] for t in trades]
    max_win = max(pnls) * 100
    max_loss = min(pnls) * 100

    # risk/reward ratio
    rr = abs(max_win / max_loss) if max_loss < 0 else None

    # max drawdown
    equity = initial_balance
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity *= (1 + t["pnl"])
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)

    return {
        "max_drawdown_pct": round(max_dd * 100, 2),
        "max_win_pct": round(max_win, 2),
        "risk_reward_ratio": round(rr, 2) if rr else None,
    }


def run_backtest(
    df: pd.DataFrame,
    strategy: str = "ema_crossover",
    initial_balance: float = 1000.0,
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
                    "side": "LONG",
                    "entry": position["entry"],
                    "exit": close,
                    "pnl": pnl
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
                trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": pnl})
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
                trades.append({"side": "LONG", "entry": position["entry"], "exit": close, "pnl": pnl})
                position = None

    stress = _calc_stress(trades, initial_balance, balance)

    return {
        "ok": True,
        "strategy": strategy,
        "trades": trades,
        "final_balance": round(balance, 2),
        "profit_pct": round(((balance / initial_balance) - 1) * 100, 2),
        "n_trades": len(trades),
        "stress": stress,
    }




  















