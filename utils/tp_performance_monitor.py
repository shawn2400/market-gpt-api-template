# -*- coding: utf-8 -*-
# utils/tp_performance_monitor.py
"""
Multi-Target TP Performance Monitoring System
Tracks effectiveness of dynamic exit percentages and TP levels
"""
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("algogpt.tp_monitor")


@dataclass
class TPPerformanceMetrics:
    """Performance metrics for Multi-Target TP system"""
    total_trades: int
    tp1_hits: int
    tp2_hits: int
    tp3_hits: int
    tp1_pnl: float
    tp2_pnl: float
    tp3_pnl: float
    avg_tp1_percent: float
    avg_tp2_percent: float
    avg_tp3_percent: float
    front_loaded_count: int
    back_loaded_count: int
    balanced_count: int
    
    def __repr__(self):
        return (
            f"TPMetrics(total={self.total_trades}, "
            f"hits=[{self.tp1_hits}, {self.tp2_hits}, {self.tp3_hits}], "
            f"pnl=[${self.tp1_pnl:.2f}, ${self.tp2_pnl:.2f}, ${self.tp3_pnl:.2f}])"
        )


class TPPerformanceMonitor:
    """
    Monitors Multi-Target TP performance in real-time.
    Tracks:
    - Exit percentages used (front-loaded vs back-loaded)
    - Hit rates per TP level
    - PnL distribution across levels
    - Effectiveness by strategy/regime/volatility
    """
    
    def __init__(self):
        self.logger = logger
        self._metrics_cache: Dict[str, TPPerformanceMetrics] = {}
        logger.info("📊 TP Performance Monitor initialized")
    
    def log_tp_allocation(
        self,
        symbol: str,
        strategy: str,
        regime: str,
        volatility: float,
        tp1_percent: float,
        tp2_percent: float,
        tp3_percent: float,
        trade_id: Optional[str] = None
    ) -> None:
        """
        Log TP exit percentage allocation for a new trade.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy type
            regime: Market regime
            volatility: ATR percentage
            tp1_percent: TP1 exit percentage (0.0-1.0)
            tp2_percent: TP2 exit percentage (0.0-1.0)
            tp3_percent: TP3 exit percentage (0.0-1.0)
            trade_id: Optional trade ID for tracking
        """
        # Classify profile
        profile_type = self._classify_profile(tp1_percent, tp2_percent, tp3_percent)
        
        # Log to console (database logging disabled - no supabase_client)
        logger.debug(
            f"✅ TP allocation: {symbol} {strategy} → "
            f"{profile_type} [{tp1_percent*100:.0f}%, {tp2_percent*100:.0f}%, {tp3_percent*100:.0f}%]"
        )
    
    def log_tp_hit(
        self,
        symbol: str,
        trade_id: str,
        tp_level: int,
        pnl: float,
        exit_percent: float
    ) -> None:
        """
        Log when a TP level is hit.
        
        Args:
            symbol: Trading symbol
            trade_id: Trade ID
            tp_level: TP level (1, 2, or 3)
            pnl: Profit/loss amount
            exit_percent: Percentage of position exited
        """
        # Log to console (database logging disabled - no supabase_client)
        logger.info(f"✅ TP{tp_level} hit: {symbol} (${pnl:.2f}, {exit_percent*100:.0f}% exit)")
    
    def get_metrics(self, lookback_hours: int = 24) -> TPPerformanceMetrics:
        """
        Get performance metrics for last N hours.
        
        Args:
            lookback_hours: How many hours to look back
            
        Returns:
            TPPerformanceMetrics object with aggregated data
        """
        try:
            # Database logging disabled - return default metrics
            return self._get_default_metrics()
            
            # Aggregate metrics
            total_trades = len(allocations.data) if allocations.data else 0
            
            tp1_hits = sum(1 for h in (hits.data or []) if h["tp_level"] == 1)
            tp2_hits = sum(1 for h in (hits.data or []) if h["tp_level"] == 2)
            tp3_hits = sum(1 for h in (hits.data or []) if h["tp_level"] == 3)
            
            tp1_pnl = sum(h["pnl"] for h in (hits.data or []) if h["tp_level"] == 1)
            tp2_pnl = sum(h["pnl"] for h in (hits.data or []) if h["tp_level"] == 2)
            tp3_pnl = sum(h["pnl"] for h in (hits.data or []) if h["tp_level"] == 3)
            
            # Average percentages
            if total_trades > 0:
                avg_tp1 = sum(a["tp1_percent"] for a in allocations.data) / total_trades
                avg_tp2 = sum(a["tp2_percent"] for a in allocations.data) / total_trades
                avg_tp3 = sum(a["tp3_percent"] for a in allocations.data) / total_trades
            else:
                avg_tp1 = avg_tp2 = avg_tp3 = 0.0
            
            # Count profiles
            front_loaded = sum(1 for a in (allocations.data or []) if a.get("profile_type") == "front_loaded")
            back_loaded = sum(1 for a in (allocations.data or []) if a.get("profile_type") == "back_loaded")
            balanced = sum(1 for a in (allocations.data or []) if a.get("profile_type") == "balanced")
            
            return TPPerformanceMetrics(
                total_trades=total_trades,
                tp1_hits=tp1_hits,
                tp2_hits=tp2_hits,
                tp3_hits=tp3_hits,
                tp1_pnl=tp1_pnl,
                tp2_pnl=tp2_pnl,
                tp3_pnl=tp3_pnl,
                avg_tp1_percent=avg_tp1,
                avg_tp2_percent=avg_tp2,
                avg_tp3_percent=avg_tp3,
                front_loaded_count=front_loaded,
                back_loaded_count=back_loaded,
                balanced_count=balanced
            )
        except Exception as e:
            logger.warning(f"Failed to get TP metrics: {e}")
            return self._get_default_metrics()
    
    def get_summary_report(self, lookback_hours: int = 24) -> str:
        """
        Generate human-readable summary report.
        
        Args:
            lookback_hours: How many hours to look back
            
        Returns:
            Formatted report string
        """
        metrics = self.get_metrics(lookback_hours)
        
        lines = [
            f"📊 **TP Performance Report** (Last {lookback_hours}h)",
            f"",
            f"**Trades:** {metrics.total_trades} total",
            f"  - Front-loaded: {metrics.front_loaded_count} ({metrics.front_loaded_count/max(1,metrics.total_trades)*100:.0f}%)",
            f"  - Back-loaded: {metrics.back_loaded_count} ({metrics.back_loaded_count/max(1,metrics.total_trades)*100:.0f}%)",
            f"  - Balanced: {metrics.balanced_count} ({metrics.balanced_count/max(1,metrics.total_trades)*100:.0f}%)",
            f"",
            f"**TP Levels Hit:**",
            f"  - TP1: {metrics.tp1_hits} hits (${metrics.tp1_pnl:.2f} PnL, avg {metrics.avg_tp1_percent*100:.0f}% exit)",
            f"  - TP2: {metrics.tp2_hits} hits (${metrics.tp2_pnl:.2f} PnL, avg {metrics.avg_tp2_percent*100:.0f}% exit)",
            f"  - TP3: {metrics.tp3_hits} hits (${metrics.tp3_pnl:.2f} PnL, avg {metrics.avg_tp3_percent*100:.0f}% exit)",
            f"",
            f"**Total PnL:** ${metrics.tp1_pnl + metrics.tp2_pnl + metrics.tp3_pnl:.2f}"
        ]
        
        return "\n".join(lines)
    
    def _classify_profile(self, tp1: float, tp2: float, tp3: float) -> str:
        """Classify TP profile as front-loaded, back-loaded, or balanced"""
        if tp1 >= 0.38:  # Front-loaded (TP1 ≥ 38%)
            return "front_loaded"
        elif tp3 >= 0.38:  # Back-loaded (TP3 ≥ 38%)
            return "back_loaded"
        else:
            return "balanced"
    
    def _get_default_metrics(self) -> TPPerformanceMetrics:
        """Return default metrics when database is unavailable"""
        return TPPerformanceMetrics(
            total_trades=0,
            tp1_hits=0,
            tp2_hits=0,
            tp3_hits=0,
            tp1_pnl=0.0,
            tp2_pnl=0.0,
            tp3_pnl=0.0,
            avg_tp1_percent=0.30,
            avg_tp2_percent=0.40,
            avg_tp3_percent=0.30,
            front_loaded_count=0,
            back_loaded_count=0,
            balanced_count=0
        )


# Singleton instance
_tp_performance_monitor: Optional[TPPerformanceMonitor] = None

def get_tp_performance_monitor() -> TPPerformanceMonitor:
    """Get singleton TPPerformanceMonitor instance"""
    global _tp_performance_monitor
    if _tp_performance_monitor is None:
        _tp_performance_monitor = TPPerformanceMonitor()
    return _tp_performance_monitor
