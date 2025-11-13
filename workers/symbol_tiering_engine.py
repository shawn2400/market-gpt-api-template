"""
Symbol Tiering Engine - Performance-Based Symbol Classification
================================================================
Classifies trading symbols into tiers (A/B/C) based on performance
with automatic promotion/demotion.

Tier Criteria:
- Tier A: Win rate ≥ 60%, avg profit > avg loss, 5+ trades
- Tier B: Win rate ≥ 45%, avg profit ≥ avg loss, 3+ trades  
- Tier C: All others or insufficient data

Author: AlgoGPT Team
"""

import logging
import os
import json
from typing import Dict, List, Tuple
from datetime import datetime
from enum import Enum

from utils.performance_tracker import get_performance_tracker

LOGGER = logging.getLogger("symbol_tiering")


class SymbolTier(Enum):
    """Symbol tier levels"""
    A = "A"  # Top performers
    B = "B"  # Average performers
    C = "C"  # Poor performers / untested


class SymbolTieringEngine:
    """
    Classifies symbols into performance tiers and manages tier changes.
    
    Benefits:
    - Tier A symbols get higher allocation and relaxed thresholds
    - Tier C symbols get reduced allocation or blacklist consideration
    - Auto-adjustment based on recent performance
    """
    
    def __init__(self):
        self.logger = LOGGER
        self.performance_tracker = get_performance_tracker()
        
        self.tiers_file = os.getenv(
            "SYMBOL_TIERS_FILE",
            "/tmp/symbol_tiers.json"
        )
        
        self.current_tiers: Dict[str, str] = {}
        self._load_tiers()
    
    def calculate_all_tiers(self, days: int = 30, min_trades: int = 3) -> Dict[str, Dict]:
        """
        Calculate tier assignments for all symbols with sufficient data.
        
        Args:
            days: Lookback period
            min_trades: Minimum trades required for tier assignment
            
        Returns:
            Dict mapping symbol -> tier info
        """
        self.logger.info(f"📊 Calculating symbol tiers (last {days} days)")
        
        all_symbol_stats = self.performance_tracker.get_all_symbol_stats(
            days=days,
            min_trades=min_trades
        )
        
        tier_assignments = {}
        tier_counts = {"A": 0, "B": 0, "C": 0}
        
        for symbol, stats in all_symbol_stats.items():
            tier, score = self._calculate_tier(stats)
            
            tier_assignments[symbol] = {
                "tier": tier.value,
                "score": score,
                "win_rate": stats["win_rate"],
                "total_trades": stats["total_trades"],
                "avg_profit": stats["avg_profit"],
                "avg_loss": stats["avg_loss"],
                "recent_trend": stats["recent_trend"]
            }
            
            tier_counts[tier.value] += 1
        
        # Save tier assignments
        self.current_tiers = {
            symbol: info["tier"]
            for symbol, info in tier_assignments.items()
        }
        self._save_tiers()
        
        self.logger.info(
            f"✅ Tiers calculated: "
            f"A={tier_counts['A']}, B={tier_counts['B']}, C={tier_counts['C']}"
        )
        
        return tier_assignments
    
    def _calculate_tier(self, stats: Dict) -> Tuple[SymbolTier, float]:
        """
        Calculate tier for a symbol based on performance metrics.
        
        Scoring (0-10):
        - Win rate: 40% weight
        - Profit/Loss ratio: 30% weight
        - Recent trend: 20% weight
        - Volume (total trades): 10% weight
        
        Returns:
            (tier, score) tuple
        """
        win_rate = stats["win_rate"]
        avg_profit = stats["avg_profit"]
        avg_loss = abs(stats["avg_loss"]) if stats["avg_loss"] != 0 else 0.01
        total_trades = stats["total_trades"]
        recent_trend = stats["recent_trend"]
        
        # Component scores (0-10)
        win_rate_score = min(win_rate / 10, 10.0)  # 100% win rate = 10 points
        
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
        pl_ratio_score = min(profit_loss_ratio * 3, 10.0)  # 3.33+ ratio = 10 points
        
        trend_scores = {
            "improving": 10.0,
            "stable": 6.0,
            "declining": 2.0,
            "insufficient_data": 5.0,
            "unknown": 5.0
        }
        trend_score = trend_scores.get(recent_trend, 5.0)
        
        volume_score = min(total_trades / 2, 10.0)  # 20+ trades = 10 points
        
        # Weighted total score
        total_score = (
            win_rate_score * 0.4 +
            pl_ratio_score * 0.3 +
            trend_score * 0.2 +
            volume_score * 0.1
        )
        
        # Determine tier based on score
        if total_score >= 7.5 and win_rate >= 60:
            return (SymbolTier.A, round(total_score, 2))
        elif total_score >= 5.0 and win_rate >= 45:
            return (SymbolTier.B, round(total_score, 2))
        else:
            return (SymbolTier.C, round(total_score, 2))
    
    def get_tier(self, symbol: str) -> str:
        """Get current tier for a symbol (returns 'C' if unknown)"""
        return self.current_tiers.get(symbol, "C")
    
    def get_tier_allocation_multiplier(self, symbol: str) -> float:
        """
        Get budget allocation multiplier based on tier.
        
        Returns:
            1.5 for Tier A, 1.0 for Tier B, 0.7 for Tier C
        """
        tier = self.get_tier(symbol)
        
        multipliers = {
            "A": 1.5,  # 50% more budget
            "B": 1.0,  # Normal budget
            "C": 0.7   # 30% less budget
        }
        
        return multipliers.get(tier, 0.7)
    
    def get_tier_symbols(self, tier: str) -> List[str]:
        """Get all symbols in a specific tier"""
        return [
            symbol for symbol, t in self.current_tiers.items()
            if t == tier
        ]
    
    def detect_tier_changes(self, new_tiers: Dict[str, Dict]) -> List[Dict]:
        """
        Detect symbols that changed tiers (promotions/demotions).
        
        Returns:
            List of tier change events
        """
        changes = []
        
        for symbol, info in new_tiers.items():
            new_tier = info["tier"]
            old_tier = self.current_tiers.get(symbol, "C")
            
            if old_tier != new_tier:
                change_type = "promoted" if self._tier_rank(new_tier) > self._tier_rank(old_tier) else "demoted"
                
                changes.append({
                    "symbol": symbol,
                    "old_tier": old_tier,
                    "new_tier": new_tier,
                    "change_type": change_type,
                    "score": info["score"],
                    "win_rate": info["win_rate"]
                })
        
        return changes
    
    def _tier_rank(self, tier: str) -> int:
        """Get numerical rank of tier (higher = better)"""
        ranks = {"A": 3, "B": 2, "C": 1}
        return ranks.get(tier, 0)
    
    def _save_tiers(self):
        """Save tier assignments to disk"""
        try:
            data = {
                "tiers": self.current_tiers,
                "updated_at": datetime.utcnow().isoformat()
            }
            with open(self.tiers_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save tier data: {e}")
    
    def _load_tiers(self):
        """Load tier assignments from disk"""
        try:
            if os.path.exists(self.tiers_file):
                with open(self.tiers_file, "r") as f:
                    data = json.load(f)
                    self.current_tiers = data.get("tiers", {})
                    self.logger.info(f"Loaded {len(self.current_tiers)} symbol tiers")
        except Exception as e:
            self.logger.warning(f"Failed to load tier data: {e}")
            self.current_tiers = {}


def update_symbol_tiers(days: int = 30) -> Dict:
    """
    Convenience function to update all symbol tiers.
    
    Args:
        days: Lookback period
        
    Returns:
        Updated tier assignments
    """
    engine = SymbolTieringEngine()
    return engine.calculate_all_tiers(days=days)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tiers = update_symbol_tiers(days=30)
    print(f"Tier Assignments: {len(tiers)} symbols classified")
