# utils/pnl_summary.py
from __future__ import annotations
from typing import List, Dict, Any
from utils.trade_state import Trade
import statistics

def summarize_trades(trades: List[Trade]) -> Dict[str, Any]:
    """
    מחשב סיכום כולל: רווחים, הפסדים, Win Rate, ממוצע רווח, ממוצע הפסד.
    """
    wins = [t.realized_pnl for t in trades if t.realized_pnl > 0]
    losses = [t.realized_pnl for t in trades if t.realized_pnl < 0]
    total_pnl = sum(t.realized_pnl for t in trades)
    win_rate = (len(wins) / len(trades)) * 100.0 if trades else 0.0

    return {
        "total_trades": len(trades),
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "total_pnl": round(total_pnl, 4),
        "avg_win": round(statistics.mean(wins), 4) if wins else 0.0,
        "avg_loss": round(statistics.mean(losses), 4) if losses else 0.0,
    }

