# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Performance Heatmap - Win/loss tracking per market condition.
Dynamic auto-activation as trades complete.
"""

import os
import logging
from collections import defaultdict
from typing import Dict, Any, List
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_PERFORMANCE_HEATMAP = os.getenv("ENABLE_PERFORMANCE_HEATMAP", "1") == "1"


class PerformanceHeatmap:
    """
    Tracks and aggregates trading performance across different market conditions.
    Helps system learn which trading modes are most profitable.
    """
    
    def __init__(self):
        self.enabled = ENABLE_PERFORMANCE_HEATMAP
        self.data: Dict[str, List[float]] = defaultdict(list)
        self.total_trades = 0
        self.total_pnl = 0.0
    
    def update(self, mode: str, pnl: float) -> None:
        """
        Record a completed trade result.
        
        Args:
            mode: Market condition (e.g., "TRENDING_UP", "CHOPPY", "BREAKOUT")
            pnl: Trade PnL in USD
        """
        if not self.enabled or not mode:
            return
        
        self.data[mode].append(pnl)
        self.total_trades += 1
        self.total_pnl += pnl
        
        logger.debug(f"📊 Heatmap updated: {mode} → ${pnl:.2f}")
    
    def get_score(self, mode: str) -> float:
        """
        Get win-rate for a specific market mode (0.0-1.0).
        
        Args:
            mode: Market condition
        
        Returns:
            Win-rate as decimal (0.0 = all losses, 1.0 = all wins)
        """
        if mode not in self.data or not self.data[mode]:
            return 0.5  # Neutral if no data
        
        trades = self.data[mode]
        wins = len([p for p in trades if p > 0])
        total = len(trades)
        
        return round(wins / total if total > 0 else 0.5, 3)
    
    def get_avg_pnl(self, mode: str) -> float:
        """Get average PnL for a market mode."""
        if mode not in self.data or not self.data[mode]:
            return 0.0
        
        with suppress(Exception):
            import numpy as np
            return round(float(np.mean(self.data[mode])), 2)
        
        trades = self.data[mode]
        return round(sum(trades) / len(trades) if trades else 0.0, 2)
    
    def summary(self) -> Dict[str, Any]:
        """
        Get summary of all market modes and their performance.
        
        Returns:
            Dictionary with win-rates, trade counts, and PnL per mode
        """
        result = {}
        for mode, trades in self.data.items():
            if not trades:
                continue
            
            wins = len([p for p in trades if p > 0])
            losses = len([p for p in trades if p < 0])
            
            with suppress(Exception):
                import numpy as np
                avg_pnl = float(np.mean(trades))
                max_pnl = float(np.max(trades))
                min_pnl = float(np.min(trades))
            avg_pnl = sum(trades) / len(trades)
            max_pnl = max(trades)
            min_pnl = min(trades)
            
            result[mode] = {
                "win_rate": round(wins / len(trades) if trades else 0, 3),
                "trades": len(trades),
                "wins": wins,
                "losses": losses,
                "avg_pnl": round(avg_pnl, 2),
                "max_pnl": round(max_pnl, 2),
                "min_pnl": round(min_pnl, 2),
                "total_pnl": round(sum(trades), 2)
            }
        
        return result
    
    def get_best_mode(self) -> str:
        """Get market mode with highest win-rate."""
        if not self.data:
            return "UNKNOWN"
        
        best_mode = None
        best_score = -1
        
        for mode in self.data:
            score = self.get_score(mode)
            if score > best_score:
                best_score = score
                best_mode = mode
        
        return best_mode or "UNKNOWN"
    
    def get_worst_mode(self) -> str:
        """Get market mode with lowest win-rate."""
        if not self.data:
            return "UNKNOWN"
        
        worst_mode = None
        worst_score = 2.0
        
        for mode in self.data:
            score = self.get_score(mode)
            if score < worst_score:
                worst_score = score
                worst_mode = mode
        
        return worst_mode or "UNKNOWN"
    
    def reset(self) -> None:
        """Reset heatmap data."""
        self.data.clear()
        self.total_trades = 0
        self.total_pnl = 0.0
        logger.info("🔄 Performance heatmap reset")
    
    def export(self) -> Dict[str, Any]:
        """Export complete heatmap data."""
        return {
            "summary": self.summary(),
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 2),
            "best_mode": self.get_best_mode(),
            "worst_mode": self.get_worst_mode()
        }


# Global singleton
_heatmap = None


def get_performance_heatmap() -> PerformanceHeatmap:
    """Get or create global performance heatmap (singleton)."""
    global _heatmap
    if _heatmap is None:
        _heatmap = PerformanceHeatmap()
        if ENABLE_PERFORMANCE_HEATMAP:
            logger.info("✅ Performance Heatmap initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  Performance Heatmap disabled")
    return _heatmap
