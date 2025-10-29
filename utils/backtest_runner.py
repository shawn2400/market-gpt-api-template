from __future__ import annotations
import math
import pandas as pd
from typing import Dict, Any

try:
    from utils.indicators import prepare_indicators_for_backtest
except Exception:
    def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:  # fallback
        out = pd.DataFrame(index=df.index)
        out["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
        out["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
        return out

def run_backtest(df: pd.DataFrame, strategy: str = "ema_crossover", initial_balance: float = 1000.0) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"final_balance": initial_balance, "profit_pct": 0.0, "n_trades": 0, "stress": {"max_drawdown_pct": 0.0, "max_win_pct": 0.0, "risk_reward_ratio": None}}
    df = df.copy()
    if "close" not in df.columns:
        raise ValueError("DataFrame must include 'close' column")

    ind = prepare_indicators_for_backtest(df)
    for col in ind.columns:
        if col not in df.columns:
            df[col] = ind[col]

    balance = float(initial_balance)
    position_open = False
    entry_price = 0.0
    trades = 0
    max_drawdown = 0.0
    peak = balance

    for i in range(1, len(df)):
        row = df.iloc[i]
        ema21 = float(row.get("ema_21", float("nan")))
        ema50 = float(row.get("ema_50", float("nan")))
        close = float(row["close"])
        if math.isnan(ema21) or math.isnan(ema50):
            continue

        if strategy == "ema_crossover":
            if not position_open and ema21 > ema50:
                position_open = True
                entry_price = close
                trades += 1
            elif position_open and ema21 < ema50:
                balance *= (1.0 + (close - entry_price) / entry_price)
                position_open = False

        peak = max(peak, balance)
        dd = 1.0 - (balance / peak) if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)

    # סגירת פוזיציה פתוחה בסוף הסימולציה במחיר האחרון
    if position_open:
        last_close = float(df["close"].iloc[-1])
        balance *= (1.0 + (last_close - entry_price) / entry_price)
        peak = max(peak, balance)
        dd = 1.0 - (balance / peak) if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, dd)

    final_balance = balance
    profit_pct = ((final_balance - initial_balance) / initial_balance) * 100.0

    return {
        "final_balance": final_balance,
        "profit_pct": profit_pct,
        "n_trades": trades,
        "stress": {
            "max_drawdown_pct": max_drawdown * 100.0,
            "max_win_pct": max(0.0, profit_pct),
            "risk_reward_ratio": (profit_pct / (max_drawdown * 100.0)) if max_drawdown > 0 else None,
        }
    }

