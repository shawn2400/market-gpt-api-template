# utils/validation/metrics.py
"""
Trading Metrics Calculator
===========================
Comprehensive performance metrics for backtest validation.
"""

from __future__ import annotations
from typing import Dict, Any, List
from dataclasses import dataclass
import logging

logger = logging.getLogger("validation.metrics")

@dataclass
class MetricsResult:
    """Structured metrics result"""
    winrate: float
    avg_rr: float
    expectancy: float
    max_dd: float
    sharpe: float
    total_trades: int
    wins: int
    losses: int
    
def calculate_metrics(trades: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Calculate comprehensive trading metrics.
    
    Args:
        trades: List of trade dictionaries with keys:
            - status: "win" or "loss"
            - pnl: Profit/loss amount
            - pnl_pct: Profit/loss percentage
            
    Returns:
        Dict with metrics: winrate, avg_rr, expectancy, max_dd, sharpe, etc.
    """
    if not trades:
        return {
            "winrate": 0.0,
            "avg_rr": 0.0,
            "expectancy": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
        }
    
    total = len(trades)
    wins = sum(1 for t in trades if _is_win(t))
    losses = total - wins
    
    winrate = (wins / total * 100) if total > 0 else 0.0
    
    # Calculate average R:R
    win_trades = [t for t in trades if _is_win(t)]
    loss_trades = [t for t in trades if not _is_win(t)]
    
    avg_win = sum(_get_pnl_pct(t) for t in win_trades) / len(win_trades) if win_trades else 0.0
    avg_loss = abs(sum(_get_pnl_pct(t) for t in loss_trades) / len(loss_trades)) if loss_trades else 1.0
    
    avg_rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # Expectancy
    win_prob = winrate / 100.0
    loss_prob = 1.0 - win_prob
    expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)
    
    # Max drawdown
    max_dd = _calculate_max_drawdown(trades)
    
    # Sharpe ratio approximation
    returns = [_get_pnl_pct(t) for t in trades]
    mean_return = sum(returns) / len(returns) if returns else 0.0
    std_return = _std_dev(returns) if len(returns) > 1 else 1.0
    sharpe = (mean_return / std_return) if std_return > 0 else 0.0
    
    return {
        "winrate": round(winrate, 2),
        "avg_rr": round(avg_rr, 2),
        "expectancy": round(expectancy, 2),
        "max_dd": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
    }

def _is_win(trade: Dict[str, Any]) -> bool:
    """Check if trade is a win"""
    status = str(trade.get("status", "")).lower()
    if status in {"win", "success", "closed_tp", "tp"}:
        return True
    
    pnl = trade.get("pnl") or trade.get("pnl_pct") or 0.0
    return float(pnl) > 0

def _get_pnl_pct(trade: Dict[str, Any]) -> float:
    """Extract PnL percentage from trade"""
    pnl_pct = trade.get("pnl_pct")
    if pnl_pct is not None:
        return float(pnl_pct)
    
    pnl = trade.get("pnl", 0.0)
    return float(pnl)

def _calculate_max_drawdown(trades: List[Dict[str, Any]]) -> float:
    """Calculate maximum drawdown percentage"""
    if not trades:
        return 0.0
    
    equity = 10000.0  # Starting equity
    peak = equity
    max_dd = 0.0
    
    for trade in trades:
        pnl_pct = _get_pnl_pct(trade)
        equity *= (1 + pnl_pct / 100.0)
        
        if equity > peak:
            peak = equity
        
        dd = ((peak - equity) / peak) * 100.0
        if dd > max_dd:
            max_dd = dd
    
    return max_dd

def _std_dev(values: List[float]) -> float:
    """Calculate standard deviation"""
    if len(values) < 2:
        return 0.0
    
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return variance ** 0.5
