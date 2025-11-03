# utils/monitors/live_health.py
"""
Live Health Monitor
===================
Real-time performance tracking with Win%, DD, and consecutive loss monitoring.
"""

from __future__ import annotations
import os
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("monitors.live_health")

@dataclass
class HealthStatus:
    """Current system health status"""
    ok: bool
    action: str  # "continue", "reduce_risk", "pause", "emergency_stop"
    reason: str
    metrics: Dict[str, Any]
    
def evaluate_live_health(
    metrics_7d: Dict[str, float],
    metrics_30d: Dict[str, float],
    consec_sl: int,
    dd_7d: float,
) -> HealthStatus:
    """
    Evaluate system health and determine if circuit breakers should trigger.
    
    Args:
        metrics_7d: 7-day metrics (winrate, rr, etc.)
        metrics_30d: 30-day metrics
        consec_sl: Consecutive stop-losses
        dd_7d: 7-day drawdown percentage
        
    Returns:
        HealthStatus with action recommendation
    """
    # Load thresholds from ENV
    breaker_winrate_min = float(os.getenv("BREAKER_WINRATE_30D_MIN", "40"))
    breaker_dd_max = float(os.getenv("BREAKER_DD_7D_MAX", "8"))
    breaker_consec_sl_max = int(os.getenv("BREAKER_CONSEC_SL_MAX", "4"))
    
    winrate_30d = metrics_30d.get("winrate", 0.0)
    
    # Check multiple conditions
    triggers = []
    
    if winrate_30d < breaker_winrate_min:
        triggers.append(f"winrate_30d={winrate_30d:.1f}%<{breaker_winrate_min}%")
    
    if dd_7d > breaker_dd_max:
        triggers.append(f"dd_7d={dd_7d:.1f}%>{breaker_dd_max}%")
    
    if consec_sl >= breaker_consec_sl_max:
        triggers.append(f"consec_sl={consec_sl}>={breaker_consec_sl_max}")
    
    # Determine action
    if not triggers:
        return HealthStatus(
            ok=True,
            action="continue",
            reason="All metrics within acceptable ranges",
            metrics={"winrate_30d": winrate_30d, "dd_7d": dd_7d, "consec_sl": consec_sl},
        )
    
    # Multiple triggers = emergency
    if len(triggers) >= 2:
        action = "emergency_stop"
        reason = f"MULTIPLE BREAKERS: {', '.join(triggers)}"
    elif dd_7d > breaker_dd_max * 1.5:
        action = "emergency_stop"
        reason = f"EXTREME DRAWDOWN: {', '.join(triggers)}"
    elif consec_sl >= breaker_consec_sl_max:
        action = "pause"
        reason = f"CONSECUTIVE LOSSES: {', '.join(triggers)}"
    else:
        action = "reduce_risk"
        reason = f"WARNING: {', '.join(triggers)}"
    
    logger.warning(f"Health check: {action.upper()} - {reason}")
    
    return HealthStatus(
        ok=False,
        action=action,
        reason=reason,
        metrics={"winrate_30d": winrate_30d, "dd_7d": dd_7d, "consec_sl": consec_sl},
    )

def calculate_recent_metrics(
    trades: List[Dict[str, Any]],
    days: int = 30,
) -> Dict[str, float]:
    """
    Calculate metrics for recent N days.
    
    Args:
        trades: List of recent trades
        days: Number of days to analyze
        
    Returns:
        Dict with winrate, avg_rr, total_trades, etc.
    """
    if not trades:
        return {"winrate": 0.0, "avg_rr": 0.0, "total_trades": 0}
    
    # Filter trades by date
    cutoff = datetime.now() - timedelta(days=days)
    recent_trades = [
        t for t in trades
        if _parse_timestamp(t.get("timestamp")) >= cutoff
    ]
    
    if not recent_trades:
        return {"winrate": 0.0, "avg_rr": 0.0, "total_trades": 0}
    
    total = len(recent_trades)
    wins = sum(1 for t in recent_trades if _is_win(t))
    
    winrate = (wins / total * 100.0) if total > 0 else 0.0
    
    # Calculate avg R:R
    win_trades = [t for t in recent_trades if _is_win(t)]
    loss_trades = [t for t in recent_trades if not _is_win(t)]
    
    avg_win = sum(abs(_get_pnl_pct(t)) for t in win_trades) / len(win_trades) if win_trades else 0.0
    avg_loss = sum(abs(_get_pnl_pct(t)) for t in loss_trades) / len(loss_trades) if loss_trades else 1.0
    
    avg_rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    return {
        "winrate": round(winrate, 2),
        "avg_rr": round(avg_rr, 2),
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
    }

def _parse_timestamp(ts: Any) -> datetime:
    """Parse timestamp to datetime"""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except:
            pass
    return datetime.min

def _is_win(trade: Dict[str, Any]) -> bool:
    """Check if trade is a win"""
    status = str(trade.get("status", "")).lower()
    if status in {"win", "success", "closed_tp", "tp"}:
        return True
    pnl = trade.get("pnl") or trade.get("pnl_pct") or 0.0
    return float(pnl) > 0

def _get_pnl_pct(trade: Dict[str, Any]) -> float:
    """Extract PnL percentage"""
    pnl_pct = trade.get("pnl_pct")
    if pnl_pct is not None:
        return float(pnl_pct)
    return float(trade.get("pnl", 0.0))
